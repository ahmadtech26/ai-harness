import json
import os
from pathlib import Path

import pytest
from psycopg import AsyncConnection

from legal_search.ingest import IngestError, ingest
from legal_search.memorandum import MemorandumError
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

TWO = '### المادة 1\n\nنص المادة الأولى من القانون.\n\n---\n\n### المادة 2\n\nنص المادة الثانية من القانون.\n'
ONE = '### المادة 1\n\nنص المادة الأولى من القانون.\n'


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
