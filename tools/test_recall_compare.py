"""The host comparison tool (recall plan, Task 1.4). On the host, from the Harness root:
    python -X utf8 -I -B -m unittest discover -s tools -p "test_recall_compare.py" -v
In the eval image (tools/gates.sh step_eval), from tools/, where legal_search is installed:
    python -B -m unittest test_release_eval test_recall_compare
The first seven tests are the plan's. The drive-letter test sets recall_compare.WINDOWS instead of being skipped off
Windows (.claude/rules/tests.md: no skipped tests), so the eval image runs it too."""

import json, random, tempfile, unittest
from pathlib import Path
from unittest import mock
import recall_compare as rc

def report(path, items, corpus='c', set_='s'):
    path.write_text(json.dumps({'run': {'corpus_sha256': corpus, 'set_sha256': set_},
        'items': [{'id': i, 'law': 'x', 'expected': e, 'ranked': r} for i, (e, r) in items.items()]}), encoding='utf-8')
    return f'eval:{path}'

K = lambda n: ['x', n, '']

# A rows: source, the README beside it that names its corpus and set, and an evalset (the bench's formats).
CORPUS, SET = 'c' * 64, '5' * 64

def rows(folder, ranked, cfg='r2|base', corpus=CORPUS, set_=SET, readme=True):
    folder.mkdir()
    (folder / 'rows.jsonl').write_text(''.join(json.dumps({'cfg': cfg, 'id': i, 'ranked': r}) + '\n'
                                               for i, r in ranked.items()), encoding='utf-8')
    if readme:
        (folder / 'README.md').write_text(f'- **corpus_sha256** `{corpus}`\n- **set_sha256** `{set_}`\n', encoding='utf-8')
    return f'rows:{folder / "rows.jsonl"}#{cfg}'

def evalset(path, expected):
    path.write_text(''.join(json.dumps({'id': i, 'scored_law': 'x', 'expected': e}) + '\n'
                            for i, e in expected.items()), encoding='utf-8')
    return path

class RecallCompareTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.d = Path(self.dir.name)
        (self.d / 'split.json').write_text(json.dumps({'a1': 'A', 'a2': 'A', 'b1': 'B', 'b2': 'B'}), encoding='utf-8')
    def tearDown(self): self.dir.cleanup()

    def test_parity_counts_identical_lists_and_names_the_first_divergence(self):
        a = report(self.d / 'a.json', {'a1': ([K(1)], [K(1), K(2)]), 'b1': ([K(3)], [K(3), K(4)])})
        b = report(self.d / 'b.json', {'a1': ([K(1)], [K(1), K(2)]), 'b1': ([K(3)], [K(4), K(3)])})
        identical, diffs = rc.parity(rc.load(a), rc.load(b), k=10)
        self.assertEqual((identical, diffs[0]['id'], diffs[0]['rank']), (1, 'b1', 1))

    def test_items_counts_rescued_kept_and_lost_by_hit_at_5(self):
        cand = {'a1': ([K(1)], [K(1)]), 'a2': ([K(2)], [K(9)] * 5 + [K(2)]), 'b1': ([K(3)], [K(3)]), 'b2': ([K(4)], [K(9)])}
        ref = {'a1': ([K(1)], [K(9)]), 'a2': ([K(2)], [K(2)]), 'b1': ([K(3)], [K(3)]), 'b2': ([K(4)], [K(9)])}
        out = rc.items(rc.load(report(self.d / 'c.json', cand)), rc.load(report(self.d / 'r.json', ref)), self.d / 'split.json')
        self.assertEqual((out['all']['rescued'], out['all']['kept'], out['all']['lost']), (['a1'], ['b1'], ['a2']))

    def test_bootstrap_matches_the_bench_function_on_the_same_differences(self):
        d = [1.0, 0.0, -0.5, 0.5, 0.0, 1.0]
        rng = random.Random(20261106)
        means = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(10000))
        self.assertEqual(rc.bootstrap(d), (sum(d) / len(d), means[250], means[9750 - 1]))

    def test_runs_on_different_corpora_are_refused(self):
        a = report(self.d / 'a.json', {'a1': ([K(1)], [K(1)])}, corpus='c1')
        b = report(self.d / 'b.json', {'a1': ([K(1)], [K(1)])}, corpus='c2')
        with self.assertRaises(SystemExit):
            rc.parity(rc.load(a), rc.load(b), k=10)

    def test_served_recall_skips_repeats_only_when_asked(self):
        first = report(self.d / 'f.json', {'a1': ([K(7)], [K(1), K(2), K(3), K(4), K(5)])})
        second = report(self.d / 's.json', {'a1': ([K(7)], [K(1), K(2), K(3), K(7)])})
        no_skip = rc.served(rc.load(first), rc.load(second), slots=8, first_k=5, skip=False)['a1']
        skip = rc.served(rc.load(first), rc.load(second), slots=8, first_k=5, skip=True)['a1']
        self.assertEqual((no_skip, skip), (0.0, 1.0))

    def test_half_b_none_prints_no_half_b_item(self):
        cand = {'a1': ([K(1)], [K(1)]), 'b1': ([K(3)], [K(3)]), 'b2': ([K(4)], [K(9)])}
        ref = {'a1': ([K(1)], [K(9)]), 'b1': ([K(3)], [K(9)]), 'b2': ([K(4)], [K(4)])}
        text = rc.render_items(rc.items(rc.load(report(self.d / 'c.json', cand)), rc.load(report(self.d / 'r.json', ref)),
                                        self.d / 'split.json'), half_b='none')
        self.assertIn('a1', text); self.assertNotIn('b1', text); self.assertNotIn('b2', text)
        self.assertNotIn('all', text.lower().split())   # no all-80 section: half B = 2 x all - half A

    # A neutral drive and folder: no test may name this machine's paths (deploy/no-machine-paths.test.mjs).
    def test_a_git_bash_drive_path_inside_a_source_is_mapped_to_the_drive(self):
        with mock.patch.object(rc, 'WINDOWS', True):
            self.assertEqual(rc.source_path('eval:/e/work dir/x.json'), Path('E:/work dir/x.json'))
            self.assertEqual(rc.source_path('rows:/e/work dir/b.jsonl#r2|base'), Path('E:/work dir/b.jsonl'))

    # Beyond the plan's seven (Task 1.4 review, 2026-11-09).

    def test_a_drive_path_is_left_as_it_is_off_windows(self):
        with mock.patch.object(rc, 'WINDOWS', False):
            path = rc.source_path('eval:/e/work dir/x.json')

        self.assertEqual(path, Path('/e/work dir/x.json'))

    def test_bootstrap_reproduces_the_bench_function_on_forty_varied_differences(self):
        # The expected triple is rag-bench py/report.py bootstrap() on this list, run on Python 3.12+ as the bench was
        # (build/1.4/fix/bench-bootstrap.out.txt). Python 3.11's plain float sum() differs below 1e-15, hence the 1e-12
        # tolerance; another seed (low end 1.6e-3 away) or the upper index means[9750] (7.5e-5 away) still fails it.
        d = [((i * 7919) % 1000) / 1000 - 0.5 for i in range(40)]

        got = rc.bootstrap(d)

        for value, bench in zip(got, (-0.004500000000000001, -0.097425, 0.0888), strict=True):
            self.assertAlmostEqual(value, bench, delta=1e-12)

    def test_an_interval_end_within_1e_9_of_zero_reads_as_zero(self):
        d = [0.1 + 0.2 - 0.3] * 6   # 5.55e-17 each: every resample mean is that, not 0.0

        got = rc.bootstrap(d)

        self.assertEqual(got[1:], (0.0, 0.0))

    def test_an_item_both_reach_is_kept_even_when_the_candidate_recalls_more(self):
        both = [K(1), K(2)]
        cand = {'a1': (both, [K(1), K(2)])}
        ref = {'a1': (both, [K(1), K(9)])}

        out = rc.items(rc.load(report(self.d / 'c.json', cand)), rc.load(report(self.d / 'r.json', ref)), self.d / 'split.json')

        self.assertEqual((out['all']['rescued'], out['all']['kept'], out['all']['up']), ([], ['a1'], ['a1']))

    def test_runs_on_different_sets_are_refused(self):
        a = report(self.d / 'a.json', {'a1': ([K(1)], [K(1)])}, set_='s1')
        b = report(self.d / 'b.json', {'a1': ([K(1)], [K(1)])}, set_='s2')

        with self.assertRaisesRegex(SystemExit, 'differ in set_sha256'):
            rc.parity(rc.load(a), rc.load(b), k=10)

    def test_a_rows_source_without_a_basis_readme_is_refused(self):
        source = rows(self.d / 'rows', {'a1': [K(1)]}, readme=False)

        with self.assertRaisesRegex(SystemExit, 'no basis README'):
            rc.load(source)

    def test_a_basis_option_naming_no_file_is_refused_rather_than_skipped(self):
        source = rows(self.d / 'rows', {'a1': [K(1)]})   # a valid README.md sits beside the rows file

        with self.assertRaisesRegex(SystemExit, 'no basis README'):
            rc.load(source, basis=self.d / 'rows' / 'READMEE.md')

    def test_a_basis_readme_naming_two_corpora_is_refused(self):
        source = rows(self.d / 'rows', {'a1': [K(1)]})
        with (self.d / 'rows' / 'README.md').open('a', encoding='utf-8') as readme:
            readme.write(f'- **corpus_sha256** `{"d" * 64}`\n')

        with self.assertRaisesRegex(SystemExit, 'names 2 values of corpus_sha256'):
            rc.load(source)

    def test_a_source_holding_an_item_twice_is_refused(self):
        source = rows(self.d / 'rows', {'a1': [K(1)]})
        with (self.d / 'rows' / 'rows.jsonl').open('a', encoding='utf-8') as lines:
            lines.write(json.dumps({'cfg': 'r2|base', 'id': 'a1', 'ranked': [K(2)]}) + '\n')

        with self.assertRaisesRegex(SystemExit, 'item a1 twice'):
            rc.load(source)

    def test_a_rows_source_whose_basis_names_another_corpus_is_refused(self):
        cand = rows(self.d / 'rows', {'a1': [K(1)]}, corpus='a' * 64)
        ref = report(self.d / 'r.json', {'a1': ([K(1)], [K(1)])}, corpus=CORPUS, set_=SET)

        with self.assertRaisesRegex(SystemExit, 'differ in corpus_sha256'):
            rc.parity(rc.load(cand), rc.load(ref), k=10)

    def test_a_rows_source_without_evalset_takes_expected_articles_from_the_eval_side(self):
        cand = rows(self.d / 'rows', {'a1': [K(1)]})
        ref = report(self.d / 'r.json', {'a1': ([K(1)], [K(9)])}, corpus=CORPUS, set_=SET)

        out = rc.items(rc.load(cand), rc.load(ref), self.d / 'split.json')

        self.assertEqual(out['all']['rescued'], ['a1'])

    def test_a_rows_source_whose_evalset_expects_other_articles_is_refused(self):
        truth = evalset(self.d / 'eval.jsonl', {'a1': [K(2)]})
        cand = rows(self.d / 'rows', {'a1': [K(1)]})
        ref = report(self.d / 'r.json', {'a1': ([K(1)], [K(1)])}, corpus=CORPUS, set_=SET)

        with self.assertRaisesRegex(SystemExit, 'expect different articles'):
            rc.items(rc.load(cand, evalset=truth), rc.load(ref), self.d / 'split.json')

    def test_a_run_with_no_items_is_refused(self):
        empty = report(self.d / 'e.json', {})

        with self.assertRaisesRegex(SystemExit, 'holds no items'):
            rc.load(empty)

    def test_a_report_without_its_set_and_corpus_digests_is_refused(self):
        path = self.d / 'old.json'
        path.write_text(json.dumps({'run': {'label': 'old'}, 'items': [{'id': 'a1', 'law': 'x', 'expected': [K(1)],
                                                                         'ranked': [K(1)]}]}), encoding='utf-8')

        with self.assertRaisesRegex(SystemExit, 'names no'):
            rc.load(f'eval:{path}')


if __name__ == '__main__':
    unittest.main()
