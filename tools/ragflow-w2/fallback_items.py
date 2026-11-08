#!/usr/bin/env python3
"""fallback_items.py: which W2 items were answered only by RAGFlow's dense-only fallback.

Usage (on the host, from this folder):
  python -I -B fallback_items.py --results <out>/w2-results-<arm>.jsonl \
      --server-log <logs>/server-<engine>-<arm>.log --run-log <out>/run-<arm>.log \
      --out <out>/w2-fallback-<arm>.json

Why. POST /api/v1/retrieval does not pass allow_dense_fallback (api/apps/restful_apis/chunk_api.py:553-571),
so the default True applies (rag/nlp/search.py:737). When the hybrid search finds nothing, Dealer.search
runs a dense-only search instead and returns what it finds (search.py:350-407). Walid's agent passes
allow_dense_fallback=False (agent/tools/retrieval.py:228), so for those items it would return nothing.
The fallback leaves no trace in the API answer. It is visible only as a root-logger DEBUG line:
  «Dealer.search dense-only fallback after empty initial search»   (search.py:357)
  «Dealer.search dense-only fallback after empty hybrid retries»   (search.py:394)
The server logs them only with LOG_LEVELS=root=DEBUG (common/log_utils.py:50-70), as compose.yaml sets.

How it matches log lines to items.
  1. The anchors. Every retrieval call logs «[Search] page=…» at its start (search.py:776), through the
     same root logger at the same level. Nothing else logs it: listing chunks uses Dealer.search but
     not Dealer.retrieval. RAGFlow's log format carries the process id (common/log_utils.py:27).
  2. The segments. A fallback line belongs to the nearest anchor BEFORE it from the same process, in
     the order the lines reached the log. run_w1.py sends one request at a time and waits for the
     answer (run_w1.py:367-380), so within one process the lines of one request are not interleaved
     with another's.
  3. Anchors to items. Only anchors inside the run's time (the results header's started_at to
     finished_at, widened by 1 s before and 2 s after) count. If their number equals the number of
     requests planned, the k-th anchor is the k-th request of run_w1.py's plan (every item on the
     first field, then every item on the next, run_w1.py:505). If the number differs (a retried
     request, or one refused before retrieval), the anchors are placed by time instead, from
     --run-log (timed_run.py's stamps): request k ran between the stamp of progress line k-1 and that
     of line k, and the last anchor in that span is the attempt whose answer run_w1.py kept. Every
     answered request must then have an anchor in its span, and no anchor may lie outside every span.
  4. The cross-check. Every anchor must also lie inside its request's span. Any disagreement stops
     the tool: it writes nothing rather than guess. --run-log is required: without its stamps an
     equal count could hide two errors that cancel (a request refused before retrieval plus a
     retried one) and shift the mapping by one.
An item is listed when its anchor's segment holds a fallback line AND its row returned at least one
chunk. A fallback that returned nothing is reported, not listed: the item is empty either way.

What it cannot prove.
  - That no other client called retrieval during the run. The stack is sealed (one account, one key,
    no published port), and an extra call would add an anchor and stop step 3 when counted, but a
    concurrent call that happened to replace a retried one would not be noticed.
  - That every line reached the log. compose.yaml caps the server's json-file log at 20 files of
    100 MB, and `docker logs` reads the rotated files too, so a line is lost only after that budget
    is spent. Rotation drops the oldest lines first, so a fallback line cannot rotate away without
    the anchor before it, and a lost anchor of an answered request stops the tool (step 3). A
    fallback line lost some other way would go unnoticed.
  - Anything about the lexical retries: the second hybrid search with min_match 0.1 (search.py:378-391)
    logs nothing of its own, so «answered by the relaxed hybrid retry» cannot be told apart.
  - That the time stamps are exact. Docker stamps a line when it reads it; the runner stamps when its
    pipe delivers. Both read the same VM clock, but a delay longer than one request would misplace an
    anchor; the cross-check then stops the tool.

Writes --out as {"<field>": [item ids, in plan order], ...} with one key per field the run sent, and
a report beside it (<out stem>.report.json) with the counts, the mapping used and the sha256 of every
input. Exit 0 when written, 1 when the matching cannot be trusted (nothing written), 2 on bad input.
Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

DOCKER_LINE = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z (.*)$')
RAGFLOW_LINE = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}\s+(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+'
                          r'(\d+)\s(.*)$')
STAMPED_LINE = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z\t(.*)$')
PROGRESS = re.compile(r'^(\d+)/(\d+) (\S+) (\S+): ')
ANCHOR = '[Search] page='
FALLBACK = 'Dealer.search dense-only fallback'
WRITTEN, UNTRUSTED, BAD_INPUT = 0, 1, 2


class BadInput(Exception):
    pass


class Untrusted(Exception):
    pass


class LogLine(NamedTuple):
    index: int
    ts: datetime
    pid: int
    msg: str


def parse_stamp(seconds: str, fraction: str | None) -> datetime:
    micro = int((fraction or '0')[:6].ljust(6, '0'))
    return datetime.strptime(seconds, '%Y-%m-%dT%H:%M:%S').replace(microsecond=micro, tzinfo=timezone.utc)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_results(path: Path) -> tuple[dict, list[dict]]:
    try:
        lines = [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
    except (OSError, ValueError):
        raise BadInput(f'cannot read {path} as JSON lines') from None
    if not lines or not isinstance(lines[0], dict) or lines[0].get('w1') != 1:
        raise BadInput(f'{path.name} does not start with a run_w1.py header')
    header, rows = lines[0], lines[1:]
    counts = header.get('counts') or {}
    if not header.get('finished_at') or counts.get('not_run') != 0 or len(rows) != counts.get('planned'):
        raise BadInput(f'{path.name} is not a complete run (finished_at, counts.not_run, row count)')
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not isinstance(row.get('chunks'), list):
            raise BadInput(f'{path.name}: a row lacks id or chunks')
    return header, rows


def read_server_log(path: Path) -> list[LogLine]:
    out = []
    try:
        handle = open(path, encoding='utf-8', errors='replace')
    except OSError:
        raise BadInput(f'cannot read {path}') from None
    with handle:
        for index, raw in enumerate(handle):
            m = DOCKER_LINE.match(raw.rstrip('\r\n'))
            if not m:
                continue
            r = RAGFLOW_LINE.match(m.group(3))
            if not r:
                continue  # tracebacks, banners and other lines without RAGFlow's prefix
            out.append(LogLine(index, parse_stamp(m.group(1), m.group(2)), int(r.group(1)), r.group(2)))
    return out


def read_run_log(path: Path, rows: list[dict]) -> list[datetime]:
    """Stamps: [start, end of request 1, ..., end of request n]."""
    start, ends = None, {}
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        raise BadInput(f'cannot read {path}') from None
    for raw in lines:
        m = STAMPED_LINE.match(raw)
        if not m:
            continue
        ts, text = parse_stamp(m.group(1), m.group(2)), m.group(3)
        if text.startswith('# timed_run start') and start is None:
            start = ts
            continue
        p = PROGRESS.match(text)
        if p:
            number = int(p.group(1))
            if number in ends:
                raise BadInput(f'{path.name}: progress line {number} appears twice')
            row = rows[number - 1] if 0 < number <= len(rows) else None
            if row is None or row.get('field') != p.group(3) or row.get('id') != p.group(4):
                raise BadInput(f'{path.name}: progress line {number} does not match row {number} of the results')
            ends[number] = ts
    if start is None or sorted(ends) != list(range(1, len(rows) + 1)):
        raise BadInput(f'{path.name} lacks the start line or a progress line for every request')
    return [start] + [ends[n] for n in range(1, len(rows) + 1)]


def segments(lines: list[LogLine], window: tuple[datetime, datetime]) -> tuple[list[LogLine], dict[int, bool]]:
    """The anchors inside the window, in log order, and whether each anchor's segment holds a fallback."""
    lo, hi = window
    inside = [x for x in lines if lo <= x.ts <= hi]
    anchors = [x for x in inside if x.msg.startswith(ANCHOR)]
    last_anchor_of_pid: dict[int, LogLine] = {}
    fell_back = {a.index: False for a in anchors}
    for x in inside:
        if x.msg.startswith(ANCHOR):
            last_anchor_of_pid[x.pid] = x
        elif x.msg.startswith(FALLBACK):
            owner = last_anchor_of_pid.get(x.pid)
            if owner is None:
                raise Untrusted(f'a fallback line (log line {x.index + 1}) has no retrieval call before it '
                                f'in process {x.pid}')
            fell_back[owner.index] = True
    return anchors, fell_back


