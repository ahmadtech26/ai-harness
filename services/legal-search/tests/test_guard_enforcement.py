import json
import os

import pytest
from psycopg import AsyncConnection

from legal_search import db, flags, tools
from legal_search.corpus import Article
from legal_search.guard_settings import GuardSettings
from legal_search.registry import Law
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

SETTINGS = GuardSettings()
CAPS = SETTINGS.caps
SWEEPER = tools.Caller('sweeper', None, None)  # direct MCP calls carry no message id: only the daily cap applies
LAWS = [
    Law(slug='penal-code', title='قانون العقوبات الأردني', folder='p'),
    Law(slug='labour', title='قانون العمل', folder='l'),
    Law(slug='civil-code', title='القانون المدني الأردني', folder='c'),
]
ARTICLES = (
    [Article('penal-code', 'x', n, '', f'نص المادة {n} من قانون العقوبات للاختبار.', 's', 'p.md') for n in range(1, 31)]
    + [Article('labour', 'x', n, '', f'نص المادة {n} من قانون العمل للاختبار.', 's', 'l.md') for n in range(1, 6)]
    + [Article('civil-code', 'x', 1, '', 'تسري نصوص هذا القانون على المسائل التي تتناولها.', 's', 'c.md')]
)


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        await db.upsert_laws(connection, LAWS)
        await db.upsert_articles(connection, ARTICLES)
        await db.replace_memorandum(connection, {1: 'شرح المادة الأولى.'}, [(1, 1)], 'example.test/memo')
        yield connection


async def _walk(conn, numbers, caller=SWEEPER, law='penal-code'):
    return [await tools.get_article(conn, CAPS, caller, number, law=law, guard=SETTINGS) for number in numbers]


async def _rows(conn, user='sweeper'):
    cur = await conn.execute(
        'SELECT tool, requested_law, requested_number, requested_suffix, outcome FROM retrieval_log '
        'WHERE user_id = %s ORDER BY id',
        (user,),
    )
    return await cur.fetchall()


def _alerts(alert_caplog):
    return [json.loads(r.getMessage()) for r in alert_caplog.records if r.name == 'legal_search.alerts']


def _refused(text):
    return text in (tools.CAP_REACHED, tools.SUSPENDED)


async def test_every_attempt_is_logged_with_what_it_asked_for_and_its_outcome(conn):
    await tools.search_law(conn, CAPS, SWEEPER, 'نص', 5, law='labour', guard=SETTINGS)
    await tools.get_article(conn, CAPS, SWEEPER, 7, ' مكرر ', 'penal-code', guard=SETTINGS)
    await tools.get_memorandum(conn, CAPS, SWEEPER, 1, guard=SETTINGS)

    rows = await _rows(conn)

    assert rows == [
        ('search_law', 'labour', None, None, 'served'),
        ('get_article', 'penal-code', 7, 'مكرر', 'served'),
        ('get_memorandum', 'civil-code', 1, '', 'served'),
    ]


async def test_the_twelfth_sequential_article_opens_a_suspected_flag_and_is_refused_under_the_throttle_cap(conn, alert_caplog):
    texts = await _walk(conn, range(1, 13))

    flag = await flags.open_flag(conn, 'sweeper')
    rows = await _rows(conn)
    assert [_refused(text) for text in texts] == [False] * 11 + [True]
    assert texts[11] == tools.CAP_REACHED and rows[11][4] == 'throttled'
    assert (flag.level, flag.evidence['opened'][0]['first'], flag.evidence['opened'][0]['last']) == ('suspected', 1, 12)
    assert [(a['event'], a['flag_level']) for a in _alerts(alert_caplog)] == [('sweep_flag_opened', 'suspected')]


async def test_a_suspected_user_is_served_up_to_the_throttle_cap(conn):
    await flags.open_new(conn, 'reader', 'suspected', 0, [])
    reader = tools.Caller('reader', None, None)

    texts = [
        *await _walk(conn, range(1, 28, 3), reader),
        await tools.search_law(conn, CAPS, reader, 'نص', 5, law='labour', guard=SETTINGS),  # cut to the tenth document
        *await _walk(conn, [1], reader, law='labour'),
    ]

    cur = await conn.execute(
        "SELECT cardinality(article_ids), cardinality(candidate_ids) FROM retrieval_log WHERE tool = 'search_law'")
    assert [_refused(text) for text in texts] == [False] * 10 + [True]
    assert (await _rows(conn, 'reader'))[-1][4] == 'throttled'
    assert await cur.fetchone() == (1, 5)  # the search served one article and logged the five it was decided on


async def test_the_twelfth_sequential_attempt_after_the_flag_escalates_to_proven_and_is_refused(conn, alert_caplog):
    texts = await _walk(conn, range(1, 25))

    flag = await flags.open_flag(conn, 'sweeper')
    cur = await conn.execute("SELECT max(id) FROM retrieval_log WHERE user_id = 'sweeper'")
    assert texts[12:23] == [tools.CAP_REACHED] * 11 and texts[23] == tools.SUSPENDED
    assert (flag.level, flag.escalated_log_id) == ('proven', (await cur.fetchone())[0])
    assert (flag.evidence['escalated'][0]['first'], flag.evidence['escalated'][0]['last']) == (13, 24)
    assert [a['event'] for a in _alerts(alert_caplog)] == ['sweep_flag_opened', 'sweep_flag_escalated']


async def test_a_suspended_user_is_refused_every_retrieval_logged_and_alerted(conn, alert_caplog):
    await _walk(conn, range(1, 25))
    alert_caplog.clear()

    texts = [
        await tools.search_law(conn, CAPS, SWEEPER, 'نص', 5, guard=SETTINGS),
        await tools.get_article(conn, CAPS, SWEEPER, 1, law='labour', guard=SETTINGS),
        await tools.get_memorandum(conn, CAPS, SWEEPER, 1, guard=SETTINGS),
        await tools.get_memorandum(conn, CAPS, SWEEPER, 1, offset=999, guard=SETTINGS),  # past its last note
        await tools.get_memorandum(conn, CAPS, SWEEPER, 99999, guard=SETTINGS),  # an article with no note
        await tools.search_law(conn, CAPS, SWEEPER, 'نص', 5, law='no-such-law', guard=SETTINGS),
    ]

    # The suspension comes first on every path, including get_memorandum's early answers.
    assert texts == [tools.SUSPENDED] * 6
    assert [row[4] for row in (await _rows(conn))[24:]] == ['suspended'] * 6
    assert [a['event'] for a in _alerts(alert_caplog)] == ['sweep_refused'] * 6


async def test_clearing_restores_normal_caps_and_access_without_refiring_on_old_events(conn):
    await _walk(conn, range(1, 25))
    await flags.clear(conn, 'sweeper', 'staff-1', 'reviewed')

    texts = await _walk(conn, [25, 26])

    assert ['المادة 25' in texts[0], 'المادة 26' in texts[1]] == [True, True]
    assert await flags.open_flag(conn, 'sweeper') is None
