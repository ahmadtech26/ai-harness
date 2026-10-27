import asyncio
import json
import logging
import os
import subprocess
import sys

import pytest
from psycopg import AsyncConnection

from legal_search import db, flags
from legal_search.alerts import alert
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

OPENED = [{'kind': 'run', 'level': 'suspected', 'value': 12}]
ESCALATED = [{'kind': 'run', 'level': 'suspected', 'value': 12, 'after_flag': True}]


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        yield connection


@pytest.fixture
async def calls(conn):
    """Two more connections, each one call's transaction (autocommit off), as two crossing calls in flight."""
    first = await AsyncConnection.connect(os.environ['DATABASE_URL'])
    second = await AsyncConnection.connect(os.environ['DATABASE_URL'])
    yield first, second
    await first.close()
    await second.close()


async def _crossing_call(conn, user='u1'):
    """What tools._record does for a call that opens a flag: the log row, then the flag, in one transaction."""
    log_id = await db.log_retrieval(conn, user_id=user, message_id=None, conversation_id=None, tool='get_article',
                                    query='penal-code:12', article_ids=[], outcome='throttled')
    return await flags.open_new(conn, user, 'suspected', log_id, OPENED)


async def _waits_on_a_lock(conn, other):
    """True once `other`'s backend is waiting on a lock (the first call's uncommitted flag); False after 10 s.
    `conn` must be autocommit: pg_stat_activity is a snapshot per transaction, so a poll inside one
    transaction would read the same row 200 times."""
    pid = other.info.backend_pid
    for _ in range(200):
        cur = await conn.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s', (pid,))
        if (await cur.fetchone())[0] == 'Lock':
            return True
        await asyncio.sleep(0.05)
    return False


async def _count(conn, query):
    cur = await conn.execute(query)
    return (await cur.fetchone())[0]


async def test_a_user_has_at_most_one_open_flag(conn):
    first = await flags.open_new(conn, 'u1', 'suspected', 12, OPENED)

    second = await flags.open_new(conn, 'u1', 'proven', 13, OPENED)

    assert first is not None and second is None
    assert (await flags.open_flag(conn, 'u1')).id == first.id


async def test_of_two_crossing_calls_in_flight_the_second_waits_and_opens_nothing(conn, calls):
    winner, loser = calls
    opened = await _crossing_call(winner)
    pending = asyncio.create_task(_crossing_call(loser))
    blocked = await _waits_on_a_lock(conn, loser)

    await winner.commit()
    second = await asyncio.wait_for(pending, 20)
    await loser.commit()

    assert opened is not None and blocked and second is None
    assert await _count(conn, "SELECT count(*) FROM sweep_flags WHERE status = 'open'") == 1
    assert await _count(conn, 'SELECT count(*) FROM retrieval_log') == 2


async def test_when_the_first_crossing_call_rolls_back_the_waiting_call_opens_the_flag(conn, calls):
    winner, loser = calls
    await _crossing_call(winner)
    pending = asyncio.create_task(_crossing_call(loser))
    blocked = await _waits_on_a_lock(conn, loser)

    await winner.rollback()
    second = await asyncio.wait_for(pending, 20)
    await loser.commit()

    assert blocked and second is not None
    assert (await flags.open_flag(conn, 'u1')).id == second.id


async def test_escalation_raises_a_suspected_flag_to_proven_keeping_both_evidence_sets(conn):
    flag = await flags.open_new(conn, 'u1', 'suspected', 12, OPENED)

    escalated = await flags.escalate(conn, flag.id, 24, ESCALATED)

    assert (escalated.level, escalated.opened_log_id, escalated.escalated_log_id) == ('proven', 12, 24)
    assert escalated.evidence == {'opened': OPENED, 'escalated': ESCALATED}


async def test_clearing_records_who_and_when_and_moves_the_watermark(conn):
    await conn.execute("INSERT INTO retrieval_log (user_id, tool) VALUES ('u1', 'get_article'), ('u2', 'search_law')")
    await flags.open_new(conn, 'u1', 'proven', 1, OPENED)

    cleared = await flags.clear(conn, 'u1', 'staff-1', 'false positive')

    cur = await conn.execute('SELECT max(id) FROM retrieval_log')
    newest = (await cur.fetchone())[0]
    assert (cleared.status, cleared.cleared_by, cleared.clear_reason) == ('cleared', 'staff-1', 'false positive')
    assert cleared.cleared_at is not None and await flags.open_flag(conn, 'u1') is None
    assert await flags.watermark(conn, 'u1') == newest


async def test_clearing_without_an_open_flag_returns_none(conn):
    await conn.execute("INSERT INTO retrieval_log (user_id, tool) VALUES ('u1', 'get_article')")
    cleared = await flags.clear(conn, 'u1', 'staff-1', None)

    assert cleared is None and await flags.watermark(conn, 'u1') == 0


def test_an_alert_is_one_error_level_json_line(alert_caplog):
    alert('sweep_flag_opened', user_id='u1', flag_level='suspected')

    [record] = [r for r in alert_caplog.records if r.name == 'legal_search.alerts']
    assert record.levelno == logging.ERROR
    assert json.loads(record.getMessage()) == {
        'level': 'error', 'event': 'sweep_flag_opened', 'user_id': 'u1', 'flag_level': 'suspected'}


def test_an_alert_is_written_once_in_a_process_running_the_mcp_server():
    # FastMCP's constructor installs a stderr handler on the root logger, and uvicorn's logging config keeps it:
    # a propagating alert would be written twice. Run as server.main does: the server built, uvicorn configured.
    script = (
        'import logging.config, uvicorn.config\n'
        'from mcp.server.fastmcp import FastMCP\n'
        'from legal_search.alerts import alert\n'
        "FastMCP('legal-search', stateless_http=True)\n"
        'logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)\n'
        "alert('sweep_flag_opened', user_id='u1', flag_level='suspected')\n"
    )

    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=120, check=True)

    assert [line for line in result.stderr.splitlines() if '"sweep_flag_opened"' in line] == [
        '{"event": "sweep_flag_opened", "flag_level": "suspected", "level": "error", "user_id": "u1"}']
