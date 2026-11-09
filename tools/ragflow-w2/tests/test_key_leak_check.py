"""Tests for key_leak_check.py: it finds a key, or any 16-character piece of it, in files and on stdin, and never
prints it. The keys here are invented at test time. Local only.

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOL_DIR = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('key_leak_check', TOOL_DIR / 'key_leak_check.py')
key_leak_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(key_leak_check)

KEY = 'sk-or-v1-' + secrets.token_hex(32)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.key_file = self.root / 'keys' / 'openrouter.key'
        self.key_file.parent.mkdir()
        self.key_file.write_text(KEY + '\n', encoding='ascii')
        self.saved = self.root / 'hr'
        (self.saved / 'out' / 'elasticsearch').mkdir(parents=True)
        (self.saved / 'logs').mkdir()
        (self.saved / 'logs' / 'ingest.txt').write_text('ok   embedder: hosted\n' * 50, encoding='utf-8')
        (self.saved / 'out' / 'elasticsearch' / 'w2-manifest.json').write_text('{"w2": 1}\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, *argv, stdin: bytes | None = None, chunk_size: int | None = None) -> tuple[int, str]:
        out = io.StringIO()
        extra = {} if chunk_size is None else {'chunk_size': chunk_size}
        code = key_leak_check.main(['--key-file', str(self.key_file), *argv], stdout=out,
                                   stdin=io.BytesIO(stdin) if stdin is not None else None, **extra)
        text = out.getvalue()
        self.assertNotIn(KEY, text)
        for start in range(9, len(KEY) - 15, 16):
            self.assertNotIn(KEY[start:start + 16], text)
        return code, text


class Finds(Base):
    def test_saved_files_without_the_key_pass_and_say_what_was_read(self):
        code, out = self.check('--scan', str(self.saved))

        self.assertEqual(code, 0, out)
        self.assertIn('scanned 2 file(s)', out)
        self.assertTrue(out.rstrip().endswith('NO KEY FOUND'), out)

    def test_the_key_in_a_saved_file_is_found_and_named_by_its_path(self):
        leak = self.saved / 'out' / 'elasticsearch' / 'chunks.jsonl'
        leak.write_text('{"content": "x"}\n{"note": "Bearer ' + KEY + '"}\n', encoding='utf-8')

        code, out = self.check('--scan', str(self.saved))

        self.assertEqual(code, 1, out)
        self.assertIn(f'HIT {leak}: full key 1', out)
        self.assertIn('KEY FOUND in 1 place(s)', out)

    def test_a_key_split_across_two_reads_is_found_once(self):
        leak = self.saved / 'logs' / 'server.log'
        leak.write_bytes(b'a' * 13 + KEY.encode() + b'b' * 20 + KEY.encode())

        code, out = self.check('--scan', str(self.saved), chunk_size=7)

        self.assertEqual(code, 1, out)
        self.assertIn(f'HIT {leak}: full key 2, pieces 8\n', out)  # 4 pieces in each key, none counted twice

    def test_a_cut_key_is_found_by_its_pieces(self):
        leak = self.saved / 'logs' / 'server.log'
        leak.write_text('key=' + KEY[:30] + '…\n', encoding='utf-8')  # «sk-or-v1-» and its first 21 secret characters

        code, out = self.check('--scan', str(self.saved))

        self.assertEqual(code, 1, out)
        self.assertIn(f'HIT {leak}: full key 0, pieces 1', out)

    def test_the_key_on_stdin_is_found_under_its_label(self):
        code, out = self.check('--stdin', 'server-log', stdin=b'2026-11-09 INFO api_key=' + KEY.encode() + b'\n')

        self.assertEqual(code, 1, out)
        self.assertIn('HIT stdin «server-log»: full key 1', out)

    def test_stdin_and_files_are_both_read(self):
        code, out = self.check('--scan', str(self.saved), '--stdin', 'docker-inspect', stdin=b'[{"Env": ["A=1"]}]')

        self.assertEqual(code, 0, out)
        self.assertIn('stdin «docker-inspect» 18 bytes', out)

    def test_the_key_file_itself_is_not_counted_when_it_sits_under_a_scanned_folder(self):
        code, out = self.check('--scan', str(self.root))

        self.assertEqual(code, 0, out)
        self.assertIn('skipped the key file itself', out)

    def test_the_last_16_characters_of_a_secret_whose_length_is_no_multiple_of_16_are_a_piece(self):
        key = 'ragflow-' + secrets.token_hex(20)  # a 40-character secret: pieces at 0 and 16, then its last 16
        self.key_file.write_text(key + '\n', encoding='ascii')
        leak = self.saved / 'logs' / 'server.log'
        leak.write_text('token=…' + key[-16:] + '\n', encoding='utf-8')  # only the tail, which neither piece covers
        out = io.StringIO()

        code = key_leak_check.main(['--key-file', str(self.key_file), '--scan', str(self.saved)], stdout=out)

        self.assertEqual(code, 1, out.getvalue())
        self.assertIn('searched whole and as 3 pieces of 16', out.getvalue())
        self.assertIn(f'HIT {leak}: full key 0, pieces 1', out.getvalue())
        self.assertNotIn(key[-16:], out.getvalue())


class Streams(Base):
    """The stream the runbook pipes in (docker logs, docker inspect) must hold something: an empty one, or one shorter
    than what a separate count of the same stream saw (--min-bytes), is no pass (README.md, H3, H4, H7, H9)."""

    def test_an_empty_stream_is_incomplete_not_a_pass(self):
        code, out = self.check('--stdin', 'server-log', stdin=b'')

        self.assertEqual(code, 2, out)
        self.assertIn('INCOMPLETE: stdin «server-log» read 0 bytes', out)
        self.assertNotIn('NO KEY FOUND', out)

    def test_an_empty_stream_beside_files_that_were_read_is_still_incomplete(self):
        code, out = self.check('--scan', str(self.saved), '--stdin', 'server-log', stdin=b'')

        self.assertEqual(code, 2, out)
        self.assertIn('scanned 2 file(s)', out)
        self.assertIn('INCOMPLETE: stdin «server-log» read 0 bytes', out)

    def test_a_stream_shorter_than_min_bytes_is_incomplete(self):
        stream = b'Error response from daemon: No such container: ragbench-rf-server\n'  # what 2>&1 pipes in

        code, out = self.check('--stdin', 'server-log', '--min-bytes', str(len(stream) + 1), stdin=stream)

        self.assertEqual(code, 2, out)
        self.assertIn(f'INCOMPLETE: stdin «server-log» read {len(stream)} bytes, fewer than --min-bytes '
                      f'{len(stream) + 1}', out)
        self.assertNotIn('NO KEY FOUND', out)

    def test_a_stream_of_exactly_min_bytes_passes(self):
        stream = b'2026-11-09 12:00:00 INFO LLMBundle.encode used_tokens: 512\n' * 10

        code, out = self.check('--stdin', 'server-log', '--min-bytes', str(len(stream)), stdin=stream)

        self.assertEqual(code, 0, out)
        self.assertTrue(out.rstrip().endswith('NO KEY FOUND'), out)

    def test_a_key_found_outranks_a_short_stream(self):
        code, out = self.check('--stdin', 'server-log', '--min-bytes', '1000000', stdin=b'api_key=' + KEY.encode())

        self.assertEqual(code, 1, out)
        self.assertIn('KEY FOUND in 1 place(s)', out)

    def test_min_bytes_needs_a_stream_and_a_count_of_zero_or_more(self):
        for argv in (['--scan', str(self.saved), '--min-bytes', '10'], ['--stdin', 'server-log', '--min-bytes', '-1']):
            with self.subTest(argv=argv):
                code, out = self.check(*argv, stdin=b'2026-11-09 INFO ok\n')

                self.assertEqual(code, 2, out)
                self.assertIn('refused: --min-bytes', out)
                self.assertNotIn('scanned', out)

    def test_a_scan_that_reads_no_file_is_incomplete_even_beside_a_stream(self):
        empty = self.root / 'empty'
        empty.mkdir()

        code, out = self.check('--scan', str(empty), '--stdin', 'server-log', stdin=b'2026-11-09 INFO ok\n' * 20)

        self.assertEqual(code, 2, out)
        self.assertIn('INCOMPLETE: no file was read', out)


class Refuses(Base):
    def test_a_key_file_that_is_missing_empty_or_not_one_key_is_refused_before_scanning(self):
        for name, data in (('missing', None), ('empty', b''), ('two lines', (KEY + '\n' + KEY).encode()),
                           ('short', b'sk-or-v1-0123\n'), ('spaces', (KEY[:20] + ' ' + KEY[20:]).encode())):
            with self.subTest(name):
                if data is None:
                    self.key_file.unlink(missing_ok=True)
                else:
                    self.key_file.write_bytes(data)
                code, out = self.check('--scan', str(self.saved))

                self.assertEqual(code, 2, out)
                self.assertNotIn('scanned', out)

    def test_nothing_to_scan_or_a_folder_that_does_not_exist_is_refused(self):
        for argv in ([], ['--scan', str(self.root / 'nowhere')]):
            with self.subTest(argv=argv):
                code, out = self.check(*argv)

                self.assertEqual(code, 2, out)

    def test_a_file_that_cannot_be_read_makes_the_check_incomplete(self):
        real_open = open

        def failing_open(path, *args, **kwargs):
            if Path(path).name == 'ingest.txt':
                raise PermissionError('denied')
            return real_open(path, *args, **kwargs)

        with mock.patch('builtins.open', failing_open):
            code, out = self.check('--scan', str(self.saved))

        self.assertEqual(code, 2, out)
        self.assertIn('could not read 1 file(s)', out)

    def test_a_key_found_outranks_a_file_that_could_not_be_read(self):
        (self.saved / 'logs' / 'server.log').write_text(KEY, encoding='ascii')
        real_open = open

        def failing_open(path, *args, **kwargs):
            if Path(path).name == 'ingest.txt':
                raise PermissionError('denied')
            return real_open(path, *args, **kwargs)

        with mock.patch('builtins.open', failing_open):
            code, out = self.check('--scan', str(self.saved))

        self.assertEqual(code, 1, out)
        self.assertIn('KEY FOUND in 1 place(s)', out)

    def test_a_folder_with_no_file_to_read_is_not_a_pass(self):
        empty = self.root / 'empty'
        empty.mkdir()

        code, out = self.check('--scan', str(empty))

        self.assertEqual(code, 2, out)
        self.assertIn('INCOMPLETE: no file was read', out)


class Registration(Base):
    def record(self, key: str) -> Path:
        salt = secrets.token_hex(16)
        path = self.saved / 'out' / 'elasticsearch' / 'hosted-embedder.json'
        path.write_text(json.dumps({'key': {'length': len(key), 'salt': salt,
                                            'salted_sha256': hashlib.sha256((salt + key).encode()).hexdigest()}}),
                        encoding='utf-8')
        return path

    def test_the_key_registered_is_confirmed_by_its_salted_hash(self):
        code, out = self.check('--scan', str(self.saved), '--registration', str(self.record(KEY)))

        self.assertEqual(code, 0, out)
        self.assertIn('the key is the one hosted-embedder.json registered', out)

    def test_another_key_than_the_registered_one_is_refused_before_scanning(self):
        code, out = self.check('--scan', str(self.saved), '--registration',
                               str(self.record('sk-or-v1-' + secrets.token_hex(32))))

        self.assertEqual(code, 2, out)
        self.assertIn('not the key hosted-embedder.json registered', out)
        self.assertNotIn('scanned', out)


if __name__ == '__main__':
    unittest.main()
