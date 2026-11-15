from legal_search.caps import Caps, Grant, allowed, grant, left_for_answer
from legal_search.server import SecretGuard

CAPS = Caps(per_answer=8, daily=300, max_results=5)


def test_limits_to_the_per_call_maximum():
    assert allowed(20, 0, 0, CAPS) == 5


def test_limits_to_what_remains_for_the_answer():
    assert allowed(5, 6, 0, CAPS) == 2


def test_limits_to_what_remains_for_the_day():
    assert allowed(5, 0, 299, CAPS) == 1


def test_returns_zero_once_a_cap_is_reached():
    assert allowed(5, 8, 0, CAPS) == 0
    assert allowed(5, 0, 300, CAPS) == 0


# FRP 2.1: the caps say which bound refused, so the tools can answer the per-answer and the daily cap apart.
def test_grant_keeps_alloweds_count_in_every_case_the_existing_tests_cover():
    cases = [(20, 0, 0), (5, 6, 0), (5, 0, 299), (5, 8, 0), (5, 0, 300)]

    assert [grant(*case, CAPS).count for case in cases] == [allowed(*case, CAPS) for case in cases] == [5, 2, 1, 0, 0]


def test_a_refusal_at_the_per_answer_cap_names_per_answer():
    assert grant(5, 8, 0, CAPS) == Grant(0, 'per_answer')


def test_a_refusal_at_the_daily_cap_names_daily_also_when_the_per_answer_cap_is_spent_too():
    assert grant(5, 0, 300, CAPS) == Grant(0, 'daily')
    assert grant(5, 8, 300, CAPS) == Grant(0, 'daily')  # a new question does not help then


def test_a_granted_call_names_no_bound():
    assert [grant(5, 6, 0, CAPS), grant(1, 0, 299, CAPS)] == [Grant(2, None), Grant(1, None)]


def test_left_for_answer_is_the_smaller_remainder_of_the_two_caps_and_never_below_0():
    assert [left_for_answer(5, 0, CAPS), left_for_answer(2, 297, CAPS), left_for_answer(9, 0, CAPS),
            left_for_answer(0, 301, CAPS)] == [3, 3, 0, 0]


async def _call(guard: SecretGuard, path: str, headers: list[tuple[bytes, bytes]]):
    sent: list[dict] = []

    async def receive():
        return {'type': 'http.request', 'body': b''}

    async def send(message):
        sent.append(message)

    await guard({'type': 'http', 'path': path, 'headers': headers}, receive, send)
    return sent


async def _inner(scope, receive, send):
    await send({'type': 'http.response.start', 'status': 200, 'headers': []})
    await send({'type': 'http.response.body', 'body': b'inner'})


async def test_refuses_mcp_requests_without_the_secret():
    sent = await _call(SecretGuard(_inner, 's' * 32), '/mcp', [])

    assert sent[0]['status'] == 403


async def test_refuses_a_wrong_secret():
    sent = await _call(SecretGuard(_inner, 's' * 32), '/mcp', [(b'x-iqraa-secret', b'x' * 32)])

    assert sent[0]['status'] == 403


async def test_passes_the_right_secret_through():
    sent = await _call(SecretGuard(_inner, 's' * 32), '/mcp', [(b'x-iqraa-secret', b's' * 32)])

    assert sent[1]['body'] == b'inner'


async def test_answers_health_without_the_secret():
    sent = await _call(SecretGuard(_inner, 's' * 32), '/health', [])

    assert (sent[0]['status'], sent[1]['body']) == (200, b'ok')


async def test_closes_a_websocket_without_reaching_the_inner_app():
    # R1 n=19: only lifespan and http scopes reach the app; a websocket route an SDK release adds would skip the secret.
    reached = []

    async def inner(scope, receive, send):
        reached.append(scope['type'])

    sent = []

    async def receive():
        return {'type': 'websocket.connect'}

    async def send(message):
        sent.append(message)

    await SecretGuard(inner, 's' * 32)({'type': 'websocket', 'path': '/mcp', 'headers': []}, receive, send)
    await SecretGuard(inner, 's' * 32)({'type': 'lifespan'}, receive, send)

    assert reached == ['lifespan']
    assert sent == [{'type': 'websocket.close', 'code': 1008}]
