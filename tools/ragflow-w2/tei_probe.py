#!/usr/bin/env python3
"""tei_probe.py: wait until TEI serves the pinned model, and time it, without curl.

Runs in a python:3.12-slim container on ragbench-rf-net (compose service tei-probe):
  python3 -I -B /w2/tei_probe.py wait --model Qwen/Qwen3-Embedding-0.6B
      Polls GET /health until it answers 200 (the model loads over Docker Desktop's file share, so the
      first start is slow), then checks GET /info names the model, and that POST /embed of one word
      returns one vector. compose.yaml makes the server wait for this to exit 0
      (service_completed_successfully), because upstream gives TEI no health check
      (docker/docker-compose-base.yml:422-433) and the TEI image may hold no curl.
  python3 -I -B /w2/tei_probe.py time --in-dir /in [--target 15]
      The prepare step's batch probe. It takes the 16 longest article blocks of the upload set (a
      «### » heading and the lines up to the next heading: about one chunk each; a merged chunk adds
      under 32 tokens, group_chunker.py:22) and times POST /embed for batches of 16, 8, 4, 2 and 1 of
      them, twice each. The ingest sends at most 16 texts per TEI call whatever EMBEDDING_BATCH_SIZE is
      (BuiltinEmbed.encode splits at 16, rag/llm/embedding_model.py:245-255), and each call has a
      30-second client timeout with no retry (embedding_model.py:1245-1249). So it picks the largest
      batch whose slowest call stays under --target seconds, and prints EMBEDDING_BATCH_SIZE=<n>.
The body is the one RAGFlow sends, {"inputs": [...]}, with no instruction prefix (embedding_model.py:1246).
Prints status codes, sizes and times only, never a text. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SIZES = (16, 8, 4, 2, 1)


def call(url: str, body: dict | None = None, timeout: float = 120.0) -> tuple[int, object, float]:
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'},
                                 method='POST' if body is not None else 'GET')
    start = time.monotonic()
    try:
        with OPENER.open(req, timeout=timeout) as resp:
            raw, status = resp.read(), resp.status
    except urllib.error.HTTPError as error:
        raw, status = error.read(), error.code
    except (urllib.error.URLError, OSError):  # not reachable yet, or the call timed out: status 0
        raw, status = b'', 0
    elapsed = time.monotonic() - start
    try:
        return status, json.loads(raw.decode('utf-8')), elapsed
    except (UnicodeDecodeError, ValueError):
        return status, None, elapsed


def article_blocks(in_dir: Path) -> list[str]:
    blocks = []
    for path in sorted(in_dir.glob('*.md')):
        current: list[str] = []
        for line in path.read_text(encoding='utf-8').split('\n'):
            if line.startswith('#'):
                if current and current[0].startswith('### '):
                    blocks.append('\n'.join(current) + '\n')
                current = [line]
            elif line.strip() and current:
                current.append(line)
        if current and current[0].startswith('### '):
            blocks.append('\n'.join(current) + '\n')
    return blocks


def choose(timings: dict[int, tuple[bool, float]], target: float) -> int | None:
    """The largest batch size whose calls all succeeded and whose slowest call stayed under target."""
    good = [size for size, (ok, slowest) in timings.items() if ok and slowest < target]
    return max(good) if good else None


def wait(args) -> int:
    deadline = time.monotonic() + args.timeout
    while True:
        status, _, _ = call(args.url + '/health', timeout=10)
        if status == 200:
            break
        if time.monotonic() > deadline:
            print(f'TEI did not answer /health with 200 within {args.timeout:.0f} s', file=sys.stderr)
            return 1
        time.sleep(5)
    status, info, _ = call(args.url + '/info', timeout=30)
    model_id = str((info or {}).get('model_id', '')) if isinstance(info, dict) else ''
    if status != 200 or not model_id.rstrip('/').endswith(args.model):
        print(f'TEI /info: HTTP {status}, model_id {model_id!r}, not {args.model}', file=sys.stderr)
        return 1
    status, vectors, seconds = call(args.url + '/embed', {'inputs': ['test']}, timeout=60)
    if status != 200 or not isinstance(vectors, list) or len(vectors) != 1:
        print(f'TEI /embed: HTTP {status}, no single vector', file=sys.stderr)
        return 1
    print(f'TEI ready: {model_id}, max_input_length {info.get("max_input_length")}, '
          f'one vector of {len(vectors[0])} dimensions in {seconds:.2f} s')
    return 0


def time_batches(args) -> int:
    blocks = sorted(article_blocks(args.in_dir), key=len, reverse=True)[:max(SIZES)]
    if len(blocks) < max(SIZES):
        print(f'only {len(blocks)} article blocks found in {args.in_dir}', file=sys.stderr)
        return 2
    print(f'the {len(blocks)} longest article blocks: {len(blocks[0])} to {len(blocks[-1])} characters')
    timings = {}
    for size in SIZES:
        results = [call(args.url + '/embed', {'inputs': blocks[:size]}) for _ in range(args.repeat)]
        ok = all(status == 200 and isinstance(v, list) and len(v) == size for status, v, _ in results)
        slowest = max(seconds for _, _, seconds in results)
        timings[size] = (ok, slowest)
        print(f'batch {size:2d}: HTTP {",".join(str(s) for s, _, _ in results)}, slowest {slowest:.2f} s')
    size = choose(timings, args.target)
    if size is None:
        print(f'no batch size stays under {args.target} s; even one text is too slow for the 30 s timeout',
              file=sys.stderr)
        return 1
    print(f'EMBEDDING_BATCH_SIZE={size}')
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Wait for TEI and time it.')
    ap.add_argument('--url', default='http://ragbench-rf-tei:80')
    sub = ap.add_subparsers(dest='step', required=True)
    w = sub.add_parser('wait')
    w.add_argument('--model', required=True)
    w.add_argument('--timeout', type=float, default=3600.0, help='seconds (default: %(default)s)')
    t = sub.add_parser('time')
    t.add_argument('--in-dir', required=True, type=Path)
    t.add_argument('--target', type=float, default=15.0, help='seconds per call (default: %(default)s)')
    t.add_argument('--repeat', type=int, default=2)
    args = ap.parse_args(argv)
    return wait(args) if args.step == 'wait' else time_batches(args)


if __name__ == '__main__':
    sys.exit(main())
