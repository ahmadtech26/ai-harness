"""The verification records and the hash rule (verification.match), without a database."""

import hashlib
import json
import os
import sys
from dataclasses import replace as with_changes
from datetime import date
from pathlib import Path

import pytest

from legal_search import ingest
from legal_search.corpus import Article
from legal_search.ingest import check_verification
from legal_search.verification import GazetteRef, Verification, gazette_in_force, match, text_sha256

FIRST = 'نص المادة الأولى من القانون.'
SECOND = 'نص المادة الثانية من القانون.'
ARTICLES = {'labour': [Article('labour', 'قانون العمل', 1, '', FIRST, 'example.test', '00.md'),
                       Article('labour', 'قانون العمل', 2, 'مكرر', SECOND, 'example.test', '00.md')]}
GAZETTE = {'method': 'text', 'original': {'issue': 4113, 'date': '1996-04-16', 'page': 1173},
           'amendments': [], 'text_sha256': None, 'checked_on': '2026-11-14'}
BUREAU = {'legislation_id': 3392, 'url': None, 'as_of': '2026-10-01', 'text_sha256': None, 'checked_on': '2026-11-14'}


def record(number: int = 1, suffix: str = '', text: str = FIRST, result: str = 'verified', **changes) -> dict:
    """A record as §2 of the owner's instructions gives it; `changes` replace keys."""
    line = {'law_slug': 'labour', 'number': number, 'suffix': suffix, 'text_sha256': text_sha256(text),
            'result': result, 'reason': None, 'differs_from': None, 'difference': None, 'checked_on': '2026-11-14',
            'normalisation': 'v1', 'gazette': GAZETTE, 'bureau': BUREAU, 'notes': '', 'lawyer_item': None}
    return {**line, **changes}


def write(directory: Path, lines: list, law: str = 'labour') -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    text = ''.join((line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)) + '\n' for line in lines)
    (directory / f'{law}.jsonl').write_text(text, encoding='utf-8')
    return directory


BOTH = [record(), record(2, 'مكرر', SECOND, result='unverifiable', reason='gazette_offline', gazette=None, bureau=None)]


def test_the_binding_key_is_the_sha256_of_the_utf8_text_exactly():
    assert text_sha256(FIRST) == hashlib.sha256(FIRST.encode('utf-8')).hexdigest()
    assert text_sha256(FIRST) != text_sha256(FIRST + ' ')  # nothing is normalised away


def test_a_verified_record_of_the_stored_text_verifies_its_article(tmp_path: Path):
    matched = match(ARTICLES, write(tmp_path / 'verification', BOTH))

    assert matched.problems == []
    assert matched.verified == {('labour', 1, ''): Verification(date(2026, 11, 14), (GazetteRef('4113', '1173'),), '3392',
                                                               date(2026, 10, 1))}
    assert (matched.files, matched.records, matched.results) == (1, 2, {'verified': 1, 'differs': 0, 'unverifiable': 1})


def test_a_changed_text_unverifies_the_article_and_is_a_problem(tmp_path: Path):
    changed = {'labour': [with_changes(ARTICLES['labour'][0], text=FIRST + ' ونص مضاف.'), ARTICLES['labour'][1]]}

    matched = match(changed, write(tmp_path / 'verification', BOTH))

    assert matched.verified == {}
    assert len(matched.problems) == 1 and 'labour المادة 1 is verified for text_sha256' in matched.problems[0]


def test_no_folder_or_no_file_for_a_law_verifies_nothing_and_is_no_problem(tmp_path: Path):
    penal = [Article('penal-code', 'قانون العقوبات', 1, '', 'لا جريمة إلا بنص.', 'example.test', '00.md')]
    laws = {**ARTICLES, 'penal-code': penal}
    only_penal = write(tmp_path / 'verification', [record(law_slug='penal-code', text=penal[0].text)], law='penal-code')

    missing = match(laws, tmp_path / 'missing')
    matched = match(laws, only_penal)

    assert (missing.verified, missing.problems, missing.files) == ({}, [], 0)
    assert (list(matched.verified), matched.problems) == ([('penal-code', 1, '')], [])  # labour has no file


@pytest.mark.parametrize('result', ['differs', 'unverifiable'])
def test_only_a_verified_result_verifies(tmp_path: Path, result: str):
    lines = [record(result=result, reason='sources_disagree', differs_from='gazette', difference='body'), BOTH[1]]

    matched = match(ARTICLES, write(tmp_path / 'verification', lines))

    assert (matched.verified, matched.problems) == ({}, [])


def test_a_record_must_match_a_parsed_article_of_its_own_law(tmp_path: Path):
    lines = [*BOTH, record(3), record(2, '', SECOND), record(law_slug='penal-code')]

    matched = match(ARTICLES, write(tmp_path / 'verification', lines))

    assert matched.problems == [
        'verification/labour.jsonl:3: labour المادة 3 matches no parsed article',
        'verification/labour.jsonl:4: labour المادة 2 matches no parsed article',
        "verification/labour.jsonl:5: law_slug 'penal-code' in the file of 'labour'",
    ]
    assert list(matched.verified) == [('labour', 1, '')]  # the good record still counts


