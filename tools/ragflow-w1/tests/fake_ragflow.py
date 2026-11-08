"""A local fake of the three RAGFlow routes run_w1.py sends to. Tests only.

It binds to 127.0.0.1 on a free port, contacts nothing, and records every request it receives,
whatever the method. Its text is invented Arabic: not law text and not client data.

Shapes follow the RAGFlow v0.27.3 source as read on 2026-11-08:
- POST /api/v1/retrieval: api/apps/restful_apis/chunk_api.py:393-604; chunk keys renamed at :590-599
  (chunk_id -> id, content_with_weight -> content, doc_id -> document_id, docnm_kwd -> document_keyword).
- GET /api/v1/datasets: dataset_api.py:318 and dataset_api_service.py:426-511 (keys remapped by
  api_utils.py:639-644; the total is "total_datasets", api_utils.py:314-315). "embedding_model" is the
  stored embd_id, which can be an opaque tenant_model id; "embedding_model_name" is the name resolved
  from it, or "" for a legacy name (dataset_api_service.py:508-510, tenant_model_service.py:554-582).
- GET /api/v1/system/version: system_api.py:44, no login.
- Errors: HTTP 200 with a non-zero "code" (api_utils.py:322-333); a missing or bad key is HTTP 401
  with code 401 (api/apps/__init__.py:273, :403-406).
They are not confirmed against a real server.
"""

from __future__ import annotations

import json
import secrets
import ssl
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

# A fresh value per run, so nothing credential-like is stored in the source.
API_KEY = 'ragflow-w1-test-' + secrets.token_hex(16)
DATASET_ID = '0123456789abcdef0123456789abcdef'
OTHER_DATASET_ID = 'fedcba9876543210fedcba9876543210'
DATASET_NAME = 'ملفات الموكل فلان السرية'   # a name the output must never carry
OWNER_NICKNAME = 'walid-fake-nickname'
EMBEDDING_ID = '5e1f0c2d3b4a59687766554433221100'   # a tenant_model id, as v0.27.3 can store it
EMBEDDING_NAME = 'bge-m3@default@Ollama'           # the name that id resolves to
LEGACY_EMBEDDING = 'bge-m3@Ollama'                  # a name stored before tenant models


def default_datasets() -> list[dict]:
    common = {'tenant_id': 'tenant-fake', 'nickname': OWNER_NICKNAME, 'language': 'Arabic'}
    return [
        {**common, 'id': DATASET_ID, 'name': DATASET_NAME, 'document_count': 5, 'chunk_count': 741,
         'embedding_model': EMBEDDING_ID, 'embedding_model_name': EMBEDDING_NAME,
         'chunk_method': 'naive', 'parser_config': {'chunk_token_num': 512, 'delimiter': '\n'}},
        {**common, 'id': OTHER_DATASET_ID, 'name': 'مجموعة أخرى', 'document_count': 0, 'chunk_count': 0,
         'embedding_model': LEGACY_EMBEDDING, 'embedding_model_name': '',
         'chunk_method': 'laws', 'parser_config': {}},
    ]


def chunks_for(question: str) -> list[dict]:
    """Three chunks whose text repeats the question, so a round trip can be checked."""
    return [{
        'id': f'chunk-{n:02d}',
        'content': f'نصٌّ تجريبيّ رقم {n} عن: {question}',
        'content_ltks': 'tokens not copied',
        'document_id': f'doc-{n:02d}',
        'document_keyword': f'قانون تجريبي {n}.md',
        'dataset_id': DATASET_ID,
        'important_keywords': [],
        'image_id': '',
        'similarity': round(0.9 - n / 10, 3),
        'vector_similarity': round(0.8 - n / 10, 3),
        'term_similarity': round(0.7 - n / 10, 3),
        'positions': [],
        'doc_type_kwd': '',
    } for n in (1, 2, 3)]


@dataclass
class Recorded:
    method: str
    path: str
    query: dict
    headers: dict
    body: object


@dataclass
class Scripted:
    status: int
    body: bytes = b'{"code": 500, "message": "scripted failure"}'
    headers: dict = field(default_factory=dict)


