"""A local fake of the RAGFlow v0.27.3 routes rf_ingest.py sends to, plus TEI's /info. Tests only.

It binds to 127.0.0.1 on a free port, contacts nothing and records every request. Shapes follow the
v0.27.3 source as read on 2026-11-08 (paths under .hq/scratch/ragflow-src-v0.27.3/x/):
- answers are {"code", "message", "data"}; healthz is bare JSON (system_api.py:269-272);
- POST /users is refused with code 103 while registration is off (user_api.py:504-509);
- /system/status gives data.doc_engine.type (system_api.py:106-115, es_conn_base.py:72);
- POST /agents answers with the stored canvas, dsl included (agent_api.py:1022-1026, canvas_service.py:92-112);
- POST /datasets answers with the stored row, keys remapped (dataset_api_service.py:138-144, api_utils.py:639-644);
- the upload answers one document per «file» part (document_api.py:651-719), with pipeline_id from the
  dataset (file_service.py:664-680) and run "UNSTART";
- a parse sets each document RUNNING and sets chunk_count to 0 only for a DONE one, so a FAIL document parsed
  again keeps its count (document_api.py:1630-1633);
- documents list as {"total", "docs"} with run names (document_api.py:849-852, document_api_service.py:218-234);
- chunks list as {"total", "chunks", "doc"} (chunk_api.py:640-698); page_size above 100 is refused
  (pagination_utils.py:34-44).
It is not confirmed against a real server.

Each setting below makes one answer differ, so that each check rf_ingest.py makes of an answer has a
test that fails without it:
  health               healthz fields set to these values: HTTP 500 and status "nok" (api/utils/health_utils.py:486-487;
                       system_api.py:269-272)
  signup_message       the message of the code-103 sign-up refusal
  canvas_category      the category the pipeline is stored as
  store_dataset        fields of the stored dataset that differ from the request
  doc_overrides        name -> fields of that stored document (None removes the field), e.g. a renamed
                       duplicate «law-03(1).md» (file_service.py:647) or no pipeline_id
  parse_short          the parse answer counts this many documents fewer
  foreign_docs         this many documents that were not uploaded appear in the dataset
  doc_chunk_count_offset  name -> added to that document's chunk_count in the listing only
  chunk_count_steps    name -> the chunk_count that document holds on its first listings from the one where it
                       turns DONE, one per listing; after them it holds its stored count. v0.27.3 marks a
                       pipeline document DONE before it sets chunk_count (rag/flow/pipeline.py:107-125,
                       api/db/services/document_service.py:1162-1180,
                       rag/svr/task_executor_refactor/dataflow_service.py:161-181)
  dataset_offsets      field -> added to the dataset's document_count or chunk_count only
  redirect             path -> answered with HTTP 302 to that path of the fake

The provider routes of the hosted run (register_hosted.py; v0.27.3 api/apps/restful_apis/provider_api.py and
api/apps/services/provider_api_service.py): PUT /providers adds a provider once (:217-239, «already exists» after);
POST .../instances with only instance_name makes an instance with no key (:725-753, never «default»); PUT
.../instances/<i> needs instance_name, api_key, base_url and model_info (provider_api.py:633-636) and stores them;
GET .../instances lists names only (:756-786); GET .../instances/<i> answers with the stored key (:1117), the route
the tools must never send; POST .../connection answers as `connection_message` says. A dataset whose embedding_model
is «<model>@<instance>@<factory>» is created only when that instance holds that model as an embedding model and a
key, as verify_embedding_availability resolves it (api/utils/api_utils.py:516-562).
  provider_exists      the provider OpenRouter is already added
  echo_key_on_instance the PUT of an instance fails with a message that repeats the key it was sent
  connection_message   None: the connection check succeeds; else it fails with this message, in which «{key}»
                       becomes the key it was sent
"""

from __future__ import annotations

import email.parser
import email.policy
import json
import re
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

API_KEY = 'ragflow-w2test' + secrets.token_urlsafe(24)
TEI_MODEL_ID = '/data/Qwen/Qwen3-Embedding-0.6B'


