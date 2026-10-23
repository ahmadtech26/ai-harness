"""MCP server (streamable HTTP) exposing `search_law` and `get_article` to LibreChat specialists.

Every MCP request must carry the shared secret (`X-Iqraa-Secret`); tool calls must carry the caller's
identity (`X-Iqraa-User`, `X-Iqraa-Message`, `X-Iqraa-Conversation`), which LibreChat fills from
`requestHeaders` placeholders. Results are capped per answer and per user per day, and every call is
written to the retrieval log.
"""

import hmac
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from psycopg_pool import AsyncConnectionPool

from legal_search import db
from legal_search.caps import Caps, allowed

Scope = dict
Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]

UNVERIFIED = 'لم يُتحقق بعد من مطابقته للنص المنشور في الجريدة الرسمية'
CAP_REACHED = 'تم بلوغ الحد المسموح من النصوص لهذه الإجابة أو لهذا اليوم. يُرجى الاعتماد على ما سبق استرجاعه.'


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


def caps_from_env() -> Caps:
    return Caps(
        per_answer=int(os.environ.get('LEGAL_SEARCH_PER_ANSWER_CAP', '8')),
        daily=int(os.environ.get('LEGAL_SEARCH_DAILY_CAP', '300')),
        max_results=int(os.environ.get('LEGAL_SEARCH_MAX_RESULTS', '5')),
    )


def format_articles(found: list[db.Found]) -> str:
    blocks = []
    for index, article in enumerate(found, start=1):
        status = 'متحقق منه' if article.verified else UNVERIFIED
        blocks.append(
            f'[{index}] {article.law_title} — {article.label}\n{article.text}\n(المصدر: {article.source} — {status})'
        )
    return '\n\n'.join(blocks)


class SecretGuard:
    """ASGI wrapper: refuse any MCP request without the shared secret (health check excepted)."""

    def __init__(self, app, secret: str) -> None:
        self.app = app
        self.secret = secret.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
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


def build_server(pool: AsyncConnectionPool, caps: Caps, allowed_hosts: list[str]) -> FastMCP:
    # The SDK only auto-protects localhost binds; name the service's own hosts so rebinding protection
    # stays on behind a service name. Server-to-server callers send no Origin, so none is allowed.
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts, allowed_origins=[]
    )
    mcp = FastMCP('legal-search', stateless_http=True, transport_security=security)

    def identity(ctx: Context) -> tuple[str, str | None, str | None]:
        request = ctx.request_context.request
        headers = request.headers if request is not None else {}
        user = (headers.get('x-iqraa-user') or '').strip()
        if not user:
            raise ValueError('caller identity is required')
        return user, headers.get('x-iqraa-message') or None, headers.get('x-iqraa-conversation') or None

    async def budget(conn, user: str, message: str | None, requested: int) -> int:
        used_for_answer = await db.documents_for_message(conn, message) if message else 0
        used_today = await db.documents_for_user_today(conn, user)
        return allowed(requested, used_for_answer, used_today, caps)

    @mcp.tool()
    async def search_law(query: str, ctx: Context, limit: int = 5) -> str:
        """Search Jordanian statutes (Arabic). Returns up to `limit` matching articles with their citation."""
        user, message, conversation = identity(ctx)
        async with pool.connection() as conn:
            remaining = await budget(conn, user, message, limit)
            found = await db.search(conn, query, remaining) if remaining > 0 else []
            await db.log_retrieval(
                conn,
                user_id=user,
                message_id=message,
                conversation_id=conversation,
                tool='search_law',
                query=query,
                article_ids=[article.id for article in found],
            )
        if remaining == 0:
            return CAP_REACHED
        return format_articles(found) or 'لم يُعثر على مواد مطابقة في المصادر المحمّلة.'

    @mcp.tool()
    async def get_article(number: int, ctx: Context, suffix: str = '', law: str = 'civil-code') -> str:
        """Fetch one article by number (and suffix such as «مكرر») from a law; default law is the Civil Code."""
        user, message, conversation = identity(ctx)
        async with pool.connection() as conn:
            remaining = await budget(conn, user, message, 1)
            article = await db.get_article(conn, law, number, suffix) if remaining > 0 else None
            await db.log_retrieval(
                conn,
                user_id=user,
                message_id=message,
                conversation_id=conversation,
                tool='get_article',
                query=f'{law}:{number}{suffix}',
                article_ids=[article.id] if article else [],
            )
        if remaining == 0:
            return CAP_REACHED
        return format_articles([article]) if article else 'هذه المادة غير موجودة في المصادر المحمّلة.'

    return mcp


def build_app(pool: AsyncConnectionPool, caps: Caps, secret: str, allowed_hosts: list[str]) -> SecretGuard:
    """The ASGI app: MCP over streamable HTTP behind the secret guard; the pool opens with the app."""
    inner = build_server(pool, caps, allowed_hosts).streamable_http_app()
    inner_lifespan = inner.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        await pool.open()
        try:
            async with pool.connection() as conn:
                await db.create_schema(conn)
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
