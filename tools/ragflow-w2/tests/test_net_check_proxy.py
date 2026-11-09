"""Tests for net_check.py's proxy checks (the hosted run): --tunnel and --tunnel-refused through --proxy.

A local fake CONNECT proxy answers each target as told: 200 and then a TLS handshake with a certificate the client
trusts, 200 and a certificate it does not trust (what TLS interception looks like), 403, or 503. The certificates
are made at test time by ../ragflow-w1/tests/tls_cert.py (CA:TRUE, subjectAltName 127.0.0.1). Nothing leaves
127.0.0.1.

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import importlib.util
import io
import socket
import ssl
import tempfile
import threading
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


net_check = load('net_check', TOOL_DIR / 'net_check.py')
tls_cert = load('tls_cert', TOOL_DIR.parent / 'ragflow-w1' / 'tests' / 'tls_cert.py')


class FakeProxy:
    """A CONNECT proxy on 127.0.0.1. `answers` maps 'host:port' to 'tls', 'untrusted', or an HTTP status (int); any
    other target gets 403. It records each request head, and the application bytes a client sent after a TLS
    handshake (`after_tls`)."""

    def __init__(self, answers: dict, trusted: tuple, untrusted: tuple):
        self.answers, self.heads, self.after_tls, self.handlers = answers, [], [], []
        self.contexts = {}
        for name, (cert, key) in (('tls', trusted), ('untrusted', untrusted)):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            context.num_tickets = 0  # no write after the client's Finished, which a client that closes at once resets
            self.contexts[name] = context
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(8)
        self.address = f'127.0.0.1:{self.listener.getsockname()[1]}'
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.listener.close()
        for handler in self.handlers:  # every answer recorded before the test reads it
            handler.join(10)

    def _serve(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            handler = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            self.handlers.append(handler)
            handler.start()

    def _handle(self, conn):
        with conn:
            conn.settimeout(10)
            head = b''
            while b'\r\n\r\n' not in head:
                chunk = conn.recv(1024)
                if not chunk:
                    return
                head += chunk
            self.heads.append(head)
            target = head.split(b' ')[1].decode('ascii')
            answer = self.answers.get(target, 403)
            if isinstance(answer, int):
                reason = {403: 'Forbidden', 503: 'Service Unavailable', 200: 'Connection established'}[answer]
                extra = b'X-Squid-Error: ERR_ACCESS_DENIED 0\r\n' if answer == 403 else b''
                conn.sendall(f'HTTP/1.1 {answer} {reason}\r\n'.encode('ascii') + extra + b'Content-Length: 0\r\n\r\n')
                return
            conn.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
            try:
                tls = self.contexts[answer].wrap_socket(conn, server_side=True)
            except (ssl.SSLError, OSError):
                return  # the client refused the certificate
            data = b''
            try:
                with tls:
                    while True:
                        chunk = tls.recv(1024)
                        if not chunk:
                            break
                        data += chunk
            except (ssl.SSLError, OSError):
                pass
            self.after_tls.append(data)


class ProxyChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        (root / 'trusted').mkdir()
        (root / 'untrusted').mkdir()
        cls.trusted = tls_cert.make_self_signed(root / 'trusted')
        cls.untrusted = tls_cert.make_self_signed(root / 'untrusted')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def proxy(self, answers: dict) -> FakeProxy:
        return FakeProxy(answers, self.trusted, self.untrusted)

    def run_check(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        code = net_check.main(list(argv) + ['--cafile', str(self.trusted[0]), '--timeout', '10'], stdout=out)
        return code, out.getvalue()

    def direct(self) -> list:
        """A passing direct pair, so that only the proxy lines decide: the proxy itself reached, and a name that
        does not resolve blocked."""
        return ['--block', 'no-such-host.invalid:443']

    def test_a_tunnel_that_opens_and_completes_a_verified_tls_handshake_is_ok(self):
        with self.proxy({'127.0.0.1:443': 'tls'}) as proxy:
            code, out = self.run_check('--reach', proxy.address, *self.direct(), '--proxy', proxy.address,
                                       '--tunnel', '127.0.0.1:443')

        self.assertEqual(code, 0, out)
        self.assertRegex(out, r'ok   tunnel 127\.0\.0\.1:443 via 127\.0\.0\.1:\d+: CONNECT 200, TLS verified')

    def test_a_tunnel_sends_the_connect_line_and_the_handshake_only(self):
        with self.proxy({'127.0.0.1:443': 'tls'}) as proxy:
            self.run_check('--reach', proxy.address, *self.direct(), '--proxy', proxy.address,
                           '--tunnel', '127.0.0.1:443')

        self.assertEqual(proxy.heads, [b'CONNECT 127.0.0.1:443 HTTP/1.1\r\nHost: 127.0.0.1:443\r\n\r\n'])
        self.assertEqual(proxy.after_tls, [b''])  # no request, no key: nothing after the handshake

    def test_a_tunnel_whose_certificate_is_not_trusted_fails_as_interception_would(self):
        with self.proxy({'127.0.0.1:443': 'untrusted'}) as proxy:
            code, out = self.run_check('--reach', proxy.address, *self.direct(), '--proxy', proxy.address,
                                       '--tunnel', '127.0.0.1:443')

        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'FAIL tunnel 127\.0\.0\.1:443 via [\d.:]+: CONNECT 200, TLS failed \(SSLCertVerificationError')

    def test_a_tunnel_the_proxy_refuses_fails(self):
        with self.proxy({}) as proxy:
            code, out = self.run_check('--reach', proxy.address, *self.direct(), '--proxy', proxy.address,
                                       '--tunnel', '127.0.0.1:443')

        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'FAIL tunnel 127\.0\.0\.1:443 via [\d.:]+: CONNECT 403')

    def test_a_target_the_proxy_answers_with_403_counts_as_refused(self):
        with self.proxy({'127.0.0.1:443': 'tls'}) as proxy:
            code, out = self.run_check('--reach', proxy.address, *self.direct(), '--proxy', proxy.address,
                                       '--tunnel', '127.0.0.1:443', '--tunnel-refused', 'pypi.org:443')

        self.assertEqual(code, 0, out)
        self.assertIn('ok   refused pypi.org:443 by ', out)
        self.assertIn('CONNECT 403 (ERR_ACCESS_DENIED 0)', out)

    def test_a_target_the_proxy_opens_or_cannot_reach_does_not_count_as_refused(self):
        for status, words in ((200, 'CONNECT 200: the proxy opened the tunnel'),
                              (503, 'CONNECT 503: not a refusal by the proxy\'s rules')):
            with self.subTest(status=status), self.proxy({'127.0.0.1:443': 'tls', 'pypi.org:443': status}) as proxy:
                code, out = self.run_check('--reach', proxy.address, *self.direct(), '--proxy', proxy.address,
                                           '--tunnel', '127.0.0.1:443', '--tunnel-refused', 'pypi.org:443')

                self.assertEqual(code, 1, out)
                self.assertIn(f'FAIL refused pypi.org:443 by {proxy.address}: {words}', out)

    def test_a_proxy_that_does_not_answer_fails_both_kinds_of_check(self):
        closed = socket.socket()
        closed.bind(('127.0.0.1', 0))
        address = f'127.0.0.1:{closed.getsockname()[1]}'
        closed.close()
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        try:
            code, out = self.run_check('--reach', f'127.0.0.1:{listener.getsockname()[1]}', *self.direct(),
                                       '--proxy', address, '--tunnel', '127.0.0.1:443', '--tunnel-refused', 'pypi.org:443')
        finally:
            listener.close()

        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'FAIL tunnel 127\.0\.0\.1:443 via [\d.:]+: the proxy did not answer')
        self.assertRegex(out, r'FAIL refused pypi\.org:443 by [\d.:]+: the proxy did not answer')

    def test_refusal_checks_without_a_tunnel_that_opens_are_refused(self):
        code, out = self.run_check('--reach', '127.0.0.1:1', '--block', '1.1.1.1:443', '--proxy', '127.0.0.1:3128',
                                   '--tunnel-refused', 'pypi.org:443')

        self.assertEqual(code, 2, out)
        self.assertIn('refused: --tunnel-refused needs at least one --tunnel', out)

    def test_proxy_checks_without_a_proxy_are_refused(self):
        for option in ('--tunnel', '--tunnel-refused'):
            with self.subTest(option=option):
                code, out = self.run_check('--reach', '127.0.0.1:1', '--block', '1.1.1.1:443', '--tunnel', 'a.b:443',
                                           option, 'pypi.org:443')

                self.assertEqual(code, 2, out)
                self.assertIn('refused: --tunnel and --tunnel-refused need --proxy', out)


if __name__ == '__main__':
    unittest.main()
