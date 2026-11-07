import json
import os
import secrets

import pytest
from psycopg_pool import AsyncConnectionPool
from starlette.testclient import TestClient

from legal_search.caps import Caps
from legal_search.server import build_app
import psycopg

from legal_search.tools import SUSPENDED
from tests.mcp import tool_text
from tests.pg import TABLES

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')


def _app(secret: str):
    pool = AsyncConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=2, open=False, kwargs={'autocommit': True})
    return build_app(pool, Caps(per_answer=8, daily=300, max_results=5), secret, ['legal-search:*'])


def _initialize(client: TestClient, secret: str, host: str):
    return client.post(
        '/mcp',
        headers={'host': host, 'x-iqraa-secret': secret, 'accept': 'application/json, text/event-stream'},
        json={
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}},
        },
    )


def test_the_app_starts_and_serves_health():
    with TestClient(_app(secrets.token_hex(16))) as client:
        response = client.get('/health')

    assert response.status_code == 200


def test_the_running_app_refuses_mcp_requests_without_the_secret():
    with TestClient(_app(secrets.token_hex(16))) as client:
        response = client.post('/mcp', json={})

    assert response.status_code == 403


def test_accepts_mcp_requests_addressed_to_the_service_host():
    secret = secrets.token_hex(16)

    with TestClient(_app(secret)) as client:
        response = _initialize(client, secret, 'legal-search:8000')

    assert response.status_code == 200


def test_refuses_mcp_requests_addressed_to_another_host():
    secret = secrets.token_hex(16)

    with TestClient(_app(secret)) as client:
        response = _initialize(client, secret, 'attacker.example:8000')

    assert response.status_code == 421


def test_lists_the_three_library_tools_with_the_law_filter():
    secret = secrets.token_hex(16)

    with TestClient(_app(secret)) as client:
        response = client.post(
            '/mcp',
            headers={'host': 'legal-search:8000', 'x-iqraa-secret': secret, 'accept': 'application/json, text/event-stream'},
            json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}},
        )

    # Stateless streamable HTTP answers with one server-sent event (or plain JSON).
    body = response.text.strip()
    data = body if body.startswith('{') else next(l[len('data: '):] for l in body.splitlines() if l.startswith('data: '))
    listed = {tool['name']: tool for tool in json.loads(data)['result']['tools']}
    assert sorted(listed) == ['get_article', 'get_memorandum', 'search_law']
    assert 'law' in listed['search_law']['inputSchema']['properties']


def _fresh_tables():
    with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as conn:
        conn.execute(f'DROP TABLE IF EXISTS {TABLES} CASCADE')


def test_the_first_start_seeds_the_guard_settings_from_the_environment_caps():
    _fresh_tables()
    pool = AsyncConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=2, open=False, kwargs={'autocommit': True})

    with TestClient(build_app(pool, Caps(per_answer=6, daily=200, max_results=4), secrets.token_hex(16), ['legal-search:*'])):
        pass

    with psycopg.connect(os.environ['DATABASE_URL']) as conn:
        stored = conn.execute('SELECT settings FROM guard_settings WHERE id = 1').fetchone()[0]
    assert (stored['per_answer'], stored['daily'], stored['max_results'], stored['suspected_run']) == (6, 200, 4, 12)


async def test_concurrent_calls_of_one_answer_share_its_cap():
    # R1 n=12 (as amended by R2 n=18): parallel tool calls of one model step each read the budget before any was logged.
    import asyncio

    import httpx

    from legal_search import db
    from legal_search.corpus import Article
    from legal_search.registry import Law

    _fresh_tables()
    secret = secrets.token_hex(16)
    pool = AsyncConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=4, open=False, kwargs={'autocommit': True})
    guard = build_app(pool, Caps(per_answer=5, daily=300, max_results=5), secret, ['legal-search:*'])
    inner = guard.app
    async with inner.router.lifespan_context(inner):
        async with pool.connection() as conn:
            await db.upsert_laws(conn, [Law(slug='labour', title='قانون العمل', folder='l')])
            await db.upsert_articles(conn, [Article('labour', 'x', n, '', f'يعاقب العامل في الحالة {n}.', 's', 'l.md') for n in range(1, 21)])
        transport = httpx.ASGITransport(app=guard)
        async with httpx.AsyncClient(transport=transport, base_url='http://legal-search:8000') as client:
            async def call(query: str) -> None:
                await client.post(
                    '/mcp',
                    headers={'x-iqraa-secret': secret, 'x-iqraa-user': 'u-par', 'x-iqraa-message': 'm-par',
                             'accept': 'application/json, text/event-stream'},
                    json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                          'params': {'name': 'search_law', 'arguments': {'query': query, 'limit': 5}}},
                )

            await asyncio.gather(*(call(query) for query in ('يعاقب', 'العامل', 'الحالة', 'يعاقب العامل')))
        async with pool.connection() as conn:
            served = await db.documents_for_message(conn, 'm-par')

    assert 0 < served <= 5


