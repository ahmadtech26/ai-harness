"""corpus-ci's verification-record checks (content/corpus/verification/<law-slug>.jsonl): schema and article coverage."""

import json
from pathlib import Path

import pytest

from skill_tools.corpus_checks import article_keys, check_verification, check_verification_record, heading_keys
from skill_tools.corpus_ci import main

SHA = 'a' * 64
# Fixture law: headings 1, ٢ (Arabic-Indic digits), 2 مكرر with inline text, 3 twice (the second relabelled by a
# correction), 4 (split by a correction into 4 and 4 مكرر), and 5, a heading with no text that the registry lists as
# a known gap. Fixture texts are not real statutory text.
SHARD = '''---
title: fixture
source: example.test
---

### المادة 1

نص أول.

---
### المادة ٢

نص ثان.

---
### المادة 2 مكرر — نص مكرر.

---
### المادة 3

نص ثالث.

---
### المادة 3

نص ثالث آخر.

---
### المادة 4

نص رابع. فقرة تفصل.

---
### المادة 5

'''
KEYS = [(1, ''), (2, ''), (2, 'مكرر'), (3, ''), (3, 'مكرر'), (4, ''), (4, 'مكرر')]
CORRECTIONS = {'review': {'status': 'draft'}, 'corrections': [
    {'type': 'relabel', 'law': 'demo-law', 'number': 3, 'occurrence': 2, 'new_suffix': 'مكرر',
     'reason': 'fixture', 'source': 'https://example.test/law'},
    {'type': 'split', 'law': 'demo-law', 'number': 4, 'marker': 'فقرة تفصل', 'second': {'number': 4, 'suffix': 'مكرر'},
     'reason': 'fixture', 'source': 'https://example.test/law'},
]}
ENTRY = {'slug': 'demo-law', 'folder': 'demo', 'known_gaps': [{'number': 5, 'reason': 'heading without text'}]}


def _corpus(root: Path) -> Path:
    sections = root / 'corpus' / 'demo' / 'sections'
    sections.mkdir(parents=True)
    (sections / '00-fixture.md').write_text(SHARD, encoding='utf-8')
    return root / 'corpus'


def record(number: int = 1, suffix: str = '', **changes) -> dict:
    value = {
        'law_slug': 'demo-law', 'number': number, 'suffix': suffix, 'text_sha256': SHA, 'result': 'unverifiable',
        'reason': 'gazette_offline', 'differs_from': None, 'difference': None, 'checked_on': '2026-11-14',
        'normalisation': 'v1', 'gazette': None, 'bureau': None, 'notes': None, 'lawyer_item': None,
    }
    value.update(changes)
    return value


def gazette(method: str = 'text', **reference) -> dict:
    original = {'issue': 1234, 'date': '1900-03-02', 'page': 10, 'document_id': 99, 'url': None, 'file_sha256': None}
    original.update(reference)
    return {'method': method, 'original': original, 'amendments': [], 'text_sha256': SHA, 'checked_on': '2026-11-14'}


BUREAU = {'legislation_id': 42, 'url': 'https://example.test/bureau/42', 'as_of': '2026-11-14', 'text_sha256': SHA,
          'checked_on': '2026-11-14'}


def verified(**changes) -> dict:
    return record(**{'result': 'verified', 'reason': None, 'gazette': gazette(), 'bureau': dict(BUREAU), **changes})


def _check(root: Path, lines: list, name: str = 'demo-law') -> list:
    corpus = _corpus(root)
    directory = root / 'verification'
    directory.mkdir()
    text = '\n'.join(line if isinstance(line, str) else json.dumps(line, ensure_ascii=False) for line in lines) + '\n'
    (directory / f'{name}.jsonl').write_text(text, encoding='utf-8')
    return check_verification(directory, {'laws': [ENTRY]}, CORRECTIONS, corpus)


def _all_records(**changes) -> list[dict]:
    return [record(number, suffix, **changes) for number, suffix in KEYS]


def test_heading_keys_read_numbers_suffixes_and_arabic_digits(tmp_path: Path):
    corpus = _corpus(tmp_path)

    assert heading_keys(corpus / 'demo') == [(1, ''), (2, ''), (2, 'مكرر'), (3, ''), (3, ''), (4, ''), (5, '')]


def test_article_keys_apply_relabel_split_and_known_gaps(tmp_path: Path):
    assert article_keys(ENTRY, CORRECTIONS, _corpus(tmp_path)) == KEYS


