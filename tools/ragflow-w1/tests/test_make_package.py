"""make_package.py: what goes to Walid holds only id, query and question, and SHA256SUMS matches the files."""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import make_package

REPO = Path(__file__).resolve().parents[3]
EVAL = REPO / 'content' / 'eval' / 'retrieval-v1.jsonl'
STAND_IN_RUNNER = b'#!/usr/bin/env python3\n"""Stand-in for run_w1.py in tests."""\nprint("stand-in")\n'
DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def gold(path: Path) -> list[dict]:
    """The eval items, parsed here independently of make_package."""
    lines = [line for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    return [json.loads(line) for line in lines[1:]]


def numbers(text: str) -> set[int]:
    return {int(run) for run in re.findall(r'[0-9]+', text.translate(DIGITS))}


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.runner = self.root / 'src' / 'run_w1.py'
        self.runner.parent.mkdir()
        self.runner.write_bytes(STAND_IN_RUNNER)
        self.out = self.root / 'package'

    def run_tool(self, *extra: str, eval_path: Path = EVAL, out: Path | None = None,
                 runner: Path | None = None) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ['--eval', str(eval_path), '--out', str(out or self.out), '--runner', str(runner or self.runner), *extra]
        code = make_package.main(argv, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def package_lines(self) -> list[dict]:
        return [json.loads(line) for line in (self.out / 'w1-queries.jsonl').read_text(encoding='utf-8').split('\n')
                if line]


class RealSetTests(Case):
    def setUp(self):
        super().setUp()
        code, _, stderr = self.run_tool()
        self.assertEqual(code, 0, stderr)
        self.lines = self.package_lines()
        self.header, self.items = self.lines[0], self.lines[1:]
        self.gold = gold(EVAL)

    def test_the_default_eval_set_is_the_frozen_one(self):
        self.assertEqual(make_package.DEFAULT_EVAL.resolve(), EVAL.resolve())
        lines = [line for line in EVAL.read_bytes().decode('utf-8').replace('\r\n', '\n').split('\n') if line.strip()]
        self.assertEqual(hashlib.sha256('\n'.join(lines[1:]).encode('utf-8')).hexdigest(),
                         make_package.FROZEN_SET_SHA256)

    def test_header(self):
        self.assertEqual(self.header, {'set': 'retrieval-v1', 'w1': 1, 'count': 80, 'fields': ['query', 'question'],
                                       'note': make_package.NOTE})
        self.assertEqual(len(self.items), 80)
        self.assertRegex(self.header['note'], '[A-Za-z]')
        self.assertRegex(self.header['note'], '[؀-ۿ]')

    def test_items_carry_only_id_query_and_question(self):
        for item in self.items:
            self.assertEqual(list(item), ['id', 'query', 'question'])

    def test_ids_and_texts_equal_the_eval_set_in_its_order(self):
        self.assertEqual([(i['id'], i['query'], i['question']) for i in self.items],
                         [(g['id'], g['query'], g['question']) for g in self.gold])

    def test_no_gold_key_or_notes_text_appears(self):
        text = (self.out / 'w1-queries.jsonl').read_text(encoding='utf-8')
        for key in ('expected', 'expected_notes', 'notes', 'law', 'suffix', 'number', 'scored_law'):
            self.assertNotIn(f'"{key}"', text)
        for item in self.gold:
            self.assertNotIn(item['notes'], text)
        self.assertNotIn('sections/', text)
        self.assertNotIn('.md', text)

    def test_no_expected_article_number_appears_unless_the_item_text_has_it(self):
        sent = {item['id']: item for item in self.items}
        for item in self.gold:
            own = numbers(item['query'] + ' ' + item['question'])
            line = sent[item['id']]
            shown = numbers(line['query'] + ' ' + line['question'])
            for expected in item['expected']:
                if expected['number'] in shown:
                    self.assertIn(expected['number'], own, item['id'])
                label = f'المادة {expected["number"]}'
                if label in json.dumps(line, ensure_ascii=False):
                    self.assertIn(label, item['query'] + item['question'], item['id'])
        header_numbers = numbers(json.dumps(self.header, ensure_ascii=False))
        self.assertEqual(header_numbers, {1, 80})

    def test_sha256sums_matches_the_two_files(self):
        sums = (self.out / 'SHA256SUMS').read_bytes()
        self.assertNotIn(b'\r', sums)
        self.assertTrue(sums.endswith(b'\n'))
        rows = [re.fullmatch(r'([0-9a-f]{64})  (\S+)', row) for row in sums.decode('ascii').splitlines()]
        self.assertTrue(all(rows), sums)
        listed = {row.group(2): row.group(1) for row in rows}
        self.assertEqual(list(listed), ['w1-queries.jsonl', 'run_w1.py'])
        for name, digest in listed.items():
            self.assertEqual(hashlib.sha256((self.out / name).read_bytes()).hexdigest(), digest, name)

    def test_runner_is_copied_byte_for_byte(self):
        self.assertEqual((self.out / 'run_w1.py').read_bytes(), STAND_IN_RUNNER)

    def test_queries_file_is_utf8_with_lf_and_no_bom(self):
        data = (self.out / 'w1-queries.jsonl').read_bytes()
        self.assertFalse(data.startswith(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\r', data)
        self.assertTrue(data.endswith(b'\n'))
        self.assertEqual(data.count(b'\n'), 81)
        data.decode('utf-8')

    def test_the_folder_holds_only_the_package(self):
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ['SHA256SUMS', 'run_w1.py', 'w1-queries.jsonl'])


class CanaryTests(Case):
    """A stand-in set with planted gold: none of it may reach the package."""

    CANARIES = ('9871', '9872', '4242', 'canary-law-slug', 'CANARY-NOTE', 'canary-suffix')

    def setUp(self):
        super().setUp()
        self.eval = self.root / 'eval.jsonl'
        rows = [
            {'set': 'canary-set', 'review': {'status': 'draft'}, 'description': 'stand-in'},
            {'id': 'evidence-01', 'question': 'سؤال أول عن البينة', 'query': 'عبارة بحث أولى',
             'law': 'canary-law-slug', 'expected': [{'law': 'canary-law-slug', 'number': 9871, 'suffix': 'canary-suffix'}],
             'notes': 'CANARY-NOTE sections/x.md'},
            {'id': 'civil-code-memo-01', 'question': 'سؤال ثان', 'query': 'عبارة ثانية',
             'expected': [{'law': 'canary-law-slug', 'number': 9872}], 'expected_notes': [4242],
             'notes': 'CANARY-NOTE again'},
        ]
        self.eval.write_text('\r\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\r\n', encoding='utf-8')

    def test_planted_gold_never_reaches_the_package(self):
        code, _, stderr = self.run_tool('--allow-other-set', eval_path=self.eval)
        self.assertEqual(code, 0, stderr)
        text = (self.out / 'w1-queries.jsonl').read_text(encoding='utf-8')
        for canary in self.CANARIES:
            self.assertNotIn(canary, text)
        lines = self.package_lines()
        self.assertEqual(lines[0]['set'], 'canary-set')
        self.assertEqual(lines[0]['count'], 2)
        self.assertEqual(lines[1:], [
            {'id': 'evidence-01', 'query': 'عبارة بحث أولى', 'question': 'سؤال أول عن البينة'},
            {'id': 'civil-code-memo-01', 'query': 'عبارة ثانية', 'question': 'سؤال ثان'},
        ])

    def test_a_set_other_than_the_frozen_one_is_refused_by_default(self):
        code, _, stderr = self.run_tool(eval_path=self.eval)
        self.assertEqual(code, 2)
        self.assertIn('not the frozen set', stderr)
        self.assertFalse(self.out.exists())

    def test_a_one_character_change_to_the_real_set_is_refused(self):
        changed = self.root / 'changed.jsonl'
        changed.write_bytes(EVAL.read_bytes().replace('العربون'.encode('utf-8'), 'العربو'.encode('utf-8'), 1))
        code, _, stderr = self.run_tool(eval_path=changed)
        self.assertEqual(code, 2)
        self.assertIn('not the frozen set', stderr)
        self.assertFalse(self.out.exists())


class LineSeparatorTests(Case):
    def test_a_unicode_line_separator_in_a_text_does_not_split_its_line(self):
        # run_w1.py reads the file with str.splitlines(), which also splits on U+2028 and U+2029.
        text = 'سؤال ثان ثالث'
        rows = [{'set': 'separator-set'}, {'id': 'evidence-01', 'question': text, 'query': 'عبارة'}]
        eval_path = self.root / 'separator.jsonl'
        eval_path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')

        code, _, stderr = self.run_tool('--allow-other-set', eval_path=eval_path)

        self.assertEqual(code, 0, stderr)
        lines = (self.out / 'w1-queries.jsonl').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])['question'], text)


