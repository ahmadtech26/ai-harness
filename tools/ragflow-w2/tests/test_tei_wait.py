"""Tests for patch_tei_wait.py and check_tei_wait.py on invented fixtures (and, when present, the v0.27.3 source).

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = TOOL_DIR.parents[2]
REAL_SOURCE = WORKSPACE / '.hq' / 'scratch' / 'ragflow-src-v0.27.3' / 'x' / 'rag' / 'llm' / 'embedding_model.py'
REAL_SHA256 = 'c2e46e1cb5d128122a48b8283d135b81321441655dbd9c22c9ecd8035a6c0536'  # the image's file, read in the image


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOL_DIR / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


patch_tei_wait = load('patch_tei_wait')
check_tei_wait = load('check_tei_wait')

ENCODE, QUERIES = (anchor for _, anchor in patch_tei_wait.ANCHORS)
DECOY = '        response = requests.post(self.base_url, headers=self.headers, json=payload, timeout=30)'


def source(encode_body=ENCODE, queries_body=QUERIES, other_body=DECOY, extra_in_encode='',
           queries_first=False) -> str:
    """A small embedding_model.py shaped like v0.27.3's: a class before and after, each with a timeout=30 line.
    queries_first defines encode_queries before encode (v0.27.3 has encode first)."""
    encode = ('    def encode(self, texts: list):\n'
              f'{extra_in_encode}'
              f'{encode_body}\n'
              '        _raise_model_exception_if_failed(response)\n'
              '        return np.array(response.json()), sum([num_tokens_from_string(text) for text in texts])\n')
    queries = ('    def encode_queries(self, text: str):\n'
               f'{queries_body}\n'
               '        _raise_model_exception_if_failed(response)\n'
               '        return np.array(response.json()[0]), num_tokens_from_string(text)\n')
    first, second = (queries, encode) if queries_first else (encode, queries)
    return (
        '"""fixture"""\n\n\n'
        'class Base:\n    pass\n\n\n'
        'class OtherEmbed(Base):\n'
        '    def encode(self, texts: list):\n'
        f'{other_body}\n'
        '        return response\n\n\n'
        'class HuggingFaceEmbed(Base):\n'
        '    _FACTORY_NAME = "HuggingFace"\n\n'
        '    def __init__(self, key, model_name, base_url=None, **kwargs):\n'
        '        self.base_url = base_url or "http://127.0.0.1:8080"\n\n'
        f'{first}\n'
        f'{second}\n\n'
        '# a comment at column 0 after the class\n'
        'class VolcEngineEmbed(Base):\n'
        '    def encode(self, texts):\n'
        '        return requests.post(self.base_url, timeout=30)\n'
    )


class PatchBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / 'src' / 'embedding_model.py'
        self.src.parent.mkdir()
        self.out = self.dir / 'patch'

    def tearDown(self):
        self.tmp.cleanup()

    def run_patch(self, text: str | bytes | None = None, *extra: str) -> tuple[int, str]:
        if text is not None:
            self.src.write_bytes(text.encode('utf-8') if isinstance(text, str) else text)
        out = io.StringIO()
        code = patch_tei_wait.main(['--source', str(self.src), '--out', str(self.out), *extra], stdout=out)
        return code, out.getvalue()

    def refused(self, code: int, printed: str, words: str) -> None:
        self.assertEqual(code, 2, printed)
        self.assertIn(words, printed)
        self.assertFalse(self.out.exists() and any(self.out.iterdir()), 'a refusal wrote something')


class PatchWrites(PatchBase):
    def test_only_the_two_anchor_lines_change_and_only_their_number(self):
        text = source()
        code, printed = self.run_patch(text)

        self.assertEqual(code, 0, printed)
        before, after = text.split('\n'), (self.out / 'embedding_model.py').read_text(encoding='utf-8').split('\n')
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual(len(before), len(after))
        self.assertEqual([before[i] for i in changed], [ENCODE, QUERIES])
        self.assertEqual([after[i] for i in changed], [ENCODE[:-3] + '900)', QUERIES[:-3] + '900)'])
        self.assertEqual(sum('timeout=30' in line for line in after), 2)  # the two decoys stay

        record = json.loads((self.out / 'patch.json').read_text(encoding='utf-8'))
        self.assertEqual(set(record), {'file', 'image_sha256', 'patched_sha256', 'changed_lines', 'wait_s', 'anchors'})
        self.assertEqual((record['file'], record['changed_lines'], record['wait_s']),
                         ('rag/llm/embedding_model.py', [i + 1 for i in changed], 900))
        self.assertEqual(record['image_sha256'], hashlib.sha256(text.encode('utf-8')).hexdigest())
        self.assertEqual(record['patched_sha256'], hashlib.sha256((self.out / 'embedding_model.py').read_bytes()).hexdigest())
        self.assertEqual([(a['method'], a['line'], a['before']) for a in record['anchors']],
                         [('encode', changed[0] + 1, ENCODE), ('encode_queries', changed[1] + 1, QUERIES)])

        diff = (self.out / 'embedding_model.diff').read_text(encoding='utf-8').split('\n')
        self.assertEqual(diff[:2], ['--- a/rag/llm/embedding_model.py', '+++ b/rag/llm/embedding_model.py'])
        self.assertEqual([d for d in diff[2:] if d[:1] in '+-' and d], ['-' + ENCODE, '+' + after[changed[0]],
                                                                       '-' + QUERIES, '+' + after[changed[1]]])

    def test_changed_lines_are_ascending_when_encode_queries_comes_first(self):
        # rf_ingest.py refuses a record whose changed_lines are not in order; the anchors keep their method order.
        code, printed = self.run_patch(source(queries_first=True))

        self.assertEqual(code, 0, printed)
        record = json.loads((self.out / 'patch.json').read_text(encoding='utf-8'))
        at = {anchor['method']: anchor['line'] for anchor in record['anchors']}
        self.assertGreater(at['encode'], at['encode_queries'])  # the fixture really has encode_queries first
        self.assertEqual(record['changed_lines'], [at['encode_queries'], at['encode']])

    def test_another_wait_is_written_where_asked(self):
        code, printed = self.run_patch(source(), '--wait', '120')

        self.assertEqual(code, 0, printed)
        self.assertEqual(json.loads((self.out / 'patch.json').read_text(encoding='utf-8'))['wait_s'], 120)
        self.assertIn(ENCODE[:-3] + '120)', (self.out / 'embedding_model.py').read_text(encoding='utf-8'))

    @unittest.skipUnless(REAL_SOURCE.is_file(), 'the v0.27.3 source tree copy is not here')
    def test_the_real_v0_27_3_file_changes_on_lines_1247_and_1253_only(self):
        self.src.write_bytes(REAL_SOURCE.read_bytes())
        code, printed = self.run_patch(None, '--expect-sha256', REAL_SHA256)

        self.assertEqual(code, 0, printed)
        record = json.loads((self.out / 'patch.json').read_text(encoding='utf-8'))
        self.assertEqual((record['changed_lines'], record['image_sha256']), ([1247, 1253], REAL_SHA256))
        # The pins check_tei_wait.py holds are this file's: the image's sha256, the patched one, the wait.
        self.assertEqual({k: record[k] for k in check_tei_wait.APPROVED}, check_tei_wait.APPROVED)
        before = REAL_SOURCE.read_bytes().split(b'\n')
        after = (self.out / 'embedding_model.py').read_bytes().split(b'\n')
        self.assertEqual([i + 1 for i, (a, b) in enumerate(zip(before, after)) if a != b], [1247, 1253])
        self.assertEqual(sum(b'timeout=30' in line for line in after), 6)

    def test_replace_overwrites_this_tool_s_own_files(self):
        self.assertEqual(self.run_patch(source())[0], 0)
        code, printed = self.run_patch(source(), '--wait', '600', '--replace')

        self.assertEqual(code, 0, printed)
        self.assertEqual(json.loads((self.out / 'patch.json').read_text(encoding='utf-8'))['wait_s'], 600)


class PatchRefuses(PatchBase):
    def test_an_anchor_that_is_not_found_is_refused(self):
        self.refused(*self.run_patch(source(encode_body=ENCODE.replace('timeout=30', 'timeout=60'))), 'found 0 time(s)')

    def test_an_anchor_found_twice_is_refused(self):
        self.refused(*self.run_patch(source(other_body=QUERIES)), 'found 2 time(s)')

    def test_an_anchor_outside_the_class_is_refused(self):
        text = source(other_body=ENCODE, encode_body='        response = None')
        self.refused(*self.run_patch(text), 'outside class HuggingFaceEmbed')

    def test_an_anchor_under_the_other_method_is_refused(self):
        self.refused(*self.run_patch(source(encode_body=QUERIES, queries_body=ENCODE)),
                     'sits under HuggingFaceEmbed.encode_queries')

    def test_cr_line_ends_are_refused(self):
        self.refused(*self.run_patch(source().replace('\n', '\r\n').encode('utf-8')), 'CR byte')

    def test_a_file_that_is_not_utf8_is_refused(self):
        self.refused(*self.run_patch(source().encode('utf-8') + b'# \xff\n'), 'not UTF-8')

    def test_a_source_with_another_sha256_than_expected_is_refused(self):
        self.refused(*self.run_patch(source(), '--expect-sha256', 'a' * 64), 'not the expected')

    def test_a_wait_that_is_not_above_30_is_refused(self):
        for wait in ('30', '5'):
            with self.subTest(wait):
                self.refused(*self.run_patch(source(), '--wait', wait), 'above 30')

    def test_a_method_that_would_still_hold_30_is_refused(self):
        # The two lines change as asked, but encode holds another 30: the compiled check catches it.
        self.refused(*self.run_patch(source(extra_in_encode='        retries = 30\n')), 'not 900 without 30')

    def test_a_non_empty_out_without_replace_and_foreign_entries_with_it_are_refused(self):
        self.out.mkdir()
        (self.out / 'notes.txt').write_text('x', encoding='utf-8')
        code, printed = self.run_patch(source())
        self.assertEqual((code, 'not empty' in printed), (2, True), printed)
        code, printed = self.run_patch(source(), '--replace')
        self.assertEqual((code, 'does not write' in printed), (2, True), printed)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ['notes.txt'])

    def test_a_source_inside_out_is_refused_even_with_replace(self):
        self.out = self.src.parent
        code, printed = self.run_patch(source(), '--replace')

        self.assertEqual((code, 'sits in --out' in printed), (2, True), printed)
        self.assertEqual(self.src.read_text(encoding='utf-8'), source())

    def test_the_second_pass_refuses_any_other_difference(self):
        text = source()
        lines = text.split('\n')
        at = [lines.index(ENCODE), lines.index(QUERIES)]
        good = list(lines)
        for i in at:
            good[i] = good[i][:-3] + '900)'
        patch_tei_wait.verify(text, '\n'.join(good), 900, at)  # the right result passes
        another_line = list(good)
        another_line[at[0] - 1] += ' '
        beyond_the_number = list(good)
        beyond_the_number[at[1]] = beyond_the_number[at[1]].replace('json=', 'data=')
        other_number = [line.replace('timeout=900', 'timeout=901') for line in good]
        for name, tampered in (('another line', another_line), ('more than the number', beyond_the_number),
                               ('another number', other_number), ('a line fewer', good[:-1])):
            with self.subTest(name), self.assertRaises(patch_tei_wait.Refused):
                patch_tei_wait.verify(text, '\n'.join(tampered), 900, at)


def fake_class(wait_encode: object = 900, wait_queries: object = 900, drop: str | None = None) -> type:
    body = {'encode': f'        return post(texts, timeout={wait_encode!r})\n',
            'encode_queries': f'        return post(text, timeout={wait_queries!r})[0]\n'}
    text = 'class HuggingFaceEmbed:\n    pass\n' + ''.join(
        f'    def {name}(self, {"texts" if name == "encode" else "text"}):\n{line}'
        for name, line in body.items() if name != drop)
    namespace: dict = {}
    exec(compile(text, 'fixture.py', 'exec'), namespace)  # defines the class; nothing is called
    return namespace['HuggingFaceEmbed']


class CodeConstants(unittest.TestCase):
    def test_both_methods_holding_the_wait_and_no_30_pass(self):
        self.assertEqual(check_tei_wait.method_problems(fake_class(), 900), [])

    def test_the_shipped_30_is_named_for_each_method(self):
        problems = check_tei_wait.method_problems(fake_class(30, 30), 900)

        self.assertEqual(len(problems), 4, problems)
        self.assertTrue(any('encode_queries still holds 30' in p for p in problems))

    def test_one_method_left_at_30_is_caught_alone(self):
        problems = check_tei_wait.method_problems(fake_class(900, 30), 900)

        self.assertTrue(problems and all('.encode_queries ' in p for p in problems), problems)

    def test_a_float_30_counts_as_30_and_a_missing_method_is_named(self):
        self.assertTrue(check_tei_wait.method_problems(fake_class(900, 30.0), 900))
        self.assertEqual(check_tei_wait.method_problems(fake_class(drop='encode'), 900),
                         ['HuggingFaceEmbed.encode is missing'])


class ServerCheck(unittest.TestCase):
    """check_tei_wait.py's main in a child Python, on a fake /ragflow and a fake /proc."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.root, self.proc, self.patch = self.dir / 'ragflow', self.dir / 'proc', self.dir / 'patch'
        (self.root / 'rag' / 'llm').mkdir(parents=True)
        (self.root / 'rag' / '__init__.py').write_text('', encoding='utf-8')
        (self.root / 'rag' / 'llm' / '__init__.py').write_text('', encoding='utf-8')
        self.original = self.dir / 'original.py'
        self.original.write_bytes(source().encode('utf-8'))  # write_text would add CRs on Windows
        out = io.StringIO()
        assert patch_tei_wait.main(['--source', str(self.original), '--out', str(self.patch)], stdout=out) == 0
        self.record = json.loads((self.patch / 'patch.json').read_text(encoding='utf-8'))
        self.module = self.root / 'rag' / 'llm' / 'embedding_model.py'
        self.module.write_bytes((self.patch / 'embedding_model.py').read_bytes())  # the mount, as a copy
        self.add_process(101, ['python3', 'rag/svr/task_executor.py', '-i', 'h_0', '-t', 'common'],
                         {'MAX_CONCURRENT_TASKS': '1', 'EMBEDDING_BATCH_SIZE': '1', 'PATH': '/usr/bin'})
        self.add_process(102, ['python3', 'api/ragflow_server.py', '--init-superuser'],
                         {'MAX_CONCURRENT_TASKS': '1', 'EMBEDDING_BATCH_SIZE': '1'})
        self.add_process(103, ['nginx', '-g', 'daemon off;'], {})
        (self.proc / 'self').mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def add_process(self, pid: int, argv: list[str], environ: dict) -> None:
        entry = self.proc / str(pid)
        entry.mkdir(parents=True, exist_ok=True)
        (entry / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in argv) + b'\0')
        (entry / 'environ').write_bytes(b''.join(f'{k}={v}\0'.encode() for k, v in environ.items()))

    def run_check(self, pins: bool = True, **env_changes) -> tuple[int, str]:
        """pins: pass the fixture's own sha256 as the expected ones (the defaults are the real file's)."""
        env = {k: v for k, v in os.environ.items()
               if k not in ('ENABLE_TIMEOUT_ASSERTION', 'MAX_CONCURRENT_TASKS', 'EMBEDDING_BATCH_SIZE', 'PYTHONPATH')}
        env.update({'MAX_CONCURRENT_TASKS': '1', 'EMBEDDING_BATCH_SIZE': '1', 'PYTHONIOENCODING': 'utf-8'})
        env.update(env_changes)
        expect = ['--expect-image-sha256', self.record['image_sha256'],
                  '--expect-patched-sha256', self.record['patched_sha256']] if pins else []
        done = subprocess.run([sys.executable, '-B', str(TOOL_DIR / 'check_tei_wait.py'),
                               '--patch', str(self.patch / 'patch.json'), '--root', str(self.root),
                               '--proc', str(self.proc), '--max-concurrent-tasks', '1', '--embedding-batch-size', '1',
                               *expect],
                              env=env, capture_output=True, text=True, encoding='utf-8', timeout=120)
        return done.returncode, done.stdout

    def write_record(self, **changes) -> None:
        (self.patch / 'patch.json').write_text(json.dumps({**self.record, **changes}), encoding='utf-8')

    def test_the_patched_module_and_the_settings_pass(self):
        code, printed = self.run_check()

        self.assertEqual(code, 0, printed)
        self.assertIn('TEI WAIT LOADED: HuggingFaceEmbed.encode and encode_queries wait 900 s', printed)
        self.assertIn('1 task executor(s) and 1 API server(s) running', printed)

    def test_a_stale_pyc_the_import_system_would_use_instead_of_the_file_is_caught(self):
        # An unchecked-hash .pyc of the shipped file is used without reading the source: the mount would be ignored.
        cached = Path(importlib.util.cache_from_source(str(self.module)))
        py_compile.compile(str(self.original), cfile=str(cached), dfile=str(self.module),
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH, doraise=True)
        code, printed = self.run_check()

        self.assertEqual(code, 1, printed)
        self.assertIn('a .pyc exists at', printed)
        self.assertIn('is not the code compiled from the file now', printed)
        self.assertIn('still holds 30', printed)

    def test_the_import_resolving_to_another_file_with_the_patched_bytes_is_caught(self):
        # rag.llm's own __path__ sends the import elsewhere; that file holds the patched bytes, so its sha256 and
        # constants pass: only the module-origin check can tell it is not the mounted file.
        elsewhere = self.dir / 'elsewhere'
        elsewhere.mkdir()
        (elsewhere / 'embedding_model.py').write_bytes(self.module.read_bytes())
        (self.root / 'rag' / 'llm' / '__init__.py').write_text(f'__path__ = [{str(elsewhere)!r}]\n', encoding='utf-8')

        code, printed = self.run_check()

        self.assertEqual(code, 1, printed)
        self.assertIn('BAD  the import system resolves rag.llm.embedding_model to', printed)
        self.assertIn('TEI WAIT NOT SHOWN: 1 check(s) failed', printed)

    def test_the_shipped_file_in_place_of_the_patched_one_is_caught(self):
        self.module.write_bytes(self.original.read_bytes())
        code, printed = self.run_check()

        self.assertEqual(code, 1, printed)
        self.assertIn('not patch.json\'s', printed)
        self.assertIn('HuggingFaceEmbed.encode does not hold 900', printed)

    def test_the_timeout_assertion_switch_is_caught_in_the_container_and_in_a_process(self):
        code, printed = self.run_check(ENABLE_TIMEOUT_ASSERTION='0')
        self.assertEqual(code, 1, printed)
        self.assertIn('this container: ENABLE_TIMEOUT_ASSERTION is set', printed)

        self.add_process(104, ['python3', '/ragflow/rag/svr/task_executor.py'],
                         {'MAX_CONCURRENT_TASKS': '1', 'EMBEDDING_BATCH_SIZE': '1', 'ENABLE_TIMEOUT_ASSERTION': '1'})
        code, printed = self.run_check()
        self.assertEqual(code, 1, printed)
        self.assertIn('task executor pid 104: ENABLE_TIMEOUT_ASSERTION is set', printed)

    def test_a_task_executor_left_at_the_default_concurrency_is_caught(self):
        self.add_process(101, ['python3', 'rag/svr/task_executor.py'], {'EMBEDDING_BATCH_SIZE': '1'})
        code, printed = self.run_check()

        self.assertEqual(code, 1, printed)
        self.assertIn("task executor pid 101: MAX_CONCURRENT_TASKS is '5' (the default), not 1", printed)

    def test_another_batch_size_in_the_container_is_caught(self):
        code, printed = self.run_check(EMBEDDING_BATCH_SIZE='16')

        self.assertEqual(code, 1, printed)
        self.assertIn("this container: EMBEDDING_BATCH_SIZE is '16', not 1", printed)

    def test_no_running_task_executor_is_caught(self):
        for pid in (101, 102):
            for name in ('cmdline', 'environ'):
                (self.proc / str(pid) / name).unlink()
            (self.proc / str(pid)).rmdir()
        code, printed = self.run_check()

        self.assertEqual(code, 1, printed)
        self.assertIn('no task executor is running', printed)

    def test_a_patch_record_whose_wait_is_not_a_whole_number_is_bad_input(self):
        for wait in ('900', 30, True):
            with self.subTest(wait=wait):
                self.write_record(wait_s=wait)
                code, printed = self.run_check()
                self.assertEqual(code, 2, printed)
                self.assertIn('wait_s must be a whole number above 30', printed)

    def test_a_patch_record_of_another_file_is_bad_input(self):
        self.write_record(file='rag/llm/chat_model.py')

        code, printed = self.run_check()

        self.assertEqual(code, 2, printed)
        self.assertIn('patch.json: file must be rag/llm/embedding_model.py', printed)

    def test_a_patch_other_than_the_approved_one_is_bad_input(self):
        # By default the record must be the approved patch: the real image file's sha256 and 900 s.
        code, printed = self.run_check(pins=False)
        self.assertEqual(code, 2, printed)
        self.assertIn(f'image_sha256 is {self.record["image_sha256"]}, not the approved '
                      f'{check_tei_wait.APPROVED["image_sha256"]}', printed)

        self.write_record(wait_s=600)
        code, printed = self.run_check()
        self.assertEqual(code, 2, printed)
        self.assertIn('wait_s is 600, not the approved 900', printed)


if __name__ == '__main__':
    unittest.main()
