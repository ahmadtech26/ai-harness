import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from psycopg import AsyncConnection
from psycopg.errors import UndefinedColumn

from legal_search import db
from legal_search import evaluate
from legal_search.corpus import Article
from legal_search.evalset import parse_evalset
from legal_search.evaluate import RESET_FLAG, EvalError, Sources, corpus_digest, memorandum_check, run_eval
from legal_search.search_config import DEFAULT, SearchConfig
from legal_search.memorandum import load_memorandum, load_memorandum_corrections
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

# Identical text in two laws (civil-code 4, penal-code 2): equal rank for «الكفالة الدين»; shares no term with the
# other queries.
TIED = 'تسقط الكفالة بانقضاء الدين.'
CIVIL = (
    '### المادة 1\n\nدفع العربون وقت ابرام العقد يفيد حق العدول.\n\n---\n\n'
    '### المادة 2\n\nيلزم كل من احدث ضررا بالغير بضمان الضرر.\n\n---\n\n'
    '### المادة 3\n\nلا تسمع الدعوى بمرور الزمان بعد خمس عشرة سنة.\n\n---\n\n'
    f'### المادة 4\n\n{TIED}\n'
)
# «العدول» four times, so without the law filter this article outranks civil-code 1 for «العدول العقد».
PENAL = (
    '### المادة 1\n\nالعدول عن الجريمة: العدول الاختياري، والعدول التام، والعدول قبل التمام لا يعاقب عليه.\n\n---\n\n'
    f'### المادة 2\n\n{TIED}\n'
)
ITEMS = [
    {'id': 'civil-code-01', 'question': 'تراجعت عن العقد بعد دفع العربون، فما الحكم؟', 'query': 'العدول العقد',
     'law': 'civil-code', 'expected': [{'law': 'civil-code', 'number': 1}], 'notes': 'fixture'},
    {'id': 'civil-code-02', 'question': 'أتلف جاري سيارتي، فهل يضمن؟', 'query': 'ضمان الضرر',
     'expected': [{'law': 'civil-code', 'number': 2}], 'expected_notes': [2], 'notes': 'fixture'},
    {'id': 'civil-code-03', 'question': 'هل تسقط الكفالة إذا انقضى الدين؟', 'query': 'الكفالة الدين',
     'expected': [{'law': 'civil-code', 'number': 4}], 'notes': 'fixture: ties with penal-code 2'},
    {'id': 'penal-code-01', 'question': 'تراجع المتهم قبل إتمام الجريمة، فهل يعاقب؟', 'query': 'العدول الاختياري الجريمة',
     'expected': [{'law': 'penal-code', 'number': 1}], 'notes': 'fixture'},
]
OTHER = Article('other', 'قانون غير مسجل', 1, '', 'نص مادة من قانون غير مسجل في السجل.', 's', 'x.md')


def _set_text() -> str:
    lines = [{'set': 'fixture', 'review': {'status': 'draft'}}, *ITEMS]
    return '\n'.join(json.dumps(line, ensure_ascii=False) for line in lines) + '\n'


def _world(tmp_path: Path) -> Sources:
    """A two-law corpus (civil 4 articles, penal 2), its registry, its memorandum (no heading precedes a first note,
    so a correction names note 1's article, civil 1, as plan A requires; note 1 ends with the heading of note 2, the
    note explaining civil article 2) and the fixture set."""
    corpus = tmp_path / 'corpus'
    for folder, body in (('civil', CIVIL), ('penal', PENAL)):
        (corpus / folder / 'sections').mkdir(parents=True)
        (corpus / folder / 'sections' / '00.md').write_text('---\nparent_law: x\nsource: example.test\n---\n\n' + body, encoding='utf-8')
    (corpus / 'law-directory.md').write_text(
        '| القانون | slug | المواد | الأقسام | الحالة | الفئة |\n|---|---|---|---|---|---|\n'
        '| civil | `civil` | 4 | 1 | complete | x |\n'
        '| penal | `penal` | 2 | 1 | complete | x |\n',
        encoding='utf-8',
    )
    notes = {'1': 'تمهيد عام. المذكرة الايضاحية للمادة (2)', '2': 'رؤي ان يكون نص المادة 2 كما ورد.'}
    (corpus / 'memorandum_civil_law.json').write_text(
        json.dumps({'source': 'example.test/memo', 'articles': notes}, ensure_ascii=False), encoding='utf-8'
    )
    entries = [
        {'slug': 'civil-code', 'title': 'القانون المدني الأردني', 'folder': 'civil', 'review': {'status': 'draft'}, 'sources': {'title': 'https://example.test'}},
        {'slug': 'penal-code', 'title': 'قانون العقوبات الأردني', 'folder': 'penal', 'review': {'status': 'draft'}, 'sources': {'title': 'https://example.test'}},
    ]
    registry = tmp_path / 'laws.json'
    registry.write_text(json.dumps({'laws': entries}, ensure_ascii=False), encoding='utf-8')
    corrections = tmp_path / 'corrections.json'
    first_note = {'note': 1, 'articles': [1], 'reason': 'no heading precedes note 1', 'evidence': 'fixture'}
    corrections.write_text(
        json.dumps({'review': {'status': 'draft'}, 'corrections': [], 'memorandum': [first_note]}), encoding='utf-8'
    )
    evalset = tmp_path / 'set.jsonl'
    evalset.write_text(_set_text(), encoding='utf-8')
    return Sources(evalset, registry, corrections, corpus)


