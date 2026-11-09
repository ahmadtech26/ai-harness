#!/usr/bin/env python3
"""check_tei_wait.py: show that the server's own Python loads the patched TEI waits, and that the server runs
with the operational settings the owner set.

Runs INSIDE the running server container, as predict_chunks.py does:
  docker exec ragbench-rf-server /ragflow/.venv/bin/python -B /w2/check_tei_wait.py --patch /patch/patch.json \
      --max-concurrent-tasks 1 --embedding-batch-size 1
Not `python -I`: that drops the image's PYTHONPATH=/ragflow/ (Dockerfile:282). This script puts /ragflow first
on sys.path itself and takes its own folder off it. `-B` writes no .pyc.

Spec: .hq/docs/specs/spec-rag-system.md, «Owner decision 2026-11-08 (later): raise RAGFlow's wait on the
embedder; run both engines»: «the run checks that the code the server loaded holds 900». What it checks, one
printed line each:
  1. patch.json, the record patch_tei_wait.py wrote, mounted read-only at /patch: the file, a wait_s that is a
     whole number above 30, two 64-hex sha256, and that it is the approved patch: image_sha256, patched_sha256
     and wait_s equal --expect-image-sha256, --expect-patched-sha256 and --expect-wait, whose defaults are the
     owner's approved change (APPROVED below: the pinned image's file c2e46e1c…, read in the image on
     2026-11-08; the patched sha256 90f3a20d… the dry run wrote from those bytes; 900 s). A record of any other
     source or wait is refused (exit 2) before anything is imported, so a patch made from an edited file fails.
  2. The module the import system resolves. `import rag.llm.embedding_model`, which is how rag/llm/__init__.py
     loads it when the server starts (:168-170, importlib.import_module), must give
     /ragflow/rag/llm/embedding_model.py, read by a SourceFileLoader, with no .pyc where the import system would
     look for one. The pinned image ships no __pycache__ under /ragflow and sets PYTHONDONTWRITEBYTECODE=1
     (README, «## TEI wait patch»), so a .pyc there means something changed.
  3. That file's sha256 equals patch.json's patched_sha256.
  4. The loaded HuggingFaceEmbed.encode and encode_queries are the code compiled from those bytes now.
  5. Their own code constants hold wait_s, and no 30 (method_problems below).
  6. The environment of this process, which is the container's, and of every running task executor and API
     server (/proc/<pid>/environ): ENABLE_TIMEOUT_ASSERTION is absent, since it would arm the @timeout limits
     (common/connection_utils.py:30-100, the gates at :52 and :70); MAX_CONCURRENT_TASKS and EMBEDDING_BATCH_SIZE equal the values given,
     read the way rag/svr/task_executor_limiter.py:20 and common/settings.py:517 read them (defaults 5 and 16);
     and at least one task executor is running (docker/entrypoint.sh:223-233).

What it cannot prove. It imports the module afresh; it cannot read the code inside processes already running.
The bridge is the bind mount: read-only, made when the container was created, before any process in it started,
and holding the bytes whose sha256 step 3 checks. Run it again after the ingest to show those bytes did not change.

Exit 0 every check passed, 1 a check failed, 2 bad input. Prints no secret: only the variables named above.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.machinery
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

RAGFLOW_ROOT = '/ragflow'
MODULE = 'rag.llm.embedding_model'
RELATIVE = 'rag/llm/embedding_model.py'
CLASS = 'HuggingFaceEmbed'
METHODS = ('encode', 'encode_queries')
SHIPPED = 30
HEX64 = re.compile(r'[0-9a-f]{64}')
FORBIDDEN = 'ENABLE_TIMEOUT_ASSERTION'
SETTINGS = (('MAX_CONCURRENT_TASKS', '5'), ('EMBEDDING_BATCH_SIZE', '16'))  # name, the server's default
ROLES = (('task executor', 'rag/svr/task_executor.py'), ('API server', 'api/ragflow_server.py'))
OK, FAILED, BAD_INPUT = 0, 1, 2
# The owner's approved change (README, «## TEI wait patch»): the pinned image's file, the patched file P9 writes
# from those bytes (the dry run's), and the wait.
APPROVED = {'image_sha256': 'c2e46e1cb5d128122a48b8283d135b81321441655dbd9c22c9ecd8035a6c0536',
            'patched_sha256': '90f3a20d0bfab00175670c90c93e410592029bbf7b75b7aadfe944f71c74acab',
            'wait_s': 900}


class BadInput(Exception):
    pass


def numbers(code) -> list:
    """The ints and floats among a code object's own constants (bool excluded; nested code objects not searched:
    Python 3.11 compiles encode's list comprehension as one, 3.12 and later inline it, PEP 709)."""
    return [c for c in code.co_consts if type(c) in (int, float)]


