"""No copy site reaches the model (owner's instructions 2026-11-14 §3, «Hide all copy sites»): no heading, source line,
label or note of search_law, get_article or get_memorandum contains a name of the shared list (tests/copy_sites.py).
Statutory text is not scanned: the law itself says «المحامي الأردني» (bar-association 9). The copy site stays in the
internal provenance column, where the same scan finds it."""

import json
import os
import shutil
from datetime import date
from pathlib import Path

import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from legal_search import db, tools
from legal_search.caps import Caps
from legal_search.citation import format_articles, format_memorandum
from legal_search.corpus import Article
from legal_search.corrections import load_corrections
from legal_search.ingest import ingest, prepare
from legal_search.registry import Law, load_registry
from legal_search.verification import GazetteRef, Verification, text_sha256
from tests.copy_sites import FIXTURE, PRODUCT_NAMES, content_list, found_in, names, without
from tests.pg import fresh

needs_postgres = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')
needs_corpus = pytest.mark.skipif(
    not (os.environ.get('DATABASE_URL') and os.environ.get('CORPUS_DIR') and os.environ.get('CONTENT_DIR')),
    reason='needs Postgres and the real corpus')

LISTED = ['jordan-lawyer.com', 'aqel-lawfirm.com', 'adaleh.info', 'حماة الحق', 'حُماة الحق', 'محامي الأردن',
          'محامي الاردن']
CAPS = Caps(per_answer=10_000, daily=100_000, max_results=5)


def test_the_list_names_the_copy_sites_and_never_the_product():
    assert names() == LISTED
    for product in PRODUCT_NAMES:
        assert product not in names() and found_in(product, names()) == []


@pytest.mark.skipif(content_list() is None, reason='the mounted content tree has no content/corpus/copy-sites.json yet')
def test_the_fixture_lists_what_the_content_tree_lists():
    assert names(content_list()) == names(FIXTURE)


@pytest.mark.parametrize('value', [
    'jordan-lawyer.com', 'JORDAN-LAWYER.COM', 'aqel-lawfirm.com/ar/tashree3at/12', 'adaleh.info Art.aspx?Typ=2&Id=1177',
    'حُماة الحق للمحاماة', 'حُـماة الحق', 'حماة الحق - محامي الأردن', 'موقع محامي الاردن',
])
def test_the_scan_finds_the_values_the_list_was_built_from(value: str):
    assert found_in(value, names())


# Every tool, on a library whose provenance is the copy sites; one article verified.

LAWS = [Law(slug='civil-code', title='القانون المدني الأردني', folder='c', number=43, year=1976,
            note='تطبق فيما لا يتعارض مع أحكام القانون المدني'),
        Law(slug='bar-association', title='قانون نقابة المحامين النظاميين', folder='b', number=11, year=1972)]
ARTICLES = [
    Article('civil-code', 'x', 107, '', 'يعتبر دفع العربون دليلا على ان العقد اصبح باتا.', 'jordan-lawyer.com', 'a.md'),
    Article('civil-code', 'x', 108, '', 'يجوز للعاقدين ان يتفقا على العربون.', 'aqel-lawfirm.com/ar/tashree3at/10', 'a.md'),
    Article('bar-association', 'x', 9, '', 'للمحامي الاردني ان يترافع امام المحاكم.', 'adaleh.info Art.aspx', 'b.md'),
]


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        yield connection


@needs_postgres
async def test_no_tool_output_names_a_copy_site_and_the_provenance_keeps_it(conn):
    await db.upsert_laws(conn, LAWS)
    await db.upsert_articles(conn, ARTICLES)
    checked = Verification(date(2026, 11, 14), (GazetteRef('2645', '2'),), '536', date(2026, 10, 1))
    await db.set_verification(conn, {('civil-code', 108, ''): checked})
    await db.replace_memorandum(conn, {74: 'العربون دليل على ان العقد اصبح باتا.'}, [(107, 74)],
                                'aqel-lawfirm.com/ar/tashree3at/9')
    caller = tools.Caller('u1', 'm1', 'c1')

    outputs = {
        'search_law': (await tools.search_law(conn, CAPS, caller, 'العربون', 5), [a.text for a in ARTICLES[:2]]),
        'get_article': (await tools.get_article(conn, CAPS, caller, 107), [ARTICLES[0].text]),
        'get_article bar': (await tools.get_article(conn, CAPS, caller, 9, law='bar-association'), [ARTICLES[2].text]),
        'get_memorandum': (await tools.get_memorandum(conn, CAPS, caller, 107), ['العربون دليل على ان العقد اصبح باتا.']),
    }

    for tool, (output, statutory) in outputs.items():
        assert found_in(without(output, *statutory), names()) == [], tool
    assert 'متحقق منه: ' in outputs['search_law'][0] and 'غير رسمية' in outputs['get_article'][0]
    assert found_in(ARTICLES[2].text, names()) == ['محامي الاردن']  # the law's own words: why statutory text is not scanned
    cur = await conn.execute('SELECT provenance, source FROM articles UNION ALL SELECT provenance, source FROM memorandum_notes')
    rows = await cur.fetchall()
    assert len(rows) == 4 and all(found_in(provenance, names()) and source == '' for provenance, source in rows)


