import json
import os
import shutil
from dataclasses import replace as with_changes
from datetime import date
from pathlib import Path

import pytest
from psycopg import AsyncConnection

from legal_search import db
from legal_search.citation import UNVERIFIED, format_articles
from legal_search.corpus import Article
from legal_search.corrections import load_corrections
from legal_search.headings import extract
from legal_search.ingest import IngestError, ingest, prepare
from legal_search.memorandum import MemorandumError
from legal_search.registry import load_registry
from legal_search.verification import text_sha256
from tests.pg import fresh

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


async def test_the_schema_step_brings_a_database_of_the_previous_image_forward(conn, tmp_path: Path):
    # The previous image's tables: verified_at (never written by it) but no references or provenance, the copy site in
    # source. A verified_at set by hand counts for nothing without a record.
    await conn.execute('ALTER TABLE articles DROP COLUMN verified_gazette, DROP COLUMN verified_bureau, '
                       'DROP COLUMN provenance')
    await conn.execute('ALTER TABLE memorandum_notes DROP COLUMN provenance')
    await conn.execute(
        "INSERT INTO articles (law_slug, law_title, number, suffix, label, text, norm, source, shard, verified_at) "
        "VALUES ('civil-code', 'x', 1, '', 'المادة 1', 'نص قديم.', 'نص قديم', 'jordan-lawyer.com', '00.md', '2026-01-01')")
    await conn.execute("INSERT INTO memorandum_notes (note_no, text, source) VALUES (1, 'شرح قديم.', 'aqel-lawfirm.com/ar/tashree3at/9')")

    await db.create_schema(conn)
    await db.create_schema(conn)  # every start runs it: a second run changes nothing
    cur = await conn.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name IN ('articles', 'memorandum_notes') "
        "AND column_name IN ('verified_at', 'verified_gazette', 'verified_bureau', 'provenance', 'source') "
        "ORDER BY table_name, column_name")
    assert await cur.fetchall() == [
        ('articles', 'provenance', 'text'), ('articles', 'source', 'text'), ('articles', 'verified_at', 'date'),
        ('articles', 'verified_bureau', 'jsonb'), ('articles', 'verified_gazette', 'jsonb'),
        ('memorandum_notes', 'provenance', 'text'), ('memorandum_notes', 'source', 'text'),
    ]

    await ingest(os.environ['DATABASE_URL'], *_sources(tmp_path, TWO, 2))

    cur = await conn.execute('SELECT number, provenance, source, verified_at FROM articles ORDER BY number')
    assert await cur.fetchall() == [(1, 'example.test', '', None), (2, 'example.test', '', None)]
    cur = await conn.execute('SELECT note_no, provenance, source FROM memorandum_notes ORDER BY note_no')
    assert await cur.fetchall() == [(1, 'example.test/memo', ''), (2, 'example.test/memo', '')]
