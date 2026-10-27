"""Retrieval evaluation set: parse the JSONL file and check it against the corpus (spec B.1, REQ-EVL-002).

Line 1 is the header: {"set": <name>, "review": {"status": "draft"|"approved", "approved_by"?, "approved_on"?}, ...}.
Every other non-empty line is one item:
  {"id", "question", "query", "law"?, "expected": [{"law", "number", "suffix"?}], "expected_notes"?, "notes"}
Retrieval is scored on `query`; `question` is kept for the Phase 4 end-to-end evaluation. `expected_notes` (a
memorandum item: exactly one Civil Code expected article) is [the note explaining that article] in plan A's
load_memorandum links: a data check, not a retrieval score. The set's sha256 covers the item lines only, so
flipping the header's review status does not change it.
"""

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from legal_search.corpus import Article
from legal_search.db import STOPWORDS
from legal_search.normalize import tokens

ITEM_KEYS = frozenset({'id', 'question', 'query', 'law', 'expected', 'expected_notes', 'notes'})
REQUIRED_KEYS = frozenset({'id', 'question', 'query', 'expected', 'notes'})
EXPECTED_KEYS = frozenset({'law', 'number', 'suffix'})
MEMORANDUM_LAW = 'civil-code'
MIN_QUERY_WORDS, MAX_QUERY_WORDS = 2, 8
COPY_WINDOW = 4  # a query may not repeat this many consecutive content words of an expected article

# Coverage (spec B.1): every law at least 2 items, more for the five most-used laws, 6 memorandum items.
MIN_PER_LAW = 2
MIN_FOR_LAW = {'civil-code': 12, 'majalla': 5, 'penal-code': 6, 'civil-procedure': 5, 'criminal-procedure': 5}
MIN_MEMORANDUM_ITEMS = 6
MIN_ITEMS = 75

_ID = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9]{2}$')
_ISO = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')


class EvalSetError(ValueError):
    pass


@dataclass(frozen=True)
class Expected:
    law: str
    number: int
    suffix: str = ''

    @property
    def key(self) -> tuple[str, int, str]:
        return (self.law, self.number, self.suffix)


@dataclass(frozen=True)
class Item:
    id: str
    question: str
    query: str
    law: str | None
    expected: tuple[Expected, ...]
    expected_notes: tuple[int, ...]
    notes: str

    @property
    def scored_law(self) -> str:
        """The law the item is reported under: that of its expected articles (one law per item)."""
        return self.expected[0].law


@dataclass(frozen=True)
class EvalSet:
    name: str
    review_status: str
    items: tuple[Item, ...]
    sha256: str


def content_words(text: str) -> list[str]:
    """Normalised words with db.STOPWORDS and one-letter tokens dropped (db.build_tsquery's base filter). Tuning's
    QUERY_STOPWORDS (candidate C3) is deliberately not applied: the 2-8 word rule and the copy check must not
    move with search tuning."""
    return [word for word in tokens(text) if word not in STOPWORDS and len(word) >= 2]


def parse_evalset(text: str) -> EvalSet:
    """Parse and shape-check the set; raises EvalSetError listing every problem with its line."""
    text = text.replace('\r\n', '\n')
    lines = [(number, line) for number, line in enumerate(text.split('\n'), 1) if line.strip()]
    if not lines:
        raise EvalSetError('line 1: the header is missing')
    problems: list[str] = []
    header = _object(*lines[0], problems)
    status = _review_status(header, problems) if header is not None else ''
    items: list[Item] = []
    for number, line in lines[1:]:
        raw = _object(number, line, problems)
        item = _item(number, raw, problems) if raw is not None else None
        if item is not None:
            items.append(item)
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            problems.append(f'duplicate id {item.id}')
        seen.add(item.id)
    if problems:
        raise EvalSetError('\n'.join(problems))
    fingerprint = hashlib.sha256('\n'.join(line for _, line in lines[1:]).encode('utf-8')).hexdigest()
    return EvalSet(str(header.get('set', '')), status, tuple(items), fingerprint)


def _object(number: int, line: str, problems: list[str]) -> dict | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as error:
        problems.append(f'line {number}: not JSON ({error.msg})')
        return None
    if not isinstance(value, dict):
        problems.append(f'line {number}: must be a JSON object')
        return None
    return value


def _review_status(header: dict, problems: list[str]) -> str:
    review = header.get('review')
    status = review.get('status') if isinstance(review, dict) else None
    if status not in ('draft', 'approved'):
        problems.append('header: review.status must be "draft" or "approved"')
        return ''
    if status == 'approved':
        if not review.get('approved_by'):
            problems.append('header: an approved set needs review.approved_by')
        if not _is_iso_date(review.get('approved_on')):
            problems.append('header: an approved set needs review.approved_on as YYYY-MM-DD')
    return status


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str) or not _ISO.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _item(number: int, raw: dict, problems: list[str]) -> Item | None:
    """One item, or None after recording why it cannot be read; rule breaks of a readable item are recorded too."""
    shape = _shape_problems(raw)
    if shape:
        problems.extend(f'line {number}: {problem}' for problem in shape)
        return None
    item = Item(
        id=raw['id'],
        question=raw['question'],
        query=raw['query'],
        law=raw.get('law'),
        expected=tuple(Expected(e['law'], e['number'], e.get('suffix', '').strip()) for e in raw['expected']),
        expected_notes=tuple(raw.get('expected_notes', ())),
        notes=raw['notes'],
    )
    problems.extend(f'line {number} ({item.id}): {problem}' for problem in _rule_problems(item))
    return item


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_expected(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and not entry.keys() - EXPECTED_KEYS
        and isinstance(entry.get('law'), str)
        and _is_int(entry.get('number'))
        and isinstance(entry.get('suffix', ''), str)
    )