def one_method_problems(cls, name: str, wait: int) -> list[str]:
    code = getattr(vars(cls).get(name), '__code__', None)
    if code is None:
        return [f'{cls.__name__}.{name} is missing']
    found, problems = numbers(code), []
    if not any(type(n) is int and n == wait for n in found):
        problems.append(f'{cls.__name__}.{name} does not hold {wait} among its constants {found}')
    if any(n == SHIPPED for n in found):
        problems.append(f'{cls.__name__}.{name} still holds {SHIPPED} among its constants {found}')
    return problems


def method_problems(cls, wait: int) -> list[str]:
    """Why cls.encode and cls.encode_queries do not hold the wait; empty when both hold `wait` and no 30."""
    return [p for name in METHODS for p in one_method_problems(cls, name, wait)]


def compiled_methods(data: bytes, filename: str) -> dict:
    """{method: code} for the class's methods, from compiling the file's bytes as the import system does
    (importlib's source_to_code: compile(data, path, 'exec', dont_inherit=True))."""
    module = compile(data, filename, 'exec', dont_inherit=True)
    bodies = [c for c in module.co_consts if getattr(c, 'co_name', None) == CLASS]
    if len(bodies) != 1:
        return {}
    return {c.co_name: c for c in bodies[0].co_consts if getattr(c, 'co_name', None) in METHODS}


def read_patch(path: Path, expect: dict | None = None) -> dict:
    """patch.json, checked. `expect` ({image_sha256, patched_sha256, wait_s}; APPROVED when None) is the patch the
    record must describe."""
    expect = APPROVED if expect is None else expect
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        raise BadInput(f'cannot read {path} as JSON') from None
    if not isinstance(record, dict):
        raise BadInput(f'{path.name} is not a JSON object')
    wait = record.get('wait_s')
    if type(wait) is not int or wait <= SHIPPED:
        raise BadInput(f'{path.name}: wait_s must be a whole number above {SHIPPED}')
    for name in ('image_sha256', 'patched_sha256'):
        if not isinstance(record.get(name), str) or not HEX64.fullmatch(record[name]):
            raise BadInput(f'{path.name}: {name} must be 64 lower-case hex characters')
    if record.get('file') != RELATIVE:
        raise BadInput(f'{path.name}: file must be {RELATIVE}')
    for name in ('image_sha256', 'patched_sha256', 'wait_s'):
        if record[name] != expect[name]:
            raise BadInput(f'{path.name}: {name} is {record[name]}, not the approved {expect[name]}: this is not '
                           'the patch the owner approved')
    return record


def processes(proc: Path) -> list[tuple[str, int, dict]]:
    """(role, pid, environment) of each task executor and API server, from /proc. Unreadable entries are skipped:
    a process may end while it is read."""
    found = []
    for entry in (sorted(proc.iterdir(), key=lambda p: p.name) if proc.is_dir() else []):
        if not entry.name.isdigit():
            continue
        try:
            argv = [a.decode('utf-8', 'replace') for a in (entry / 'cmdline').read_bytes().split(b'\0') if a]
            raw = (entry / 'environ').read_bytes()
        except OSError:
            continue
        role = next((name for name, script in ROLES
                     if any(a == script or a.endswith('/' + script) for a in argv)), None)
        if role is None:
            continue
        environ = dict(item.split('=', 1) for item in raw.decode('utf-8', 'replace').split('\0') if '=' in item)
        found.append((role, int(entry.name), environ))
    return found


def environment_problems(environ, expected: dict, where: str) -> list[str]:
    problems = []
    if FORBIDDEN in environ:
        problems.append(f'{where}: {FORBIDDEN} is set; it must stay unset')
    for name, default in SETTINGS:
        value = environ.get(name, default)
        if value.strip() != str(expected[name]):
            problems.append(f'{where}: {name} is {value!r}{" (the default)" if name not in environ else ""}, '
                            f'not {expected[name]}')
    return problems


