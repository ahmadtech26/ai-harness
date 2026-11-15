"""The texts already served to one answer (plan 2026-11-14 S5a; RP 6.4): what the per-answer count, a repeated fetch
and a search's skip read from the retrieval log."""

import os

import pytest
from psycopg import AsyncConnection

from legal_search import db, post_search
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        yield connection


async def _log(conn, message, article_ids=(), note_ids=()):
    await db.log_retrieval(conn, user_id='u1', message_id=message, conversation_id='c1', tool='search_law', query='q',
                           article_ids=list(article_ids), note_ids=list(note_ids))


async def test_the_per_answer_count_counts_a_text_once(conn):
    await _log(conn, 'm1', [1, 2, 3])
    await _log(conn, 'm1', [3, 2, 4], [7])
    await _log(conn, 'm1', [1], [7, 8])

    assert await db.documents_for_message(conn, 'm1') == 4 + 2  # articles 1-4, notes 7 and 8


async def test_served_ids_are_this_answer_only(conn):
    await _log(conn, 'm1', [1, 2], [7])
    await _log(conn, 'm1', [2, 3])
    await _log(conn, 'm2', [4], [8])

    assert await post_search.served_ids_for_message(conn, 'm1') == frozenset({1, 2, 3})
    assert await post_search.served_note_ids_for_message(conn, 'm1') == frozenset({7})
    assert await post_search.served_ids_for_message(conn, None) == frozenset()  # a call without a message id