@dataclass
class Recorded:
    method: str
    path: str
    query: dict
    headers: dict
    body: bytes


def chunk_texts(data: bytes) -> list[str]:
    """Invented chunking for the fake: one chunk per «### » block."""
    blocks, current = [], []
    for line in data.decode('utf-8').split('\n'):
        if line.startswith('### ') and current:
            blocks.append('\n'.join(current) + '\n')
            current = []
        if line.strip():
            current.append(line)
    if current:
        blocks.append('\n'.join(current) + '\n')
    return blocks


class FakeRagflowW2:
    def __init__(self, *, engine='elasticsearch', version='v0.27.3', register_enabled=0, existing_datasets=0,
                 fail=None, extra_chunks=None, unstable_paging=None, alter_dsl=False, echo_key_on_dataset=False,
                 tei_model_id=TEI_MODEL_ID, health=None, signup_message='User registration is disabled!',
                 canvas_category=None, store_dataset=None, doc_overrides=None, parse_short=0, foreign_docs=0,
                 doc_chunk_count_offset=None, dataset_offsets=None, redirect=None, chunk_count_steps=None,
                 provider_exists=False, echo_key_on_instance=False, connection_message=None):
        self.engine, self.version, self.register_enabled = engine, version, register_enabled
        self.fail = dict(fail or {})              # name -> number of parse rounds that fail
        self.extra_chunks = dict(extra_chunks or {})  # name -> extra invented chunks
        self.unstable_paging = dict(unstable_paging or {})  # name -> dumps that repeat one chunk, drop one
        self.alter_dsl, self.echo_key_on_dataset, self.tei_model_id = alter_dsl, echo_key_on_dataset, tei_model_id
        self.health, self.signup_message, self.canvas_category = dict(health or {}), signup_message, canvas_category
        self.store_dataset, self.doc_overrides = dict(store_dataset or {}), dict(doc_overrides or {})
        self.parse_short, self.foreign_docs = parse_short, foreign_docs
        self.doc_chunk_count_offset = dict(doc_chunk_count_offset or {})
        self.chunk_count_steps = {k: list(v) for k, v in (chunk_count_steps or {}).items()}
        self.dataset_offsets, self.redirect = dict(dataset_offsets or {}), dict(redirect or {})
        self.providers = {'OpenRouter': {}} if provider_exists else {}  # name -> instance name -> stored fields
        self.echo_key_on_instance, self.connection_message = echo_key_on_instance, connection_message
        self.requests: list[Recorded] = []
        self.agents, self.datasets, self.docs, self.chunks = {}, {}, {}, {}
        for n in range(existing_datasets):
            self.datasets[secrets.token_hex(16)] = {'name': f'old-{n}', 'document_count': 0, 'chunk_count': 0}
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(('127.0.0.1', 0), self._handler())
        self.url = f'http://127.0.0.1:{self._server.server_address[1]}'

    def __enter__(self):
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()

    def paths(self) -> list[tuple[str, str]]:
        return [(r.method, r.path) for r in self.requests]

    # --- request handling -------------------------------------------------------------------------

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _serve(self, method):
                parts = urlsplit(self.path)
                length = int(self.headers.get('Content-Length') or 0)
                body = self.rfile.read(length) if length else b''
                rec = Recorded(method, parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()},
                               {k: v for k, v in self.headers.items()}, body)
                with fake._lock:
                    fake.requests.append(rec)
                    status, payload, *extra = fake.route(rec)
                raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                for name, value in (extra[0] if extra else {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._serve('GET')

            def do_POST(self):
                self._serve('POST')

            def do_PUT(self):
                self._serve('PUT')

        return Handler

    @staticmethod
    def ok(data=None):
        return 200, {'code': 0, 'message': 'success', 'data': data}

    @staticmethod
    def err(code, message):
        return 200, {'code': code, 'message': message, 'data': False}

    def route(self, r: Recorded):
        anonymous = {'/api/v1/system/version', '/api/v1/system/healthz', '/api/v1/system/config',
                     '/api/v1/users', '/info'}
        if r.path in self.redirect:
            return 302, {'code': 0, 'message': 'moved', 'data': None}, {'Location': self.url + self.redirect[r.path]}
        if r.path not in anonymous and r.headers.get('Authorization') != f'Bearer {API_KEY}':
            return 401, {'code': 401, 'message': 'Unauthorized', 'data': None}
        if r.method == 'GET' and r.path == '/info':
            return 200, {'model_id': self.tei_model_id, 'max_input_length': 32768}
        if r.method == 'GET' and r.path == '/api/v1/system/version':
            return self.ok(self.version)
        if r.method == 'GET' and r.path == '/api/v1/system/healthz':
            health = dict({'db': 'ok', 'redis': 'ok', 'doc_engine': 'ok', 'storage': 'ok'}, **self.health)
            healthy = all(v == 'ok' for v in health.values())
            return (200 if healthy else 500), dict(health, status='ok' if healthy else 'nok')
        if r.method == 'GET' and r.path == '/api/v1/system/config':
            return self.ok({'registerEnabled': self.register_enabled, 'disablePasswordLogin': False})
        if r.method == 'POST' and r.path == '/api/v1/users':
            if self.register_enabled:
                return self.ok({'id': secrets.token_hex(16)})
            return self.err(103, self.signup_message)
        if r.method == 'GET' and r.path == '/api/v1/system/status':
            return self.ok({'doc_engine': {'type': self.engine, 'status': 'green'}})
        if r.method == 'POST' and r.path == '/api/v1/agents':
            return self.create_agent(json.loads(r.body))
        if r.path == '/api/v1/datasets':
            if r.method == 'POST':
                return self.create_dataset(json.loads(r.body))
            if 'id' in r.query:
                return self.ok([self.dataset_view(r.query['id'])] if r.query['id'] in self.datasets else [])
            return self.ok([self.dataset_view(i) for i in self.datasets])
        m = re.fullmatch(r'/api/v1/datasets/([0-9a-f]{32})/documents(/parse)?', r.path)
        if m and m.group(1) in self.datasets:
            if r.method == 'POST' and m.group(2):
                return self.parse(m.group(1), json.loads(r.body))
            if r.method == 'POST':
                return self.upload(m.group(1), r)
            return self.list_docs(m.group(1), r.query)
        m = re.fullmatch(r'/api/v1/datasets/([0-9a-f]{32})/documents/([0-9a-f]{32})/chunks', r.path)
        if m and r.method == 'GET' and m.group(2) in self.docs:
            return self.list_chunks(m.group(2), r.query)
        if r.method == 'PUT' and r.path == '/api/v1/providers':
            return self.add_provider(json.loads(r.body))
        m = re.fullmatch(r'/api/v1/providers/([^/]+)/(instances|connection)(?:/([^/]+))?', r.path)
        if m and m.group(2) == 'connection' and r.method == 'POST' and not m.group(3):
            return self.connection(json.loads(r.body))
        if m and m.group(2) == 'instances' and not m.group(3) and r.method == 'POST':
            return self.create_instance(m.group(1), json.loads(r.body))
        if m and m.group(2) == 'instances' and not m.group(3) and r.method == 'GET':
            return self.ok([{'instance_name': name} for name in self.providers.get(m.group(1), {})])
        if m and m.group(2) == 'instances' and m.group(3) and r.method in ('PUT', 'GET'):
            instance = self.providers.get(m.group(1), {}).get(m.group(3))
            if instance is None:
                return self.err(102, f'No instance found for provider {m.group(1)!r} and instance {m.group(3)!r}')
            if r.method == 'GET':  # show_provider_instance: the stored key, in clear
                return self.ok({'instance_name': m.group(3), **instance})
            return self.update_instance(instance, json.loads(r.body))
        return 404, {'code': 404, 'message': 'no such route in the fake', 'data': None}

    def add_provider(self, body):
        name = body.get('provider_name')
        if name in self.providers:
            return self.err(102, f'Provider {name} already exists')
        if name != 'OpenRouter':
            return self.err(102, f"Provider '{name}' is not allowed")
        self.providers[name] = {}
        return self.ok(None)

    def create_instance(self, provider, body):
        if provider not in self.providers:
            return self.err(102, f"Provider '{provider}' does not exist")
        if set(body) != {'instance_name'}:
            return self.err(102, 'the fake makes name-only instances only')
        name = body['instance_name']
        if name == 'default' or not re.fullmatch(r'[0-9A-Za-z_-]+', name):
            return self.err(101, "Instance name cannot be 'default'" if name == 'default' else 'bad instance name')
        if name in self.providers[provider]:
            return self.err(102, f'Instance {name} already exists')
        self.providers[provider][name] = {'api_key': '', 'base_url': '', 'models': [], 'verify': None}
        return self.ok(None)

    def update_instance(self, instance, body):
        missing = [k for k in ('instance_name', 'api_key', 'base_url', 'model_info') if k not in body]
        if missing:
            return self.err(101, f'Missing required fields: {", ".join(missing)}')
        if self.echo_key_on_instance:
            return self.err(102, f'cannot store {body["api_key"]} for Bearer {API_KEY}')
        instance.update(api_key=body['api_key'], base_url=body['base_url'], verify=body.get('verify', True),
                        models=[(m['model_name'], tuple(m['model_type'])) for m in body['model_info']])
        return self.ok(None)

    def connection(self, body):
        if 'api_key' not in body:
            return self.err(101, 'api_key is required')
        if self.connection_message is not None:
            return self.err(102, self.connection_message.replace('{key}', body['api_key']))
        return self.ok(None)

    def create_agent(self, body):
        if body.get('dsl') is None or body.get('title') is None:
            return self.err(101, 'No DSL data in request.')
        dsl = json.loads(json.dumps(body['dsl']))
        if self.alter_dsl:
            first = next(iter(dsl['components'].values()))
            first['obj']['params']['injected'] = True
        aid = secrets.token_hex(16)
        self.agents[aid] = {'id': aid, 'title': body['title'], 'dsl': dsl,
                            'canvas_category': self.canvas_category or body.get('canvas_category') or 'agent_canvas'}
        return self.ok(self.agents[aid])

    def create_dataset(self, body):
        if 'chunk_method' in body or body.get('parse_type') in (None, 1) or body.get('pipeline_id') not in self.agents:
            return self.err(101, 'parser_id provided or pipeline fields missing')
        if str(body.get('embedding_model')).count('@') == 2:  # <model>@<instance>@<factory>
            model, instance, factory = body['embedding_model'].rsplit('@', 2)
            held = self.providers.get(factory, {}).get(instance)
            if not held or not held['api_key'] or (model, ('embedding',)) not in held['models']:
                return self.err(102, f'Unsupported model {body["embedding_model"]}')
        did = secrets.token_hex(16)
        self.datasets[did] = {'name': body['name'], 'embedding_model': body['embedding_model'],
                              'pipeline_id': body['pipeline_id'], 'language': body.get('language', 'English'),
                              'chunk_method': 'naive', 'document_count': 0, 'chunk_count': 0}
        self.datasets[did].update(self.store_dataset)
        if self.echo_key_on_dataset:
            return self.err(102, f'something failed for Bearer {API_KEY}, {API_KEY} and Bearer eyJ-other-session-token')
        return self.ok(self.dataset_view(did))

    def dataset_view(self, did):
        ds = dict(self.datasets[did], id=did)
        mine = [d for d in self.docs.values() if d['dataset_id'] == did]
        if mine:
            ds['document_count'] = len(mine)
            ds['chunk_count'] = sum(d['chunk_count'] for d in mine)
        for field, offset in self.dataset_offsets.items():
            ds[field] += offset
        return ds

    def upload(self, did, r: Recorded):
        message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            b'Content-Type: ' + r.headers['Content-Type'].encode('ascii') + b'\r\n\r\n' + r.body)
        out = []
        for part in message.iter_parts():
            if part.get_param('name', header='content-disposition') != 'file':
                return self.err(101, 'No file part!')
            name, data = part.get_filename(), part.get_payload(decode=True)
            doc_id = secrets.token_hex(16)
            doc = {'id': doc_id, 'dataset_id': did, 'name': name, 'size': len(data),
                   'pipeline_id': self.datasets[did]['pipeline_id'], 'run': 'UNSTART',
                   'progress': 0.0, 'chunk_count': 0, 'progress_msg': '', 'data': data, 'polls': 0, 'rounds': 0}
            for field, value in self.doc_overrides.get(name, {}).items():
                if value is None:
                    doc.pop(field, None)
                else:
                    doc[field] = value
            self.docs[doc_id] = doc
            self.chunks[doc_id] = chunk_texts(data) + [f'### extra {n}\n' for n in range(self.extra_chunks.get(name, 0))]
            out.append({k: v for k, v in doc.items() if k not in ('data', 'polls', 'rounds')})
        for n in range(self.foreign_docs):  # not in the upload answer: another client's, say
            doc_id = secrets.token_hex(16)
            self.docs[doc_id] = {'id': doc_id, 'dataset_id': did, 'name': f'foreign-{n}.md', 'size': 1,
                                 'pipeline_id': self.datasets[did]['pipeline_id'], 'run': 'DONE', 'progress': 1.0,
                                 'chunk_count': 0, 'progress_msg': '', 'data': b'', 'polls': 0, 'rounds': 0}
            self.chunks[doc_id] = []
        return self.ok(out)

    def parse(self, did, body):
        ids = body.get('document_ids') or []
        for i in ids:
            d = self.docs[i]
            if d['run'] == 'DONE':  # v0.27.3 clears the count of a DONE document only
                d['chunk_count'] = 0
            d.update(run='RUNNING', progress=0.05, polls=1)
            d.pop('late', None)
            d['rounds'] += 1
        return self.ok({'success_count': len(ids) - self.parse_short})

    def list_docs(self, did, query):
        if int(query.get('page_size', 30)) > 100:
            return self.err(101, 'page_size must be less than or equal to 100')
        docs = []
        for d in self.docs.values():
            if d['dataset_id'] != did:
                continue
            if d['run'] == 'RUNNING':
                if d['polls'] > 0:
                    d['polls'] -= 1
                elif self.fail.get(d['name'], 0) >= d['rounds']:
                    d.update(run='FAIL', progress=-1, progress_msg=f'12:00:00 [ERROR]: embedding timed out\n'
                                                                    f'key echoed: {API_KEY}')
                else:
                    d.update(run='DONE', progress=1.0, chunk_count=len(self.chunks[d['id']]),
                             late=list(self.chunk_count_steps.get(d['name'], ())))
            if d['run'] == 'DONE' and 'late' in d:  # DONE before chunk_count is set (chunk_count_steps)
                if d['late']:
                    d['chunk_count'] = d['late'].pop(0)
                else:
                    d['chunk_count'] = len(self.chunks[d['id']])
                    del d['late']
            view = {k: v for k, v in d.items() if k not in ('data', 'polls', 'rounds', 'late')}
            if d['run'] == 'DONE' and d['name'] in self.doc_chunk_count_offset:
                view['chunk_count'] += self.doc_chunk_count_offset[d['name']]
            docs.append(view)
        return self.ok({'total': len(docs), 'docs': docs})

    def list_chunks(self, doc_id, query):
        page, size = int(query.get('page', 1)), int(query.get('page_size', 30))
        if size > 100:
            return self.err(101, 'page_size must be less than or equal to 100')
        texts = list(reversed(self.chunks[doc_id]))  # pipeline chunks carry no order field
        rows = [{'id': f'{doc_id[:8]}{n:08d}', 'content': t, 'document_id': doc_id, 'docnm_kwd': self.docs[doc_id]['name'],
                 'doc_type_kwd': 'text', 'available': True} for n, t in enumerate(texts)]
        name = self.docs[doc_id]['name']
        if self.unstable_paging.get(name, 0) > 0 and len(rows) > size:
            if page == 2:
                rows[size] = rows[size - 1]  # page 2 repeats the last chunk of page 1 and drops one
            if page * size >= len(rows):
                self.unstable_paging[name] -= 1
        return self.ok({'total': len(rows), 'chunks': rows[(page - 1) * size: page * size],
                        'doc': {'id': doc_id, 'name': self.docs[doc_id]['name']}})
