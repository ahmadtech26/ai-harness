import hashlib
import socket
import tempfile
import unittest
from pathlib import Path

from ragflow_export.client import RagflowClient, load_api_key
from ragflow_export.errors import (ApiError, ApiKeyError, AuthError, BadBaseUrl, HttpError, InsecureTransport,
                                   PaginationError, ReadOnlyViolation, RedirectRefused, ShapeError, TransportError,
                                   UnsafeIdentifier)
from ragflow_export.files import safe_id
from tests.fake_ragflow import API_KEY, FakeRagflow, Scripted


def make_client(base_url: str, key: str = API_KEY, **kwargs) -> tuple[RagflowClient, list[float]]:
    sleeps: list[float] = []
    kwargs.setdefault('sleep', sleeps.append)
    return RagflowClient(base_url, key, **kwargs), sleeps


class ReadOnlyTests(unittest.TestCase):
    def test_refuses_every_method_but_get_before_sending_anything(self):
        with FakeRagflow() as fake:
            client, _ = make_client(fake.base_url)

            for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'post'):
                with self.subTest(method=method), self.assertRaises(ReadOnlyViolation):
                    client.request_json(method, '/api/v1/datasets')

            self.assertEqual(fake.requests, [])

    def test_refuses_a_get_outside_the_listing_and_download_routes(self):
        refused = ['/api/v1/retrieval', '/api/v1/system/tokens', '/api/v1/datasets/ds01laws',
                   '/api/v1/datasets/ds01laws/documents/doc01lease/chunks/doc01lease-c01',
                   '/api/v1/datasets/../system/tokens', '/v1/system/tokens', '/api/v1/datasets/ds01laws/chunks',
                   '/api/v1/datasets/ds01laws/documents/doc01lease/parse']
        with FakeRagflow() as fake:
            client, _ = make_client(fake.base_url)

            for path in refused:
                with self.subTest(path=path), self.assertRaises(ReadOnlyViolation):
                    client.request_json('GET', path)

            self.assertEqual(fake.requests, [])

    def test_refuses_an_identifier_that_could_leave_its_route(self):
        with FakeRagflow() as fake:
            client, _ = make_client(fake.base_url)

            for bad in ('../x', 'a/b', '', 'x?y', 'ds 1', 'مجموعة', '..', 'a\\b'):
                with self.subTest(identifier=bad), self.assertRaises(UnsafeIdentifier):
                    client.list_documents(bad, page_size=30)

            self.assertEqual(fake.requests, [])

    def test_refuses_windows_device_names_as_identifiers(self):
        for name in ('NUL', 'con', 'Aux', 'prn', 'COM0', 'com9', 'LPT1', 'lpt0'):
            with self.subTest(identifier=name), self.assertRaises(UnsafeIdentifier):
                safe_id(name)

        allowed = ('console', 'nul0', 'COM10', 'NULL')
        self.assertEqual([safe_id(name) for name in allowed], list(allowed))


class TransportSafetyTests(unittest.TestCase):
    def test_sends_the_key_as_a_bearer_header_and_keeps_it_out_of_repr(self):
        with FakeRagflow() as fake:
            client, _ = make_client(fake.base_url)

            client.list_datasets(page_size=30)

            self.assertEqual(fake.requests[0].authorization, f'Bearer {API_KEY}')
            self.assertNotIn(API_KEY, repr(client))

    def test_refuses_a_redirect_and_never_contacts_its_target(self):
        with FakeRagflow() as fake, FakeRagflow() as elsewhere:
            fake.redirects['/api/v1/datasets'] = elsewhere.base_url + '/api/v1/datasets'
            client, _ = make_client(fake.base_url)

            with self.assertRaises(RedirectRefused):
                client.list_datasets(page_size=30)

            self.assertEqual(elsewhere.requests, [])
            self.assertEqual(len(fake.requests), 1)

    def test_refuses_plain_http_to_a_remote_host_unless_allowed(self):
        with self.assertRaises(InsecureTransport):
            RagflowClient('http://ragflow.example.org', API_KEY)

        for url in ('http://127.0.0.1:9', 'http://localhost:9', 'http://[::1]:9', 'https://ragflow.example.org'):
            with self.subTest(url=url):
                RagflowClient(url, API_KEY)
        RagflowClient('http://ragflow.example.org', API_KEY, allow_insecure_http=True)

    def test_refuses_a_base_url_with_credentials_a_query_or_another_scheme(self):
        for url in ('https://user:pw@ragflow.example.org', 'https://ragflow.example.org/?a=1',
                    'https://ragflow.example.org/#top', 'ftp://ragflow.example.org', 'ragflow.example.org:9380', ''):
            with self.subTest(url=url), self.assertRaises(BadBaseUrl):
                RagflowClient(url, API_KEY)

    def test_refuses_an_empty_key(self):
        with self.assertRaises(ApiKeyError):
            RagflowClient('https://ragflow.example.org', '')

    def test_works_under_a_path_prefix(self):
        with FakeRagflow(prefix='/ragflow') as fake:
            client, _ = make_client(fake.base_url + '/')

            datasets = client.list_datasets(page_size=30)

            self.assertEqual(len(datasets), 3)
            self.assertEqual(fake.paths(), ['/ragflow/api/v1/datasets'])


