"""The Civil Code explanatory memorandum (memorandum_civil_law.json in the corpus folder) and the Civil Code
articles each of its notes explains.

The source glued each note's heading onto the end of the previous note: note 73 ends «المذكرة الايضاحية
للمادة (107)», so note 74 explains article 107. The links are read from those headings only;
memorandum-article-index.json is not used (most of its links are citations of other codes, not the note
that explains an article). Where a heading is missing or wrong, an entry of the corrections file's
`memorandum` list sets the note's articles."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

NOTES_FILE = 'memorandum_civil_law.json'
HEADING_WINDOW = 220  # characters: a heading is looked for in a note's last 220 only, anchored at its end

# Every heading form in the 766 notes; the note that ends with each typo is in brackets.
_HEADING = re.compile(
    r'(?:المذكر|المكر|الماد)[ةه]\s*'          # المذكرة; typos «المكرة» (353), «المادة» (157)
    r'ال[اإأآ]?يضا(?:حي|يح)[ةه]\s*'          # الايضاحية; typo «الايضايحة» (158)
    r'لل(?:ماد[ةه]|مادتين|مواد|مد[ةه])\s*'   # للمادة, للمادتين, للمواد; typo «للمدة» (188)
    r'(?:من\s*)?'                             # «للمواد من ( 214 - 238)» (165)
    r'(?P<numbers>[0-9()\s\-و]*[0-9][0-9()\s\-و]*)'
    r'[\s.]*$'
)
# One «و»-separated part of the numbers, brackets removed: a number, or an inclusive range «A - B».
_PART = re.compile(r'(?P<first>[0-9]+)(?:\s*-\s*(?P<last>[0-9]+))?')


class MemorandumError(ValueError):
    pass


@dataclass(frozen=True)
class MemorandumCorrection:
    """The Civil Code articles a note explains, where the heading before it is missing or wrong."""

    note: int
    articles: tuple[int, ...]
    reason: str
    evidence: str


def _numbers(raw: str) -> list[int] | None:
    """`( 108 - 110)` → [108, 109, 110]; `(13) و ( 14) و (15)` → [13, 14, 15]; None when a part is unreadable."""
    numbers: list[int] = []
    for part in raw.replace('(', ' ').replace(')', ' ').split('و'):
        match = _PART.fullmatch(part.strip())
        if match is None:
            return None
        first = int(match['first'])
        last = int(match['last'] or first)
        if last < first:
            return None
        numbers.extend(range(first, last + 1))
    return numbers


def _heading(text: str) -> tuple[int, list[int] | None] | None:
    """Where the heading at the end of `text` starts, and the articles it names (None if its numbers are
    unreadable); None when `text` does not end with a heading."""
    match = _HEADING.search(text, max(0, len(text) - HEADING_WINDOW))
    if match is None:
        return None
    return match.start(), _numbers(match['numbers'])


def parse_heading(tail: str) -> list[int] | None:
    """The Civil Code articles named by a heading at the end of `tail`, ranges expanded; None when there is
    none or its numbers are unreadable (a reference such as «تراجع المذكرة الايضاحية للمادة (246)» inside the
    text is not a heading)."""
    found = _heading(tail)
    return found[1] if found else None


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _memorandum_correction(entry: object, name: str) -> MemorandumCorrection:
    if not isinstance(entry, dict):
        raise MemorandumError(f'{name}: each memorandum correction must be an object')
    note, articles = entry.get('note'), entry.get('articles')
    if not (_is_int(note) and note >= 1):
        raise MemorandumError(f'{name}: note must be an int >= 1')
    ascending = (isinstance(articles, list) and bool(articles) and all(_is_int(a) for a in articles)
                 and all(a < b for a, b in zip(articles, articles[1:])))
    if not ascending:
        raise MemorandumError(f'{name}: articles must be a non-empty list of ints in strictly ascending order')
    for key in ('reason', 'evidence'):
        if not (isinstance(entry.get(key), str) and entry[key].strip()):
            raise MemorandumError(f'{name}: {key} must not be empty')
    return MemorandumCorrection(note, tuple(articles), entry['reason'], entry['evidence'])


def load_memorandum_corrections(path: Path) -> list[MemorandumCorrection]:
    """The corrections file's `memorandum` list (none when the key is absent), every entry checked."""
    entries = json.loads(path.read_text(encoding='utf-8')).get('memorandum', [])
    if not isinstance(entries, list):
        raise MemorandumError('corrections file: memorandum must be a list')
    corrections: list[MemorandumCorrection] = []
    for index, entry in enumerate(entries):
        correction = _memorandum_correction(entry, f'memorandum[{index}]')
        if any(existing.note == correction.note for existing in corrections):
            raise MemorandumError(f'memorandum[{index}]: note {correction.note} is corrected more than once')
        corrections.append(correction)
    return corrections


