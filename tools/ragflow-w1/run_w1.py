#!/usr/bin/env python3
"""run_w1.py: run the W1 queries through your own RAGFlow retrieval and save the ranked chunks.

It sends three kinds of request to the --base-url server, and nothing else:
  POST /api/v1/retrieval            once per query and field, with your API key
  GET  /api/v1/datasets?id=<id>     once per --dataset, with your API key (counts and settings)
  GET  /api/v1/system/version       once, WITHOUT the key (RAGFlow serves it without login)
--list-datasets sends only GET /api/v1/datasets. --dry-run sends nothing.
It follows no redirect, uses no proxy and always checks the server's certificate. The key is read
from a file and sent only in the Authorization header. It is never printed or written.

It writes one file, --out. A query the server answers with an error is kept as a row with the
error code only; the server's message is shown on screen, not written. A run that stops early
writes <out>.partial instead of <out>: it is not a complete result, so do not send it.
Exit codes: 0 done, 1 some queries failed or the run stopped, 2 refused before sending anything,
130 interrupted.

Python 3.9 or later, standard library only. Read this file, and the message it came with, before
running it. Run it with python3 -I (on Windows, python -I), for example: python3 -I run_w1.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The defaults reproduce the Retrieval node of the canvas «IQRA LAW – FINAL REVIEW v3»: top_n 20,
# similarity_threshold 0.2, keywords_similarity_weight 0.7, rerank_candidates_count 64, no top_k,
# no rerank_id. The RAGFlow v0.27.3 agent maps them so (agent/tools/retrieval.py:214-223):
# page 1, page_size = top_n, vector_similarity_weight = 1 - keywords_similarity_weight,
# knn top_k = the tool's default 1024 (retrieval.py:89).
PAGE_SIZE = 20
SIMILARITY_THRESHOLD = 0.2
VECTOR_SIMILARITY_WEIGHT = 0.3
TOP_K = 1024
RERANK_CANDIDATES = 64  # the server refuses page * page_size above it (api/apps/restful_apis/chunk_api.py:519)

ROUTES = {  # (method, path) -> query keys allowed. The only requests this script can send.
    ('POST', '/api/v1/retrieval'): set(),
    ('GET', '/api/v1/datasets'): {'id', 'page', 'page_size'},
    ('GET', '/api/v1/system/version'): set(),
}
RETRY_STATUSES = {429, 500, 502, 503, 504}
AUTH_CODES = {109, 401}  # RetCode.AUTHENTICATION_ERROR and UNAUTHORIZED (common/constants.py:55-57)
RET_CODES = {100: 'exception', 101: 'argument error', 102: 'data error', 103: 'operating error',
             105: 'connection error', 108: 'permission error', 400: 'bad request', 404: 'not found',
             500: 'server error'}  # RetCode names (common/constants.py:45-61)
FIELDS = ('query', 'question')
QUERY_HEADER_KEYS = {'set', 'w1', 'count', 'fields', 'note'}
QUERY_ITEM_KEYS = {'id', 'query', 'question'}
DATASET_ID = re.compile(r'[0-9a-f]{32}')  # RAGFlow dataset ids are 32 hex characters

DONE, INCOMPLETE, REFUSED, INTERRUPTED = 0, 1, 2, 130


class Refused(Exception):
    """A problem found before anything was sent."""


class Stop(Exception):
    """The run cannot go on: a refused key, a redirect, an unreachable server or an unknown answer."""


class ApiError(Exception):
    """The server answered one request with an error code. The run goes on."""

    def __init__(self, code: int, message: str):
        super().__init__(f'code {code}: {message}')  # for the screen; the message is already redacted
        self.code = code

    def short(self) -> str:
        """For the results file. RAGFlow's messages can name hosts on your network (api_utils.py:152)."""
        return f'code {self.code} ({RET_CODES.get(self.code, "error")}); the message was shown on screen only'