class RetryTests(unittest.TestCase):
    def test_retries_server_errors_and_rate_limits_with_backoff_and_retry_after(self):
        with FakeRagflow() as fake:
            fake.scripted['/api/v1/datasets'] = [Scripted(503), Scripted(429, {'Retry-After': '7'}), Scripted(502)]
            client, sleeps = make_client(fake.base_url, base_delay=1.0, max_delay=60.0, max_attempts=5)

            datasets = client.list_datasets(page_size=30)

            self.assertEqual(len(datasets), 3)
            self.assertEqual(sleeps, [1.0, 7.0, 4.0])
            self.assertEqual(len(fake.requests), 4)

    def test_gives_up_after_the_last_attempt(self):
        with FakeRagflow() as fake:
            fake.broken['/api/v1/datasets'] = 503
            client, sleeps = make_client(fake.base_url, max_attempts=3)

            with self.assertRaises(HttpError) as caught:
                client.list_datasets(page_size=30)

            self.assertEqual(caught.exception.status, 503)
            self.assertEqual((len(fake.requests), len(sleeps)), (3, 2))

    def test_does_not_retry_a_client_error(self):
        with FakeRagflow() as fake:
            fake.broken['/api/v1/datasets'] = 404
            client, sleeps = make_client(fake.base_url)

            with self.assertRaises(HttpError):
                client.list_datasets(page_size=30)

            self.assertEqual((len(fake.requests), sleeps), (1, []))

    def test_retries_a_dropped_connection(self):
        with FakeRagflow() as fake:
            fake.drop['/api/v1/datasets'] = 2
            client, sleeps = make_client(fake.base_url)

            datasets = client.list_datasets(page_size=30)

            self.assertEqual((len(datasets), len(fake.requests), len(sleeps)), (3, 3, 2))

    def test_an_unreachable_server_is_a_transport_error_after_the_last_attempt(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        client, sleeps = make_client(f'http://127.0.0.1:{port}', max_attempts=2, timeout=5)

        with self.assertRaises(TransportError):
            client.list_datasets(page_size=30)

        self.assertEqual(len(sleeps), 1)

    def test_an_api_error_code_is_not_retried(self):
        with FakeRagflow() as fake:
            fake.api_errors['/api/v1/datasets'] = {'code': 102, 'message': 'boom'}
            client, sleeps = make_client(fake.base_url)

            with self.assertRaises(ApiError) as caught:
                client.list_datasets(page_size=30)

            self.assertEqual((caught.exception.code, len(fake.requests), sleeps), (102, 1, []))


class AuthTests(unittest.TestCase):
    def test_a_wrong_key_is_an_auth_error(self):
        with FakeRagflow() as fake:
            client, _ = make_client(fake.base_url, key='not-the-key')

            with self.assertRaises(AuthError):
                client.list_datasets(page_size=30)

    def test_http_401_is_an_auth_error(self):
        with FakeRagflow() as fake:
            fake.broken['/api/v1/datasets'] = 401
            client, sleeps = make_client(fake.base_url)

            with self.assertRaises(AuthError):
                client.list_datasets(page_size=30)

            self.assertEqual(sleeps, [])

    def test_an_error_message_that_repeats_the_key_is_redacted(self):
        with FakeRagflow() as fake:
            fake.echo_auth.add('/api/v1/datasets')
            client, _ = make_client(fake.base_url)

            with self.assertRaises(ApiError) as caught:
                client.list_datasets(page_size=30)

            self.assertIn('fake rejected header', str(caught.exception))
            self.assertNotIn(API_KEY, str(caught.exception))


class PaginationTests(unittest.TestCase):
    def test_pages_through_chunks_until_the_reported_total(self):
        with FakeRagflow() as fake:
            client, _ = make_client(fake.base_url)

            listing = client.list_chunks('ds01laws', 'doc01lease', page_size=3)

            expected = [c['id'] for c in fake.data['chunks']['doc01lease']]
            self.assertEqual([c['id'] for c in listing.items], expected)
            self.assertEqual([r.query['page'] for r in fake.requests], ['1', '2', '3'])
            self.assertEqual(listing.total_reported, 7)

    def test_a_listing_without_a_total_stops_on_a_short_page(self):
        with FakeRagflow() as fake:
            client, _ = make_client(fake.base_url)

            datasets = client.list_datasets(page_size=2)

            self.assertEqual([d['id'] for d in datasets], ['ds01laws', 'ds02clients', 'ds03empty'])
            self.assertEqual(len(fake.requests), 2)

    def test_keeps_paging_when_the_server_caps_the_page_size(self):
        with FakeRagflow() as fake:
            fake.max_page_size = 2
            client, _ = make_client(fake.base_url)

            listing = client.list_chunks('ds01laws', 'doc01lease', page_size=5)

            self.assertEqual(len(listing.items), 7)

    def test_stops_when_the_server_ignores_the_page_parameter(self):
        with FakeRagflow() as fake:
            fake.ignore_paging = True
            client, _ = make_client(fake.base_url)

            with self.assertRaises(PaginationError):
                client.list_datasets(page_size=2)

            self.assertEqual(len(fake.requests), 2)

    def test_an_unknown_response_shape_fails_loudly(self):
        with FakeRagflow() as fake:
            fake.api_errors['/api/v1/datasets/ds01laws/documents'] = {'code': 0, 'data': {'items': []}}
            client, _ = make_client(fake.base_url)

            with self.assertRaises(ShapeError) as caught:
                client.list_documents('ds01laws', page_size=30)

            self.assertIn('items', str(caught.exception))


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.fake = self.enterContext(FakeRagflow())

    def test_saves_the_original_bytes_and_their_hash(self):
        client, _ = make_client(self.fake.base_url)
        dest = self.tmp / 'original.txt'

        result = client.download_document('ds01laws', 'doc01lease', dest)

        blob = self.fake.data['blobs']['doc01lease']
        self.assertEqual(dest.read_bytes(), blob)
        self.assertEqual((result.sha256, result.size), (hashlib.sha256(blob).hexdigest(), len(blob)))
        self.assertEqual([p.name for p in self.tmp.iterdir()], ['original.txt'])

    def test_retries_a_body_cut_short(self):
        self.fake.truncate['doc02memo'] = 1
        client, sleeps = make_client(self.fake.base_url)
        dest = self.tmp / 'original.pdf'

        result = client.download_document('ds01laws', 'doc02memo', dest)

        blob = self.fake.data['blobs']['doc02memo']
        self.assertEqual((dest.read_bytes(), result.size, len(sleeps)), (blob, len(blob), 1))

    def test_a_json_error_body_is_an_error_not_a_file(self):
        self.fake.download_json_error.add('doc02memo')
        client, _ = make_client(self.fake.base_url)

        with self.assertRaises(ApiError):
            client.download_document('ds01laws', 'doc02memo', self.tmp / 'original.pdf')

        self.assertEqual(list(self.tmp.iterdir()), [])


class ApiKeyFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_reads_the_key_and_strips_surrounding_whitespace(self):
        path = self.tmp / 'key'
        path.write_bytes(f'  {API_KEY}\r\n'.encode())

        self.assertEqual(load_api_key(path), API_KEY)

    def test_refuses_a_missing_empty_or_multi_line_file_without_echoing_it(self):
        cases = {'empty': b'\n', 'two-lines': f'{API_KEY}\nsecond\n'.encode(), 'inner-space': f'{API_KEY} x'.encode()}
        for name, content in cases.items():
            path = self.tmp / name
            path.write_bytes(content)
            with self.subTest(case=name), self.assertRaises(ApiKeyError) as caught:
                load_api_key(path)
            self.assertNotIn(API_KEY, str(caught.exception))
        with self.assertRaises(ApiKeyError):
            load_api_key(self.tmp / 'missing')


if __name__ == '__main__':
    unittest.main()