class FakeRagflow:
    """Use as `with FakeRagflow() as fake:`; `fake.base_url` is its address. With `tls`, it speaks https."""

    def __init__(self, tls: ssl.SSLContext | None = None):
        self.datasets = default_datasets()
        self.requests: list[Recorded] = []
        self.scripted: dict[str, list[Scripted]] = {}   # path -> answers served first, in order
        self.redirects: dict[str, str] = {}             # path -> Location of a 302
        self.api_errors: dict[str, dict] = {}           # question -> JSON body served with HTTP 200
        self.echo_auth_for: set[str] = set()            # questions whose error message repeats the header
        self.echo_key_for: set[str] = set()             # questions whose error message repeats the bare key
        self.key_in_chunk_for: set[str] = set()         # questions whose first chunk holds the bare key
        self.version_answer: dict | None = None         # served for the version route instead of the version
        self.ignore_id_filter = False                   # list every dataset whatever ?id= asks for
        self.missing: set[str] = set()                  # paths answered 404
        self.prefix = ''                                # a path prefix the routes sit under, e.g. '/ragflow'
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(('127.0.0.1', 0), self._handler())
        self._server.daemon_threads = True
        self._scheme = 'http'
        if tls is not None:  # the handshake runs in accept(); socketserver drops a failed one
            self._server.socket = tls.wrap_socket(self._server.socket, server_side=True)
            self._scheme = 'https'
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={'poll_interval': 0.02},
                                        daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f'{self._scheme}://{host}:{port}'

    def __enter__(self) -> 'FakeRagflow':
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()

    def recorded(self, method: str | None = None, path: str | None = None) -> list[Recorded]:
        with self._lock:
            return [r for r in self.requests if (method is None or r.method == method)
                    and (path is None or r.path == path)]

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _any(self):
                fake._serve(self)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _any

            def send(self, status: int, payload: object = None, headers: dict | None = None, raw: bytes | None = None):
                body = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)

        return Handler

    def _serve(self, h) -> None:
        parts = urlsplit(h.path)
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        length = int(h.headers.get('Content-Length') or 0)
        raw = h.rfile.read(length) if length else b''
        try:
            body = json.loads(raw.decode('utf-8')) if raw else None
        except ValueError:
            body = raw
        path = parts.path  # recorded as received, routed without the prefix
        route = path[len(self.prefix):] if path.startswith(self.prefix + '/') else ''
        with self._lock:
            self.requests.append(Recorded(h.command, path, query, dict(h.headers.items()), body))
            queue = self.scripted.get(route)
            scripted = queue.pop(0) if queue else None
        if scripted is not None:
            h.send(scripted.status, raw=scripted.body, headers=scripted.headers)
            return
        if route in self.redirects:
            h.send(302, raw=b'', headers={'Location': self.redirects[route]})
            return
        if route in self.missing:
            h.send(404, {'code': 404, 'message': f'Not Found: {path}', 'data': None, 'error': 'Not Found'})
            return
        if (h.command, route) == ('GET', '/api/v1/system/version'):
            h.send(200, self.version_answer or {'code': 0, 'message': 'success', 'data': 'v0.27.3-fake'})
            return
        if h.headers.get('Authorization') != f'Bearer {API_KEY}':
            h.send(401, {'code': 401, 'message': "<Unauthorized '401: Unauthorized'>", 'data': None})
            return
        if (h.command, route) == ('GET', '/api/v1/datasets'):
            listed = [d for d in self.datasets if self.ignore_id_filter or 'id' not in query or d['id'] == query['id']]
            page, size = int(query.get('page', 1)), int(query.get('page_size', 30))
            h.send(200, {'code': 0, 'data': listed[(page - 1) * size: page * size], 'total_datasets': len(listed)})
            return
        if (h.command, route) == ('POST', '/api/v1/retrieval') and isinstance(body, dict):
            question = str(body.get('question', ''))
            if question in self.echo_auth_for:
                h.send(200, {'code': 102, 'message': f"fake rejected header {h.headers.get('Authorization')}"})
                return
            if question in self.echo_key_for:
                h.send(200, {'code': 102, 'message': f'fake rejected key {API_KEY} here'})
                return
            if question in self.api_errors:
                h.send(200, self.api_errors[question])
                return
            chunks = chunks_for(question)[: int(body.get('page_size', 30))]
            if question in self.key_in_chunk_for:
                chunks[0]['content'] += f' {API_KEY}'
            h.send(200, {'code': 0, 'data': {'chunks': chunks, 'total': len(chunks),
                                             'doc_aggs': [{'doc_name': c['document_keyword'],
                                                           'doc_id': c['document_id'], 'count': 1} for c in chunks]}})
            return
        h.send(404, {'code': 404, 'message': f'Not Found: {path}', 'data': None, 'error': 'Not Found'})
