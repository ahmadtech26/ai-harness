"""Staff admin API (spec C.4) at /admin on the legal-search app, behind SecretGuard like the MCP endpoint.
The fork proxies it from /api/iqraa/admin/library/* and names the staff member in X-Iqraa-Staff, which is
recorded as "who" on settings changes and flag clears. Holding the shared secret already lets a caller act
as any user over MCP, so this adds no new trust boundary.

    GET  /admin/flags?status=open|cleared|all     flags with evidence (default open)
    POST /admin/flags/{user_id}/clear             {reason?}; 404 without an open flag
    GET  /admin/guard-settings                    current settings, updated_by, updated_at
    PUT  /admin/guard-settings                    {settings: {...changes}, reason}
    GET  /admin/guard-settings/history            who, when, why, previous values (newest first)
    POST /admin/guard-settings/simulate           {settings?: {...candidate changes}, days?}; writes nothing
    GET  /admin/telemetry?days=N                  per-user-day distributions, users, open flags

Every 400 is {"error": <category>, "rule": <the rule>, "message": ...}: category `invalid_settings` for a
settings value (the rule is the validation rule it breaks), `bad_request` for the rest (staff_required,
reason_required, bad_json, bad_days, bad_status, bad_request, too_many_events). Simulation and telemetry read
at most events.MAX_EVENTS events; loading them (on a connection of their own) and computing both run in
worker threads, so retrievals keep being served meanwhile.
"""

import json
import re
from datetime import timedelta

import anyio
from psycopg_pool import AsyncConnectionPool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from legal_search import events, flags, guard_settings
from legal_search.guard_settings import SettingsCache, SettingsError
from legal_search.telemetry import MAX_DAYS, simulate, telemetry

DEFAULT_DAYS = 7
STATUSES = {'open': 'open', 'cleared': 'cleared', 'all': None}


class BadRequest(Exception):
    """A request the admin API refuses with 400 `bad_request`; `rule` says what is wrong with it."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message


def _refusal(category: str, rule: str, message: str) -> JSONResponse:
    return JSONResponse({'error': category, 'rule': rule, 'message': message}, status_code=400)


def _staff(request: Request) -> str:
    staff = (request.headers.get('x-iqraa-staff') or '').strip()
    if not staff:
        raise BadRequest('staff_required', 'X-Iqraa-Staff (the staff member) is required')
    return staff


async def _body(request: Request) -> dict:
    raw = await request.body()
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except ValueError:
        raise BadRequest('bad_json', 'the body must be a JSON object') from None
    if not isinstance(body, dict):
        raise BadRequest('bad_json', 'the body must be a JSON object')
    return body


def _text(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _days(value) -> int:
    """A window in days: a whole number from 1 to MAX_DAYS (a JSON boolean, fraction or string is refused)."""
    if type(value) is not int or not 1 <= value <= MAX_DAYS:
        raise BadRequest('bad_days', f'days must be a whole number from 1 to {MAX_DAYS}')
    return value


def _query_days(request: Request) -> int:
    """`days` from the query string: ASCII digits only, then the same range as _days."""
    raw = request.query_params.get('days')
    if raw is None:
        return DEFAULT_DAYS
    return _days(int(raw) if re.fullmatch('[0-9]{1,4}', raw) else None)


def routes(pool: AsyncConnectionPool, cache: SettingsCache) -> list[Route]:
    def handler(endpoint):
        async def wrapped(request: Request) -> JSONResponse:
            try:
                return await endpoint(request)
            except BadRequest as error:
                return _refusal('bad_request', error.rule, error.message)
            except SettingsError as error:
                return _refusal(error.category, error.rule, error.message)
            except events.TooManyEvents as error:
                return _refusal('bad_request', 'too_many_events', str(error))

        return wrapped

    async def list_flags(request: Request) -> JSONResponse:
        status = request.query_params.get('status', 'open')
        if status not in STATUSES:
            raise BadRequest('bad_status', 'status must be open, cleared or all')
        async with pool.connection() as conn:
            found = await flags.list_flags(conn, STATUSES[status])
        return JSONResponse({'flags': [flag.as_dict() for flag in found]})

    async def clear_flag(request: Request) -> JSONResponse:
        staff = _staff(request)
        reason = _text((await _body(request)).get('reason'))
        async with pool.connection() as conn:
            flag = await flags.clear(conn, request.path_params['user_id'], staff, reason)
        if flag is None:
            return JSONResponse({'error': 'no_open_flag', 'message': 'this user has no open flag'}, status_code=404)
        return JSONResponse({'flag': flag.as_dict()})

    async def get_settings(request: Request) -> JSONResponse:
        async with pool.connection() as conn:
            return JSONResponse(await guard_settings.current(conn))

    async def put_settings(request: Request) -> JSONResponse:
        staff = _staff(request)
        body = await _body(request)
        changes = body.get('settings')
        if not isinstance(changes, dict) or not changes:
            raise BadRequest('bad_request', 'settings (an object of the values to change) is required')
        async with pool.connection() as conn:
            updated = await guard_settings.update_settings(conn, changes, staff, _text(body.get('reason')))
        cache.invalidate()
        return JSONResponse({'settings': updated.as_dict()})

    async def settings_history(request: Request) -> JSONResponse:
        async with pool.connection() as conn:
            return JSONResponse({'history': await guard_settings.history(conn)})

    async def simulate_settings(request: Request) -> JSONResponse:
        body = await _body(request)
        changes = body.get('settings', {})
        if not isinstance(changes, dict):
            raise BadRequest('bad_request', 'settings must be an object of candidate values')
        days = _days(body.get('days', DEFAULT_DAYS))
        async with pool.connection() as conn:
            candidate = guard_settings.merged(await guard_settings.load_settings(conn), changes)
        # The window plus the detector's look-back before it, so the 7-day signals see their history.
        by_user, now = await anyio.to_thread.run_sync(
            events.load_window_sync, pool.conninfo, timedelta(days=days) + events.lookback(candidate))
        would_flag = await anyio.to_thread.run_sync(simulate, by_user, candidate, now - timedelta(days=days))
        return JSONResponse({'window_days': days, 'settings': candidate.as_dict(), 'would_flag': would_flag})

    async def report(request: Request) -> JSONResponse:
        days = _query_days(request)
        async with pool.connection() as conn:
            settings = await guard_settings.load_settings(conn)
            open_flags = await flags.open_counts(conn)
        by_user, _ = await anyio.to_thread.run_sync(events.load_window_sync, pool.conninfo, timedelta(days=days))
        result = await anyio.to_thread.run_sync(telemetry, by_user, settings, open_flags)
        return JSONResponse({'window_days': days, **result})

    return [
        Route('/flags', handler(list_flags), methods=['GET']),
        Route('/flags/{user_id}/clear', handler(clear_flag), methods=['POST']),
        Route('/guard-settings', handler(get_settings), methods=['GET']),
        Route('/guard-settings', handler(put_settings), methods=['PUT']),
        Route('/guard-settings/history', handler(settings_history), methods=['GET']),
        Route('/guard-settings/simulate', handler(simulate_settings), methods=['POST']),
        Route('/telemetry', handler(report), methods=['GET']),
    ]
