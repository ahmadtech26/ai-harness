import json
import os
import sys
from pathlib import Path

import pytest
from psycopg import AsyncConnection

from legal_search import db
from legal_search import evaluate
from legal_search.corpus import Article
from legal_search.evalset import parse_evalset
from legal_search.evaluate import RESET_FLAG, EvalError, Sources, corpus_digest, memorandum_check, run_eval
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
