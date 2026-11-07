import asyncio
import os
import re
import secrets

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool
from starlette.testclient import TestClient

from legal_search import admin, events, tools
from legal_search.caps import Caps
from legal_search.normalize import normalize
from legal_search.server import build_app
from tests.mcp import tool_text
from tests.pg import TABLES

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

STAFF = {'x-iqraa-staff': 'staff-1'}
ADMIN_ROUTES = [
    ('GET', '/admin/flags'),
    ('POST', '/admin/flags/u1/clear'),
    ('POST', '/admin/flags/u1/suspend'),
    ('GET', '/admin/guard-settings'),
    ('PUT', '/admin/guard-settings'),
    ('GET', '/admin/guard-settings/history'),
    ('POST', '/admin/guard-settings/simulate'),
    ('GET', '/admin/telemetry'),
]


def _sql(statement: str, params: tuple = ()) -> None:
    with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as conn:
        conn.execute(statement, params)


def _results(text: str) -> int:
    return len(re.findall(r'^\[\d+\]', text, re.MULTILINE))


def _refusal(response) -> tuple:
    body = response.json()
    return response.status_code, body['error'], body['rule'], bool(body['message'])


def _articles(numbers) -> None:
    """Civil Code articles that a search for «العربون» finds."""
    _sql("INSERT INTO laws (slug, title) VALUES ('civil-code', 'القانون المدني الأردني')")
    for number in numbers:
        text = f'يحق للمشتري العدول عن العقد بترك العربون، المادة {number}.'
        _sql(
            "INSERT INTO articles (law_slug, law_title, number, label, text, norm) VALUES ('civil-code', 'x', %s, %s, %s, %s)",
            (number, f'المادة {number}', text, normalize(text)),
        )


@pytest.fixture
def client():
    _sql(f'DROP TABLE IF EXISTS {TABLES} CASCADE')
    shared = secrets.token_hex(16)
    pool = AsyncConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=2, open=False, kwargs={'autocommit': True})
    with TestClient(build_app(pool, Caps(per_answer=8, daily=300, max_results=5), shared, ['legal-search:*'])) as test_client:
        test_client.headers.update({'x-iqraa-secret': shared, 'host': 'legal-search:8000'})
        yield test_client


@pytest.mark.parametrize(('method', 'path'), ADMIN_ROUTES)
def test_every_admin_route_refuses_a_missing_or_wrong_secret(client, method, path):
    body = None if method == 'GET' else {'settings': {'max_results': 1}, 'reason': 'r'}
    missing = client.build_request(method, path, json=body, headers=STAFF)
    del missing.headers['x-iqraa-secret']
    wrong = client.build_request(method, path, json=body, headers={**STAFF, 'x-iqraa-secret': secrets.token_hex(16)})
    lookalikes = [client.build_request(method, near) for near in ('/health/', '/HEALTH', '/Health')]
    for request in lookalikes:
        del request.headers['x-iqraa-secret']

    statuses = [client.send(missing).status_code, client.send(wrong).status_code]
    near_health = [client.send(request).status_code for request in lookalikes]

    assert statuses == [403, 403]
    assert near_health == [403, 403, 403]  # only /health itself is answered without the secret


def test_a_settings_change_without_the_staff_header_is_rejected(client):
    response = client.put('/admin/guard-settings', json={'settings': {'suspected_run': 13}, 'reason': 'r'})
    garbled = client.put('/admin/guard-settings', headers=STAFF, content=b'{"settings": ')  # named, but not JSON

    assert _refusal(response) == (400, 'bad_request', 'staff_required', True)
    assert _refusal(garbled) == (400, 'bad_request', 'bad_json', True)


def test_a_settings_change_without_a_reason_is_rejected(client):
    before = client.get('/admin/guard-settings').json()

    response = client.put('/admin/guard-settings', headers=STAFF, json={'settings': {'suspected_run': 13}, 'reason': ' '})

    assert _refusal(response) == (400, 'bad_request', 'reason_required', True)
    assert client.get('/admin/guard-settings').json() == before


def test_invalid_settings_are_rejected_naming_the_rule(client):
    response = client.put('/admin/guard-settings', headers=STAFF, json={'settings': {'throttle_daily_cap': 300}, 'reason': 'r'})

    assert _refusal(response) == (400, 'invalid_settings', 'throttle_below_daily', True)