class _Retry(Exception):
    def __init__(self, message: str, retry_after: str | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise Stop(f'the server answered HTTP {code} with a redirect; redirects are refused, '
                   'so the key never goes to another address. Use the final address as --base-url.')


# Inputs ------------------------------------------------------------------------------------------

def read_key(path: Path) -> str:
    """The key alone on one line. Messages repeat neither the path (it could be the key, typed by mistake) nor the key."""
    try:
        text = Path(path).read_bytes().decode('utf-8-sig')
    except OSError as error:
        raise Refused(f'cannot read the --api-key-file: {error.strerror or type(error).__name__}') from None
    except UnicodeDecodeError:
        raise Refused('the --api-key-file is not UTF-8 text') from None
    if not text.strip():
        raise Refused('the --api-key-file is empty')
    lines = text.splitlines()
    if len(lines) != 1:
        raise Refused('the --api-key-file must hold the key alone, on one line')
    key = lines[0].strip()
    if any(ch.isspace() for ch in key) or not key.isascii() or not key.isprintable():
        raise Refused('the key in the --api-key-file holds characters an HTTP header cannot carry')
    return key


def is_loopback(host: str) -> bool:
    """Only the name localhost and loopback addresses. Windows asks DNS for any other *.localhost name."""
    host = host.lower()
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def parse_base_url(base_url: str, allow_insecure_http: bool) -> str:
    parts = urllib.parse.urlsplit((base_url or '').strip())
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise Refused('--base-url must look like https://host[:port][/prefix]')
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise Refused('--base-url must not hold a user, a password, a query or a fragment')
    try:
        parts.port
    except ValueError:
        raise Refused('--base-url has an invalid port') from None
    if parts.scheme == 'http' and not allow_insecure_http and not is_loopback(parts.hostname):
        raise Refused('plain http would send the key unencrypted: use https, or pass --allow-insecure-http '
                      'only on a network you trust')
    return f'{parts.scheme}://{parts.netloc.lower()}{parts.path.rstrip("/")}'


def read_queries(path: Path, fields: list[str]) -> tuple[list[dict], str]:
    """The query items in file order, and the file's sha256. Only id, query and question are allowed."""
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise Refused(f'cannot read the queries file {path}: {error.strerror or type(error).__name__}') from None
    try:
        lines = raw.decode('utf-8-sig').splitlines()
        rows = [json.loads(line) for line in lines]
    except (UnicodeDecodeError, ValueError):
        raise Refused(f'the queries file {path} is not UTF-8 JSON lines') from None
    if not rows or not isinstance(rows[0], dict) or rows[0].get('w1') != 1 or set(rows[0]) - QUERY_HEADER_KEYS:
        raise Refused(f'the queries file {path} does not start with the W1 header line')
    header, items = rows[0], rows[1:]
    missing = [f for f in fields if f not in (header.get('fields') or [])]
    if missing:
        raise Refused(f'the queries file has no {", ".join(missing)} field')
    if header.get('count') != len(items):
        raise Refused(f'the queries file header says {header.get("count")} items, but it holds {len(items)}')
    seen = set()
    for number, item in enumerate(items, start=2):
        if not isinstance(item, dict) or set(item) != QUERY_ITEM_KEYS:
            raise Refused(f'line {number} of the queries file must hold exactly id, query and question')
        if not all(isinstance(item[k], str) and item[k].strip() for k in QUERY_ITEM_KEYS):
            raise Refused(f'line {number} of the queries file has an empty or non-text value')
        if item['id'] in seen:
            raise Refused(f'line {number} of the queries file repeats the id {item["id"]}')
        seen.add(item['id'])
    return items, hashlib.sha256(raw).hexdigest()


def retrieval_settings(args) -> dict:
    """Everything sent with each question, beside the question and the dataset ids."""
    checks = [
        (1 <= args.page_size <= RERANK_CANDIDATES, f'--page-size must be 1 to {RERANK_CANDIDATES}'),
        (0 <= args.similarity_threshold <= 1, '--similarity-threshold must be 0 to 1'),
        (0 <= args.vector_similarity_weight <= 1, '--vector-similarity-weight must be 0 to 1'),
        (1 <= args.top_k <= 2048, '--top-k must be 1 to 2048'),
    ]
    for ok, message in checks:
        if not ok:
            raise Refused(message)
    settings = {
        'page': 1,
        'page_size': args.page_size,
        'similarity_threshold': args.similarity_threshold,
        'vector_similarity_weight': args.vector_similarity_weight,
        'top_k': args.top_k,
        'rerank_candidates_count': RERANK_CANDIDATES,
        # Off, as in the canvas. Each would call a model on your server.
        'keyword': False, 'use_kg': False, 'toc_enhance': False, 'cross_languages': [], 'highlight': False,
    }
    if args.rerank_id:
        settings['rerank_id'] = args.rerank_id
    return settings


# HTTP --------------------------------------------------------------------------------------------

class Client:
    def __init__(self, base_url: str, key: str, *, timeout: float, max_attempts: int,
                 ca_file: str | None = None, sleep=time.sleep):
        self.base = base_url
        self._key = key
        self.timeout = timeout
        self.max_attempts = max_attempts
        self._sleep = sleep
        try:
            context = ssl.create_default_context(cafile=ca_file)
        except (OSError, ssl.SSLError) as error:
            raise Refused(f'cannot load --ca-file {ca_file}: {type(error).__name__}') from None
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(), urllib.request.HTTPSHandler(context=context))

    def __repr__(self) -> str:
        return 'Client(...)'

    def redact(self, text: str) -> str:
        text = ' '.join(str(text).replace(self._key, '[REDACTED]').split())
        return re.sub(r'(?i)\bbearer\s+\S+', 'Bearer [REDACTED]', text)[:200]

    def call(self, method: str, path: str, *, query: dict | None = None, body: dict | None = None,
             auth: bool = True) -> dict:
        """The one gate every request passes. Returns the JSON answer whose "code" is 0."""
        allowed = ROUTES.get((method, path))
        if allowed is None or set(query or {}) - allowed or (body is not None) != (method == 'POST'):
            raise Refused(f'refused {method} {path}: not one of the requests this script may send')
        url = self.base + path + ('?' + urllib.parse.urlencode(query) if query else '')
        headers = {'Accept': 'application/json', 'User-Agent': 'run_w1/1'}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if auth:
            headers['Authorization'] = f'Bearer {self._key}'
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self._answer(method, path, self._send(method, path, request))
            except _Retry as retry:
                if attempt == self.max_attempts:
                    raise Stop(f'{retry} (gave up after {attempt} attempts)') from None
                self._sleep(self._delay(attempt, retry.retry_after))
        raise AssertionError('unreachable')

    def _send(self, method: str, path: str, request) -> bytes:
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            status, retry_after = error.code, error.headers.get('Retry-After')
            error.close()  # the body is never read: it might repeat the request
            if 300 <= status < 400:
                raise Stop(f'{method} {path}: HTTP {status}, a redirect; redirects are refused') from None
            if status in (401, 403):
                raise Stop(f'{method} {path}: HTTP {status}, not authorised; check the key') from None
            if status in RETRY_STATUSES:
                raise _Retry(f'{method} {path}: HTTP {status}', retry_after) from None
            raise Stop(f'{method} {path}: HTTP {status}') from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLError):  # a certificate problem does not heal by retrying
                raise Stop(f'{method} {path}: TLS failed: {self.redact(error.reason)}') from None
            raise _Retry(f'{method} {path}: cannot reach the server: {self.redact(error.reason)}') from None
        except (http.client.HTTPException, OSError) as error:
            raise _Retry(f'{method} {path}: the connection failed ({type(error).__name__})') from None

    def _answer(self, method: str, path: str, raw: bytes) -> dict:
        try:
            payload = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            payload = None
        code = payload.get('code') if isinstance(payload, dict) else None
        if not isinstance(code, int) or isinstance(code, bool):
            raise Stop(f'{method} {path}: the answer ({len(raw)} bytes) is not RAGFlow JSON; check --base-url')
        if code != 0:
            message = self.redact(payload.get('message', ''))
            if code in AUTH_CODES:
                raise Stop(f'{method} {path}: the server refused the key (code {code}): {message}')
            raise ApiError(code, message)
        return payload

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        delay = min(30.0, 2.0 ** (attempt - 1))
        try:
            return max(delay, min(float(retry_after), 120.0)) if retry_after else delay
        except ValueError:
            return delay


