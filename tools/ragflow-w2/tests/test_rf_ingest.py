"""Tests for rf_ingest.py against the local fake RAGFlow (tests/fake_ragflow_w2.py). Nothing leaves 127.0.0.1.

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import email.parser
import email.policy
import hashlib
import importlib.util
import io
import json
import os
import re
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fake_ragflow_w2 import API_KEY, FakeRagflowW2

TOOL_DIR = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('rf_ingest', TOOL_DIR / 'rf_ingest.py')
rf_ingest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rf_ingest)

ENGINE = 'elasticsearch'
DIGEST = 'sha256:' + 'ab' * 32
ENV = {'W2_DOC_ENGINE': ENGINE, 'W2_TEI_MODEL': 'Qwen/Qwen3-Embedding-0.6B', 'W2_TEI_REVISION': 'c' * 40,
       'W2_EMBEDDING_BATCH_SIZE': '4', 'W2_RAGFLOW_IMAGE': f'infiniflow/ragflow:v0.27.3@{DIGEST}'}
CONTRACT_KEYS = {'w2', 'created_at', 'engine', 'embedder', 'ragflow_version', 'ragflow_image_digest', 'dataset_id',
                 'language', 'document_count', 'chunk_count', 'predicted_chunk_count', 'all_match', 'canvas_sha256',
                 'upload_manifest_sha256', 'file_shape', 'embedding_batch_size'}


def canvas_dsl() -> dict:
    def comp(name, down, params):
        return {'obj': {'component_name': name, 'params': params}, 'downstream': down, 'upstream': []}
    return {'components': {
        'File': comp('File', ['Parser:A'], {}),
        'Parser:A': comp('Parser', ['TitleChunker:B'], {'setups': {'markdown': {'output_format': 'json', 'suffix': ['md']}}}),
        'TitleChunker:B': comp('TitleChunker', ['Tokenizer:C'], {'method': 'group', 'hierarchy': 3, 'chunk_token_cap': 8000,
                                                                 'levels': [['^#\\s', '^##\\s', '^###\\s']]}),
        'Tokenizer:C': comp('Tokenizer', [], {'search_method': ['embedding', 'full_text'], 'fields': 'text',
                                              'filename_embd_weight': 0.1}),
    }, 'globals': {}, 'graph': {}}


def law_text(n: int, articles: int) -> bytes:
    body = ''.join(f'### المادة {k}\n\nنص تجريبي رقم {k} في القانون التجريبي {n}.\n\n' for k in range(1, articles + 1))
    return f'# قانون تجريبي {n}\n\n{body}'.encode('utf-8')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.in_dir, self.out = root / 'in', root / 'out' / ENGINE
        self.in_dir.mkdir()
        self.out.mkdir(parents=True)
        self.canvas = root / 'canvas.json'
        self.canvas.write_text(json.dumps(canvas_dsl(), ensure_ascii=False), encoding='utf-8')
        files = []
        for n in range(1, 23):
            data = law_text(n, 3 if n != 7 else 230)  # law-07 lists in three pages of chunks
            name = f'law-{n:02d}.md'
            (self.in_dir / name).write_bytes(data)
            files.append({'name': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
        self.files = files
        self.manifest = self.in_dir / 'upload-manifest.json'
        self.write_manifest()
        self.key_file = root / 'key'
        self.key_file.write_text(API_KEY + '\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def write_manifest(self):
        canvas_sha = hashlib.sha256(self.canvas.read_bytes()).hexdigest()
        self.manifest.write_text(json.dumps({'w2_upload': 1, 'file_shape': 'slug-title-served-v1',
                                             'canvas': {'sha256': canvas_sha}, 'files': self.files}),
                                 encoding='utf-8')

    def run_tool(self, fake, step='all', *extra, env=None):
        argv = [step, '--engine', ENGINE, '--base-url', fake.url, '--tei-url', fake.url,
                '--api-key-file', str(self.key_file)]
        if step in ('create', 'all'):
            argv += ['--canvas', str(self.canvas), '--in-dir', str(self.in_dir), '--upload-manifest', str(self.manifest)]
        if step != 'preflight':
            argv += ['--out', str(self.out)]
        out = io.StringIO()
        ticks = iter(range(0, 10 ** 6, 10))
        code = rf_ingest.main(argv + list(extra), stdout=out, environ=dict(ENV if env is None else env),
                              sleep=lambda s: None, clock=lambda: next(ticks))
        return code, out.getvalue()

    def refused_before_sending(self, fake, code):
        self.assertEqual(code, 2)
        self.assertEqual(fake.requests, [])

    def body_of(self, fake, method, path_end):
        return next(json.loads(r.body) for r in fake.requests if r.method == method and r.path.endswith(path_end))


class Routes(Base):
    def test_the_run_sends_the_cited_routes_in_order(self):
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.assertEqual(code, 0)
        firsts = list(dict.fromkeys((m, p if '/datasets/' not in p else p.split('/')[-1]) for m, p in fake.paths()))
        self.assertEqual(firsts[:12], [
            ('GET', '/api/v1/system/version'), ('GET', '/api/v1/system/healthz'), ('GET', '/api/v1/system/config'),
            ('POST', '/api/v1/users'), ('GET', '/api/v1/system/status'), ('GET', '/info'),
            ('GET', '/api/v1/datasets'), ('POST', '/api/v1/agents'), ('POST', '/api/v1/datasets'),
            ('POST', 'documents'), ('POST', 'parse'), ('GET', 'documents')])
        self.assertEqual(firsts[12:], [('GET', 'chunks')])

    def test_the_canvas_is_imported_as_it_is_as_a_dataflow_canvas(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake)

        body = self.body_of(fake, 'POST', '/api/v1/agents')
        self.assertEqual((body['dsl'], body['canvas_category']), (canvas_dsl(), 'dataflow_canvas'))

    def test_the_dataset_is_bound_to_the_pipeline_with_the_builtin_model_and_no_chunk_method(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake)

        body = self.body_of(fake, 'POST', '/api/v1/datasets')
        agent_id = next(iter(fake.agents))
        self.assertEqual(body, {'name': 'w2-laws-elasticsearch', 'embedding_model': 'Qwen/Qwen3-Embedding-0.6B@Builtin',
                                'parse_type': 2, 'pipeline_id': agent_id, 'language': 'English'})

    def test_the_upload_is_one_multipart_request_with_one_file_part_per_law(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake)

        upload = next(r for r in fake.requests if r.method == 'POST' and r.path.endswith('/documents'))
        message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            b'Content-Type: ' + upload.headers['Content-Type'].encode() + b'\r\n\r\n' + upload.body)
        parts = {p.get_filename(): p.get_payload(decode=True) for p in message.iter_parts()
                 if p.get_param('name', header='content-disposition') == 'file'}
        self.assertEqual(parts, {p.name: p.read_bytes() for p in self.in_dir.glob('*.md')})

    def test_the_key_goes_only_in_the_authorization_header_of_routes_that_need_it(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake)

        anonymous = {'/api/v1/system/version', '/api/v1/system/healthz', '/api/v1/system/config', '/api/v1/users', '/info'}
        for r in fake.requests:
            expected = None if r.path in anonymous else f'Bearer {API_KEY}'
            self.assertEqual(r.headers.get('Authorization'), expected, r.path)
            self.assertNotIn(API_KEY.encode(), r.body)

    def test_chunks_are_listed_in_pages_of_at_most_100(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake)

        sizes = {int(r.query['page_size']) for r in fake.requests if r.path.endswith('/chunks')}
        pages_of_law7 = [r.query['page'] for r in fake.requests
                         if r.path.endswith('/chunks') and fake.docs[r.path.split('/')[-2]]['name'] == 'law-07.md']
        self.assertEqual((sizes, pages_of_law7), ({100}, ['1', '2', '3']))


class Results(Base):
    def test_every_stored_chunk_is_dumped_once(self):
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        rows = [json.loads(x) for x in (self.out / 'chunks.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual(sorted((r['document_name'], r['content']) for r in rows),
                         sorted((fake.docs[d]['name'], t) for d, texts in fake.chunks.items() for t in texts))

    def test_the_manifest_holds_exactly_the_contract_keys_with_all_match_false(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake)

        m = json.loads((self.out / 'w2-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(set(m), CONTRACT_KEYS)
        self.assertEqual((m['w2'], m['all_match'], m['predicted_chunk_count'], m['document_count'], m['file_shape']),
                         (1, False, None, 22, 'slug-title-served-v1'))
        self.assertEqual(m['chunk_count'], sum(len(t) for t in fake.chunks.values()))

    def test_the_manifest_records_the_hashes_and_the_run_facts(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake)

        m = json.loads((self.out / 'w2-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(m['canvas_sha256'], hashlib.sha256(self.canvas.read_bytes()).hexdigest())
        self.assertEqual(m['upload_manifest_sha256'], hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        self.assertEqual((m['engine'], m['embedder'], m['ragflow_image_digest'], m['embedding_batch_size'],
                          m['dataset_id'], m['language'], m['ragflow_version']),
                         (ENGINE, {'name': 'Qwen/Qwen3-Embedding-0.6B', 'revision': 'c' * 40, 'via': 'builtin-tei'},
                          DIGEST, 4, next(iter(fake.datasets)), 'English', 'v0.27.3'))


class Polling(Base):
    def test_a_failed_document_alone_is_parsed_again(self):
        with FakeRagflowW2(fail={'law-05.md': 1}) as fake:
            code, out = self.run_tool(fake)

        rounds = [json.loads(r.body)['document_ids'] for r in fake.requests if r.path.endswith('/parse')]
        doc5 = next(i for i, d in fake.docs.items() if d['name'] == 'law-05.md')
        self.assertEqual(code, 0)
        self.assertEqual((len(rounds[0]), rounds[1:]), (22, [[doc5]]))
        self.assertIn('law-05.md: FAIL', out)

    def test_it_gives_up_after_two_rounds_of_parsing_again_and_writes_no_manifest(self):
        with FakeRagflowW2(fail={'law-05.md': 9}) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertEqual(sum(r.path.endswith('/parse') for r in fake.requests), 3)
        self.assertFalse((self.out / 'w2-manifest.json').exists())
        self.assertTrue((self.out / 'ingest-state.json').exists())

    def test_progress_lines_are_printed_while_waiting(self):
        with FakeRagflowW2() as fake:
            _, out = self.run_tool(fake)

        self.assertRegex(out, r'done 0, failed 0, waiting 22 of 22')
        self.assertRegex(out, r'done 22, failed 0, waiting 0 of 22; chunks so far')

    def test_wait_and_dump_can_be_run_again_from_the_state_file(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake, 'create')
            code_wait, _ = self.run_tool(fake, 'wait')
            code_dump, _ = self.run_tool(fake, 'dump')

        self.assertEqual((code_wait, code_dump), (0, 0))
        self.assertTrue((self.out / 'w2-manifest.json').exists())

    def test_an_unstable_chunk_listing_is_listed_again(self):
        with FakeRagflowW2(unstable_paging={'law-07.md': 1}) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 0)
        listed, total = map(int, re.search(r'law-07\.md: listed (\d+) unique of total (\d+)', out).groups())
        self.assertEqual(listed, total - 1)

    def test_a_chunk_listing_that_never_adds_up_writes_nothing(self):
        with FakeRagflowW2(unstable_paging={'law-07.md': 9}) as fake:
            code, _ = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertFalse((self.out / 'chunks.jsonl').exists())


class Refusals(Base):
    def test_an_upload_set_of_21_files_is_refused_even_when_the_manifest_lists_the_same_21(self):
        (self.in_dir / 'law-22.md').unlink()
        self.files = self.files[:21]
        self.write_manifest()
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.refused_before_sending(fake, code)

    def test_a_markdown_file_the_manifest_does_not_list_is_refused(self):
        (self.in_dir / 'extra.md').write_bytes(law_text(99, 1))
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.refused_before_sending(fake, code)

    def test_a_file_whose_bytes_differ_from_the_manifest_is_refused(self):
        (self.in_dir / 'law-03.md').write_bytes(law_text(3, 4))
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.refused_before_sending(fake, code)

    def test_an_upload_set_made_against_another_canvas_is_refused(self):
        self.manifest.write_text(json.dumps({'file_shape': 'slug-title-served-v1', 'canvas': {'sha256': '0' * 64},
                                             'files': self.files}), encoding='utf-8')
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.refused_before_sending(fake, code)

    def test_a_canvas_with_another_component_is_refused(self):
        dsl = canvas_dsl()
        dsl['components']['Code:X'] = {'obj': {'component_name': 'Code', 'params': {}}, 'downstream': []}
        self.canvas.write_text(json.dumps(dsl), encoding='utf-8')
        self.write_manifest()  # the same canvas the upload set names, so only the component check can refuse
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.refused_before_sending(fake, code)

    def test_an_out_folder_that_already_holds_a_run_is_refused(self):
        (self.out / 'ingest-state.json').write_text('{}', encoding='utf-8')
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.refused_before_sending(fake, code)

    def test_an_engine_other_than_the_one_compose_started_is_refused(self):
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake, env=dict(ENV, W2_DOC_ENGINE='infinity'))

        self.refused_before_sending(fake, code)

    def test_a_base_url_that_is_not_loopback_http_is_refused(self):
        with FakeRagflowW2() as fake:
            out = io.StringIO()
            code = rf_ingest.main(['preflight', '--engine', ENGINE, '--base-url', 'http://ragflow.example:9380',
                                   '--api-key-file', str(self.key_file)], stdout=out, environ=dict(ENV))

        self.refused_before_sending(fake, code)

    def test_a_stack_that_already_holds_a_dataset_gets_no_pipeline(self):
        with FakeRagflowW2(existing_datasets=1) as fake:
            code, _ = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertNotIn(('POST', '/api/v1/agents'), fake.paths())

    def test_open_sign_up_stops_the_run(self):
        with FakeRagflowW2(register_enabled=1) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertIn('sign-up is not off', out)

    def test_another_ragflow_version_stops_the_run(self):
        with FakeRagflowW2(version='v0.28.0') as fake:
            code, _ = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertNotIn(('POST', '/api/v1/agents'), fake.paths())

    def test_a_server_running_another_doc_engine_stops_the_run(self):
        with FakeRagflowW2(engine='infinity') as fake:
            code, _ = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertNotIn(('POST', '/api/v1/agents'), fake.paths())

    def test_tei_serving_another_model_stops_the_run(self):
        with FakeRagflowW2(tei_model_id='/data/BAAI/bge-m3') as fake:
            code, _ = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertNotIn(('POST', '/api/v1/agents'), fake.paths())

    def test_a_pipeline_stored_differently_from_the_canvas_stops_the_run(self):
        with FakeRagflowW2(alter_dsl=True) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertNotIn(('POST', '/api/v1/datasets'), fake.paths())
        self.assertIn('differs from the canvas', out)

    def test_a_tei_revision_that_is_not_a_40_hex_commit_is_refused(self):
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake, env=dict(ENV, W2_TEI_REVISION='main'))

        self.refused_before_sending(fake, code)

    def test_an_out_folder_not_named_after_the_engine_is_refused(self):
        self.out = self.out.parent / 'es'
        self.out.mkdir()
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.refused_before_sending(fake, code)

    def test_an_upload_manifest_of_another_file_shape_is_refused(self):
        self.manifest.write_text(json.dumps({'file_shape': 'slug-title-served-v0', 'files': self.files}),
                                 encoding='utf-8')
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.refused_before_sending(fake, code)

    def test_a_file_name_that_is_not_a_registry_slug_is_refused(self):
        (self.in_dir / 'law-03.md').rename(self.in_dir / 'Law_03.md')
        self.files[2]['name'] = 'Law_03.md'
        self.write_manifest()
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.refused_before_sending(fake, code)

    def test_a_file_without_the_title_line_is_refused(self):
        data = law_text(3, 3).replace('# قانون'.encode('utf-8'), 'قانون'.encode('utf-8'), 1)
        (self.in_dir / 'law-03.md').write_bytes(data)
        self.files[2].update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        self.write_manifest()
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.refused_before_sending(fake, code)

    def test_a_canvas_whose_components_are_not_chained_in_order_is_refused(self):
        dsl = canvas_dsl()
        dsl['components']['Parser:A']['downstream'] = ['Tokenizer:C']
        dsl['components']['TitleChunker:B']['downstream'] = []
        self.canvas.write_text(json.dumps(dsl), encoding='utf-8')
        self.write_manifest()  # the same canvas the upload set names, so only the chain check can refuse
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.refused_before_sending(fake, code)


class ServerAnswers(Base):
    """Each answer rf_ingest.py checks, answered wrong once: the run stops before the next step."""

    def test_an_unhealthy_stack_gets_no_pipeline(self):
        with FakeRagflowW2(health={'doc_engine': 'nok'}) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertNotIn(('POST', '/api/v1/agents'), fake.paths())
        self.assertIn("healthz: HTTP 500, {'db': 'ok', 'redis': 'ok', 'doc_engine': 'nok'", out)

    def test_a_sign_up_refused_for_another_reason_stops_the_run(self):
        with FakeRagflowW2(signup_message='Invalid email address: w2-probe@ragbench.invalid') as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertNotIn(('POST', '/api/v1/agents'), fake.paths())
        self.assertIn('unexpected message', out)

    def test_a_pipeline_stored_as_another_kind_of_canvas_gets_no_dataset(self):
        with FakeRagflowW2(canvas_category='agent_canvas') as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertNotIn(('POST', '/api/v1/datasets'), fake.paths())
        self.assertIn("stored as 'agent_canvas'", out)

    def test_a_dataset_stored_with_other_values_than_asked_gets_no_upload(self):
        for field, value in (('pipeline_id', secrets.token_hex(16)), ('embedding_model', 'BAAI/bge-m3@Builtin'),
                             ('language', 'Arabic')):
            with self.subTest(field=field), FakeRagflowW2(store_dataset={field: value}) as fake:
                code, out = self.run_tool(fake)

                self.assertEqual(code, 1)
                self.assertFalse(any(p.endswith('/documents') for _, p in fake.paths()))
                self.assertIn(f'created with other {field} than asked', out)
            (self.out / 'ingest-state.json').unlink(missing_ok=True)  # the next subtest needs an unused folder

    def test_a_document_stored_without_our_pipeline_is_not_parsed(self):
        for value in (None, secrets.token_hex(16)):
            with self.subTest(pipeline_id=value), \
                    FakeRagflowW2(doc_overrides={'law-03.md': {'pipeline_id': value}}) as fake:
                code, out = self.run_tool(fake)

                self.assertEqual(code, 1)
                self.assertFalse(any(p.endswith('/parse') for _, p in fake.paths()))
                self.assertIn('law-03.md: the stored document differs in size, pipeline_id or id', out)
            (self.out / 'ingest-state.json').unlink(missing_ok=True)

    def test_a_document_stored_under_another_name_is_not_parsed(self):
        with FakeRagflowW2(doc_overrides={'law-03.md': {'name': 'law-03(1).md'}}) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertFalse(any(p.endswith('/parse') for _, p in fake.paths()))
        self.assertIn('whose names differ from the 22 sent', out)

    def test_a_parse_started_for_fewer_documents_stops_the_run(self):
        with FakeRagflowW2(parse_short=1) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertIn('parse started for 21 of 22 documents', out)
        self.assertFalse(any(p.endswith('/chunks') for _, p in fake.paths()))

    def test_a_document_we_did_not_upload_stops_the_wait(self):
        with FakeRagflowW2(foreign_docs=1) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertIn('the dataset holds 23 document(s), not the 22 uploaded', out)
        self.assertFalse(any(p.endswith('/chunks') for _, p in fake.paths()))

    def test_a_document_chunk_count_other_than_its_listing_writes_nothing(self):
        with FakeRagflowW2(doc_chunk_count_offset={'law-04.md': 1}) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertIn('law-04.md: the chunk listing does not add up', out)
        self.assertFalse((self.out / 'chunks.jsonl').exists())

    def test_a_chunk_count_that_changes_after_the_parse_writes_nothing(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake, 'create')
            self.run_tool(fake, 'wait')
            doc4 = next(i for i, d in fake.docs.items() if d['name'] == 'law-04.md')
            fake.chunks[doc4].append('### added after the parse\n')  # the listing and the counts all agree
            fake.docs[doc4]['chunk_count'] += 1
            code, out = self.run_tool(fake, 'dump')

        self.assertEqual(code, 1)
        self.assertIn('law-04.md: its chunk count changed since the parse finished', out)
        self.assertFalse((self.out / 'chunks.jsonl').exists())

    def test_a_dataset_whose_counts_differ_from_the_dump_writes_nothing(self):
        for field in ('document_count', 'chunk_count'):
            with self.subTest(field=field), FakeRagflowW2(dataset_offsets={field: 1}) as fake:
                code, out = self.run_tool(fake)

                self.assertEqual(code, 1)
                self.assertIn('the dataset says', out)
                self.assertFalse((self.out / 'chunks.jsonl').exists())
            (self.out / 'ingest-state.json').unlink(missing_ok=True)

    def test_a_redirect_is_refused_and_not_followed(self):
        with FakeRagflowW2(redirect={'/api/v1/system/version': '/moved'}) as fake:
            code, out = self.run_tool(fake, 'preflight')

        self.assertEqual(code, 1)
        self.assertIn('redirects are refused', out)
        self.assertNotIn(('GET', '/moved'), fake.paths())

    def test_a_proxy_named_in_the_environment_is_not_used(self):
        with FakeRagflowW2() as proxy, FakeRagflowW2() as fake, \
                mock.patch.dict(os.environ, {'http_proxy': proxy.url, 'no_proxy': ''}):
            code, _ = self.run_tool(fake)

        self.assertEqual((code, proxy.requests), (0, []))


class TheKey(Base):
    def test_the_key_appears_in_no_output_and_no_file_written(self):
        with FakeRagflowW2(fail={'law-05.md': 1}) as fake:  # the fake's failure message echoes the key
            code, out = self.run_tool(fake)

        self.assertEqual(code, 0)
        self.assertNotIn(API_KEY, out)
        self.assertIn('[REDACTED]', out)
        for path in self.out.iterdir():
            self.assertNotIn(API_KEY, path.read_text(encoding='utf-8'), path.name)

    def test_a_server_message_that_echoes_the_key_is_shown_redacted(self):
        with FakeRagflowW2(echo_key_on_dataset=True) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 1)
        self.assertNotIn(API_KEY, out)
        self.assertNotIn('eyJ-other-session-token', out)
        self.assertIn('Bearer [REDACTED]', out)

    def test_a_state_file_holds_the_key_redacted_when_the_server_echoes_it(self):
        with FakeRagflowW2(store_dataset={'name': f'w2-laws-elasticsearch {API_KEY}'}) as fake:
            code, _ = self.run_tool(fake)

        state = (self.out / 'ingest-state.json').read_text(encoding='utf-8')
        self.assertEqual(code, 1)  # the stored name differs from the one asked
        self.assertNotIn(API_KEY, state)
        self.assertIn('w2-laws-elasticsearch [REDACTED]', state)

    def test_a_logged_answer_holds_the_key_redacted_when_the_server_echoes_it(self):
        with FakeRagflowW2(tei_model_id=f'/data/{API_KEY}/Qwen/Qwen3-Embedding-0.6B') as fake:
            code, out = self.run_tool(fake, 'preflight')

        self.assertEqual(code, 0)
        self.assertNotIn(API_KEY, out)
        self.assertIn('ok   TEI: /data/[REDACTED]/Qwen', out)

    def test_a_key_file_holding_anything_but_one_key_is_refused(self):
        self.key_file.write_text('not a key\n', encoding='utf-8')
        with FakeRagflowW2() as fake:
            code, _ = self.run_tool(fake)

        self.refused_before_sending(fake, code)


if __name__ == '__main__':
    unittest.main()
