#!/usr/bin/env python3
"""key_leak_check.py: search saved files and a stream for a key, and never print it. Runs inside the runner.

The hosted run's leak check (README.md, «Hosted run (owner, 2026-11-09)», H3 and H9): the key is read from the file
only the runner has, and everything the run saved, the server's log and the containers' configuration are searched
for it. It is the W2 runs' API-key check («grep -c -F -f /run/rf/key», state/run-es.json key_leak_check) made a tool:

  N=$(docker logs ragbench-rf-server 2>&1 | wc -c)
  docker logs ragbench-rf-server 2>&1 | docker exec -i ragbench-rf-runner python3 -I -B /w2/key_leak_check.py \
      --key-file /keys/openrouter.key --registration /out/elasticsearch/hosted-embedder.json \
      --scan /hr --stdin server-log --min-bytes "$N"; echo "pipeline exit $?"
  docker inspect ragbench-rf-server ragbench-rf-runner ragbench-rf-proxy \
    | docker exec -i ragbench-rf-runner python3 -I -B /w2/key_leak_check.py --key-file /keys/openrouter.key \
      --stdin docker-inspect; echo "pipeline exit $?"

What counts as a leak: the whole key, or any of its 16-character pieces (the part after «sk-or-v1-» or «ragflow-»,
cut at every 16 characters, plus its last 16), so a key cut short or partly masked by a log formatter is found too.
It finds the bytes as they are: a key re-encoded (base64, URL or UTF-16) is not found. A key that runs across two
reads is found once, at the read where it ends.

--key-file        the key: one line (LF or CRLF), printable ASCII, no space, at least 20 characters.
--registration    register_hosted.py's hosted-embedder.json: the key must have its salted sha256, so the check
                  cannot pass by searching for another key than the one the server stored.
--scan DIR|FILE   every regular file below it (links are not followed); the key file itself is skipped and said so.
--stdin LABEL     also read standard input, reported under that label.
--min-bytes N     the stream must hold at least N bytes: the runbook takes N from a separate count of the same stream
                  (`docker logs … 2>&1 | wc -c`) made just before, so a stream cut short cannot pass.
Prints counts and the paths of hits, never a key or a piece. Exit 0 no key found, 1 found, 2 refused or incomplete
(a key file or registration that does not hold, nothing to read, a file that could not be read, a --scan that read
no file, a stream of 0 bytes or of fewer than --min-bytes; a failed `docker logs` pipes in its error text, which
--min-bytes catches). A key found outranks an incomplete check. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

PIECE = 16
PREFIXES = ('sk-or-v1-', 'ragflow-')
KEY_SHAPE = re.compile(r'[\x21-\x7e]{20,}')
CHUNK = 1 << 20


class Refused(Exception):
    """The check cannot be made, or would not mean anything."""


def read_key(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        raise Refused(f'no readable key file at {path}') from None
    body = raw[:-2] if raw.endswith(b'\r\n') else raw[:-1] if raw.endswith(b'\n') else raw
    try:
        key = body.decode('ascii')
    except UnicodeDecodeError:
        key = ''
    if not KEY_SHAPE.fullmatch(key):
        raise Refused('the key file must hold one key on one line: printable ASCII, no space, 20 characters or more')
    return key


def pieces(key: str) -> list[str]:
    secret = next((key[len(p):] for p in PREFIXES if key.startswith(p)), key)
    found = [secret[i:i + PIECE] for i in range(0, len(secret) - PIECE + 1, PIECE)]
    if len(secret) >= PIECE and secret[-PIECE:] not in found:
        found.append(secret[-PIECE:])
    return found


def check_registration(path: Path, key: str) -> None:
    try:
        summary = json.loads(path.read_text(encoding='utf-8'))['key']
        salt, want = summary['salt'], summary['salted_sha256']
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise Refused(f'{path.name} holds no key summary (register_hosted.py writes key.salt and key.salted_sha256)') \
            from None
    if not isinstance(salt, str) or hashlib.sha256((salt + key).encode('ascii')).hexdigest() != want:
        raise Refused(f'the key file is not the key {path.name} registered: searching for it would prove nothing')


class Counter:
    """Counts every pattern in a stream read in blocks, each match once, at the block in which it ends."""

    def __init__(self, key: str):
        self.full, self.parts = key.encode('ascii'), [p.encode('ascii') for p in pieces(key)]
        self.keep = len(self.full) - 1

    def count(self, blocks) -> tuple[int, int, int]:
        """(full-key matches, piece matches, bytes read)"""
        full = parts = size = 0
        tail = b''
        for block in blocks:
            size += len(block)
            data = tail + block
            full += self._ending_after(data, self.full, len(tail))
            parts += sum(self._ending_after(data, p, len(tail)) for p in self.parts)
            tail = data[-self.keep:] if self.keep else b''
        return full, parts, size

    @staticmethod
    def _ending_after(data: bytes, pattern: bytes, start: int) -> int:
        n, at = 0, data.find(pattern)
        while at != -1:
            if at + len(pattern) > start:
                n += 1
            at = data.find(pattern, at + 1)
        return n


def file_blocks(path: str, size: int):
    with open(path, 'rb') as handle:
        while True:
            block = handle.read(size)
            if not block:
                return
            yield block


def walk(root: Path):
    """Every regular file at or below root, in a stable order; links are not followed."""
    if root.is_file() and not root.is_symlink():
        yield str(root)
        return
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(folder, name)
            if not os.path.islink(path) and os.path.isfile(path):
                yield path


def main(argv: list[str] | None = None, *, stdout=None, stdin=None, chunk_size: int = CHUNK) -> int:
    stdout = stdout or sys.stdout
    ap = argparse.ArgumentParser(description='Search saved files and a stream for a key, without printing it.')
    ap.add_argument('--key-file', required=True, type=Path)
    ap.add_argument('--registration', type=Path)
    ap.add_argument('--scan', action='append', type=Path, default=[])
    ap.add_argument('--stdin', metavar='LABEL')
    ap.add_argument('--min-bytes', type=int, metavar='N')
    args = ap.parse_args(argv)

    def say(line: str) -> None:
        print(line, file=stdout, flush=True)

    try:
        key = read_key(args.key_file)
        if not args.scan and args.stdin is None:
            raise Refused('nothing to search: give --scan and/or --stdin')
        if args.min_bytes is not None and (args.stdin is None or args.min_bytes < 0):
            raise Refused('--min-bytes needs --stdin, and a count of 0 or more')
        missing = [str(p) for p in args.scan if not p.exists()]
        if missing:
            raise Refused(f'no such file or folder: {", ".join(missing)}')
        counter = Counter(key)
        say(f'key: {len(key)} characters, searched whole and as {len(counter.parts)} pieces of {PIECE} '
            '(never printed)')
        if args.registration is not None:
            check_registration(args.registration, key)
            say(f'registration: the key is the one {args.registration.name} registered (salted sha256)')
    except Refused as refusal:
        say(f'refused: {refusal}')
        return 2
    hits, unread, files, size = [], [], 0, 0
    own = os.path.realpath(args.key_file)
    skipped_key = False
    for root in args.scan:
        for path in walk(root):
            if os.path.realpath(path) == own:
                skipped_key = True
                continue
            try:
                full, parts, read = counter.count(file_blocks(path, chunk_size))
            except OSError:
                unread.append(path)
                continue
            files, size = files + 1, size + read
            if full or parts:
                hits.append((path, full, parts))
    where = ', '.join(str(p) for p in args.scan)
    summary = [f'scanned {files} file(s), {size:,} bytes under {where}'] if args.scan else []
    incomplete = [f'could not read {len(unread)} file(s): {", ".join(unread[:5])}'] if unread else []
    if args.scan and files == 0:
        incomplete.append('no file was read')
    if args.stdin is not None:
        stream = stdin if stdin is not None else sys.stdin.buffer
        full, parts, read = counter.count(iter(lambda: stream.read(chunk_size), b''))
        summary.append(f'stdin «{args.stdin}» {read:,} bytes')
        if full or parts:
            hits.append((f'stdin «{args.stdin}»', full, parts))
        least = max(args.min_bytes or 0, 1)
        if read < least:
            incomplete.append(f'stdin «{args.stdin}» read {read} bytes'
                              + (f', fewer than --min-bytes {args.min_bytes}' if read else ''))
    say('; '.join(summary) + ('; skipped the key file itself' if skipped_key else ''))
    for place, full, parts in hits:
        say(f'HIT {place}: full key {full}, pieces {parts}')
    for reason in incomplete:
        say(f'INCOMPLETE: {reason}')
    if hits:  # a key found outranks a check left incomplete
        say(f'KEY FOUND in {len(hits)} place(s)')
        return 1
    if incomplete:
        return 2
    say('NO KEY FOUND')
    return 0


if __name__ == '__main__':
    sys.exit(main())
