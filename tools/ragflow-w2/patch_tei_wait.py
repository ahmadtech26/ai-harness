#!/usr/bin/env python3
"""patch_tei_wait.py: raise RAGFlow v0.27.3's wait on TEI from 30 s to --wait seconds, on exactly two lines.

    python -I -B patch_tei_wait.py --source <embedding_model.py copied from the pinned image> --out <folder>
        [--wait 900] [--expect-sha256 <64 hex>] [--replace]

Spec: .hq/docs/specs/spec-rag-system.md, «Owner decision 2026-11-08 (later): raise RAGFlow's wait on the
embedder; run both engines», bullet «The change». On this machine the pinned TEI needs 36-39 s for the longest
article, and RAGFlow v0.27.3 waits 30 s per TEI call with no retry: the requests.post lines of
HuggingFaceEmbed.encode and HuggingFaceEmbed.encode_queries (rag/llm/embedding_model.py:1247, :1253 in the
v0.27.3 source tree, .hq/scratch/ragflow-src-v0.27.3/x/). The built-in TEI embedder delegates to that class
(BuiltinEmbed, embedding_model.py:240, :251, :258).

What it changes: `timeout=30)` to `timeout=<wait>)` at the end of those two lines, and nothing else. The two
lines are found by their exact full text as they stand in v0.27.3 (ANCHORS below, leading spaces included).
The file holds six more `timeout=30` lines in other classes (lines 614, 900, 986, 1140, 1461, 1481); they are
left alone.

It refuses (exit 2, nothing written) when:
  - the source holds a CR byte (CRLF or CR line ends) or is not UTF-8;
  - --expect-sha256 is given and the source's sha256 differs;
  - either anchor is not found exactly once, or there is not exactly one `class HuggingFaceEmbed`;
  - an anchor sits outside class HuggingFaceEmbed, or under another method than the one it is named for;
  - --wait is not a whole number above 30;
  - the result differs from the source anywhere but those two lines and that number (checked by a second,
    independent pass over both texts), or does not compile, or its compiled HuggingFaceEmbed.encode and
    encode_queries do not hold the new wait and no 30 among their constants (compiled by this Python, not the
    server's: check_tei_wait.py is the check in the server's own Python);
  - --out is a file, is not empty without --replace, or holds anything this tool does not write (even with
    --replace), or holds the source itself.

It writes into --out: embedding_model.py (the patched file, LF line ends as the source), embedding_model.diff
(unified, a/ and b/ named rag/llm/embedding_model.py) and patch.json:
  {"file": "rag/llm/embedding_model.py", "image_sha256": <sha256 of the source>, "patched_sha256": <of the
   patched file>, "changed_lines": [<1-based line numbers, ascending>], "wait_s": <wait>,
   "anchors": [{"method", "line", "before", "after"}, ...]}   (anchors in ANCHORS order: encode, encode_queries)
`image_sha256` is the sha256 of the bytes given as --source: the prepare step copies them out of the pinned image
and checks that sha256 itself (README, «## TEI wait patch»). Standard library only; Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

FILE = 'rag/llm/embedding_model.py'
CLASS = 'HuggingFaceEmbed'
SHIPPED = 30
OLD_TAIL = f'timeout={SHIPPED})'
# The two lines as they stand in v0.27.3 (embedding_model.py:1247, :1253), named by the method that holds them.
# Plain strings, not f-strings: the braces are the source's own.
ANCHORS = (
    ('encode', '        response = requests.post(f"{self.base_url}/embed", json={"inputs": texts}, '
               'headers={"Content-Type": "application/json"}, timeout=30)'),
    ('encode_queries', '        response = requests.post(f"{self.base_url}/embed", json={"inputs": text}, '
                       'headers={"Content-Type": "application/json"}, timeout=30)'),
)
OUT_PY, OUT_DIFF, OUT_JSON = 'embedding_model.py', 'embedding_model.diff', 'patch.json'
OUTPUTS = (OUT_PY, OUT_DIFF, OUT_JSON)
HEX64 = re.compile(r'[0-9a-f]{64}')
CLASS_LINE = re.compile(rf'class {CLASS}\b')
METHOD_LINE = re.compile(r'    def (\w+)\(')


class Refused(Exception):
    """A problem found before anything was written."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_source(path: Path) -> tuple[bytes, str]:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise Refused(f'cannot read --source {path}: {type(error).__name__}') from None
    carriage_returns = data.count(b'\r')
    if carriage_returns:
        raise Refused(f'{path.name} holds {carriage_returns} CR byte(s): CRLF or CR line ends are refused, '
                      'since the copy from the image has LF only')
    try:
        return data, data.decode('utf-8')
    except UnicodeDecodeError:
        raise Refused(f'{path.name} is not UTF-8') from None


