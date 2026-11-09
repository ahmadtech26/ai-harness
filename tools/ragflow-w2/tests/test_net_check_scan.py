"""Tests for net_check.py's --scan: a TCP connect scan of one address (the internal network's gateway, README.md, H3)
that sends nothing and is recorded, not checked. Nothing leaves 127.0.0.1.

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import importlib.util
import io
import socket
import threading
import unittest
from pathlib import Path
from unittest import mock

TOOL_DIR = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('net_check', TOOL_DIR / 'net_check.py')
net_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(net_check)


class Listener:
    """One listening port on 127.0.0.1 that records every byte a client sends before it closes."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.received, self.accepted = [], threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        conn, _ = self.sock.accept()
        self.accepted.set()
        with conn:
            conn.settimeout(5)
            try:
                while chunk := conn.recv(4096):
                    self.received.append(chunk)
            except OSError:
                pass

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._thread.join(timeout=10)
        self.sock.close()


def run(*argv) -> tuple[int, str]:
    out = io.StringIO()
    code = net_check.main(list(argv), stdout=out)
    return code, out.getvalue()


CONTROL = ('--reach', '127.0.0.1:1', '--block', '192.0.2.1:443')  # attempt() is replaced in the tests that use these


def attempt_as_asked(host, port, timeout):
    return ('connected', 'connected') if port == 1 else ('blocked', 'timed out')


class Scan(unittest.TestCase):
    def test_a_listening_port_is_connected_and_receives_nothing(self):
        with Listener() as listener:
            found = net_check.scan('127.0.0.1', range(listener.port, listener.port + 1), 5.0)
            self.assertTrue(listener.accepted.wait(10))

        self.assertEqual({'connected': [listener.port]}, found)
        self.assertEqual(b'', b''.join(listener.received))

    def test_every_port_of_the_range_is_tried_both_ends_included(self):
        tried = []

        def probe(host, port, timeout):
            tried.append(port)
            return 'refused'

        with mock.patch.object(net_check, 'probe', probe):
            found = net_check.scan('10.231.47.1', range(5, 8), 1.0)

        self.assertEqual(([5, 6, 7], {'refused': [5, 6, 7]}), (sorted(tried), found))

    def test_each_outcome_is_counted_and_the_open_and_silent_ports_are_named(self):
        outcomes = {111: 'connected', 443: 'timeout', 3128: 'refused', 8080: 'timeout', 46425: 'connected',
                    50000: 'errno 113'}

        with mock.patch.object(net_check, 'attempt', attempt_as_asked), \
                mock.patch.object(net_check, 'probe', lambda host, port, timeout: outcomes.get(port, 'refused')):
            code, out = run(*CONTROL, '--scan', '10.231.47.1')

        self.assertEqual(0, code, out)
        self.assertIn('scan 10.231.47.1 ports 1-65535 (nothing sent; recorded, not a check): connected 2, '
                      'errno 113 1, refused 65530, timeout 2\n', out)
        self.assertIn('scan connected: 111 46425\n', out)
        self.assertIn('scan timed out: 443 8080\n', out)
        self.assertIn('scan other: 50000 errno 113\n', out)

    def test_open_ports_are_recorded_not_checked(self):
        with mock.patch.object(net_check, 'attempt', attempt_as_asked), \
                mock.patch.object(net_check, 'probe', lambda host, port, timeout: 'connected'):
            code, out = run(*CONTROL, '--scan', '10.231.47.1', '--scan-ports', '100-102')

        self.assertEqual(0, code, out)  # a scan never fails the run: H0 (f) is the owner's decision on its list
        self.assertIn('scan connected: 100 101 102\n', out)

    def test_a_long_list_is_cut_and_says_how_many_more(self):
        with mock.patch.object(net_check, 'attempt', attempt_as_asked), \
                mock.patch.object(net_check, 'probe', lambda host, port, timeout: 'timeout'):
            code, out = run(*CONTROL, '--scan', '10.231.47.1', '--scan-ports', '1-250')

        self.assertEqual(0, code, out)
        self.assertIn('scan timed out: ' + ' '.join(str(p) for p in range(1, 201)) + ' and 50 more\n', out)

    def test_a_name_or_a_bad_range_is_refused_before_anything_is_tried(self):
        tried = []
        for extra in (['--scan', 'ragbench-rf-proxy'], ['--scan', '10.231.47.1', '--scan-ports', '0-5'],
                      ['--scan', '10.231.47.1', '--scan-ports', '7-5'], ['--scan', '10.231.47.1', '--scan-ports', '1-65536'],
                      ['--scan', '10.231.47.1', '--scan-ports', 'all'], ['--scan-ports', '1-5']):
            with self.subTest(extra=extra), mock.patch.object(net_check, 'attempt', lambda *a: tried.append(a)), \
                    mock.patch.object(net_check, 'probe', lambda *a: tried.append(a)):
                code, out = run(*CONTROL, *extra)

                self.assertEqual(2, code, out)
                self.assertTrue(out.startswith('refused: '), out)
        self.assertEqual([], tried)


if __name__ == '__main__':
    unittest.main()
