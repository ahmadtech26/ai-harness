"""MCP server (streamable HTTP) exposing the legal library to LibreChat specialists: `search_law`,
`get_article` and `get_memorandum` (their behaviour lives in tools.py).

Every request must carry the shared secret (`X-Iqraa-Secret`); tool calls must carry the caller's identity
(`X-Iqraa-User`, `X-Iqraa-Message`, `X-Iqraa-Conversation`), which LibreChat fills from `requestHeaders`
placeholders. Each tool call reads the guard settings (thresholds and caps, cached for at most 30 s), is
decided by the sweep guard, capped, and written to the retrieval log.

Only the timing stack (compose.timing.yaml) sets LEGAL_SEARCH_TIMING_SPANS=1: each search_law call then appends one
line of its spans to LEGAL_SEARCH_TIMING_FILE (REQ-RAG-021). No deploy file sets either.

search_law ranks with the server's search config: DEFAULT, or the overrides LEGAL_SEARCH_SEARCH_CONFIG names, which
only the timing stack sets (recall plan Tasks 3.2 and 3.9; search_config.search_config_from_env). A server whose
config ranks with the keyword engine (ranker=bm25) builds that config's index before it serves. Its searches run
one at a time (keyword_engine.DEFAULT_SEARCHES) unless LEGAL_SEARCH_ENGINE_SEARCHES allows more; no deploy file sets it.
An everyday search vocabulary is installed only when LEGAL_SEARCH_VOCABULARY names its file (vocabulary.py); no deploy
file sets it either.
"""

import asyncio
import hmac
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Annotated, TypeVar

import anyio
import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool
from pydantic import Field
from starlette.routing import Mount

from legal_search import admin, db, keyword_engine, spans, synonyms, tools, vocabulary
from legal_search import guard as sweep
from legal_search.caps import Caps
from legal_search.guard_settings import GuardSettings, SettingsCache, ensure_settings, validate
from legal_search.search_config import DEFAULT, SearchConfig, search_config_from_env

Scope = dict
Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]
T = TypeVar('T')
# psycopg_pool's own default (3.3.3), made explicit: a call waits at most this long for a pool connection (R3 n=13).
POOL_TIMEOUT = 30.0
# An article number the tools accept: far above the corpus's highest (1851), so no real article is out of reach;
# anything else is refused before the tool runs and is never logged (R2 n=10, R3 n=10).
MAX_ARTICLE_NUMBER = 9_999
ArticleNumber = Annotated[int, Field(ge=1, le=MAX_ARTICLE_NUMBER)]
# The fork's PLAIN_ID (routes.ts): LibreChat's user and message ids are plain. A placeholder LibreChat does not
# know arrives as its own text ("{{...}}"), one identity that would merge every customer (R3 n=12).
PLAIN_ID = re.compile('[A-Za-z0-9_-]+')
# The timing stack's switch and span file (Task 1.5); compose.contract.test.mjs keeps them out of staging.
TIMING_SPANS = 'LEGAL_SEARCH_TIMING_SPANS'
TIMING_FILE = 'LEGAL_SEARCH_TIMING_FILE'
# The keyword-engine searches that may run at once (review 2026-11-11 (b)4).
ENGINE_SEARCHES = 'LEGAL_SEARCH_ENGINE_SEARCHES'
LOGGER = logging.getLogger('legal_search.server')


def read_secret() -> str:
    path = os.environ.get('LEGAL_SEARCH_SECRET_FILE')
    if not path:
        raise RuntimeError('LEGAL_SEARCH_SECRET_FILE is required')
    with open(path, encoding='utf-8') as handle:
        secret = handle.read().strip()
    if len(secret) < 16:
        raise RuntimeError('legal-search secret is too short')
    return secret


def allowed_hosts_from_env() -> list[str]:
    """Host headers the MCP endpoint answers (e.g. `legal-search:*`); the SDK's rebinding check uses them."""
    hosts = [h.strip() for h in os.environ.get('LEGAL_SEARCH_ALLOWED_HOSTS', '').split(',') if h.strip()]
    if not hosts:
        raise RuntimeError('LEGAL_SEARCH_ALLOWED_HOSTS is required (comma-separated, e.g. legal-search:*)')
    return hosts