# The run -----------------------------------------------------------------------------------------

def dataset_facts(client: Client, dataset_ids: list[str]) -> list[dict]:
    """Counts and settings of each dataset, for the header. Names are left out on purpose."""
    facts = []
    for dataset_id in dataset_ids:
        try:
            payload = client.call('GET', '/api/v1/datasets', query={'id': dataset_id})
        except ApiError as error:
            raise Stop(f'dataset {dataset_id}: {error}') from None
        data = payload.get('data')
        found = [d for d in data if isinstance(d, dict) and d.get('id') == dataset_id] if isinstance(data, list) else []
        if not found:
            raise Stop(f'dataset {dataset_id} is not among the datasets this key can read')
        d = found[0]
        facts.append({'id': dataset_id, 'document_count': d.get('document_count'), 'chunk_count': d.get('chunk_count'),
                      'embedding_model': embedding_model(d), 'chunk_method': d.get('chunk_method'),
                      'parser_config': d.get('parser_config')})
    return facts


def embedding_model(dataset: dict):
    """The model's name. v0.27.3 can hold an opaque tenant_model id in embedding_model and give the name
    beside it (dataset_api_service.py:508-510); v1.0.0-rc3 puts the name in embedding_model (crud.go:730)."""
    name = dataset.get('embedding_model_name')
    return name if isinstance(name, str) and name.strip() else dataset.get('embedding_model')


