import os

import pytest
from psycopg import AsyncConnection, errors

from legal_search import db
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

GUARD_COLUMNS = ('requested_law', 'requested_number', 'requested_suffix', 'outcome', 'candidate_ids')


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        yield connection


async def test_schema_upgrade_adds_the_request_and_outcome_columns_to_an_existing_log(conn):
    await conn.execute('DROP TABLE retrieval_log')
    await conn.execute(
        "CREATE TABLE retrieval_log (id BIGSERIAL PRIMARY KEY, user_id TEXT NOT NULL, message_id TEXT, "
        "conversation_id TEXT, tool TEXT NOT NULL, query TEXT, article_ids BIGINT[] NOT NULL DEFAULT '{}', "
        "note_ids BIGINT[] NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    await conn.execute("INSERT INTO retrieval_log (user_id, tool, query) VALUES ('u0', 'search_law', 'old row')")

    await db.create_schema(conn)

    cur = await conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'retrieval_log' "
        'AND column_name = ANY (%s) ORDER BY column_name',
        (list(GUARD_COLUMNS),),
    )
    assert [row[0] for row in await cur.fetchall()] == sorted(GUARD_COLUMNS)
    cur = await conn.execute("SELECT outcome, candidate_ids FROM retrieval_log WHERE user_id = 'u0'")
    assert await cur.fetchone() == ('served', [])
    with pytest.raises(errors.CheckViolation):
        await conn.execute("INSERT INTO retrieval_log (user_id, tool, outcome) VALUES ('u0', 'get_article', 'refused')")


async def test_log_retrieval_records_the_request_and_outcome_and_returns_the_row_id(conn):
    log_id = await db.log_retrieval(
        conn, user_id='u1', message_id=None, conversation_id=None, tool='get_article',
        query='penal-code:153مكرر', article_ids=[], requested_law='penal-code', requested_number=153,
        requested_suffix='مكرر', outcome='throttled',
    )
    search_id = await db.log_retrieval(
        conn, user_id='u1', message_id=None, conversation_id=None, tool='search_law', query='عقد',
        article_ids=[7], candidate_ids=[7, 9],
    )

    cur = await conn.execute(
        'SELECT id, requested_law, requested_number, requested_suffix, outcome, candidate_ids FROM retrieval_log '
        'WHERE user_id = %s ORDER BY id',
        ('u1',),
    )
    assert await cur.fetchall() == [
        (log_id, 'penal-code', 153, 'مكرر', 'throttled', []),
        (search_id, None, None, None, 'served', [7, 9]),
    ]