class UserLocks:
    """One asyncio lock per user, dropped when nobody holds or waits on it."""

    def __init__(self) -> None:
        self._locks: dict[str, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def hold(self, user: str):
        lock, users = self._locks.get(user, (asyncio.Lock(), 0))
        self._locks[user] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            lock, users = self._locks[user]
            if users == 1:
                del self._locks[user]
            else:
                self._locks[user] = (lock, users - 1)

    def held(self) -> int:
        return len(self._locks)


async def serialised(pool: AsyncConnectionPool, locks: UserLocks, user: str,
                     body: Callable[[AsyncConnection], Awaitable[T]], deadline: float | None = None) -> T:
    """Runs one tool call of `user` alone (R1 n=12, R2 n=18): the budget read, the guard decision, the search and the
    log row see every earlier call of the user committed. The user's calls queue in this process before taking a pool
    connection, so one user's parallel step cannot hold the whole pool; the advisory lock, the first statement of the
    call's outer transaction, keeps a second process in line too. Alerts go out only after that transaction commits.
    With a `deadline` (seconds), a call still running then is cancelled with TimeoutError: its transaction rolls back
    and its connection goes back to the pool (R3 n=13); None sets no deadline.
    The waits for the user's lock and for a pool connection are timed as the spans lock_wait and pool_wait."""
    with anyio.fail_after(deadline):
        async with AsyncExitStack() as held:  # released in reverse: the connection, then the user's lock
            async with spans.span('lock_wait'):
                await held.enter_async_context(locks.hold(user))
            async with spans.span('pool_wait'):
                conn = await held.enter_async_context(pool.connection())
            pending: list = []
            token = sweep.DEFERRED.set(pending)
            try:
                async with conn.transaction():
                    await conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (user,))
                    result = await body(conn)
            finally:
                sweep.DEFERRED.reset(token)
            sweep.raise_alerts(pending)
            return result


def _positive_env(name: str) -> int | None:
    """A positive whole number from the environment, or None when it is unset."""
    raw = os.environ.get(name, '').strip()
    if not raw:
        return None
    if not re.fullmatch('[0-9]+', raw) or int(raw) == 0:
        raise RuntimeError(f'{name} must be a positive whole number, got {raw!r}')
    return int(raw)


def connection_kwargs() -> dict:
    """The pool's connection options: autocommit, plus each statement and lock timeout (milliseconds) that is set.
    Unset by default: the owner sets them from measured call times (R3 n=13)."""
    kwargs: dict = {'autocommit': True}
    options = [
        f'-c {setting}={value}'
        for setting, value in (('statement_timeout', _positive_env('LEGAL_SEARCH_STATEMENT_TIMEOUT_MS')),
                               ('lock_timeout', _positive_env('LEGAL_SEARCH_LOCK_TIMEOUT_MS')))
        if value is not None
    ]
    if options:
        kwargs['options'] = ' '.join(options)
    return kwargs


def timing_file_from_env() -> str | None:
    """The file a timing stack's server appends one span line per search_law call to: LEGAL_SEARCH_TIMING_FILE,
    read only when LEGAL_SEARCH_TIMING_SPANS=1 (then required). None when the switch is unset or 0: no spans are
    collected. Any other value stops the server, as a malformed number does in _positive_env."""
    switch = os.environ.get(TIMING_SPANS, '').strip()
    if switch in ('', '0'):
        return None
    if switch != '1':
        raise RuntimeError(f'{TIMING_SPANS} must be 0 or 1, got {switch!r}')
    path = os.environ.get(TIMING_FILE, '').strip()
    if not path:
        raise RuntimeError(f'{TIMING_FILE} is required when {TIMING_SPANS}=1')
    return path


