"""Law registry, corrections and verification-record checks (content/corpus/laws.json, corrections.json,
verification/<law-slug>.jsonl), run by corpus-ci.

Every check returns problems; an empty list passes. Rules: phase 3 spec A.1–A.3. A present value needs a
source URL; an absent value is fine (values are never guessed)."""

import json
import re
from collections import Counter
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


# Verification records: content/corpus/verification/<law-slug>.jsonl, one line per corpus article (the record format
# of content/corpus/verification/README.md). Schema only. Whether a record still matches its article's stored text
# (`text_sha256`) is checked where the parser lives: legal-search's `--check-verification` on recall-plan. A law
# without a file is simply unverified.
SHA256 = re.compile(r'^[0-9a-f]{64}$')
RESULTS = ('verified', 'differs', 'unverifiable')
REASONS = ('gazette_offline', 'gazette_image_unread', 'bureau_unreachable', 'no_official_source', 'sources_disagree')
DIFFERS_FROM = ('gazette', 'bureau', 'both')
DIFFERENCES = ('formatting', 'trailing-title', 'body', 'repeal')
METHODS = ('text', 'image')
EFFECTS = ('amended', 'replaced', 'added', 'repealed', 'renumbered')
NORMALISATIONS = ('v1',)
# (kind, nullable). A kind is a named value type, a tuple of allowed values, a nested object, or [item kind].
_REFERENCE = {'issue': ('id', True), 'date': ('date', True), 'page': ('id', True), 'document_id': ('id', True),
              'url': ('url', True), 'file_sha256': ('sha256', True)}
_AMENDMENT = {'law': ('int', True), 'year': ('int', True), **_REFERENCE, 'effect': (EFFECTS, False)}
_GAZETTE = {'method': (METHODS, True), 'original': (_REFERENCE, True), 'amendments': ([_AMENDMENT], False),
            'text_sha256': ('sha256', True), 'checked_on': ('date', True)}
_BUREAU = {'legislation_id': ('id', True), 'url': ('url', True), 'as_of': ('date', True),
           'text_sha256': ('sha256', True), 'checked_on': ('date', True)}
RECORD = {
    'law_slug': ('str', False), 'number': ('int', False), 'suffix': ('str', False), 'text_sha256': ('sha256', False),
    'norm_sha256': ('sha256', True), 'result': (RESULTS, False), 'reason': (REASONS, True),
    'differs_from': (DIFFERS_FROM, True), 'difference': (DIFFERENCES, True), 'checked_on': ('date', False),
    'normalisation': (NORMALISATIONS, False), 'gazette': (_GAZETTE, True), 'bureau': (_BUREAU, True),
    'notes': ('str', True), 'lawyer_item': ('str', True),
}
OPTIONAL_RECORD_KEYS = {'norm_sha256'}
_KINDS = {
    'int': (lambda v: _is(v, int), 'an int'),
    'str': (lambda v: _is(v, str), 'a string'),
    'id': (lambda v: _is(v, int) or (_is(v, str) and bool(v.strip())), 'an int or a non-empty string'),
    'sha256': (lambda v: _is(v, str) and bool(SHA256.match(v)), 'a sha256 (64 lowercase hex digits)'),
    'date': (lambda v: _iso(v), 'an ISO date (YYYY-MM-DD)'),
    'url': (lambda v: _url(v), 'an http(s) URL'),
}
MAX_PROBLEMS_PER_FILE = 20
# `### المادة N`, optionally «مكرر» and one more word, optionally a dash and inline text: the article headings of a
# law's sections/*.md. Read here for article keys only; the article text and its hash belong to legal-search's parser.
_HEADING = re.compile(r'^\s*###\s+المادة\s+([0-9٠-٩]+)(.*)$')
_ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


def _key_label(number: object, suffix: object) -> str:
    return f'المادة {number}' + (f' {suffix}' if suffix else '')


def _value_problems(value: object, kind: object, nullable: bool, path: str) -> list[tuple[str, str]]:
    if value is None:
        return [] if nullable else [('schema', f'{path} must not be null')]
    if isinstance(kind, dict):
        if not _is(value, dict):
            return [('schema', f'{path} must be an object')]
        return _object_problems(value, kind, f'{path}.')
    if isinstance(kind, list):
        if not _is(value, list):
            return [('schema', f'{path} must be a list')]
        return [problem for index, item in enumerate(value)
                for problem in _value_problems(item, kind[0], False, f'{path}[{index}]')]
    if isinstance(kind, tuple):
        return [] if _is(value, str) and value in kind else [('schema', f'{path} must be one of {", ".join(kind)}')]
    accepts, description = _KINDS[kind]
    return [] if accepts(value) else [('date' if kind == 'date' else 'schema', f'{path} must be {description}')]