def test_one_valid_record_per_article_passes(tmp_path: Path):
    lines = _all_records()
    lines[0] = verified()
    lines[1] = record(2, result='differs', reason=None, differs_from='bureau', difference='formatting')

    assert _check(tmp_path, lines) == []


def test_no_directory_or_no_file_means_unverified_and_passes(tmp_path: Path):
    corpus = _corpus(tmp_path)
    (tmp_path / 'empty').mkdir()

    assert check_verification(tmp_path / 'missing', {'laws': [ENTRY]}, CORRECTIONS, corpus) == []
    assert check_verification(tmp_path / 'empty', {'laws': [ENTRY]}, CORRECTIONS, corpus) == []


def test_reports_a_missing_an_extra_and_a_duplicate_record(tmp_path: Path):
    lines = _all_records()[1:] + [record(5), record(2)]

    problems = [(p.skill, p.rule, p.message) for p in _check(tmp_path, lines)]

    assert problems == [
        ('verification/demo-law.jsonl:7', 'articles', 'المادة 5 is not an article of this law in the corpus'),
        ('verification/demo-law.jsonl:8', 'articles', 'المادة 2 has more than one record'),
        ('verification/demo-law.jsonl', 'articles', '1 corpus article(s) have no record: المادة 1'),
    ]


def test_rejects_a_file_for_a_law_not_in_the_registry(tmp_path: Path):
    problems = _check(tmp_path, [record(law_slug='other-law')], name='other-law')

    assert [(p.skill, p.message) for p in problems] == [('verification/other-law.jsonl', "'other-law' is not a law in the registry")]


def _without(key: str) -> dict:
    value = record()
    del value[key]
    return value


def _with_gazette(**changes) -> dict:
    return {**gazette(), **changes}


# (record, (rule, message) the check must report). One case per rule, so dropping a rule fails this test.
RECORD_VIOLATIONS = [
    ('[1]', ('schema', 'each line must be a JSON object')),
    (record(source='jordan-lawyer.com'), ('schema', 'unknown field source')),
    (_without('lawyer_item'), ('schema', 'missing field lawyer_item')),
    (record(number='1'), ('schema', 'number must be an int')),
    (record(suffix=None), ('schema', 'suffix must not be null')),
    (record(text_sha256='ABC'), ('schema', 'text_sha256 must be a sha256 (64 lowercase hex digits)')),
    (record(law_slug='civil-code'), ('schema', "law_slug 'civil-code' is not the file's law 'demo-law'")),
    (record(result='checked'), ('schema', 'result must be one of verified, differs, unverifiable')),
    (record(reason='offline'), ('schema', 'reason must be one of gazette_offline, gazette_image_unread, '
                                          'bureau_unreachable, no_official_source, sources_disagree')),
    (record(differs_from='lob'), ('schema', 'differs_from must be one of gazette, bureau, both')),
    (record(difference='wording'), ('schema', 'difference must be one of formatting, trailing-title, body, repeal')),
    (record(normalisation='v2'), ('schema', 'normalisation must be one of v1')),
    (record(checked_on='2026-02-30'), ('date', 'checked_on must be an ISO date (YYYY-MM-DD)')),
    (record(checked_on='14/11/2026'), ('date', 'checked_on must be an ISO date (YYYY-MM-DD)')),
    (record(gazette=gazette(date='1900-3-2')), ('date', 'gazette.original.date must be an ISO date (YYYY-MM-DD)')),
    (record(gazette=gazette(method='pdf')), ('schema', 'gazette.method must be one of text, image')),
    (record(gazette=gazette(url='doc.pm.gov.jo/1')), ('schema', 'gazette.original.url must be an http(s) URL')),
    (record(gazette=gazette(editor='x')), ('schema', 'unknown field gazette.original.editor')),
    (record(gazette=_with_gazette(amendments=[{'law': 7}])), ('schema', 'missing field gazette.amendments[0].effect')),
    (record(gazette=_with_gazette(amendments=[{
        'law': 7, 'year': 1901, 'issue': 1300, 'date': '1901-05-06', 'page': 3, 'effect': 'changed',
        'document_id': None, 'url': None, 'file_sha256': None}])),
     ('schema', 'gazette.amendments[0].effect must be one of amended, replaced, added, repealed, renumbered')),
    (record(bureau={**BUREAU, 'as_of': '2026'}), ('date', 'bureau.as_of must be an ISO date (YYYY-MM-DD)')),
    (record(bureau={**BUREAU, 'version': 3}), ('schema', 'unknown field bureau.version')),
    (record(lawyer_item=12), ('schema', 'lawyer_item must be a string')),
    (record(reason=None), ('schema', 'an unverifiable record needs a reason')),
    (record(result='differs', reason=None, differs_from='gazette'), ('schema', 'a differs record needs difference')),
    (verified(reason='sources_disagree'), ('schema', 'a verified record must have reason null')),
    (verified(bureau=None), ('schema', 'a verified record needs the bureau block')),
    (verified(gazette=None), ('schema', 'a verified record needs the gazette block')),
    (verified(bureau={**BUREAU, 'legislation_id': None}), ('schema', 'a verified record needs bureau.legislation_id')),
    (verified(gazette={**gazette(), 'text_sha256': None}), ('schema', 'a verified record needs gazette.text_sha256')),
    (verified(gazette=gazette(page=None)),
     ('schema', 'a verified record needs a Gazette reference (gazette.original or an amendment) with issue, date, '
                'page and document_id or url')),
    (verified(gazette=gazette(method='image')),
     ('schema', 'a verified record needs a Gazette reference (gazette.original or an amendment) with issue, date, '
                'page and document_id or url, and file_sha256 (method image)')),
]