def class_bounds(lines: list[str]) -> tuple[int, int]:
    """(first, end): the `class HuggingFaceEmbed` line and the first line after its body (the next line at column
    0 that is neither blank nor a comment)."""
    starts = [i for i, line in enumerate(lines) if CLASS_LINE.match(line)]
    if len(starts) != 1:
        raise Refused(f'expected exactly one `class {CLASS}`, found {len(starts)}')
    first = starts[0]
    end = next((i for i in range(first + 1, len(lines))
                if lines[i] and not lines[i][0].isspace() and not lines[i].startswith('#')), len(lines))
    return first, end


def locate(lines: list[str]) -> list[tuple[str, int]]:
    """[(method, 0-based index)] of the two anchors, each found once, inside the class, under its own method."""
    first, end = class_bounds(lines)
    found = []
    for method, anchor in ANCHORS:
        hits = [i for i, line in enumerate(lines) if line == anchor]
        if len(hits) != 1:
            raise Refused(f'the {method} anchor (the v0.27.3 requests.post line) is found {len(hits)} time(s), '
                          'not exactly once: this is not the v0.27.3 file')
        index = hits[0]
        if not first < index < end:
            raise Refused(f'the {method} anchor is at line {index + 1}, outside class {CLASS} '
                          f'(lines {first + 1}-{end})')
        owner = next((m.group(1) for m in (METHOD_LINE.match(lines[i]) for i in range(index - 1, first, -1)) if m),
                     None)
        if owner != method:
            raise Refused(f'the {method} anchor at line {index + 1} sits under {CLASS}.{owner}, not {CLASS}.{method}')
        found.append((method, index))
    return found


def patched_line(line: str, wait: int) -> str:
    return line[:-len(OLD_TAIL)] + f'timeout={wait})'


def verify(original: str, patched: str, wait: int, indices: list[int]) -> None:
    """The second pass, independent of the patching: the two texts have the same lines but at `indices`, and each
    of those differs only in the number after `timeout=`, 30 before and `wait` after."""
    a, b = original.split('\n'), patched.split('\n')
    if len(a) != len(b):
        raise Refused(f'the result has {len(b)} lines, the source {len(a)}')
    differing = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if differing != sorted(indices):
        raise Refused(f'the result differs from the source on lines {[i + 1 for i in differing]}, not only on '
                      f'{[i + 1 for i in sorted(indices)]}')
    for i in differing:
        x, y = a[i], b[i]
        if not (x.endswith(OLD_TAIL) and y.endswith(f'timeout={wait})')
                and x[:-len(OLD_TAIL)] == y[:-len(f'timeout={wait})')]):
            raise Refused(f'line {i + 1} differs by more than timeout={SHIPPED} becoming timeout={wait}')
    expected = len(original.encode('utf-8')) + len(indices) * (len(str(wait)) - len(str(SHIPPED)))
    if len(patched.encode('utf-8')) != expected:
        raise Refused(f'the result is {len(patched.encode("utf-8"))} bytes, not {expected}')


def compiled_constants(text: str) -> dict[str, list]:
    """{method: the numbers among its own code constants} for HuggingFaceEmbed.encode and encode_queries, from
    compiling `text` (nothing is run). Nested code objects are not searched: Python 3.11 compiles encode's list
    comprehension as one, 3.12 and later inline it (PEP 709)."""
    try:
        module = compile(text, FILE, 'exec', dont_inherit=True)
    except SyntaxError as error:
        raise Refused(f'the result does not compile: {error.msg} at line {error.lineno}') from None
    bodies = [c for c in module.co_consts if getattr(c, 'co_name', None) == CLASS]
    if len(bodies) != 1:
        raise Refused(f'the compiled module holds {len(bodies)} class bodies named {CLASS}, not 1')
    found = {}
    for code in bodies[0].co_consts:
        name = getattr(code, 'co_name', None)
        if name in dict(ANCHORS):
            found[name] = [c for c in code.co_consts if type(c) in (int, float)]
    return found


def check_compiled(text: str, wait: int) -> None:
    constants = compiled_constants(text)
    for method, _ in ANCHORS:
        numbers = constants.get(method)
        if numbers is None:
            raise Refused(f'the compiled {CLASS} has no {method}')
        if not any(type(n) is int and n == wait for n in numbers) or any(n == SHIPPED for n in numbers):
            raise Refused(f'the compiled {CLASS}.{method} holds the numbers {numbers}: not {wait} without {SHIPPED}')


