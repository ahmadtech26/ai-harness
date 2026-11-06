"""A local fake of the four RAGFlow HTTP routes the exporter reads. Tests only.

It binds to 127.0.0.1 on a free port, contacts nothing, and records every request it receives,
whatever the method. Its data is invented Arabic test text: not law text and not client data.

The response shapes follow the RAGFlow v0.x HTTP API reference as the tool's author understood it
({"code": 0, "data": ...}); they are not confirmed against a real server.
"""

from __future__ import annotations

import copy
import json
import re
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

# A fresh random value per test run, so nothing credential-like is stored in the source and a
# search of the output for it cannot match by accident.
API_KEY = 'ragflow-test-' + secrets.token_hex(16)

# Invented Arabic: harakat, hamza forms, Arabic punctuation, Arabic-Indic digits, tatweel,
# a right-to-left mark and a presentation-form ligature (U+FEFB).
ARABIC = [
    'نصٌّ اختباريّ: يُعاقَبُ المُخالِفُ وفقَ الشروطِ المتفقِ عليها؟ هذا ليس نصًّا قانونيًّا.',
    'أحكام، إحكام، احكام؛ ثلاث كتابات لكلمة واحدة — نص تجريبي.',
    'المدّعي والمدّعى عليه في الدعوى رقم ١٢٣/٢٠٢٦ (وقائع وهمية).',
    'قـــانون تجريبي‏: مادة ٧ — نصّ مختلق للاختبار فقط.',
    'ﻻ يجوز ذلك؛ مثال على حرف مركّب في نص تجريبي.',
    'الموكّل «فلان الفلاني» اسم وهمي، ولا يمثّل شخصًا حقيقيًّا.',
    'تنتهي المهلة بعد ثلاثين يومًا، والتاريخ ٠٤/١١/٢٠٢٦ مختلق.',
]


def _chunks(doc_id: str, texts: list[str]) -> list[dict]:
    return [{
        'id': f'{doc_id}-c{n:02d}',
        'content': text,
        'document_id': doc_id,
        'important_keywords': ['اختبار', 'تجريبي'],
        'positions': [],
        'available': True,
    } for n, text in enumerate(texts, start=1)]


def default_data() -> dict:
    lease_text = ('عقد إيجار — نموذج اختباري\n' + '\n'.join(ARABIC) + '\n').encode('utf-8')
    memo_pdf = b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n' + 'مذكرة دفاع تجريبية'.encode('utf-8') + b'\n%%EOF\n'
    documents = {
        'ds01laws': [
            {'id': 'doc01lease', 'name': 'نموذج عقد إيجار.txt', 'run': 'DONE', 'type': 'doc'},
            {'id': 'doc02memo', 'name': 'مذكرة دفاع ١٢٣.pdf', 'run': 'DONE', 'type': 'pdf'},
        ],
        'ds02clients': [
            {'id': 'doc03odd', 'name': 'عقد/إيجار: نموذج؟.docx', 'run': 'DONE', 'type': 'doc'},
            {'id': 'doc04hostile', 'name': '../../hostile.pdf', 'run': 'DONE', 'type': 'pdf'},
            {'id': 'doc05unparsed', 'name': 'صورة ممسوحة.png', 'run': 'UNSTART', 'type': 'visual'},
        ],
        'ds03empty': [],
    }
    blobs = {
        'doc01lease': lease_text,
        'doc02memo': memo_pdf,
        'doc03odd': b'PK\x03\x04' + 'مستند وورد تجريبي'.encode('utf-8'),
        'doc04hostile': b'%PDF-1.4\n' + 'اسم ملف عدائي'.encode('utf-8') + b'\n%%EOF\n',
        'doc05unparsed': b'\x89PNG\r\n\x1a\n' + bytes(range(256)),
    }
    chunks = {
        'doc01lease': _chunks('doc01lease', ARABIC),
        'doc02memo': _chunks('doc02memo', ARABIC[:2]),
        'doc03odd': _chunks('doc03odd', ARABIC[2:3]),
        'doc04hostile': _chunks('doc04hostile', ARABIC[5:6]),
        'doc05unparsed': [],
    }
    datasets = [
        {'id': 'ds01laws', 'name': 'مكتبة القوانين التجريبية', 'language': 'Arabic', 'chunk_method': 'laws'},
        {'id': 'ds02clients', 'name': 'ملفات الموكلين (وهمية)', 'language': 'Arabic', 'chunk_method': 'naive'},
        {'id': 'ds03empty', 'name': 'مجموعة فارغة', 'language': 'Arabic', 'chunk_method': 'naive'},
    ]
    data = {'datasets': datasets, 'documents': documents, 'blobs': blobs, 'chunks': chunks}
    refresh_counts(data)
    return data


