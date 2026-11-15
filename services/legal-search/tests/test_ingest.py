import json
import os
import shutil
from dataclasses import replace as with_changes
from datetime import date
from pathlib import Path

import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from legal_search import db
from legal_search.citation import UNVERIFIED, format_articles
from legal_search.corpus import Article
from legal_search.corrections import load_corrections
from legal_search.headings import extract
from legal_search.ingest import IngestError, ingest, prepare
from legal_search.memorandum import MemorandumError
from legal_search.registry import load_registry
from legal_search.verification import text_sha256
from tests.pg import TABLES, fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

TWO = '### المادة 1\n\nنص المادة الأولى من القانون.\n\n---\n\n### المادة 2\n\nنص المادة الثانية من القانون.\n'
ONE = '### المادة 1\n\nنص المادة الأولى من القانون.\n'
# Article 1 ends with the title of what follows (O-42): a short unpunctuated paragraph after a sentence end, which
# headings.extract makes article 2's heading. Article 1's text keeps it.
TITLED = (
    '### المادة 1\n\nنص المادة الأولى من القانون.\n\nالفصل الثاني احكام العقد\n\n---\n\n'
    '### المادة 2\n\nنص المادة الثانية من القانون.\n'
)


def _sources(tmp_path: Path, body: str, count: int) -> tuple[Path, Path, Path]:
    corpus = tmp_path / 'corpus'
    (corpus / 'civil' / 'sections').mkdir(parents=True, exist_ok=True)
    (corpus / 'civil' / 'sections' / '00.md').write_text('---\nparent_law: x\nsource: example.test\n---\n\n' + body, encoding='utf-8')
    (corpus / 'law-directory.md').write_text(
        '| القانون | slug | المواد | الأقسام | الحالة | الفئة |\n|---|---|---|---|---|---|\n'
        f'| law | `civil` | {count} | 1 | complete | x |\n',
        encoding='utf-8',
    )
    # Note 1 ends with the heading of note 2 (article 2); no heading precedes note 1, so a correction names its article.
    notes = {'1': 'شرح أول. المذكرة الايضاحية للمادة (2)', '2': 'شرح ثانٍ.'}
    (corpus / 'memorandum_civil_law.json').write_text(
        json.dumps({'source': 'example.test/memo', 'articles': notes}, ensure_ascii=False), encoding='utf-8'
    )
    registry = tmp_path / 'laws.json'
    entry = {'slug': 'civil-code', 'title': 'القانون المدني الأردني', 'folder': 'civil',
             'review': {'status': 'draft'}, 'sources': {'title': 'https://example.test'}}
    registry.write_text(json.dumps({'laws': [entry]}, ensure_ascii=False), encoding='utf-8')
    corrections = tmp_path / 'corrections.json'
    first_note = {'note': 1, 'articles': [1], 'reason': 'no heading precedes note 1', 'evidence': 'test'}
    corrections.write_text(
        json.dumps({'review': {'status': 'draft'}, 'corrections': [], 'memorandum': [first_note]}), encoding='utf-8'
    )
    return registry, corrections, corpus


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        yield connection


async def _count(conn, table: str) -> int:
    cur = await conn.execute(f'SELECT count(*) FROM {table}')
    return (await cur.fetchone())[0]


async def test_ingest_loads_laws_articles_and_the_memorandum(conn, tmp_path: Path):
    await ingest(os.environ['DATABASE_URL'], *_sources(tmp_path, TWO, 2))

    counts = [await _count(conn, table) for table in ('laws', 'articles', 'memorandum_notes', 'memorandum_links')]
    assert counts == [1, 2, 2, 2]


async def test_ingesting_again_keeps_ids_and_drops_removed_articles(conn, tmp_path: Path):
    await ingest(os.environ['DATABASE_URL'], *_sources(tmp_path, TWO, 2))
    cur = await conn.execute("SELECT id FROM articles WHERE law_slug = 'civil-code' AND number = 1")
    first_id = (await cur.fetchone())[0]

    await ingest(os.environ['DATABASE_URL'], *_sources(tmp_path, ONE, 1))

    cur = await conn.execute("SELECT id, number FROM articles WHERE law_slug = 'civil-code'")
    assert await cur.fetchall() == [(first_id, 1)]


async def test_a_failed_check_writes_nothing(conn, tmp_path: Path):
    with pytest.raises(IngestError, match='civil-code: parsed 2 articles, expected 3'):
        await ingest(os.environ['DATABASE_URL'], *_sources(tmp_path, TWO, 3))
    # The memorandum is checked before any write too: without note 1's correction it cannot load.
    registry, corrections, corpus = _sources(tmp_path / 'memo', TWO, 2)
    corrections.write_text(json.dumps({'review': {'status': 'draft'}, 'corrections': []}), encoding='utf-8')
    with pytest.raises(MemorandumError, match='memorandum note 1 has no readable heading'):
        await ingest(os.environ['DATABASE_URL'], registry, corrections, corpus)

    assert await _count(conn, 'laws') == 0