def append_timing_line(path: str, message: str | None, got: list[spans.Span], server_ms: float) -> None:
    """One call's line: its message id, its spans and its server time. Ids and times only, never query text.
    It runs in the tool's `finally`, after server_ms is taken (so its cost lands in the driver's transport): a write
    that fails is logged, without the message id, and never replaces the tool's answer; the driver then counts the
    call as unjoined and fails the run."""
    line = json.dumps({'message': message, 'spans': [[name, ms] for name, ms in got], 'server_ms': server_ms})
    try:
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write(line + '\n')
    except OSError as error:
        LOGGER.warning('timing span line not written to %s: %s', path, type(error).__name__)


def tool_deadline_from_env() -> float | None:
    """Seconds a tool call may run (LEGAL_SEARCH_TOOL_DEADLINE_SECONDS); None when unset (R3 n=13)."""
    seconds = _positive_env('LEGAL_SEARCH_TOOL_DEADLINE_SECONDS')
    return None if seconds is None else float(seconds)


def engine_searches_from_env() -> int:
    """The keyword-engine searches that may run at once: LEGAL_SEARCH_ENGINE_SEARCHES, a positive whole number, or
    keyword_engine.DEFAULT_SEARCHES (1) when it is unset; the reasons for 1 are at that constant."""
    return _positive_env(ENGINE_SEARCHES) or keyword_engine.DEFAULT_SEARCHES


def caps_from_env() -> Caps:
    """The environment's caps: the guard settings' first-start defaults (runtime values live in guard_settings)."""
    return Caps(
        per_answer=int(os.environ.get('LEGAL_SEARCH_PER_ANSWER_CAP', '8')),
        daily=int(os.environ.get('LEGAL_SEARCH_DAILY_CAP', '300')),
        max_results=int(os.environ.get('LEGAL_SEARCH_MAX_RESULTS', '5')),
    )


class SecretGuard:
    """ASGI wrapper: refuse any request without the shared secret (health check excepted)."""

    def __init__(self, app, secret: str) -> None:
        self.app = app
        self.secret = secret.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] == 'lifespan':
            await self.app(scope, receive, send)
            return
        if scope['type'] != 'http':
            # No route behind this guard speaks anything but HTTP, so any other scope is refused here rather than
            # trusted to find no route: a websocket route a later SDK release adds would skip the secret (R1 n=19).
            if scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 1008})
            return
        if scope.get('path') == '/health':
            await self._reply(send, 200, b'ok')
            return
        supplied = dict(scope.get('headers') or []).get(b'x-iqraa-secret', b'')
        if not hmac.compare_digest(supplied, self.secret):
            await self._reply(send, 403, b'forbidden')
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reply(send: Send, status: int, body: bytes) -> None:
        await send({'type': 'http.response.start', 'status': status, 'headers': [(b'content-type', b'text/plain')]})
        await send({'type': 'http.response.body', 'body': body})