def server_version(client: Client) -> tuple[str | None, str | None]:
    try:
        payload = client.call('GET', '/api/v1/system/version', auth=False)
    except ApiError as error:
        return None, f'the version request failed: {error.short()}'
    except Stop as error:
        return None, f'the version request failed: {error}'
    version = payload.get('data')
    if isinstance(version, str) and version.strip():
        return version.strip()[:100], None
    return None, 'the version request answered without a version string'


def ranked_chunks(payload: dict) -> list[dict]:
    data = payload.get('data')
    chunks = data.get('chunks') if isinstance(data, dict) else None
    if not isinstance(chunks, list) or not all(isinstance(c, dict) for c in chunks):
        raise Stop('POST /api/v1/retrieval: the answer has no data.chunks list; this server is not '
                   'the RAGFlow version the script was written for')

    def first(chunk, *names):  # field names as of RAGFlow v0.27.3 (chunk_api.py:590-599), then older names
        return next((chunk[n] for n in names if isinstance(chunk.get(n), str)), None)

    def number(value):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    return [{
        'rank': rank,
        'content': first(c, 'content', 'content_with_weight'),
        'document_name': first(c, 'document_keyword', 'docnm_kwd', 'document_name'),
        'document_id': first(c, 'document_id', 'doc_id'),
        'chunk_id': first(c, 'id', 'chunk_id'),
        'similarity': number(c.get('similarity')),
        'vector_similarity': number(c.get('vector_similarity')),
        'term_similarity': number(c.get('term_similarity')),
    } for rank, c in enumerate(chunks, start=1)]


