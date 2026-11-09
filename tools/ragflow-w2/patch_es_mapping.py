#!/usr/bin/env python3
"""patch_es_mapping.py: give RAGFlow v0.27.3's Elasticsearch mapping an explicit template for 4096-dimension vectors.

    python -I -B patch_es_mapping.py write --source <conf/mapping.json copied from the pinned image> --out <folder>
        [--replace]
    python -I -B patch_es_mapping.py check --copy <a mapping.json to verify>

Why (README.md, «Hosted run (owner, 2026-11-09)»; PREMISES-hosted-run.md §6): the hosted embedder,
qwen/qwen3-embedding-8b, returns 4096 numbers, so RAGFlow stores them in the field q_4096_vec (`"q_%d_vec" %
len(v)`, rag/flow/tokenizer/tokenizer.py:124). RAGFlow's conf/mapping.json (v0.27.3, in
.hq/scratch/ragflow-src-v0.27.3/x/) has dense_vector templates for *_512_vec, *_768_vec, *_1024_vec and *_1536_vec
only, so Elasticsearch 8.11 would map q_4096_vec through its own dynamic mapping. This tool adds the one template
that is missing, so the mapping the server sends decides the field.

The server reads that file once per process, at os.path.join(get_project_base_directory(), "conf", "mapping.json")
(common/doc_store/es_conn_base.py:38-51), which is /ragflow/conf/mapping.json in the image (common/file_utils.py:22-42:
the folder above common/, since RAG_PROJECT_BASE and RAG_DEPLOY_BASE are set nowhere; Dockerfile:275, :301, :307),
and create_idx sends its "settings" and "mappings" as they are (es_conn_base.py:120-127). compose.hosted.yaml
mounts the copy this tool writes, read-only, over that path.

write: refuses (exit 2, nothing written) unless the source is the pinned v0.27.3 file (SOURCE_SHA256, the image's
own bytes: README.md, H1), and when:
  - the source holds a CR byte or is not UTF-8;
  - the *_1536_vec block (ANCHOR, its exact lines) is not found exactly once, or the text already names *_4096_vec;
  - a property is named q_4096_vec, or a template before the new one would take q_4096_vec (Elasticsearch applies
    the first dynamic template that matches; a template this tool cannot judge counts as one that would);
  - the result is not the source with exactly the eleven lines of the new block inserted right after the
    *_1536_vec block, or its JSON is not the source's with exactly the one template inserted there (a second,
    independent pass over both texts and both parsed documents);
  - --out is a file, is not empty without --replace, holds anything this tool does not write (even with
    --replace), or holds the source.
The new block is the *_1536_vec block with its two numbers changed: the same name ("dense_vector"), the same keys in
the same order, the same options (type dense_vector, index true, similarity cosine), dims 4096.
It writes into --out: mapping.json (the copy, LF line ends as the source), mapping.diff (unified, a/ and b/ named
conf/mapping.json) and mapping-patch.json:
  {"file": "conf/mapping.json", "source_sha256", "patched_sha256", "inserted_lines": [first, last] (1-based, in the
   copy), "after_template": "*_1536_vec", "template": <the new entry>, "field": "q_4096_vec"}

check: verifies a copy, for example the one the server reads (README.md, H3, in the server's own Python):
  - its sha256 is PATCHED_SHA256, the copy write makes from the pinned source;
  - it is JSON, holds exactly one *_4096_vec template, right after *_1536_vec, whose mapping is exactly
    {type dense_vector, index true, similarity cosine, dims 4096}, no property names q_4096_vec, and no earlier
    template would take that field.
It prints one line per check, then «ES MAPPING OK: <path>» (exit 0) or «ES MAPPING NOT APPROVED: …» (exit 1); a
copy it cannot read is refused (exit 2). Standard library only; Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

FILE = 'conf/mapping.json'
SOURCE_SHA256 = '49877a9153c466479ce75a81e5da49e952567ca9c3cb1d46e2b20c2a6bab8097'  # v0.27.3, the image's own bytes
PATCHED_SHA256 = '136b31a0d07b89116e814c99562ecfacbb52aee66ea91e12bf24ba0c4174ef90'  # what write makes from them
AFTER, NEW = '*_1536_vec', '*_4096_vec'
FIELD = 'q_4096_vec'  # "q_%d_vec" % 4096 (rag/flow/tokenizer/tokenizer.py:124)
MAPPING = {'type': 'dense_vector', 'index': True, 'similarity': 'cosine', 'dims': 4096}
# The *_1536_vec block as it stands in v0.27.3 (conf/mapping.json:193-203), and the block inserted after it.
ANCHOR = (
    '      {',
    '        "dense_vector": {',
    '          "match": "*_1536_vec",',
    '          "mapping": {',
    '            "type": "dense_vector",',
    '            "index": true,',
    '            "similarity": "cosine",',
    '            "dims": 1536',
    '          }',
    '        }',
    '      },',
)
BLOCK = tuple(line.replace('"*_1536_vec"', '"*_4096_vec"').replace('"dims": 1536', '"dims": 4096') for line in ANCHOR)
OUT_JSON, OUT_DIFF, OUT_RECORD = 'mapping.json', 'mapping.diff', 'mapping-patch.json'
OUTPUTS = (OUT_JSON, OUT_DIFF, OUT_RECORD)
TEMPLATE_KEYS = {'match', 'match_pattern', 'mapping'}


class Refused(Exception):
    """A problem found before anything was written."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_text(path: Path, what: str) -> tuple[bytes, str]:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise Refused(f'cannot read {what} {path}: {type(error).__name__}') from None
    carriage_returns = data.count(b'\r')
    if carriage_returns:
        raise Refused(f'{path.name} holds {carriage_returns} CR byte(s): CRLF or CR line ends are refused, '
                      'since the copy from the image has LF only')
    try:
        return data, data.decode('utf-8')
    except UnicodeDecodeError:
        raise Refused(f'{path.name} is not UTF-8') from None