def refresh_counts(data: dict) -> None:
    """Fill the counts a real server reports, from the data itself."""
    for dataset in data['datasets']:
        docs = data['documents'].get(dataset['id'], [])
        dataset['document_count'] = len(docs)
        dataset['chunk_count'] = sum(len(data['chunks'].get(d['id'], [])) for d in docs)
        for doc in docs:
            doc['dataset_id'] = dataset['id']
            doc['size'] = len(data['blobs'].get(doc['id'], b''))
            doc['chunk_count'] = len(data['chunks'].get(doc['id'], []))


CONTENT_TYPES = {'txt': 'text/plain; charset=utf-8', 'pdf': 'application/pdf', 'png': 'image/png',
                 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


@dataclass
class Recorded:
    method: str
    path: str
    query: dict
    authorization: str | None


@dataclass
class Scripted:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b'{"code": 500, "message": "scripted failure"}'


class FakeRagflow:
    """Start with `with FakeRagflow() as fake:` or `fake.start()` / `fake.stop()`."""

    def __init__(self, data: dict | None = None, prefix: str = ''):
        self.data = data if data is not None else default_data()
        self.prefix = prefix.rstrip('/')
        self.requests: list[Recorded] = []
        self.scripted: dict[str, list[Scripted]] = {}   # path -> responses served first, in order
        self.broken: dict[str, int] = {}                # path -> HTTP status served every time
        self.redirects: dict[str, str] = {}             # path -> Location of a 302
        self.api_errors: dict[str, dict] = {}           # path -> JSON body served with HTTP 200
        self.echo_auth: set[str] = set()                # paths whose error message repeats the header
        self.drop: dict[str, int] = {}                  # path -> times to close without answering
        self.truncate: dict[str, int] = {}              # document id -> times to cut the body short
        self.download_json_error: set[str] = set()      # document ids answered with a JSON error
        self.reported_chunk_count: dict[str, int] = {}  # document id -> chunk_count in the listing
        self.ignore_paging = False
        self.max_page_size: int | None = None
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(('127.0.0.1', 0), self._handler())
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={'poll_interval': 0.02},
                                        daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f'http://{host}:{port}{self.prefix}'

    def start(self) -> 'FakeRagflow':
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> 'FakeRagflow':
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def paths(self) -> list[str]:
        with self._lock:
            return [r.path for r in self.requests]

    def _record(self, handler: BaseHTTPRequestHandler) -> tuple[str, dict]:
        parts = urlsplit(handler.path)
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        with self._lock:
            self.requests.append(Recorded(handler.command, parts.path, query, handler.headers.get('Authorization')))
        return parts.path, query

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output clean
                pass

            def do_GET(self):
                path, query = fake._record(self)
                fake._serve(self, path, query)

            def _refuse(self):
                fake._record(self)
                self._send(405, {'Content-Type': 'application/json'}, b'{"code": 405, "message": "fake: GET only"}')

            do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _refuse

            def _send(self, status: int, headers: dict, body: bytes):
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)

        return Handler

    def _json(self, handler, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        handler._send(status, {'Content-Type': 'application/json'}, body)

    def _page(self, items: list, query: dict) -> list:
        page = 1 if self.ignore_paging else int(query.get('page', 1))
        size = int(query.get('page_size', 30))
        if self.max_page_size is not None:
            size = min(size, self.max_page_size)
        return items[(page - 1) * size: page * size]

    def _serve(self, handler, path: str, query: dict) -> None:
        if self.prefix:
            if not path.startswith(self.prefix + '/'):
                handler._send(404, {'Content-Type': 'text/html'}, b'<h1>not found</h1>')
                return
            path = path[len(self.prefix):]
        with self._lock:
            dropping = self.drop.get(path, 0)
            if dropping:
                self.drop[path] = dropping - 1
            scripted = self.scripted.get(path)
            response = scripted.pop(0) if scripted else None
        if dropping:
            handler.close_connection = True
            return
        if response is not None:
            handler._send(response.status, {'Content-Type': 'application/json', **response.headers}, response.body)
            return
        if path in self.broken:
            status = self.broken[path]
            self._json(handler, {'code': status, 'message': 'fake: broken'}, status)
            return
        if path in self.redirects:
            handler._send(302, {'Location': self.redirects[path]}, b'')
            return
        if handler.headers.get('Authorization') != f'Bearer {API_KEY}':
            self._json(handler, {'code': 109, 'message': 'Authentication error: API key is invalid!'})
            return
        if path in self.echo_auth:
            self._json(handler, {'code': 102, 'message': f"fake rejected header {handler.headers.get('Authorization')}"})
            return
        if path in self.api_errors:
            self._json(handler, self.api_errors[path])
            return
        if path == '/api/v1/system/version':
            self._json(handler, {'code': 0, 'data': 'v0.27.3-fake'})
            return
        if path == '/api/v1/datasets':
            self._json(handler, {'code': 0, 'data': copy.deepcopy(self._page(self.data['datasets'], query))})
            return
        match = re.fullmatch(r'/api/v1/datasets/([^/]+)/documents(?:/([^/]+)(/chunks)?)?', path)
        if not match or match.group(1) not in self.data['documents']:
            self._json(handler, {'code': 404, 'message': 'fake: no such route'}, 404)
            return
        dataset_id, doc_id, chunks = match.groups()
        docs = self.data['documents'][dataset_id]
        if doc_id is None:
            listed = copy.deepcopy(self._page(docs, query))
            for doc in listed:
                if doc['id'] in self.reported_chunk_count:
                    doc['chunk_count'] = self.reported_chunk_count[doc['id']]
            self._json(handler, {'code': 0, 'data': {'docs': listed, 'total': len(docs)}})
            return
        doc = next((d for d in docs if d['id'] == doc_id), None)
        if doc is None:
            self._json(handler, {'code': 102, 'message': "You don't own the document."})
            return
        if chunks:
            all_chunks = self.data['chunks'].get(doc_id, [])
            self._json(handler, {'code': 0, 'data': {'chunks': copy.deepcopy(self._page(all_chunks, query)),
                                                     'doc': copy.deepcopy(doc), 'total': len(all_chunks)}})
            return
        self._download(handler, doc)

    def _download(self, handler, doc: dict) -> None:
        doc_id = doc['id']
        if doc_id in self.download_json_error:
            self._json(handler, {'code': 102, 'message': 'Document not found!'})
            return
        blob = self.data['blobs'][doc_id]
        extension = doc['name'].rsplit('.', 1)[-1].lower()
        headers = {'Content-Type': CONTENT_TYPES.get(extension, 'application/octet-stream'),
                   'Content-Disposition': "attachment; filename*=UTF-8''ignored"}
        with self._lock:
            cutting = self.truncate.get(doc_id, 0)
            if cutting:
                self.truncate[doc_id] = cutting - 1
        if cutting:
            handler.send_response(200)
            for name, value in headers.items():
                handler.send_header(name, value)
            handler.send_header('Content-Length', str(len(blob)))
            handler.end_headers()
            handler.wfile.write(blob[: len(blob) // 2])
            handler.close_connection = True
            return
        handler._send(200, headers, blob)
