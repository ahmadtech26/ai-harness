import os
import secrets

import pytest
from psycopg_pool import AsyncConnectionPool
from starlette.testclient import TestClient

from legal_search.caps import Caps
from legal_search.server import build_app

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
