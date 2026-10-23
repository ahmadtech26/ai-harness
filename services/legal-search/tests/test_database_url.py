import pytest

from legal_search.db import database_url


def test_reads_the_url_from_a_file_without_trailing_newline(tmp_path, monkeypatch):
    secret = tmp_path / 'database_url'
    secret.write_text('postgresql://u:p@db:5432/legal\n', encoding='utf-8')
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('DATABASE_URL_FILE', str(secret))

    url = database_url()

    assert url == 'postgresql://u:p@db:5432/legal'


def test_environment_value_wins_over_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://env/legal')
    monkeypatch.setenv('DATABASE_URL_FILE', str(tmp_path / 'missing'))

    url = database_url()

    assert url == 'postgresql://env/legal'


def test_fails_when_neither_is_set(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('DATABASE_URL_FILE', raising=False)

    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        database_url()
