#!/usr/bin/env python3
"""rf_ingest.py: build the W2 dataset inside the throwaway RAGFlow v0.27.3, over its HTTP API.

Runs INSIDE ragbench-rf-runner, which shares ragbench-rf-server's network namespace, so the API is
http://127.0.0.1:9380 and nothing is published. The API key is read from the runner's tmpfs
(/run/rf/key, written there by make_key.py through a pipe); it never touches the host disk.

  python3 -I -B /w2/rf_ingest.py preflight --engine elasticsearch
  python3 -I -B /w2/rf_ingest.py all --engine elasticsearch --canvas /canvas/indexing-pipeline.json \
      --in-dir /in --upload-manifest /in/upload-manifest.json --tei-wait-patch /patch/patch.json \
      --out /out/elasticsearch
  (or the steps one by one: create, wait, dump; wait and dump can be run again after an interruption;
  create, dump and all take --tei-wait-patch)

What it sends (paths after http://127.0.0.1:9380; v0.27.3 source, .hq/scratch/ragflow-src-v0.27.3/x/):
  GET  /api/v1/system/version     no key    system_api.py:44-63
  GET  /api/v1/system/healthz     no key    system_api.py:269-272 (bare JSON; 200 only when all ok)
  GET  /api/v1/system/config      no key    system_api.py:244-266 (data.registerEnabled)
  POST /api/v1/users              no key    user_api.py:470-509: a sign-up probe that must be refused
                                            with code 103 «User registration is disabled!»
  GET  /api/v1/system/status      key       system_api.py:73-115 (data.doc_engine.type:
                                            es_conn_base.py:72, infinity_conn_base.py:512)
  GET  /api/v1/datasets           key       dataset_api.py:318 (the stack must hold no dataset)
  POST /api/v1/agents             key       agent_api.py:962-1026: the canvas DSL as it is, with
                                            canvas_category "dataflow_canvas" (api/db/__init__.py:60-62)
  POST /api/v1/datasets           key       dataset_api.py:82-164: name, embedding_model
                                            "<TEI model>@Builtin", parse_type 2 and pipeline_id, language;
                                            no chunk_method (validation_utils.py:562-585, :770-816;
                                            the web's Pipeline parse type is 2, web/src/constants/knowledge.ts:147-150)
  POST /api/v1/datasets/<id>/documents          key  document_api.py:442-519, :651-719: multipart, one
                                                     «file» part per law (files.getlist("file"), :658)
  POST /api/v1/datasets/<id>/documents/parse    key  document_api.py:1542-1659; a pipeline dataset is
                                                     queued as a dataflow (document_service.py:1289-1290).
                                                     (/datasets/<id>/chunks refuses pipeline datasets,
                                                     chunk_api.py:271-274.)
  GET  /api/v1/datasets/<id>/documents          key  document_api.py:722-852 (run, progress, chunk_count)
  GET  /api/v1/datasets/<id>/documents/<doc>/chunks  key  chunk_api.py:607-698, page_size at most 100
                                                     (api/utils/pagination_utils.py:19, :34-44)
  GET  http://ragbench-rf-tei:80/info           no key  TEI's own route: which model it serves
ROUTES below lists them; any other request is refused before it is sent. No proxy, no redirect.

What it never does. It never prints or writes the key, and it never prints a response body: only
the fields it checks, and a server message cut at 200 characters with the key removed. It deletes
nothing on the server. It refuses an --out that already holds a run, a stack that already holds a
dataset, and an upload set that is not exactly the 22 files the upload manifest lists.

Writes into --out (which must be named after the engine): ingest-state.json (ids, hashes, parse
rounds), chunks.jsonl (every stored chunk, one per line) and w2-manifest.json (the W2 contract,
with all_match false: only w2_check.py sets it). Facts the runner cannot observe come from the
environment compose.yaml gives it: W2_DOC_ENGINE, W2_TEI_MODEL, W2_TEI_REVISION,
W2_EMBEDDING_BATCH_SIZE, W2_MAX_CONCURRENT_TASKS, W2_RAGFLOW_IMAGE. The TEI-wait patch comes from
--tei-wait-patch, patch_tei_wait.py's patch.json in the folder compose.yaml mounts at /patch for the runner
and, over the module, for the server (README, «## TEI wait patch»): its five contract fields and the text of
embedding_model.diff beside it go into the manifest as tei_wait_patch (six keys; the spec puts the diff and both
sha256 there), after the patched file beside it is checked against patched_sha256 and the diff against the
changed lines of that file. create records them in the state file, and dump refuses a patch that differs from
that record.

Exit codes: 0 done, 1 a check failed or the server refused (state kept), 2 refused before sending.
Standard library only; Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAGFLOW_VERSION_PREFIX = 'v0.27.3'
EXPECTED_DOCUMENTS = 22
FILE_SHAPE = 'slug-title-served-v1'
PAGE_SIZE = 100            # the REST maximum (api/utils/pagination_utils.py:19)
PARSE_TYPE_PIPELINE = 2    # web/src/constants/knowledge.ts:149; anything but 1 keeps pipeline_id (validation_utils.py:583)
DATAFLOW_CANVAS = 'dataflow_canvas'
ENGINES = ('elasticsearch', 'infinity')
CANVAS_CHAIN = ('File', 'Parser', 'TitleChunker', 'Tokenizer')
SLUG_MD = re.compile(r'[a-z0-9][a-z0-9-]*\.md')
HEX32 = re.compile(r'[0-9a-f]{32}')
KEY_SHAPE = re.compile(r'ragflow-[A-Za-z0-9_-]{20,}')
HEX64 = re.compile(r'[0-9a-f]{64}')
TEI_WAIT_FILE = 'rag/llm/embedding_model.py'   # patch_tei_wait.py FILE
TEI_WAIT_PATCHED = 'embedding_model.py'        # the patched file, beside patch.json
TEI_WAIT_DIFF = 'embedding_model.diff'          # its unified diff, beside patch.json (patch_tei_wait.py OUT_DIFF)
TEI_WAIT_SHIPPED = 30                           # v0.27.3's wait (rag/llm/embedding_model.py:1247, :1253)
TEI_WAIT_RECORD_KEYS = ('file', 'image_sha256', 'patched_sha256', 'changed_lines', 'wait_s')  # from patch.json
# The manifest's tei_wait_patch: those five and the diff text (spec, «The change»: «Its diff and both sha256 go in
# the W2 manifest»).
TEI_WAIT_KEYS = TEI_WAIT_RECORD_KEYS + ('diff',)
HUNK = re.compile(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@')
DONE_RUN, FAIL_RUNS = 'DONE', ('FAIL', 'CANCEL')  # TaskStatus names (common/constants.py:106-112), mapped by
                                                  # document_api_service.py:218-234
STATE, CHUNKS, MANIFEST = 'ingest-state.json', 'chunks.jsonl', 'w2-manifest.json'

ROUTES = (  # (method, path pattern, needs the key)
    ('GET', r'/api/v1/system/version', False),
    ('GET', r'/api/v1/system/healthz', False),
    ('GET', r'/api/v1/system/config', False),
    ('POST', r'/api/v1/users', False),
    ('GET', r'/api/v1/system/status', True),
    ('GET', r'/api/v1/datasets', True),
    ('POST', r'/api/v1/datasets', True),
    ('POST', r'/api/v1/agents', True),
    ('POST', r'/api/v1/datasets/[0-9a-f]{32}/documents', True),
    ('POST', r'/api/v1/datasets/[0-9a-f]{32}/documents/parse', True),
    ('GET', r'/api/v1/datasets/[0-9a-f]{32}/documents', True),
    ('GET', r'/api/v1/datasets/[0-9a-f]{32}/documents/[0-9a-f]{32}/chunks', True),
)

DONE, FAILED, REFUSED = 0, 1, 2


class Refused(Exception):
    """A problem found before anything was sent."""


class Failed(Exception):
    """A check failed or the server refused; what was done so far is in the state file."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Failed(f'HTTP {code}: a redirect; redirects are refused')


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_loopback(host: str) -> bool:
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def read_key(path: Path) -> str:
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        raise Refused('the API key file cannot be read') from None
    key = text.strip()
    if not KEY_SHAPE.fullmatch(key) or text.count('\n') > 1:
        raise Refused('the API key file must hold one RAGFlow key («ragflow-…») on one line')
    return key


