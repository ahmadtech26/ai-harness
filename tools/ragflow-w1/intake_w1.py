#!/usr/bin/env python3
"""Put Walid's returned W1 results file into quarantine, with a manifest.

    python -I intake_w1.py --file <returned file> --handover-id <slug> --client-data-declared no [--rights TEXT]
    python -I intake_w1.py --record-screening --handover-id <slug> --screened-by NAME --outcome clear|flagged

The first form checks the file against the W1 contract (README, «The shared contract»), refuses a file that
looks like it holds a key or a server address, copies it to
.hq/quarantine/ragflow-export/<handover-id>/w1-results.jsonl and writes manifest.json beside it
(.hq/docs/specs/spec-rag-system.md, «The safe path for imported data», step 3). The second form records the
person's screen (step 4); score_w1.py scores only a file whose screen is recorded as clear.

It prints counts, line numbers and key names only, never text from the file (REQ-RAG-047: the chunks are his
data, kept for scoring only). Exit codes: 0 done, 2 refused (nothing written). Python standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

TOOL = Path(__file__).resolve().parent
DEFAULT_ROOT = TOOL.parents[2] / '.hq' / 'quarantine' / 'ragflow-export'  # <workspace>/AI Harness*/tools/ragflow-w1
DEFAULT_PACKAGE = TOOL.parents[2] / '.hq' / 'docs' / 'specs' / 'w1-for-walid'  # what make_package.py wrote and we sent
STORED_NAME = 'w1-results.jsonl'
MANIFEST = 'manifest.json'
DECLARED_TYPE = 'W1 evaluation evidence'
USE = ('REQ-RAG-047: used only for scoring; stays in quarantine; never ingested; deleted when the agreement says')

# The contract. Every key outside these sets is refused, so a dataset name or a server address cannot ride along.
FIELDS = ('query', 'question')
HEADER_KEYS = frozenset({'w1', 'script_sha256', 'queries_sha256', 'started_at', 'finished_at', 'ragflow_version',
                         'ragflow_version_note', 'datasets', 'settings', 'fields', 'counts'})
HEADER_REQUIRED = HEADER_KEYS - {'ragflow_version_note'}
DATASET_KEYS = frozenset({'id', 'document_count', 'chunk_count', 'embedding_model', 'chunk_method', 'parser_config'})
LINE_KEYS = frozenset({'id', 'field', 'sent', 'status', 'error', 'chunks'})
LINE_REQUIRED = LINE_KEYS - {'error'}
CHUNK_KEYS = frozenset({'rank', 'content', 'document_name', 'document_id', 'chunk_id', 'similarity',
                        'vector_similarity', 'term_similarity'})
COUNTS_KEYS = frozenset({'items', 'planned', 'ok', 'error', 'not_run'})  # run_w1.py main(), header['counts']
# run_w1.py retrieval_settings(): every name it sends. A test checks that this set holds them all.
SETTING_KEYS = frozenset({'page', 'page_size', 'similarity_threshold', 'vector_similarity_weight', 'top_k',
                          'rerank_candidates_count', 'keyword', 'use_kg', 'toc_enhance', 'cross_languages',
                          'highlight', 'rerank_id'})
SETTING_FLAGS = frozenset({'keyword', 'use_kg', 'toc_enhance', 'highlight'})
ITEM_ID = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9]{2}$')  # the eval set's id rule (legal_search/evalset.py:35)
SHA256 = re.compile(r'^[0-9a-f]{64}$')
SLUG = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$')
SAFE_NAME = re.compile(r'^[A-Za-z0-9_.-]{1,64}$')
WINDOWS_DEVICES = frozenset({'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(10)), *(f'lpt{i}' for i in range(10))})

MAX_FILE_BYTES = 512 << 20
MAX_LINE_BYTES = 4 << 20
MAX_CHUNKS = 1000
MAX_ERROR_CHARS = 500
MAX_LINES = 2 * 1000 + 1

# Refused anywhere in the file. A RAGFlow key is "ragflow-" + secrets.token_urlsafe(32)
# (ragflow-src-v0.27.3 api/utils/api_utils.py:348-351).
SECRET_PATTERNS = (
    ('a RAGFlow API key', re.compile(r'ragflow-[A-Za-z0-9_-]{20,}')),
    ('a Bearer token', re.compile(r'(?i)\bbearer\s+(?!\[REDACTED\])\S{8,}')),  # run_w1.py redacts to that
    ('an Authorization header', re.compile(r'(?i)\bauthori[sz]ation\b')),
)
URL_PATTERNS = (
    ('a URL', re.compile(r'(?i)\b(?:https?|wss?|ftp)://')),
    ('a localhost address', re.compile(r'(?i)\blocalhost\b')),
)
# Refused outside chunk text (header, ids, names, errors): law text has no reason to hold these either, but chunk
# text is not searched for them, to avoid refusing a statute that numbers clauses like 1.2.3.4.
IPV4 = re.compile(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])')
# IPv6: a bracketed address ([fe80::1]), one with «::» (fe80::1, ::1), or all eight groups. A time such as
# 08:00:00+00:00 has neither «::» nor eight groups, so the header's times pass.
_HEX = r'[0-9A-Fa-f]{1,4}'
IPV6 = re.compile(r'\[[0-9A-Fa-f.:]*:[0-9A-Fa-f.:]*\]'
                  rf'|(?<![0-9A-Za-z:])(?:{_HEX}(?::{_HEX})*::(?:{_HEX}(?::{_HEX})*)?|::{_HEX}(?::{_HEX})*'
                  rf'|(?:{_HEX}:){{7}}{_HEX})(?![0-9A-Za-z:])')
# A long random-looking token (a key without its prefix): 32+ characters of [A-Za-z0-9_-] with an upper-case
# letter, a lower-case letter and a digit. Not applied to document names or chunk text, which can look like that:
# Walid's criminal-procedure file holds «source_review_file: 'IQRA_LAW_Criminal_Procedure_Articles_1-370_REVIEW.md'».
# In those two places it is counted for the screen instead (long_mixed_token below).
LONG_TOKEN = re.compile(r'(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])')

# Pattern counts for the person who screens the file (safe path step 4). Counted, never refused, never printed.
_ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
CLIENT_FACT_PATTERNS = (
    ('national_id_shape', re.compile(r'(?<!\d)\d{10}(?!\d)')),
    ('phone_number', re.compile(r'(?<!\d)(?:\+?962|0)7[789]\d{7}(?!\d)')),
    ('case_number', re.compile(r'(?<!\d)\d{1,6}\s*/\s*(?:19|20)\d{2}(?!\d)')),
    ('word_almuddai', re.compile('المدعي')),  # «المدعي»
    ('word_almuwakkil', re.compile('الموكل')),  # «الموكل»
    ('word_muwakkili', re.compile('موكلي')),  # «موكلي»
    ('long_mixed_token', re.compile(r'(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*[A-Z])(?=[A-Za-z0-9_-]*[a-z])'
                                    r'(?=[A-Za-z0-9_-]*[0-9])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])')),  # as LONG_TOKEN
)


class Refused(Exception):
    """The file or the request was refused; nothing was written. The message holds no text from the file."""


@dataclass
class Results:
    header: dict
    lines: list[dict]
    line_numbers: list[int]
    warnings: list[str] = field(default_factory=list)


def _key_name(key: object) -> str:
    return key if isinstance(key, str) and re.fullmatch(r'[a-z_]{1,40}', key) else '<a key not shown>'


def _keys(where: str, value: dict, allowed: frozenset, required: frozenset) -> None:
    extra = sorted(_key_name(key) for key in value if key not in allowed)
    if extra:
        raise Refused(f'{where}: keys outside the contract: {", ".join(extra)}')
    missing = sorted(required - set(value))
    if missing:
        raise Refused(f'{where}: missing keys: {", ".join(missing)}')


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _number_or_null(value: object) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def _strings(value: object, path: str = ''):
    """Every string in a JSON value, keys included, with a path of key names (no values)."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield f'{path}.{_key_name(key)}', str(key)
            yield from _strings(item, f'{path}.{_key_name(key)}')
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item, f'{path}[]')