def test_a_settings_change_applies_to_the_next_mcp_call_and_is_in_the_history(client):
    _articles((1, 2, 3))
    before = tool_text(client, 'u-search', 'search_law', {'query': 'العربون'})

    changed = client.put('/admin/guard-settings', headers=STAFF, json={'settings': {'max_results': 1}, 'reason': 'narrower pages'})
    after = tool_text(client, 'u-search', 'search_law', {'query': 'العربون'})

    latest = client.get('/admin/guard-settings/history').json()['history'][0]
    assert (changed.status_code, _results(before), _results(after)) == (200, 3, 1)
    assert (latest['changed_by'], latest['reason'], latest['previous']['max_results'], latest['settings']['max_results']) == (
        'staff-1', 'narrower pages', 5, 1)


def _walk_rows(user: str, numbers, law: str = 'penal-code', ago: str = '1 hour') -> None:
    """One served get_article row per number, all at one instant `ago` before now (one Amman day, in order)."""
    _sql(
        'INSERT INTO retrieval_log (user_id, tool, query, requested_law, requested_number, requested_suffix, outcome, '
        "created_at) SELECT %s, 'get_article', %s || ':' || u.n, %s, u.n, '', 'served', now() - %s::interval "
        'FROM unnest(%s::int[]) WITH ORDINALITY AS u (n, i) ORDER BY u.i',
        (user, law, law, ago, list(numbers)),
    )


def _snapshot(client) -> tuple:
    """What simulate must leave as it is: the settings, the flags and the size of every table it could touch."""
    with psycopg.connect(os.environ['DATABASE_URL']) as conn:
        counts = [conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                  for table in ('guard_settings_history', 'guard_watermarks', 'retrieval_log', 'sweep_flags')]
    return client.get('/admin/guard-settings').json(), client.get('/admin/flags?status=all').json(), counts


def test_clearing_through_the_api_records_the_staff_member_and_404s_without_an_open_flag(client):
    _sql("INSERT INTO sweep_flags (user_id, level, opened_log_id, evidence) VALUES ('u9', 'proven', 0, '{}')")

    cleared = client.post('/admin/flags/u9/clear', headers=STAFF, json={'reason': 'reviewed'})
    again = client.post('/admin/flags/u9/clear', headers=STAFF, json={})

    listed = client.get('/admin/flags?status=all').json()['flags']
    unknown = client.get('/admin/flags?status=x')
    assert (cleared.status_code, cleared.json()['flag']['cleared_by'], again.status_code) == (200, 'staff-1', 404)
    assert [(flag['user_id'], flag['status']) for flag in listed] == [('u9', 'cleared')]
    assert _refusal(unknown) == (400, 'bad_request', 'bad_status', True)


def test_simulate_lists_the_users_flagged_in_the_window_and_changes_nothing(client):
    _walk_rows('walker', range(1, 12))                          # 11 sequential articles an hour ago
    _walk_rows('early', range(1, 13), law='labour', ago='2 days')  # flagged two days ago: before the window
    _walk_rows('coverer', range(1, 895, 3), ago='2 days')       # 298 articles three apart two days ago,
    _sql("INSERT INTO retrieval_log (user_id, tool, query, requested_law, requested_number, requested_suffix, note_ids, "
         "created_at) VALUES ('coverer', 'get_memorandum', 'civil-code:memorandum:1@0', 'civil-code', 1, '', %s, "
         "now() - interval '1 hour')", (list(range(1, 11)),))  # the 299th an hour ago, with ten notes: the throttle cap
    _articles((1, 2, 3))
    crossing = tool_text(client, 'coverer', 'search_law', {'query': 'العربون'})  # 301 with its candidates: refused
    before = _snapshot(client)

    response = client.post('/admin/guard-settings/simulate', json={'settings': {'suspected_run': 10}, 'days': 1})

    assert (crossing, [(flag['user_id'], flag['level']) for flag in before[1]['flags']]) == (
        tools.CAP_REACHED, [('coverer', 'suspected')])  # the guard flagged the coverer at that search
    assert [(user['user_id'], user['level']) for user in response.json()['would_flag']] == [
        ('coverer', 'suspected'), ('walker', 'suspected')]
    assert _snapshot(client) == before


def test_simulate_refuses_days_that_are_not_a_whole_number(client):
    responses = [client.post('/admin/guard-settings/simulate', json={'days': days}) for days in (True, 1.5, '7')]

    assert [_refusal(response) for response in responses] == [(400, 'bad_request', 'bad_days', True)] * 3


