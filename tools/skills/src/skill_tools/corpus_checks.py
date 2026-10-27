"""Law registry and corrections checks (content/corpus/laws.json, corrections.json), run by corpus-ci.

Every check returns problems; an empty list passes. Rules: phase 3 spec A.1–A.3. A present value needs a
source URL; an absent value is fine (values are never guessed)."""

import re
from datetime import date
from pathlib import Path

from skill_tools.checks import Problem

SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
URL = re.compile(r'^https?://\S+$')
ISO_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
REVIEW_STATUSES = ('draft', 'approved')
TOP_FIELDS = {
    'slug': str, 'title': str, 'folder': str, 'number': int, 'year': int, 'gazette': dict,
    'amendment': dict, 'note': str, 'known_gaps': list, 'review': dict, 'sources': dict,
}
REQUIRED = ('slug', 'title', 'folder', 'review', 'sources')
GAZETTE_FIELDS = {'issue': int, 'date': str, 'source_url': str}
AMENDMENT_FIELDS = {'law': int, 'year': int, 'gazette_issue': int, 'gazette_date': str, 'source_url': str}
DATE_PATHS = ('gazette.date', 'amendment.gazette_date')
# Paths that need no entry in `sources`: identifiers, bookkeeping, and the source URLs themselves.
UNSOURCED = {'slug', 'folder', 'known_gaps', 'review', 'sources', 'gazette.source_url', 'amendment.source_url'}
CORRECTION_FIELDS = {'replace': ('text',), 'split': ('marker', 'second'), 'relabel': ('new_suffix',)}


def _is(value: object, kind: type) -> bool:
    if kind is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, kind)


def _url(value: object) -> bool:
    return _is(value, str) and bool(URL.match(value))


def _iso(value: object) -> bool:
    if not (_is(value, str) and ISO_DATE.match(value)):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _fields(values: dict, allowed: dict, prefix: str, name: str) -> list[Problem]:
    problems = []
    for key, value in values.items():
        if key not in allowed:
            problems.append(Problem(name, 'schema', f'unknown field {prefix}{key}'))
        elif not _is(value, allowed[key]):
            problems.append(Problem(name, 'schema', f'{prefix}{key} must be {allowed[key].__name__}'))
    return problems


def present_paths(entry: dict) -> dict[str, object]:
    """Every value present in an entry, keyed by its field path (e.g. `gazette.issue`)."""
    paths: dict[str, object] = {}
    for key, value in entry.items():
        if key in ('gazette', 'amendment') and _is(value, dict):
            paths.update({f'{key}.{sub}': subvalue for sub, subvalue in value.items()})
        else:
            paths[key] = value
    return paths


def check_review_shape(review: object, name: str) -> list[Problem]:
    if not _is(review, dict) or review.get('status') not in REVIEW_STATUSES:
        return [Problem(name, 'schema', 'review.status must be draft or approved')]
    if review['status'] == 'approved' and not (review.get('approved_by') and review.get('approved_on')):
        return [Problem(name, 'schema', 'an approved review needs approved_by and approved_on')]
    return []


def check_schema(entry: dict, name: str) -> list[Problem]:
    problems = [Problem(name, 'schema', f'missing required field {key}') for key in REQUIRED if key not in entry]
    problems += _fields(entry, TOP_FIELDS, '', name)
    if _is(entry.get('slug'), str) and not SLUG.match(entry['slug']):
        problems.append(Problem(name, 'schema', 'slug must be lowercase latin words joined by hyphens'))
    for key in ('title', 'folder', 'note'):
        if _is(entry.get(key), str) and not entry[key].strip():
            problems.append(Problem(name, 'schema', f'{key} must not be empty'))
    if _is(entry.get('gazette'), dict):
        problems += _fields(entry['gazette'], GAZETTE_FIELDS, 'gazette.', name)
    if _is(entry.get('amendment'), dict):
        problems += _fields(entry['amendment'], AMENDMENT_FIELDS, 'amendment.', name)
    for gap in entry['known_gaps'] if _is(entry.get('known_gaps'), list) else []:
        valid = (_is(gap, dict) and _is(gap.get('number'), int) and _is(gap.get('suffix', ''), str)
                 and _is(gap.get('reason'), str) and gap['reason'].strip())
        if not valid:
            problems.append(Problem(name, 'schema', 'each known gap needs number (int), reason (text) and an optional suffix'))
    if 'review' in entry:
        problems += check_review_shape(entry['review'], name)
    return problems


def check_dates(entry: dict, name: str) -> list[Problem]:
    paths = present_paths(entry)
    problems = [Problem(name, 'date', f'{path} must be an ISO date (YYYY-MM-DD)')
                for path in DATE_PATHS if path in paths and not _iso(paths[path])]
    review = entry.get('review')
    if _is(review, dict) and 'approved_on' in review and not _iso(review['approved_on']):
        problems.append(Problem(name, 'date', 'review.approved_on must be an ISO date (YYYY-MM-DD)'))
    return problems


