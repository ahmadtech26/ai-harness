"""Whole-call timing (Task 1.5, REQ-RAG-021): per-call spans, the timing stack's span lines, and the driver's
percentiles and refusal count."""

import json
import logging
import os
import secrets
from types import SimpleNamespace

import httpx
import psycopg
import pytest
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from legal_search import db, keyword_engine, server, spans, timing, tools
from legal_search.caps import Caps
from legal_search.corpus import Article
from legal_search.registry import Law
from legal_search.search_config import DEFAULT, with_overrides
from legal_search.timing import percentiles
from tests.pg import TABLES, fresh

needs_pg = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')
BM25 = with_overrides(DEFAULT, ['ranker=bm25'])

# The fixture of test_tools.py's search tests.
CAPS = Caps(per_answer=8, daily=300, max_results=5)
LAWS = [Law(slug='civil-code', title='القانون المدني الأردني', folder='c'), Law(slug='penal-code', title='قانون العقوبات الأردني', folder='p')]
ARTICLES = [
    Article('civil-code', 'x', 1, '', 'تسري نصوص هذا القانون على المسائل التي تتناولها.', 's', 'a.md'),
    Article('civil-code', 'x', 2, '', 'يعاقب كل من خالف احكام العقد بالتعويض.', 's', 'a.md'),
    Article('penal-code', 'x', 1, '', 'لا جريمة إلا بنص.', 's', 'b.md'),
    Article('penal-code', 'x', 153, 'مكرر', 'يعاقب بالحبس كل من دخل المملكة بطريقة غير مشروعة.', 's', 'b.md'),
    Article('penal-code', 'x', 154, '', 'يعاقب بالحبس من ساعد على ذلك.', 's', 'b.md'),
]


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        await db.upsert_laws(connection, LAWS)
        await db.upsert_articles(connection, ARTICLES)
        yield connection


async def test_spans_are_collected_in_order_when_a_collector_is_set():
    with spans.collect() as got:
        async with spans.span('budget'):
            pass
        async with spans.span('search'):
            pass
    assert [name for name, _ in got] == ['budget', 'search'] and all(ms >= 0 for _, ms in got)


async def test_no_collector_means_no_spans_and_no_cost():
    async with spans.span('search'):
        pass
    assert spans.current() is None


async def test_no_collector_reads_no_clock(monkeypatch):
    # The shipping server sets no collector: a span then costs its context-manager setup only, never a clock read.
    def no_clock() -> float:
        raise AssertionError('a span read the clock with no collector set')

    monkeypatch.setattr(spans, 'time', SimpleNamespace(perf_counter=no_clock))
    async with spans.span('search'):
        pass
    assert spans.current() is None


@needs_pg
async def test_search_law_output_is_unchanged_by_spans(conn):
    # Two answers (message ids) of one user: a second call on the same message would be budgeted to what is left of it.
    plain = await tools.search_law(conn, CAPS, tools.Caller('u1', 'm-plain', 'c1'), 'يعاقب', 5)
    with spans.collect() as got:
        timed = await tools.search_law(conn, CAPS, tools.Caller('u1', 'm-timed', 'c1'), 'يعاقب', 5)

    assert plain.startswith('[1] ') and timed == plain
    assert [name for name, _ in got] == ['budget', 'search', 'guard', 'log']


# The engine-alone figure (review 2026-11-11 (b)2): with ranker=bm25, search holds the wait for an engine turn
# (engine_wait) and bm25.Index.search alone (engine).

@needs_pg
async def test_a_bm25_call_times_the_engine_inside_its_search_span(conn):
    await keyword_engine.CACHE.ensure(conn, BM25)   # built: the engine serves, not the cold fallback
    plain = await tools.search_law(conn, CAPS, tools.Caller('u1', 'm-plain', 'c1'), 'يعاقب', 5, config=BM25)

    with spans.collect() as got:
        timed = await tools.search_law(conn, CAPS, tools.Caller('u1', 'm-timed', 'c1'), 'يعاقب', 5, config=BM25)

    took = dict(got)
    assert plain.startswith('[1] ') and timed == plain
    assert [name for name, _ in got] == ['budget', 'engine_wait', 'engine', 'search', 'guard', 'log']
    assert took['engine_wait'] + took['engine'] <= took['search']


async def test_an_untimed_engine_search_reads_no_clock(monkeypatch):
    def no_clock() -> float:
        raise AssertionError('an engine search read the clock with no collector set')

    monkeypatch.setattr(keyword_engine, 'time', SimpleNamespace(perf_counter=no_clock))

    assert await keyword_engine.Searches(1).run(sorted, [3, 1, 2]) == [1, 2, 3]


