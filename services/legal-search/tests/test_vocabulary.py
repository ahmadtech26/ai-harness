"""The everyday search vocabulary (vocabulary.py): its file, the directed expansion it adds to both engines' queries,
the switch that installs it, and the evaluation's record of it."""

import json
import re
import os
from pathlib import Path

import pytest
from psycopg import AsyncConnection

from legal_search import db, evaluate, synonyms
from legal_search.analysis import GuardLight, Lexicon, Today
from legal_search.corpus import Article
from legal_search.normalize import tokens
from legal_search.search_config import SearchConfig
from legal_search.vocabulary import (
    VOCABULARY_ENV,
    VocabularyError,
    load_vocabulary,
    parse_vocabulary,
    vocabulary_from_env,
)
from tests.pg import fresh

ENTRIES = [
    {'id': 'v01', 'everyday': ['طرد العامل', 'فصل الموظف'], 'statutory': 'فصل العامل', 'law': 'labour', 'articles': [28]},
    {'id': 'v02', 'everyday': ['الكمبيالة'], 'statutory': 'سند السحب', 'law': 'commerce', 'articles': [123]},
    {'id': 'v03', 'everyday': ['الشهادة السماعية'], 'statutory': 'الشهادة بالسماع', 'law': 'evidence', 'articles': [39]},
]


def _bytes(entries=ENTRIES, **top) -> bytes:
    doc = {'version': 1, 'review': {'status': 'draft'}, 'note': 'fixture', 'entries': entries, **top}
    return json.dumps(doc, ensure_ascii=False).encode('utf-8')


@pytest.fixture
def installed():
    """The fixture vocabulary installed for the test, and none again afterwards."""
    vocabulary = parse_vocabulary(_bytes())
    synonyms.use_vocabulary(vocabulary)
    yield vocabulary
    synonyms.use_vocabulary(None)


# The file.

def test_a_vocabulary_parses_into_one_pair_per_everyday_wording():
    vocabulary = parse_vocabulary(_bytes())

    assert vocabulary.pairs() == (
        ('طرد العامل', 'فصل العامل'), ('فصل الموظف', 'فصل العامل'), ('الكمبيالة', 'سند السحب'),
        ('الشهادة السماعية', 'الشهادة بالسماع'),
    )
    assert len(vocabulary.sha256) == 64


@pytest.mark.parametrize('entries, top, problem', [
    (ENTRIES, {'extra': 1}, "unknown keys ['extra']"),
    (ENTRIES, {'version': 2}, 'version must be 1'),
    ([], {}, 'entries must be a non-empty list'),
    ([{**ENTRIES[0], 'source': 'x'}], {}, "entry 1: unknown keys ['source']"),
    ([{'everyday': ['الكمبيالة'], 'law': 'commerce'}], {}, "entry 1: missing keys ['statutory']"),
    ([{**ENTRIES[1], 'everyday': []}], {}, 'entry 1: everyday must be a non-empty list of wordings'),
    ([{**ENTRIES[1], 'everyday': ['السند السحب']}], {}, 'is the statutory phrase itself'),
    ([{**ENTRIES[1], 'everyday': ['سب الشريك']}], {}, 'begins with a word under 3 letters'),
    ([ENTRIES[1], {**ENTRIES[1], 'statutory': 'سند الأمر'}], {}, 'entry 2: «الكمبيالة» is already in entry 1'),
    ([{**ENTRIES[1], 'articles': ['123']}], {}, 'articles must be a list of article numbers'),
])
def test_a_malformed_vocabulary_is_refused_naming_the_problem(entries, top, problem):
    with pytest.raises(VocabularyError, match=re.escape(problem)):
        parse_vocabulary(_bytes(entries, **top))