def test_rejects_each_record_violation():
    missed = []
    for value, expected in RECORD_VIOLATIONS:
        found = check_verification_record(json.loads(value) if isinstance(value, str) else value, 'demo-law')
        if expected not in found:
            missed.append((expected, found))

    assert missed == []


def test_accepts_the_filled_forms_of_a_verified_record():
    image = verified(gazette=gazette(method='image', file_sha256=SHA))
    amended_only = verified(gazette={**gazette(), 'original': None, 'amendments': [{
        'law': 7, 'year': 1901, 'issue': '1300', 'date': '1901-05-06', 'page': '12-13', 'effect': 'replaced',
        'document_id': None, 'url': 'https://example.test/gazette/1300', 'file_sha256': None}]})
    with_norm = verified(norm_sha256=SHA, notes='trailing heading «الفصل الثاني» set aside', lawyer_item='companies-3')

    assert [check_verification_record(value, 'demo-law') for value in (image, amended_only, with_norm)] == [[], [], []]


def test_reports_lines_that_are_not_json_or_blank(tmp_path: Path):
    lines = _all_records()
    lines[1:1] = ['{"law_slug": ', '']

    problems = [(p.skill, p.message) for p in _check(tmp_path, lines)]

    assert problems == [('verification/demo-law.jsonl:2', 'not JSON: Expecting value'),
                        ('verification/demo-law.jsonl:3', 'blank line')]


def test_caps_the_problems_shown_per_file(tmp_path: Path):
    # 28 records with a bad result, and 7 keys with more than one record: 35 problems, 20 shown.
    problems = _check(tmp_path, [record(number, suffix, result='done') for number, suffix in KEYS] * 4)

    assert len(problems) == 21
    assert problems[-1].message == '15 more problem(s) not shown'


def _content(root: Path, lines: list[dict]) -> tuple[Path, Path]:
    content = root / 'content'
    (content / 'corpus' / 'verification').mkdir(parents=True)
    entry = {**ENTRY, 'title': 'قانون تجريبي', 'review': {'status': 'draft'}, 'sources': {'title': 'https://example.test/law'}}
    (content / 'corpus' / 'laws.json').write_text(json.dumps({'laws': [entry]}, ensure_ascii=False), encoding='utf-8')
    (content / 'corpus' / 'corrections.json').write_text(json.dumps(CORRECTIONS, ensure_ascii=False), encoding='utf-8')
    (content / 'corpus' / 'verification' / 'demo-law.jsonl').write_text(
        ''.join(json.dumps(line, ensure_ascii=False) + '\n' for line in lines), encoding='utf-8')
    (content / 'corpus' / 'verification' / 'README.md').write_text('not a record\n', encoding='utf-8')
    return content, _corpus(root)


def test_cli_passes_and_names_the_laws_with_a_file(tmp_path: Path, capsys):
    content, corpus = _content(tmp_path, _all_records())

    main(['--content', str(content), '--corpus', str(corpus)])

    assert capsys.readouterr().out.splitlines() == [
        'corpus-ci: registry, corrections and verification records pass; laws with a verification file: demo-law']


def test_cli_fails_on_a_record_problem(tmp_path: Path, capsys):
    content, corpus = _content(tmp_path, _all_records()[:-1])

    with pytest.raises(SystemExit) as exit_info:
        main(['--content', str(content), '--corpus', str(corpus)])

    assert exit_info.value.code == 1
    assert capsys.readouterr().out.splitlines() == [
        'FAIL verification/demo-law.jsonl: articles: 1 corpus article(s) have no record: المادة 4 مكرر']
