"""No copy site reaches the model (owner's instructions 2026-11-14 §3, «Hide all copy sites»): no output of search_law,
get_article or get_memorandum contains a name of the copy-site list, content/corpus/copy-sites.json of the mounted
content tree (tests/copy_sites.py), in its headings, source lines, labels and notes or in the statutory text. One pair is
looked for outside the statutory text only: the law itself says «المحامي الأردني» (bar-association 9), which holds the
site title's «محامي الأردن» (copy_sites.STATUTORY_TERMS). The copy site stays in the internal provenance column (and,
in this release, in the old source column), where the same scan finds it. A test that needs the list skips while the
mounted tree has none."""

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
from legal_search.citation import (
    LIBRARY_COPY,
    UNVERIFIED,
    format_articles,
    format_memorandum,
)
from legal_search.corpus import Article
from legal_search.corrections import load_corrections
from legal_search.ingest import ingest, prepare
from legal_search.registry import Law, load_registry
from legal_search.verification import GazetteRef, Verification, text_sha256
from tests.copy_sites import (
    PRODUCT_NAMES,
    STATUTORY_TERMS,
    found_in,
    in_statutory_text,
    names,
    needs_list,
    scan,
)
from tests.pg import fresh

needs_postgres = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')
needs_corpus = pytest.mark.skipif(
    not (os.environ.get('DATABASE_URL') and os.environ.get('CORPUS_DIR') and os.environ.get('CONTENT_DIR')),
    reason='needs Postgres and the real corpus')

CAPS = Caps(per_answer=10_000, daily=100_000, max_results=5)
# What the list must hold at least: the copy sites of the corpus and the page copies, and Qistas (a helper source of the
# verification pass). A check of the content tree's list, which the scan reads; never a list the scan reads.
COPY_SITES = ('jordan-lawyer.com', 'aqel-lawfirm.com', 'adaleh.info', 'حماة الحق', 'حُماة الحق', 'محامي الأردن',
              'محامي الاردن', 'qistas', 'قسطاس')


@needs_list
def test_the_list_names_the_copy_sites_and_never_the_product():
    listed = names()

    assert all(isinstance(name, str) and name and name == name.strip() for name in listed)
    assert len(set(listed)) == len(listed)
    assert set(COPY_SITES) <= set(listed)
    for product in PRODUCT_NAMES:
        assert product not in listed and found_in(product, listed) == []
    assert set(STATUTORY_TERMS) <= set(listed)  # the exception is for two names the list has


@needs_list
@pytest.mark.parametrize('value', [
    'jordan-lawyer.com', 'JORDAN-LAWYER.COM', 'aqel-lawfirm.com/ar/tashree3at/12', 'adaleh.info Art.aspx?Typ=2&Id=1177',
    'حُماة الحق للمحاماة', 'حُـماة الحق', 'حماة الحق - محامي الأردن', 'موقع محامي الاردن',
    'research.qistas.com/ar/print/laws', 'منشورات موقع قسطاس',
])
def test_the_scan_finds_the_values_the_list_was_built_from(value: str):
    assert found_in(value, names())


@pytest.mark.parametrize('text, name', [
    ('EXAMPLE.TEST/ar/12', 'example.test'),
    ('موقع حُـماة القانون للمحاماة', 'حماة القانون'),
    ('موقع حماة القانون', 'حُماة القانون'),
])
def test_the_scan_ignores_diacritics_tatweel_and_the_case_of_latin_letters(text: str, name: str):
    assert found_in(text, [name]) == [name]
    assert found_in('حماية القانون', [name]) == []


def _block(text: str, source: str = LIBRARY_COPY) -> str:
    return f'[1] قانون العمل — المادة 1\n{text}\n(المصدر: {source} — {UNVERIFIED})'


@needs_list
def test_the_scan_reads_the_statutory_text_for_every_name_but_the_statutory_terms():
    listed = names()

    for name in listed:
        text = f'نص المادة، وفيه {name} في سطره.'
        assert name in scan(_block('نص المادة.', source=name), ['نص المادة.'], listed)  # outside the text: always
        if name in STATUTORY_TERMS:
            assert scan(_block(text), [text], listed) == [], name
        else:
            assert name in scan(_block(text), [text], listed), name
    assert sorted(set(listed) - set(in_statutory_text(listed))) == sorted(STATUTORY_TERMS)


