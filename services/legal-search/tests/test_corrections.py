import json
from pathlib import Path

import pytest

from legal_search.corpus import Article
from legal_search.corrections import CorrectionError, apply_corrections, load_corrections


def _article(number: int, suffix: str, text: str) -> Article:
    return Article('penal-code', 'قانون العقوبات الأردني', number, suffix, text, 's', 'x.md')


def _corrections(tmp_path: Path, *entries: dict) -> list:
    base = {'law': 'penal-code', 'reason': 'test', 'source': 'https://example.test/source'}
    path = tmp_path / 'corrections.json'
    document = {'review': {'status': 'draft'}, 'corrections': [{**base, **entry} for entry in entries]}
    path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
    return load_corrections(path)


def test_relabel_renames_only_the_named_occurrence(tmp_path: Path):
    articles = [_article(25, 'مكرر', 'الأولى'), _article(25, 'مكرر', 'الثانية')]
    corrections = _corrections(
        tmp_path, {'type': 'relabel', 'number': 25, 'suffix': 'مكرر', 'occurrence': 2, 'new_suffix': 'مكرر ثانياً'}
    )

    result = apply_corrections(articles, corrections)

    assert [(a.suffix, a.text) for a in result] == [('مكرر', 'الأولى'), ('مكرر ثانياً', 'الثانية')]


def test_replace_sets_the_new_text(tmp_path: Path):
    corrections = _corrections(tmp_path, {'type': 'replace', 'number': 7, 'text': 'النص المصحح.'})

    result = apply_corrections([_article(7, '', 'نص فيه خطأ.')], corrections)

    assert result[0].text == 'النص المصحح.'


def test_split_makes_two_articles_at_the_marker(tmp_path: Path):
    corrections = _corrections(
        tmp_path, {'type': 'split', 'number': 8, 'marker': 'المادة التاسعة:', 'second': {'number': 9, 'suffix': 'مكرر'}}
    )

    result = apply_corrections([_article(8, '', 'نص الثامنة. المادة التاسعة: نص التاسعة.')], corrections)

    assert [(a.number, a.suffix, a.text) for a in result] == [
        (8, '', 'نص الثامنة.'), (9, 'مكرر', 'المادة التاسعة: نص التاسعة.')]


def test_a_correction_that_matches_nothing_fails_naming_its_target(tmp_path: Path):
    corrections = _corrections(tmp_path, {'type': 'replace', 'number': 99, 'text': 'x'})

    with pytest.raises(CorrectionError, match='penal-code المادة 99'):
        apply_corrections([_article(7, '', 'نص.')], corrections)


def test_an_incomplete_correction_is_rejected(tmp_path: Path):
    path = tmp_path / 'corrections.json'
    entry = {'type': 'replace', 'law': 'penal-code', 'number': 7, 'text': 'x', 'reason': 'r'}
    path.write_text(json.dumps({'corrections': [entry]}), encoding='utf-8')
    with pytest.raises(CorrectionError, match='source'):
        load_corrections(path)

    # A split without the second article's number would only fail much later, in the database.
    with pytest.raises(CorrectionError, match='second.number'):
        _corrections(tmp_path, {'type': 'split', 'number': 8, 'marker': 'م', 'second': {}})
