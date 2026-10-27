import json
from pathlib import Path

import pytest

from skill_tools.corpus_checks import check_all
from skill_tools.corpus_ci import main

DRAFT_CORRECTIONS = {'review': {'status': 'draft'}, 'corrections': []}
APPROVED = {'status': 'approved', 'approved_by': 'lawyer', 'approved_on': '2026-11-01'}


def _corpus(tmp_path: Path) -> Path:
    for folder in ('penal', 'civil'):
        (tmp_path / folder / 'sections').mkdir(parents=True)
    return tmp_path


def _entry(**changes) -> dict:
    # Fixture values are deliberately not real citation data.
    entry = {
        'slug': 'penal-code',
        'title': 'قانون العقوبات الأردني',
        'folder': 'penal',
        'number': 99,
        'year': 1900,
        'gazette': {'issue': 1234, 'date': '1900-03-02', 'source_url': 'https://example.test/gazette'},
        'amendment': {'law': 7, 'year': 1901, 'gazette_issue': 1300, 'gazette_date': '1901-05-06',
                      'source_url': 'https://example.test/amendment'},
        'review': {'status': 'draft'},
        'sources': {
            'title': 'https://example.test/law',
            'number': 'https://example.test/law',
            'year': 'https://example.test/law',
            'gazette.issue': 'https://example.test/gazette',
            'gazette.date': 'https://example.test/gazette',
            'amendment.law': 'https://example.test/amendment',
            'amendment.year': 'https://example.test/amendment',
            'amendment.gazette_issue': 'https://example.test/amendment',
            'amendment.gazette_date': 'https://example.test/amendment',
        },
    }
    entry.update(changes)
    return entry


def _problems(tmp_path: Path, entries: list[dict], corrections=DRAFT_CORRECTIONS, release=False):
    return check_all({'laws': entries}, corrections, _corpus(tmp_path), release)


def test_a_valid_registry_passes_every_check(tmp_path: Path):
    assert _problems(tmp_path, [_entry()]) == []


def _with_sources(**extra) -> dict:
    return {**_entry()['sources'], **extra}


def _amendment(**changes) -> dict:
    return {**_entry()['amendment'], **changes}


# (entry, a message the checks must report). One case per rule, so dropping a rule fails this test.
SCHEMA_VIOLATIONS = [
    (_entry(number='99'), 'number must be int'),
    (_entry(publisher='x'), 'unknown field publisher'),
    (_entry(slug='Penal_Code'), 'slug must be lowercase latin words joined by hyphens'),
    (_entry(title='  '), 'title must not be empty'),
    (_entry(note=' ', sources=_with_sources(note='https://example.test/law')), 'note must not be empty'),
    (_entry(known_gaps=[{'number': 'x'}]), 'each known gap needs number (int), reason (text) and an optional suffix'),
    (_entry(review={'status': 'approved'}), 'an approved review needs approved_by and approved_on'),
    (_entry(review={'status': 'approved', 'approved_by': 'l', 'approved_on': '1/11/2026'}),
     'review.approved_on must be an ISO date (YYYY-MM-DD)'),
    (_entry(sources=_with_sources(note='https://example.test/law')), 'sources names note, which has no value'),
    (_entry(gazette={'issue': 1234, 'date': '1900-03-02', 'source_url': 'ftp://example.test'}),
     'gazette.source_url is not an http(s) URL'),
    (_entry(amendment=_amendment(law='7')), 'amendment.law must be int'),
    (_entry(amendment=_amendment(gazette_date='6/5/1901')), 'amendment.gazette_date must be an ISO date (YYYY-MM-DD)'),
    ({key: value for key, value in _entry().items() if key != 'folder'}, 'missing required field folder'),
    (_entry(gazette={'issue': '1234', 'date': '1900-03-02', 'source_url': 'https://example.test/gazette'}),
     'gazette.issue must be int'),
]


def test_rejects_each_schema_violation(tmp_path: Path):
    missed = []
    for index, (entry, expected) in enumerate(SCHEMA_VIOLATIONS):
        messages = [p.message for p in _problems(tmp_path / str(index), [entry])]
        if expected not in messages:
            missed.append((expected, messages))
    top_level = check_all({'entries': []}, DRAFT_CORRECTIONS, _corpus(tmp_path / 'top'), False)

    assert missed == []
    assert [p.message for p in top_level] == ['top level must be {"laws": [...]}']


def test_rejects_a_folder_missing_from_the_corpus(tmp_path: Path):
    problems = _problems(tmp_path, [_entry(folder='missing')])

    assert [(p.skill, p.rule) for p in problems] == [('penal-code', 'folder')]


def test_rejects_a_duplicate_slug(tmp_path: Path):
    problems = _problems(tmp_path, [_entry(), _entry(folder='civil')])

    assert [(p.skill, p.rule) for p in problems] == [('penal-code', 'slug')]


def test_rejects_a_date_that_is_not_iso(tmp_path: Path):
    gazette = {'issue': 1234, 'date': '2/3/1900', 'source_url': 'https://example.test/gazette'}

    problems = _problems(tmp_path, [_entry(gazette=gazette)])

    assert [(p.skill, p.rule) for p in problems] == [('penal-code', 'date')]


def test_requires_a_source_url_for_every_value_present(tmp_path: Path):
    entry = _entry()
    del entry['sources']['year']
    bare = _entry(sources=_with_sources(year='example.test/law'))  # a value, but not an http(s) URL

    messages = [p.message for p in _problems(tmp_path, [entry])]

    assert messages == ['year has no source URL in sources']
    assert [p.message for p in _problems(tmp_path / 'bare', [bare])] == ['year has no source URL in sources']