def _screen_strings(where: str, value: object, chunk_text: bool) -> None:
    for path, text in _strings(value):
        is_content = chunk_text and path.endswith('.content')
        is_name = chunk_text and path.endswith('.document_name')
        for label, pattern in SECRET_PATTERNS + URL_PATTERNS:
            if pattern.search(text):
                raise Refused(f'{where}{path}: looks like it holds {label}; ask for a file without it')
        if not is_content and (IPV4.search(text) or IPV6.search(text)):
            raise Refused(f'{where}{path}: looks like it holds an IP address; ask for a file without it')
        if not (is_name or is_content) and any(re.search('[A-Z]', t) and re.search('[a-z]', t) and re.search('[0-9]', t)
                               for t in LONG_TOKEN.findall(text)):
            raise Refused(f'{where}{path}: holds a long random-looking token (a possible key); ask for a file without it')


def _check_header(header: dict) -> None:
    _keys('line 1 (header)', header, HEADER_KEYS, HEADER_REQUIRED)
    if header['w1'] != 1:
        raise Refused('line 1 (header): "w1" must be 1')
    for name in ('script_sha256', 'queries_sha256'):
        if not isinstance(header[name], str) or not SHA256.match(header[name]):
            raise Refused(f'line 1 (header): "{name}" must be 64 lower-case hex characters')
    if header['finished_at'] is None:
        raise Refused('line 1 (header): "finished_at" is null, so the run did not finish; ask for a complete run')
    for name in ('started_at', 'finished_at'):
        if not isinstance(header[name], str) or not re.match(r'^\d{4}-\d{2}-\d{2}T', header[name]):
            raise Refused(f'line 1 (header): "{name}" must be an ISO-8601 time')
    version = header['ragflow_version']
    if version is None:
        if not isinstance(header.get('ragflow_version_note'), str) or not header['ragflow_version_note'].strip():
            raise Refused('line 1 (header): "ragflow_version" is null, so "ragflow_version_note" must say why')
    elif not isinstance(version, str):
        raise Refused('line 1 (header): "ragflow_version" must be a string or null')
    fields = header['fields']
    if (not isinstance(fields, list) or not fields or len(set(map(str, fields))) != len(fields)
            or any(name not in FIELDS for name in fields)):
        raise Refused('line 1 (header): "fields" must list "query" and/or "question", each once')
    if not isinstance(header['datasets'], list) or not header['datasets']:
        raise Refused('line 1 (header): "datasets" must be a non-empty list')
    for number, dataset in enumerate(header['datasets'], 1):
        if not isinstance(dataset, dict):
            raise Refused(f'line 1 (header): datasets[{number}] must be an object')
        _keys(f'line 1 (header): datasets[{number}]', dataset, DATASET_KEYS, DATASET_KEYS)
        if not isinstance(dataset['id'], str) or not dataset['id']:
            raise Refused(f'line 1 (header): datasets[{number}].id must be a string')
    for name in ('settings', 'counts'):
        if not isinstance(header[name], dict):
            raise Refused(f'line 1 (header): "{name}" must be an object')
    # Only run_w1.py's names and value types, so no free text rides along in a key or a value.
    _keys('line 1 (header): counts', header['counts'], COUNTS_KEYS, COUNTS_KEYS)
    if not all(_count(value) for value in header['counts'].values()):
        raise Refused('line 1 (header): every "counts" value must be a whole number, 0 or more')
    _keys('line 1 (header): settings', header['settings'], SETTING_KEYS, frozenset())
    for name, value in header['settings'].items():
        if name == 'rerank_id':
            ok = isinstance(value, str)
        elif name == 'cross_languages':
            ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
        elif name in SETTING_FLAGS:
            ok = isinstance(value, bool)
        else:
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not ok:
            raise Refused(f'line 1 (header): settings.{name} has a value of the wrong type')