# The heading field (recall plan Task 3.4, review 2026-11-11 (f)): stored once from the text as published, index-only.

CIVIL = 'القانون المدني الأردني'


def _prepared(tmp_path: Path, body: str, count: int) -> list[Article]:
    registry, corrections, corpus = _sources(tmp_path, body, count)
    return prepare(load_registry(registry), load_corrections(corrections), corpus).articles['civil-code']


async def _stored(conn) -> list[tuple]:
    cur = await conn.execute('SELECT number, text, heading, heading_origin FROM articles ORDER BY number')
    return await cur.fetchall()


async def test_ingest_stores_the_extracted_heading_and_leaves_text_unchanged(conn, tmp_path: Path):
    await ingest(os.environ['DATABASE_URL'], *_sources(tmp_path, TITLED, 2))

    assert await _stored(conn) == [
        (1, 'نص المادة الأولى من القانون.\n\nالفصل الثاني احكام العقد', '', 'site'),
        (2, 'نص المادة الثانية من القانون.', 'الفصل الثاني احكام العقد', 'site'),
    ]


async def test_format_articles_is_byte_identical_with_headings_present(conn, tmp_path: Path):
    # REQ-RAG-050: the heading feeds the keyword index only; what the library serves does not change with it. Before:
    # a database from before Task 3.4, without the columns; after: create_schema adds them and the headings are stored.
    articles = _prepared(tmp_path, TITLED, 2)
    await conn.execute('ALTER TABLE articles DROP COLUMN heading, DROP COLUMN heading_origin')
    await db.upsert_articles(conn, articles)
    before = format_articles([await db.get_article(conn, 'civil-code', number, '') for number in (1, 2)])

    await db.create_schema(conn)
    await db.upsert_articles(conn, articles, extract(articles))
    after = format_articles([await db.get_article(conn, 'civil-code', number, '') for number in (1, 2)])

    assert [row[2] for row in await _stored(conn)] == ['', 'الفصل الثاني احكام العقد']   # the heading is there
    assert after.encode('utf-8') == before.encode('utf-8')


async def test_an_upsert_without_headings_keeps_the_stored_heading_and_its_origin(conn):
    # A later rewrite of the text (an O-42 clean-up) never re-derives or clears a heading stored from the published text.
    article = Article('civil-code', CIVIL, 2, '', 'نص المادة الثانية من القانون.', 's', '00.md')
    await db.upsert_articles(conn, [article], {('civil-code', 2, ''): 'الفصل الثاني احكام العقد'})

    await db.upsert_articles(conn, [with_changes(article, text='نص منقح.')])

    assert await _stored(conn) == [(2, 'نص منقح.', 'الفصل الثاني احكام العقد', 'site')]


async def test_headings_missing_an_article_are_refused_before_anything_is_written(conn):
    first = Article('civil-code', CIVIL, 1, '', 'نص المادة الأولى.', 's', '00.md')
    second = with_changes(first, number=2, text='نص المادة الثانية.')

    with pytest.raises(KeyError):
        await db.upsert_articles(conn, [first, second], {('civil-code', 1, ''): ''})

    assert await _count(conn, 'articles') == 0


# Verification (owner's instructions 2026-11-14 §3): set from the records beside the registry on every run, NULL otherwise.

FIRST = 'نص المادة الأولى من القانون.'
GAZETTE = {'method': 'text', 'original': {'issue': 2645, 'date': '1976-08-01', 'page': 2}, 'amendments': [],
           'text_sha256': None, 'checked_on': '2026-11-14'}
BUREAU = {'legislation_id': 536, 'url': None, 'as_of': '2026-10-01', 'text_sha256': None, 'checked_on': '2026-11-14'}


def _records(registry: Path, *lines: dict) -> None:
    folder = registry.parent / 'verification'
    folder.mkdir(exist_ok=True)
    (folder / 'civil-code.jsonl').write_text(
        ''.join(json.dumps(line, ensure_ascii=False) + '\n' for line in lines), encoding='utf-8')


def _record(number: int, text: str, result: str = 'verified') -> dict:
    return {'law_slug': 'civil-code', 'number': number, 'suffix': '', 'text_sha256': text_sha256(text),
            'result': result, 'reason': None, 'differs_from': None, 'difference': None, 'checked_on': '2026-11-14',
            'normalisation': 'v1', 'gazette': GAZETTE if result == 'verified' else None,
            'bureau': BUREAU if result == 'verified' else None, 'notes': '', 'lawyer_item': None}


async def _verification_columns(conn) -> list[tuple]:
    cur = await conn.execute('SELECT number, verified_at, verified_gazette, verified_bureau FROM articles ORDER BY number')
    return await cur.fetchall()