@dataclass(frozen=True)
class Memorandum:
    source: str
    notes: dict[int, str]  # note_no -> text, without the heading of the next note
    links: list[tuple[int, int]]  # (Civil Code article, note_no), sorted
    uncovered: list[int]  # Civil Code articles that no note explains


def _check(note_no: int, articles: list[int], previous: tuple[int, int] | None, civil_articles: int) -> None:
    """A note's articles ascend, lie in the Civil Code and come after the previous note's (note_no, last article)."""
    if any(b <= a for a, b in zip(articles, articles[1:])):
        raise MemorandumError(f'memorandum note {note_no}: articles {articles} are not in strictly ascending order')
    outside = [article for article in articles if not 1 <= article <= civil_articles]
    if outside:
        raise MemorandumError(f'memorandum note {note_no}: article {outside[0]} is outside 1..{civil_articles}')
    if previous and articles[0] <= previous[1]:
        raise MemorandumError(
            f'memorandum note {note_no}: article {articles[0]} is not after the last article of note {previous[0]} ({previous[1]})'
        )


def load_memorandum(
    corpus: Path, corrections: Sequence[MemorandumCorrection] = (), civil_articles: int = 1449
) -> Memorandum:
    """The notes and their article links, read from the memorandum's own headings (the heading at the end of a
    note names the next note's articles), a correction replacing the set for its note. Raises MemorandumError
    naming the note when a note has no articles, when its articles are out of order or overlap the previous
    note's, or when one falls outside 1..civil_articles."""
    document = json.loads((corpus / NOTES_FILE).read_text(encoding='utf-8'))
    raw = {int(number): str(text).strip() for number, text in document['articles'].items()}
    numbers = sorted(raw)
    notes: dict[int, str] = {}
    named: dict[int, list[int] | None] = {}  # note_no -> the articles named by the heading before it
    for index, note_no in enumerate(numbers):
        heading = _heading(raw[note_no])
        notes[note_no] = raw[note_no][:heading[0]].rstrip() if heading else raw[note_no]
        if heading and index + 1 < len(numbers):
            named[numbers[index + 1]] = heading[1]
    for correction in corrections:
        if correction.note not in notes:
            raise MemorandumError(f'memorandum correction for note {correction.note}: the memorandum has no such note')
        named[correction.note] = list(correction.articles)
    links: list[tuple[int, int]] = []
    previous: tuple[int, int] | None = None  # (note_no, its last article)
    for index, note_no in enumerate(numbers):
        articles = named.get(note_no)
        if not articles:
            where = f'the end of note {numbers[index - 1]}' if index else 'no note precedes it'
            raise MemorandumError(
                f'memorandum note {note_no} has no readable heading naming its articles ({where}); add a memorandum correction'
            )
        _check(note_no, articles, previous, civil_articles)
        links += [(article, note_no) for article in articles]
        previous = (note_no, articles[-1])
    covered = {article for article, _ in links}
    uncovered = [article for article in range(1, civil_articles + 1) if article not in covered]
    return Memorandum(document.get('source', ''), notes, sorted(links), uncovered)