def _check_line(number: int, line: dict, fields: list) -> None:
    where = f'line {number}'
    _keys(where, line, LINE_KEYS, LINE_REQUIRED)
    if not isinstance(line['id'], str) or not ITEM_ID.match(line['id']):
        raise Refused(f'{where}: "id" is not an eval-set id')
    if line['field'] not in fields:
        raise Refused(f'{where}: "field" must be one of the header\'s fields')
    if not isinstance(line['sent'], str):
        raise Refused(f'{where}: "sent" must be a string')
    status, error, chunks = line['status'], line.get('error'), line['chunks']
    if status not in ('ok', 'error'):
        raise Refused(f'{where}: "status" must be "ok" or "error"')
    if status == 'ok' and error is not None:
        raise Refused(f'{where}: an "ok" line must not carry an error')
    if status == 'error' and (not isinstance(error, str) or len(error) > MAX_ERROR_CHARS):
        raise Refused(f'{where}: an "error" line needs a short "error" string (at most {MAX_ERROR_CHARS} characters)')
    if not isinstance(chunks, list) or len(chunks) > MAX_CHUNKS:
        raise Refused(f'{where}: "chunks" must be a list of at most {MAX_CHUNKS}')
    if status == 'error' and chunks:
        raise Refused(f'{where}: an "error" line must have no chunks')
    for expected_rank, chunk in enumerate(chunks, 1):
        if not isinstance(chunk, dict):
            raise Refused(f'{where}: chunk {expected_rank} must be an object')
        _keys(f'{where}: chunk {expected_rank}', chunk, CHUNK_KEYS, CHUNK_KEYS)
        if not _count(chunk['rank']) or chunk['rank'] != expected_rank:
            raise Refused(f'{where}: chunk ranks must be 1, 2, 3 ... in order (chunk {expected_rank})')
        if chunk['content'] is not None and not isinstance(chunk['content'], str):
            raise Refused(f'{where}: chunk {expected_rank}: "content" must be a string or null')
        for name in ('document_name', 'document_id', 'chunk_id'):
            if chunk[name] is not None and not isinstance(chunk[name], str):
                raise Refused(f'{where}: chunk {expected_rank}: "{name}" must be a string or null')
        for name in ('similarity', 'vector_similarity', 'term_similarity'):
            if not _number_or_null(chunk[name]):
                raise Refused(f'{where}: chunk {expected_rank}: "{name}" must be a number or null')


