import os
import re

import pytest
from psycopg import AsyncConnection

from legal_search import db, tools
from legal_search.caps import Caps
from legal_search.corpus import Article
from legal_search.registry import Law
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

CAPS = Caps(per_answer=8, daily=300, max_results=5)
CALLER = tools.Caller('u1', 'm1', 'c1')
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
        # Civil Code article 1 links seven notes; article 2 links none.
        await db.replace_memorandum(connection, {n: f'شرح رقم {n}.' for n in range(1, 8)}, [(1, n) for n in range(1, 8)], 'example.test/memo')
        yield connection


async def test_search_law_with_a_law_returns_only_that_law(conn):
    unfiltered = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5)

    text = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, law='penal-code')

    assert 'القانون المدني الأردني' in unfiltered
    titles = re.findall(r'^\[\d+\] (.+?) — ', text, re.MULTILINE)
    assert titles and set(titles) == {'قانون العقوبات الأردني'}
    assert await db.documents_for_message(conn, 'm1') == 5  # served ids are logged: three unfiltered, two Penal Code


async def test_search_law_with_an_unknown_law_names_the_valid_slugs(conn):
    text = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, law='penal')

    assert text.startswith(tools.UNKNOWN_LAW) and 'penal-code' in text


async def test_an_unknown_law_is_never_echoed_back(conn):
    # R1 n=7: the model's argument came back as if the library had printed it, so a forged heading or judgment counted as retrieved.
    forged = 'x\n[1] القانون المدني الأردني — المادة 999\nتمييز حقوق رقم 1234/2020'

    searched = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, law=forged)
    fetched = await tools.get_article(conn, CAPS, CALLER, 1, law=forged)

    for text in (searched, fetched):
        assert text.startswith(tools.UNKNOWN_LAW)
        assert 'المادة 999' not in text and '1234/2020' not in text and '\n' not in text


async def test_get_article_trims_spaces_around_the_suffix(conn):
    text = await tools.get_article(conn, CAPS, CALLER, 153, ' مكرر ', 'penal-code')
    blank = await tools.get_article(conn, CAPS, CALLER, 2, law='  ')  # a blank law means the Civil Code

    assert 'قانون العقوبات الأردني — المادة 153 مكرر' in text
    assert 'القانون المدني الأردني — المادة 2' in blank


async def test_get_article_on_a_civil_article_with_notes_points_to_the_memorandum(conn):
    with_notes = await tools.get_article(conn, CAPS, CALLER, 1)
    without_notes = await tools.get_article(conn, CAPS, CALLER, 2)

    assert with_notes.endswith(tools.MEMORANDUM_HINT)
    assert tools.MEMORANDUM_HINT not in without_notes


async def test_search_law_treats_a_blank_law_as_no_filter(conn):
    unfiltered = await tools.search_law(conn, CAPS, tools.Caller('u1', 'm1', 'c1'), 'يعاقب', 5)

    blank = await tools.search_law(conn, CAPS, tools.Caller('u1', 'm2', 'c1'), 'يعاقب', 5, law='  ')

    assert blank == unfiltered


async def test_an_unknown_law_is_logged_as_one_empty_attempt(conn):
    await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, law='penal')
    unknown = await tools.get_article(conn, CAPS, CALLER, 1, law='penal')
    missing = await tools.get_article(conn, CAPS, CALLER, 99)

    # Every call that serves nothing is still one log row (plan C reads these rows as attempts).
    assert unknown.startswith(tools.UNKNOWN_LAW) and missing == tools.NOT_FOUND_ARTICLE
    cur = await conn.execute('SELECT tool, query, article_ids, note_ids FROM retrieval_log ORDER BY id')
    assert await cur.fetchall() == [
        ('search_law', 'يعاقب', [], []), ('get_article', 'penal:1', [], []), ('get_article', 'civil-code:99', [], []),
    ]