async def test_parallel_calls_that_cross_the_distinct_threshold_together_open_a_flag():
    # R2 n=18 (a), test 1: the guard decision runs inside the user's lock. Two parallel searches of 5 new articles
    # each, at 294 distinct articles: decided outside the lock, both see 299 and no flag opens; inside it, the
    # second is budgeted to 3, decided at 302 (suspected_distinct_7d=300) and opens a suspected flag.
    import asyncio

    import httpx

    from legal_search import db, flags
    from legal_search.corpus import Article
    from legal_search.registry import Law

    _fresh_tables()
    secret = secrets.token_hex(16)
    pool = AsyncConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=4, open=False, kwargs={'autocommit': True})
    guard = build_app(pool, Caps(per_answer=8, daily=300, max_results=5), secret, ['legal-search:*'])
    inner = guard.app
    async with inner.router.lifespan_context(inner):
        async with pool.connection() as conn:
            await db.upsert_laws(conn, [Law(slug='civil-code', title='القانون المدني الأردني', folder='c')])
            await db.upsert_articles(conn, [
                *(Article('civil-code', 'x', n, '', f'يحق للمشتري العدول عن العقد بترك العربون، الحالة {n}.', 's', 'c.md')
                  for n in range(1, 6)),
                *(Article('civil-code', 'x', n, '', f'تنعقد الكفالة بإيجاب الكفيل وحده، الحالة {n}.', 's', 'c.md')
                  for n in range(6, 11)),
            ])
            # 294 distinct articles two days ago: inside the 7 days, outside the run window and the 24 h cap.
            await conn.execute(
                "INSERT INTO retrieval_log (user_id, message_id, tool, query, requested_law, requested_number, "
                "requested_suffix, outcome, created_at) SELECT 'u-x', 'm-old', 'get_article', 'seen:' || n, 'seen', n, "
                "'', 'served', now() - interval '2 days' FROM generate_series(1, 294) AS n"
            )
        transport = httpx.ASGITransport(app=guard)
        async with httpx.AsyncClient(transport=transport, base_url='http://legal-search:8000') as client:
            async def call(query: str) -> None:
                await client.post(
                    '/mcp',
                    headers={'x-iqraa-secret': secret, 'x-iqraa-user': 'u-x', 'x-iqraa-message': 'm-x',
                             'accept': 'application/json, text/event-stream'},
                    json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                          'params': {'name': 'search_law', 'arguments': {'query': query, 'limit': 5}}},
                )

            await asyncio.gather(call('العربون'), call('الكفالة'))
        async with pool.connection() as conn:
            served = await db.documents_for_message(conn, 'm-x')
            flag = await flags.open_flag(conn, 'u-x')

    assert served <= 8
    assert flag is not None and flag.level == 'suspected'


async def test_an_alert_waits_for_the_commit_of_its_call(alert_caplog):
    # R2 n=18 (b): inside the call's outer transaction, a flag alert raised before a rollback must never go out.
    from legal_search import guard as sweep
    from legal_search.server import UserLocks, serialised

    pool = AsyncConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=2, open=False, kwargs={'autocommit': True})
    await pool.open()

    async def opens_then_fails(conn):
        sweep.raise_alerts([('sweep_flag_opened', {'user_id': 'u-roll'})])
        raise RuntimeError('after the insert')

    async def opens(conn):
        sweep.raise_alerts([('sweep_flag_opened', {'user_id': 'u-ok'})])
        return 'served'

    try:
        with pytest.raises(RuntimeError):
            await serialised(pool, UserLocks(), 'u-roll', opens_then_fails)
        assert [r for r in alert_caplog.records if r.name == 'legal_search.alerts'] == []
        assert await serialised(pool, UserLocks(), 'u-ok', opens) == 'served'
    finally:
        await pool.close()

    assert [json.loads(r.getMessage())['user_id'] for r in alert_caplog.records if r.name == 'legal_search.alerts'] == ['u-ok']