def test_the_switch_installs_nothing_unless_it_names_a_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(VOCABULARY_ENV, raising=False)
    assert vocabulary_from_env() is None
    monkeypatch.setenv(VOCABULARY_ENV, '  ')
    assert vocabulary_from_env() is None

    path = tmp_path / 'search-vocabulary.json'
    path.write_bytes(_bytes())
    monkeypatch.setenv(VOCABULARY_ENV, str(path))
    assert vocabulary_from_env() == load_vocabulary(path)

    monkeypatch.setenv(VOCABULARY_ENV, str(tmp_path / 'missing.json'))
    with pytest.raises(OSError):
        vocabulary_from_env()


# The expansion (Postgres search).

def test_without_a_vocabulary_an_everyday_query_is_searched_as_written():
    assert synonyms.DIRECTED == ()
    assert db.build_tsquery('طرد العامل من عمله', SearchConfig(synonyms=True)) == 'طرد:* | عامل:* | عمله:*'


def test_an_everyday_wording_adds_the_statutory_phrase(installed):
    assert db.build_tsquery('طرد العامل من عمله', SearchConfig(synonyms=True)) == (
        'طرد:* | عامل:* | عمله:* | (فصل:* <-> عامل:*)')
    # Each word of a wording matches as a prefix of the query word, as synonym members do.
    assert db.build_tsquery('دعوى بالكمبيالة', SearchConfig(synonyms=True)) == 'دعوي:* | كمبياله:* | (سند:* <-> سحب:*)'


def test_a_longer_everyday_word_does_not_count_as_the_statutory_word_it_begins_with(installed):
    # «السماعية» begins with «سماع», but the query searches «سماعيه:*», which never matches «بالسماع».
    assert db.build_tsquery('قبول الشهادة السماعية', SearchConfig(synonyms=True)) == (
        'قبول:* | شهاده:* | سماعيه:* | (شهاده:* <-> سماع:*)')


def test_the_expansion_runs_one_way_and_never_repeats_a_phrase_already_asked(installed):
    assert db.build_tsquery('فصل العامل', SearchConfig(synonyms=True)) == 'فصل:* | عامل:*'
    assert db.build_tsquery('طرد العامل فصل العامل', SearchConfig(synonyms=True)) == 'طرد:* | عامل:* | فصل:*'


def test_synonyms_off_turns_the_vocabulary_off_too(installed):
    assert db.build_tsquery('طرد العامل', SearchConfig(synonyms=False)) == 'طرد:* | عامل:*'


def test_the_vocabulary_adds_to_the_synonym_groups(installed):
    assert synonyms.synonym_terms(tokens('تقادم الكمبيالة')) == [
        '(مرور:* <-> زمان:*)', '(مرور:* <-> زمن:*)', '(سند:* <-> سحب:*)']


def test_installing_none_removes_the_vocabulary(installed):
    synonyms.use_vocabulary(None)

    assert (synonyms.RAW_DIRECTED, synonyms.DIRECTED, synonyms.VOCABULARY_SHA256) == ((), (), None)
    assert synonyms.synonym_terms(tokens('الكمبيالة')) == []


# The expansion (keyword engine): the same pairs, analysed with the engine's analyser.

ANALYSERS = {'today': Today, 'guardlight': lambda: GuardLight(Lexicon.from_texts(['سند السحب الكمبيالة دعوى الشهادة بالسماع']))}


@pytest.mark.parametrize('name', sorted(ANALYSERS))
def test_an_analyser_built_after_install_adds_the_statutory_phrase(installed, name):
    analyser = ANALYSERS[name]()

    assert analyser.synonym_members(analyser.tokens('دعوى الكمبيالة')) == [analyser.tokens('سند السحب')]
    assert analyser.synonym_members(analyser.tokens('سند السحب')) == []
    # Today keeps «سماعيه», which does not cover «سماع»; GuardLight strips the suffix, so the wording is the phrase.
    expected = [] if analyser.tokens('الشهادة السماعية') == analyser.tokens('الشهادة بالسماع') else [analyser.tokens('الشهادة بالسماع')]
    assert analyser.synonym_members(analyser.tokens('الشهادة السماعية')) == expected
    assert expected == {'today': [['شهاده', 'سماع']], 'guardlight': []}[name]


