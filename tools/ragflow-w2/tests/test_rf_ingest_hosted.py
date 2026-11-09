"""Tests for rf_ingest.py's hosted mode (--embedder hosted) against the local fake RAGFlow. Nothing leaves 127.0.0.1.

The registration is made by register_hosted.py itself, against the same fake, so the record rf_ingest.py reads is the
one that tool writes. The built-in mode's tests are tests/test_rf_ingest.py, unchanged.

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import secrets
import unittest
from pathlib import Path
from unittest import mock

from tests.fake_ragflow_w2 import FakeRagflowW2
from tests.test_rf_ingest import CONTRACT_KEYS, DIGEST, ENGINE, ENV, Base, rf_ingest

TOOL_DIR = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('register_hosted', TOOL_DIR / 'register_hosted.py')
register_hosted = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(register_hosted)

OR_KEY = 'sk-or-v1-' + secrets.token_hex(32)
MODEL, INSTANCE = 'qwen/qwen3-embedding-8b', 'w2or'
EMBEDDING = f'{MODEL}@{INSTANCE}@OpenRouter'
POLICY = 'owner set on 2026-11-09: no training, ZDR only, guardrail qwen3-embedding-8b on Nebius only, $2 budget'
HOSTED_ENV = {'W2_DOC_ENGINE': ENGINE, 'W2_EMBEDDER': 'hosted', 'W2_EMBEDDING_BATCH_SIZE': '16',
              'W2_MAX_CONCURRENT_TASKS': '1', 'W2_RAGFLOW_IMAGE': f'infiniflow/ragflow:v0.27.3@{DIGEST}'}
HOSTED_KEYS = (CONTRACT_KEYS - {'tei_wait_patch'}) | {'hosted_embedder'}


class Hosted(Base):
    def setUp(self):
        super().setUp()
        self.or_key = Path(self.tmp.name) / 'openrouter.key'
        self.or_key.write_text(OR_KEY + '\n', encoding='ascii')
        self.record = self.out / 'hosted-embedder.json'

    def register(self, fake, *extra):
        out = io.StringIO()
        code = register_hosted.main(['register', '--base-url', fake.url, '--api-key-file', str(self.key_file),
                                     '--key-file', str(self.or_key), '--model', MODEL, '--instance', INSTANCE,
                                     '--data-policy', POLICY, '--out', str(self.out), *extra], stdout=out)
        self.assertEqual(code, 0, out.getvalue())
        fake.requests.clear()  # what follows is rf_ingest.py's alone

    def run_hosted(self, fake, step='all', *extra, env=None, model=EMBEDDING, record=None):
        argv = [step, '--engine', ENGINE, '--embedder', 'hosted', '--base-url', fake.url,
                '--api-key-file', str(self.key_file)]
        if step in ('create', 'all'):
            argv += ['--canvas', str(self.canvas), '--in-dir', str(self.in_dir), '--upload-manifest', str(self.manifest)]
        if step in ('create', 'dump', 'all'):
            argv += ['--embedding-model', model, '--hosted-record', str(record or self.record)]
        if step != 'preflight':
            argv += ['--out', str(self.out)]
        out = io.StringIO()
        ticks = iter(range(0, 10 ** 6, 10))
        code = rf_ingest.main(argv + list(extra), stdout=out, environ=dict(HOSTED_ENV if env is None else env),
                              sleep=lambda s: None, clock=lambda: next(ticks))
        return code, out.getvalue()

    def manifest_json(self) -> dict:
        return json.loads((self.out / 'w2-manifest.json').read_text(encoding='utf-8'))

    def edit_record(self, **changes):
        record = json.loads(self.record.read_text(encoding='utf-8'))
        record.update(changes)
        self.record.write_text(json.dumps(record), encoding='utf-8')


class HostedRun(Hosted):
    def test_a_hosted_run_creates_the_dataset_with_the_registered_model_and_sends_nothing_to_tei(self):
        with FakeRagflowW2() as fake:
            self.register(fake)
            code, out = self.run_hosted(fake)

        body = self.body_of(fake, 'POST', '/api/v1/datasets')
        self.assertEqual(code, 0, out)
        self.assertEqual(body['embedding_model'], EMBEDDING)
        self.assertNotIn(('GET', '/info'), fake.paths())
        self.assertIn('ok   embedder: hosted (qwen/qwen3-embedding-8b@w2or@OpenRouter); no TEI on this stack', out)

    def test_the_hosted_manifest_records_the_hosted_embedder_in_place_of_the_tei_wait_patch(self):
        with FakeRagflowW2() as fake:
            self.register(fake, '--provider-order', 'nebius')
            self.run_hosted(fake)

        m = self.manifest_json()
        self.assertEqual(set(m), HOSTED_KEYS)
        self.assertEqual(m['embedder'], {'name': MODEL, 'revision': None, 'via': 'hosted-openrouter'})
        self.assertEqual(m['hosted_embedder'], {'model': MODEL, 'instance': INSTANCE, 'factory': 'OpenRouter',
                                                'base_url': 'https://openrouter.ai/api/v1', 'provider_order': 'nebius',
                                                'data_policy': POLICY})
        self.assertEqual(list(m['hosted_embedder']), list(rf_ingest.HOSTED_KEYS))
        self.assertEqual((m['embedding_batch_size'], m['max_concurrent_tasks'], m['all_match'],
                          m['predicted_chunk_count']), (16, 1, False, None))

    def test_the_chunks_dumped_are_the_same_as_the_builtin_mode_s(self):
        with FakeRagflowW2() as fake:
            self.register(fake)
            code, _ = self.run_hosted(fake)

        rows = [json.loads(x) for x in (self.out / 'chunks.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual(sorted((r['document_name'], r['content']) for r in rows),
                         sorted((fake.docs[d]['name'], t) for d, texts in fake.chunks.items() for t in texts))

    def test_wait_and_dump_can_be_run_again_in_hosted_mode(self):
        with FakeRagflowW2() as fake:
            self.register(fake)
            self.run_hosted(fake, 'create')
            code_wait, _ = self.run_hosted(fake, 'wait')
            code_dump, out = self.run_hosted(fake, 'dump')

        self.assertEqual((code_wait, code_dump), (0, 0), out)
        self.assertEqual(self.manifest_json()['hosted_embedder']['model'], MODEL)

    def test_a_dataset_whose_model_the_server_cannot_resolve_gets_no_upload(self):
        with FakeRagflowW2() as fake:
            self.register(fake)
            fake.providers['OpenRouter'][INSTANCE]['api_key'] = ''  # as if the key were never stored
            code, out = self.run_hosted(fake)

        self.assertEqual(code, 1, out)
        self.assertIn('Unsupported model', out)
        self.assertFalse(any(p.endswith('/documents') for _, p in fake.paths()))

    def test_the_openrouter_key_is_in_no_output_and_no_file_written(self):
        with FakeRagflowW2() as fake:
            self.register(fake)
            code, out = self.run_hosted(fake)

        self.assertEqual(code, 0, out)
        self.assertNotIn(OR_KEY, out)
        for path in self.out.iterdir():
            self.assertNotIn(OR_KEY, path.read_text(encoding='utf-8'), path.name)


class HostedRefusals(Hosted):
    def test_a_tei_wait_patch_is_refused_in_hosted_mode(self):
        with FakeRagflowW2() as fake:
            self.register(fake)
            code, out = self.run_hosted(fake, 'all', '--tei-wait-patch', str(self.patch_dir / 'patch.json'))

        self.refused_before_sending(fake, code)
        self.assertIn('--tei-wait-patch is for the built-in embedder', out)

    def test_create_dump_and_all_need_the_model_and_the_record_in_hosted_mode(self):
        for step in ('create', 'dump', 'all'):
            for missing in ('--embedding-model', '--hosted-record'):
                err = io.StringIO()
                with self.subTest(step=step, missing=missing), self.assertRaises(SystemExit), \
                        mock.patch('sys.stderr', err):
                    argv = [step, '--engine', ENGINE, '--embedder', 'hosted', '--out', str(self.out)]
                    if step != 'dump':
                        argv += ['--canvas', str(self.canvas), '--in-dir', str(self.in_dir),
                                 '--upload-manifest', str(self.manifest)]
                    argv += {'--embedding-model': ['--hosted-record', str(self.record)],
                             '--hosted-record': ['--embedding-model', EMBEDDING]}[missing]
                    rf_ingest.main(argv, stdout=io.StringIO(), environ=dict(HOSTED_ENV))
                self.assertIn(f'required with --embedder hosted: {missing}', err.getvalue())

    def test_a_missing_embedder_option_is_reported_with_its_own_step_s_usage(self):
        """As argparse reported a missing required option before the hosted mode: the step's usage and «<step>:
        error:», not the top-level usage."""
        inputs = ['--canvas', str(self.canvas), '--in-dir', str(self.in_dir), '--upload-manifest', str(self.manifest)]
        cases = (('create', ['--engine', ENGINE, *inputs, '--out', str(self.out)], dict(ENV),
                  'create: error: the following arguments are required: --tei-wait-patch'),
                 ('dump', ['--engine', ENGINE, '--embedder', 'hosted', '--hosted-record', str(self.record),
                           '--out', str(self.out)], dict(HOSTED_ENV),
                  'dump: error: the following arguments are required with --embedder hosted: --embedding-model'))
        for step, argv, environ, message in cases:
            err = io.StringIO()
            with self.subTest(step), self.assertRaises(SystemExit) as stop, mock.patch('sys.stderr', err):
                rf_ingest.main([step, *argv], stdout=io.StringIO(), environ=environ)

            self.assertEqual(2, stop.exception.code)
            self.assertIn(message, err.getvalue())
            self.assertIn(f' {step} [-h] --engine', err.getvalue())

    def test_the_hosted_options_are_refused_in_builtin_mode(self):
        for option, value in (('--embedding-model', EMBEDDING), ('--hosted-record', 'x.json')):
            err = io.StringIO()
            with self.subTest(option=option), self.assertRaises(SystemExit), mock.patch('sys.stderr', err):
                rf_ingest.main(['create', '--engine', ENGINE, '--canvas', str(self.canvas), '--in-dir', str(self.in_dir),
                                '--upload-manifest', str(self.manifest), '--tei-wait-patch',
                                str(self.patch_dir / 'patch.json'), '--out', str(self.out), option, value],
                               stdout=io.StringIO(), environ=dict(ENV))
            self.assertIn(f'{option}: only with --embedder hosted', err.getvalue())

    def test_an_embedder_other_than_the_one_compose_started_is_refused(self):
        with FakeRagflowW2() as fake:
            self.register(fake)
            code, out = self.run_hosted(fake, env=dict(ENV))  # the built-in stack: no W2_EMBEDDER
        self.refused_before_sending(fake, code)
        self.assertIn('differs from W2_EMBEDDER', out)

        with FakeRagflowW2() as fake:
            code, out = self.run_tool(fake, env=dict(ENV, W2_EMBEDDER='hosted'))  # built-in options on the hosted stack
        self.refused_before_sending(fake, code)
        self.assertIn('differs from W2_EMBEDDER', out)

    def test_an_embedding_model_other_than_the_registered_one_is_refused_before_sending(self):
        for model in ('qwen/qwen3-embedding-4b@w2or@OpenRouter', 'qwen/qwen3-embedding-8b@other@OpenRouter',
                      'qwen/qwen3-embedding-8b@OpenRouter', 'qwen/qwen3-embedding-8b@Builtin'):
            with self.subTest(model=model), FakeRagflowW2() as fake:
                self.register(fake)
                code, out = self.run_hosted(fake, model=model)

                self.refused_before_sending(fake, code)
                self.assertIn('--embedding-model', out)
            self.record.unlink()

    def test_a_record_that_is_not_what_register_hosted_writes_is_refused_before_sending(self):
        cases = {'verify true': {'verify': True}, 'another factory': {'factory': 'OpenAI-API-Compatible'},
                 'another base url': {'base_url': 'https://eu.openrouter.ai/api/v1'},
                 'another contract version': {'w2_hosted_registration': 2},
                 'an empty data-policy note': {'data_policy': ' '},
                 'an embedding_model that is not model@instance@factory': {'embedding_model': f'{MODEL}@w2@OpenRouter'},
                 'the instance default': {'instance': 'default', 'embedding_model': f'{MODEL}@default@OpenRouter'},
                 'a provider order that is no text': {'provider_order': 5}}
        for name, changes in cases.items():
            with self.subTest(name), FakeRagflowW2() as fake:
                self.register(fake)
                self.edit_record(**changes)
                model = changes.get('embedding_model', EMBEDDING)
                code, out = self.run_hosted(fake, model=model)

                self.refused_before_sending(fake, code)
                self.assertIn('hosted-embedder.json', out)
            self.record.unlink()

    def test_a_dump_with_another_record_than_create_kept_writes_no_manifest(self):
        with FakeRagflowW2() as fake:
            self.register(fake)
            self.run_hosted(fake, 'create')
            self.run_hosted(fake, 'wait')
            self.edit_record(data_policy='another note')
            code, out = self.run_hosted(fake, 'dump')

        self.assertEqual(code, 2, out)
        self.assertIn('differs from the hosted embedder «create» recorded', out)
        self.assertFalse((self.out / 'w2-manifest.json').exists())


if __name__ == '__main__':
    unittest.main()