async def test_one_users_queue_does_not_hold_every_connection():
    # R2 n=18 (c): a user's calls wait for their turn before taking a pool connection, so another user is not starved.
    import asyncio
    import time

    from legal_search.server import UserLocks, serialised

    pool = AsyncConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=2, open=False, kwargs={'autocommit': True})
    await pool.open()
    locks = UserLocks()

    async def slow(conn):
        await asyncio.sleep(0.5)

    async def quick(conn):
        return time.monotonic()

    try:
        start = time.monotonic()
        busy = [asyncio.create_task(serialised(pool, locks, 'u-a', slow)) for _ in range(4)]
        await asyncio.sleep(0.05)
        done = await serialised(pool, locks, 'u-b', quick)
        await asyncio.gather(*busy)
    finally:
        await pool.close()

    assert done - start < 0.9
    assert locks.held() == 0


def test_mcp_tool_calls_are_decided_by_the_guard():
    _fresh_tables()
    secret = secrets.token_hex(16)

    with TestClient(_app(secret)) as client:
        with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as conn:
            conn.execute(
                "INSERT INTO sweep_flags (user_id, level, opened_log_id, evidence) VALUES ('u-mcp', 'proven', 0, '{}')"
            )
        text = tool_text(client, 'u-mcp', 'get_article', {'number': 1}, {'x-iqraa-secret': secret})

    assert text == SUSPENDED


async def test_a_call_past_its_deadline_is_cut_off_and_frees_its_connection():
    # R3 n=13: without a deadline, one slow call keeps its pool connection for as long as it runs.
    from legal_search.server import UserLocks, serialised

    pool = AsyncConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=1, open=False, timeout=5,
                               kwargs={'autocommit': True})
    await pool.open()
    locks = UserLocks()

    async def slow(conn):
        await conn.execute('SELECT pg_sleep(10)')  # longer than the pool's wait: only a cancelled statement frees it

    async def quick(conn):
        return 'served'

    try:
        with pytest.raises(TimeoutError):
            await serialised(pool, locks, 'u-slow', slow, deadline=0.2)
        after = await serialised(pool, locks, 'u-slow', quick)  # the only connection, back in the pool
    finally:
        await pool.close()

    assert after == 'served' and locks.held() == 0


async def test_statement_and_lock_timeouts_apply_to_each_pool_connection_when_set(monkeypatch):
    # R3 n=13: nothing bounded how long one statement holds its connection; the owner sets the values.
    from psycopg import AsyncConnection

    from legal_search.server import connection_kwargs

    monkeypatch.setenv('LEGAL_SEARCH_STATEMENT_TIMEOUT_MS', '1500')
    monkeypatch.setenv('LEGAL_SEARCH_LOCK_TIMEOUT_MS', '250')

    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], **connection_kwargs()) as conn:
        cur = await conn.execute("SELECT current_setting('statement_timeout'), current_setting('lock_timeout')")
        applied = await cur.fetchone()

    assert applied == ('1500ms', '250ms')


def test_a_timeout_that_is_not_a_positive_whole_number_is_refused(monkeypatch):
    from legal_search.server import connection_kwargs

    monkeypatch.setenv('LEGAL_SEARCH_LOCK_TIMEOUT_MS', '0')

    with pytest.raises(RuntimeError):
        connection_kwargs()


def test_an_article_number_beyond_any_law_is_refused_before_the_tool_runs():
    # R2 n=10 / R3 n=10: the article number was any integer; the highest article in the corpus is 1851.
    _fresh_tables()
    secret = secrets.token_hex(16)

    with TestClient(_app(secret)) as client:
        tool_text(client, 'u-big', 'get_article', {'number': 100_000}, {'x-iqraa-secret': secret})
        tool_text(client, 'u-big', 'get_memorandum', {'article': 100_000}, {'x-iqraa-secret': secret})
        with psycopg.connect(os.environ['DATABASE_URL']) as conn:
            logged = conn.execute("SELECT count(*) FROM retrieval_log WHERE user_id = 'u-big'").fetchone()[0]

    assert logged == 0


def test_a_literal_identity_placeholder_is_refused_and_logs_nothing():
    # R3 n=12: a mistyped placeholder arrives as its own text, one identity that would merge every customer.
    _fresh_tables()
    secret = secrets.token_hex(16)

    with TestClient(_app(secret)) as client:
        tool_text(client, '{{LIBRECHAT_USERID}}', 'get_article', {'number': 1}, {'x-iqraa-secret': secret})
        tool_text(client, 'u-ok', 'get_article', {'number': 1},
                  {'x-iqraa-secret': secret, 'x-iqraa-message': '{{LIBRECHAT_BODY_MESSAGEID}}'})
        with psycopg.connect(os.environ['DATABASE_URL']) as conn:
            logged = conn.execute('SELECT count(*) FROM retrieval_log').fetchone()[0]

    assert logged == 0
