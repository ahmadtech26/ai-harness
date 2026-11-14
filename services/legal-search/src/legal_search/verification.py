"""The verification records (content/corpus/verification/<law-slug>.jsonl, in the folder beside the registry) as the
ingest reads them, and the hash rule that ties a record to the text the library stores.

One JSON object per line, one line per corpus article of the law (content PRs, owner's instructions 2026-11-14 §2).
The ingest reads `law_slug`, `number`, `suffix`, `text_sha256`, `result`, `checked_on`, the Gazette references of
`gazette` and the `bureau` block; every other key is the record's own (corpus-ci checks the schema).

An article is verified only when its record's `result` is `verified` and its `text_sha256` equals the sha256 of the
UTF-8 of the text the ingest stores (`ingest.prepare`'s text, corrections applied): a later change to the text
unverifies it until the record is redone. Without the folder, or without a file for a law, no article of it is
verified.

`match` never refuses a run: a record it cannot use leaves its article unverified, and each such record is one of its
problems. The ingest prints them; `legal-search-ingest --check-verification` fails on any.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from legal_search.corpus import Article

VERIFICATION_DIR = 'verification'
RESULTS = ('verified', 'differs', 'unverifiable')
# An amendment with one of these effects is where the text in force begins: it replaced the whole text, inserted the
# article («مكرر») or repealed it. Later amendments touched that text; earlier issues are history.
_TEXT_STARTS = ('replaced', 'added', 'repealed')
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
# An issue, page or legislation id as the label prints it: ASCII letters and digits, inner «.», «/» and «-» («12-13»).
# Nothing that could end the label early or move its dash («؛», «)», « — »).
_TOKEN = re.compile(r'^[0-9A-Za-z](?:[0-9A-Za-z./-]*[0-9A-Za-z])?$')

Key = tuple[str, int, str]  # (law slug, number, suffix)


@dataclass(frozen=True)
class GazetteRef:
    """One Official Gazette issue of an article's text in force, and its page as the record gives it."""

    issue: str
    page: str | None = None


@dataclass(frozen=True)
class Verification:
    """What the library shows for a verified article: the Gazette issues of the text in force, the Bureau's legislation
    id and the date of the version it showed, and the day the record was checked (stored as articles.verified_at)."""

    checked_on: date
    gazette: tuple[GazetteRef, ...]
    bureau_id: str
    bureau_as_of: date | None = None

    def gazette_column(self) -> list[dict]:
        """articles.verified_gazette."""
        return [{'issue': ref.issue, 'page': ref.page} for ref in self.gazette]

    def bureau_column(self) -> dict:
        """articles.verified_bureau."""
        return {'legislation_id': self.bureau_id,
                'as_of': self.bureau_as_of.isoformat() if self.bureau_as_of else None}

    @classmethod
    def from_columns(cls, verified_at: date | None, gazette: object, bureau: object) -> 'Verification | None':
        """The verification stored in an article's row; None unless the date and both references are there (the ingest
        writes the three together or none, so anything else is not a verified article)."""
        if verified_at is None or not isinstance(gazette, list) or not gazette or not isinstance(bureau, dict):
            return None
        refs = tuple(GazetteRef(str(ref['issue']), ref.get('page')) for ref in gazette
                     if isinstance(ref, dict) and ref.get('issue') is not None)
        if not refs or not bureau.get('legislation_id'):
            return None
        as_of = bureau.get('as_of')
        return cls(verified_at, refs, str(bureau['legislation_id']), date.fromisoformat(as_of) if as_of else None)