def plain_url(url: str, *, allow_hosts: tuple[str, ...] = ()) -> str:
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ''
    if parts.scheme != 'http' or not (is_loopback(host) or host in allow_hosts) or parts.query or parts.fragment:
        raise Refused(f'{url!r}: only http:// to a loopback address{" or " + ", ".join(allow_hosts) if allow_hosts else ""}')
    return url.rstrip('/')


class Client:
    """The one gate every request passes. Answers are parsed; bodies are never printed."""

    def __init__(self, base_url: str, key: str, *, timeout: float = 120.0):
        self.base = base_url
        self._key = key
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def __repr__(self) -> str:
        return 'Client(...)'

    def redact(self, text) -> str:
        text = ' '.join(str(text).replace(self._key, '[REDACTED]').split())
        return re.sub(r'(?i)\bbearer\s+\S+', 'Bearer [REDACTED]', text)[:200]

    def request(self, method: str, path: str, *, query: dict | None = None, body: dict | None = None,
                multipart: tuple[bytes, str] | None = None) -> tuple[int, object]:
        route = next((r for r in ROUTES if r[0] == method and re.fullmatch(r[1], path)), None)
        if route is None:
            raise Refused(f'refused {method} {path}: not one of the requests this tool may send')
        url = self.base + path + ('?' + urllib.parse.urlencode(query) if query else '')
        headers = {'Accept': 'application/json', 'User-Agent': 'rf_ingest/1'}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        elif multipart is not None:
            data, headers['Content-Type'] = multipart
        if route[2]:
            headers['Authorization'] = f'Bearer {self._key}'
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
            error.close()
        except urllib.error.URLError as error:
            raise Failed(f'{method} {path}: cannot reach the server ({type(error.reason).__name__})') from None
        except OSError as error:
            raise Failed(f'{method} {path}: the connection failed ({type(error).__name__})') from None
        try:
            return status, json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise Failed(f'{method} {path}: HTTP {status}, the answer ({len(raw)} bytes) is not JSON') from None

    def call(self, method: str, path: str, *, expect_code: int = 0, **kwargs) -> dict:
        status, payload = self.request(method, path, **kwargs)
        code = payload.get('code') if isinstance(payload, dict) else None
        if code != expect_code:
            message = self.redact(payload.get('message', '')) if isinstance(payload, dict) else ''
            raise Failed(f'{method} {path}: HTTP {status}, code {code}, expected {expect_code}: {message}')
        return payload