def _side(tmp_path: Path, rows: list[dict]) -> Path:
    """A --queries side file holding `rows`, one JSON line each (ensure_ascii=False, as a recorder would write it)."""
    side = tmp_path / 'queries.jsonl'
    side.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    return side


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        yield connection


async def test_run_scores_items_against_the_ingested_corpus(conn, tmp_path: Path):
    report = await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 'fixture')

    # Reciprocal ranks: civil-code-01 0.5 (penal-code 1 outranks it), civil-code-02 1, civil-code-03 0.5 (the tie),
    # penal-code-01 1.
    assert report['metrics']['overall'] == {'recall@5': 1.0, 'recall@10': 1.0, 'hit@5': 1.0, 'hit@10': 1.0, 'mrr': 0.75, 'items': 4}
    assert report['metrics']['per_law']['civil-code']['mrr'] == 0.6667
    # Equal rank: the number tie-break puts penal-code 2 before civil-code 4.
    assert report['items'][2]['ranked'][:2] == [['penal-code', 2, ''], ['civil-code', 4, '']]


async def test_two_runs_on_the_same_corpus_report_identical_metrics_and_rankings(conn, tmp_path: Path):
    sources = _world(tmp_path)

    first = await run_eval(os.environ['DATABASE_URL'], sources, 'first')
    second = await run_eval(os.environ['DATABASE_URL'], sources, 'second')

    assert (second['metrics'], second['items'], second['run']['corpus_sha256']) == (
        first['metrics'], first['items'], first['run']['corpus_sha256'])
    # The fingerprint really follows the corpus: one article's searchable text changed, the digest changes.
    await conn.execute("UPDATE articles SET norm = norm || ' x' WHERE law_slug = 'penal-code' AND number = 2")
    assert await corpus_digest(conn) != first['run']['corpus_sha256']


async def test_law_filter_mode_passes_the_item_law_to_search(conn, tmp_path: Path):
    report = await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 'filtered', use_law_filter=True)

    first = report['items'][0]
    assert (first['law_filter'], first['mrr']) == ('civil-code', 1.0)


async def test_memorandum_check_reports_an_item_whose_served_notes_differ(conn, tmp_path: Path):
    sources = _world(tmp_path)
    # Fixture premise (plan A's derivation): civil 1 -> note 1 (the correction), civil 2 -> note 2 (note 1's heading).
    corrections = load_memorandum_corrections(sources.corrections)
    assert [tuple(link) for link in load_memorandum(sources.corpus, corrections=corrections).links] == [(1, 1), (2, 2)]
    report = await run_eval(os.environ['DATABASE_URL'], sources, 'fixture')
    await conn.execute('DELETE FROM memorandum_links')

    after = await memorandum_check(conn, parse_evalset(_set_text()).items)

    assert report['memorandum'] == {'items_checked': 1, 'mismatched': [], 'pass': True}
    assert after == {'items_checked': 1, 'mismatched': ['civil-code-02: article 2 serves notes [], expected [2]'], 'pass': False}


async def test_run_refuses_a_database_holding_articles_outside_the_registry(conn, tmp_path: Path):
    await db.upsert_articles(conn, [OTHER])

    with pytest.raises(EvalError, match='holds 1 articles, 1 outside the registry, which gives 6'):
        await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 'fixture')

    cur = await conn.execute('SELECT count(*) FROM articles')
    assert (await cur.fetchone())[0] == 1  # refused before the ingest wrote anything


