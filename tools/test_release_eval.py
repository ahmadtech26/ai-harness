"""The release retrieval gate. From tools/, where legal_search is importable (the eval image):
    python -B -m unittest test_release_eval
The real keep rule and targets run here, so a reworded reason in legal_search.metrics fails these tests."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import release_eval


def run_of(recall5=0.5, mrr=0.5, civil=0.5, penal=0.5, **run):
    return {
        'run': {'label': 'release', 'set_sha256': 'set-a', 'corpus_sha256': 'corpus-a', **run},
        'metrics': {
            'overall': {'recall@5': recall5, 'mrr': mrr},
            'per_law': {'civil-code': {'recall@5': civil}, 'penal-code': {'recall@5': penal}},
        },
        'items': [{'id': 'civil-code-01', 'query': 'q'}],
    }


class CheckTest(unittest.TestCase):
    def test_identical_metrics_pass(self):
        code, lines = release_eval.check(run_of(), run_of())
        self.assertEqual(code, 0, lines)
        self.assertNotIn('no change', '\n'.join(lines))

    def test_a_rise_passes(self):
        code, lines = release_eval.check(run_of(recall5=0.6, penal=0.7), run_of())
        self.assertEqual(code, 0, lines)

    def test_an_overall_recall_drop_fails(self):
        code, lines = release_eval.check(run_of(recall5=0.4), run_of())
        self.assertEqual(code, 1)
        self.assertIn('overall recall@5 drops 0.5000 -> 0.4000', '\n'.join(lines))

    def test_one_law_dropping_fails_and_names_the_law(self):
        code, lines = release_eval.check(run_of(penal=0.25), run_of())
        self.assertEqual(code, 1)
        reasons = '\n'.join(lines).split('targets:')[0]  # the targets lines name every law under the floor
        self.assertIn('penal-code recall@5 drops 0.5000 -> 0.2500', reasons)
        self.assertNotIn('civil-code', reasons)

    def test_every_reason_is_listed(self):
        code, lines = release_eval.check(run_of(mrr=0.4, civil=0.3, penal=0.2), run_of())
        self.assertEqual(code, 1)
        text = '\n'.join(lines)
        for reason in ('overall mrr drops', 'civil-code recall@5 drops', 'penal-code recall@5 drops'):
            self.assertIn(reason, text)

    def test_a_different_set_or_corpus_fails_and_says_how_to_refresh(self):
        for field in ('set_sha256', 'corpus_sha256'):
            with self.subTest(field):
                code, lines = release_eval.check(run_of(recall5=0.9, **{field: 'other'}), run_of())
                self.assertEqual(code, 1)
                text = '\n'.join(lines)
                self.assertIn(field, text)
                self.assertIn('write-baseline', text)

    def test_a_different_set_is_not_compared_at_all(self):
        _, lines = release_eval.check(run_of(recall5=0.1, set_sha256='other'), run_of())
        self.assertNotIn('drops', '\n'.join(lines))


class TargetsTest(unittest.TestCase):
    def test_missed_targets_print_missed_and_still_exit_0(self):
        code, lines = release_eval.check(run_of(), run_of())
        self.assertEqual(code, 0, lines)
        text = '\n'.join(lines)
        self.assertIn('targets: MISSED', text)
        self.assertIn('overall recall@5 0.5000 < 0.8', text)
        self.assertIn('civil-code recall@5 0.5000 < 0.6', text)
        self.assertIn('overall MRR 0.5000 < 0.6', text)

    def test_meeting_the_agreed_targets_prints_met(self):
        met = run_of(recall5=0.8, mrr=0.6, civil=0.6, penal=0.6)
        _, lines = release_eval.check(met, met)
        self.assertIn('targets: MET', lines)
        self.assertNotIn('targets: MISSED', lines)

    def test_each_agreed_target_is_held_at_its_number(self):
        cases = {'recall5': {'recall5': 0.79}, 'law floor': {'civil': 0.59}, 'mrr': {'mrr': 0.59}}
        for name, below in cases.items():
            with self.subTest(name):
                values = {'recall5': 0.8, 'mrr': 0.6, 'civil': 0.6, 'penal': 0.6, **below}
                _, lines = release_eval.check(run_of(**values), run_of(**values))
                self.assertIn('targets: MISSED', lines)

    def test_a_failing_run_still_prints_the_targets(self):
        for failing in (run_of(recall5=0.4), run_of(set_sha256='other')):
            code, lines = release_eval.check(failing, run_of())
            self.assertEqual(code, 1)
            self.assertIn('targets: MISSED', lines)


class FilesTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.report = Path(folder.name) / 'report.json'
        self.baseline = Path(folder.name) / 'baseline.json'

    def main(self, command):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = release_eval.main([command, '--report', str(self.report), '--baseline', str(self.baseline)])
        return code, out.getvalue()

    def test_write_baseline_keeps_run_and_metrics_and_drops_the_items(self):
        report = run_of(recall5=0.5312)
        self.report.write_text(json.dumps(report), encoding='utf-8')
        code, _ = self.main('write-baseline')
        self.assertEqual(code, 0)
        written = json.loads(self.baseline.read_text(encoding='utf-8'))
        self.assertEqual(written, {'run': report['run'], 'metrics': report['metrics']})

    def test_a_run_passes_against_the_baseline_written_from_it(self):
        self.report.write_text(json.dumps(run_of()), encoding='utf-8')
        self.main('write-baseline')
        code, out = self.main('check')
        self.assertEqual(code, 0, out)
        self.assertIn('targets: MISSED', out)

    def test_write_baseline_refuses_a_report_without_metrics_and_writes_nothing(self):
        self.report.write_text(json.dumps({'run': run_of()['run']}), encoding='utf-8')
        code, _ = self.main('write-baseline')
        self.assertEqual(code, 1)
        self.assertFalse(self.baseline.exists())

    def test_a_missing_baseline_fails_and_says_how_to_create_it(self):
        self.report.write_text(json.dumps(run_of()), encoding='utf-8')
        code, out = self.main('check')
        self.assertEqual(code, 1)
        self.assertIn('write-baseline', out)

    def test_a_baseline_that_cannot_be_compared_fails(self):
        self.report.write_text(json.dumps(run_of()), encoding='utf-8')
        for unusable in ('not json', '{}', json.dumps({'metrics': run_of()['metrics']}), json.dumps({'run': run_of()['run']})):
            with self.subTest(unusable):
                self.baseline.write_text(unusable, encoding='utf-8')
                code, _ = self.main('check')
                self.assertEqual(code, 1)

    def test_the_process_exits_1_on_a_regression(self):
        self.report.write_text(json.dumps(run_of(recall5=0.4)), encoding='utf-8')
        self.baseline.write_text(json.dumps(run_of()), encoding='utf-8')
        script = Path(__file__).with_name('release_eval.py')
        command = [sys.executable, '-B', str(script), 'check', '--report', str(self.report), '--baseline', str(self.baseline)]
        done = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn('overall recall@5 drops', done.stdout)


if __name__ == '__main__':
    unittest.main()