def test_release_fails_on_a_draft_entry_naming_it(tmp_path: Path):
    corrections = {'review': APPROVED, 'corrections': []}

    problems = _problems(tmp_path, [_entry()], corrections, release=True)

    assert [(p.skill, p.rule) for p in problems] == [('penal-code', 'review')]


def _relabel(**changes) -> dict:
    item = {'type': 'relabel', 'law': 'penal-code', 'number': 25, 'suffix': 'مكرر', 'occurrence': 2,
            'new_suffix': 'مكرر ثانياً', 'reason': 'two headings parse as 25 مكرر', 'source': 'https://example.test/law'}
    item.update(changes)
    return item


def _without(key: str) -> dict:
    item = _relabel()
    del item[key]
    return item


# (corrections document, a message the checks must report). One case per rule.
CORRECTION_VIOLATIONS = [
    ({'review': {'status': 'draft'}, 'corrections': [_relabel(type='rename')]}, 'type must be one of replace, split, relabel'),
    ({'review': {'status': 'draft'}, 'corrections': [_relabel(law='penal')]}, "law 'penal' is not in the registry"),
    ({'review': {'status': 'draft'}, 'corrections': [_without('new_suffix')]}, 'relabel correction is missing new_suffix'),
    ({'review': {'status': 'draft'}, 'corrections': [_relabel(number='25')]}, 'number must be int'),
    ({'review': {'status': 'pending'}, 'corrections': []}, 'review.status must be draft or approved'),
    ({'corrections': {}}, 'top level must be {"review": {...}, "corrections": [...]}'),
]


def test_rejects_each_invalid_correction(tmp_path: Path):
    missed = []
    for index, (corrections, expected) in enumerate(CORRECTION_VIOLATIONS):
        messages = [p.message for p in _problems(tmp_path / str(index), [_entry()], corrections)]
        if expected not in messages:
            missed.append((expected, messages))

    assert missed == []


def test_rejects_a_correction_without_a_reason_or_a_source_url(tmp_path: Path):
    corrections = {'review': {'status': 'draft'}, 'corrections': [_relabel(reason=' ', source='jordan-lawyer.com')]}

    rules = [(p.skill, p.rule) for p in _problems(tmp_path, [_entry()], corrections)]

    assert rules == [('corrections[0]', 'schema'), ('corrections[0]', 'source')]


MEMORANDUM_CORRECTION = {'note': 458, 'articles': [716, 717], 'reason': 'the heading names 716 only',
                         'evidence': 'the note opens «مصدر حكم هاتين المادتين»'}


def _memorandum(entries: object) -> dict:
    return {'review': {'status': 'draft'}, 'corrections': [], 'memorandum': entries}


# (memorandum list, (where, message) the checks must report). One case per rule.
MEMORANDUM_VIOLATIONS = [
    ({}, ('corrections.json', 'memorandum must be a list')),
    (['x'], ('memorandum[0]', 'each memorandum correction must be an object')),
    ([{**MEMORANDUM_CORRECTION, 'note': 0}], ('memorandum[0]', 'note must be an int >= 1')),
    ([MEMORANDUM_CORRECTION, MEMORANDUM_CORRECTION], ('memorandum[1]', 'note 458 is corrected more than once')),
    ([{**MEMORANDUM_CORRECTION, 'articles': [717, 716]}],
     ('memorandum[0]', 'articles must be a non-empty list of ints in strictly ascending order')),
    ([{**MEMORANDUM_CORRECTION, 'articles': []}],
     ('memorandum[0]', 'articles must be a non-empty list of ints in strictly ascending order')),
    ([{**MEMORANDUM_CORRECTION, 'reason': ' '}], ('memorandum[0]', 'reason must not be empty')),
    ([{key: value for key, value in MEMORANDUM_CORRECTION.items() if key != 'evidence'}],
     ('memorandum[0]', 'evidence must not be empty')),
]


def test_rejects_each_invalid_memorandum_correction(tmp_path: Path):
    reported = [[(p.skill, p.message) for p in _problems(tmp_path / str(index), [_entry()], _memorandum(entries))]
                for index, (entries, _) in enumerate(MEMORANDUM_VIOLATIONS)]
    valid = _problems(tmp_path / 'valid', [_entry()], _memorandum([MEMORANDUM_CORRECTION]))

    assert reported == [[expected] for _, expected in MEMORANDUM_VIOLATIONS]
    assert valid == []


def test_release_fails_while_the_corrections_are_draft(tmp_path: Path):
    problems = _problems(tmp_path, [_entry(review=APPROVED)], {'review': {'status': 'draft'}, 'corrections': []}, release=True)

    assert [(p.skill, p.rule) for p in problems] == [('corrections.json', 'review')]


def test_cli_prints_each_problem_and_exits_1(tmp_path: Path, capsys):
    content = tmp_path / 'content'
    (content / 'corpus').mkdir(parents=True)
    (content / 'corpus' / 'laws.json').write_text(json.dumps({'laws': [_entry()]}, ensure_ascii=False), encoding='utf-8')
    (content / 'corpus' / 'corrections.json').write_text(json.dumps({'review': APPROVED, 'corrections': []}), encoding='utf-8')
    corpus = _corpus(tmp_path / 'corpus')

    with pytest.raises(SystemExit) as exit_info:
        main(['--content', str(content), '--corpus', str(corpus), '--release'])

    assert exit_info.value.code == 1
    assert capsys.readouterr().out.splitlines() == [
        'FAIL penal-code: review: release needs review.status approved, approved_by and approved_on'
    ]