async def test_reset_is_refused_without_the_test_stack_flag(conn, tmp_path: Path, monkeypatch):
    monkeypatch.delenv(RESET_FLAG, raising=False)

    with pytest.raises(EvalError, match=f'{RESET_FLAG}=1'):
        await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 'fixture', reset=True)


async def test_reset_with_the_flag_clears_articles_outside_the_registry(conn, tmp_path: Path, monkeypatch):
    monkeypatch.setenv(RESET_FLAG, '1')
    await db.upsert_articles(conn, [OTHER])

    report = await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 'fixture', reset=True)

    assert report['metrics']['overall']['items'] == 4


def test_run_exits_1_and_keeps_the_report_when_the_memorandum_check_fails(tmp_path: Path, monkeypatch):
    sources = _world(tmp_path)
    out = tmp_path / 'out'

    async def failing_check(conn, items):
        return {'items_checked': 1, 'mismatched': ['civil-code-02: article 2 serves notes [], expected [2]'], 'pass': False}

    monkeypatch.setenv(RESET_FLAG, '1')
    monkeypatch.setattr(evaluate, 'memorandum_check', failing_check)
    monkeypatch.setattr(sys, 'argv', [
        'legal-search-eval', '--set', str(sources.evalset), '--registry', str(sources.registry),
        '--corrections', str(sources.corrections), '--corpus', str(sources.corpus), '--out', str(out),
        'run', '--label', 'broken', '--reset',
    ])

    with pytest.raises(SystemExit) as exit_info:
        evaluate.main()

    assert exit_info.value.code == 1
    assert json.loads((out / 'eval-broken.json').read_text(encoding='utf-8'))['memorandum']['pass'] is False


async def test_run_applies_the_search_config_it_is_given(conn, tmp_path: Path, monkeypatch):
    seen = []
    real_search = db.search

    async def spy(connection, query, limit, law=None, config=DEFAULT, **kwargs):
        seen.append(config)
        return await real_search(connection, query, limit, law=law, config=config, **kwargs)

    monkeypatch.setattr(db, 'search', spy)
    config = SearchConfig(rank_normalization=2)

    report = await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 'configured', config=config)

    assert set(seen) == {config}
    assert report['run']['config']['rank_normalization'] == 2


async def test_run_searches_the_question_field_when_asked(conn, tmp_path: Path, monkeypatch):
    seen = []
    real_search = db.search

    async def spy(connection, query, limit, law=None, config=DEFAULT, **kwargs):
        seen.append(query)
        return await real_search(connection, query, limit, law=law, config=config, **kwargs)

    monkeypatch.setattr(db, 'search', spy)
    sources = _world(tmp_path)
    report = await run_eval(os.environ['DATABASE_URL'], sources, 'q', field='question')
    questions = [item.question for item in parse_evalset(sources.evalset.read_text(encoding='utf-8')).items]
    assert (seen, report['run']['field'], report['run']['queries_sha256']) == (questions, 'question', None)


async def test_run_takes_queries_and_laws_from_a_side_file_and_records_its_sha(conn, tmp_path: Path):
    sources = _world(tmp_path)
    items = parse_evalset(sources.evalset.read_text(encoding='utf-8')).items
    side = tmp_path / 'queries.jsonl'
    side.write_text(''.join(json.dumps({'id': i.id, 'query': 'العربون', 'law': 'civil-code'}, ensure_ascii=False) + '\n'
                            for i in items), encoding='utf-8')
    report = await run_eval(os.environ['DATABASE_URL'], sources, 'side', queries=side, use_law_filter=True)
    assert {row['query'] for row in report['items']} == {'العربون'}
    assert {row['law_filter'] for row in report['items']} == {'civil-code'}
    assert report['run']['queries_sha256'] == hashlib.sha256(side.read_bytes()).hexdigest()


async def test_a_side_file_missing_an_item_is_refused(conn, tmp_path: Path):
    side = tmp_path / 'queries.jsonl'
    side.write_text('{"id": "civil-code-01", "query": "العربون", "law": null}\n', encoding='utf-8')
    with pytest.raises(EvalError, match='side file'):
        await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 'side', queries=side)