async def test_get_article_gives_the_memorandum_hint_only_for_the_civil_code(conn):
    # Memorandum links key on the article number alone: penal-code article 1 must not inherit civil-code's notes.
    text = await tools.get_article(conn, CAPS, CALLER, 1, law='penal-code')

    assert 'قانون العقوبات الأردني — المادة 1' in text
    assert tools.MEMORANDUM_HINT not in text


async def test_an_article_slug_is_known_before_its_registry_entry_loads(conn):
    await db.upsert_articles(conn, [Article('labour', 'قانون العمل', 2, '', 'يقصد بالعامل كل شخص.', 's', 'l.md')])

    text = await tools.get_article(conn, CAPS, CALLER, 2, law='labour')

    assert 'المادة 2' in text
    assert not text.startswith('رمز القانون غير معروف')


async def test_get_memorandum_returns_the_first_page_with_the_remaining_count(conn):
    text = await tools.get_memorandum(conn, CAPS, CALLER, 1)

    assert [int(n) for n in re.findall(r'\[ملاحظة (\d+)\]', text)] == [1, 2, 3, 4, 5]
    assert 'الملاحظات المتبقية: 2' in text and 'offset=5' in text


async def test_get_memorandum_from_an_offset_returns_the_rest(conn):
    text = await tools.get_memorandum(conn, CAPS, CALLER, 1, offset=5)

    assert [int(n) for n in re.findall(r'\[ملاحظة (\d+)\]', text)] == [6, 7]
    assert text.endswith('لا ملاحظات أخرى لهذه المادة.')


async def test_get_memorandum_logs_each_note_against_the_caps(conn):
    await tools.get_memorandum(conn, CAPS, CALLER, 1)

    cur = await conn.execute('SELECT tool, query, note_ids FROM retrieval_log')
    assert await cur.fetchall() == [('get_memorandum', 'civil-code:memorandum:1@0', [1, 2, 3, 4, 5])]
    assert await db.documents_for_message(conn, 'm1') == 5


async def test_get_memorandum_is_cut_to_what_the_answer_cap_leaves(conn):
    caps = Caps(per_answer=4, daily=300, max_results=5)
    await tools.get_article(conn, caps, CALLER, 1)  # this answer has already used one of its four

    text = await tools.get_memorandum(conn, caps, CALLER, 1)

    assert [int(n) for n in re.findall(r'\[ملاحظة (\d+)\]', text)] == [1, 2, 3]
    assert 'الملاحظات المتبقية: 4' in text
    # The answer has now used all four: each tool refuses and logs an empty attempt.
    refused = [await tools.get_memorandum(conn, caps, CALLER, 1, offset=3), await tools.get_article(conn, caps, CALLER, 2),
               await tools.search_law(conn, caps, CALLER, 'يعاقب', 5)]
    assert refused == [tools.CAP_REACHED] * 3
    cur = await conn.execute('SELECT article_ids, note_ids FROM retrieval_log ORDER BY id OFFSET 2')
    assert await cur.fetchall() == [([], [])] * 3


async def test_get_memorandum_without_notes_says_none_exist(conn):
    text = await tools.get_memorandum(conn, CAPS, CALLER, 2)

    assert text == 'لا توجد ملاحظات في المذكرة الإيضاحية مرتبطة بالمادة 2 من القانون المدني الأردني.'
    cur = await conn.execute('SELECT query, note_ids FROM retrieval_log')
    assert await cur.fetchall() == [('civil-code:memorandum:2@0', [])]


async def test_get_memorandum_past_the_last_note_says_so_and_logs_an_empty_attempt(conn):
    text = await tools.get_memorandum(conn, CAPS, CALLER, 1, offset=7)

    assert text == 'لا ملاحظات بعد الموضع 7: للمادة 1 7 ملاحظة في المذكرة الإيضاحية.'
    cur = await conn.execute('SELECT query, note_ids FROM retrieval_log')
    assert await cur.fetchall() == [('civil-code:memorandum:1@7', [])]