def main(argv: list[str] | None = None, *, stdout=None) -> int:
    stdout = stdout or sys.stdout
    real_stdout, sys.stdout = sys.stdout, sys.stderr  # anything RAGFlow prints while importing stays off stdout

    def say(line: str) -> None:
        print(line, file=stdout, flush=True)

    try:
        ap = argparse.ArgumentParser(description='Check the TEI waits the server\'s Python loads.')
        ap.add_argument('--patch', required=True, type=Path, help='patch.json, as mounted (/patch/patch.json)')
        ap.add_argument('--max-concurrent-tasks', required=True, type=int)
        ap.add_argument('--embedding-batch-size', required=True, type=int)
        ap.add_argument('--expect-image-sha256', default=APPROVED['image_sha256'],
                        help='sha256 of the image file the patch was made from (default: the approved one)')
        ap.add_argument('--expect-patched-sha256', default=APPROVED['patched_sha256'],
                        help='sha256 of the patched file (default: the approved one)')
        ap.add_argument('--expect-wait', type=int, default=APPROVED['wait_s'], help='seconds (default: %(default)s)')
        ap.add_argument('--root', default=RAGFLOW_ROOT, help='RAGFlow\'s code (default: %(default)s)')
        ap.add_argument('--proc', type=Path, default=Path('/proc'), help=argparse.SUPPRESS)
        args = ap.parse_args(argv)
        try:
            record = read_patch(args.patch, {'image_sha256': args.expect_image_sha256,
                                             'patched_sha256': args.expect_patched_sha256, 'wait_s': args.expect_wait})
        except BadInput as error:
            say(f'refused: {error}')
            return BAD_INPUT
        wait = record['wait_s']
        expected = {'MAX_CONCURRENT_TASKS': args.max_concurrent_tasks,
                    'EMBEDDING_BATCH_SIZE': args.embedding_batch_size}
        problems = []

        def check(ok: bool, good: str, bad: str) -> bool:
            say(f'{"ok  " if ok else "BAD "} {good if ok else bad}')
            if not ok:
                problems.append(bad)
            return ok

        say(f'ok   patch.json: {record["file"]}, wait_s {wait}, image_sha256 {record["image_sha256"]}, '
            f'patched_sha256 {record["patched_sha256"]}: the approved patch')

        here = os.path.dirname(os.path.abspath(__file__))
        sys.path[:] = [p for p in sys.path if os.path.abspath(p or '.') != here]
        sys.path.insert(0, args.root)
        want = os.path.join(args.root, *RELATIVE.split('/'))
        try:
            module = importlib.import_module(MODULE)
        except Exception as error:  # noqa: BLE001 - any import failure is reported, not raised
            check(False, '', f'import {MODULE} failed: {type(error).__name__}: {str(error)[:200]}')
            module = None
        if module is not None:
            spec = module.__spec__
            origin = spec.origin or ''
            cached = (spec.cached or importlib.util.cache_from_source(origin)) if origin else ''
            source_loader = isinstance(spec.loader, importlib.machinery.SourceFileLoader)
            check(os.path.realpath(origin) == os.path.realpath(want) and source_loader,
                  f'module: {origin} (read from source)',
                  f'the import system resolves {MODULE} to {origin!r} via {type(spec.loader).__name__}, '
                  f'not {want} from source')
            check(not (cached and os.path.exists(cached)), f'no .pyc at {cached}',
                  f'a .pyc exists at {cached}: the import system may read it instead of the mounted file')
            try:
                data = Path(origin).read_bytes()
            except OSError:
                data = b''
            sha = hashlib.sha256(data).hexdigest()
            check(sha == record['patched_sha256'], f'sha256 {sha}: the patched file',
                  f'the module file\'s sha256 is {sha}, not patch.json\'s {record["patched_sha256"]}')
            cls = getattr(module, CLASS, None)
            if check(isinstance(cls, type), f'{CLASS} found', f'the module has no class {CLASS}'):
                try:
                    fresh = compiled_methods(data, origin)
                except (SyntaxError, ValueError):
                    fresh = {}
                for name in METHODS:
                    code = getattr(vars(cls).get(name), '__code__', None)
                    check(code is not None and fresh.get(name) == code,
                          f'{CLASS}.{name} (line {getattr(code, "co_firstlineno", "?")}) is the code compiled '
                          'from that file now',
                          f'the loaded {CLASS}.{name} is not the code compiled from the file now')
                    mine = one_method_problems(cls, name, wait)
                    check(not mine, f'{CLASS}.{name} holds {wait}, not {SHIPPED}: constants '
                                    f'{numbers(code) if code else []}', '; '.join(mine))

        check(not environment_problems(os.environ, expected, 'this container'),
              f'this container: {FORBIDDEN} unset, '
              + ', '.join(f'{n}={os.environ.get(n, d)}' for n, d in SETTINGS),
              '; '.join(environment_problems(os.environ, expected, 'this container')))
        running = processes(args.proc)
        check(any(role == 'task executor' for role, _, _ in running),
              f'{sum(role == "task executor" for role, _, _ in running)} task executor(s) and '
              f'{sum(role == "API server" for role, _, _ in running)} API server(s) running',
              'no task executor is running')
        for role, pid, environ in running:
            found = environment_problems(environ, expected, f'{role} pid {pid}')
            check(not found, f'{role} pid {pid}: {FORBIDDEN} unset, '
                  + ', '.join(f'{n}={environ.get(n, d)}' for n, d in SETTINGS), '; '.join(found))

        if problems:
            say(f'TEI WAIT NOT SHOWN: {len(problems)} check(s) failed')
            return FAILED
        say(f'TEI WAIT LOADED: {CLASS}.encode and encode_queries wait {wait} s; '
            + ', '.join(f'{n} {expected[n]}' for n, _ in SETTINGS) + f'; {FORBIDDEN} unset')
        return OK
    finally:
        sys.stdout = real_stdout


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