async def test_a_side_file_naming_an_item_twice_is_refused(conn, tmp_path: Path):
    # Beyond the plan's named tests: Step 3 also refuses a duplicated id. Every item is present, so only that check can
    # fire. An item named three times is reported once; rows for an id outside the set are ignored, even repeated.
    sources = _world(tmp_path)
    items = parse_evalset(sources.evalset.read_text(encoding='utf-8')).items
    ids = [i.id for i in items] + [items[0].id, items[0].id, 'other-01', 'other-01']
    side = _side(tmp_path, [{'id': i, 'query': 'العربون', 'law': None} for i in ids])

    with pytest.raises(EvalError, match='side file.*civil-code-01') as refusal:
        await run_eval(os.environ['DATABASE_URL'], sources, 'side', queries=side)

    assert (str(refusal.value).count('civil-code-01'), 'other-01' in str(refusal.value)) == (1, False)


async def test_side_file_rows_reach_their_own_items_and_their_law_needs_the_law_filter(conn, tmp_path: Path):
    # A different query per row, written in reverse item order: a row must reach the item it names, not the item at its
    # position. Without use_law_filter a row's law is not passed to search, as item.law is not (plan Task 1.2 Step 3).
    sources = _world(tmp_path)
    items = parse_evalset(sources.evalset.read_text(encoding='utf-8')).items
    side = _side(tmp_path, [{'id': i.id, 'query': i.question, 'law': 'civil-code'} for i in reversed(items)])

    report = await run_eval(os.environ['DATABASE_URL'], sources, 'side', queries=side)

    assert {row['id']: row['query'] for row in report['items']} == {i.id: i.question for i in items}
    assert {row['law_filter'] for row in report['items']} == {None}


@pytest.mark.parametrize('bad', [
    '{"id": "civil-code-01", "query": }',
    '["civil-code-01", "العربون"]',
    '{"query": "العربون", "law": null}',
    '{"id": "civil-code-01", "law": null}',
    '{"id": "civil-code-01", "query": null, "law": null}',
    '{"id": "civil-code-01", "query": "العربون", "law": 5}',
], ids=['not-json', 'not-an-object', 'no-id', 'no-query', 'null-query', 'law-not-a-string'])
async def test_a_malformed_side_file_row_is_refused_by_line_before_the_ingest(conn, tmp_path: Path, bad: str):
    # The bad row is line 1; the other items' rows are valid, so only the row check can name a line.
    sources = _world(tmp_path)
    items = parse_evalset(sources.evalset.read_text(encoding='utf-8')).items
    side = _side(tmp_path, [{'id': i.id, 'query': 'العربون', 'law': None} for i in items[1:]])
    side.write_text(bad + '\n' + side.read_text(encoding='utf-8'), encoding='utf-8')

    with pytest.raises(EvalError, match=r'^side file .*: line 1: '):
        await run_eval(os.environ['DATABASE_URL'], sources, 'side', queries=side)

    cur = await conn.execute('SELECT count(*) FROM articles')
    assert (await cur.fetchone())[0] == 0  # refused before the ingest wrote anything


@pytest.mark.parametrize(('law', 'expected'), [('', None), (' civil-code ', 'civil-code')])
async def test_a_side_file_law_is_read_as_search_law_reads_it(conn, tmp_path: Path, law: str, expected: str | None):
    # tools.search_law reads its law as (law or '').strip() or None ("models often send "" for an optional argument"),
    # so a recorded call is scored with the law the service would have searched.
    sources = _world(tmp_path)
    items = parse_evalset(sources.evalset.read_text(encoding='utf-8')).items
    side = _side(tmp_path, [{'id': i.id, 'query': 'العربون', 'law': law} for i in items])

    report = await run_eval(os.environ['DATABASE_URL'], sources, 'side', queries=side, use_law_filter=True)

    assert {row['law_filter'] for row in report['items']} == {expected}


async def test_a_side_file_query_may_hold_a_line_separator(conn, tmp_path: Path):
    # json.dumps(ensure_ascii=False) writes U+2028 unescaped; the file splits on newlines only, as parse_evalset does.
    sources = _world(tmp_path)
    items = parse_evalset(sources.evalset.read_text(encoding='utf-8')).items
    query = 'العربون العقد'
    side = _side(tmp_path, [{'id': i.id, 'query': query, 'law': None} for i in items])

    report = await run_eval(os.environ['DATABASE_URL'], sources, 'side', queries=side)

    assert {row['query'] for row in report['items']} == {query}


