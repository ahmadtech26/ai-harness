#!/usr/bin/env python3
"""Build the W1 package the owner sends Walid: w1-queries.jsonl, a copy of run_w1.py, and SHA256SUMS.

w1-queries.jsonl has one header line, then one line per eval item in eval-set order with only
id, query and question. Nothing else from the eval set is written: no expected articles, no law
field, no notes. The ids are the eval set's own, so they still name each item's law and mark the
six memorandum items (civil-code-memo-NN). Standard library only.

    python make_package.py [--eval PATH] [--out DIR] [--runner PATH] [--replace] [--allow-other-set]

Exit codes: 0 written; 1 failed while writing; 2 refused before anything was written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_EVAL = REPO / 'content' / 'eval' / 'retrieval-v1.jsonl'
DEFAULT_OUT = REPO.parent / '.hq' / 'docs' / 'specs' / 'w1-for-walid'
DEFAULT_RUNNER = HERE / 'run_w1.py'

QUERIES_NAME = 'w1-queries.jsonl'
RUNNER_NAME = 'run_w1.py'
SUMS_NAME = 'SHA256SUMS'
PACKAGE_NAMES = (QUERIES_NAME, RUNNER_NAME, SUMS_NAME)
TMP_SUFFIX = '.w1-tmp'

FIELDS = ('query', 'question')
SENT_KEYS = ('id',) + FIELDS

# The frozen set the decisive test runs on (spec-rag-system.md, «The decisive test»: set sha 870ce8df5335).
# Computed as legal_search.evalset does: sha256 of the non-empty item lines joined by "\n", header excluded.
FROZEN_SET_SHA256 = '870ce8df5335f6fae364c07b7af3d3de9a0b2f98bede262858ab83510cbd79f2'
FROZEN_COUNT = 80

NOTE = ('W1 retrieval queries: send each field (query, then question) as written. '
        '| استعلامات اختبار W1: يُرسَل كل حقل (query ثم question) كما هو مكتوب.')


class Refused(Exception):
    """A problem found before anything was written."""


def ascii_safe(value: object) -> str:
    """Terminal text: non-ASCII is escaped, so a cp1252 console cannot fail on an Arabic path."""
    return str(value).encode('ascii', 'backslashreplace').decode('ascii')


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_evalset(path: Path) -> tuple[dict, list[dict], str]:
    """The header, the items in file order, and the set fingerprint. Raises Refused listing every problem."""
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise Refused(f'cannot read the eval set {ascii_safe(path)}: {error.strerror or type(error).__name__}')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise Refused(f'the eval set {ascii_safe(path)} is not UTF-8')
    text = text.lstrip('\ufeff').replace('\r\n', '\n')
    lines = [(number, line) for number, line in enumerate(text.split('\n'), 1) if line.strip()]
    if not lines:
        raise Refused('the eval set is empty')
    problems: list[str] = []
    header = _object(*lines[0], problems)
    if header is not None and not (isinstance(header.get('set'), str) and header['set'].strip()):
        problems.append(f'line {lines[0][0]}: the header needs a "set" name')
    items: list[dict] = []
    seen: set[str] = set()
    for number, line in lines[1:]:
        item = _object(number, line, problems)
        if item is None:
            continue
        bad = [key for key in SENT_KEYS if not (isinstance(item.get(key), str) and item[key].strip())]
        if bad:
            problems.append(f'line {number}: {", ".join(bad)} must be non-empty strings')
            continue
        if item['id'] in seen:
            problems.append(f'line {number}: duplicate id {ascii_safe(item["id"])}')
        seen.add(item['id'])
        items.append(item)
    if not items and not problems:
        problems.append('the eval set has no items')
    if problems:
        raise Refused('the eval set cannot be read:\n  ' + '\n  '.join(problems))
    fingerprint = sha256_bytes('\n'.join(line for _, line in lines[1:]).encode('utf-8'))
    return header, items, fingerprint


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


def _line(value: dict) -> str:
    # U+2028 and U+2029 are escaped too: some readers split lines on them.
    text = json.dumps(value, ensure_ascii=False)
    return text.replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def queries_file(set_name: str, items: list[dict]) -> bytes:
    """The w1-queries.jsonl bytes: UTF-8, LF line ends, no BOM. Each item keeps id, query and question only."""
    header = {'set': set_name, 'w1': 1, 'count': len(items), 'fields': list(FIELDS), 'note': NOTE}
    lines = [_line(header)] + [_line({key: item[key] for key in SENT_KEYS}) for item in items]
    return ('\n'.join(lines) + '\n').encode('utf-8')


def sums_file(hashes: dict[str, str]) -> bytes:
    """sha256sum format (hash, two spaces, name), so `sha256sum -c SHA256SUMS` checks it."""
    return ''.join(f'{digest}  {name}\n' for name, digest in hashes.items()).encode('ascii')


def check_out(out: Path, replace: bool) -> list[str]:
    """Refuse an unusable folder, or package files already there without --replace. Returns the other files."""
    if out.exists() and not out.is_dir():
        raise Refused(f'--out {ascii_safe(out)} exists and is not a folder')
    if not out.exists():
        if not out.parent.is_dir():
            raise Refused(f'the parent of --out {ascii_safe(out)} does not exist')
        return []
    present = sorted(entry.name for entry in out.iterdir())
    clash = [name for name in PACKAGE_NAMES if name in present]
    if clash and not replace:
        raise Refused(f'{ascii_safe(out)} already holds {", ".join(clash)}; pass --replace to overwrite them')
    return [name for name in present if name not in PACKAGE_NAMES and not name.endswith(TMP_SUFFIX)]


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + TMP_SUFFIX)
    with open(tmp, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def build(eval_path: Path, out: Path, runner: Path, replace: bool = False,
          allow_other_set: bool = False) -> tuple[dict[str, str], list[str], int]:
    """Check everything, then write the package. Returns the hashes, the other files in --out, and the count."""
    header, items, fingerprint = read_evalset(eval_path)
    if not allow_other_set:
        if fingerprint != FROZEN_SET_SHA256:
            raise Refused(f'the eval set is not the frozen set (fingerprint {fingerprint[:12]}, '
                          f'expected {FROZEN_SET_SHA256[:12]}); pass --allow-other-set to package it anyway')
        if len(items) != FROZEN_COUNT:
            raise Refused(f'the eval set has {len(items)} items, expected {FROZEN_COUNT}')
    if not runner.is_file():
        raise Refused(f'{RUNNER_NAME} not found at {ascii_safe(runner)}; nothing was written. '
                      f'Write it first, or pass --runner PATH')
    try:
        runner_bytes = runner.read_bytes()
    except OSError as error:
        raise Refused(f'cannot read {ascii_safe(runner)}: {error.strerror or type(error).__name__}')
    if not runner_bytes.strip():
        raise Refused(f'{ascii_safe(runner)} is empty; nothing was written')
    others = check_out(out, replace)

    queries = queries_file(header['set'], items)
    files = {QUERIES_NAME: queries, RUNNER_NAME: runner_bytes}
    out.mkdir(exist_ok=True)
    hashes = {}
    for name, data in files.items():
        write_atomic(out / name, data)
        hashes[name] = sha256_bytes(data)
    for name, digest in hashes.items():  # read back what landed on disk
        if sha256_bytes((out / name).read_bytes()) != digest:
            raise OSError(f'{name} on disk does not match what was written')
    write_atomic(out / SUMS_NAME, sums_file(hashes))
    return hashes, others, len(items)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='make_package.py', allow_abbrev=False,
        description='Write w1-queries.jsonl, a copy of run_w1.py and SHA256SUMS into one folder.')
    parser.add_argument('--eval', type=Path, default=DEFAULT_EVAL,
                        help='the eval set (default: this repository\'s content/eval/retrieval-v1.jsonl)')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT,
                        help='the package folder (default: .hq/docs/specs/w1-for-walid beside the repository)')
    parser.add_argument('--runner', type=Path, default=DEFAULT_RUNNER,
                        help='the run_w1.py to copy (default: the one beside this script)')
    parser.add_argument('--replace', action='store_true',
                        help='overwrite the three package files if they are already there; nothing else is touched')
    parser.add_argument('--allow-other-set', action='store_true',
                        help='package an eval set that is not the frozen 80-item set')
    return parser


def main(argv: list[str] | None = None, stdout=None, stderr=None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        hashes, others, count = build(args.eval, args.out, args.runner, args.replace, args.allow_other_set)
    except Refused as error:
        print(f'refused: {error}', file=stderr)
        return 2
    except OSError as error:
        print(f'failed while writing: {ascii_safe(error)}', file=stderr)
        return 1
    print(f'eval set: {ascii_safe(args.eval)} ({count} items)', file=stdout)
    for name, digest in hashes.items():
        print(f'wrote {ascii_safe(args.out / name)}  sha256 {digest}', file=stdout)
    print(f'wrote {ascii_safe(args.out / SUMS_NAME)}', file=stdout)
    if others:
        print(f'also in the folder, not part of the package: {", ".join(ascii_safe(n) for n in others)}', file=stdout)
    print(f'Send {QUERIES_NAME} and {RUNNER_NAME} (by email, both in one .zip: Outlook blocks .py). '
          f'Keep {SUMS_NAME}: the returned header\'s queries_sha256 and script_sha256 should equal it.', file=stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main())