def build_server(pool: AsyncConnectionPool, cache: SettingsCache, allowed_hosts: list[str],
                 deadline: float | None = None, max_query: int | None = None, timing_file: str | None = None,
                 config: SearchConfig = DEFAULT) -> FastMCP:
    # The SDK only auto-protects localhost binds; name the service's own hosts so rebinding protection
    # stays on behind a service name. Server-to-server callers send no Origin, so none is allowed.
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts, allowed_origins=[]
    )
    mcp = FastMCP('legal-search', stateless_http=True, transport_security=security)
    locks = UserLocks()

    def caller(ctx: Context) -> tools.Caller:
        request = ctx.request_context.request
        headers = request.headers if request is not None else {}
        user = (headers.get('x-iqraa-user') or '').strip()
        if not user:
            raise ValueError('caller identity is required')
        message = headers.get('x-iqraa-message') or None
        if not PLAIN_ID.fullmatch(user) or (message is not None and not PLAIN_ID.fullmatch(message)):
            raise ValueError('caller identity must be a plain id')
        return tools.Caller(user, message, headers.get('x-iqraa-conversation') or None)

    @mcp.tool()
    async def search_law(query: str, ctx: Context, limit: int = 5, law: str | None = None) -> str:
        """Search Jordanian statutes (Arabic). Returns up to `limit` matching articles with their citation.
        Pass `law` (a law slug such as "penal-code" or "civil-procedure") to search that law only."""
        who = caller(ctx)

        async def body(conn: AsyncConnection) -> str:
            async with spans.span('guard_settings'):
                settings = await cache.get(conn)
            return await tools.search_law(conn, settings.caps, who, query, limit, law, guard=settings, max_query=max_query,
                                          config=config)

        if timing_file is None:
            return await serialised(pool, locks, who.user, body, deadline)
        with spans.collect() as got:  # the timing stack only: this call's spans, from before the lock wait
            started = time.perf_counter()
            try:
                return await serialised(pool, locks, who.user, body, deadline)
            finally:
                append_timing_line(timing_file, who.message, got, (time.perf_counter() - started) * 1000.0)

    @mcp.tool()
    async def get_article(number: ArticleNumber, ctx: Context, suffix: str = '', law: str = 'civil-code') -> str:
        """Fetch one article by number (and suffix such as «مكرر») from a law, by its slug; default law is the Civil Code."""
        who = caller(ctx)

        async def body(conn: AsyncConnection) -> str:
            settings = await cache.get(conn)
            return await tools.get_article(conn, settings.caps, who, number, suffix, law, guard=settings)

        return await serialised(pool, locks, who.user, body, deadline)

    @mcp.tool()
    async def get_memorandum(article: ArticleNumber, ctx: Context, offset: int = 0) -> str:
        """Civil Code explanatory memorandum: the notes linked to a Civil Code article, one page at a time.
        The result says how many notes remain and the next `offset`."""
        who = caller(ctx)

        async def body(conn: AsyncConnection) -> str:
            settings = await cache.get(conn)
            return await tools.get_memorandum(conn, settings.caps, who, article, offset, guard=settings)

        return await serialised(pool, locks, who.user, body, deadline)

    return mcp


def build_app(pool: AsyncConnectionPool, caps: Caps, secret: str, allowed_hosts: list[str],
              deadline: float | None = None, max_query: int | None = None, timing_file: str | None = None,
              config: SearchConfig = DEFAULT) -> SecretGuard:
    """The ASGI app behind the secret guard; the pool opens with the app. `caps` (the environment's) seed the
    guard settings on first start only; afterwards the database row is authoritative. `deadline`: seconds a tool
    call may run; `max_query`: the longest search_law query searched, in characters (None: no limit for either).
    `timing_file`: where each search_law call appends its span line (the timing stack only; None: no spans).
    `config`: the search config search_law ranks with. With ranker=bm25 the lifespan builds its keyword index, and
    waits for it, before the app serves: the first search finds it warm instead of falling back to Postgres. A build
    that fails stops the start-up."""
    defaults = validate(GuardSettings(per_answer=caps.per_answer, daily=caps.daily, max_results=caps.max_results).as_dict())
    cache = SettingsCache()
    inner = build_server(pool, cache, allowed_hosts, deadline, max_query, timing_file, config).streamable_http_app()
    # The staff admin API shares the app, the pool, the settings cache and SecretGuard.
    inner.router.routes.append(Mount('/admin', routes=admin.routes(pool, cache)))
    inner_lifespan = inner.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        await pool.open()
        try:
            async with pool.connection() as conn:
                await db.create_schema(conn)
                await ensure_settings(conn, defaults)
                if config.ranker == 'bm25':
                    await keyword_engine.CACHE.ensure(conn, config)
            async with inner_lifespan(app):
                yield
        finally:
            await pool.close()

    inner.router.lifespan_context = lifespan
    return SecretGuard(inner, secret)


def main() -> None:
    keyword_engine.SEARCHES = keyword_engine.Searches(engine_searches_from_env())
    synonyms.use_vocabulary(vocabulary.vocabulary_from_env())  # before any index build; unset installs none
    pool = AsyncConnectionPool(db.database_url(), min_size=1, max_size=10, open=False, timeout=POOL_TIMEOUT,
                               kwargs=connection_kwargs())
    app = build_app(pool, caps_from_env(), read_secret(), allowed_hosts_from_env(), tool_deadline_from_env(),
                    _positive_env('LEGAL_SEARCH_MAX_QUERY_CHARS'), timing_file_from_env(),
                    config=search_config_from_env())
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', '8000')), log_level='info')


if __name__ == '__main__':
    main()
