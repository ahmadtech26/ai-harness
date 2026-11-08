"""Tests for tei_probe.py's batch choice and article blocks, and net_check.py's verdicts. Local only.

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import importlib.util
import io
import socket
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOL_DIR / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tei_probe = load('tei_probe')
net_check = load('net_check')


class BatchChoice(unittest.TestCase):
    def test_the_largest_batch_under_the_target_wins(self):
        timings = {16: (True, 22.0), 8: (True, 11.0), 4: (True, 6.0), 2: (True, 3.0), 1: (True, 1.5)}

        self.assertEqual(tei_probe.choose(timings, 15.0), 8)

    def test_a_batch_with_a_failed_call_is_never_chosen(self):
        timings = {16: (False, 2.0), 8: (True, 9.0), 4: (True, 5.0), 2: (True, 3.0), 1: (True, 1.0)}

        self.assertEqual(tei_probe.choose(timings, 15.0), 8)

    def test_no_batch_under_the_target_gives_none(self):
        timings = {16: (True, 90.0), 8: (True, 50.0), 4: (True, 30.0), 2: (True, 20.0), 1: (True, 16.0)}

        self.assertIsNone(tei_probe.choose(timings, 15.0))


class ArticleBlocks(unittest.TestCase):
    def test_a_block_runs_from_an_article_heading_to_the_next_heading_of_any_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'x.md').write_text('# قانون\n\n### المادة 1\n\nأ\n\n## الفصل الثاني\n### المادة 2\n\nب\nج\n',
                                         encoding='utf-8')

            blocks = tei_probe.article_blocks(Path(tmp))

        self.assertEqual(blocks, ['### المادة 1\nأ\n', '### المادة 2\nب\nج\n'])


class NetCheck(unittest.TestCase):
    def test_an_open_port_is_reached_and_a_refused_port_does_not_count_as_blocked(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        closed = socket.socket()
        closed.bind(('127.0.0.1', 0))
        closed_port = closed.getsockname()[1]
        closed.close()
        out = io.StringIO()
        try:
            code = net_check.main(['--reach', f'127.0.0.1:{listener.getsockname()[1]}',
                                   '--block', f'127.0.0.1:{closed_port}', '--timeout', '10'], stdout=out)  # Windows retries a refused SYN for about 2 s
        finally:
            listener.close()

        self.assertEqual(code, 1)
        self.assertRegex(out.getvalue(), r'ok   reach 127\.0\.0\.1:\d+: connected')
        self.assertRegex(out.getvalue(), r'FAIL block 127\.0\.0\.1:\d+')

    def test_a_name_that_does_not_resolve_counts_as_blocked(self):
        self.assertEqual(net_check.attempt('no-such-host.invalid', 443, 2)[0], 'blocked')

    def test_a_check_without_a_positive_control_is_refused(self):
        self.assertEqual(net_check.main(['--block', '1.1.1.1:443'], stdout=io.StringIO()), 2)


if __name__ == '__main__':
    unittest.main()