def test_simulate_refuses_settings_that_are_not_an_object(client):
    response = client.post('/admin/guard-settings/simulate', json={'settings': [], 'days': 1})

    assert _refusal(response) == (400, 'bad_request', 'bad_request', True)


def test_a_user_above_the_event_ceiling_is_left_out_and_named_and_everyone_else_is_reported(client):
    # R1 n=15: the ceiling was global, so one customer's rows refused the simulation and the telemetry for everyone.
    _sql("INSERT INTO retrieval_log (user_id, tool) SELECT 'bulk', 'search_law' FROM generate_series(1, %s)",
         (events.MAX_EVENTS + 1,))
    _walk_rows('walker', range(1, 12))

    simulated = client.post('/admin/guard-settings/simulate', json={'settings': {'suspected_run': 10}, 'days': 1})
    report = client.get('/admin/telemetry?days=1')

    assert (simulated.status_code, report.status_code) == (200, 200)
    assert ([user['user_id'] for user in simulated.json()['would_flag']], simulated.json()['left_out']) == (['walker'], ['bulk'])
    assert (report.json()['users'], report.json()['left_out']) == (1, ['bulk'])


def test_past_the_total_event_ceiling_the_largest_users_are_left_out(client, monkeypatch):
    # R1 n=15: the per-user ceiling alone left one request's memory unbounded; past the total, the largest users go.
    monkeypatch.setattr(events, 'MAX_EVENTS', 50)
    monkeypatch.setattr(events, 'MAX_TOTAL_EVENTS', 100, raising=False)
    for user, count in (('u37', 37), ('u38', 38), ('u39', 39), ('u40', 40)):
        _sql("INSERT INTO retrieval_log (user_id, tool) SELECT %s, 'search_law' FROM generate_series(1, %s)", (user, count))

    simulated = client.post('/admin/guard-settings/simulate', json={'days': 1})
    report = client.get('/admin/telemetry?days=1')

    assert (simulated.status_code, report.status_code) == (200, 200)
    assert (simulated.json()['left_out'], report.json()['left_out']) == (['u39', 'u40'], ['u39', 'u40'])
    assert report.json()['users'] == 2


@pytest.mark.parametrize(('method', 'path', 'computation'), [
    ('POST', '/admin/guard-settings/simulate', 'simulate'),
    ('GET', '/admin/telemetry', 'telemetry'),
])
def test_simulation_and_telemetry_compute_off_the_event_loop(client, monkeypatch, method, path, computation):
    threads = []

    def probe(original):
        def probed(*args):
            try:
                asyncio.get_running_loop()
                threads.append('event loop')
            except RuntimeError:
                threads.append('worker thread')
            return original(*args)

        return probed

    monkeypatch.setattr(admin, computation, probe(getattr(admin, computation)))
    monkeypatch.setattr(events, 'load_window_sync', probe(events.load_window_sync))

    response = client.request(method, path, json={} if method == 'POST' else None)

    assert (response.status_code, threads) == (200, ['worker thread', 'worker thread'])  # the load, then the computation


def test_telemetry_reports_the_window_and_refuses_days_outside_one_to_thirty(client):
    _walk_rows('walker', range(1, 13))
    _walk_rows('reader', range(1, 3), law='labour')
    _sql("INSERT INTO sweep_flags (user_id, level, opened_log_id, evidence) VALUES ('walker', 'suspected', 0, '{}')")

    report = client.get('/admin/telemetry?days=1').json()
    refused = [client.get('/admin/telemetry', params={'days': days}) for days in ('31', '٧', ' 7')]

    assert (report['window_days'], report['users'], report['longest_run']['max']) == (1, 2, 12)
    assert report['open_flags'] == {'suspected': 1, 'proven': 0}
    assert [_refusal(response) for response in refused] == [(400, 'bad_request', 'bad_days', True)] * 3


def test_a_staff_suspension_refuses_every_retrieval_until_the_flag_is_cleared(client):
    # R1 n=16: suspending an account left the library open to the tool calls its last model step requested.
    _articles((1,))

    suspended = client.post('/admin/flags/u-acct/suspend', headers=STAFF, json={'reason': 'account suspended'})
    refused = tool_text(client, 'u-acct', 'get_article', {'number': 1})
    client.post('/admin/flags/u-acct/clear', headers=STAFF, json={'reason': 'account restored'})
    served = tool_text(client, 'u-acct', 'get_article', {'number': 1})

    assert suspended.status_code == 200 and suspended.json()['flag']['level'] == 'proven'
    assert refused == tools.SUSPENDED and 'المادة 1' in served
