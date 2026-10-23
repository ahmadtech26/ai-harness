import os
import secrets

import pytest
from psycopg_pool import AsyncConnectionPool
from starlette.testclient import TestClient

from legal_search.caps import Caps
from legal_search.server import build_app

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')


def _app():
    pool = AsyncConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=2, open=False, kwargs={'autocommit': True})
    return build_app(pool, Caps(per_answer=8, daily=300, max_results=5), secrets.token_hex(16))


def test_the_app_starts_and_serves_health():
    with TestClient(_app()) as client:
        response = client.get('/health')

    assert response.status_code == 200


def test_the_running_app_refuses_mcp_requests_without_the_secret():
    with TestClient(_app()) as client:
        response = client.post('/mcp', json={})

    assert response.status_code == 403
