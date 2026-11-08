"""Tests for w2_check.py on invented fixtures (no RAGFlow needed).

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('w2_check', TOOL_DIR / 'w2_check.py')
w2_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w2_check)

CANVAS_SHA = 'f' * 64
NAMES = [f'law-{n:02d}.md' for n in range(1, 23)]


def texts_of(name: str) -> list[str]:
    return [f'### المادة {k}\nنص تجريبي {k} من {name}\n' for k in range(1, 4)]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.predicted = {n: texts_of(n) for n in NAMES}
        self.stored = {n: list(reversed(texts_of(n))) for n in NAMES}  # listing order is not file order
        self.manifest = {'w2': 1, 'document_count': 22, 'chunk_count': 66, 'predicted_chunk_count': None,
                         'all_match': False, 'canvas_sha256': CANVAS_SHA}
        self.file_sha = {n: hashlib.sha256(n.encode()).hexdigest() for n in NAMES}
        self.state = {'files': [{'name': n, 'sha256': s} for n, s in self.file_sha.items()]}

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self):
        header = {'w2_predict': 1, 'canvas_sha256': CANVAS_SHA, 'files': self.file_sha}
        lines = [header] + [{'file': n, 'i': i, 'text': t} for n, ts in self.predicted.items() for i, t in enumerate(ts)]
        (self.dir / 'p.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in lines), encoding='utf-8')
        rows = [{'document_name': n, 'document_id': 'd', 'chunk_id': f'{n}{i}', 'content': t}
                for n, ts in self.stored.items() for i, t in enumerate(ts)]
        (self.dir / 'c.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows), encoding='utf-8')
        (self.dir / 'w2-manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        (self.dir / 'state.json').write_text(json.dumps(self.state), encoding='utf-8')
        argv = ['--predicted', str(self.dir / 'p.jsonl'), '--dumped', str(self.dir / 'c.jsonl'),
                '--manifest', str(self.dir / 'w2-manifest.json'), '--ingest-state', str(self.dir / 'state.json')]
        out = io.StringIO()
        code = w2_check.main(argv, stdout=out)
        manifest = json.loads((self.dir / 'w2-manifest.json').read_text(encoding='utf-8'))
        return code, out.getvalue(), manifest


class Verdicts(Base):
    def test_the_same_texts_in_another_order_match_and_set_all_match(self):
        code, out, manifest = self.run_check()

        self.assertEqual(code, 0)
        self.assertIn('ALL MATCH', out)
        self.assertEqual((manifest['all_match'], manifest['predicted_chunk_count']), (True, 66))

    def test_one_byte_of_difference_is_found_and_located(self):
        self.stored['law-04.md'][1] = self.stored['law-04.md'][1].replace('نص', 'نص ')

        code, out, manifest = self.run_check()

        self.assertEqual((code, manifest['all_match']), (1, False))
        self.assertIn('BAD law-04: predicted 3, stored 3; 1 text(s) only predicted, 1 only stored', out)
        self.assertIn('first difference at char', out)

    def test_a_missing_chunk_is_a_count_difference(self):
        self.stored['law-09.md'].pop()
        self.manifest['chunk_count'] = 65

        code, out, manifest = self.run_check()

        self.assertEqual((code, manifest['all_match']), (1, False))
        self.assertIn('BAD law-09: predicted 3, stored 2', out)

    def test_a_document_stored_but_not_predicted_is_reported(self):
        self.stored['law-23.md'] = texts_of('law-23.md')
        self.manifest['chunk_count'] = 69

        code, out, _ = self.run_check()

        self.assertEqual(code, 1)
        self.assertIn('BAD law-23: the document is stored only', out)

    def test_a_manifest_chunk_count_that_differs_from_the_dump_fails(self):
        self.manifest['chunk_count'] = 67

        code, out, _ = self.run_check()

        self.assertEqual(code, 1)
        self.assertIn('the manifest says chunk_count 67', out)

    def test_a_prediction_made_from_another_canvas_fails(self):
        self.manifest['canvas_sha256'] = '0' * 64

        code, out, _ = self.run_check()

        self.assertEqual(code, 1)
        self.assertIn('different canvas', out)

    def test_a_prediction_made_from_other_file_bytes_fails(self):
        self.state['files'][0]['sha256'] = '0' * 64

        code, out, _ = self.run_check()

        self.assertEqual(code, 1)
        self.assertIn('different file bytes', out)

    def test_a_prediction_that_covers_21_files_fails(self):
        for table in (self.predicted, self.stored, self.file_sha):
            del table['law-22.md']
        self.state['files'] = self.state['files'][:21]
        self.manifest['chunk_count'] = 63

        code, out, manifest = self.run_check()

        self.assertEqual((code, manifest['all_match']), (1, False))
        self.assertIn('BAD the predictor read 21 files, not 22', out)

    def test_a_manifest_that_names_another_document_count_fails(self):
        self.manifest['document_count'] = 21

        code, out, manifest = self.run_check()

        self.assertEqual((code, manifest['all_match']), (1, False))
        self.assertIn('BAD the manifest says document_count 21, not 22', out)

    def test_a_mismatch_resets_an_earlier_all_match(self):
        self.manifest['all_match'] = True
        self.stored['law-01.md'][0] += 'x'

        _, _, manifest = self.run_check()

        self.assertFalse(manifest['all_match'])

    def test_repeated_predicted_texts_are_named_as_a_collapse(self):
        self.predicted['law-02.md'].append(self.predicted['law-02.md'][0])

        code, out, _ = self.run_check()

        self.assertEqual(code, 1)
        self.assertIn('repeat inside this file', out)

    def test_the_report_records_both_input_hashes(self):
        self.run_check()

        report = json.loads((self.dir / 'w2-check.json').read_text(encoding='utf-8'))
        self.assertEqual(report['predicted_sha256'], hashlib.sha256((self.dir / 'p.jsonl').read_bytes()).hexdigest())
        self.assertEqual(report['dumped_sha256'], hashlib.sha256((self.dir / 'c.jsonl').read_bytes()).hexdigest())


class BadInput(Base):
    def test_a_prediction_without_its_header_is_refused_and_the_manifest_kept(self):
        self.run_check()
        (self.dir / 'p.jsonl').write_text('{"file": "law-01.md", "text": "x"}\n', encoding='utf-8')
        before = (self.dir / 'w2-manifest.json').read_bytes()
        out = io.StringIO()

        code = w2_check.main(['--predicted', str(self.dir / 'p.jsonl'), '--dumped', str(self.dir / 'c.jsonl'),
                              '--manifest', str(self.dir / 'w2-manifest.json'),
                              '--ingest-state', str(self.dir / 'state.json')], stdout=out)

        self.assertEqual(code, 2)
        self.assertEqual((self.dir / 'w2-manifest.json').read_bytes(), before)

    def test_a_check_without_the_ingest_state_is_refused_and_the_manifest_kept(self):
        self.manifest['all_match'] = True
        self.run_check()
        before = (self.dir / 'w2-manifest.json').read_bytes()
        out = io.StringIO()

        code = w2_check.main(['--predicted', str(self.dir / 'p.jsonl'), '--dumped', str(self.dir / 'c.jsonl'),
                              '--manifest', str(self.dir / 'w2-manifest.json')], stdout=out)

        self.assertEqual((code, (self.dir / 'w2-manifest.json').read_bytes()), (2, before))
        self.assertIn('give --ingest-state', out.getvalue())

    def test_an_ingest_state_without_its_file_list_is_refused(self):
        self.state = {'dataset_id': 'd'}

        code, out, manifest = self.run_check()

        self.assertEqual((code, manifest['all_match']), (2, False))
        self.assertIn('holds no "files" list', out)


if __name__ == '__main__':
    unittest.main()