def text_sha256(text: str) -> str:
    """The binding key of a record: sha256 of the UTF-8 of the article's stored text, exactly."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def records_dir(registry: Path) -> Path:
    """Where the records are: `verification/` beside the registry (/content/corpus/verification in the stack)."""
    return registry.parent / VERIFICATION_DIR


def _label(number: int, suffix: str) -> str:
    return f'المادة {number}' + (f' {suffix}' if suffix else '')


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _iso(value: object) -> date | None:
    """A YYYY-MM-DD string as a date; None for anything else."""
    if not (isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _token(value: object, field: str) -> str | None:
    """An issue, page or legislation id as the label prints it; None when the record leaves it out (null or "").
    Raises ValueError naming the field when it is there but is not a whole number or a _TOKEN string."""
    if value is None or value == '':
        return None
    text = str(value) if _is_int(value) else value.strip() if isinstance(value, str) else None
    if text is None or not _TOKEN.match(text):
        raise ValueError(f'{field} {value!r} is not a number or an ASCII reference such as 12-13')
    return text


def gazette_in_force(gazette: dict) -> tuple[GazetteRef, ...]:
    """The Gazette issues of the text in force: from the last amendment that replaced, added or repealed the article
    (else from the original law's issue) through every later amendment, oldest first. The amendments are taken in date
    order when each has a date, else in the order recorded. A reference without an issue is left out; an issue or page
    the label cannot print raises ValueError."""
    original = gazette.get('original') if isinstance(gazette.get('original'), dict) else None
    amendments = [a for a in (gazette.get('amendments') or []) if isinstance(a, dict)]
    dates = [_iso(a.get('date')) for a in amendments]
    if amendments and all(dates):
        amendments = [a for _, a in sorted(zip(dates, amendments), key=lambda pair: pair[0])]
    start = 0
    for index, amendment in enumerate(amendments, start=1):
        if amendment.get('effect') in _TEXT_STARTS:
            start = index
    chain = ([original] if original else [{}]) + amendments
    refs = []
    for entry in chain[start:]:
        issue = _token(entry.get('issue'), 'gazette issue')
        if issue is not None:
            refs.append(GazetteRef(issue, _token(entry.get('page'), 'gazette page')))
    return tuple(refs)


def verification_of(record: dict) -> Verification | str:
    """A verified record's references, or why the library cannot show them (the record then verifies nothing)."""
    checked_on = _iso(record.get('checked_on'))
    if checked_on is None:
        return 'checked_on is not a YYYY-MM-DD date'
    gazette, bureau = record.get('gazette'), record.get('bureau')
    try:
        refs = gazette_in_force(gazette) if isinstance(gazette, dict) else ()
        bureau_id = _token(bureau.get('legislation_id'), 'bureau legislation_id') if isinstance(bureau, dict) else None
    except ValueError as error:
        return str(error)
    if not refs:
        return 'a verified record names no Gazette issue of the text in force'
    if bureau_id is None:
        return 'a verified record names no Bureau legislation_id'
    as_of = bureau.get('as_of')
    if as_of is not None and _iso(as_of) is None:
        return 'bureau.as_of is not a YYYY-MM-DD date'
    return Verification(checked_on, refs, bureau_id, _iso(as_of))


@dataclass(frozen=True)
class Matched:
    verified: dict[Key, Verification]  # the articles to store as verified, by key
    # Every record that verifies nothing for another reason than its result; --check-verification fails on any.
    problems: list[str]
    files: int
    records: int
    results: dict[str, int]  # result -> records with it, as recorded (before the hash rule)


def match(articles: dict[str, list[Article]], directory: Path) -> Matched:
    """The verified articles among `articles` (law slug -> its articles as `ingest.prepare` returns them) by the records
    in `directory`, and the problems: a line that is not a record, a record of another law or of no parsed article, a
    second record for an article, a verified record whose text_sha256 is not the text's or whose references cannot be
    shown, and a law with a file but an article without a record."""
    verified: dict[Key, Verification] = {}
    problems: list[str] = []
    results = dict.fromkeys(RESULTS, 0)
    files = records = 0
    if not directory.is_dir():
        return Matched(verified, problems, files, records, results)
    for path in sorted(directory.glob('*.jsonl')):
        files += 1
        slug = path.stem
        name = f'{VERIFICATION_DIR}/{path.name}'
        if slug not in articles:
            problems.append(f'{name}: no law {slug!r} in the registry')
            continue
        texts = {(a.number, a.suffix): a.text for a in articles[slug]}
        seen: set[tuple[int, str]] = set()
        for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
            if not line.strip():
                continue
            where = f'{name}:{line_no}'
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                problems.append(f'{where}: not JSON ({error.msg})')
                continue
            if not isinstance(record, dict):
                problems.append(f'{where}: not a JSON object')
                continue
            records += 1
            number, suffix, result = record.get('number'), record.get('suffix'), record.get('result')
            if record.get('law_slug') != slug:
                problems.append(f'{where}: law_slug {record.get("law_slug")!r} in the file of {slug!r}')
                continue
            if not _is_int(number) or not isinstance(suffix, str):
                problems.append(f'{where}: number must be an int and suffix a string')
                continue
            if result not in RESULTS:
                problems.append(f'{where}: result {result!r} is not one of {", ".join(RESULTS)}')
                continue
            results[result] += 1
            key = (number, suffix)
            if key not in texts:
                problems.append(f'{where}: {slug} {_label(*key)} matches no parsed article')
                continue
            if key in seen:
                problems.append(f'{where}: a second record for {slug} {_label(*key)}')
                verified.pop((slug, *key), None)  # two records for one article: neither is applied
                continue
            seen.add(key)
            recorded = record.get('text_sha256')
            if not (isinstance(recorded, str) and _SHA256.match(recorded)):
                problems.append(f'{where}: text_sha256 is not a lowercase sha256 hex digest')
                continue
            if result != 'verified':
                continue
            if recorded != text_sha256(texts[key]):
                problems.append(f'{where}: {slug} {_label(*key)} is verified for text_sha256 {recorded[:12]}…, '
                                f'but its text is now {text_sha256(texts[key])[:12]}…: redo the record')
                continue
            shown = verification_of(record)
            if isinstance(shown, str):
                problems.append(f'{where}: {slug} {_label(*key)}: {shown}')
                continue
            verified[(slug, *key)] = shown
        missing = [_label(*key) for key in texts if key not in seen]
        if missing:
            problems.append(f'{name}: {len(missing)} article(s) of {slug} have no record: {", ".join(missing)}')
    return Matched(verified, problems, files, records, results)