def check_sources(entry: dict, name: str) -> list[Problem]:
    sources = entry['sources'] if _is(entry.get('sources'), dict) else {}
    paths = present_paths(entry)
    problems = [Problem(name, 'source', f'{path} has no source URL in sources')
                for path in sorted(paths) if path not in UNSOURCED and not _url(sources.get(path))]
    problems += [Problem(name, 'source', f'sources names {path}, which has no value')
                 for path in sorted(sources) if path not in paths]
    problems += [Problem(name, 'source', f'{path} is not an http(s) URL')
                 for path in ('gazette.source_url', 'amendment.source_url') if path in paths and not _url(paths[path])]
    return problems


def check_unique_slugs(entries: list[dict]) -> list[Problem]:
    seen: set[str] = set()
    problems = []
    for entry in entries:
        slug = entry.get('slug')
        if not _is(slug, str):
            continue
        if slug in seen:
            problems.append(Problem(slug, 'slug', 'slug is used by more than one entry'))
        seen.add(slug)
    return problems


def check_folders(entries: list[dict], corpus: Path) -> list[Problem]:
    return [Problem(str(entry.get('slug')), 'folder', f'folder not found in the corpus: {entry["folder"]}/sections')
            for entry in entries
            if _is(entry.get('folder'), str) and not (corpus / entry['folder'] / 'sections').is_dir()]


def check_approved(review: object, name: str) -> list[Problem]:
    if _is(review, dict) and review.get('status') == 'approved' and review.get('approved_by') and review.get('approved_on'):
        return []
    return [Problem(name, 'review', 'release needs review.status approved, approved_by and approved_on')]


def check_corrections(document: object, slugs: set[str]) -> list[Problem]:
    if not (_is(document, dict) and _is(document.get('corrections'), list)):
        return [Problem('corrections.json', 'schema', 'top level must be {"review": {...}, "corrections": [...]}')]
    problems = check_review_shape(document.get('review'), 'corrections.json')
    for index, item in enumerate(document['corrections']):
        name = f'corrections[{index}]'
        if not _is(item, dict) or item.get('type') not in CORRECTION_FIELDS:
            problems.append(Problem(name, 'schema', f'type must be one of {", ".join(CORRECTION_FIELDS)}'))
            continue
        problems += [Problem(name, 'schema', f'{item["type"]} correction is missing {key}')
                     for key in ('law', 'number', 'reason', 'source', *CORRECTION_FIELDS[item['type']]) if key not in item]
        if 'law' in item and item['law'] not in slugs:
            problems.append(Problem(name, 'schema', f'law {item["law"]!r} is not in the registry'))
        if 'number' in item and not _is(item['number'], int):
            problems.append(Problem(name, 'schema', 'number must be int'))
        if 'reason' in item and not (_is(item['reason'], str) and item['reason'].strip()):
            problems.append(Problem(name, 'schema', 'reason must not be empty'))
        if 'source' in item and not _url(item['source']):
            problems.append(Problem(name, 'source', 'source must be an http(s) URL'))
    return problems + check_memorandum_corrections(document.get('memorandum', []))


def _ascending_ints(values: object) -> bool:
    return (_is(values, list) and bool(values) and all(_is(value, int) for value in values)
            and all(a < b for a, b in zip(values, values[1:])))


def check_memorandum_corrections(entries: object) -> list[Problem]:
    """The corrections file's `memorandum` list: the Civil Code articles a memorandum note explains where its
    heading is missing or wrong. legal_search.memorandum.load_memorandum_corrections applies the same rules."""
    if not _is(entries, list):
        return [Problem('corrections.json', 'schema', 'memorandum must be a list')]
    problems: list[Problem] = []
    seen: set[int] = set()
    for index, item in enumerate(entries):
        name = f'memorandum[{index}]'
        if not _is(item, dict):
            problems.append(Problem(name, 'schema', 'each memorandum correction must be an object'))
            continue
        note = item.get('note')
        if not (_is(note, int) and note >= 1):
            problems.append(Problem(name, 'schema', 'note must be an int >= 1'))
        elif note in seen:
            problems.append(Problem(name, 'schema', f'note {note} is corrected more than once'))
        else:
            seen.add(note)
        if not _ascending_ints(item.get('articles')):
            problems.append(Problem(name, 'schema', 'articles must be a non-empty list of ints in strictly ascending order'))
        for key in ('reason', 'evidence'):
            if not (_is(item.get(key), str) and item[key].strip()):
                problems.append(Problem(name, 'schema', f'{key} must not be empty'))
    return problems


def check_all(registry: object, corrections: object, corpus: Path, release: bool) -> list[Problem]:
    entries = registry.get('laws') if _is(registry, dict) else None
    if not _is(entries, list):
        return [Problem('laws.json', 'schema', 'top level must be {"laws": [...]}')]
    problems: list[Problem] = []
    valid = []
    for index, entry in enumerate(entries):
        if not _is(entry, dict):
            problems.append(Problem(f'laws[{index}]', 'schema', 'each entry must be an object'))
            continue
        valid.append(entry)
        name = entry['slug'] if _is(entry.get('slug'), str) else f'laws[{index}]'
        problems += check_schema(entry, name) + check_dates(entry, name) + check_sources(entry, name)
        if release:
            problems += check_approved(entry.get('review'), name)
    problems += check_unique_slugs(valid) + check_folders(valid, corpus)
    problems += check_corrections(corrections, {e['slug'] for e in valid if _is(e.get('slug'), str)})
    if release:
        problems += check_approved(corrections.get('review') if _is(corrections, dict) else None, 'corrections.json')
    return problems