def run_queries(client: Client, plan: list[tuple[str, dict]], dataset_ids: list[str], settings: dict,
                rows: list[dict], log) -> None:
    """Send the queries one at a time, appending one row each to `rows`. Stop and Ctrl-C leave `rows` as far as it got."""
    for number, (field, item) in enumerate(plan, start=1):
        text = item[field]
        body = {'question': text, 'dataset_ids': dataset_ids, **settings}
        try:
            chunks, status, error = ranked_chunks(client.call('POST', '/api/v1/retrieval', body=body)), 'ok', None
            shown = f'{len(chunks)} chunks'
        except ApiError as failure:
            chunks, status, error, shown = [], 'error', failure.short(), str(failure)
        rows.append({'id': item['id'], 'field': field, 'sent': text, 'status': status, 'error': error,
                     'chunks': chunks})
        log(f'{number}/{len(plan)} {field} {item["id"]}: {shown}')


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def write_results(out: Path, header: dict, rows: list[dict], key: str, complete: bool) -> Path:
    """Write <out>.partial, then rename it to <out> only when every planned row was attempted."""
    text = ''.join(json.dumps(line, ensure_ascii=False) + '\n' for line in [header, *rows])
    text = text.replace(key, '[REDACTED]')  # a server could echo the key into a chunk; it is never written
    partial = out.with_name(out.name + '.partial')
    with open(partial, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    if not complete or out.exists():
        return partial
    os.replace(partial, out)
    return out


def list_datasets(client: Client, stdout) -> None:
    print('id\tname\tdocument_count\tchunk_count\tembedding_model\tchunk_method', file=stdout)
    seen = 0
    for page in range(1, 101):
        payload = client.call('GET', '/api/v1/datasets', query={'page': page, 'page_size': 30})
        data = payload.get('data')
        if not isinstance(data, list):
            raise Stop('GET /api/v1/datasets: the answer has no data list')
        for d in data:
            if isinstance(d, dict):
                values = (d.get('id'), d.get('name'), d.get('document_count'), d.get('chunk_count'),
                          embedding_model(d), d.get('chunk_method'))
                print('\t'.join('' if v is None else str(v) for v in values), file=stdout)
        seen += len(data)
        total = payload.get('total_datasets', payload.get('total'))
        if len(data) < 30 or (isinstance(total, int) and seen >= total):
            return


# Command line ------------------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse repeats what it cannot use: a key typed there stays off the screen
        super().error(re.sub(r'ragflow-\S+', 'ragflow-[REDACTED]', message))


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog='run_w1.py', allow_abbrev=False, description=__doc__,
                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--base-url', required=True,
                   help='your RAGFlow address, e.g. https://your-ragflow-host or http://localhost:9380')
    p.add_argument('--api-key-file', required=True, type=Path, help='a file holding your API key alone, on one line')
    p.add_argument('--dataset', action='append', default=[],
                   help='a dataset id as --list-datasets prints it; repeat for more (one embedding model for all)')
    p.add_argument('--queries', type=Path, default=HERE / 'w1-queries.jsonl',
                   help='the queries file (default: w1-queries.jsonl beside this script)')
    p.add_argument('--out', type=Path, default=Path('w1-results.jsonl'),
                   help='the results file; it must not exist (default: %(default)s in the current folder)')
    p.add_argument('--fields', default='query,question', help='which texts to send, in order (default: %(default)s)')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--list-datasets', action='store_true',
                      help='print your datasets on screen, which also tests the address and the key; write nothing')
    mode.add_argument('--dry-run', action='store_true',
                      help='check the inputs only and print the first request body; send nothing')
    p.add_argument('--page-size', type=int, default=PAGE_SIZE,
                   help='chunks returned per query, 1 to 64 (default: %(default)s, the canvas top_n)')
    p.add_argument('--similarity-threshold', type=float, default=SIMILARITY_THRESHOLD,
                   help='0 to 1 (default: %(default)s, as in the canvas)')
    p.add_argument('--vector-similarity-weight', type=float, default=VECTOR_SIMILARITY_WEIGHT,
                   help='0 to 1 (default: %(default)s, that is 1 - the canvas keyword weight 0.7)')
    p.add_argument('--top-k', type=int, default=TOP_K,
                   help='vector search candidates, 1 to 2048 (default: %(default)s, the agent tool default)')
    p.add_argument('--rerank-id', default='', help='a rerank model id (default: none, as in the canvas)')
    p.add_argument('--allow-insecure-http', action='store_true',
                   help='allow http:// to a host other than this machine; the key then travels unencrypted')
    p.add_argument('--ca-file', help='a CA bundle for a server with a private certificate')
    p.add_argument('--timeout', type=float, default=120.0, help='seconds per request (default: %(default)s)')
    p.add_argument('--max-attempts', type=int, default=5,
                   help='attempts per request on 429, 5xx, a dropped connection or a timeout, 1 to 10 '
                        '(default: %(default)s)')
    return p


