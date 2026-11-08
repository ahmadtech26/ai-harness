"""Tests for fallback_items.py and timed_run.py on invented log fixtures (no RAGFlow needed).

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOL_DIR / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fallback_items = load('fallback_items')
timed_run = load('timed_run')

T0 = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)
API_PID, EXECUTOR_PID = 41, 77
ITEMS = ['civil-code-01', 'evidence-02', 'penal-03']


def docker_line(ts: datetime, pid: int, level: str, msg: str) -> str:
    asctime = ts.strftime('%Y-%m-%d %H:%M:%S,') + f'{ts.microsecond // 1000:03d}'
    return f'{ts.strftime("%Y-%m-%dT%H:%M:%S")}.{ts.microsecond:06d}123Z {asctime} {level:<8} {pid} {msg}'


def stamp(ts: datetime) -> str:
    return ts.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


class Run:
    """An invented run of len(ITEMS) items on two fields: request k spans [T0 + 2k s, T0 + 2k + 2 s]."""

    def __init__(self):
        self.rows = [{'id': i, 'field': f, 'sent': 'x', 'status': 'ok', 'error': None, 'chunks': [{'rank': 1}]}
                     for f in ('query', 'question') for i in ITEMS]
        self.fallback_at: set[int] = set()   # request numbers (1-based) whose search falls back
        self.extra_anchor_at: set[int] = set()
        self.late_anchor_at: set[int] = set()  # anchor stamped after the request's end
        self.first_attempt_fallback_at: set[int] = set()  # a retried request whose first attempt fell back
        self.missing_anchor_at: set[int] = set()  # an answered request whose retrieval call was not logged
        self.wrong_progress_id_at: set[int] = set()  # a progress line naming another item than its row
        self.before_window_anchor = False  # a retrieval call and a fallback logged 10 s before the run started
        self.stray_anchor_after = False  # a retrieval call inside the log window but after the last request

    def span(self, k: int) -> tuple[datetime, datetime]:
        return T0 + timedelta(seconds=2 * k), T0 + timedelta(seconds=2 * k + 2)

    def write(self, folder: Path) -> dict:
        n = len(self.rows)
        header = {'w1': 1, 'started_at': T0.isoformat(timespec='seconds'),
                  'finished_at': (T0 + timedelta(seconds=2 * n + 3)).isoformat(timespec='seconds'),
                  'fields': ['query', 'question'], 'counts': {'planned': n, 'ok': n, 'error': 0, 'not_run': 0}}
        (folder / 'results.jsonl').write_text(
            ''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in [header, *self.rows]), encoding='utf-8')
        log = [docker_line(T0 - timedelta(seconds=30), EXECUTOR_PID, 'INFO', 'task executor heartbeat'),
               docker_line(T0 + timedelta(seconds=1), API_PID, 'DEBUG', 'Dealer.search TOTAL: 12')]
        if self.before_window_anchor:
            log[1:1] = [docker_line(T0 - timedelta(seconds=10), API_PID, 'DEBUG', '[Search] page=1, page_size=20'),
                        docker_line(T0 - timedelta(seconds=10) + timedelta(milliseconds=30), API_PID, 'DEBUG',
                                    'Dealer.search dense-only fallback after empty initial search')]
        run_log = [f'{stamp(T0 + timedelta(seconds=1))}\t# timed_run start: python3 run_w1.py']
        for k, row in enumerate(self.rows, start=1):
            lo, hi = self.span(k)
            anchors = 0 if k in self.missing_anchor_at else 2 if k in self.extra_anchor_at else 1
            for a in range(anchors):
                at = hi + timedelta(milliseconds=500) if k in self.late_anchor_at else lo + timedelta(milliseconds=100 + 300 * a)
                log.append(docker_line(at, API_PID, 'DEBUG', '[Search] page=1, page_size=20, rerank_candidates_count=64'))
                log.append(docker_line(at + timedelta(milliseconds=10), EXECUTOR_PID, 'DEBUG', 'Dealer.search TOTAL: 0'))
                log.append(docker_line(at + timedelta(milliseconds=20), API_PID, 'DEBUG', 'Dealer.search TOTAL: 0'))
                if (k in self.fallback_at and a == anchors - 1) or (k in self.first_attempt_fallback_at and a == 0):
                    log.append(docker_line(at + timedelta(milliseconds=30), API_PID, 'DEBUG',
                                           'Dealer.search dense-only fallback after empty hybrid retries'))
                log.append('Traceback (most recent call last):  <- a line without the RAGFlow prefix')
            named = 'another-item' if k in self.wrong_progress_id_at else row['id']
            run_log.append(f'{stamp(hi)}\t{k}/{n} {row["field"]} {named}: 1 chunks')
        if self.stray_anchor_after:  # after the last progress stamp, before finished_at + 2 s
            log.append(docker_line(self.span(n)[1] + timedelta(milliseconds=500), API_PID, 'DEBUG',
                                   '[Search] page=1, page_size=20, rerank_candidates_count=64'))
        run_log.append(f'{stamp(T0 + timedelta(seconds=2 * n + 3))}\t# timed_run exit 0')
        (folder / 'server.log').write_text('\n'.join(log) + '\n', encoding='utf-8')
        (folder / 'run.log').write_text('\n'.join(run_log) + '\n', encoding='utf-8')
        return header


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.run = Run()

    def tearDown(self):
        self.tmp.cleanup()

    def find(self, *, run_log=True):
        self.run.write(self.dir)
        argv = ['--results', str(self.dir / 'results.jsonl'), '--server-log', str(self.dir / 'server.log'),
                '--out', str(self.dir / 'w2-fallback-v3.json')]
        if run_log:
            argv += ['--run-log', str(self.dir / 'run.log')]
        out = io.StringIO()
        code = fallback_items.main(argv, stdout=out)
        path = self.dir / 'w2-fallback-v3.json'
        found = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        return code, found, out.getvalue()


class Matching(Base):
    def test_an_item_whose_search_fell_back_is_listed_under_its_field(self):
        self.run.fallback_at = {5}  # the second item on the question field

        code, found, _ = self.find()

        self.assertEqual(code, 0)
        self.assertEqual(found, {'query': [], 'question': ['evidence-02']})

    def test_a_retrieval_call_logged_before_the_run_is_ignored(self):
        self.run.before_window_anchor = True
        self.run.fallback_at = {2}

        code, found, _ = self.find()

        report = json.loads((self.dir / 'w2-fallback-v3.report.json').read_text(encoding='utf-8'))
        self.assertEqual(code, 0)
        self.assertEqual((report['mapping'], report['retrieval_calls_logged']), ('sequence', 6))
        self.assertEqual(found, {'query': ['evidence-02'], 'question': []})

    def test_a_fallback_that_returned_nothing_is_reported_but_not_listed(self):
        self.run.fallback_at = {2}
        self.run.rows[1]['chunks'] = []

        code, found, _ = self.find()

        report = json.loads((self.dir / 'w2-fallback-v3.report.json').read_text(encoding='utf-8'))
        self.assertEqual(code, 0)
        self.assertEqual(found['query'], [])
        self.assertEqual(report['fallback_returned_nothing']['query'], ['evidence-02'])

    def test_a_retried_request_is_placed_by_time_and_takes_its_last_attempt(self):
        self.run.extra_anchor_at = {4}
        self.run.fallback_at = {6}

        code, found, _ = self.find()

        report = json.loads((self.dir / 'w2-fallback-v3.report.json').read_text(encoding='utf-8'))
        self.assertEqual(code, 0)
        self.assertEqual((report['mapping'], report['retried']), ('time', ['question:civil-code-01']))
        self.assertEqual(found, {'query': [], 'question': ['penal-03']})


    def test_a_retried_request_is_judged_by_the_attempt_whose_answer_was_kept(self):
        self.run.extra_anchor_at = {4}
        self.run.first_attempt_fallback_at = {4}

        code, found, _ = self.find()

        self.assertEqual(code, 0)
        self.assertEqual(found, {'query': [], 'question': []})


class Refusals(Base):
    def test_without_the_run_log_nothing_is_written(self):
        self.run.fallback_at = {1}

        code, found, out = self.find(run_log=False)

        self.assertEqual((code, found), (2, None))
        self.assertIn('give --run-log', out)

    def test_a_retrieval_call_outside_every_request_writes_nothing(self):
        self.run.stray_anchor_after = True

        code, found, out = self.find()

        self.assertEqual((code, found), (1, None))
        self.assertIn('outside every request', out)

    def test_an_answered_request_without_a_logged_retrieval_call_writes_nothing(self):
        self.run.missing_anchor_at = {2}

        code, found, out = self.find()

        self.assertEqual((code, found), (1, None))
        self.assertIn('no retrieval call was logged during it', out)

    def test_a_progress_line_that_names_another_item_than_its_row_is_refused(self):
        self.run.wrong_progress_id_at = {3}

        code, found, out = self.find()

        self.assertEqual((code, found), (2, None))
        self.assertIn('progress line 3 does not match row 3', out)

    def test_a_call_logged_outside_its_request_time_writes_nothing(self):
        self.run.late_anchor_at = {3}

        code, found, out = self.find()

        self.assertEqual((code, found), (1, None))

    def test_a_fallback_line_from_a_process_that_logged_no_retrieval_call_writes_nothing(self):
        self.run.write(self.dir)
        stray = docker_line(T0 + timedelta(seconds=4, milliseconds=200), EXECUTOR_PID, 'DEBUG',
                            'Dealer.search dense-only fallback after empty initial search')
        with open(self.dir / 'server.log', 'a', encoding='utf-8') as log:
            log.write(stray + '\n')
        out = io.StringIO()

        code = fallback_items.main(['--results', str(self.dir / 'results.jsonl'), '--server-log',
                                    str(self.dir / 'server.log'), '--run-log', str(self.dir / 'run.log'),
                                    '--out', str(self.dir / 'f.json')], stdout=out)

        self.assertEqual(code, 1)
        self.assertIn(f'in process {EXECUTOR_PID}', out.getvalue())

    def test_a_log_without_debug_lines_writes_nothing(self):
        self.run.write(self.dir)
        (self.dir / 'server.log').write_text(docker_line(T0, API_PID, 'INFO', 'server is ready') + '\n',
                                             encoding='utf-8')
        out = io.StringIO()

        code = fallback_items.main(['--results', str(self.dir / 'results.jsonl'), '--server-log',
                                    str(self.dir / 'server.log'), '--run-log', str(self.dir / 'run.log'),
                                    '--out', str(self.dir / 'f.json')], stdout=out)

        self.assertEqual(code, 1)
        self.assertIn('not logging at DEBUG', out.getvalue())

    def test_an_incomplete_run_is_refused(self):
        self.run.write(self.dir)
        lines = (self.dir / 'results.jsonl').read_text(encoding='utf-8').splitlines()
        (self.dir / 'results.jsonl').write_text('\n'.join(lines[:-1]) + '\n', encoding='utf-8')
        out = io.StringIO()

        code = fallback_items.main(['--results', str(self.dir / 'results.jsonl'), '--server-log',
                                    str(self.dir / 'server.log'), '--run-log', str(self.dir / 'run.log'),
                                    '--out', str(self.dir / 'f.json')], stdout=out)

        self.assertEqual(code, 2)

    def test_an_existing_output_is_not_overwritten(self):
        (self.dir / 'w2-fallback-v3.json').write_text('{}', encoding='utf-8')

        code, found, _ = self.find()

        self.assertEqual((code, found), (2, {}))


class TimedRun(unittest.TestCase):
    def test_each_line_is_stamped_and_the_exit_code_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'run.log'
            child = [sys.executable, '-I', '-c', 'import sys; print("1/2 query a: ok", flush=True); '
                     'print("2/2 query b: ok", file=sys.stderr); sys.exit(3)']

            code = timed_run.main(['--log', str(log), '--', *child], echo=io.StringIO())

            lines = log.read_text(encoding='utf-8').splitlines()
        self.assertEqual(code, 3)
        self.assertEqual([x.split('\t', 1)[1] for x in lines[1:]], ['1/2 query a: ok', '2/2 query b: ok', '# timed_run exit 3'])
        self.assertRegex(lines[1], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z\t')

    def test_an_existing_log_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'run.log'
            log.write_text('kept\n', encoding='utf-8')

            code = timed_run.main(['--log', str(log), '--', sys.executable, '-c', 'pass'], echo=io.StringIO())

            self.assertEqual((code, log.read_text(encoding='utf-8')), (2, 'kept\n'))


if __name__ == '__main__':
    unittest.main()