VERIFIED_ROW = (1, date(2026, 11, 14), [{'issue': '2645', 'page': '2'}], {'legislation_id': '536', 'as_of': '2026-10-01'})


async def test_ingest_verifies_an_article_whose_record_is_verified_for_the_text_it_stores(conn, tmp_path: Path):
    registry, corrections, corpus = _sources(tmp_path, TWO, 2)
    _records(registry, _record(1, FIRST), _record(2, 'نص المادة الثانية من القانون.', 'unverifiable'))

    _, _, matched = await ingest(os.environ['DATABASE_URL'], registry, corrections, corpus)

    assert matched.problems == []
    assert await _verification_columns(conn) == [VERIFIED_ROW, (2, None, None, None)]
    served = format_articles([await db.get_article(conn, 'civil-code', 1, '')])
    assert served.splitlines()[2] == (
        '(المصدر: الجريدة الرسمية وديوان التشريع والرأي — متحقق منه: الجريدة الرسمية العدد 2645 ص 2، ديوان التشريع '
        'والرأي معرّف التشريع 536 بصيغته في 1/10/2026، تاريخ التحقق 14/11/2026؛ بيانات النشر لم يُتحقق منها بعد)')
    assert 'المصدر: نسخة المكتبة، غير رسمية — ' in format_articles([await db.get_article(conn, 'civil-code', 2, '')])


async def test_a_changed_text_or_a_removed_record_sets_the_columns_back_to_null(conn, tmp_path: Path):
    registry, corrections, corpus = _sources(tmp_path, TWO, 2)
    _records(registry, _record(1, FIRST), _record(2, 'نص المادة الثانية من القانون.', 'unverifiable'))
    await ingest(os.environ['DATABASE_URL'], registry, corrections, corpus)
    assert (await _verification_columns(conn))[0] == VERIFIED_ROW

    # The text changes and the record does not: the record no longer binds, and the earlier run's values go.
    changed = TWO.replace(FIRST, 'نص المادة الأولى من القانون بعد التعديل.')
    _, _, matched = await ingest(os.environ['DATABASE_URL'], *_sources(tmp_path, changed, 2))

    assert await _verification_columns(conn) == [(1, None, None, None), (2, None, None, None)]
    assert len(matched.problems) == 1 and 'civil-code المادة 1 is verified for text_sha256' in matched.problems[0]
    assert f'— {UNVERIFIED}؛ ' in format_articles([await db.get_article(conn, 'civil-code', 1, '')])

    # Back to the recorded text, then without the folder: verified, then NULL again.
    await ingest(os.environ['DATABASE_URL'], *_sources(tmp_path, TWO, 2))
    assert (await _verification_columns(conn))[0] == VERIFIED_ROW
    shutil.rmtree(registry.parent / 'verification')
    _, _, matched = await ingest(os.environ['DATABASE_URL'], *_sources(tmp_path, TWO, 2))
    assert (await _verification_columns(conn), matched.files) == ([(1, None, None, None), (2, None, None, None)], 0)


# A database of the previous image (owner, point 10 (c)): built with its schema, tests/fixtures/schema-recall-plan-649559a.sql
# (db.SCHEMA on recall-plan 649559a, before verification and provenance), with a row in each table the library and the
# log use, every column set.

PREVIOUS_SCHEMA = (Path(__file__).parent / 'fixtures' / 'schema-recall-plan-649559a.sql').read_text(encoding='utf-8')
# The columns the schema step adds to that database, table by table, in order: (name, type, what an existing row holds).
ADDED = {
    'articles': [('verified_gazette', 'jsonb', None), ('verified_bureau', 'jsonb', None), ('provenance', 'text', '')],
    'laws': [('instrument', 'text', 'law')],
    'memorandum_notes': [('provenance', 'text', '')],
}
_PREVIOUS_ROWS = [
    ("INSERT INTO laws (slug, title, number, year, gazette_issue, gazette_date, gazette_url, amendment_law, amendment_year, "
     "amendment_gazette_issue, amendment_gazette_date, amendment_url, note, approved) VALUES ('civil-code', 'قانون قديم', "
     "99, 1900, 1234, '1900-03-02', 'https://example.test/g', 7, 1950, 4321, '1950-06-05', 'https://example.test/a', "
     "'ملاحظة قديمة', true)"),
    # verified_at was in the previous image's table and never written by it: one set by hand counts for nothing.
    ("INSERT INTO articles (law_slug, law_title, number, suffix, label, text, norm, source, shard, verified_at, heading, "
     "heading_origin) VALUES ('civil-code', 'x', 1, '', 'المادة 1', 'نص قديم.', 'نص قديم', 'example.test/old', '00.md', "
     "'2026-01-01', 'عنوان قديم', 'site')"),
    "INSERT INTO memorandum_notes (note_no, text, source) VALUES (1, 'شرح قديم.', 'example.test/old-memo')",
    'INSERT INTO memorandum_links (article_number, note_no) VALUES (1, 1)',
    ("INSERT INTO retrieval_log (user_id, message_id, conversation_id, tool, query, article_ids, note_ids, requested_law, "
     "requested_number, requested_suffix, outcome, candidate_ids) VALUES ('u1', 'm1', 'c1', 'get_article', 'العربون', "
     "'{1}', '{1}', 'civil-code', 1, 'مكرر', 'capped', '{1,2}')"),
    'UPDATE index_state SET version = 7',
]