def main(argv: list[str] | None = None, *, stdout=None, stderr=None, sleep=time.sleep) -> int:
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr

    def log(message: str) -> None:
        print(message, file=stderr, flush=True)

    args = build_parser().parse_args(argv)
    try:
        if not 0 < args.timeout <= 3600 or not 1 <= args.max_attempts <= 10:
            raise Refused('--timeout must be above 0 and at most 3600; --max-attempts must be 1 to 10')
        base = parse_base_url(args.base_url, args.allow_insecure_http)
        key = read_key(args.api_key_file)
        client = Client(base, key, timeout=args.timeout, max_attempts=args.max_attempts,
                        ca_file=args.ca_file, sleep=sleep)
        if args.list_datasets:
            list_datasets(client, stdout)
            return DONE
        fields = [f.strip() for f in args.fields.split(',')]
        if not fields or any(f not in FIELDS for f in fields) or len(set(fields)) != len(fields):
            raise Refused('--fields takes query, question or both, comma-separated, each once')
        if not args.dataset or any(not DATASET_ID.fullmatch(d) for d in args.dataset):
            raise Refused('give each dataset as --dataset <id>, 32 hex characters as --list-datasets prints it')
        dataset_ids = list(dict.fromkeys(args.dataset))
        items, queries_sha256 = read_queries(args.queries, fields)
        settings = retrieval_settings(args)
        out = args.out
        if out.exists() or out.with_name(out.name + '.partial').exists():
            raise Refused(f'{out} or {out.name}.partial already exists; move it away or choose another --out')
        if not out.resolve().parent.is_dir():
            raise Refused(f'the folder for --out {out} does not exist')
    except Refused as refusal:
        log(f'refused: {refusal}')
        return REFUSED
    except (Stop, ApiError) as stop:  # only --list-datasets sends anything above
        log(f'stopped: {stop}')
        return INCOMPLETE
    except KeyboardInterrupt:
        log('interrupted')
        return INTERRUPTED

    plan = [(field, item) for field in fields for item in items]  # all of one field, then the next
    if args.dry_run:
        first = {'question': plan[0][1][plan[0][0]], 'dataset_ids': dataset_ids, **settings}
        print(f'dry run: nothing was sent. A run sends {len(plan)} POST /api/v1/retrieval requests '
              f'({len(items)} items x {", ".join(fields)}), one at a time, to {base}', file=stdout)
        print('The first request body (the key travels only in the Authorization header):', file=stdout)
        print(json.dumps(first, ensure_ascii=False, indent=2), file=stdout)
        return DONE

    started, rows = now(), []
    header = {'w1': 1, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'queries_sha256': queries_sha256, 'started_at': started, 'finished_at': None}
    try:
        facts = dataset_facts(client, dataset_ids)
        version, version_note = server_version(client)
    except Stop as stop:
        log(f'stopped before any query was sent: {stop}')
        return INCOMPLETE
    except KeyboardInterrupt:
        log('interrupted before any query was sent; nothing was written')
        return INTERRUPTED
    result, reason = DONE, None
    try:
        run_queries(client, plan, dataset_ids, settings, rows, log)
    except Stop as stop:
        result, reason = INCOMPLETE, f'stopped: {stop}'
    except KeyboardInterrupt:
        result, reason = INTERRUPTED, 'interrupted'
    errors = sum(row['status'] == 'error' for row in rows)
    complete = len(rows) == len(plan)
    header['finished_at'] = now() if complete else None
    header['ragflow_version'] = version
    if version is None:
        header['ragflow_version_note'] = version_note
    header.update({'datasets': facts, 'settings': settings, 'fields': fields,
                   'counts': {'items': len(items), 'planned': len(plan), 'ok': len(rows) - errors,
                              'error': errors, 'not_run': len(plan) - len(rows)}})
    written = write_results(out, header, rows, key, complete)
    if reason:
        log(reason)
    if complete and written != out:
        log(f'{out} appeared during the run, so it was left as it was')
    if result == DONE and (errors or written != out):
        result = INCOMPLETE
    log(f'{len(rows) - errors} ok, {errors} error, {len(plan) - len(rows)} not run. Written: {written}')
    if written != out:
        log(f'{written.name} is not a complete result. Look at the reason above, then run again with a new --out.')
    return result


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