def _object_problems(value: dict, spec: dict, prefix: str, optional: frozenset | set = frozenset()) -> list[tuple[str, str]]:
    problems = [('schema', f'unknown field {prefix}{key}') for key in value if key not in spec]
    for key, (kind, nullable) in spec.items():
        if key in value:
            problems += _value_problems(value[key], kind, nullable, f'{prefix}{key}')
        elif key not in optional:
            problems.append(('schema', f'missing field {prefix}{key}'))
    return problems


def _filled_reference(reference: object, method: object) -> bool:
    return (_is(reference, dict) and all(reference.get(key) is not None for key in ('issue', 'date', 'page'))
            and (reference.get('document_id') is not None or reference.get('url') is not None)
            and (method != 'image' or reference.get('file_sha256') is not None))


def _result_problems(record: dict) -> list[str]:
    """What a record's result requires of its other fields (run on a record whose schema passed)."""
    result = record['result']
    if result == 'differs':
        return [f'a differs record needs {key}' for key in ('differs_from', 'difference') if record[key] is None]
    if result == 'unverifiable':
        return [] if record['reason'] is not None else ['an unverifiable record needs a reason']
    problems = [f'a verified record must have {key} null' for key in ('reason', 'differs_from', 'difference')
                if record[key] is not None]
    gazette, bureau = record['gazette'], record['bureau']
    if gazette is None:
        problems.append('a verified record needs the gazette block')
    else:
        problems += [f'a verified record needs gazette.{key}' for key in ('method', 'text_sha256', 'checked_on')
                     if gazette[key] is None]
        references = [gazette['original'], *gazette['amendments']]
        if not any(_filled_reference(reference, gazette['method']) for reference in references):
            problems.append('a verified record needs a Gazette reference (gazette.original or an amendment) with issue, '
                            'date, page and document_id or url' + (', and file_sha256 (method image)'
                                                                  if gazette['method'] == 'image' else ''))
    if bureau is None:
        problems.append('a verified record needs the bureau block')
    else:
        problems += [f'a verified record needs bureau.{key}' for key in _BUREAU if bureau[key] is None]
    return problems


def check_verification_record(record: object, slug: str) -> list[tuple[str, str]]:
    """(rule, message) for each problem of one record of verification/<slug>.jsonl."""
    if not _is(record, dict):
        return [('schema', 'each line must be a JSON object')]
    problems = _object_problems(record, RECORD, '', OPTIONAL_RECORD_KEYS)
    if _is(record.get('law_slug'), str) and record['law_slug'] != slug:
        problems.append(('schema', f'law_slug {record["law_slug"]!r} is not the file\'s law {slug!r}'))
    if not problems:
        problems += [('schema', message) for message in _result_problems(record)]
    return problems


def heading_keys(law_folder: Path) -> list[tuple[int, str]]:
    """(number, suffix) of every article heading in a law's sections/*.md, in file order: «### المادة N», with the
    suffix «مكرر» plus at most one more word before any dash. Keys only; this reads no article text."""
    keys = []
    for shard in sorted((law_folder / 'sections').glob('*.md')):
        for line in shard.read_text(encoding='utf-8').replace('\r\n', '\n').split('\n'):
            heading = _HEADING.match(line)
            if not heading:
                continue
            words = re.split('[—–-]', heading.group(2), maxsplit=1)[0].split()
            suffix = ' '.join(words[:2]) if words and words[0] == 'مكرر' else ''
            keys.append((int(heading.group(1).translate(_ARABIC_DIGITS)), suffix))
    return keys


