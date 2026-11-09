"""Tests for register_hosted.py against the local fake RAGFlow (tests/fake_ragflow_w2.py). Nothing leaves 127.0.0.1.

The OpenRouter key here is invented at test time in the documented shape («sk-or-v1-» and 64 hex characters). The
main rule under test: it reaches the server in exactly one request body, and nowhere else.

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fake_ragflow_w2 import API_KEY, FakeRagflowW2

TOOL_DIR = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('register_hosted', TOOL_DIR / 'register_hosted.py')
register_hosted = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(register_hosted)

OR_KEY = 'sk-or-v1-' + secrets.token_hex(32)
MODEL, INSTANCE = 'qwen/qwen3-embedding-8b', 'w2or'
POLICY = 'owner set on 2026-11-09: no training, ZDR only, guardrail qwen3-embedding-8b on Nebius only, $2 budget'
RECORD_KEYS = {'w2_hosted_registration', 'registered_at', 'factory', 'instance', 'model', 'embedding_model',
               'base_url', 'max_tokens', 'provider_order', 'verify', 'data_policy', 'key'}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.out = root / 'out' / 'elasticsearch'
        self.out.mkdir(parents=True)
        self.or_key = root / 'openrouter.key'
        self.or_key.write_bytes((OR_KEY + '\n').encode('ascii'))
        self.rf_key = root / 'rf-key'
        self.rf_key.write_text(API_KEY + '\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, fake, step='register', *extra) -> tuple[int, str, str]:
        argv = [step, '--base-url', fake.url, '--api-key-file', str(self.rf_key), '--key-file', str(self.or_key),
                '--model', MODEL]
        if step == 'register':
            argv += ['--instance', INSTANCE, '--data-policy', POLICY, '--out', str(self.out)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err):
            code = register_hosted.main(argv + list(extra), stdout=out)
        return code, out.getvalue(), err.getvalue()

    def record(self) -> dict:
        return json.loads((self.out / 'hosted-embedder.json').read_text(encoding='utf-8'))

    @staticmethod
    def body(fake, method, path) -> dict:
        return next(json.loads(r.body) for r in fake.requests if (r.method, r.path) == (method, path))


class Register(Base):
    def test_it_sends_the_three_cited_routes_in_order_and_nothing_else(self):
        with FakeRagflowW2() as fake:
            code, out, _ = self.run_tool(fake)

        self.assertEqual(code, 0, out)
        self.assertEqual(fake.paths(), [('PUT', '/api/v1/providers'), ('POST', '/api/v1/providers/OpenRouter/instances'),
                                        ('PUT', '/api/v1/providers/OpenRouter/instances/w2or')])

    def test_the_instance_is_made_by_name_then_given_the_key_with_verify_false(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake)

        self.assertEqual(self.body(fake, 'PUT', '/api/v1/providers'), {'provider_name': 'OpenRouter'})
        self.assertEqual(self.body(fake, 'POST', '/api/v1/providers/OpenRouter/instances'), {'instance_name': 'w2or'})
        self.assertEqual(self.body(fake, 'PUT', '/api/v1/providers/OpenRouter/instances/w2or'), {
            'instance_name': 'w2or', 'api_key': OR_KEY, 'base_url': 'https://openrouter.ai/api/v1', 'region': '',
            'model_info': [{'model_type': ['embedding'], 'model_name': MODEL, 'max_tokens': 32768}], 'verify': False})

    def test_the_key_reaches_the_server_in_one_request_body_and_nowhere_else(self):
        with FakeRagflowW2() as fake:
            code, out, err = self.run_tool(fake)

        carriers = [(r.method, r.path) for r in fake.requests if OR_KEY.encode() in r.body]
        elsewhere = [r.path for r in fake.requests if OR_KEY in r.path or OR_KEY in json.dumps(r.query)
                     or OR_KEY in json.dumps(r.headers)]
        self.assertEqual(code, 0, out)
        self.assertEqual(carriers, [('PUT', '/api/v1/providers/OpenRouter/instances/w2or')])
        self.assertEqual(sum(r.body.count(OR_KEY.encode()) for r in fake.requests), 1)
        self.assertEqual(elsewhere, [])
        self.assertNotIn(OR_KEY, out + err)
        for path in self.out.iterdir():
            self.assertNotIn(OR_KEY, path.read_text(encoding='utf-8'), path.name)

    def test_the_runner_s_ragflow_key_goes_only_in_the_authorization_header(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake)

        self.assertEqual({r.headers.get('Authorization') for r in fake.requests}, {f'Bearer {API_KEY}'})
        self.assertFalse(any(API_KEY.encode() in r.body for r in fake.requests))

    def test_the_record_holds_the_registration_and_only_the_key_s_length_and_salted_hash(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake)

        record = self.record()
        key = record['key']
        self.assertEqual(set(record), RECORD_KEYS)
        self.assertEqual((record['factory'], record['instance'], record['model'], record['embedding_model'],
                          record['base_url'], record['provider_order'], record['verify'], record['data_policy']),
                         ('OpenRouter', INSTANCE, MODEL, f'{MODEL}@{INSTANCE}@OpenRouter', 'https://openrouter.ai/api/v1',
                          None, False, POLICY))
        self.assertEqual(set(key), {'length', 'salt', 'salted_sha256'})
        self.assertEqual(key['length'], len(OR_KEY))
        self.assertEqual(key['salted_sha256'], hashlib.sha256((key['salt'] + OR_KEY).encode('ascii')).hexdigest())
        self.assertRegex(key['salt'], r'^[0-9a-f]{32}$')

    def test_a_provider_order_wraps_the_key_as_json_in_memory(self):
        with FakeRagflowW2() as fake:
            code, out, _ = self.run_tool(fake, 'register', '--provider-order', 'nebius')

        sent = self.body(fake, 'PUT', '/api/v1/providers/OpenRouter/instances/w2or')['api_key']
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(sent), {'api_key': OR_KEY, 'provider_order': 'nebius'})
        self.assertEqual(self.record()['provider_order'], 'nebius')
        self.assertNotIn(OR_KEY, out)

    def test_the_dataset_route_then_finds_the_model(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake)

        held = fake.providers['OpenRouter'][INSTANCE]
        self.assertEqual((held['api_key'], held['models'], held['verify']), (OR_KEY, [(MODEL, ('embedding',))], False))


class Refusals(Base):
    def assert_refused_before_sending(self, fake, code, out, words):
        self.assertEqual(code, 2, out)
        self.assertEqual(fake.requests, [])
        self.assertIn(words, out)
        self.assertFalse((self.out / 'hosted-embedder.json').exists())

    def test_a_key_file_that_is_missing_empty_or_not_one_openrouter_key_is_refused_before_sending(self):
        cases = {'missing': (None, 'no key file'),
                 'empty': (b'', 'is empty'),
                 'two lines': ((OR_KEY + '\n' + OR_KEY + '\n').encode(), 'more than one line'),
                 'a blank second line': ((OR_KEY + '\n\n').encode(), 'more than one line'),
                 'a byte-order mark': (b'\xef\xbb\xbf' + OR_KEY.encode(), 'byte-order mark'),
                 'spaces around it': ((' ' + OR_KEY + ' \n').encode(), 'does not hold one OpenRouter key'),
                 'a RAGFlow key': ((API_KEY + '\n').encode(), 'does not hold one OpenRouter key'),
                 'a short key': ((OR_KEY[:-1] + '\n').encode(), 'does not hold one OpenRouter key'),
                 'capital hex': ((OR_KEY.upper() + '\n').encode(), 'does not hold one OpenRouter key'),
                 'not ASCII': ((OR_KEY + 'é').encode('utf-8'), 'does not hold one OpenRouter key')}
        for name, (data, words) in cases.items():
            with self.subTest(name):
                if data is None:
                    self.or_key.unlink(missing_ok=True)
                else:
                    self.or_key.write_bytes(data)
                with FakeRagflowW2() as fake:
                    code, out, err = self.run_tool(fake)

                self.assert_refused_before_sending(fake, code, out, words)
                self.assertNotIn(OR_KEY, out + err)

    def test_a_key_file_of_one_line_with_or_without_its_line_end_is_accepted(self):
        for ending in (b'', b'\n', b'\r\n'):
            with self.subTest(ending=ending):
                self.or_key.write_bytes(OR_KEY.encode('ascii') + ending)
                (self.out / 'hosted-embedder.json').unlink(missing_ok=True)
                with FakeRagflowW2() as fake:
                    code, out, _ = self.run_tool(fake)

                self.assertEqual(code, 0, out)
                self.assertEqual(self.body(fake, 'PUT', '/api/v1/providers/OpenRouter/instances/w2or')['api_key'], OR_KEY)

    def test_an_instance_name_that_ragflow_would_refuse_is_refused_before_sending(self):
        for name in ('default', 'w2 or', 'w2/or', ''):
            with self.subTest(name=name), FakeRagflowW2() as fake:
                code, out, _ = self.run_tool(fake, 'register', '--instance', name)

                self.assert_refused_before_sending(fake, code, out, '--instance')

    def test_a_model_that_is_not_an_openrouter_model_id_is_refused_before_sending(self):
        for model in ('qwen3-embedding-8b', 'qwen/qwen3@w2or', 'qwen/ qwen3'):
            with self.subTest(model=model), FakeRagflowW2() as fake:
                code, out, _ = self.run_tool(fake, 'register', '--model', model)

                self.assert_refused_before_sending(fake, code, out, '--model')

    def test_a_data_policy_note_that_is_empty_or_more_than_one_line_is_refused_before_sending(self):
        for note in ('', '  ', 'line one\nline two'):
            with self.subTest(note=note), FakeRagflowW2() as fake:
                code, out, _ = self.run_tool(fake, 'register', '--data-policy', note)

                self.assert_refused_before_sending(fake, code, out, '--data-policy')

    def test_a_provider_order_that_is_not_a_provider_slug_is_refused_before_sending(self):
        for order in ('Nebius', 'nebius;deepinfra', ''):
            with self.subTest(order=order), FakeRagflowW2() as fake:
                code, out, _ = self.run_tool(fake, 'register', '--provider-order', order)

                self.assert_refused_before_sending(fake, code, out, '--provider-order')

    def test_a_record_already_in_out_is_refused_before_sending(self):
        (self.out / 'hosted-embedder.json').write_text('{}', encoding='utf-8')
        with FakeRagflowW2() as fake:
            code, out, _ = self.run_tool(fake)

        self.assertEqual((code, fake.requests), (2, []))
        self.assertIn('already holds a registration', out)

    def test_a_base_url_that_is_not_loopback_http_is_refused_before_sending(self):
        with FakeRagflowW2() as fake:
            out = io.StringIO()
            code = register_hosted.main(['register', '--base-url', 'http://ragflow.example:9380', '--api-key-file',
                                         str(self.rf_key), '--key-file', str(self.or_key), '--model', MODEL,
                                         '--instance', INSTANCE, '--data-policy', POLICY, '--out', str(self.out)],
                                        stdout=out)

        self.assertEqual((code, fake.requests), (2, []))

    def test_a_server_message_is_cut_and_loses_every_key_and_bearer_token(self):
        client = register_hosted.Client('http://127.0.0.1:9', API_KEY, secrets_to_hide=(OR_KEY,))

        text = client.redact(f'bad {OR_KEY} for Bearer {API_KEY} and bearer eyJ-other\n' + 'x' * 300)

        self.assertTrue(text.startswith('bad [REDACTED] for Bearer [REDACTED] and Bearer [REDACTED] xxx'), text)
        self.assertEqual(len(text), 200)

    def test_the_route_that_returns_a_stored_key_is_never_sent(self):
        client = register_hosted.Client('http://127.0.0.1:9', API_KEY, secrets_to_hide=(OR_KEY,))

        for path in ('/api/v1/providers/OpenRouter/instances/w2or', '/api/v1/providers/OpenRouter/instances'):
            with self.subTest(path=path), self.assertRaises(register_hosted.Refused):
                client.request('GET', path)


class ServerAnswers(Base):
    def test_a_provider_already_added_stops_before_any_instance(self):
        with FakeRagflowW2(provider_exists=True) as fake:
            code, out, _ = self.run_tool(fake)

        self.assertEqual(code, 1, out)
        self.assertEqual(fake.paths(), [('PUT', '/api/v1/providers')])
        self.assertIn('Provider OpenRouter already exists', out)
        self.assertFalse((self.out / 'hosted-embedder.json').exists())

    def test_a_server_message_that_repeats_the_key_is_shown_redacted_and_nothing_is_written(self):
        with FakeRagflowW2(echo_key_on_instance=True) as fake:
            code, out, err = self.run_tool(fake)

        self.assertEqual(code, 1, out)
        self.assertNotIn(OR_KEY, out + err)
        self.assertNotIn(API_KEY, out + err)
        self.assertIn('cannot store [REDACTED] for Bearer [REDACTED]', out)
        self.assertFalse((self.out / 'hosted-embedder.json').exists())

    def test_main_s_own_log_redacts_both_keys_from_a_message_that_bypassed_client_redact(self):
        """The second layer: a refusal or failure raised after both keys are read and worded with them, which never
        went through Client.redact (the first layer, tested above), is still printed without them."""
        for error in (register_hosted.Failed, register_hosted.Refused):
            message = f'echo of {OR_KEY} with Bearer {API_KEY}'
            with self.subTest(error.__name__), FakeRagflowW2() as fake, \
                    mock.patch.object(register_hosted, 'register', side_effect=error(message)):
                code, out, err = self.run_tool(fake)

            self.assertEqual(code, 1 if error is register_hosted.Failed else 2, out)
            self.assertIn('echo of [REDACTED] with Bearer [REDACTED]', out)
            self.assertNotIn(OR_KEY, out + err)
            self.assertNotIn(API_KEY, out + err)

    def test_a_proxy_named_in_the_environment_is_not_used(self):
        with FakeRagflowW2() as proxy, FakeRagflowW2() as fake, \
                mock.patch.dict(os.environ, {'http_proxy': proxy.url, 'no_proxy': ''}):
            code, _, _ = self.run_tool(fake)

        self.assertEqual((code, proxy.requests), (0, []))


class Smoke(Base):
    def test_smoke_sends_one_connection_check_carrying_the_key_and_the_model(self):
        with FakeRagflowW2() as fake:
            code, out, err = self.run_tool(fake, 'smoke')

        self.assertEqual(code, 0, out)
        self.assertEqual(fake.paths(), [('POST', '/api/v1/providers/OpenRouter/connection')])
        self.assertEqual(self.body(fake, 'POST', '/api/v1/providers/OpenRouter/connection'), {
            'api_key': OR_KEY, 'base_url': 'https://openrouter.ai/api/v1',
            'model_info': [{'model_type': ['embedding'], 'model_name': MODEL, 'max_tokens': 32768}]})
        self.assertNotIn(OR_KEY, out + err)

    def test_smoke_with_a_provider_order_checks_the_json_form(self):
        with FakeRagflowW2() as fake:
            self.run_tool(fake, 'smoke', '--provider-order', 'nebius')

        sent = self.body(fake, 'POST', '/api/v1/providers/OpenRouter/connection')['api_key']
        self.assertEqual(json.loads(sent), {'api_key': OR_KEY, 'provider_order': 'nebius'})

    def test_a_failed_smoke_call_is_reported_redacted(self):
        with FakeRagflowW2(connection_message='Fail to access embedding model. 401 for key {key}') as fake:
            code, out, err = self.run_tool(fake, 'smoke')

        self.assertEqual(code, 1, out)
        self.assertNotIn(OR_KEY, out + err)
        self.assertIn('401 for key [REDACTED]', out)


if __name__ == '__main__':
    unittest.main()