def read_results(path: Path) -> Results:
    """The file checked against the contract; raises Refused naming the line and key, never quoting the file."""
    path = Path(path)
    if not path.is_file():
        raise Refused(f'not a file: {path}')
    size = path.stat().st_size
    if size == 0 or size > MAX_FILE_BYTES:
        raise Refused(f'the file must hold 1 byte to {MAX_FILE_BYTES >> 20} MiB; it holds {size} bytes')
    data = path.read_bytes()
    warnings = []
    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]
        warnings.append('the file starts with a UTF-8 byte-order mark (an editor may have saved it)')
    if b'\r\n' in data:
        warnings.append('the file has CRLF line ends (an editor or a mail client may have changed it)')
    raw_lines = data.split(b'\n')
    if len(raw_lines) > MAX_LINES + 1:
        raise Refused(f'the file has more than {MAX_LINES} lines')
    parsed: list[tuple[int, dict]] = []
    for number, raw in enumerate(raw_lines, 1):
        if len(raw) > MAX_LINE_BYTES:
            raise Refused(f'line {number} is longer than {MAX_LINE_BYTES >> 20} MiB')
        raw = raw.rstrip(b'\r')
        if not raw.strip():
            continue
        try:
            value = json.loads(raw.decode('utf-8'))
        except UnicodeDecodeError:
            raise Refused(f'line {number} is not UTF-8') from None
        except ValueError:
            raise Refused(f'line {number} is not JSON') from None
        if not isinstance(value, dict):
            raise Refused(f'line {number} must be a JSON object')
        parsed.append((number, value))
    if not parsed or 'w1' not in parsed[0][1]:
        raise Refused('the header (an object with "w1") must be the first line')
    header_number, header = parsed[0]
    if header_number != 1:
        raise Refused('the header must be on line 1, with no blank line before it')
    _check_header(header)
    _screen_strings('line 1 (header)', header, chunk_text=False)
    seen = set()
    for number, line in parsed[1:]:
        _check_line(number, line, header['fields'])
        _screen_strings(f'line {number}', line, chunk_text=True)
        pair = (line['field'], line['id'])
        if pair in seen:
            raise Refused(f'line {number}: a second line for the same field and id')
        seen.add(pair)
    return Results(header, [line for _, line in parsed[1:]], [number for number, _ in parsed[1:]], warnings)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


