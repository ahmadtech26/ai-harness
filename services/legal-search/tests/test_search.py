import os

import pytest
from psycopg import AsyncConnection

from legal_search import db
from legal_search.corpus import Article
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

ARTICLES = [
    Article('civil-code', 'القانون المدني الأردني', 107, '', 'يعتبر دفع العربون دليلا على ان العقد اصبح باتا.', 's', 'a.md'),
    Article('civil-code', 'القانون المدني الأردني', 108, '', 'لا يجوز العدول عن العقد الا بالتراضي.', 's', 'a.md'),
    Article('civil-code', 'القانون المدني الأردني', 465, '', 'البيع تمليك مال او حق مالي لقاء عوض.', 's', 'b.md'),
]


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        await db.upsert_articles(connection, ARTICLES)
        yield connection


async def test_finds_an_article_across_spelling_variants(conn):
    found = await db.search(conn, 'ما حكم العربون؟', 5)

    assert [a.label for a in found][0] == 'المادة 107'


async def test_hamza_in_the_query_does_not_matter(conn):
    assert [a.label for a in await db.search(conn, 'أصبح العقد باتاً', 5)][0] == 'المادة 107'


async def test_function_words_alone_find_nothing(conn):
    assert await db.search(conn, 'ما هو في من على', 5) == []


async def test_respects_the_limit(conn):
    assert len(await db.search(conn, 'العقد', 1)) == 1


async def test_reingesting_updates_instead_of_duplicating(conn):
    await db.upsert_articles(conn, ARTICLES)

    cur = await conn.execute('SELECT count(*) FROM articles')
    assert (await cur.fetchone())[0] == 3


async def test_gets_an_article_by_number(conn):
    article = await db.get_article(conn, 'civil-code', 465, '')

    assert article is not None and article.label == 'المادة 465' and not article.verified


async def test_counts_retrievals_per_answer_and_per_day(conn):
    await db.log_retrieval(conn, user_id='u1', message_id='m1', conversation_id='c1', tool='search_law', query='q', article_ids=[1, 2])
    await db.log_retrieval(conn, user_id='u1', message_id='m2', conversation_id='c1', tool='get_article', query='q', article_ids=[3])

    assert await db.documents_for_message(conn, 'm1') == 2
    assert await db.documents_for_user_today(conn, 'u1') == 3
    assert await db.documents_for_user_today(conn, 'u2') == 0
