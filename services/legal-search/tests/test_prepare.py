import json
from pathlib import Path

import pytest

from legal_search.corrections import load_corrections
from legal_search.ingest import IngestError, prepare
from legal_search.registry import Gap, Law

LAW = Law(slug='penal-code', title='قانون العقوبات الأردني', folder='penal')
BODY = '### المادة 1\n\nنص المادة الأولى من القانون.\n\n---\n\n### المادة 2\n\nنص المادة الثانية من القانون.\n'


def _corpus(tmp_path: Path, body: str, count: int) -> Path:
    sections = tmp_path / 'corpus' / 'penal' / 'sections'
    sections.mkdir(parents=True, exist_ok=True)
    (sections / '00.md').write_text('---\nparent_law: عنوان الشريحة\nsource: example.test\n---\n\n' + body, encoding='utf-8')
    (tmp_path / 'corpus' / 'law-directory.md').write_text(
        '| القانون | slug | المواد | الأقسام | الحالة | الفئة |\n|---|---|---|---|---|---|\n'
        f'| law | `penal` | {count} | 1 | complete | x |\n',
        encoding='utf-8',
    )
    return tmp_path / 'corpus'


def test_loads_a_law_whose_count_matches_its_directory(tmp_path: Path):
    prepared = prepare([LAW], [], _corpus(tmp_path, BODY, 2))

    assert [a.number for a in prepared.articles['penal-code']] == [1, 2]
    assert {a.law_title for a in prepared.articles['penal-code']} == {'قانون العقوبات الأردني'}


def test_a_count_short_of_the_directory_fails_naming_the_law(tmp_path: Path):
    with pytest.raises(IngestError, match='penal-code: parsed 2 articles, expected 3'):
        prepare([LAW], [], _corpus(tmp_path, BODY, 3))


def test_a_known_gap_lowers_the_expected_count(tmp_path: Path):
    law = Law(slug='penal-code', title='قانون العقوبات الأردني', folder='penal', known_gaps=(Gap(3, '', 'no text'),))

    prepared = prepare([law], [], _corpus(tmp_path, BODY, 3))

    assert len(prepared.articles['penal-code']) == 2


def test_a_duplicate_article_fails_naming_the_law_and_article(tmp_path: Path):
    body = BODY + '\n---\n\n### المادة 2\n\nنص آخر يحمل رقم المادة الثانية.\n'

    with pytest.raises(IngestError, match='penal-code: duplicate article المادة 2'):
        prepare([LAW], [], _corpus(tmp_path, body, 3))


def test_reports_articles_shorter_than_15_characters(tmp_path: Path):
    body = BODY + '\n---\n\n### المادة 3\n\nملغاة.\n'

    prepared = prepare([LAW], [], _corpus(tmp_path, body, 3))

    assert [a.label for a in prepared.short] == ['المادة 3']


def test_corrections_are_applied_before_the_duplicate_check(tmp_path: Path):
    body = BODY + '\n---\n\n### المادة 2\n\nنص آخر يحمل رقم المادة الثانية.\n'
    path = tmp_path / 'corrections.json'
    relabel = {'type': 'relabel', 'law': 'penal-code', 'number': 2, 'occurrence': 2, 'new_suffix': 'مكرر',
               'reason': 'test', 'source': 'https://example.test'}
    path.write_text(json.dumps({'corrections': [relabel]}, ensure_ascii=False), encoding='utf-8')

    prepared = prepare([LAW], load_corrections(path), _corpus(tmp_path, body, 3))

    assert [(a.number, a.suffix) for a in prepared.articles['penal-code']] == [(1, ''), (2, ''), (2, 'مكرر')]