def entry(template: dict) -> tuple[str, dict]:
    """(name, body) of one dynamic template, an object with exactly one key."""
    if not isinstance(template, dict) or len(template) != 1:
        raise ValueError(f'a dynamic template is not an object with one name: {json.dumps(template)[:80]}')
    (name, body), = template.items()
    if not isinstance(body, dict):
        raise ValueError(f'the dynamic template {name!r} is not an object')
    return name, body


def takes(body: dict, field: str) -> bool:
    """Whether a top-level field of that name would be given to this template (Elasticsearch: `match` with `*`
    wildcards, or a whole-name regex with match_pattern "regex"). A template with any other condition
    (match_mapping_type, path_match, unmatch, ...) cannot be judged here, so it counts as one that would; so does a
    `match` that is not one string (Elasticsearch 8.9 and later also take a list) or a regex Python cannot compile."""
    if set(body) - TEMPLATE_KEYS or 'match' not in body or not isinstance(body['match'], str):
        return True
    pattern = body['match']
    if body.get('match_pattern') == 'regex':
        try:
            return re.fullmatch(pattern, field) is not None
        except re.error:
            return True
    if body.get('match_pattern', 'simple') != 'simple':
        return True
    return re.fullmatch('.*'.join(re.escape(part) for part in pattern.split('*')), field) is not None


def template_problems(document) -> list[str]:
    """What keeps `document` from declaring q_4096_vec by the one new template; [] when nothing does."""
    try:
        mappings = document['mappings']
        templates = mappings['dynamic_templates']
        named = [entry(t) for t in templates]
    except (KeyError, TypeError, ValueError) as error:
        return [f'no readable mappings.dynamic_templates ({type(error).__name__}: {error})']
    problems = []
    if FIELD in (mappings.get('properties') or {}):
        problems.append(f'a property is named {FIELD}, so no template decides it')
    new = [i for i, (_, body) in enumerate(named) if body.get('match') == NEW]
    after = [i for i, (_, body) in enumerate(named) if body.get('match') == AFTER]
    if len(new) != 1:
        return problems + [f'{len(new)} template(s) match {NEW}, not exactly one']
    index = new[0]
    name, body = named[index]
    if name != 'dense_vector' or set(body) != {'match', 'mapping'} or body['mapping'] != MAPPING:
        problems.append(f'the {NEW} template is {json.dumps(templates[index], sort_keys=True)}, not '
                        f'{json.dumps({"dense_vector": {"match": NEW, "mapping": MAPPING}}, sort_keys=True)}')
    if after != [index - 1]:
        problems.append(f'the {NEW} template is not right after the one {AFTER} template')
    first = next((i for i, (_, b) in enumerate(named) if takes(b, FIELD)), None)
    if first != index:
        problems.append(f'the first template that would take {FIELD} is {named[first][0]!r} '
                        f'({json.dumps(named[first][1], sort_keys=True)[:120]}), not the {NEW} one')
    return problems


