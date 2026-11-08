"""Tests for run_w1.py against the local fake RAGFlow server. Nothing here contacts another host.

Run from tools/ragflow-w1:  python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import ssl
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fake_ragflow import (API_KEY, DATASET_ID, DATASET_NAME, EMBEDDING_ID, EMBEDDING_NAME, LEGACY_EMBEDDING,
                                OTHER_DATASET_ID, OWNER_NICKNAME, FakeRagflow, Scripted)
from tests.tls_cert import make_self_signed

TOOL_DIR = Path(__file__).resolve().parents[1]
RUN_W1 = TOOL_DIR / 'run_w1.py'
_spec = importlib.util.spec_from_file_location('run_w1', RUN_W1)
run_w1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_w1)

# Invented Arabic with harakat, tatweel, Arabic-Indic digits, a right-to-left mark and the
# presentation-form ligature U+FEFB. Not law text, not client data.
ITEMS = [
    {'id': 'test-01', 'query': 'العربونُ والعدولُ عن البيـــع ١٢٣',
     'question': 'دفعتُ عربوناً ثم عدلتُ عن الشراء؛ هل أستردّه؟‏'},
    {'id': 'test-02', 'query': 'ﻻ يجوز الإثبات بالشهادة',
     'question': 'متى لا تُقبل شهادة الشهود في الإثبات؟'},
]
HEADER = {'set': 'retrieval-v1', 'w1': 1, 'count': 2, 'fields': ['query', 'question'],
          'note': 'اختبار فقط. Test only.'}

# The Retrieval node of «IQRA LAW – FINAL REVIEW v3», as read from the canvas export on 2026-11-08
# (python -I, data only). It has no top_k key, so the tool default stands (agent/tools/retrieval.py:89).
CANVAS = {'top_n': 20, 'similarity_threshold': 0.2, 'keywords_similarity_weight': 0.7,
          'rerank_candidates_count': 64, 'rerank_id': ''}
TOOL_DEFAULT_TOP_K = 1024


def write_queries(folder: Path, items=ITEMS, header=HEADER) -> Path:
    path = folder / 'w1-queries.jsonl'
    lines = [header, *items]
    path.write_bytes(''.join(json.dumps(line, ensure_ascii=False) + '\n' for line in lines).encode('utf-8'))
    return path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = FakeRagflow()
        self.fake.__enter__()
        self.addCleanup(self.fake.__exit__)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.key_file = self.dir / 'ragflow.key'
        self.key_file.write_text(API_KEY + '\n', encoding='utf-8')
        self.queries = write_queries(self.dir)
        self.out = self.dir / 'w1-results.jsonl'
        self.sleeps: list[float] = []

    def argv(self, *extra: str, base_url: str | None = None) -> list[str]:
        return ['--base-url', base_url or self.fake.base_url, '--api-key-file', str(self.key_file),
                '--dataset', DATASET_ID, '--queries', str(self.queries), '--out', str(self.out), *extra]

    def run_main(self, argv: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run_w1.main(argv, stdout=stdout, stderr=stderr, sleep=self.sleeps.append)
        return code, stdout.getvalue(), stderr.getvalue()

    def posts(self) -> list:
        return self.fake.recorded('POST', '/api/v1/retrieval')


class RequestShape(Base):
    def test_first_request_body_holds_the_query_and_the_canvas_settings(self):
        code, _, _ = self.run_main(self.argv())

        self.assertEqual(code, 0)
        self.assertEqual(self.posts()[0].body, {
            'question': ITEMS[0]['query'], 'dataset_ids': [DATASET_ID], 'page': 1, 'page_size': 20,
            'similarity_threshold': 0.2, 'vector_similarity_weight': 0.3, 'top_k': 1024,
            'rerank_candidates_count': 64, 'keyword': False, 'use_kg': False, 'toc_enhance': False,
            'cross_languages': [], 'highlight': False})

    def test_key_goes_only_in_the_authorization_header_and_never_to_the_version_route(self):
        self.run_main(self.argv())

        keyed = self.posts() + self.fake.recorded('GET', '/api/v1/datasets')
        version = self.fake.recorded('GET', '/api/v1/system/version')
        self.assertTrue(all(r.headers.get('Authorization') == f'Bearer {API_KEY}' for r in keyed))
        self.assertTrue(all(r.headers.get('Content-Type') == 'application/json' for r in self.posts()))
        self.assertEqual([r.headers.get('Authorization') for r in version], [None])
        self.assertFalse(any(API_KEY in json.dumps(r.body, ensure_ascii=False) + json.dumps(r.query) for r in keyed))

    def test_default_settings_reproduce_the_canvas_retrieval_node(self):
        args = run_w1.build_parser().parse_args(['--base-url', 'https://x', '--api-key-file', 'k'])

        settings = run_w1.retrieval_settings(args)

        # retrieval.py:214-223: page 1, page_size = top_n, vector weight = 1 - keywords weight.
        self.assertEqual(settings['page'], 1)
        self.assertEqual(settings['page_size'], CANVAS['top_n'])
        self.assertEqual(settings['similarity_threshold'], CANVAS['similarity_threshold'])
        self.assertAlmostEqual(settings['vector_similarity_weight'], 1 - CANVAS['keywords_similarity_weight'])
        self.assertEqual(settings['top_k'], TOOL_DEFAULT_TOP_K)
        self.assertEqual(settings['rerank_candidates_count'], CANVAS['rerank_candidates_count'])
        self.assertNotIn('rerank_id', settings)

    def test_rerank_id_is_sent_when_given(self):
        self.run_main(self.argv('--rerank-id', 'bge-reranker@Fake'))

        self.assertEqual(self.posts()[0].body['rerank_id'], 'bge-reranker@Fake')

    def test_runs_every_item_on_the_query_field_then_on_the_question_field(self):
        self.run_main(self.argv())

        rows = read_jsonl(self.out)[1:]
        expected = [('query', 'test-01'), ('query', 'test-02'), ('question', 'test-01'), ('question', 'test-02')]
        self.assertEqual([(r['field'], r['id']) for r in rows], expected)
        self.assertEqual([p.body['question'] for p in self.posts()], [ITEMS[i][f] for f, i in
                                                                     [('query', 0), ('query', 1), ('question', 0), ('question', 1)]])

    def test_fields_option_runs_only_the_named_field(self):
        self.run_main(self.argv('--fields', 'question'))

        rows = read_jsonl(self.out)
        self.assertEqual(rows[0]['fields'], ['question'])
        self.assertEqual([r['sent'] for r in rows[1:]], [ITEMS[0]['question'], ITEMS[1]['question']])

    def test_a_base_url_path_prefix_is_kept_in_every_request(self):
        self.fake.prefix = '/ragflow'

        code, _, _ = self.run_main(self.argv(base_url=self.fake.base_url + '/ragflow/'))

        self.assertEqual(code, 0)
        self.assertEqual(len(self.fake.recorded('POST', '/ragflow/api/v1/retrieval')), 4)
        self.assertTrue(all(r.path.startswith('/ragflow/api/v1/') for r in self.fake.recorded()))

    def test_proxy_settings_in_the_environment_are_ignored(self):
        with FakeRagflow() as proxy:
            env = {k: v for k, v in os.environ.items() if k.lower() != 'no_proxy'}
            env.update({'HTTP_PROXY': proxy.base_url, 'HTTPS_PROXY': proxy.base_url})
            with mock.patch.dict(os.environ, env, clear=True):
                code, _, _ = self.run_main(self.argv())

            self.assertEqual(code, 0)
            self.assertEqual(proxy.recorded(), [])
            self.assertEqual(len(self.posts()), 4)


class Output(Base):
    def test_arabic_text_round_trips_unchanged(self):
        self.run_main(self.argv())

        raw = self.out.read_bytes()
        rows = read_jsonl(self.out)[1:]
        self.assertEqual(rows[0]['sent'], ITEMS[0]['query'])
        self.assertEqual(self.posts()[0].body['question'], ITEMS[0]['query'])
        self.assertTrue(rows[0]['chunks'][0]['content'].endswith(ITEMS[0]['query']))
        self.assertIn(ITEMS[1]['query'].encode('utf-8'), raw)  # written as UTF-8, not \\u escapes

    def test_output_carries_no_dataset_name_and_no_server_address(self):
        self.run_main(self.argv())

        text = self.out.read_text(encoding='utf-8')
        header = read_jsonl(self.out)[0]
        port = self.fake.base_url.rsplit(':', 1)[1]
        for absent in (DATASET_NAME, OWNER_NICKNAME, '127.0.0.1', 'localhost', f':{port}', self.fake.base_url):
            self.assertNotIn(absent, text)
        self.assertEqual(set(header['datasets'][0]), {'id', 'document_count', 'chunk_count', 'embedding_model',
                                                      'chunk_method', 'parser_config'})

    def test_rows_follow_the_contract_and_rank_from_one(self):
        self.run_main(self.argv())

        row = read_jsonl(self.out)[1]
        self.assertEqual(set(row), {'id', 'field', 'sent', 'status', 'error', 'chunks'})
        self.assertEqual((row['status'], row['error']), ('ok', None))
        self.assertEqual([c['rank'] for c in row['chunks']], [1, 2, 3])
        self.assertEqual(row['chunks'][0], {
            'rank': 1, 'content': f'نصٌّ تجريبيّ رقم 1 عن: {ITEMS[0]["query"]}', 'document_name': 'قانون تجريبي 1.md',
            'document_id': 'doc-01', 'chunk_id': 'chunk-01', 'similarity': 0.8,
            'vector_similarity': 0.7, 'term_similarity': 0.6})

    def test_header_records_version_hashes_settings_and_counts(self):
        self.run_main(self.argv())

        header = read_jsonl(self.out)[0]
        self.assertEqual(header['ragflow_version'], 'v0.27.3-fake')
        self.assertNotIn('ragflow_version_note', header)
        self.assertEqual(header['script_sha256'], hashlib.sha256(RUN_W1.read_bytes()).hexdigest())
        self.assertEqual(header['queries_sha256'], hashlib.sha256(self.queries.read_bytes()).hexdigest())
        self.assertEqual(header['settings'], {k: v for k, v in self.posts()[0].body.items()
                                              if k not in ('question', 'dataset_ids')})
        self.assertEqual(header['counts'], {'items': 2, 'planned': 4, 'ok': 4, 'error': 0, 'not_run': 0})
        self.assertIsNotNone(header['finished_at'])

    def test_missing_version_route_gives_null_and_a_note(self):
        self.fake.missing.add('/api/v1/system/version')

        code, _, _ = self.run_main(self.argv())

        header = read_jsonl(self.out)[0]
        self.assertEqual(code, 0)
        self.assertIsNone(header['ragflow_version'])
        self.assertIn('HTTP 404', header['ragflow_version_note'])

    def test_a_version_error_message_stays_out_of_the_header(self):
        self.fake.version_answer = {'code': 100, 'message': "ConnectionError('http://10.0.0.5:11434/api/embed')"}

        self.run_main(self.argv())

        header = read_jsonl(self.out)[0]
        self.assertIsNone(header['ragflow_version'])
        self.assertIn('code 100', header['ragflow_version_note'])
        self.assertNotIn('10.0.0.5', self.out.read_text(encoding='utf-8'))

    def test_header_names_the_embedding_model_rather_than_its_tenant_model_id(self):
        self.run_main(self.argv())

        dataset = read_jsonl(self.out)[0]['datasets'][0]
        self.assertEqual(dataset['embedding_model'], EMBEDDING_NAME)
        self.assertNotIn(EMBEDDING_ID, self.out.read_text(encoding='utf-8'))

    def test_header_keeps_a_legacy_embedding_model_name_when_none_is_resolved(self):
        argv = self.argv()
        argv[argv.index(DATASET_ID)] = OTHER_DATASET_ID

        self.run_main(argv)

        self.assertEqual(read_jsonl(self.out)[0]['datasets'][0]['embedding_model'], LEGACY_EMBEDDING)

    def test_header_takes_the_facts_of_the_dataset_asked_for_when_the_server_lists_more(self):
        self.fake.ignore_id_filter = True  # a server that ignores ?id= returns every dataset
        argv = self.argv()
        argv[argv.index(DATASET_ID)] = OTHER_DATASET_ID

        self.run_main(argv)

        dataset = read_jsonl(self.out)[0]['datasets'][0]
        self.assertEqual((dataset['id'], dataset['chunk_count'], dataset['chunk_method']), (OTHER_DATASET_ID, 0, 'laws'))

    def test_a_key_echoed_into_a_chunk_is_never_written(self):
        out = self.dir / 'direct.jsonl'
        rows = [{'id': 'x', 'chunks': [{'content': f'echo {API_KEY} echo'}]}]

        run_w1.write_results(out, {'w1': 1}, rows, API_KEY, complete=True)

        self.assertNotIn(API_KEY, out.read_text(encoding='utf-8'))


class Refusals(Base):
    def assertRefusedBeforeSending(self, argv: list[str], words: str):
        code, _, stderr = self.run_main(argv)
        self.assertEqual(code, 2)
        self.assertIn(words, stderr)
        self.assertEqual(self.fake.recorded(), [])

    def test_refuses_plain_http_to_another_host(self):
        self.assertRefusedBeforeSending(self.argv(base_url='http://ragflow.example.invalid'), 'plain http')

    def test_refuses_plain_http_to_a_name_under_localhost(self):
        # Windows asks DNS for such a name, so it is not this machine.
        self.assertRefusedBeforeSending(self.argv(base_url='http://w1.localhost:9380'), 'plain http')

    def test_a_key_given_as_the_key_file_path_is_not_repeated(self):
        argv = self.argv()
        argv[argv.index(str(self.key_file))] = API_KEY

        code, _, stderr = self.run_main(argv)

        self.assertEqual(code, 2)
        self.assertNotIn(API_KEY, stderr)

    def test_a_key_typed_after_an_unknown_option_is_not_repeated(self):
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as stop:
            run_w1.main(self.argv('--api-key', API_KEY))

        self.assertEqual(stop.exception.code, 2)
        self.assertIn('unrecognized arguments', stderr.getvalue())
        self.assertNotIn(API_KEY, stderr.getvalue())

    def test_refuses_an_abbreviated_option(self):
        argv = self.argv()
        argv[argv.index('--dataset')] = '--data'

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            run_w1.main(argv)

        self.assertEqual(stop.exception.code, 2)
        self.assertEqual(self.fake.recorded(), [])

    def test_refuses_an_empty_key_file(self):
        self.key_file.write_text('\n', encoding='utf-8')

        self.assertRefusedBeforeSending(self.argv(), 'is empty')

    def test_refuses_a_key_file_with_more_than_one_line(self):
        self.key_file.write_text(f'{API_KEY}\nsecond line\n', encoding='utf-8')

        self.assertRefusedBeforeSending(self.argv(), 'on one line')

    def test_refuses_to_overwrite_an_existing_out(self):
        self.out.write_text('keep me', encoding='utf-8')

        self.assertRefusedBeforeSending(self.argv(), 'already exists')
        self.assertEqual(self.out.read_text(encoding='utf-8'), 'keep me')

    def test_refuses_when_a_partial_file_from_an_earlier_run_exists(self):
        self.out.with_name(self.out.name + '.partial').write_text('earlier run', encoding='utf-8')

        self.assertRefusedBeforeSending(self.argv(), 'already exists')

    def test_refuses_an_out_folder_that_does_not_exist(self):
        argv = self.argv()
        argv[argv.index(str(self.out))] = str(self.dir / 'nowhere' / 'w1-results.jsonl')

        self.assertRefusedBeforeSending(argv, 'does not exist')

    def test_refuses_a_queries_header_with_a_key_outside_the_contract(self):
        self.queries = write_queries(self.dir, header=dict(HEADER, expected_notes='gold'))

        self.assertRefusedBeforeSending(self.argv(), 'W1 header')

    def test_refuses_a_queries_file_that_carries_expected_articles(self):
        leaked = [dict(ITEMS[0], expected=[{'law': 'evidence', 'number': 1, 'suffix': ''}]), ITEMS[1]]
        self.queries = write_queries(self.dir, items=leaked)

        self.assertRefusedBeforeSending(self.argv(), 'exactly id, query and question')

    def test_refuses_a_page_size_the_server_would_reject(self):
        self.assertRefusedBeforeSending(self.argv('--page-size', '65'), '--page-size')

    def test_refuses_a_dataset_id_that_is_not_32_hex_characters(self):
        argv = self.argv()
        argv[argv.index(DATASET_ID)] = 'my-dataset'

        self.assertRefusedBeforeSending(argv, '32 hex')

    def test_refuses_an_unknown_flag(self):
        result = subprocess.run([sys.executable, '-I', str(RUN_W1), *self.argv('--no-such-flag')],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=self.dir)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.fake.recorded(), [])

    def test_refuses_a_redirect_and_sends_nothing_to_its_target(self):
        with FakeRagflow() as elsewhere:
            self.fake.redirects['/api/v1/retrieval'] = elsewhere.base_url + '/api/v1/retrieval'

            code, _, stderr = self.run_main(self.argv())

            self.assertEqual(code, 1)
            self.assertIn('redirect', stderr)
            self.assertEqual(len(self.posts()), 1)
            self.assertEqual(elsewhere.recorded(), [])

    def test_gate_refuses_a_request_outside_the_allowlist(self):
        client = run_w1.Client(self.fake.base_url, API_KEY, timeout=5, max_attempts=1)
        outside = [('DELETE', '/api/v1/datasets', None, None),
                   ('GET', '/api/v1/datasets/x/documents', None, None),
                   ('GET', '/api/v1/datasets', {'name': 'x'}, None),
                   ('GET', '/api/v1/retrieval', None, None),
                   ('POST', '/api/v1/datasets', None, {'name': 'x'})]

        for method, path, query, body in outside:
            with self.subTest(method=method, path=path):
                with self.assertRaises(run_w1.Refused):
                    client.call(method, path, query=query, body=body)

        self.assertEqual(self.fake.recorded(), [])


class Failures(Base):
    def test_retries_a_503_then_succeeds(self):
        self.fake.scripted['/api/v1/retrieval'] = [Scripted(503)]

        code, _, _ = self.run_main(self.argv())

        self.assertEqual(code, 0)
        self.assertEqual(self.sleeps, [1.0])
        self.assertEqual(len(self.posts()), 5)
        self.assertTrue(all(r['status'] == 'ok' for r in read_jsonl(self.out)[1:]))

    def test_gives_up_after_the_last_attempt_and_leaves_only_a_partial_file(self):
        self.fake.scripted['/api/v1/retrieval'] = [Scripted(503) for _ in range(3)]

        code, _, _ = self.run_main(self.argv('--max-attempts', '3'))

        partial = self.out.with_name(self.out.name + '.partial')
        header = read_jsonl(partial)[0]
        self.assertEqual(code, 1)
        self.assertFalse(self.out.exists())
        self.assertIsNone(header['finished_at'])
        self.assertEqual(header['counts']['not_run'], 4)

    def test_a_refused_key_stops_at_the_first_request_without_retrying(self):
        self.key_file.write_text('not-the-right-key\n', encoding='utf-8')

        code, _, stderr = self.run_main(self.argv())

        self.assertEqual(code, 1)
        self.assertIn('not authorised', stderr)
        self.assertEqual(len(self.fake.recorded()), 1)
        self.assertFalse(self.out.exists())

    def test_a_server_error_on_one_query_is_recorded_and_the_run_goes_on(self):
        self.fake.api_errors[ITEMS[0]['question']] = {'code': 100, 'message': "Exception('boom')"}

        code, _, _ = self.run_main(self.argv())

        rows = read_jsonl(self.out)
        failed = [r for r in rows[1:] if r['status'] == 'error']
        self.assertEqual(code, 1)
        self.assertEqual([(r['field'], r['id'], r['chunks']) for r in failed], [('question', 'test-01', [])])
        self.assertIn('code 100', failed[0]['error'])
        self.assertEqual(rows[0]['counts']['error'], 1)

    def test_a_server_error_message_is_shown_on_screen_and_kept_out_of_the_file(self):
        # RAGFlow answers an exception with code 100 and repr(e) (api_utils.py:152), which can name his LAN.
        self.fake.api_errors[ITEMS[0]['query']] = {'code': 100,
                                                   'message': "ConnectionError('http://10.0.0.5:11434/api/embed')"}

        _, _, stderr = self.run_main(self.argv())

        failed = [r for r in read_jsonl(self.out)[1:] if r['status'] == 'error']
        self.assertEqual(failed[0]['error'], 'code 100 (exception); the message was shown on screen only')
        self.assertNotIn('10.0.0.5', self.out.read_text(encoding='utf-8'))
        self.assertIn('http://10.0.0.5:11434', stderr)

    def test_a_bare_key_in_a_server_message_is_not_shown(self):
        self.fake.echo_key_for.add(ITEMS[0]['query'])

        _, _, stderr = self.run_main(self.argv())

        self.assertIn('fake rejected key [REDACTED] here', stderr)
        self.assertNotIn(API_KEY, stderr)

    def test_another_bearer_token_in_a_server_message_is_not_shown(self):
        self.fake.api_errors[ITEMS[0]['query']] = {'code': 100, 'message': 'upstream said Bearer other-token-0123456789'}

        _, _, stderr = self.run_main(self.argv())

        self.assertIn('Bearer [REDACTED]', stderr)
        self.assertNotIn('other-token-0123456789', stderr)

    def test_an_authentication_code_in_the_answer_stops_the_run_at_once(self):
        self.fake.api_errors[ITEMS[0]['query']] = {'code': 109, 'message': 'Authentication error: API key is invalid!'}

        code, _, stderr = self.run_main(self.argv())

        self.assertEqual(code, 1)
        self.assertIn('refused the key', stderr)
        self.assertEqual(len(self.posts()), 1)
        self.assertFalse(self.out.exists())

    def test_an_out_file_that_appears_during_the_run_is_left_alone(self):
        real = run_w1.ranked_chunks

        def someone_writes_out(payload):
            if not self.out.exists():
                self.out.write_text('written by someone else', encoding='utf-8')
            return real(payload)

        with mock.patch.object(run_w1, 'ranked_chunks', someone_writes_out):
            code, _, _ = self.run_main(self.argv())

        self.assertEqual(code, 1)
        self.assertEqual(self.out.read_text(encoding='utf-8'), 'written by someone else')
        self.assertEqual(read_jsonl(self.out.with_name(self.out.name + '.partial'))[0]['counts']['ok'], 4)

    def test_ctrl_c_writes_a_partial_file_and_exits_130(self):
        real = run_w1.ranked_chunks
        calls = []

        def interrupt_on_second(payload):
            calls.append(1)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return real(payload)

        with mock.patch.object(run_w1, 'ranked_chunks', interrupt_on_second):
            code, _, _ = self.run_main(self.argv())

        partial = read_jsonl(self.out.with_name(self.out.name + '.partial'))
        self.assertEqual(code, 130)
        self.assertEqual(partial[0]['counts'], {'items': 2, 'planned': 4, 'ok': 1, 'error': 0, 'not_run': 3})
        self.assertFalse(self.out.exists())


class Modes(Base):
    def test_dry_run_sends_nothing_writes_nothing_and_shows_the_first_body(self):
        code, stdout, _ = self.run_main(self.argv('--dry-run'))

        self.assertEqual(code, 0)
        self.assertEqual(self.fake.recorded(), [])
        self.assertFalse(self.out.exists())
        self.assertIn(ITEMS[0]['query'], stdout)
        self.assertIn('"page_size": 20', stdout)
        self.assertNotIn(API_KEY, stdout)

    def test_list_datasets_prints_names_sends_one_kind_of_request_and_writes_nothing(self):
        before = sorted(p.name for p in self.dir.iterdir())

        code, stdout, _ = self.run_main(self.argv('--list-datasets'))

        self.assertEqual(code, 0)
        self.assertIn(DATASET_NAME, stdout)
        self.assertEqual({(r.method, r.path) for r in self.fake.recorded()}, {('GET', '/api/v1/datasets')})
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)

    def test_list_datasets_shows_the_embedding_model_name(self):
        _, stdout, _ = self.run_main(self.argv('--list-datasets'))

        self.assertIn(EMBEDDING_NAME, stdout)
        self.assertIn(LEGACY_EMBEDDING, stdout)
        self.assertNotIn(EMBEDDING_ID, stdout)


class Tls(Base):
    """A fake that speaks https with a fresh self-signed certificate the system does not trust."""

    def setUp(self):
        super().setUp()
        self.cert, key = make_self_signed(self.dir)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, key)
        self.secure = FakeRagflow(tls=context)
        self.secure.__enter__()
        self.addCleanup(self.secure.__exit__)

    def test_an_untrusted_certificate_stops_the_run_at_once_and_sends_nothing(self):
        code, _, stderr = self.run_main(self.argv(base_url=self.secure.base_url))

        self.assertEqual(code, 1)
        self.assertIn('TLS failed', stderr)
        self.assertEqual(self.sleeps, [])  # no retry
        self.assertEqual(self.secure.recorded(), [])
        self.assertFalse(self.out.exists())

    def test_ca_file_lets_a_private_certificate_through(self):
        code, _, _ = self.run_main(self.argv('--ca-file', str(self.cert), base_url=self.secure.base_url))

        self.assertEqual(code, 0)
        self.assertEqual(len(self.secure.recorded('POST', '/api/v1/retrieval')), 4)


class Subprocess(Base):
    def test_key_never_appears_in_stdout_stderr_or_the_output_when_run_isolated(self):
        self.fake.key_in_chunk_for.add(ITEMS[0]['query'])
        self.fake.echo_auth_for.add(ITEMS[1]['question'])

        # -I puts neither the script's folder nor the current one on sys.path; cwd is a foreign folder.
        result = subprocess.run([sys.executable, '-I', str(RUN_W1), *self.argv()], capture_output=True,
                                text=True, encoding='utf-8', errors='replace', cwd=self.dir, timeout=60)

        written = self.out.read_text(encoding='utf-8')
        self.assertEqual(result.returncode, 1)  # one query answered with an error
        self.assertIn('[REDACTED]', written)        # the key in a chunk
        self.assertIn('[REDACTED]', result.stderr)  # the key in the error message, shown on screen only
        for text in (result.stdout, result.stderr, written):
            self.assertNotIn(API_KEY, text)


if __name__ == '__main__':
    unittest.main()