def article_keys(entry: dict, corrections: object, corpus: Path) -> list[tuple[int, str]]:
    """The law's article keys as corpus-ci can know them without the parser: the headings, with the corrections that
    change a key (relabel, split) applied and the registry's known gaps (headings with no text) removed."""
    keys = heading_keys(corpus / entry['folder'])
    items = corrections.get('corrections') if _is(corrections, dict) else None
    for item in items if _is(items, list) else []:
        if not (_is(item, dict) and item.get('law') == entry['slug'] and item.get('type') in ('relabel', 'split')):
            continue
        target = (item.get('number'), item.get('suffix', ''))
        matches = [index for index, key in enumerate(keys) if key == target]
        occurrence = item.get('occurrence', 1)
        if not (_is(occurrence, int) and 1 <= occurrence <= len(matches)):
            continue  # the ingest fails on a correction that matches nothing; the key list is left as it is
        index = matches[occurrence - 1]
        if item['type'] == 'relabel' and _is(item.get('new_suffix'), str):
            keys[index] = (target[0], item['new_suffix'])
        elif item['type'] == 'split' and _is(item.get('second'), dict) and _is(item['second'].get('number'), int):
            keys.insert(index + 1, (item['second']['number'], item['second'].get('suffix', '')))
    gaps = {(gap.get('number'), gap.get('suffix', '')) for gap in entry.get('known_gaps') or [] if _is(gap, dict)}
    return [key for key in keys if key not in gaps]


def _read_records(path: Path, name: str) -> tuple[list[tuple[int, object]], list[Problem]]:
    try:
        text = path.read_bytes().decode('utf-8')
    except UnicodeDecodeError:
        return [], [Problem(name, 'schema', 'not UTF-8')]
    records, problems = [], []
    for line_number, line in enumerate(text.split('\n'), 1):
        if not line.strip():
            if line_number < text.count('\n') + 1:
                problems.append(Problem(f'{name}:{line_number}', 'schema', 'blank line'))
            continue
        try:
            records.append((line_number, json.loads(line)))
        except json.JSONDecodeError as error:
            problems.append(Problem(f'{name}:{line_number}', 'schema', f'not JSON: {error.msg}'))
    return records, problems


def _article_problems(name: str, records: list[tuple[int, object]], expected: list[tuple[int, str]]) -> list[Problem]:
    known = set(expected)
    problems = []
    seen: Counter = Counter()
    for line_number, record in records:
        if not (_is(record, dict) and _is(record.get('number'), int) and _is(record.get('suffix'), str)):
            continue
        key = (record['number'], record['suffix'])
        seen[key] += 1
        if key not in known:
            problems.append(Problem(f'{name}:{line_number}', 'articles',
                                    f'{_key_label(*key)} is not an article of this law in the corpus'))
        elif seen[key] == 2:
            problems.append(Problem(f'{name}:{line_number}', 'articles', f'{_key_label(*key)} has more than one record'))
    missing = [key for key in expected if key not in seen]
    if missing:
        listed = ', '.join(_key_label(*key) for key in missing[:5]) + (' …' if len(missing) > 5 else '')
        problems.append(Problem(name, 'articles', f'{len(missing)} corpus article(s) have no record: {listed}'))
    return problems


def check_verification(directory: Path, registry: object, corrections: object, corpus: Path) -> list[Problem]:
    """Every verification/<law-slug>.jsonl: a registry law, one valid record per corpus article and none for an
    article that does not exist. A missing directory or a law without a file passes (unverified)."""
    if not directory.is_dir():
        return []
    entries = registry.get('laws') if _is(registry, dict) else None
    laws = {entry['slug']: entry for entry in entries if _is(entry, dict) and _is(entry.get('slug'), str)
            and _is(entry.get('folder'), str)} if _is(entries, list) else {}
    problems: list[Problem] = []
    for path in sorted(directory.glob('*.jsonl')):
        slug, name = path.stem, f'verification/{path.name}'
        if slug not in laws:
            problems.append(Problem(name, 'schema', f'{slug!r} is not a law in the registry'))
            continue
        records, file_problems = _read_records(path, name)
        for line_number, record in records:
            file_problems += [Problem(f'{name}:{line_number}', rule, message)
                              for rule, message in check_verification_record(record, slug)]
        if (corpus / laws[slug]['folder'] / 'sections').is_dir():
            file_problems += _article_problems(name, records, article_keys(laws[slug], corrections, corpus))
        if len(file_problems) > MAX_PROBLEMS_PER_FILE:
            more = len(file_problems) - MAX_PROBLEMS_PER_FILE
            file_problems = file_problems[:MAX_PROBLEMS_PER_FILE] + [Problem(name, 'schema', f'{more} more problem(s) not shown')]
        problems += file_problems
    return problems
