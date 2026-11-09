"""Tests for rf_ingest.py against the local fake RAGFlow (tests/fake_ragflow_w2.py). Nothing leaves 127.0.0.1.

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import email.parser
import email.policy
import functools
import hashlib
import importlib.util
import io
import json
import os
import re
import secrets
import tempfile
import types
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
       'W2_EMBEDDING_BATCH_SIZE': '4', 'W2_MAX_CONCURRENT_TASKS': '1',
       'W2_RAGFLOW_IMAGE': f'infiniflow/ragflow:v0.27.3@{DIGEST}'}
CONTRACT_KEYS = {'w2', 'created_at', 'engine', 'embedder', 'ragflow_version', 'ragflow_image_digest', 'dataset_id',
                 'language', 'document_count', 'chunk_count', 'predicted_chunk_count', 'all_match', 'canvas_sha256',
                 'upload_manifest_sha256', 'file_shape', 'embedding_batch_size', 'max_concurrent_tasks',
                 'tei_wait_patch'}
_spec = importlib.util.spec_from_file_location('patch_tei_wait', TOOL_DIR / 'patch_tei_wait.py')
patch_tei_wait = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(patch_tei_wait)


@functools.lru_cache(maxsize=None)
def tei_wait_fixture(wait: int = 900) -> tuple[bytes, str]:
    """(patched file, diff text) as patch_tei_wait.py writes them, for a small source whose two anchors sit on
    lines 1247 and 1253, as in v0.27.3."""
    encode, queries = (anchor for _, anchor in patch_tei_wait.ANCHORS)
    lines = [f'# filler line {n}' for n in range(1, 1237)] + [
        'class HuggingFaceEmbed:', *(f'    setting_{n} = None' for n in range(1238, 1246)),
        '    def encode(self, texts: list):', encode, '        return response', '', '',
        '', '    def encode_queries(self, text: str):', queries, '        return response', '']
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / 'embedding_model.py'
        source.write_bytes('\n'.join(lines).encode('utf-8'))
        built = patch_tei_wait.build(source, wait)
    assert built['record']['changed_lines'] == [1247, 1253], built['record']
    return built['patched'], built['diff'].decode('utf-8')


PATCHED, DIFF = tei_wait_fixture()


def patch_record(patched: bytes = PATCHED, **changes) -> dict:
    """patch.json as patch_tei_wait.py writes it, for the file `patched`."""
    record = {'file': 'rag/llm/embedding_model.py', 'image_sha256': 'd' * 64,
              'patched_sha256': hashlib.sha256(patched).hexdigest(), 'changed_lines': [1247, 1253], 'wait_s': 900,
              'anchors': [{'method': 'encode', 'line': 1247, 'before': '...', 'after': '...'}]}
    record.update(changes)
    return record


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
        self.patch_dir = root / 'patch'
        self.patch_dir.mkdir()
        self.write_patch()

    def write_patch(self, patched: bytes = PATCHED, diff: str = DIFF, **changes):
        (self.patch_dir / 'embedding_model.py').write_bytes(patched)
        (self.patch_dir / 'embedding_model.diff').write_bytes(diff.encode('utf-8'))
        (self.patch_dir / 'patch.json').write_text(json.dumps(patch_record(patched, **changes)), encoding='utf-8')

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
        if step in ('create', 'dump', 'all'):
            argv += ['--tei-wait-patch', str(self.patch_dir / 'patch.json')]
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

    def test_the_manifest_records_the_tei_wait_patch_and_the_concurrency(self):
        with FakeRagflowW2() as fake:
            code, out = self.run_tool(fake, env=dict(ENV, W2_MAX_CONCURRENT_TASKS='2'))

        self.assertEqual(code, 0, out)
        m = json.loads((self.out / 'w2-manifest.json').read_text(encoding='utf-8'))
        record = patch_record()
        self.assertEqual(m['tei_wait_patch'], {**{k: record[k] for k in ('file', 'image_sha256', 'patched_sha256',
                                                                           'changed_lines', 'wait_s')}, 'diff': DIFF})
        self.assertEqual(list(m['tei_wait_patch']), list(rf_ingest.TEI_WAIT_KEYS))
        self.assertEqual(m['max_concurrent_tasks'], 2)


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


class Settling(Base):
    """v0.27.3 marks a pipeline document DONE before it sets its chunk_count (rf_ingest.unsettled). law-04 holds
    4 chunks of its own and 382 extra ones: 386, as maritime-commerce.md did in the Elasticsearch run."""

    LAW_04_386 = {'law-04.md': 382}

    def final_counts(self) -> dict:
        state = json.loads((self.out / 'ingest-state.json').read_text(encoding='utf-8'))
        return {d['name']: d['chunk_count'] for d in state.get('documents_final') or []}

    @staticmethod
    def stored_counts(fake) -> dict:
        return {d['name']: len(fake.chunks[i]) for i, d in fake.docs.items()}

    @staticmethod
    def parse_rounds(fake) -> list:
        return [json.loads(r.body)['document_ids'] for r in fake.requests if r.path.endswith('/parse')]

    def test_a_document_done_with_0_chunks_for_one_poll_is_recorded_with_the_386_that_follow(self):
        with FakeRagflowW2(extra_chunks=self.LAW_04_386, chunk_count_steps={'law-04.md': [0]}) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 0, out)
        self.assertIn('law-04.md: DONE, 0 chunks', out)
        self.assertEqual(self.final_counts()['law-04.md'], 386)
        self.assertEqual(self.final_counts(), self.stored_counts(fake))
        self.assertEqual(len(self.parse_rounds(fake)), 1)  # all DONE, none failed: nothing is parsed again

    def test_the_wait_step_alone_records_the_386_too(self):
        with FakeRagflowW2(extra_chunks=self.LAW_04_386, chunk_count_steps={'law-04.md': [0]}) as fake:
            self.run_tool(fake, 'create')
            code, out = self.run_tool(fake, 'wait')

        self.assertEqual((code, self.final_counts().get('law-04.md')), (0, 386), out)

    def test_0_chunks_read_on_two_polls_is_not_settled(self):
        with FakeRagflowW2(extra_chunks=self.LAW_04_386, chunk_count_steps={'law-04.md': [0, 0]}) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 0, out)
        self.assertEqual(self.final_counts()['law-04.md'], 386)

    def test_a_count_that_rises_100_then_386_then_386_is_recorded_as_386(self):
        with FakeRagflowW2(extra_chunks=self.LAW_04_386, chunk_count_steps={'law-04.md': [100]}) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 0, out)
        self.assertIn('law-04.md: DONE, 100 chunks', out)
        self.assertIn('law-04.md: DONE, 386 chunks', out)
        self.assertEqual(self.final_counts()['law-04.md'], 386)

    def test_the_progress_line_counts_the_settled_documents(self):
        with FakeRagflowW2(extra_chunks=self.LAW_04_386, chunk_count_steps={'law-04.md': [100]}) as fake:
            _, out = self.run_tool(fake)

        self.assertRegex(out, r'done 22, failed 0, waiting 0 of 22; chunks so far [\d,]+; settled 0\n')
        self.assertRegex(out, r'done 22, failed 0, waiting 0 of 22; chunks so far [\d,]+; settled 21\n')
        self.assertRegex(out, r'done 22, failed 0, waiting 0 of 22; chunks so far [\d,]+; settled 22\n')

    def test_a_document_that_stays_done_with_0_chunks_fails_after_max_wait_naming_it(self):
        steps = {'law-04.md': [0] * 50, 'law-05.md': list(range(1, 51))}
        with FakeRagflowW2(extra_chunks=self.LAW_04_386, chunk_count_steps=steps) as fake:
            code, out = self.run_tool(fake, 'all', '--max-wait', '100')

        failure = out.strip().splitlines()[-1]
        self.assertEqual(code, 1, out)
        self.assertRegex(failure, r'^failed: still parsing after 100 s; DONE but not settled: law-04\.md \(0 chunks\), '
                                  r'law-05\.md \(count still changing: \d+ -> \d+\); run «wait» again to keep waiting$')
        self.assertFalse(any(p.endswith('/chunks') for _, p in fake.paths()))
        self.assertNotIn('documents_final', json.loads((self.out / 'ingest-state.json').read_text(encoding='utf-8')))

    def test_documents_done_and_stable_from_the_start_are_recorded_as_before(self):
        with FakeRagflowW2() as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 0, out)
        self.assertEqual(self.final_counts(), self.stored_counts(fake))
        self.assertEqual(len(self.parse_rounds(fake)), 1)

    def test_a_failed_document_is_parsed_again_and_recorded_as_before(self):
        with FakeRagflowW2(fail={'law-05.md': 1}) as fake:
            code, out = self.run_tool(fake)

        doc5 = next(i for i, d in fake.docs.items() if d['name'] == 'law-05.md')
        rounds = self.parse_rounds(fake)
        self.assertEqual(code, 0, out)
        self.assertEqual((len(rounds[0]), rounds[1:]), (22, [[doc5]]))
        self.assertEqual(self.final_counts(), self.stored_counts(fake))

    def test_a_chunk_count_that_is_not_a_number_is_waited_out_not_a_crash(self):
        with FakeRagflowW2(chunk_count_steps={'law-04.md': ['n/a']}) as fake:
            code, out = self.run_tool(fake)

        self.assertEqual(code, 0, out)
        self.assertIn('law-04.md: DONE, n/a chunks', out)
        self.assertEqual(self.final_counts(), self.stored_counts(fake))

    def test_a_document_still_settling_is_not_parsed_again_with_a_failed_one(self):
        with FakeRagflowW2(fail={'law-05.md': 1}, extra_chunks=self.LAW_04_386,
                           chunk_count_steps={'law-04.md': [0]}) as fake:
            code, out = self.run_tool(fake)

        doc5 = next(i for i, d in fake.docs.items() if d['name'] == 'law-05.md')
        rounds = self.parse_rounds(fake)
        self.assertEqual(code, 0, out)
        self.assertEqual((len(rounds[0]), rounds[1:]), (22, [[doc5]]))
        self.assertEqual(self.final_counts()['law-04.md'], 386)


class SettledRule(unittest.TestCase):
    def test_done_with_a_whole_count_above_0_read_the_same_on_the_previous_poll_is_settled(self):
        for count in (386, 1):
            with self.subTest(count=count):
                self.assertIsNone(rf_ingest.unsettled(('DONE', count), ('DONE', count)))

    def test_anything_else_is_not_settled(self):
        for before, now in ((None, ('DONE', 386)), (('RUNNING', 386), ('DONE', 386)), (('FAIL', 386), ('DONE', 386)),
                            (('DONE', 100), ('DONE', 386)), (('DONE', 400), ('DONE', 386)),
                            (('DONE', 386), ('DONE', 0)), (('DONE', 0), ('DONE', 0)),
                            (('DONE', None), ('DONE', None)), (('DONE', True), ('DONE', True)),
                            (('DONE', 386.0), ('DONE', 386.0)), (('DONE', '386'), ('DONE', '386')),
                            (('DONE', -1), ('DONE', -1)), (('RUNNING', 386), ('RUNNING', 386)),
                            (('DONE', 386.0), ('DONE', 386)), (('DONE', True), ('DONE', 1))):
            with self.subTest(before=before, now=now):
                self.assertIsNotNone(rf_ingest.unsettled(before, now))

    def test_the_reason_names_0_chunks_or_a_changing_count(self):
        self.assertEqual(rf_ingest.unsettled(('DONE', 0), ('DONE', 0)), '0 chunks')
        self.assertEqual(rf_ingest.unsettled(('DONE', 100), ('DONE', 386)), 'count still changing: 100 -> 386')


class ScriptedListing:
    """Answers each document listing with the next of `polls` ({document_id: (run, chunk_count)}), for runs of
    wait() that the fake cannot produce."""

    def __init__(self, polls):
        self.polls, self.listings = list(polls), 0

    def redact(self, text):
        return str(text)

    def call(self, method, path, **_):
        listing = self.polls[min(self.listings, len(self.polls) - 1)]
        self.listings += 1
        docs = [{'id': i, 'run': run, 'chunk_count': count, 'progress': 1.0, 'progress_msg': ''}
                for i, (run, count) in listing.items()]
        return {'data': {'total': len(docs), 'docs': docs}}


class PreviousPoll(unittest.TestCase):
    """unsettled() is given each document's read on the poll just before, whatever its run was then."""

    def test_a_document_back_to_done_with_its_old_count_settles_only_on_the_next_poll(self):
        a, b = 'a' * 32, 'b' * 32
        client = ScriptedListing([
            {a: ('DONE', 1), b: ('DONE', 4)},
            {a: ('DONE', 2), b: ('DONE', 4)},     # b settled; a still rising
            {a: ('DONE', 10), b: ('RUNNING', 0)},  # b parsed again by another client (its count reset to 0)
            {a: ('DONE', 10), b: ('DONE', 4)},     # a settled; b back to DONE, read once
            {a: ('DONE', 10), b: ('DONE', 4)}])
        ticks = iter(range(10 ** 6))
        args = types.SimpleNamespace(poll=30.0, max_wait=10 ** 6, max_reparse=0)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / rf_ingest.STATE).write_text(json.dumps({
                'dataset_id': 'd' * 32, 'parse_rounds': [{'at': 'x', 'document_ids': [a, b]}],
                'files': [{'name': 'law-a.md', 'document_id': a}, {'name': 'law-b.md', 'document_id': b}]}),
                encoding='utf-8')

            rf_ingest.wait(client, args, out, lambda line: None, '', sleep=lambda s: None, clock=lambda: next(ticks))

        self.assertEqual(client.listings, 5)


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


