#!/usr/bin/env python3
"""w2_check.py: compare the chunks RAGFlow stored with the chunks its own chunker predicts.

Usage (on the host, from this folder):
  python -I -B w2_check.py --predicted <out>/predicted-chunks.jsonl --dumped <out>/chunks.jsonl \
      --manifest <out>/w2-manifest.json --ingest-state <out>/ingest-state.json [--show 3]

--predicted  predict_chunks.py's output: one header line {"w2_predict": 1, ...}, then one line per chunk
             {"file": "<slug>.md", "i": <n>, "tokens": <n>, "text": "<chunk text>"}.
--dumped     rf_ingest.py's chunks.jsonl: one line per stored chunk
             {"document_name", "document_id", "chunk_id", "content", ...}.
--manifest   the W2 manifest rf_ingest.py wrote. Updated in place (atomically): predicted_chunk_count is
             set to the predicted total, and all_match to true ONLY when everything matches; any other
             outcome sets all_match to false.
--ingest-state  rf_ingest.py's ingest-state.json (required): the name and sha256 of every uploaded file.

What it compares, per law (file) and in total:
  - the number of chunks predicted and stored;
  - the chunk texts, byte for byte, as multisets. Order is not compared: RAGFlow's pipeline path never
    sets chunk_order_int (rag/svr/task_executor.py:919-951 sets no order field), and the chunk listing
    sorts on it (api/apps/restful_apis/chunk_api.py:631-640; rag/nlp/search.py:302-306), so the listing
    order of pipeline chunks is not the file order. A text the predictor gives twice inside one file
    cannot match: see compare().
  - that the predictor read 22 files, and the manifest's own facts: document_count 22 and chunk_count
    equal to the stored total. (The manifest holds no document names; the names are compared law by
    law above, and with the ingest state below.)
  - that the predictor read the same canvas as rf_ingest.py imported (canvas_sha256), and the same
    files, by name and sha256, as rf_ingest.py uploaded (the ingest state).

It prints one line per law, then ALL MATCH or the first differences. Exit 0 on ALL MATCH, 1 when
something differs, 2 when an input cannot be read. It also writes w2-check.json beside the manifest
(counts, sha256 of both inputs, the verdict). Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_DOCUMENTS = 22
MATCH, DIFFER, BAD_INPUT = 0, 1, 2


class BadInput(Exception):
    """An input file is missing or not in the expected shape."""


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        with open(path, encoding='utf-8') as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    raise BadInput(f'{path.name} line {number} is not JSON') from None
                if not isinstance(row, dict):
                    raise BadInput(f'{path.name} line {number} is not a JSON object')
                rows.append(row)
    except OSError as error:
        raise BadInput(f'cannot read {path}: {type(error).__name__}') from None
    return rows


def read_predicted(path: Path) -> tuple[dict, dict[str, list[str]]]:
    rows = read_jsonl(path)
    if not rows or rows[0].get('w2_predict') != 1:
        raise BadInput(f'{path.name} does not start with the predict_chunks.py header line')
    header, by_file = rows[0], {}
    for row in rows[1:]:
        name, text = row.get('file'), row.get('text')
        if not isinstance(name, str) or not isinstance(text, str):
            raise BadInput(f'{path.name}: a chunk line lacks "file" or "text"')
        by_file.setdefault(name, []).append(text)
    for name in header.get('files', {}):
        by_file.setdefault(name, [])  # a file that yields no chunk still counts as a file
    return header, by_file


def read_dumped(path: Path) -> dict[str, list[str]]:
    by_file: dict[str, list[str]] = {}
    for row in read_jsonl(path):
        name, text = row.get('document_name'), row.get('content')
        if not isinstance(name, str) or not isinstance(text, str):
            raise BadInput(f'{path.name}: a chunk line lacks "document_name" or "content"')
        by_file.setdefault(name, []).append(text)
    return by_file


def show(text: str, limit: int = 160) -> str:
    shown = json.dumps(text, ensure_ascii=False)
    return shown if len(shown) <= limit else shown[:limit] + f'... ({len(text)} chars)'


def first_line(text: str) -> str:
    return text.split('\n', 1)[0]


def describe_differences(only_predicted: list[str], only_stored: list[str], limit: int) -> list[str]:
    """Pair texts that share a first line (the heading) and say where they part; list the rest."""
    lines, stored_by_head = [], {}
    for text in only_stored:
        stored_by_head.setdefault(first_line(text), []).append(text)
    paired = 0
    for text in only_predicted:
        if len(lines) >= limit:
            break
        candidates = stored_by_head.get(first_line(text))
        if candidates:
            other = candidates.pop(0)
            at = next((i for i, (a, b) in enumerate(zip(text, other)) if a != b), min(len(text), len(other)))
            lines.append(f'    same first line {show(first_line(text), 80)}: predicted {len(text)} chars, stored '
                         f'{len(other)} chars, first difference at char {at}: predicted {show(text[at:at + 40], 60)} '
                         f'stored {show(other[at:at + 40], 60)}')
            paired += 1
        else:
            lines.append(f'    only predicted: {show(text)}')
    leftover = [t for texts in stored_by_head.values() for t in texts]
    for text in leftover[:max(0, limit - len(lines))]:
        lines.append(f'    only stored: {show(text)}')
    return lines


def compare(predicted: dict[str, list[str]], stored: dict[str, list[str]], limit: int) -> tuple[list[dict], list[str]]:
    """Per-file verdicts and the printable lines."""
    results, out = [], []
    for name in sorted(set(predicted) | set(stored)):
        p, s = predicted.get(name), stored.get(name)
        law = name[:-3] if name.endswith('.md') else name
        if p is None or s is None:
            where = 'stored only' if p is None else 'predicted only'
            results.append({'law': law, 'file': name, 'predicted': len(p or []), 'stored': len(s or []), 'ok': False,
                            'note': f'document {where}'})
            out.append(f'BAD {law}: the document is {where} (predicted {len(p or [])}, stored {len(s or [])})')
            continue
        pc, sc = Counter(p), Counter(s)
        only_p = list((pc - sc).elements())
        only_s = list((sc - pc).elements())
        dup_p = sum(n - 1 for n in pc.values() if n > 1)
        ok = not only_p and not only_s
        results.append({'law': law, 'file': name, 'predicted': len(p), 'stored': len(s), 'ok': ok,
                        'only_predicted': len(only_p), 'only_stored': len(only_s), 'duplicate_predicted_texts': dup_p})
        tag = 'OK ' if ok else 'BAD'
        out.append(f'{tag} {law}: predicted {len(p)}, stored {len(s)}'
                   + ('' if ok else f'; {len(only_p)} text(s) only predicted, {len(only_s)} only stored'))
        if dup_p:
            # Not «stored once»: the id is xxh64(text + document id) (rag/svr/task_executor.py:926-927), but the
            # document's chunk_count adds every copy (task_executor.py:972; document_service.py:774).
            # Elasticsearch keeps one row per id (rag/utils/es_conn.py:378-380); Infinity deletes the batch's
            # ids and inserts the whole batch (rag/utils/infinity_conn.py:626-635), so copies in one batch stay.
            out.append(f'    {dup_p} predicted text(s) repeat inside this file: RAGFlow gives the copies one chunk id '
                       'but counts each of them, so this law cannot be certified (README, runbook E4 stops on any '
                       'repeat)')
        if not ok:
            out.extend(describe_differences(only_p, only_s, limit))
    return results, out


def write_json_atomic(path: Path, data: dict) -> None:
    partial = path.with_name(path.name + '.partial')
    with open(partial, 'w', encoding='utf-8', newline='\n') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)


def main(argv: list[str] | None = None, *, stdout=None) -> int:
    stdout = stdout or sys.stdout

    def say(line: str) -> None:
        print(line, file=stdout)

    ap = argparse.ArgumentParser(description='Compare stored W2 chunks with the predicted ones.')
    ap.add_argument('--predicted', required=True, type=Path)
    ap.add_argument('--dumped', required=True, type=Path)
    ap.add_argument('--manifest', required=True, type=Path)
    ap.add_argument('--ingest-state', type=Path,
                    help="rf_ingest.py's ingest-state.json, for the sha256 checks (required)")
    ap.add_argument('--show', type=int, default=3, help='differences shown per law (default: %(default)s)')
    args = ap.parse_args(argv)

    try:
        if args.ingest_state is None:
            raise BadInput('give --ingest-state (rf_ingest.py\'s ingest-state.json): without it nothing shows that '
                           'the predictor read the bytes that were uploaded')
        header, predicted = read_predicted(args.predicted)
        stored = read_dumped(args.dumped)
        try:
            manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise BadInput(f'cannot read the manifest {args.manifest}') from None
        if not isinstance(manifest, dict) or manifest.get('w2') != 1:
            raise BadInput(f'{args.manifest.name} is not a W2 manifest')
        try:
            state = json.loads(args.ingest_state.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise BadInput(f'cannot read the ingest state {args.ingest_state}') from None
        if not isinstance(state, dict) or not isinstance(state.get('files'), list):
            raise BadInput(f'{args.ingest_state.name} holds no "files" list')
    except BadInput as error:
        say(f'refused: {error}')
        return BAD_INPUT

    results, lines = compare(predicted, stored, max(0, args.show))
    for line in lines:
        say(line)

    problems = []
    total_predicted = sum(len(v) for v in predicted.values())
    total_stored = sum(len(v) for v in stored.values())
    if len(predicted) != EXPECTED_DOCUMENTS:
        problems.append(f'the predictor read {len(predicted)} files, not {EXPECTED_DOCUMENTS}')
    if manifest.get('document_count') != EXPECTED_DOCUMENTS:
        problems.append(f'the manifest says document_count {manifest.get("document_count")}, not {EXPECTED_DOCUMENTS}')
    if manifest.get('chunk_count') != total_stored:
        problems.append(f'the manifest says chunk_count {manifest.get("chunk_count")}, '
                        f'but chunks.jsonl holds {total_stored}')
    if header.get('canvas_sha256') != manifest.get('canvas_sha256'):
        problems.append('the predictor read a different canvas from the one rf_ingest.py imported (canvas_sha256)')
    uploaded = {f.get('name'): f.get('sha256') for f in state['files'] if isinstance(f, dict)}
    if uploaded != header.get('files'):
        problems.append('the predictor read different file bytes from those rf_ingest.py uploaded (sha256)')
    for problem in problems:
        say(f'BAD {problem}')

    all_match = not problems and all(r['ok'] for r in results)
    differing = sum(not r['ok'] for r in results)
    say(f'TOTAL predicted {total_predicted}, stored {total_stored}, documents {len(stored)}')
    say('ALL MATCH' if all_match else f'{differing} law(s) differ, {len(problems)} other problem(s)')

    manifest['predicted_chunk_count'] = total_predicted
    manifest['all_match'] = bool(all_match)
    write_json_atomic(args.manifest, manifest)
    write_json_atomic(args.manifest.with_name('w2-check.json'), {
        'w2_check': 1, 'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'all_match': bool(all_match), 'predicted_total': total_predicted, 'stored_total': total_stored,
        'predicted_sha256': sha256_of(args.predicted), 'dumped_sha256': sha256_of(args.dumped),
        'problems': problems, 'laws': results})
    return MATCH if all_match else DIFFER


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