PATTERN_PLACES = ('content', 'document_name', 'error', 'header', 'other')


def _place(path: str) -> str:
    for place in ('content', 'document_name', 'error'):
        if path.endswith('.' + place):
            return place
    return 'other'


def pattern_counts(results: Results) -> dict[str, dict[str, int]]:
    """The client-fact pattern counts over every string in the file, keys included, by where the string sits:
    chunk content, document names, error strings, the header, and everything else (ids, sent text)."""
    counts = {place: dict.fromkeys((name for name, _ in CLIENT_FACT_PATTERNS), 0) for place in PATTERN_PLACES}
    found = [('header', text) for _, text in _strings(results.header)]
    found += [(_place(path), text) for line in results.lines for path, text in _strings(line)]
    for place, text in found:
        text = text.translate(_ARABIC_DIGITS)
        for name, pattern in CLIENT_FACT_PATTERNS:
            counts[place][name] += len(pattern.findall(text))
    return counts


def summary(results: Results) -> dict:
    header = results.header
    per_field = {name: {'lines': 0, 'ok': 0, 'error': 0, 'chunks': 0} for name in header['fields']}
    for line in results.lines:
        row = per_field[line['field']]
        row['lines'] += 1
        row[line['status']] += 1
        row['chunks'] += len(line['chunks'])
    version = header['ragflow_version']
    return {
        'w1': header['w1'],
        'fields': list(header['fields']),
        'per_field': per_field,
        'datasets': len(header['datasets']),
        'ragflow_version': version if isinstance(version, str) and SAFE_NAME.match(version) else
        (None if version is None else '<not shown: unexpected characters>'),
        'script_sha256': header['script_sha256'],
        'queries_sha256': header['queries_sha256'],
    }


def _ours(package: Path, name: str) -> str | None:
    """The sha256 of the file we sent: the package's copy, else (for run_w1.py) the one beside this script."""
    for path in (Path(package) / name, TOOL / name):
        if path.is_file():
            return sha256_file(path)
    return None


def _repository_root(path: Path) -> Path | None:
    """The nearest folder at or above `path` holding .git (a folder, or a file in a worktree)."""
    return next((folder for folder in (path, *path.parents) if (folder / '.git').exists()), None)


def handover_folder(root: Path, handover_id: str) -> Path:
    if not SLUG.match(handover_id or '') or handover_id in WINDOWS_DEVICES:
        raise Refused('--handover-id must be a lower-case slug: letters, digits and dashes, at most 64 characters')
    absolute = Path(os.path.realpath(root))  # resolved, so a link cannot carry a "quarantine" name elsewhere
    if 'quarantine' not in (part.lower() for part in absolute.parts):
        raise Refused(f'{root} is not inside a folder named "quarantine" (resolved: {absolute})')
    repository = _repository_root(absolute)
    if repository is not None:
        raise Refused(f'{root} is inside the repository {repository}; the quarantine must sit outside every repository')
    if not absolute.is_dir():
        raise Refused(f'the quarantine folder {absolute} does not exist; create it on purpose first')
    return absolute / handover_id


def _write_json(path: Path, value: dict) -> None:
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    os.replace(tmp, path)