class TeiWaitPatch(Base):
    def test_a_wait_that_is_not_a_whole_number_above_30_is_refused(self):
        for wait in ('900', 30, 29, True, 900.0, None):
            with self.subTest(wait=wait):
                self.write_patch(wait_s=wait)
                with FakeRagflowW2() as fake:
                    code, out = self.run_tool(fake)

                self.refused_before_sending(fake, code)
                self.assertIn('wait_s must be a whole number above 30', out)

    def test_a_sha_that_is_not_64_hex_is_refused(self):
        for name, value in (('image_sha256', 'D' * 64), ('image_sha256', 'd' * 63), ('patched_sha256', 'x' * 64),
                            ('patched_sha256', 12)):
            with self.subTest(name=name, value=value):
                self.write_patch(**{name: value})
                with FakeRagflowW2() as fake:
                    code, out = self.run_tool(fake)

                self.refused_before_sending(fake, code)
                self.assertIn(f'{name} must be 64 lower-case hex characters', out)

    def test_a_record_that_does_not_describe_the_file_beside_it_is_refused(self):
        self.write_patch()
        (self.patch_dir / 'embedding_model.py').write_bytes(PATCHED + b'# changed after patching\n')
        with FakeRagflowW2() as fake:
            code, out = self.run_tool(fake)

        self.refused_before_sending(fake, code)
        self.assertIn('does not have its patched_sha256', out)

    def test_a_record_of_another_file_or_of_no_change_is_refused(self):
        for changes, words in (({'file': 'rag/llm/chat_model.py'}, 'file must be'),
                               ({'image_sha256': hashlib.sha256(PATCHED).hexdigest()}, 'nothing was changed'),
                               ({'changed_lines': [1247]}, 'changed_lines must be two'),
                               ({'changed_lines': [1253, 1247]}, 'changed_lines must be two line numbers, in order')):
            with self.subTest(words):
                self.write_patch(**changes)
                with FakeRagflowW2() as fake:
                    code, out = self.run_tool(fake)

                self.refused_before_sending(fake, code)
                self.assertIn(words, out)

    def test_a_diff_that_is_missing_or_not_the_diff_of_the_change_is_refused(self):
        moved = re.sub(r'^@@ -(\d+)', lambda m: f'@@ -{int(m.group(1)) + 1}', DIFF, count=1, flags=re.M)
        extra = DIFF.replace('\n+', '\n+# an extra added line\n+', 1)
        cases = {'no diff': None,
                 'another file named': DIFF.replace('a/rag/llm/embedding_model.py', 'a/rag/llm/chat_model.py', 1),
                 'the diff of another wait': tei_wait_fixture(600)[1],
                 'the hunk moved by a line': moved,
                 'other text on the changed lines': DIFF.replace('"inputs": texts', '"inputs": items'),
                 'one more added line': extra,
                 'a blank row inside the hunk': DIFF.replace('\n-', '\n\n-', 1),
                 'CRLF line ends': DIFF.replace('\n', '\r\n')}
        for name, diff in cases.items():
            with self.subTest(name):
                self.write_patch()
                if diff is None:
                    (self.patch_dir / 'embedding_model.diff').unlink()
                else:
                    (self.patch_dir / 'embedding_model.diff').write_bytes(diff.encode('utf-8'))
                with FakeRagflowW2() as fake:
                    code, out = self.run_tool(fake)

                self.refused_before_sending(fake, code)
                self.assertIn('embedding_model.diff beside patch.json', out)

    def test_a_concurrency_that_is_not_a_number_from_1_is_refused(self):
        for value in ('', '0', 'one'):
            with self.subTest(value=value), FakeRagflowW2() as fake:
                code, _ = self.run_tool(fake, env=dict(ENV, W2_MAX_CONCURRENT_TASKS=value))

                self.refused_before_sending(fake, code)

    def test_the_patch_is_required_by_create_and_all(self):
        for step in ('create', 'all'):
            with self.subTest(step), self.assertRaises(SystemExit), mock.patch('sys.stderr', io.StringIO()):
                rf_ingest.main([step, '--engine', ENGINE, '--canvas', str(self.canvas), '--in-dir', str(self.in_dir),
                                '--upload-manifest', str(self.manifest), '--out', str(self.out)],
                               stdout=io.StringIO(), environ=dict(ENV))

    def test_a_dump_with_another_patch_than_create_recorded_writes_no_manifest(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake, 'create')
            self.run_tool(fake, 'wait')
            self.write_patch(*tei_wait_fixture(600), wait_s=600)
            code, out = self.run_tool(fake, 'dump')

        self.assertEqual(code, 2, out)
        self.assertIn('differs from the patch «create» recorded', out)
        self.assertFalse((self.out / 'w2-manifest.json').exists())
        state = json.loads((self.out / 'ingest-state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['tei_wait_patch']['wait_s'], 900)


if __name__ == '__main__':
    unittest.main()