def tei_get(url: str, *, timeout: float = 30.0) -> dict:
    """GET <tei>/info with no key: TEI is not RAGFlow and gets no credential."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(urllib.request.Request(url + '/info', headers={'Accept': 'application/json'}),
                         timeout=timeout) as resp:
            info = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError) as error:
        raise Failed(f'GET {url}/info: {type(error).__name__}') from None
    if not isinstance(info, dict):
        raise Failed(f'GET {url}/info: not a JSON object')
    return info


# Facts the runner cannot observe: given by compose.yaml from the same variables that set up the server.

def run_facts(engine: str, environ=os.environ) -> dict:
    facts = {k: environ.get(k, '') for k in
             ('W2_DOC_ENGINE', 'W2_TEI_MODEL', 'W2_TEI_REVISION', 'W2_EMBEDDING_BATCH_SIZE',
              'W2_MAX_CONCURRENT_TASKS', 'W2_RAGFLOW_IMAGE')}
    if facts['W2_DOC_ENGINE'] != engine:
        raise Refused(f'--engine {engine} differs from W2_DOC_ENGINE {facts["W2_DOC_ENGINE"]!r} '
                      '(the engine compose.yaml started)')
    if not facts['W2_TEI_MODEL'] or not re.fullmatch(r'[0-9a-f]{40}', facts['W2_TEI_REVISION']):
        raise Refused('W2_TEI_MODEL and W2_TEI_REVISION (a 40-hex commit) must be set by compose.yaml')
    if not facts['W2_EMBEDDING_BATCH_SIZE'].isdigit() or not 1 <= int(facts['W2_EMBEDDING_BATCH_SIZE']) <= 64:
        raise Refused('W2_EMBEDDING_BATCH_SIZE must be a number from 1 to 64 (the prepare step sets it)')
    if not facts['W2_MAX_CONCURRENT_TASKS'].isdigit() or not 1 <= int(facts['W2_MAX_CONCURRENT_TASKS']) <= 64:
        raise Refused('W2_MAX_CONCURRENT_TASKS must be a number from 1 to 64 (compose.yaml sets it from '
                      'RF_MAX_CONCURRENT_TASKS, as for the server)')
    digest = re.search(r'@(sha256:[0-9a-f]{64})$', facts['W2_RAGFLOW_IMAGE'])
    if not facts['W2_RAGFLOW_IMAGE'].startswith('infiniflow/ragflow:') or not digest:
        raise Refused('W2_RAGFLOW_IMAGE must be infiniflow/ragflow:<tag>@sha256:<digest>')
    return {'engine': engine, 'model': facts['W2_TEI_MODEL'], 'revision': facts['W2_TEI_REVISION'],
            'batch_size': int(facts['W2_EMBEDDING_BATCH_SIZE']),
            'max_concurrent_tasks': int(facts['W2_MAX_CONCURRENT_TASKS']), 'image': facts['W2_RAGFLOW_IMAGE'],
            'image_digest': digest.group(1)}


def _whole(value) -> bool:
    return type(value) is int


def tei_wait_diff_problem(diff: str, patched: list[str], lines: list[int], wait: int) -> str | None:
    """Why `diff` is not patch_tei_wait.py's diff of this change; None when it is. It must name a/ and b/
    rag/llm/embedding_model.py, and its only removed and added lines are `lines` (1-based, the same in the old
    and the new file, since no line is added), each `timeout=30)` becoming `timeout=<wait>)`, each added line
    equal to the patched file's line of that number."""
    rows = diff.split('\n')
    if rows[:2] != [f'--- a/{TEI_WAIT_FILE}', f'+++ b/{TEI_WAIT_FILE}']:
        return f'it does not name a/{TEI_WAIT_FILE} and b/{TEI_WAIT_FILE}'
    removed, added, old, new = [], [], None, None
    for at, row in enumerate(rows[2:], 3):
        hunk = HUNK.fullmatch(row)
        if hunk:
            old, new = int(hunk.group(1)), int(hunk.group(2))
        elif row == '' and at == len(rows):
            pass  # after the last line end
        elif old is None or row[:1] not in (' ', '-', '+'):
            return f'its line {at} is neither a hunk header nor a context, removed or added line'
        elif row[0] == '-':
            removed.append((old, row[1:]))
            old += 1
        elif row[0] == '+':
            added.append((new, row[1:]))
            new += 1
        else:
            old, new = old + 1, new + 1
    if [n for n, _ in removed] != lines or [n for n, _ in added] != lines:
        return (f'it removes lines {[n for n, _ in removed]} and adds lines {[n for n, _ in added]}, not exactly '
                f'the changed lines {lines}')
    shipped, raised = f'timeout={TEI_WAIT_SHIPPED})', f'timeout={wait})'
    for (_, before), (n, after) in zip(removed, added):  # n: the added line's number, in the patched file
        if not (before.endswith(shipped) and after.endswith(raised)
                and before[:-len(shipped)] == after[:-len(raised)]):
            return f'line {n} does not change only timeout={TEI_WAIT_SHIPPED} to timeout={wait}'
        if n > len(patched) or patched[n - 1] != after:
            return f'its line {n} is not the patched file\'s line {n}'
    return None