def intake(file: Path, handover_id: str, client_data: str | None, rights: str, origin: str, received: str,
           root: Path = DEFAULT_ROOT, package: Path = DEFAULT_PACKAGE) -> dict:
    """Check, copy and record one returned file. Returns the manifest. Raises Refused before writing anything."""
    if client_data is None:
        raise Refused('--client-data-declared is required: Walid declares the client-data flag for each file '
                      '(spec safe path, step 2)')
    if client_data == 'yes':
        raise Refused('the file is declared to hold client data; a flagged file is never taken (spec safe path, step 2)')
    try:
        received_on = date.fromisoformat(received).isoformat()
    except ValueError:
        raise Refused('--received must be a date as YYYY-MM-DD') from None
    folder = handover_folder(root, handover_id)
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise Refused(f'{folder} already exists and is not an empty folder')
    results = read_results(file)
    digest = sha256_file(file)
    facts = summary(results)
    script, queries = _ours(package, 'run_w1.py'), _ours(package, 'w1-queries.jsonl')
    warnings = list(results.warnings)
    if script is not None and script != facts['script_sha256']:
        warnings.append('script_sha256 differs from our run_w1.py: the script he ran is not byte-identical to ours')
    if queries is not None and queries != facts['queries_sha256']:
        warnings.append('queries_sha256 differs from the w1-queries.jsonl we sent')
    for name, row in facts['per_field'].items():
        if row['error']:
            warnings.append(f'{row["error"]} {name} lines have status "error"')
    original = Path(file).name
    manifest = {
        'manifest': 1,
        'handover_id': handover_id,
        'declared_type': DECLARED_TYPE,
        'origin': origin,
        'date_received': received_on,
        'intake_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'client_data_declared': client_data,
        'rights_status': rights,
        'use': USE,
        'files': [{
            'name': STORED_NAME,
            'original_name': original if SAFE_NAME.match(original) else '<not recorded: unexpected characters>',
            'sha256': digest,
            'bytes': Path(file).stat().st_size,
        }],
        'contract': {**facts,
                     'script_matches_ours': None if script is None else script == facts['script_sha256'],
                     'queries_match_ours': None if queries is None else queries == facts['queries_sha256']},
        'pattern_counts': pattern_counts(results),
        'screening': {'status': 'pending',
                      'note': 'a person screens the file before anything else opens it (spec safe path, step 4)'},
        'screening_history': [],
        'warnings': warnings,
    }
    folder.mkdir(mode=0o700, exist_ok=True)
    stored = folder / STORED_NAME
    tmp = folder / (STORED_NAME + '.tmp')
    try:
        tmp.write_bytes(Path(file).read_bytes())
        if sha256_file(tmp) != digest:
            raise Refused('the copy does not match the file it was copied from')
        os.replace(tmp, stored)
        _write_json(folder / MANIFEST, manifest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        stored.unlink(missing_ok=True)
        raise
    return manifest


def record_screening(handover_id: str, screened_by: str, outcome: str, root: Path = DEFAULT_ROOT,
                     on: str | None = None) -> dict:
    """Record a person's screen. Each screen is added to screening_history. A flagged file stays flagged: it is
    returned or deleted as the agreement says, and is not opened further (spec safe path, step 4)."""
    folder = handover_folder(root, handover_id)
    manifest = load_manifest(folder)
    if outcome not in ('clear', 'flagged'):
        raise Refused('--outcome must be "clear" or "flagged"')
    name = ' '.join((screened_by or '').split())
    if not name or len(name) > 100 or not name.isprintable():
        raise Refused('--screened-by must name the person, in at most 100 printable characters')
    if (manifest.get('screening') or {}).get('status') == 'flagged':
        raise Refused('the screen is already recorded as "flagged": the file is returned or deleted as the agreement '
                      'says, and is not opened further (spec safe path, step 4)')
    screen = {'status': outcome, 'by': name, 'on': on or date.today().isoformat(),
              'recorded_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'note': 'recorded with intake_w1.py --record-screening (spec safe path, step 4)'}
    manifest['screening'] = screen
    manifest['screening_history'] = [*manifest.get('screening_history', []), screen]
    _write_json(folder / MANIFEST, manifest)
    return manifest


def load_manifest(folder: Path) -> dict:
    path = Path(folder) / MANIFEST
    if not path.is_file():
        raise Refused(f'no {MANIFEST} in {folder}: run intake_w1.py first')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    stored = Path(folder) / STORED_NAME
    if not stored.is_file() or sha256_file(stored) != manifest['files'][0]['sha256']:
        raise Refused(f'{stored} is missing or no longer matches the sha256 in {MANIFEST}')
    return manifest


def check_cleared(results_path: Path) -> dict:
    """The manifest beside a quarantined results file, if it lets the file be scored; else Refused. The file must
    sit in a handover folder that handover_folder accepts: inside a quarantine, outside every repository."""
    results_path = Path(results_path)
    if results_path.name != STORED_NAME:
        raise Refused(f'score the quarantined copy ({STORED_NAME} in a handover folder), not {results_path.name}')
    resolved = Path(os.path.realpath(results_path))
    if resolved.name != STORED_NAME:
        raise Refused(f'{results_path} is a link to another file; score the quarantined copy itself')
    manifest = load_manifest(handover_folder(resolved.parent.parent, resolved.parent.name))
    if manifest.get('client_data_declared') != 'no':
        raise Refused('the manifest does not record the client-data flag as "no"')
    status = (manifest.get('screening') or {}).get('status')
    if status != 'clear':
        raise Refused(f'the screen is "{status}", not "clear": a person screens the file first and records it with '
                      'intake_w1.py --record-screening (spec safe path, step 4)')
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0], allow_abbrev=False)
    parser.add_argument('--file', type=Path, help='the returned W1 results file')
    parser.add_argument('--handover-id', required=True, help='a lower-case slug naming this handover')
    parser.add_argument('--client-data-declared', choices=('no', 'yes'),
                        help="Walid's declaration for this file; required, and \"yes\" is refused")
    parser.add_argument('--rights', default='not yet checked by the lawyer (spec safe path, step 5)',
                        help='the rights status Walid declared')
    parser.add_argument('--origin', default="Walid (lawyer): ranked results of run_w1.py on his own RAGFlow",
                        help='where the file came from')
    parser.add_argument('--received', default=date.today().isoformat(), help='the date received, YYYY-MM-DD')
    parser.add_argument('--quarantine-root', type=Path, default=DEFAULT_ROOT, help=f'default {DEFAULT_ROOT}')
    parser.add_argument('--package', type=Path, default=DEFAULT_PACKAGE,
                        help=f'the package we sent, to compare the header hashes with (default {DEFAULT_PACKAGE})')
    parser.add_argument('--record-screening', action='store_true', help="record a person's screen of the file")
    parser.add_argument('--screened-by', help='with --record-screening: who screened it')
    parser.add_argument('--outcome', choices=('clear', 'flagged'), help='with --record-screening: the outcome')
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='backslashreplace')
    args = _parser().parse_args(argv)
    try:
        if args.record_screening:
            manifest = record_screening(args.handover_id, args.screened_by, args.outcome, args.quarantine_root)
            print(f'recorded screening "{manifest["screening"]["status"]}" for {args.handover_id}')
            return 0
        if args.file is None:
            raise Refused('--file is required')
        manifest = intake(args.file, args.handover_id, args.client_data_declared, args.rights, args.origin,
                          args.received, args.quarantine_root, args.package)
    except Refused as error:
        print(f'refused: {error}', file=sys.stderr)
        return 2
    folder = handover_folder(args.quarantine_root, args.handover_id)
    contract = manifest['contract']
    print(f'quarantined {STORED_NAME} in {folder}')
    print(f'sha256 {manifest["files"][0]["sha256"]}')
    for name, row in contract['per_field'].items():
        print(f'{name}: {row["lines"]} lines ({row["ok"]} ok, {row["error"]} error), {row["chunks"]} chunks')
    found = ', '.join(f'{place} {name} {count}' for place, counts in manifest['pattern_counts'].items()
                      for name, count in counts.items() if count)
    print(f'pattern counts for the screen: {found or "none found"}')
    for warning in manifest['warnings']:
        print(f'warning: {warning}')
    print('next: a person screens the file, then: intake_w1.py --record-screening --handover-id '
          f'{args.handover_id} --screened-by NAME --outcome clear|flagged')
    return 0


if __name__ == '__main__':
    sys.exit(main())