class RefusalTests(Case):
    def test_a_missing_runner_is_refused_and_nothing_is_written(self):
        code, stdout, stderr = self.run_tool(runner=self.root / 'nowhere' / 'run_w1.py')
        self.assertEqual(code, 2)
        self.assertIn('run_w1.py not found', stderr)
        self.assertIn('nothing was written', stderr)
        self.assertEqual(stdout, '')
        self.assertFalse(self.out.exists())

    def test_a_missing_runner_leaves_an_existing_folder_as_it_was(self):
        self.out.mkdir()
        (self.out / 'message-for-walid.md').write_text('draft', encoding='utf-8')
        code, _, _ = self.run_tool(runner=self.root / 'nowhere' / 'run_w1.py')
        self.assertEqual(code, 2)
        self.assertEqual([p.name for p in self.out.iterdir()], ['message-for-walid.md'])

    def test_existing_package_files_are_kept_without_replace(self):
        self.assertEqual(self.run_tool()[0], 0)
        before = {p.name: p.read_bytes() for p in self.out.iterdir()}
        self.runner.write_bytes(STAND_IN_RUNNER + b'# changed\n')
        code, _, stderr = self.run_tool()
        self.assertEqual(code, 2)
        self.assertIn('--replace', stderr)
        self.assertEqual({p.name: p.read_bytes() for p in self.out.iterdir()}, before)

    def test_replace_overwrites_the_package_and_leaves_other_files_alone(self):
        self.assertEqual(self.run_tool()[0], 0)
        message = self.out / 'message-for-walid.md'
        message.write_bytes('مسودة الرسالة\n'.encode('utf-8'))
        self.runner.write_bytes(STAND_IN_RUNNER + b'# changed\n')
        code, stdout, stderr = self.run_tool('--replace')
        self.assertEqual(code, 0, stderr)
        self.assertEqual((self.out / 'run_w1.py').read_bytes(), STAND_IN_RUNNER + b'# changed\n')
        self.assertEqual(message.read_bytes(), 'مسودة الرسالة\n'.encode('utf-8'))
        self.assertIn('not part of the package: message-for-walid.md', stdout)
        sums = (self.out / 'SHA256SUMS').read_text(encoding='ascii')
        self.assertIn(hashlib.sha256(STAND_IN_RUNNER + b'# changed\n').hexdigest() + '  run_w1.py', sums)

    def test_a_folder_holding_only_other_files_is_used_without_replace(self):
        self.out.mkdir()
        (self.out / 'message-for-walid.md').write_text('draft', encoding='utf-8')
        code, _, stderr = self.run_tool()
        self.assertEqual(code, 0, stderr)
        self.assertEqual((self.out / 'message-for-walid.md').read_text(encoding='utf-8'), 'draft')

    def test_an_item_without_a_query_is_refused(self):
        bad = self.root / 'bad.jsonl'
        bad.write_text('{"set": "x"}\n{"id": "a-01", "question": "س", "query": ""}\n', encoding='utf-8')
        code, _, stderr = self.run_tool('--allow-other-set', eval_path=bad)
        self.assertEqual(code, 2)
        self.assertIn('line 2: query must be non-empty strings', stderr)
        self.assertFalse(self.out.exists())

    def test_a_duplicate_id_is_refused(self):
        bad = self.root / 'dup.jsonl'
        row = '{"id": "a-01", "question": "س", "query": "ع"}'
        bad.write_text('{"set": "x"}\n' + row + '\n' + row + '\n', encoding='utf-8')
        code, _, stderr = self.run_tool('--allow-other-set', eval_path=bad)
        self.assertEqual(code, 2)
        self.assertIn('duplicate id a-01', stderr)

    def test_an_out_whose_parent_is_missing_is_refused(self):
        code, _, stderr = self.run_tool(out=self.root / 'missing' / 'package')
        self.assertEqual(code, 2)
        self.assertIn('does not exist', stderr)

    def test_terminal_output_is_ascii_for_an_arabic_folder(self):
        out = self.root / 'حزمة'
        code, stdout, stderr = self.run_tool(out=out)
        self.assertEqual(code, 0, stderr)
        self.assertTrue(stdout.isascii(), stdout)
        code, _, stderr = self.run_tool(out=out)
        self.assertEqual(code, 2)
        self.assertTrue(stderr.isascii(), stderr)


if __name__ == '__main__':
    unittest.main()
