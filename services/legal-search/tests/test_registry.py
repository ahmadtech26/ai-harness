import json
from datetime import date
from pathlib import Path

import pytest

from legal_search.registry import Gap, RegistryError, directory_counts, load_registry

# Fixture values are deliberately not real citation data.
ENTRY = {
    'slug': 'penal-code',
    'title': 'قانون العقوبات الأردني',
    'folder': 'قانون-العقوبات-الأردني',
    'number': 99,
    'year': 1900,
    'gazette': {'issue': 1234, 'date': '1900-03-02', 'source_url': 'https://example.test/gazette'},
    'amendment': {'law': 7, 'year': 1950, 'gazette_issue': 4321, 'gazette_date': '1950-06-05',
                  'source_url': 'https://example.test/amendment'},
    'known_gaps': [{'number': 7, 'suffix': 'مكرر', 'reason': 'heading without text'}],
    'review': {'status': 'draft'},
    'sources': {'title': 'https://example.test/title'},
}


def _write(tmp_path: Path, laws: list[dict]) -> Path:
    path = tmp_path / 'laws.json'
    path.write_text(json.dumps({'laws': laws}, ensure_ascii=False), encoding='utf-8')
    return path


def test_reads_citation_fields_and_known_gaps(tmp_path: Path):
    [law] = load_registry(_write(tmp_path, [ENTRY]))

    assert (law.slug, law.number, law.year, law.gazette_issue, law.gazette_date) == ('penal-code', 99, 1900, 1234, date(1900, 3, 2))
    assert law.known_gaps == (Gap(7, 'مكرر', 'heading without text'),)
    # «آخر تعديل» in every citation reads these four fields.
    assert (law.amendment_law, law.amendment_year, law.amendment_gazette_issue, law.amendment_gazette_date) == (
        7, 1950, 4321, date(1950, 6, 5))
    assert law.approved is False


def test_rejects_a_duplicate_slug(tmp_path: Path):
    with pytest.raises(RegistryError, match='penal-code'):
        load_registry(_write(tmp_path, [ENTRY, ENTRY]))


def test_rejects_an_entry_without_a_folder(tmp_path: Path):
    entry = {key: value for key, value in ENTRY.items() if key != 'folder'}

    with pytest.raises(RegistryError, match='folder'):
        load_registry(_write(tmp_path, [entry]))


def test_reads_article_counts_from_the_law_directory(tmp_path: Path):
    path = tmp_path / 'law-directory.md'
    path.write_text(
        '| القانون | slug | المواد | الأقسام | الحالة | الفئة |\n|---|---|---|---|---|---|\n'
        '| قانون العقوبات الأردني | `قانون-العقوبات-الأردني` | 489 | 10 | complete | x |\n',
        encoding='utf-8',
    )

    assert directory_counts(path) == {'قانون-العقوبات-الأردني': 489}