def prepare_out(out: Path, source: Path, replace: bool) -> list[Path]:
    """The files a --replace run removes; refuses a non-empty folder without --replace, any entry this tool does
    not write even with it (make_w2_corpus.py's convention), and an --out that holds the source."""
    if out.exists() and not out.is_dir():
        raise Refused(f'--out is not a folder: {out}')
    if out.is_dir() and source.resolve().parent == out.resolve():
        raise Refused('--source sits in --out: copy it elsewhere first, so a --replace cannot overwrite it')
    entries = sorted(out.iterdir()) if out.is_dir() else []
    if entries and not replace:
        raise Refused(f'--out is not empty ({len(entries)} entries); pass --replace to overwrite this tool\'s files')
    foreign = [e.name for e in entries if not (e.is_file() and not e.is_symlink() and e.name in OUTPUTS)]
    if foreign:
        raise Refused(f'--out holds entries this tool does not write, left alone: {", ".join(foreign[:5])}')
    return entries


def build(source: Path, wait: int, expect_sha256: str | None = None) -> dict:
    """Every check; returns what would be written, without writing."""
    if type(wait) is not int or wait <= SHIPPED:
        raise Refused(f'--wait must be a whole number of seconds above {SHIPPED}, not {wait!r}')
    if expect_sha256 is not None and not HEX64.fullmatch(expect_sha256):
        raise Refused('--expect-sha256 must be 64 lower-case hex characters')
    data, text = read_source(source)
    image_sha = sha256_bytes(data)
    if expect_sha256 is not None and image_sha != expect_sha256:
        raise Refused(f'the source\'s sha256 is {image_sha}, not the expected {expect_sha256}')
    lines = text.split('\n')
    found = locate(lines)
    new_lines = list(lines)
    for _, index in found:
        new_lines[index] = patched_line(lines[index], wait)
    patched = '\n'.join(new_lines)
    indices = [index for _, index in found]
    verify(text, patched, wait, indices)
    check_compiled(patched, wait)
    patched_bytes = patched.encode('utf-8')
    diff = ''.join(difflib.unified_diff(text.splitlines(keepends=True), patched.splitlines(keepends=True),
                                        fromfile=f'a/{FILE}', tofile=f'b/{FILE}', n=3))
    record = {'file': FILE, 'image_sha256': image_sha, 'patched_sha256': sha256_bytes(patched_bytes),
              'changed_lines': sorted(index + 1 for index in indices), 'wait_s': wait,  # ascending, as rf_ingest.py reads it
              'anchors': [{'method': method, 'line': index + 1, 'before': lines[index], 'after': new_lines[index]}
                          for method, index in found]}
    return {'patched': patched_bytes, 'diff': diff.encode('utf-8'), 'record': record}


def write(out: Path, result: dict, stale: list[Path]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for entry in stale:
        entry.unlink()
    written = []
    try:
        for name, data in ((OUT_PY, result['patched']), (OUT_DIFF, result['diff']),
                           (OUT_JSON, (json.dumps(result['record'], ensure_ascii=False, indent=1) + '\n')
                            .encode('utf-8'))):
            (out / name).write_bytes(data)
            written.append(out / name)
        if sha256_bytes((out / OUT_PY).read_bytes()) != result['record']['patched_sha256']:
            raise Refused(f'the written {OUT_PY} reads back with another sha256')
    except (OSError, Refused):
        for path in written:
            path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None, *, stdout=None) -> int:
    stdout = stdout or sys.stdout
    ap = argparse.ArgumentParser(description='Raise HuggingFaceEmbed\'s TEI wait in a copy of RAGFlow v0.27.3\'s '
                                             'rag/llm/embedding_model.py, on exactly two lines.', allow_abbrev=False)
    ap.add_argument('--source', type=Path, required=True, help='embedding_model.py as copied from the pinned image')
    ap.add_argument('--out', type=Path, required=True, help='the folder to write the patch into')
    ap.add_argument('--wait', type=int, default=900, help='seconds (default: %(default)s, the owner\'s value)')
    ap.add_argument('--expect-sha256', help='refuse a source with another sha256')
    ap.add_argument('--replace', action='store_true', help='overwrite this tool\'s files in a non-empty --out')
    args = ap.parse_args(argv)
    try:
        stale = prepare_out(args.out, args.source, args.replace)
        result = build(args.source, args.wait, args.expect_sha256)
        write(args.out, result, stale)
    except Refused as error:
        print(f'refused: {error}', file=stdout)
        return 2
    except OSError as error:
        print(f'refused: cannot write --out: {type(error).__name__}', file=stdout)
        return 2
    record = result['record']
    print(f'source sha256  {record["image_sha256"]}', file=stdout)
    for anchor in record['anchors']:
        print(f'line {anchor["line"]:5d} ({CLASS}.{anchor["method"]}): timeout={SHIPPED} -> timeout={record["wait_s"]}',
              file=stdout)
    print(f'patched sha256 {record["patched_sha256"]}', file=stdout)
    print(f'wrote {", ".join(OUTPUTS)} to {args.out}', file=stdout)
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