def test_an_analyser_built_without_a_vocabulary_adds_nothing():
    assert Today().synonym_members(Today().tokens('دعوى الكمبيالة')) == []


# Postgres: an everyday query finds the article worded in the statute only with the vocabulary.

@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        yield connection


@pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')
async def test_a_query_with_only_the_everyday_word_finds_nothing_without_the_vocabulary(conn):
    await db.upsert_articles(conn, [Article('commerce', 'قانون التجارة', 123, '', 'سند السحب يشتمل على البيانات التالية.', 's', 'a.md')])

    plain = await db.search(conn, 'الكمبيالة', 5, config=SearchConfig(synonyms=True))
    synonyms.use_vocabulary(parse_vocabulary(_bytes()))
    try:
        expanded = await db.search(conn, 'الكمبيالة', 5, config=SearchConfig(synonyms=True))
    finally:
        synonyms.use_vocabulary(None)

    assert plain == []
    assert [a.number for a in expanded] == [123]


# The evaluation records the vocabulary it searched with.

@pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')
async def test_a_run_records_the_vocabulary_it_searched_with(conn, tmp_path: Path):
    from tests.test_evaluate import _world

    sources = _world(tmp_path)
    plain = await evaluate.run_eval(os.environ['DATABASE_URL'], sources, 'plain')
    vocabulary = parse_vocabulary(_bytes())
    synonyms.use_vocabulary(vocabulary)
    try:
        with_vocabulary = await evaluate.run_eval(os.environ['DATABASE_URL'], sources, 'vocabulary')
    finally:
        synonyms.use_vocabulary(None)

    assert plain['run']['vocabulary_sha256'] is None
    assert with_vocabulary['run']['vocabulary_sha256'] == vocabulary.sha256


def test_the_settings_line_names_the_vocabulary():
    run = {'config': {}, 'vocabulary_sha256': 'ab' * 32}

    assert evaluate._settings(run) == 'vocabulary abababababab'
    assert evaluate._settings({'config': {}, 'vocabulary_sha256': None}) == 'defaults'


# The content file, when the content tree is mounted: every statutory phrase is in its law's ingested text, and every
# article the file lists exists and contains it.

def _content_vocabulary() -> Path | None:
    content = os.environ.get('CONTENT_DIR')
    path = Path(content) / 'corpus' / 'search-vocabulary.json' if content else None
    return path if path is not None and path.exists() else None


@pytest.mark.skipif(not (os.environ.get('CORPUS_DIR') and _content_vocabulary()), reason='real corpus and vocabulary not mounted')
def test_the_content_vocabulary_holds_to_the_ingested_corpus():
    from legal_search.corrections import load_corrections
    from legal_search.ingest import prepare
    from legal_search.registry import load_registry

    corpus_files = Path(os.environ['CONTENT_DIR']) / 'corpus'
    prepared = prepare(load_registry(corpus_files / 'laws.json'), load_corrections(corpus_files / 'corrections.json'),
                       Path(os.environ['CORPUS_DIR']))
    vocabulary = load_vocabulary(_content_vocabulary())
    raw = json.loads(_content_vocabulary().read_text(encoding='utf-8'))['entries']

    def holds(text: str, phrase: tuple[str, ...]) -> bool:
        words = tokens(text)
        return any(all(words[i + j].startswith(phrase[j]) for j in range(len(phrase))) for i in range(len(words) - len(phrase) + 1))

    problems = []
    for entry, row in zip(vocabulary.entries, raw, strict=True):
        articles = prepared.articles.get(entry.law)
        if articles is None:
            problems.append(f'{entry.statutory}: unknown law {entry.law}')
            continue
        phrase = tuple(tokens(entry.statutory))
        if not any(holds(article.text, phrase) for article in articles):
            problems.append(f'{entry.statutory}: not in {entry.law}')
        by_number = {article.number: article for article in articles if not article.suffix}
        for number in row.get('articles', []):
            if number not in by_number or not holds(by_number[number].text, phrase):
                problems.append(f'{entry.statutory}: {entry.law} {number} does not contain it')
    assert problems == []