def test_a_file_for_a_law_not_in_the_registry_is_a_problem(tmp_path: Path):
    matched = match(ARTICLES, write(tmp_path / 'verification', [record(law_slug='labor')], law='labor'))

    assert matched.problems == ["verification/labor.jsonl: no law 'labor' in the registry"]


def test_an_article_without_a_record_in_a_file_of_its_law_is_a_problem(tmp_path: Path):
    matched = match(ARTICLES, write(tmp_path / 'verification', [record()]))

    assert matched.problems == ['verification/labour.jsonl: 1 article(s) of labour have no record: المادة 2 مكرر']
    assert list(matched.verified) == [('labour', 1, '')]


def test_two_records_for_one_article_verify_nothing(tmp_path: Path):
    matched = match(ARTICLES, write(tmp_path / 'verification', [record(), record(), BOTH[1]]))

    assert matched.verified == {}
    assert matched.problems == ['verification/labour.jsonl:2: a second record for labour المادة 1']


@pytest.mark.parametrize('line, problem', [
    ('{"law_slug": "labour"', 'not JSON'),
    ('[1, 2]', 'not a JSON object'),
    (record(number='1'), 'number must be an int and suffix a string'),
    (record(number=True), 'number must be an int and suffix a string'),
    (record(suffix=None), 'number must be an int and suffix a string'),
    (record(result='checked'), "result 'checked' is not one of verified, differs, unverifiable"),
    (record(text_sha256='ABC'), 'text_sha256 is not a lowercase sha256 hex digest'),
    (record(checked_on='14/11/2026'), 'checked_on is not a YYYY-MM-DD date'),
    (record(gazette=None), 'a verified record names no Gazette issue of the text in force'),
    (record(gazette={**GAZETTE, 'original': {'issue': None}}), 'a verified record names no Gazette issue'),
    (record(bureau=None), 'a verified record names no Bureau legislation_id'),
    (record(bureau={**BUREAU, 'as_of': '2026-13-01'}), 'bureau.as_of is not a YYYY-MM-DD date'),
    (record(gazette={**GAZETTE, 'original': {'issue': 4113, 'page': '12 — 13'}}), "gazette page '12 — 13' is not"),
    (record(bureau={**BUREAU, 'legislation_id': '3392)'}), "bureau legislation_id '3392)' is not"),
], ids=lambda value: value if isinstance(value, str) and len(value) < 40 else None)
def test_a_record_the_library_cannot_use_verifies_nothing_and_is_a_problem(tmp_path: Path, line, problem: str):
    matched = match(ARTICLES, write(tmp_path / 'verification', [line, BOTH[1]]))

    assert matched.verified == {}
    assert len(matched.problems) >= 1 and problem in matched.problems[0]


def test_the_gazette_issues_of_the_text_in_force():
    original = {'issue': 1487, 'date': '1960-05-01', 'page': 374}
    amended = {'law': 12, 'year': 2001, 'issue': 4480, 'date': '2001-03-01', 'page': 1, 'effect': 'amended'}
    replaced = {'law': 7, 'year': 2011, 'issue': 5090, 'date': '2011-05-02', 'page': 1, 'effect': 'replaced'}
    later = {'law': 9, 'year': 2017, 'issue': 5450, 'date': '2017-04-30', 'page': '2-3', 'effect': 'amended'}

    # Never amended: the original's issue. Amended in passages: the original and each amendment, oldest first.
    assert gazette_in_force({'original': original, 'amendments': []}) == (GazetteRef('1487', '374'),)
    assert gazette_in_force({'original': original, 'amendments': [amended]}) == (
        GazetteRef('1487', '374'), GazetteRef('4480', '1'))
    # A whole text replaced: the replacing law and what came after it; recorded out of order, read in date order.
    assert gazette_in_force({'original': original, 'amendments': [later, amended, replaced]}) == (
        GazetteRef('5090', '1'), GazetteRef('5450', '2-3'))
    # «مكرر» inserted, or repealed: from that law.
    assert gazette_in_force({'original': None, 'amendments': [{**amended, 'effect': 'added'}]}) == (GazetteRef('4480', '1'),)
    assert gazette_in_force({'original': original, 'amendments': [{**replaced, 'effect': 'repealed'}]}) == (
        GazetteRef('5090', '1'),)
    # An earlier issue the record keeps without its number is left out.
    assert gazette_in_force({'original': {'issue': None}, 'amendments': [amended]}) == (GazetteRef('4480', '1'),)


def test_the_stored_columns_give_back_the_verification():
    verification = Verification(date(2026, 11, 14), (GazetteRef('4113', '1173'), GazetteRef('5573')), '3392')

    back = Verification.from_columns(verification.checked_on, verification.gazette_column(), verification.bureau_column())

    assert back == verification
    # The three are written together or not at all; anything less is not a verified article.
    assert Verification.from_columns(None, verification.gazette_column(), verification.bureau_column()) is None
    assert Verification.from_columns(date(2026, 11, 14), None, verification.bureau_column()) is None
    assert Verification.from_columns(date(2026, 11, 14), [], verification.bureau_column()) is None
    assert Verification.from_columns(date(2026, 11, 14), verification.gazette_column(), None) is None