def locate(lines: list[str]) -> int:
    """The 0-based index of the line after the *_1536_vec block, which must be found exactly once."""
    size = len(ANCHOR)
    hits = [i for i in range(len(lines) - size + 1) if tuple(lines[i:i + size]) == ANCHOR]
    if len(hits) != 1:
        raise Refused(f'the {AFTER} block (its exact v0.27.3 lines) is found {len(hits)} time(s), not exactly once')
    return hits[0] + size


def verify(original: str, patched: str, at: int) -> None:
    """The second pass, independent of the insertion: the texts differ only by BLOCK inserted at line `at`, and
    the parsed documents only by its one template, right after *_1536_vec."""
    a, b = original.split('\n'), patched.split('\n')
    size = len(BLOCK)
    # The text: every line of the source, in order, and the block's lines at `at`, nothing else (so a change that
    # leaves the JSON equal, a space or a line end, is caught here).
    if b[:at] != a[:at] or b[at + size:] != a[at:] or b[at:at + size] != list(BLOCK):
        raise Refused(f'the result is not the source with the {NEW} block inserted at line {at + 1}')
    # The meaning: the same settings and mappings, and the same templates in the same order, but one, inserted
    # right after the *_1536_vec template (so a block put in the wrong place, or a wrong block, is caught here).
    try:
        before, after = json.loads(original), json.loads(patched)
        olds, news = before['mappings']['dynamic_templates'], after['mappings']['dynamic_templates']
        index = next(i for i, t in enumerate(olds) if entry(t)[1].get('match') == AFTER) + 1
        same = (set(after) == set(before) and after['settings'] == before['settings']
                and {k: v for k, v in after['mappings'].items() if k != 'dynamic_templates'}
                == {k: v for k, v in before['mappings'].items() if k != 'dynamic_templates'}
                and news[:index] + news[index + 1:] == olds
                and news[index] == {'dense_vector': {'match': NEW, 'mapping': MAPPING}})
    except (ValueError, KeyError, TypeError, IndexError, StopIteration) as error:
        raise Refused(f'the result cannot be compared with the source as JSON ({type(error).__name__})') from None
    if not same:
        raise Refused(f'the parsed result is not the source with the one template inserted after the {AFTER} one')


def insertion_diff(lines: list[str], at: int, context: int = 3) -> str:
    """The unified diff of BLOCK inserted before 0-based line `at`, with the hunk where the block really goes
    (difflib would show the same change one line later, since the block opens and closes as its neighbours do)."""
    whole = len(lines) - (1 if lines and lines[-1] == '' else 0)  # the '' after the last line end is no line
    start, end = max(0, at - context), min(whole, at + context)
    before, after = lines[start:at], lines[at:end]
    old = len(before) + len(after)
    return ''.join([f'--- a/{FILE}\n', f'+++ b/{FILE}\n',
                    f'@@ -{start + 1},{old} +{start + 1},{old + len(BLOCK)} @@\n']
                   + [f' {line}\n' for line in before] + [f'+{line}\n' for line in BLOCK]
                   + [f' {line}\n' for line in after])


def build(source: Path) -> dict:
    """Every check; returns what would be written, without writing."""
    data, text = read_text(source, '--source')
    source_sha = sha256_bytes(data)
    if source_sha != SOURCE_SHA256:
        raise Refused(f'the source\'s sha256 is {source_sha}, not v0.27.3\'s {SOURCE_SHA256} (the pinned image\'s '
                      'conf/mapping.json): this tool patches that file only')
    if NEW in text:
        raise Refused(f'the source already names {NEW}')
    try:
        document = json.loads(text)
    except ValueError as error:
        raise Refused(f'the source is not JSON ({error})') from None
    if not isinstance(document, dict):
        raise Refused('the source is not a JSON object')
    lines = text.split('\n')
    at = locate(lines)
    patched = '\n'.join(lines[:at] + list(BLOCK) + lines[at:])
    problems = template_problems(json.loads(patched))
    if problems:
        raise Refused('; '.join(problems))
    verify(text, patched, at)
    patched_bytes = patched.encode('utf-8')
    diff = insertion_diff(lines, at)
    record = {'file': FILE, 'source_sha256': source_sha, 'patched_sha256': sha256_bytes(patched_bytes),
              'inserted_lines': [at + 1, at + len(BLOCK)], 'after_template': AFTER,
              'template': {'dense_vector': {'match': NEW, 'mapping': MAPPING}}, 'field': FIELD}
    return {'patched': patched_bytes, 'diff': diff.encode('utf-8'), 'record': record}


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


