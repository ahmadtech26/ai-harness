"""MCP server (streamable HTTP) exposing the legal library to LibreChat specialists: `search_law`,
`get_article` and `get_memorandum` (their behaviour lives in tools.py).

Every request must carry the shared secret (`X-Iqraa-Secret`); tool calls must carry the caller's identity
(`X-Iqraa-User`, `X-Iqraa-Message`, `X-Iqraa-Conversation`), which LibreChat fills from `requestHeaders`
placeholders. Each tool call reads the guard settings (thresholds and caps, cached for at most 30 s), is
decided by the sweep guard, capped, and written to the retrieval log.
"""

import asyncio
import hmac
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TypeVar

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool
from starlette.routing import Mount

from legal_search import admin, db, tools
from legal_search import guard as sweep
from legal_search.caps import Caps
from legal_search.guard_settings import GuardSettings, SettingsCache, ensure_settings, validate

Scope = dict
Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]
T = TypeVar('T')


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
                     body: Callable[[AsyncConnection], Awaitable[T]]) -> T:
    """Runs one tool call of `user` alone (R1 n=12, R2 n=18): the budget read, the guard decision, the search and the
    log row see every earlier call of the user committed. The user's calls queue in this process before taking a pool
    connection, so one user's parallel step cannot hold the whole pool; the advisory lock, the first statement of the
    call's outer transaction, keeps a second process in line too. Alerts go out only after that transaction commits."""
    async with locks.hold(user):
        async with pool.connection() as conn:
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


def build_server(pool: AsyncConnectionPool, cache: SettingsCache, allowed_hosts: list[str]) -> FastMCP:
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
        return tools.Caller(user, headers.get('x-iqraa-message') or None, headers.get('x-iqraa-conversation') or None)

    @mcp.tool()
    async def search_law(query: str, ctx: Context, limit: int = 5, law: str | None = None) -> str:
        """Search Jordanian statutes (Arabic). Returns up to `limit` matching articles with their citation.
        Pass `law` (a law slug such as "penal-code" or "civil-procedure") to search that law only."""
        who = caller(ctx)

        async def body(conn: AsyncConnection) -> str:
            settings = await cache.get(conn)
            return await tools.search_law(conn, settings.caps, who, query, limit, law, guard=settings)

        return await serialised(pool, locks, who.user, body)

    @mcp.tool()
    async def get_article(number: int, ctx: Context, suffix: str = '', law: str = 'civil-code') -> str:
        """Fetch one article by number (and suffix such as «مكرر») from a law, by its slug; default law is the Civil Code."""
        who = caller(ctx)

        async def body(conn: AsyncConnection) -> str:
            settings = await cache.get(conn)
            return await tools.get_article(conn, settings.caps, who, number, suffix, law, guard=settings)

        return await serialised(pool, locks, who.user, body)

    @mcp.tool()
    async def get_memorandum(article: int, ctx: Context, offset: int = 0) -> str:
        """Civil Code explanatory memorandum: the notes linked to a Civil Code article, one page at a time.
        The result says how many notes remain and the next `offset`."""
        who = caller(ctx)

        async def body(conn: AsyncConnection) -> str:
            settings = await cache.get(conn)
            return await tools.get_memorandum(conn, settings.caps, who, article, offset, guard=settings)

        return await serialised(pool, locks, who.user, body)

    return mcp


def build_app(pool: AsyncConnectionPool, caps: Caps, secret: str, allowed_hosts: list[str]) -> SecretGuard:
    """The ASGI app behind the secret guard; the pool opens with the app. `caps` (the environment's) seed the
    guard settings on first start only; afterwards the database row is authoritative."""
    defaults = validate(GuardSettings(per_answer=caps.per_answer, daily=caps.daily, max_results=caps.max_results).as_dict())
    cache = SettingsCache()
    inner = build_server(pool, cache, allowed_hosts).streamable_http_app()
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
            async with inner_lifespan(app):
                yield
        finally:
            await pool.close()

    inner.router.lifespan_context = lifespan
    return SecretGuard(inner, secret)


def main() -> None:
    pool = AsyncConnectionPool(db.database_url(), min_size=1, max_size=10, open=False, kwargs={'autocommit': True})
    app = build_app(pool, caps_from_env(), read_secret(), allowed_hosts_from_env())
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', '8000')), log_level='info')


if __name__ == '__main__':
    main()