async def _previous_database(conn) -> None:
    await conn.execute(f'DROP TABLE IF EXISTS {TABLES} CASCADE')
    await conn.execute(PREVIOUS_SCHEMA)
    for statement in _PREVIOUS_ROWS:
        await conn.execute(statement)


async def _columns(conn) -> dict[str, list[tuple[str, str]]]:
    """Each table's (column, type), in column order."""
    cur = await conn.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' "
        "ORDER BY table_name, ordinal_position")
    columns: dict[str, list[tuple[str, str]]] = {}
    for table, column, data_type in await cur.fetchall():
        columns.setdefault(table, []).append((column, data_type))
    return columns


async def _rows(conn, table: str, columns: list[str]) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f'SELECT {", ".join(columns)} FROM {table}')
        return sorted(await cur.fetchall(), key=repr)


async def test_the_schema_step_leaves_every_row_of_a_previous_database_as_it_was(conn):
    await _previous_database(conn)
    columns = await _columns(conn)
    before = {table: await _rows(conn, table, [name for name, _ in cols]) for table, cols in columns.items()}
    assert all(before[table] for table in ('laws', 'articles', 'memorandum_notes', 'memorandum_links', 'retrieval_log',
                                           'index_state'))

    await db.create_schema(conn)
    await db.create_schema(conn)  # every start runs it: a second run changes nothing

    now = await _columns(conn)
    assert list(now) == list(columns)  # no table added or dropped
    for table, cols in columns.items():
        added = ADDED.get(table, [])
        assert now[table] == cols + [(name, data_type) for name, data_type, _ in added], table
        # Every value a row had is still there, and each new column holds its default.
        assert await _rows(conn, table, [name for name, _ in cols]) == before[table], table
        if added:
            new = await _rows(conn, table, [name for name, _, _ in added])
            assert new == [{name: value for name, _, value in added}] * len(before[table]), table


async def test_an_ingest_brings_a_database_of_the_previous_image_forward(conn, tmp_path: Path):
    await _previous_database(conn)

    await ingest(os.environ['DATABASE_URL'], *_sources(tmp_path, TWO, 2))

    # The copy site in provenance, and the same in source, which the previous image prints until it is recreated; the
    # verified_at no record backs is cleared, and the registry entry, without an instrument, is a law.
    cur = await conn.execute('SELECT number, provenance, source, verified_at FROM articles ORDER BY number')
    assert await cur.fetchall() == [(1, 'example.test', 'example.test', None), (2, 'example.test', 'example.test', None)]
    cur = await conn.execute('SELECT note_no, provenance, source FROM memorandum_notes ORDER BY note_no')
    assert await cur.fetchall() == [(1, 'example.test/memo', 'example.test/memo'),
                                    (2, 'example.test/memo', 'example.test/memo')]
    cur = await conn.execute('SELECT slug, title, instrument FROM laws')
    assert await cur.fetchall() == [('civil-code', 'القانون المدني الأردني', 'law')]


async def test_the_ingest_stores_the_registry_instrument_and_the_citation_follows_it(conn, tmp_path: Path):
    registry, corrections, corpus = _sources(tmp_path, TWO, 2)
    laws = json.loads(registry.read_text(encoding='utf-8'))
    laws['laws'][0] |= {'title': 'جدول رسوم المحاكم', 'number': 43, 'year': 2005, 'instrument': 'regulation',
                        'amendment': {'law': 108, 'year': 2008}}
    registry.write_text(json.dumps(laws, ensure_ascii=False), encoding='utf-8')

    await ingest(os.environ['DATABASE_URL'], registry, corrections, corpus)

    cur = await conn.execute('SELECT slug, instrument FROM laws')
    assert await cur.fetchall() == [('civil-code', 'regulation')]
    lines = format_articles([await db.get_article(conn, 'civil-code', 1, '')]).splitlines()
    assert lines[0] == '[1] جدول رسوم المحاكم، نظام رقم 43 لسنة 2005 — المادة 1'
    assert lines[2].startswith('(آخر تعديل: النظام المعدِّل رقم 108 لسنة 2008؛ المصدر: ')
