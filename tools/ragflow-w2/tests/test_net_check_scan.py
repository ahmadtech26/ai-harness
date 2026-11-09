"""Tests for net_check.py's --scan: a TCP connect scan of one address (the internal network's former gateway, which no
interface holds on the hosted stack, README.md, H3) that sends nothing, and fails the run when any port answers: one
that accepts a connection, one that refuses it (a host holds the address), and one whose attempt ended in an error
that is not silence (the port was not checked). Nothing leaves 127.0.0.1.

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import errno
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


NO_ROUTE = f'errno {errno.EHOSTUNREACH}'  # 113 on Linux, where the scan runs
NO_NETWORK = f'errno {errno.ENETUNREACH}'  # 101 on Linux


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

        self.assertEqual(1, code, out)
        self.assertIn('scan 10.231.47.1 ports 1-65535 (nothing sent): connected 2, '
                      'errno 113 1, refused 65530, timeout 2\n', out)
        self.assertIn('scan connected: 111 46425\n', out)
        refused = [p for p in range(1, 65536) if p not in outcomes or p == 3128]
        self.assertIn('scan refused: ' + ' '.join(map(str, refused[:200])) + ' and 65330 more\n', out)
        self.assertIn('scan timed out: 443 8080\n', out)
        self.assertIn('scan other: 50000 errno 113\n', out)
        self.assertIn('FAIL scan 10.231.47.1: 65532 port(s) answered, so a host holds this address '
                      '(connected 2: 111 46425; refused 65530)\n', out)

    def test_any_port_that_accepts_a_connection_fails_the_run(self):
        with mock.patch.object(net_check, 'attempt', attempt_as_asked), \
                mock.patch.object(net_check, 'probe',
                                  lambda host, port, timeout: 'connected' if port == 101 else 'timeout'):
            code, out = run(*CONTROL, '--scan', '10.231.47.1', '--scan-ports', '100-102')

        self.assertEqual(1, code, out)  # nothing may listen there: H3 stops the run (README.md)
        self.assertIn('scan connected: 101\n', out)
        self.assertIn('FAIL scan 10.231.47.1: 1 port(s) answered, so a host holds this address '
                      '(connected 1: 101; refused 0)\n', out)

    def test_a_refused_port_fails_the_run_since_a_host_answered(self):
        # A refusal is a host's answer (a TCP reset): something holds the address, even with nothing listening on
        # the ports tried. The gateway the review found refused 65,530 ports (README.md, «The gateway»).
        outcomes = {100: 'timeout', 101: 'refused', 102: NO_ROUTE}

        with mock.patch.object(net_check, 'attempt', attempt_as_asked), \
                mock.patch.object(net_check, 'probe', lambda host, port, timeout: outcomes[port]):
            code, out = run(*CONTROL, '--scan', '10.231.47.1', '--scan-ports', '100-102')

        self.assertEqual(1, code, out)
        self.assertIn('scan connected: none\n', out)
        self.assertIn('scan refused: 101\n', out)
        self.assertIn('FAIL scan 10.231.47.1: 1 port(s) answered, so a host holds this address '
                      '(connected 0: none; refused 1)\n', out)
        self.assertNotIn('ok   scan', out)

    def test_a_scan_where_nothing_answers_passes(self):
        outcomes = {100: 'timeout', 101: NO_NETWORK, 102: NO_ROUTE}

        with mock.patch.object(net_check, 'attempt', attempt_as_asked), \
                mock.patch.object(net_check, 'probe', lambda host, port, timeout: outcomes[port]):
            code, out = run(*CONTROL, '--scan', '10.231.47.1', '--scan-ports', '100-102')

        self.assertEqual(0, code, out)
        self.assertIn('scan connected: none\n', out)
        self.assertIn('scan refused: none\n', out)
        counts = ', '.join(f'{k} 1' for k in sorted([NO_NETWORK, NO_ROUTE, 'timeout']))
        self.assertIn(f'ok   scan 10.231.47.1: no port answered ({counts})\n', out)

    def test_an_error_that_is_not_silence_fails_the_run_as_not_checked(self):
        # Too many open files, an address the client could not bind, a reset: the port was not shown silent.
        outcomes = {100: 'timeout', 101: 'errno 24', 102: NO_ROUTE}

        with mock.patch.object(net_check, 'attempt', attempt_as_asked), \
                mock.patch.object(net_check, 'probe', lambda host, port, timeout: outcomes[port]):
            code, out = run(*CONTROL, '--scan', '10.231.47.1', '--scan-ports', '100-102')

        self.assertEqual(1, code, out)
        self.assertIn('FAIL scan 10.231.47.1: 1 port(s) not checked (an error that is not silence): 101 errno 24\n',
                      out)
        self.assertNotIn('ok   scan', out)

    def test_a_clean_scan_does_not_hide_a_failed_check(self):
        with mock.patch.object(net_check, 'attempt', lambda host, port, timeout: ('connected', 'connected')), \
                mock.patch.object(net_check, 'probe', lambda host, port, timeout: 'timeout'):
            code, out = run(*CONTROL, '--scan', '10.231.47.1', '--scan-ports', '100-102')

        self.assertEqual(1, code, out)  # the --block line connected
        self.assertIn('ok   scan 10.231.47.1: no port answered', out)

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