def by_time(anchors: list[LogLine], rows: list[dict], stamps: list[datetime]) -> tuple[list[LogLine | None], list[str]]:
    chosen, retried = [], []
    for k, row in enumerate(rows, start=1):
        lo, hi = stamps[k - 1], stamps[k]
        inside = [a for a in anchors if lo < a.ts <= hi]
        if not inside:
            if row.get('status') == 'ok':
                raise Untrusted(f'request {k} ({row["field"]} {row["id"]}) was answered, but no retrieval call '
                                'was logged during it')
            chosen.append(None)
            continue
        if len(inside) > 1:
            retried.append(f'{row["field"]}:{row["id"]}')
        chosen.append(inside[-1])
    placed = {a.index for a in chosen if a is not None}
    stray = [a for a in anchors if a.index not in placed and not any(
        stamps[k - 1] < a.ts <= stamps[k] for k in range(1, len(rows) + 1))]
    if stray:
        raise Untrusted(f'{len(stray)} retrieval call(s) fall outside every request of this run')
    return chosen, retried


def write_json(path: Path, data) -> None:
    partial = path.with_name(path.name + '.partial')
    with open(partial, 'w', encoding='utf-8', newline='\n') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
        handle.write('\n')
    os.replace(partial, path)


def main(argv: list[str] | None = None, *, stdout=None) -> int:
    stdout = stdout or sys.stdout

    def say(line: str) -> None:
        print(line, file=stdout)

    ap = argparse.ArgumentParser(description='List the W2 items answered only by the dense-only fallback.')
    ap.add_argument('--results', required=True, type=Path)
    ap.add_argument('--server-log', required=True, type=Path, help='docker logs --timestamps of the server')
    ap.add_argument('--run-log', type=Path, help="timed_run.py's log of the same run (required)")
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args(argv)
    report_path = args.out.with_name(args.out.stem + '.report.json')
    try:
        if args.run_log is None:
            raise BadInput("give --run-log (timed_run.py's log of the same run): without its stamps an equal count "
                           'can hide a refused request plus a retried one and shift the mapping by one')
        if args.out.exists() or report_path.exists():
            raise BadInput(f'{args.out.name} or {report_path.name} already exists')
        header, rows = read_results(args.results)
        lines = read_server_log(args.server_log)
        stamps = read_run_log(args.run_log, rows)
        started = datetime.fromisoformat(header['started_at'])
        finished = datetime.fromisoformat(header['finished_at'])
        window = (started - timedelta(seconds=1), finished + timedelta(seconds=2))
        anchors, fell_back = segments(lines, window)
        if not anchors:
            raise Untrusted('no «[Search] page=» line in the run window: the server was not logging at DEBUG, '
                            'or the log does not cover the run')
        retried: list[str] = []
        if len(anchors) == len(rows):
            mapping, chosen = 'sequence', list(anchors)
            for k, (row, a) in enumerate(zip(rows, chosen), start=1):
                if not stamps[k - 1] < a.ts <= stamps[k]:
                    raise Untrusted(f'retrieval call {k} (log line {a.index + 1}) was logged outside the time '
                                    f'of request {k} ({row["field"]} {row["id"]})')
        else:
            mapping, (chosen, retried) = 'time', by_time(anchors, rows, stamps)
    except BadInput as error:
        say(f'refused: {error}')
        return BAD_INPUT
    except Untrusted as error:
        say(f'stopped, nothing written: {error}')
        return UNTRUSTED

    fields = list(header.get('fields') or dict.fromkeys(r['field'] for r in rows))
    only, empty = {f: [] for f in fields}, {f: [] for f in fields}
    for row, anchor in zip(rows, chosen):
        if anchor is None or not fell_back.get(anchor.index):
            continue
        target = only if row.get('status') == 'ok' and row['chunks'] else empty
        target.setdefault(row['field'], []).append(row['id'])
    write_json(args.out, only)
    write_json(report_path, {
        'w2_fallback': 1, 'mapping': mapping, 'requests': len(rows), 'retrieval_calls_logged': len(anchors),
        'processes': sorted({a.pid for a in anchors}), 'time_cross_check': True,
        'log_window': [window[0].isoformat(), window[1].isoformat()],
        'fallback_only': only, 'fallback_returned_nothing': empty, 'retried': retried,
        'results_sha256': sha256_of(args.results), 'server_log_sha256': sha256_of(args.server_log),
        'run_log_sha256': sha256_of(args.run_log)})
    for f in fields:
        say(f'{f}: {len(only[f])} item(s) answered only by the dense-only fallback'
            + (f', {len(empty[f])} more where it returned nothing' if empty[f] else ''))
    say(f'mapping by {mapping}; {len(anchors)} retrieval calls for {len(rows)} requests; '
        'every call checked against the request times')
    say(f'written: {args.out} and {report_path.name}')
    return WRITTEN


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