async def test_engine_wait_runs_to_the_start_of_the_search_and_engine_from_there_to_its_end(monkeypatch):
    # It fails if engine is timed from the request for a turn, so that it holds the wait, or a span is in seconds.
    readings = iter([1.0, 1.5, 3.75])                # asked on the loop; started and ended in the worker thread
    monkeypatch.setattr(keyword_engine, 'time', SimpleNamespace(perf_counter=lambda: next(readings)))

    with spans.collect() as got:
        result = await keyword_engine.Searches(1).run(sorted, [3, 1, 2])

    assert result == [1, 2, 3] and got == [('engine_wait', 500.0), ('engine', 2250.0)]


def test_the_engine_spans_are_reported_and_never_subtracted_from_other_twice(tmp_path):
    path = tmp_path / 'calls.jsonl'
    path.write_text(json.dumps({'message': 'a', 'spans': [['budget', 2.0], ['engine_wait', 3.0], ['engine', 12.0],
                                                          ['search', 20.0], ['log', 4.0]], 'server_ms': 30.0}) + '\n',
                    encoding='utf-8')

    level = timing.tally([timing.Call('a', 40.0, 'served')], timing.read_span_lines(path))

    assert (level['spans_ms']['engine_wait'], level['spans_ms']['engine']) == (percentiles([3.0]), percentiles([12.0]))
    assert level['spans_ms']['other'] == percentiles([4.0])  # 30 less 2 + 20 + 4: the engine's spans are inside search


def test_timing_percentiles_are_nearest_rank():
    assert percentiles([5.0, 1.0, 3.0, 2.0, 4.0]) == {'p50': 3.0, 'p95': 5.0, 'p99': 5.0, 'max': 5.0, 'n': 5}
    # 20 values tell rank ceil(p/100 * n) from a floor index: p50 is the 10th value, p95 the 19th.
    assert percentiles([float(v) for v in range(20, 0, -1)]) == {'p50': 10.0, 'p95': 19.0, 'p99': 20.0, 'max': 20.0, 'n': 20}


def _reply(text: str, *, error: bool = False, sse: bool = False) -> str:
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'content': [{'type': 'text', 'text': text}], 'isError': error}})
    return f'event: message\ndata: {body}\n\n' if sse else body