# Every tool, on a library whose provenance names every copy site; one article verified.

LAWS = [Law(slug='civil-code', title='القانون المدني الأردني', folder='c', number=43, year=1976,
            note='تطبق فيما لا يتعارض مع أحكام القانون المدني'),
        Law(slug='bar-association', title='قانون نقابة المحامين النظاميين', folder='b', number=11, year=1972)]
TEXTS = [('civil-code', 107, 'يعتبر دفع العربون دليلا على ان العقد اصبح باتا.'),
         ('civil-code', 108, 'يجوز للعاقدين ان يتفقا على العربون.'),
         ('bar-association', 9, 'للمحامي الاردني ان يترافع امام المحاكم.')]
NOTE = 'العربون دليل على ان العقد اصبح باتا.'


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        yield connection


@needs_postgres
@needs_list
async def test_no_tool_output_names_a_copy_site_and_the_provenance_keeps_it(conn):
    listed = names()
    provenance = ' | '.join(listed)
    articles = [Article(law, 'x', number, '', text, provenance, 'a.md') for law, number, text in TEXTS]
    await db.upsert_laws(conn, LAWS)
    await db.upsert_articles(conn, articles)
    checked = Verification(date(2026, 11, 14), (GazetteRef('2645', '2'),), '536', date(2026, 10, 1))
    await db.set_verification(conn, {('civil-code', 108, ''): checked})
    await db.replace_memorandum(conn, {74: NOTE}, [(107, 74)], provenance)
    caller = tools.Caller('u1', 'm1', 'c1')

    outputs = {
        'search_law': (await tools.search_law(conn, CAPS, caller, 'العربون', 5), [a.text for a in articles[:2]]),
        'get_article': (await tools.get_article(conn, CAPS, caller, 107), [articles[0].text]),
        'get_article bar': (await tools.get_article(conn, CAPS, caller, 9, law='bar-association'), [articles[2].text]),
        'get_memorandum': (await tools.get_memorandum(conn, CAPS, caller, 107), [NOTE]),
    }

    for tool, (output, statutory) in outputs.items():
        assert scan(output, statutory, listed) == [], tool
    assert 'متحقق منه: ' in outputs['search_law'][0] and 'غير رسمية' in outputs['get_article'][0]
    # The law's own words hold a listed name, and only one of the statutory terms: why they are the exception.
    assert found_in(articles[2].text, listed) and found_in(articles[2].text, in_statutory_text(listed)) == []
    cur = await conn.execute('SELECT provenance, source FROM articles UNION ALL SELECT provenance, source FROM memorandum_notes')
    rows = await cur.fetchall()
    # source keeps the same value for the previous image, which prints it until it is recreated.
    assert len(rows) == 4 and all(found_in(stored, listed) == listed and source == stored for stored, source in rows)


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
@needs_list
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
    leaks, excepted = [], []
    for article in found:
        hits = scan(format_articles([article]), [article.text], listed)
        if hits:
            leaks.append(f'{article.law_slug} {article.label}: {", ".join(hits)}')
        if found_in(article.text, listed):
            excepted.append((article.law_slug, article.number, article.suffix))
    assert leaks == []
    assert sum(article.verified for article in found) == verified
    # Only the statutory terms are in the law's own words (bar-association 9 among them); the scan looked for every
    # other name there too.
    assert ('bar-association', 9, '') in excepted

    notes_served, note_leaks = set(), []
    for article in sorted({article for article, _ in memorandum.links}):
        total = await db.memorandum_count(conn, article)
        page = await db.memorandum_page(conn, article, 0, total)
        hits = scan(format_memorandum(article, 0, page, total), [note.text for note in page], listed)
        if hits:
            note_leaks.append(f'memorandum of {article}: {", ".join(hits)}')
        notes_served |= {note.note_no for note in page}
    assert note_leaks == []
    assert notes_served == set(memorandum.notes)

    # The copy sites are all still there, in provenance and in source, where no tool reads them.
    for table in ('articles', 'memorandum_notes'):
        cur = await conn.execute(f"SELECT provenance, count(*) FROM {table} GROUP BY provenance")
        groups = await cur.fetchall()
        assert all(found_in(provenance, listed) for provenance, _ in groups), table
        cur = await conn.execute(f"SELECT count(*) FROM {table} WHERE source IS DISTINCT FROM provenance")
        assert (await cur.fetchone())[0] == 0