def read_tei_wait_patch(path: Path) -> dict:
    """The five contract fields of patch_tei_wait.py's patch.json, checked, and the diff beside it; the patched
    file beside it must have the recorded patched_sha256 (it is the folder the server mounts the module from),
    and the diff must change exactly the recorded lines of that file (tei_wait_diff_problem)."""
    try:
        record = json.loads(path.read_bytes().decode('utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        raise Refused(f'the TEI-wait patch record {path} cannot be read as JSON') from None
    if not isinstance(record, dict) or not all(k in record for k in TEI_WAIT_RECORD_KEYS):
        raise Refused(f'{path.name} must hold {", ".join(TEI_WAIT_RECORD_KEYS)} (patch_tei_wait.py writes it)')
    if record['file'] != TEI_WAIT_FILE:
        raise Refused(f'{path.name}: file must be {TEI_WAIT_FILE}')
    if not _whole(record['wait_s']) or record['wait_s'] <= TEI_WAIT_SHIPPED:
        raise Refused(f'{path.name}: wait_s must be a whole number above {TEI_WAIT_SHIPPED}')
    for name in ('image_sha256', 'patched_sha256'):
        if not isinstance(record[name], str) or not HEX64.fullmatch(record[name]):
            raise Refused(f'{path.name}: {name} must be 64 lower-case hex characters')
    if record['image_sha256'] == record['patched_sha256']:
        raise Refused(f'{path.name}: the patched file has the image file\'s sha256, so nothing was changed')
    lines = record['changed_lines']
    if not (isinstance(lines, list) and len(lines) == 2 and all(_whole(n) and n > 0 for n in lines)
            and lines[0] < lines[1]):
        raise Refused(f'{path.name}: changed_lines must be two line numbers, in order')
    try:
        patched = (path.parent / TEI_WAIT_PATCHED).read_bytes()
    except OSError:
        raise Refused(f'no {TEI_WAIT_PATCHED} beside {path.name}: the record must sit with the file it '
                      'describes') from None
    if sha256_bytes(patched) != record['patched_sha256']:
        raise Refused(f'the {TEI_WAIT_PATCHED} beside {path.name} does not have its patched_sha256')
    try:
        diff = (path.parent / TEI_WAIT_DIFF).read_bytes().decode('utf-8')
        patched_lines = patched.decode('utf-8').split('\n')
    except OSError:
        raise Refused(f'no {TEI_WAIT_DIFF} beside {path.name}: the record must sit with the diff of its '
                      'change') from None
    except UnicodeDecodeError:
        raise Refused(f'the {TEI_WAIT_DIFF} or {TEI_WAIT_PATCHED} beside {path.name} is not UTF-8') from None
    problem = tei_wait_diff_problem(diff, patched_lines, lines, record['wait_s'])
    if problem:
        raise Refused(f'the {TEI_WAIT_DIFF} beside {path.name} is not the diff of its change: {problem}')
    return {**{k: record[k] for k in TEI_WAIT_RECORD_KEYS}, 'diff': diff}


# Inputs ------------------------------------------------------------------------------------------

def check_canvas(path: Path) -> tuple[dict, str, list[str]]:
    """Read the canvas as data; accept only the File -> Parser -> TitleChunker -> Tokenizer chain."""
    try:
        raw = path.read_bytes()
        dsl = json.loads(raw.decode('utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        raise Refused(f'the canvas {path} cannot be read as JSON') from None
    components = dsl.get('components') if isinstance(dsl, dict) else None
    if not isinstance(components, dict):
        raise Refused('the canvas has no components object')
    by_name = {}
    for cid, comp in components.items():
        name = (comp.get('obj') or {}).get('component_name') if isinstance(comp, dict) else None
        if name not in CANVAS_CHAIN or name in by_name:
            raise Refused(f'the canvas holds a component other than one each of {", ".join(CANVAS_CHAIN)}: {name!r}')
        by_name[name] = cid
    if set(by_name) != set(CANVAS_CHAIN):
        raise Refused(f'the canvas lacks {sorted(set(CANVAS_CHAIN) - set(by_name))}')
    ids = [by_name[n] for n in CANVAS_CHAIN]
    for here, there in zip(ids, ids[1:] + [None]):
        if components[here].get('downstream') != ([there] if there else []):
            raise Refused(f'the canvas is not the chain {" -> ".join(CANVAS_CHAIN)}')
    tc = components[by_name['TitleChunker']]['obj'].get('params') or {}
    tk = components[by_name['Tokenizer']]['obj'].get('params') or {}
    md = ((components[by_name['Parser']]['obj'].get('params') or {}).get('setups') or {}).get('markdown') or {}
    summary = [f'TitleChunker: method {tc.get("method")}, hierarchy {tc.get("hierarchy")}, chunk_token_cap '
               f'{tc.get("chunk_token_cap")}, {sum(len(g) for g in tc.get("levels") or [])} level pattern(s)',
               f'Tokenizer: search_method {tk.get("search_method")}, fields {tk.get("fields")}, '
               f'filename_embd_weight {tk.get("filename_embd_weight")}',
               f'Parser markdown: output_format {md.get("output_format")}, delimiter {md.get("delimiter")!r}']
    return dsl, sha256_bytes(raw), summary


def check_upload_set(in_dir: Path, manifest_path: Path, canvas_sha256: str) -> tuple[list[dict], str]:
    """The 22 <slug>.md files, exactly as the generator's manifest lists them."""
    try:
        manifest_raw = manifest_path.read_bytes()
        manifest = json.loads(manifest_raw.decode('utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        raise Refused(f'the upload manifest {manifest_path} cannot be read as JSON') from None
    listed = manifest.get('files') if isinstance(manifest, dict) else None
    if not isinstance(listed, list) or not all(isinstance(f, dict) and isinstance(f.get('name'), str)
                                               and isinstance(f.get('sha256'), str) for f in listed):
        raise Refused('the upload manifest must hold "files": [{"name": "<slug>.md", "sha256": "<hex>"}, ...]')
    if manifest.get('file_shape') != FILE_SHAPE:
        raise Refused(f'the upload manifest names file_shape {manifest.get("file_shape")!r}, not {FILE_SHAPE}')
    canvas = manifest.get('canvas')
    if isinstance(canvas, dict) and canvas.get('sha256') not in (None, canvas_sha256):
        raise Refused('the upload set was generated against another canvas (upload manifest canvas.sha256)')
    expected = {f['name']: f['sha256'].lower() for f in listed}
    try:
        present = sorted(p.name for p in in_dir.iterdir() if p.name.lower().endswith('.md'))
    except OSError:
        raise Refused(f'cannot list {in_dir}') from None
    if len(present) != EXPECTED_DOCUMENTS or len(expected) != EXPECTED_DOCUMENTS or set(present) != set(expected):
        raise Refused(f'{in_dir} holds {len(present)} .md file(s) and the manifest lists {len(expected)}; '
                      f'both must be the same {EXPECTED_DOCUMENTS}')
    files = []
    for name in present:
        if not SLUG_MD.fullmatch(name):
            raise Refused(f'{name}: not a registry slug file name')
        path = in_dir / name
        if not path.is_file():
            raise Refused(f'{name}: not a plain file')
        data = path.read_bytes()
        if sha256_bytes(data) != expected[name]:
            raise Refused(f'{name}: its sha256 differs from the upload manifest')
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            raise Refused(f'{name}: not UTF-8') from None
        if not text.startswith('# ') or '\n### المادة ' not in text:
            raise Refused(f'{name}: does not start with «# <title>» or holds no «### المادة» heading')
        files.append({'name': name, 'bytes': len(data), 'sha256': sha256_bytes(data)})
    return files, sha256_bytes(manifest_raw)


def encode_multipart(parts: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    while True:
        boundary = 'w2-' + secrets.token_hex(16)
        if not any(boundary.encode('ascii') in data for _, data in parts):
            break
    chunks = []
    for name, data in parts:
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                       'Content-Type: text/markdown\r\n\r\n').encode('ascii'))
        chunks.append(data)
        chunks.append(b'\r\n')
    chunks.append(f'--{boundary}--\r\n'.encode('ascii'))
    return b''.join(chunks), f'multipart/form-data; boundary={boundary}'


# State -------------------------------------------------------------------------------------------

def write_json(path: Path, data, key: str) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=1) + '\n'
    text = text.replace(key, '[REDACTED]') if key else text
    partial = path.with_name(path.name + '.partial')
    with open(partial, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)


def load_state(out: Path) -> dict:
    try:
        return json.loads((out / STATE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise Refused(f'no readable {STATE} in {out}: run «create» first') from None


# Steps -------------------------------------------------------------------------------------------

def preflight(client: Client, facts: dict, tei_url: str, log, *, require_empty: bool) -> dict:
    payload = client.call('GET', '/api/v1/system/version')
    version = payload.get('data')
    if not isinstance(version, str) or not version.startswith(RAGFLOW_VERSION_PREFIX):
        raise Failed(f'the server reports version {client.redact(version)!r}, not {RAGFLOW_VERSION_PREFIX}')
    log(f'ok   version: {version.strip()[:60]}')
    status, health = client.request('GET', '/api/v1/system/healthz')
    if status != 200 or not isinstance(health, dict) or health.get('status') != 'ok':
        parts = {k: health.get(k) for k in ('db', 'redis', 'doc_engine', 'storage')} if isinstance(health, dict) else {}
        raise Failed(f'healthz: HTTP {status}, {parts}')
    log('ok   healthz: db, redis, doc_engine and storage ok')
    config = client.call('GET', '/api/v1/system/config').get('data') or {}
    if config.get('registerEnabled') not in (0, False):
        raise Failed(f'sign-up is not off: registerEnabled {config.get("registerEnabled")!r}')
    log('ok   sign-up off: registerEnabled 0')
    probe = {'nickname': 'w2-probe', 'email': 'w2-probe@ragbench.invalid', 'password': secrets.token_hex(8)}
    refusal = client.call('POST', '/api/v1/users', body=probe, expect_code=103)
    if 'disabled' not in str(refusal.get('message', '')):
        raise Failed('the sign-up probe was refused with an unexpected message')
    log('ok   sign-up probe refused: code 103')
    engine = ((client.call('GET', '/api/v1/system/status').get('data') or {}).get('doc_engine') or {}).get('type')
    if engine != facts['engine']:
        raise Failed(f'the server runs doc engine {engine!r}, not {facts["engine"]}')
    log(f'ok   doc engine: {engine}')
    info = tei_get(tei_url)
    model_id = str(info.get('model_id', ''))
    if not model_id.rstrip('/').endswith(facts['model']):
        raise Failed(f'TEI serves {client.redact(model_id)!r}, not {facts["model"]}')
    log(f'ok   TEI: {model_id}, max_input_length {info.get("max_input_length")}')
    datasets = client.call('GET', '/api/v1/datasets', query={'page': 1, 'page_size': 30}).get('data')
    if not isinstance(datasets, list):
        raise Failed('GET /api/v1/datasets: no data list')
    if require_empty and datasets:
        raise Failed(f'the stack already holds {len(datasets)} dataset(s); W2 runs on a fresh stack only')
    log(f'ok   datasets on the stack: {len(datasets)}')
    return {'ragflow_version': version.strip(), 'tei': {'model_id': model_id,
                                                        'max_input_length': info.get('max_input_length')}}


def create(client: Client, args, facts: dict, out: Path, log, key: str, patch: dict) -> dict:
    for name in (STATE, CHUNKS, MANIFEST):
        if (out / name).exists() or (out / (name + '.partial')).exists():
            raise Refused(f'{out / name} already exists: this folder already holds a run')
    dsl, canvas_sha, summary = check_canvas(args.canvas)
    files, upload_manifest_sha = check_upload_set(args.in_dir, args.upload_manifest, canvas_sha)
    log(f'canvas sha256 {canvas_sha}')
    for line in summary:
        log(f'  {line}')
    log(f'upload set: {len(files)} files, {sum(f["bytes"] for f in files):,} bytes; '
        f'manifest sha256 {upload_manifest_sha}')
    log(f'TEI-wait patch: {patch["file"]} lines {patch["changed_lines"]}, wait {patch["wait_s"]} s, '
        f'patched sha256 {patch["patched_sha256"]}')
    state = {'w2_ingest': 1, 'created_at': now(), 'engine': facts['engine'], 'canvas_sha256': canvas_sha,
             'upload_manifest_sha256': upload_manifest_sha, 'files': files, 'parse_rounds': [], 'parsed': False,
             'tei_wait_patch': patch}
    state.update(preflight(client, facts, args.tei_url, log, require_empty=True))

    title = f'w2-indexing-{facts["engine"]}'
    agent = client.call('POST', '/api/v1/agents',
                        body={'title': title, 'dsl': dsl, 'canvas_category': DATAFLOW_CANVAS}).get('data') or {}
    agent_id = agent.get('id')
    if not isinstance(agent_id, str) or not HEX32.fullmatch(agent_id):
        raise Failed('POST /api/v1/agents: no 32-hex id in the answer')
    if agent.get('canvas_category') != DATAFLOW_CANVAS:
        raise Failed(f'the pipeline was stored as {agent.get("canvas_category")!r}, not {DATAFLOW_CANVAS}')
    stored = (agent.get('dsl') or {}).get('components') if isinstance(agent.get('dsl'), dict) else None
    if stored != dsl['components']:
        differing = sorted(k for k in set(dsl['components']) | set(stored or {})
                           if (stored or {}).get(k) != dsl['components'].get(k))
        raise Failed(f'the stored pipeline differs from the canvas in component(s) {differing}')
    state.update({'agent_id': agent_id, 'agent_title': title})
    write_json(out / STATE, state, key)
    log(f'pipeline imported as it is: agent {agent_id} ({DATAFLOW_CANVAS})')

    name = f'w2-laws-{facts["engine"]}'
    embedding = f'{facts["model"]}@Builtin'
    dataset = client.call('POST', '/api/v1/datasets', body={
        'name': name, 'embedding_model': embedding, 'parse_type': PARSE_TYPE_PIPELINE,
        'pipeline_id': agent_id, 'language': args.language}).get('data') or {}
    dataset_id = dataset.get('id')
    if not isinstance(dataset_id, str) or not HEX32.fullmatch(dataset_id):
        raise Failed('POST /api/v1/datasets: no 32-hex id in the answer')
    checks = {'name': name, 'pipeline_id': agent_id, 'embedding_model': embedding, 'language': args.language}
    wrong = [k for k, v in checks.items() if dataset.get(k) != v]
    state.update({'dataset_id': dataset_id, 'dataset_name': dataset.get('name'),
                  'embedding_model': dataset.get('embedding_model'), 'language': dataset.get('language')})
    write_json(out / STATE, state, key)
    if wrong:
        raise Failed(f'the dataset was created with other {", ".join(wrong)} than asked')
    log(f'dataset {dataset_id}: pipeline {agent_id}, embedding {embedding}, language {args.language}')

    parts = [(f['name'], (args.in_dir / f['name']).read_bytes()) for f in files]
    if [sha256_bytes(data) for _, data in parts] != [f['sha256'] for f in files]:
        raise Failed('an upload file changed after it was checked; nothing was uploaded')
    payload = client.call('POST', f'/api/v1/datasets/{dataset_id}/documents', multipart=encode_multipart(parts))
    docs = payload.get('data')
    if not isinstance(docs, list):
        raise Failed('the upload answer holds no document list')
    by_name = {d.get('name'): d for d in docs if isinstance(d, dict)}
    if sorted(by_name) != sorted(f['name'] for f in files) or len(docs) != len(files):
        raise Failed(f'the server created {len(docs)} document(s) whose names differ from the 22 sent '
                     '(a duplicate name would be renamed, file_service.py:647)')
    for f in files:
        d = by_name[f['name']]
        if d.get('size') != f['bytes'] or d.get('pipeline_id') != agent_id or not HEX32.fullmatch(str(d.get('id'))):
            raise Failed(f'{f["name"]}: the stored document differs in size, pipeline_id or id')
        f['document_id'] = d['id']
    write_json(out / STATE, state, key)
    log(f'uploaded {len(files)} documents, each bound to pipeline {agent_id}')

    start_parse(client, state, [f['document_id'] for f in files], out, log, key)
    return state


def start_parse(client: Client, state: dict, document_ids: list[str], out: Path, log, key: str) -> None:
    result = client.call('POST', f'/api/v1/datasets/{state["dataset_id"]}/documents/parse',
                         body={'document_ids': document_ids}).get('data') or {}
    if result.get('success_count') != len(document_ids):
        raise Failed(f'parse started for {result.get("success_count")} of {len(document_ids)} documents')
    state['parse_rounds'].append({'at': now(), 'document_ids': document_ids})
    write_json(out / STATE, state, key)
    log(f'parse started for {len(document_ids)} document(s) (round {len(state["parse_rounds"])})')


def list_documents(client: Client, dataset_id: str) -> list[dict]:
    data = client.call('GET', f'/api/v1/datasets/{dataset_id}/documents',
                       query={'page': 1, 'page_size': PAGE_SIZE}).get('data') or {}
    docs = data.get('docs')
    if not isinstance(docs, list) or data.get('total') != len(docs):
        raise Failed('the document listing holds no complete docs list')
    return [d for d in docs if isinstance(d, dict)]


def last_line(text, client: Client) -> str:
    lines = [x for x in str(text or '').splitlines() if x.strip()]
    return client.redact(lines[-1]) if lines else ''


def wait(client: Client, args, out: Path, log, key: str, *, sleep=time.sleep, clock=time.monotonic) -> dict:
    state = load_state(out)
    if state.get('parsed'):
        log('parse already recorded as done')
        return state
    if not state.get('parse_rounds'):
        raise Refused('the state records no parse round: «create» stopped before parsing')
    ours = {f['document_id']: f['name'] for f in state['files']}
    started, seen = clock(), {}
    while True:
        docs = {d.get('id'): d for d in list_documents(client, state['dataset_id'])}
        if set(docs) != set(ours):
            raise Failed(f'the dataset holds {len(docs)} document(s), not the {len(ours)} uploaded')
        done = [i for i, d in docs.items() if d.get('run') == DONE_RUN]
        failed = [i for i, d in docs.items() if d.get('run') in FAIL_RUNS or d.get('progress') == -1]
        for i in done + failed:
            now_state = (docs[i].get('run'), docs[i].get('chunk_count'))
            if seen.get(i) != now_state:
                seen[i] = now_state
                tail = '' if i in done else f': {last_line(docs[i].get("progress_msg"), client)}'
                log(f'  {ours[i]}: {docs[i].get("run")}, {docs[i].get("chunk_count")} chunks{tail}')
        chunks = sum(int(d.get('chunk_count') or 0) for d in docs.values())
        log(f'[{datetime.now(timezone.utc).strftime("%H:%M:%S")}] done {len(done)}, failed {len(failed)}, '
            f'waiting {len(docs) - len(done) - len(failed)} of {len(docs)}; chunks so far {chunks:,}')
        if len(done) == len(docs):
            state['parsed'] = True
            state['parsed_at'] = now()
            state['documents_final'] = [{'name': ours[i], 'document_id': i, 'chunk_count': docs[i].get('chunk_count')}
                                        for i in sorted(ours, key=ours.get)]
            write_json(out / STATE, state, key)
            log('parse done for every document')
            return state
        if len(done) + len(failed) == len(docs):
            if len(state['parse_rounds']) - 1 >= args.max_reparse:
                raise Failed(f'{len(failed)} document(s) still failed after {args.max_reparse} re-parse round(s)')
            start_parse(client, state, sorted(failed, key=ours.get), out, log, key)
            seen = {i: s for i, s in seen.items() if i not in failed}
        if clock() - started > args.max_wait:
            raise Failed(f'still parsing after {args.max_wait:.0f} s; run «wait» again to keep waiting')
        sleep(args.poll)


def dump_document(client: Client, dataset_id: str, document_id: str) -> tuple[list[dict], int]:
    chunks, seen, total, page = [], set(), None, 1
    while True:
        data = client.call('GET', f'/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks',
                           query={'page': page, 'page_size': PAGE_SIZE}).get('data') or {}
        batch, total = data.get('chunks'), data.get('total')
        if not isinstance(batch, list) or not isinstance(total, int):
            raise Failed('the chunk listing holds no chunks list or total')
        for c in batch:
            cid = c.get('id') if isinstance(c, dict) else None
            if not isinstance(cid, str) or not isinstance(c.get('content'), str):
                raise Failed('a listed chunk lacks id or content')
            if cid not in seen:
                seen.add(cid)
                chunks.append(c)
        if len(batch) < PAGE_SIZE or len(seen) >= total or page > total // PAGE_SIZE + 2:
            return chunks, total
        page += 1


def dump(client: Client, args, facts: dict, out: Path, log, key: str, patch: dict) -> dict:
    state = load_state(out)
    if not state.get('parsed'):
        raise Refused('the state does not record a finished parse: run «wait» first')
    if state.get('tei_wait_patch') != patch:
        raise Refused('--tei-wait-patch differs from the patch «create» recorded in the state file: the server '
                      'that parsed this dataset ran another patch, or none')
    for name in (CHUNKS, MANIFEST):
        if (out / name).exists():
            raise Refused(f'{out / name} already exists')
    expected = {d['document_id']: d for d in state['documents_final']}
    listed = {d.get('id'): d for d in list_documents(client, state['dataset_id'])}
    rows = []
    for f in state['files']:
        doc_id = f['document_id']
        want = listed.get(doc_id, {}).get('chunk_count')
        if not isinstance(want, int):
            raise Failed(f'{f["name"]}: the document listing gives no chunk_count')
        for attempt in range(1, args.dump_attempts + 1):
            chunks, total = dump_document(client, state['dataset_id'], doc_id)
            if len(chunks) == total == want:
                break
            log(f'  {f["name"]}: listed {len(chunks)} unique of total {total}, document says {want}; '
                f'attempt {attempt} of {args.dump_attempts}')
        else:
            raise Failed(f'{f["name"]}: the chunk listing does not add up; nothing written (a chunk text repeated '
                         'inside one law gets one chunk id but is counted twice: runbook E4 must have stopped it)')
        if want != expected[doc_id]['chunk_count']:
            raise Failed(f'{f["name"]}: its chunk count changed since the parse finished')
        for c in chunks:
            rows.append({'document_name': f['name'], 'document_id': doc_id, 'chunk_id': c['id'],
                         'content': c['content'], 'doc_type_kwd': c.get('doc_type_kwd'),
                         'available': c.get('available')})
        log(f'  {f["name"]}: {len(chunks)} chunks')
    datasets = client.call('GET', '/api/v1/datasets', query={'id': state['dataset_id']}).get('data') or []
    ds = next((d for d in datasets if isinstance(d, dict) and d.get('id') == state['dataset_id']), None)
    if ds is None:
        raise Failed('the dataset is not listed any more')
    if ds.get('document_count') != EXPECTED_DOCUMENTS or ds.get('chunk_count') != len(rows):
        raise Failed(f'the dataset says {ds.get("document_count")} documents and {ds.get("chunk_count")} chunks; '
                     f'the listing gave {len(state["files"])} and {len(rows)}')
    text = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows).replace(key, '[REDACTED]')
    partial = out / (CHUNKS + '.partial')
    with open(partial, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, out / CHUNKS)
    manifest = {
        'w2': 1, 'created_at': now(), 'engine': facts['engine'],
        'embedder': {'name': facts['model'], 'revision': facts['revision'], 'via': 'builtin-tei'},
        'ragflow_version': state['ragflow_version'], 'ragflow_image_digest': facts['image_digest'],
        'dataset_id': state['dataset_id'], 'language': ds.get('language'), 'document_count': ds['document_count'],
        'chunk_count': ds['chunk_count'], 'predicted_chunk_count': None, 'all_match': False,
        'canvas_sha256': state['canvas_sha256'], 'upload_manifest_sha256': state['upload_manifest_sha256'],
        'file_shape': FILE_SHAPE, 'embedding_batch_size': facts['batch_size'],
        'max_concurrent_tasks': facts['max_concurrent_tasks'], 'tei_wait_patch': patch,
    }
    write_json(out / MANIFEST, manifest, key)
    log(f'wrote {len(rows):,} chunks to {CHUNKS} and {MANIFEST} (all_match false until w2_check.py)')
    return manifest


# Command line ------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description='Build the W2 dataset in the throwaway RAGFlow, inside the runner.')
    sub = ap.add_subparsers(dest='step', required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--engine', required=True, choices=ENGINES)
    common.add_argument('--base-url', default='http://127.0.0.1:9380')
    common.add_argument('--api-key-file', type=Path, default=Path('/run/rf/key'))
    common.add_argument('--tei-url', default='http://ragbench-rf-tei:80')
    common.add_argument('--timeout', type=float, default=120.0, help='seconds per request')
    inputs = argparse.ArgumentParser(add_help=False)
    inputs.add_argument('--canvas', required=True, type=Path, help="Walid's indexing-pipeline canvas (data)")
    inputs.add_argument('--in-dir', required=True, type=Path, help='the folder holding the 22 <slug>.md files')
    inputs.add_argument('--upload-manifest', required=True, type=Path, help="the generator's manifest")
    inputs.add_argument('--language', default='English',
                        help="the dataset language (default: %(default)s, RAGFlow's own default, db_models.py:1269)")
    output = argparse.ArgumentParser(add_help=False)
    output.add_argument('--out', required=True, type=Path, help='the run folder, named after the engine')
    waiting = argparse.ArgumentParser(add_help=False)
    waiting.add_argument('--poll', type=float, default=30.0, help='seconds between polls (default: %(default)s)')
    waiting.add_argument('--max-wait', type=float, default=12 * 3600.0, help='seconds (default: %(default)s)')
    waiting.add_argument('--max-reparse', type=int, default=2, choices=(0, 1, 2),
                         help='re-parse rounds for failed documents only (default: %(default)s)')
    dumping = argparse.ArgumentParser(add_help=False)
    dumping.add_argument('--dump-attempts', type=int, default=3)
    patching = argparse.ArgumentParser(add_help=False)
    patching.add_argument('--tei-wait-patch', required=True, type=Path,
                          help="patch_tei_wait.py's patch.json, beside the patched file (/patch/patch.json)")
    sub.add_parser('preflight', parents=[common], help='check the stack and print what it finds')
    sub.add_parser('create', parents=[common, inputs, patching, output],
                   help='import, create, upload and start the parse')
    sub.add_parser('wait', parents=[common, output, waiting], help='poll until every document is parsed')
    sub.add_parser('dump', parents=[common, patching, output, dumping],
                   help='dump every chunk and write the W2 manifest')
    sub.add_parser('all', parents=[common, inputs, patching, output, waiting, dumping], help='create, wait and dump')
    return ap


def main(argv: list[str] | None = None, *, stdout=None, environ=None, sleep=time.sleep, clock=time.monotonic) -> int:
    stdout = stdout or sys.stdout
    environ = os.environ if environ is None else environ
    key = ''

    def log(message: str) -> None:
        print(message.replace(key, '[REDACTED]') if key else message, file=stdout, flush=True)

    args = build_parser().parse_args(argv)
    try:
        base = plain_url(args.base_url)
        tei_url = plain_url(args.tei_url, allow_hosts=('ragbench-rf-tei',))
        args.tei_url = tei_url
        key = read_key(args.api_key_file)
        facts = run_facts(args.engine, environ)
        patch = read_tei_wait_patch(args.tei_wait_patch) if getattr(args, 'tei_wait_patch', None) else None
        client = Client(base, key, timeout=args.timeout)
        out = getattr(args, 'out', None)
        if out is not None:
            if out.name != args.engine or not out.is_dir():
                raise Refused(f'--out must be an existing folder named {args.engine}')
        if args.step == 'preflight':
            preflight(client, facts, tei_url, log, require_empty=False)
        if args.step in ('create', 'all'):
            create(client, args, facts, out, log, key, patch)
        if args.step in ('wait', 'all'):
            wait(client, args, out, log, key, sleep=sleep, clock=clock)
        if args.step in ('dump', 'all'):
            dump(client, args, facts, out, log, key, patch)
    except Refused as refusal:
        log(f'refused: {refusal}')
        return REFUSED
    except Failed as failure:
        log(f'failed: {failure}')
        return FAILED
    except KeyboardInterrupt:
        log('interrupted; the state file records what was done')
        return FAILED
    return DONE


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