def test_the_driver_counts_refusals_apart_from_served_lists():
    articles = '[1] القانون المدني الأردني — المادة 2\nيعاقب كل من خالف احكام العقد بالتعويض.\n(المصدر: s)'
    responses = [
        (200, _reply(articles, sse=True)),                                  # an article list: a timed search
        (200, _reply(tools.NOT_FOUND_SEARCH)),                              # the not-found text: a timed search
        (200, _reply(tools.CAP_REACHED)),                                   # a cap refusal
        (200, _reply(tools.SUSPENDED)),                                     # a suspension refusal
        (200, _reply(f'{tools.UNKNOWN_LAW}. الرموز المتاحة: civil-code.')),  # not a search
        (200, _reply(articles, error=True)),                                # a tool error, whatever its text
        (200, json.dumps({'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32602, 'message': 'invalid params'}})),
        (403, 'forbidden'),
    ]

    kinds = [timing.outcome(status, body) for status, body in responses]
    level = timing.tally([timing.Call(f'm{n}', float(n + 1), kind) for n, kind in enumerate(kinds)])

    assert kinds == ['served', 'not_found'] + ['refused'] * 6
    assert (level['timed'], level['not_found'], level['refused']) == (2, 1, 6)
    assert level['client_ms'] == percentiles([1.0, 2.0])  # refused calls are never timed as searches
    with pytest.raises(SystemExit):
        timing.require_no_refusals({'levels': [{'users': 1, **level}]})


def test_the_driver_joins_span_lines_by_message_id(tmp_path):
    path = tmp_path / 'calls.jsonl'
    path.write_text(
        json.dumps({'message': 'a', 'spans': [['lock_wait', 1.0], ['search', 20.0], ['search', 5.0], ['log', 4.0]],
                    'server_ms': 35.0})
        + '\n\n'  # a blank line is skipped
        + json.dumps({'message': 'c', 'spans': [['search', 9.0]], 'server_ms': 12.0}) + '\n',
        encoding='utf-8')
    calls = [timing.Call('a', 50.0, 'served'), timing.Call('b', 40.0, 'not_found'), timing.Call('c', 30.0, 'refused')]

    level = timing.tally(calls, timing.read_span_lines(path))

    assert (level['joined'], level['unjoined']) == (1, 1)  # b has no line; the refused c is never joined
    assert level['server_ms'] == percentiles([35.0])
    assert level['transport_ms'] == percentiles([15.0])  # the client total less the server total
    assert level['spans_ms']['search'] == percentiles([25.0])  # one call's spans of one name are summed
    assert level['spans_ms']['other'] == percentiles([5.0])  # 35 less 1 + 25 + 4
    assert level['spans_ms']['pool_wait'] == percentiles([])  # a span the line lacks is not counted as 0
    with pytest.raises(SystemExit):
        timing.require_joined({'levels': [{'users': 1, **level}]})
    timing.require_joined({'levels': [{'users': 1, **timing.tally(calls[:1], timing.read_span_lines(path))}]})
    assert timing.read_span_lines(tmp_path / 'missing.jsonl') == {}


def test_every_run_times_its_own_callers():
    # A run's users start with no history of an earlier run on the same stack (the guard loads 8 days of it).
    first, second = timing.callers('query-aaaaaa', 5), timing.callers('fused-bbbbbb', 5)
    assert len(set(first)) == 5 and not set(first) & set(second)
    assert timing.heavy_user('query-aaaaaa') != timing.heavy_user('fused-bbbbbb')
    assert all(server.PLAIN_ID.fullmatch(name) for name in [*first, *second, timing.heavy_user('query-aaaaaa')])
    tags = {timing.run_tag('query') for _ in range(5)}
    assert len(tags) == 5 and all(tag.startswith('query-') for tag in tags)
    # An empty tag gives the plan's names.
    assert timing.callers('', 2) == ['timing-2-1', 'timing-2-2'] and timing.heavy_user('') == 'timing-heavy'


def test_an_unknown_timing_switch_value_stops_the_server(monkeypatch):
    # Only 0 and 1 (or unset) are accepted: «true» would otherwise switch timing off without a word.
    monkeypatch.setenv(server.TIMING_FILE, '/spans/calls.jsonl')
    for value in ('true', 'yes', '2'):
        monkeypatch.setenv(server.TIMING_SPANS, value)
        with pytest.raises(RuntimeError):
            server.timing_file_from_env()


def test_a_span_line_that_cannot_be_written_is_logged_and_never_raised(tmp_path, caplog):
    # The tool's own answer stands (the line is written in its `finally`); the driver then counts the call as
    # unjoined and fails the run. The log names no message id.
    with caplog.at_level(logging.WARNING, logger='legal_search.server'):
        server.append_timing_line(str(tmp_path), 'm-unwritten', [('search', 1.0)], 2.0)  # a folder: open() fails
    assert len(caplog.records) == 1 and 'm-unwritten' not in caplog.text


def test_the_timing_file_is_used_only_when_the_switch_is_on(monkeypatch):
    # The shipping server reads these variables; only the timing stack sets them (compose.timing.yaml).
    monkeypatch.delenv(server.TIMING_SPANS, raising=False)
    monkeypatch.setenv(server.TIMING_FILE, '/spans/calls.jsonl')
    assert server.timing_file_from_env() is None
    monkeypatch.setenv(server.TIMING_SPANS, '0')
    assert server.timing_file_from_env() is None
    monkeypatch.setenv(server.TIMING_SPANS, '1')
    assert server.timing_file_from_env() == '/spans/calls.jsonl'
    monkeypatch.delenv(server.TIMING_FILE)
    with pytest.raises(RuntimeError):
        server.timing_file_from_env()


@needs_pg
async def test_a_timed_call_appends_one_line_of_ids_and_times_and_no_query_text(tmp_path):
    with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as plain:
        plain.execute(f'DROP TABLE IF EXISTS {TABLES} CASCADE')
    secret, path, query = secrets.token_hex(16), tmp_path / 'calls.jsonl', 'يعاقب بالحبس'
    pool = AsyncConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=2, open=False, kwargs={'autocommit': True})
    app = server.build_app(pool, CAPS, secret, ['legal-search:*'], timing_file=str(path))
    inner = app.app
    async with inner.router.lifespan_context(inner):
        async with pool.connection() as connection:
            await db.upsert_laws(connection, LAWS)
            await db.upsert_articles(connection, ARTICLES)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://legal-search:8000') as client:
            response = await client.post(
                '/mcp',
                headers={'x-iqraa-secret': secret, 'x-iqraa-user': 'u-timed', 'x-iqraa-message': 'm-timed',
                         'accept': 'application/json, text/event-stream'},
                json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                      'params': {'name': 'search_law', 'arguments': {'query': query, 'limit': 5}}},
            )

    assert timing.outcome(response.status_code, response.text) == 'served'
    lines = path.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1
    line = json.loads(lines[0])
    assert sorted(line) == ['message', 'server_ms', 'spans'] and line['message'] == 'm-timed'
    assert [name for name, _ in line['spans']] == ['lock_wait', 'pool_wait', 'guard_settings', 'budget', 'search', 'guard', 'log']
    assert all(isinstance(ms, float) and ms >= 0 for _, ms in line['spans']) and line['server_ms'] >= sum(ms for _, ms in line['spans'])
    for word in query.split():
        assert word not in lines[0] and json.dumps(word)[1:-1] not in lines[0]
