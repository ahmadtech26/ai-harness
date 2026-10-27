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
