"""Everyday search vocabulary (content/corpus/search-vocabulary.json): a candidate search lever, off unless
LEGAL_SEARCH_VOCABULARY names the file.

Each entry maps everyday wordings a client may type («طرد العامل», «الكمبيالة», «الشهادة السماعية») to the statutory
noun phrase the mapped law uses («فصل العامل», «سند السحب», «الشهادة بالسماع»). With a vocabulary installed
(synonyms.use_vocabulary), a query holding an everyday wording also searches the statutory phrase: synonyms.synonym_terms
adds it to the Postgres query and analysis.Analyser.synonym_members to the keyword engine's, matched the way synonym
groups are (each word a prefix of the query word, in order). Unlike a group it works in one direction only: a query worded
in the statute adds nothing. It rides on SearchConfig.synonyms, so synonyms=false turns it off as well.

The file is content (draft, for lawyer review): `everyday` wordings, the `statutory` phrase, its `law` slug and, for the
reviewer, `articles` that contain the phrase; the content tests hold each phrase to the mapped law's text. No deploy
file sets LEGAL_SEARCH_VOCABULARY: a vocabulary is measured with `legal-search-eval run` (which reads the same
variable and records the file's sha256) before any server uses it.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from legal_search.normalize import tokens

VOCABULARY_ENV = 'LEGAL_SEARCH_VOCABULARY'
VERSION = 1
TOP_KEYS = frozenset({'version', 'review', 'note', 'entries'})
ENTRY_KEYS = frozenset({'id', 'everyday', 'statutory', 'law', 'articles'})
REQUIRED_ENTRY_KEYS = frozenset({'everyday', 'statutory', 'law'})
# A wording's first word is matched as a prefix of a query word, so it must be long enough not to match unrelated words
# («سب» would match «سبب» and «سبيل»).
MIN_LEAD_LETTERS = 3


class VocabularyError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    everyday: tuple[str, ...]
    statutory: str
    law: str


@dataclass(frozen=True)
class Vocabulary:
    entries: tuple[Entry, ...]
    sha256: str  # of the file's bytes: a run records which vocabulary it searched with

    def pairs(self) -> tuple[tuple[str, str], ...]:
        """(everyday wording, statutory phrase), one per wording, in file order."""
        return tuple((word, entry.statutory) for entry in self.entries for word in entry.everyday)


def parse_vocabulary(data: bytes) -> Vocabulary:
    """Parse and check the file; raises VocabularyError listing every problem."""
    try:
        doc = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VocabularyError(f'not JSON: {error}') from error
    if not isinstance(doc, dict):
        raise VocabularyError('the vocabulary must be a JSON object')
    problems = [f'unknown keys {sorted(doc.keys() - TOP_KEYS)}'] if doc.keys() - TOP_KEYS else []
    if doc.get('version') != VERSION:
        problems.append(f'version must be {VERSION}')
    raw_entries = doc.get('entries')
    if not isinstance(raw_entries, list) or not raw_entries:
        raise VocabularyError('; '.join(problems + ['entries must be a non-empty list']))
    entries: list[Entry] = []
    owner: dict[tuple[str, ...], int] = {}
    for number, raw in enumerate(raw_entries, 1):
        entry_problems = _entry_problems(raw)
        if entry_problems:
            problems += [f'entry {number}: {problem}' for problem in entry_problems]
            continue
        entry = Entry(tuple(raw['everyday']), raw['statutory'], raw['law'])
        statutory = tuple(tokens(entry.statutory))
        for word in entry.everyday:
            words = tuple(tokens(word))
            if words == statutory:
                problems.append(f'entry {number}: «{word}» is the statutory phrase itself')
            elif len(words[0]) < MIN_LEAD_LETTERS:
                problems.append(f'entry {number}: «{word}» begins with a word under {MIN_LEAD_LETTERS} letters')
            elif words in owner:
                problems.append(f'entry {number}: «{word}» is already in entry {owner[words]}')
            else:
                owner[words] = number
        entries.append(entry)
    if problems:
        raise VocabularyError('; '.join(problems))
    return Vocabulary(tuple(entries), hashlib.sha256(data).hexdigest())


def _entry_problems(raw: object) -> list[str]:
    if not isinstance(raw, dict):
        return ['must be a JSON object']
    problems = [f'unknown keys {sorted(raw.keys() - ENTRY_KEYS)}'] if raw.keys() - ENTRY_KEYS else []
    if REQUIRED_ENTRY_KEYS - raw.keys():
        return problems + [f'missing keys {sorted(REQUIRED_ENTRY_KEYS - raw.keys())}']
    everyday = raw['everyday']
    if not isinstance(everyday, list) or not everyday or not all(isinstance(w, str) and tokens(w) for w in everyday):
        problems.append('everyday must be a non-empty list of wordings')
    for key in ('statutory', 'law'):
        if not isinstance(raw[key], str) or not tokens(raw[key]):
            problems.append(f'{key} must be a non-empty string')
    articles = raw.get('articles', [1])
    if not isinstance(articles, list) or not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in articles):
        problems.append('articles must be a list of article numbers')
    return problems


def load_vocabulary(path: Path) -> Vocabulary:
    return parse_vocabulary(Path(path).read_bytes())


def vocabulary_from_env() -> Vocabulary | None:
    """The vocabulary LEGAL_SEARCH_VOCABULARY names, or None when it is unset or blank. A named file that is missing or
    invalid raises (OSError or VocabularyError), which stops the server or the run before it starts."""
    path = os.environ.get(VOCABULARY_ENV, '').strip()
    return load_vocabulary(Path(path)) if path else None