@pytest.mark.parametrize(('field', 'with_side_file'), [('notes', False), ('question', True)])
async def test_run_refuses_a_field_it_would_not_search(conn, tmp_path: Path, field: str, with_side_file: bool):
    # Only query and question are searched; with a side file its rows give each item's query, so a field beside it
    # would be recorded in the run but not searched.
    sources = _world(tmp_path)
    items = parse_evalset(sources.evalset.read_text(encoding='utf-8')).items
    side = _side(tmp_path, [{'id': i.id, 'query': 'العربون', 'law': None} for i in items])

    with pytest.raises(EvalError, match='^field '):
        await run_eval(os.environ['DATABASE_URL'], sources, 'side', field=field, queries=side if with_side_file else None)


async def test_run_records_an_index_digest_over_the_index_only_columns(conn, tmp_path: Path, monkeypatch):
    first = await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 'a')
    assert first['run']['index_sha256'] == await evaluate.index_digest(conn)
    monkeypatch.setattr(evaluate, 'INDEX_COLUMNS', ('label',))  # any column: the mechanism, apart from the defaults
    before = await evaluate.index_digest(conn)                   # both digests over the same columns
    corpus_before = await evaluate.corpus_digest(conn)
    await conn.execute("UPDATE articles SET label = label || ' x' WHERE number = 1")
    assert await evaluate.index_digest(conn) != before
    assert await evaluate.corpus_digest(conn) == corpus_before   # an index-only change leaves the corpus digest alone


async def test_evaluation_searches_are_strict(conn, tmp_path: Path, monkeypatch):
    seen = []
    real_search = db.search

    async def spy(connection, query, limit, law=None, config=DEFAULT, **kwargs):
        seen.append(kwargs.get('strict'))
        return await real_search(connection, query, limit, law=law, config=config, **kwargs)

    monkeypatch.setattr(db, 'search', spy)
    await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 's')
    assert set(seen) == {True}


async def test_index_digest_follows_the_law_title_and_corpus_digest_does_not(conn, tmp_path: Path):
    # The BM25 engine scores law_title under title_weight (the bench's title field); corpus_digest hashes only the
    # keys and norm, so the default INDEX_COLUMNS must cover it.
    run = await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 't')

    await conn.execute("UPDATE articles SET law_title = law_title || ' x' WHERE number = 1")

    assert await evaluate.index_digest(conn) != run['run']['index_sha256']
    assert await corpus_digest(conn) == run['run']['corpus_sha256']


async def test_index_digest_follows_the_heading_and_corpus_digest_does_not(conn, tmp_path: Path):
    # The BM25 engine scores the stored heading under heading_weight (Task 3.4); it is not in the served text or norm.
    run = await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 'h')

    await conn.execute("UPDATE articles SET heading = heading || ' x' WHERE number = 1")

    assert await evaluate.index_digest(conn) != run['run']['index_sha256']
    assert await corpus_digest(conn) == run['run']['corpus_sha256']


async def test_index_digest_ignores_row_order_and_follows_the_keys(conn, tmp_path: Path):
    await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 'k')
    before = await evaluate.index_digest(conn)

    # An UPDATE that changes nothing still writes new row versions, so the table's physical order changes.
    await conn.execute('UPDATE articles SET label = label WHERE number = 1')
    assert await evaluate.index_digest(conn) == before

    await conn.execute("UPDATE articles SET number = 99 WHERE law_slug = 'civil-code' AND number = 4")
    assert await evaluate.index_digest(conn) != before


async def test_a_bad_index_column_fails_the_run_before_any_search(conn, tmp_path: Path, monkeypatch):
    # Both digests are taken before scoring: nothing writes to the corpus while it is scored, and a column the schema
    # lacks stops the run at once instead of after every item has been searched.
    seen = []
    real_search = db.search

    async def spy(connection, query, limit, law=None, config=DEFAULT, **kwargs):
        seen.append(query)
        return await real_search(connection, query, limit, law=law, config=config, **kwargs)

    monkeypatch.setattr(db, 'search', spy)
    monkeypatch.setattr(evaluate, 'INDEX_COLUMNS', ('no_such_column',))

    with pytest.raises(UndefinedColumn):
        await run_eval(os.environ['DATABASE_URL'], _world(tmp_path), 'bad')

    assert seen == []
