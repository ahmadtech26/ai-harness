import os
from datetime import date

import pytest
from psycopg import AsyncConnection

from legal_search import db
from legal_search.corpus import Article
from legal_search.registry import Law
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

# Fixture values are deliberately not real citation data.
PENAL = Law(slug='penal-code', title='قانون العقوبات الأردني', folder='p', number=99, year=1900,
            gazette_issue=1234, gazette_date=date(1900, 3, 2), note='ملاحظة اختبار')
LABOUR = Law(slug='labour', title='قانون العمل', folder='l')
ARTICLES = [
    Article('penal-code', 'عنوان الشريحة', 153, 'مكرر', 'يعاقب بالحبس كل من دخل المملكة بطريقة غير مشروعة.', 's', 'a.md'),
    Article('labour', 'عنوان الشريحة', 20, '', 'يعاقب صاحب العمل بالحبس او الغرامة عند المخالفة.', 's', 'b.md'),
]


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        # An earlier load with other values: the second upsert must update them (a lawyer's approval and the
        # researched metadata reach an existing database this way).
        await db.upsert_laws(connection, [Law(slug='penal-code', title='عنوان قديم', folder='p', approved=True)])
        await db.upsert_laws(connection, [PENAL, LABOUR])
        await db.upsert_articles(connection, ARTICLES)
        yield connection


async def test_search_with_a_law_returns_only_that_law(conn):
    found = await db.search(conn, 'يعاقب بالحبس', 5, law='labour')

    assert [a.law_slug for a in found] == ['labour']


async def test_found_carries_law_slug_number_and_suffix(conn):
    [found] = await db.search(conn, 'المملكة', 5)

    assert (found.law_slug, found.number, found.suffix) == ('penal-code', 153, 'مكرر')


async def test_found_carries_the_registry_title_and_citation_fields(conn):
    found = await db.get_article(conn, 'penal-code', 153, 'مكرر')

    assert found.law_title == 'قانون العقوبات الأردني'
    assert (found.law.number, found.law.year, found.law.gazette_issue, found.law.gazette_date, found.law.note, found.law.approved) == (
        99, 1900, 1234, date(1900, 3, 2), 'ملاحظة اختبار', False)


async def test_pruning_drops_articles_no_longer_in_the_source(conn):
    deleted = await db.prune_articles(conn, 'penal-code', {(1, '')})

    assert deleted == 1
    assert await db.get_article(conn, 'penal-code', 153, 'مكرر') is None
    assert await db.get_article(conn, 'labour', 20, '') is not None


async def test_schema_upgrade_adds_note_ids_to_an_existing_log(conn):
    await conn.execute('DROP TABLE retrieval_log')
    await conn.execute(
        "CREATE TABLE retrieval_log (id BIGSERIAL PRIMARY KEY, user_id TEXT NOT NULL, message_id TEXT, "
        "conversation_id TEXT, tool TEXT NOT NULL, query TEXT, article_ids BIGINT[] NOT NULL DEFAULT '{}', "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )

    await db.create_schema(conn)

    cur = await conn.execute(
        "SELECT count(*) FROM information_schema.columns WHERE table_name = 'retrieval_log' AND column_name = 'note_ids'"
    )
    assert (await cur.fetchone())[0] == 1


async def test_cap_sums_count_articles_and_notes(conn):
    await db.log_retrieval(conn, user_id='u1', message_id='m1', conversation_id='c1', tool='get_article', query='q', article_ids=[1])
    await db.log_retrieval(conn, user_id='u1', message_id='m1', conversation_id='c1', tool='get_memorandum', query='q',
                           article_ids=[], note_ids=[9, 20, 21])

    assert await db.documents_for_message(conn, 'm1') == 4
    assert await db.documents_for_user_today(conn, 'u1') == 4