def write(out: Path, result: dict, stale: list[Path]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for path in stale:
        path.unlink()
    written = []
    try:
        for name, data in ((OUT_JSON, result['patched']), (OUT_DIFF, result['diff']),
                           (OUT_RECORD, (json.dumps(result['record'], indent=1) + '\n').encode('utf-8'))):
            (out / name).write_bytes(data)
            written.append(out / name)
        if sha256_bytes((out / OUT_JSON).read_bytes()) != result['record']['patched_sha256']:
            raise Refused(f'the written {OUT_JSON} reads back with another sha256')
    except (OSError, Refused):
        for path in written:
            path.unlink(missing_ok=True)
        raise


def check(path: Path, stdout) -> int:
    try:
        data = path.read_bytes()
    except OSError as error:
        print(f'refused: cannot read --copy {path}: {type(error).__name__}', file=stdout)
        return 2
    bad = []

    def line(ok: bool, label: str, detail: str) -> None:
        print(f'{"ok  " if ok else "BAD "} {label}: {detail}', file=stdout)
        if not ok:
            bad.append(label.split(' ', 1)[0])

    digest = sha256_bytes(data)
    line(digest == PATCHED_SHA256, f'sha256 {digest}', 'the approved copy (v0.27.3\'s conf/mapping.json and one '
         'template)' if digest == PATCHED_SHA256 else f'not the approved {PATCHED_SHA256}')
    try:
        document = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        line(False, 'json', f'not readable ({type(error).__name__})')
    else:
        problems = template_problems(document)
        line(not problems, f'template {NEW}', f'dense_vector, dims 4096, cosine, index true, right after {AFTER}, '
             f'and the first template that takes {FIELD}' if not problems else '; '.join(problems))
    if bad:
        print(f'ES MAPPING NOT APPROVED: {path} ({", ".join(bad)})', file=stdout)
        return 1
    print(f'ES MAPPING OK: {path}', file=stdout)
    return 0


def main(argv: list[str] | None = None, *, stdout=None) -> int:
    stdout = stdout or sys.stdout
    ap = argparse.ArgumentParser(description='Add an explicit *_4096_vec template to a copy of RAGFlow v0.27.3\'s '
                                             'conf/mapping.json, or verify such a copy.', allow_abbrev=False)
    sub = ap.add_subparsers(dest='command', required=True)
    w = sub.add_parser('write', allow_abbrev=False, help='write the copy, its diff and its record')
    w.add_argument('--source', type=Path, required=True, help='conf/mapping.json as copied from the pinned image')
    w.add_argument('--out', type=Path, required=True, help='the folder to write into')
    w.add_argument('--replace', action='store_true', help='overwrite this tool\'s files in a non-empty --out')
    c = sub.add_parser('check', allow_abbrev=False, help='verify a copy')
    c.add_argument('--copy', type=Path, required=True, help='the mapping.json to verify')
    args = ap.parse_args(argv)
    if args.command == 'check':
        return check(args.copy, stdout)
    try:
        stale = prepare_out(args.out, args.source, args.replace)
        result = build(args.source)
        write(args.out, result, stale)
    except Refused as error:
        print(f'refused: {error}', file=stdout)
        return 2
    except OSError as error:
        print(f'refused: cannot write --out: {type(error).__name__}', file=stdout)
        return 2
    record = result['record']
    first, last = record['inserted_lines']
    print(f'source sha256  {record["source_sha256"]}', file=stdout)
    print(f'lines {first}-{last}: the {NEW} template (dense_vector, dims 4096, cosine, index true), after {AFTER}; '
          f'it decides {FIELD}', file=stdout)
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