def _shape_problems(raw: dict) -> list[str]:
    problems = []
    if raw.keys() - ITEM_KEYS:
        problems.append(f'unknown keys {sorted(raw.keys() - ITEM_KEYS)}')
    if REQUIRED_KEYS - raw.keys():
        return problems + [f'missing keys {sorted(REQUIRED_KEYS - raw.keys())}']
    for key in ('id', 'question', 'query'):
        if not isinstance(raw[key], str) or not raw[key].strip():
            problems.append(f'{key} must be a non-empty string')
    if not isinstance(raw['notes'], str):
        problems.append('notes must be a string')
    if 'law' in raw and not isinstance(raw['law'], str):
        problems.append('law must be a slug string')
    expected = raw['expected']
    if not isinstance(expected, list) or not expected or not all(_is_expected(entry) for entry in expected):
        problems.append('expected must be a non-empty list of {"law": slug, "number": int, "suffix"?: str}')
    if 'expected_notes' in raw:
        notes = raw['expected_notes']
        if not isinstance(notes, list) or not notes or not all(_is_int(note) for note in notes):
            problems.append('expected_notes must be a non-empty list of note numbers')
    return problems


def _rule_problems(item: Item) -> list[str]:
    problems = []
    law = item.scored_law
    if not _ID.match(item.id) or not item.id.startswith(f'{law}-'):
        problems.append(f'id must be "<law slug>-[<word>-]NN" with the slug of its expected law ({law})')
    if len({expected.law for expected in item.expected}) > 1:
        problems.append('every expected article must belong to one law')
    if len(set(item.expected)) < len(item.expected):
        problems.append('an expected article is listed twice')
    if item.law is not None and item.law != law:
        problems.append(f'law {item.law!r} differs from the expected law {law!r}')
    if item.expected_notes and (law != MEMORANDUM_LAW or len(item.expected) != 1):
        problems.append(f'expected_notes need exactly one {MEMORANDUM_LAW} expected article')
    words = len(content_words(item.query))
    if not MIN_QUERY_WORDS <= words <= MAX_QUERY_WORDS:
        problems.append(f'query has {words} content words; use {MIN_QUERY_WORDS} to {MAX_QUERY_WORDS}')
    return problems


def copied_phrase(query: str, article_text: str, window: int = COPY_WINDOW) -> str | None:
    """The first run of `window` consecutive content words the query shares with the article, or None."""
    words, article = content_words(query), content_words(article_text)
    runs = {tuple(article[i:i + window]) for i in range(len(article) - window + 1)}
    for i in range(len(words) - window + 1):
        if tuple(words[i:i + window]) in runs:
            return ' '.join(words[i:i + window])
    return None


def corpus_problems(evalset: EvalSet, articles: dict[str, list[Article]], explaining: dict[int, int]) -> list[str]:
    """Per item: laws known, expected articles present, no copied phrase, and a memorandum item's expected_notes
    equal to [the note explaining its article]. `explaining` maps a Civil Code article to that note
    (dict(load_memorandum(...).links); plan A gives at most one note per article)."""
    index = {(a.law_slug, a.number, a.suffix): a for law_articles in articles.values() for a in law_articles}
    problems: list[str] = []
    for item in evalset.items:
        problems += _item_corpus_problems(item, articles, index)
        problems += _memorandum_problems(item, explaining)
    return problems


def _memorandum_problems(item: Item, explaining: dict[int, int]) -> list[str]:
    if not item.expected_notes:
        return []
    number = item.expected[0].number  # parse_evalset: exactly one civil-code expected article
    own = explaining.get(number)
    if own is None:
        return [f'{item.id}: {MEMORANDUM_LAW} {number} has no explaining memorandum note; drop expected_notes']
    if list(item.expected_notes) != [own]:
        return [f'{item.id}: expected_notes {list(item.expected_notes)} must be [{own}], the note explaining {MEMORANDUM_LAW} {number}']
    return []


def _item_corpus_problems(item: Item, articles: dict[str, list[Article]], index: dict) -> list[str]:
    laws = sorted({item.law, *(expected.law for expected in item.expected)} - {None})
    problems = [f'{item.id}: unknown law {law!r}' for law in laws if law not in articles]
    for expected in item.expected:
        article = index.get(expected.key)
        if article is None:
            if expected.law in articles:
                problems.append(f'{item.id}: {expected.law} {f"{expected.number} {expected.suffix}".strip()} is not in the corpus')
            continue
        phrase = copied_phrase(item.query, article.text)
        if phrase:
            problems.append(f'{item.id}: query copies «{phrase}» from {article.law_slug} {article.label}')
    return problems


def coverage(evalset: EvalSet) -> dict[str, int]:
    """Items per law (the law each item is reported under), sorted by slug."""
    counts: dict[str, int] = {}
    for item in evalset.items:
        counts[item.scored_law] = counts.get(item.scored_law, 0) + 1
    return dict(sorted(counts.items()))


def coverage_problems(evalset: EvalSet, laws: Iterable[str]) -> list[str]:
    counts = coverage(evalset)
    problems = []
    for law in sorted(laws):
        need = MIN_FOR_LAW.get(law, MIN_PER_LAW)
        if counts.get(law, 0) < need:
            problems.append(f'coverage: {law} has {counts.get(law, 0)} items, needs at least {need}')
    memorandum = sum(1 for item in evalset.items if item.expected_notes)
    if memorandum < MIN_MEMORANDUM_ITEMS:
        problems.append(f'coverage: {memorandum} memorandum items, needs at least {MIN_MEMORANDUM_ITEMS}')
    if len(evalset.items) < MIN_ITEMS:
        problems.append(f'coverage: {len(evalset.items)} items, needs at least {MIN_ITEMS}')
    return problems
