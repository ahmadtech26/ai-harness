"""The output-contract snapshot (REQ-RAG-050): every article and every memorandum note as the library serves it."""

import asyncio
import hashlib
import os
import sys

import pytest
from psycopg import AsyncConnection

from legal_search import contract, db, tools
from legal_search.caps import Caps
from legal_search.citation import format_articles
from legal_search.contract import ContractError, snapshot
from legal_search.corpus import Article
from legal_search.registry import Law
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

# Inserted out of key order. Key order is code point order of the slug, then the number, then the suffix: «9» comes
# before «107»; 107 comes before «107 مكرر» and that before «107 مكرر ثانياً» (the corpus's two suffixes), and the
# three are inserted so that neither the database's row order nor its reverse is key order, so a sort that leaves
# the suffix out shows; «labour-law» comes before «labourers» («-» is U+002D), which a collation that skips
# punctuation (the database's en_US) would put the other way round. penal-code has no registry row: the article is
# still served.
ARTICLES = [
    Article('penal-code', 'قانون العقوبات الأردني', 153, 'مكرر', 'نص المادة المكررة.', 's', 'p.md'),
    Article('civil-code', 'القانون المدني الأردني', 107, 'مكرر', 'نص المادة 107 مكرر.', 's', 'a.md'),
    Article('labourers', 'قانون العمال', 2, '', 'نص قانون العمال.', 's', 'w.md'),
    Article('civil-code', 'القانون المدني الأردني', 107, '', 'يعتبر دفع العربون دليلا على ان العقد اصبح باتا.', 's', 'a.md'),
    Article('labour-law', 'قانون العمل', 2, '', 'نص قانون العمل.', 's', 'l.md'),
    Article('civil-code', 'القانون المدني الأردني', 107, 'مكرر ثانياً', 'نص المادة 107 مكرر ثانياً.', 's', 'a.md'),
    Article('civil-code', 'القانون المدني الأردني', 9, '', 'نص المادة التاسعة.', 's', 'a.md'),
]
LAWS = [
    Law('civil-code', 'القانون المدني الأردني', 'civil', number=43, year=1976, note='تطبق فيما لا يتعارض مع أحكام القانون المدني'),
    Law('labour-law', 'قانون العمل', 'labour', number=8, year=1996, approved=True),
    Law('labourers', 'قانون العمال', 'labourers'),
]
KEY_ORDER = ['civil-code:9', 'civil-code:107', 'civil-code:107:مكرر', 'civil-code:107:مكرر ثانياً', 'labour-law:2',
             'labourers:2', 'penal-code:153:مكرر']
# Note 166 explains 214-216 (three links: a join on the links would repeat it). Notes 74 and 75 both explain 107, so
# 75 is served second of two. Note 3 explains no article, so no tool can serve it.
NOTES = {166: 'شرح المواد.', 75: 'شرح ثان للعربون.', 74: 'شرح العربون.', 3: 'ملاحظة لا تشرح مادة.'}
LINKS = [(107, 74), (107, 75), (214, 166), (215, 166), (216, 166)]
SOURCE = 'example.test/memo'
# get_memorandum serves a page of one note under these caps.
ONE_NOTE = Caps(per_answer=100, daily=1000, max_results=1)


async def _load(connection: AsyncConnection, *, articles: bool = True, notes: bool = True) -> None:
    await fresh(connection)
    await db.upsert_laws(connection, LAWS)
    if articles:
        await db.upsert_articles(connection, ARTICLES)
    if notes:
        await db.replace_memorandum(connection, NOTES, LINKS, SOURCE)


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await _load(connection)
        yield connection


async def _served_article(conn: AsyncConnection, key: str) -> str:
    """The article as get_article formats it, alone."""
    law, number, *suffix = key.split(':')
    return format_articles([await db.get_article(conn, law, int(number), suffix[0] if suffix else '')])


async def _served_note(conn: AsyncConnection, article: int, offset: int) -> str:
    """get_memorandum's reply for `article` at `offset` when its page holds one note."""
    caller = tools.Caller('u1', f'm-{article}-{offset}', 'c1')
    return await tools.get_memorandum(conn, ONE_NOTE, caller, article, offset)


async def test_the_snapshot_holds_every_article_and_note_once(conn):
    expected = ''.join([f'@@ article {key}\n{await _served_article(conn, key)}\n' for key in KEY_ORDER]
                       + ['@@ note 3\n\n',
                          f'@@ note 74\n{await _served_note(conn, 107, 0)}\n',
                          f'@@ note 75\n{await _served_note(conn, 107, 1)}\n',
                          f'@@ note 166\n{await _served_note(conn, 214, 0)}\n'])

    data = await snapshot(conn)

    assert data == expected.encode('utf-8')


async def test_the_snapshot_changes_when_served_text_changes(conn):
    before = await snapshot(conn)

    await conn.execute("UPDATE articles SET norm = 'عربون' WHERE law_slug = 'civil-code' AND number = 107 AND suffix = ''")
    index_only = await snapshot(conn)
    await conn.execute("UPDATE articles SET text = text || ' ' WHERE law_slug = 'civil-code' AND number = 107 AND suffix = ''")
    served = await snapshot(conn)

    assert index_only == before
    assert served != before


@pytest.mark.parametrize('forge, record', [
    ("UPDATE articles SET text = text || E'\\n@@ article civil-code:1' WHERE law_slug = 'labourers'", 'article labourers:2'),
    ("UPDATE memorandum_notes SET text = E'@@ note 1\\n' || text WHERE note_no = 75", 'note 75'),
])
async def test_the_snapshot_refuses_served_text_with_a_line_like_a_key_line(conn, forge, record):
    await conn.execute(forge)

    with pytest.raises(ContractError, match=f'^{record}: '):
        await snapshot(conn)


async def test_the_tool_reads_in_one_repeatable_read_read_only_transaction(monkeypatch):
    seen = []

    async def probe(connection: AsyncConnection) -> tuple[bytes, int, int]:
        for setting in ('transaction_isolation', 'transaction_read_only'):
            cur = await connection.execute(f'SHOW {setting}')
            seen.append((await cur.fetchone())[0])
        return b'', 0, 0

    monkeypatch.setattr(contract, '_snapshot', probe)
    await contract._take(os.environ['DATABASE_URL'])

    assert seen == ['repeatable read', 'on']


def _database(**load) -> None:
    async def run() -> None:
        async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
            await _load(connection, **load)

    asyncio.run(run())


def _tool(monkeypatch, out) -> None:
    monkeypatch.setattr(sys, 'argv', ['legal-search-contract', '--out', str(out)])
    contract.main()


@pytest.mark.parametrize('articles, notes', [(False, False), (True, False), (False, True)])
def test_the_tool_refuses_a_database_without_articles_or_notes(tmp_path, monkeypatch, articles, notes):
    _database(articles=articles, notes=notes)
    out = tmp_path / 'contract.txt'

    with pytest.raises(SystemExit, match='nothing written'):
        _tool(monkeypatch, out)

    assert not out.exists()


def test_the_tool_writes_the_snapshot_into_a_new_folder_and_prints_its_sha256(tmp_path, monkeypatch, capsys):
    _database()
    out = tmp_path / 'new' / 'contract.txt'

    _tool(monkeypatch, out)

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    assert f'sha256 {digest}, 7 articles, 4 notes' in capsys.readouterr().out