# legal-search-ingest --check-verification: ingest.prepare over the content tree, then match; no database.

def _tree(tmp_path: Path, body: str) -> list[str]:
    """A content tree of one law, labour (articles 1 and 2 مكرر), and the arguments that point at it."""
    sections = tmp_path / 'corpus' / 'labour' / 'sections'
    sections.mkdir(parents=True)
    (sections / '00.md').write_text('---\nparent_law: x\nsource: example.test\n---\n\n' + body, encoding='utf-8')
    (tmp_path / 'corpus' / 'law-directory.md').write_text(
        '| القانون | slug | المواد | الأقسام | الحالة | الفئة |\n|---|---|---|---|---|---|\n'
        '| law | `labour` | 2 | 1 | complete | x |\n', encoding='utf-8')
    registry = tmp_path / 'content' / 'corpus' / 'laws.json'
    registry.parent.mkdir(parents=True)
    entry = {'slug': 'labour', 'title': 'قانون العمل', 'folder': 'labour', 'review': {'status': 'draft'}}
    registry.write_text(json.dumps({'laws': [entry]}, ensure_ascii=False), encoding='utf-8')
    corrections = registry.parent / 'corrections.json'
    corrections.write_text(json.dumps({'corrections': []}), encoding='utf-8')
    return ['--registry', str(registry), '--corrections', str(corrections), '--corpus', str(tmp_path / 'corpus')]


BODY = f'### المادة 1\n\n{FIRST}\n\n---\n\n### المادة 2 مكرر\n\n{SECOND}\n'


def _check(monkeypatch, capsys, arguments: list[str]) -> tuple[str, str | None]:
    """Runs the check mode as the command line does, without a database; returns its output and its failure."""
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('DATABASE_URL_FILE', raising=False)
    monkeypatch.setattr(sys, 'argv', ['legal-search-ingest', '--check-verification', *arguments])
    try:
        ingest.main()
        failure = None
    except SystemExit as exit_:
        failure = str(exit_.code)
    return capsys.readouterr().out, failure


def test_the_check_passes_when_every_verified_record_binds_its_text(tmp_path: Path, monkeypatch, capsys):
    arguments = _tree(tmp_path, BODY)
    write(tmp_path / 'content' / 'corpus' / 'verification', BOTH)

    out, failure = _check(monkeypatch, capsys, arguments)

    assert failure is None
    assert 'verification: 1 articles verified, from 2 records in 1 files' in out
    assert out.rstrip().endswith('verification check passed')


def test_the_check_passes_without_records(tmp_path: Path, monkeypatch, capsys):
    out, failure = _check(monkeypatch, capsys, _tree(tmp_path, BODY))

    assert failure is None and 'verification: 0 articles verified, from 0 records in 0 files' in out


def test_the_check_fails_on_a_verified_record_of_another_text_and_on_a_key_no_article_has(tmp_path: Path, monkeypatch,
                                                                                          capsys):
    arguments = _tree(tmp_path, BODY.replace(FIRST, FIRST[:-1] + '،'))  # one punctuation mark changed
    write(tmp_path / 'content' / 'corpus' / 'verification', [*BOTH, record(2, '', SECOND, result='differs')])

    out, failure = _check(monkeypatch, capsys, arguments)

    assert failure == 'verification check failed: 2 problem(s)'
    problems = [line for line in out.splitlines() if line.startswith('verification problem: ')]
    assert len(problems) == 2
    assert problems[0].startswith('verification problem: verification/labour.jsonl:1: labour المادة 1 is verified for '
                                  f'text_sha256 {text_sha256(FIRST)[:12]}…')
    assert problems[1] == 'verification problem: verification/labour.jsonl:3: labour المادة 2 matches no parsed article'


def test_the_check_fails_on_a_corpus_the_ingest_would_refuse(tmp_path: Path, monkeypatch, capsys):
    arguments = _tree(tmp_path, BODY.replace('### المادة 2 مكرر', '### المادة 1'))  # a duplicate article

    _, failure = _check(monkeypatch, capsys, arguments)

    assert failure == 'verification check failed: labour: duplicate article المادة 1'


@pytest.mark.skipif(not (os.environ.get('CORPUS_DIR') and os.environ.get('CONTENT_DIR')), reason='real corpus not mounted')
def test_the_real_records_bind_the_texts_the_ingest_stores():
    """The hash check of the content tree (owner's instructions §2): every verified record's text_sha256 is the sha256
    of its article's text as ingest.prepare returns it, and every record names a parsed article. A tree without
    content/corpus/verification passes."""
    corpus_files = Path(os.environ['CONTENT_DIR']) / 'corpus'

    _, matched = check_verification(corpus_files / 'laws.json', corpus_files / 'corrections.json',
                                    Path(os.environ['CORPUS_DIR']))

    assert matched.problems == []