# The whole library: every article and every memorandum note, as the tools format them.

def _verify_one_law(registry: Path, corrections: Path, slug: str) -> int:
    """Writes test records that verify every article of `slug` (made-up references; the database is the test one)
    beside a copy of the registry, so both formats are scanned over real articles. Returns how many."""
    prepared = prepare(load_registry(registry), load_corrections(corrections), Path(os.environ['CORPUS_DIR']))
    folder = registry.parent / 'verification'
    folder.mkdir()
    gazette = {'method': 'text', 'original': {'issue': 1, 'date': None, 'page': 1}, 'amendments': []}
    bureau = {'legislation_id': 'T1', 'url': None, 'as_of': '2026-11-01'}
    lines = [{'law_slug': slug, 'number': a.number, 'suffix': a.suffix, 'text_sha256': text_sha256(a.text),
              'result': 'verified', 'checked_on': '2026-11-14', 'gazette': gazette, 'bureau': bureau}
             for a in prepared.articles[slug]]
    (folder / f'{slug}.jsonl').write_text(''.join(json.dumps(line, ensure_ascii=False) + '\n' for line in lines),
                                          encoding='utf-8')
    return len(lines)


@needs_corpus
async def test_no_article_or_memorandum_note_of_the_library_is_served_with_a_copy_site(conn, tmp_path: Path):
    corpus_files = Path(os.environ['CONTENT_DIR']) / 'corpus'
    registry, corrections = tmp_path / 'laws.json', tmp_path / 'corrections.json'
    shutil.copyfile(corpus_files / 'laws.json', registry)
    shutil.copyfile(corpus_files / 'corrections.json', corrections)
    verified = _verify_one_law(registry, corrections, 'mediation')
    listed = names()

    prepared, memorandum, matched = await ingest(os.environ['DATABASE_URL'], registry, corrections,
                                                 Path(os.environ['CORPUS_DIR']))

    assert matched.problems == [] and len(matched.verified) == verified > 0
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(db._SELECT)
        found = [db._found(row) for row in await cur.fetchall()]
    assert len(found) == sum(len(articles) for articles in prepared.articles.values())
    leaks, in_the_law = [], []
    for article in found:
        output = format_articles([article])
        if found_in(without(output, article.text), listed):
            leaks.append(f'{article.law_slug} {article.label}')
        if found_in(article.text, listed):
            in_the_law.append((article.law_slug, article.number, article.suffix))
    assert leaks == []
    assert sum(article.verified for article in found) == verified
    assert ('bar-association', 9, '') in in_the_law  # the scan would have found the law's own words

    notes_served = set()
    for article in sorted({article for article, _ in memorandum.links}):
        total = await db.memorandum_count(conn, article)
        page = await db.memorandum_page(conn, article, 0, total)
        output = format_memorandum(article, 0, page, total)
        assert found_in(without(output, *[note.text for note in page]), listed) == [], f'memorandum of {article}'
        notes_served |= {note.note_no for note in page}
    assert notes_served == set(memorandum.notes)

    # The copy sites are all still there, in provenance, where no tool reads them.
    for table in ('articles', 'memorandum_notes'):
        cur = await conn.execute(f"SELECT provenance, count(*) FROM {table} GROUP BY provenance")
        groups = await cur.fetchall()
        assert all(found_in(provenance, listed) for provenance, _ in groups), table
        cur = await conn.execute(f"SELECT count(*) FROM {table} WHERE source <> ''")
        assert (await cur.fetchone())[0] == 0
