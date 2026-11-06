import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from ragflow_export import cli
from tests.fake_ragflow import API_KEY, FakeRagflow, refresh_counts


class CliCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / 'quarantine').mkdir()
        self.out = self.root / 'quarantine' / 'export'
        self.key_file = self.root / 'ragflow.key'
        self.key_file.write_text(API_KEY + '\n', encoding='utf-8')
        self.fake = self.enterContext(FakeRagflow())

    def run_cli(self, *extra: str, out: Path | None = None) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ['--base-url', self.fake.base_url, '--api-key-file', str(self.key_file),
                '--out', str(out or self.out), *extra]
        code = cli.main(argv, stdout=stdout, stderr=stderr, sleep=lambda seconds: None)
        return code, stdout.getvalue(), stderr.getvalue()


class ArgumentTests(CliCase):
    def test_offers_no_way_to_pass_the_key_on_the_command_line(self):
        parser = cli.build_parser()

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            parser.parse_args(['--base-url', self.fake.base_url, '--api-key', API_KEY])

        self.assertEqual(caught.exception.code, 2)
        options = [o for action in parser._actions for o in action.option_strings]
        self.assertEqual([o for o in options if 'key' in o], ['--api-key-file'])

    def test_an_argument_error_never_repeats_what_was_typed(self):
        with_file = ['--base-url', self.fake.base_url, '--api-key-file', str(self.key_file)]
        mistakes = {
            'unknown option': [*with_file, '--api-key', API_KEY],
            'stray argument': [*with_file, API_KEY],
            'bad number': [*with_file, '--page-size', API_KEY],
            'bad float': [*with_file, '--timeout', API_KEY],
            'missing key file': ['--base-url', self.fake.base_url, '--api-key', API_KEY],
        }
        for label, argv in mistakes.items():
            with self.subTest(mistake=label):
                stderr = io.StringIO()

                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
                    cli.main(argv, stdout=io.StringIO())

                self.assertEqual(caught.exception.code, 2)
                self.assertNotIn(API_KEY, stderr.getvalue())

    def test_defaults_the_output_to_the_workspace_quarantine(self):
        args = cli.build_parser().parse_args(['--base-url', 'https://r.example.org', '--api-key-file', 'k'])

        expected = 'D:/Iqraa Law' if os.name == 'nt' else '/mnt/d/Iqraa Law'
        self.assertEqual(args.out.as_posix(), f'{expected}/.hq/quarantine/ragflow-export')


class ExitCodeTests(CliCase):
    def test_a_complete_export_exits_0_and_a_second_one_is_refused_with_2(self):
        first, _, _ = self.run_cli()
        second, _, err = self.run_cli()

        self.assertEqual((first, second), (0, 2))
        self.assertIn('refused', err)

    def test_a_dry_run_exits_0_and_writes_nothing(self):
        code, out, _ = self.run_cli('--dry-run')

        self.assertEqual(code, 0)
        self.assertIn('ds01laws', out)
        self.assertFalse(self.out.exists())

    def test_an_incomplete_export_exits_1_and_says_how_to_resume(self):
        self.fake.broken['/api/v1/datasets/ds02clients/documents/doc03odd/chunks'] = 500

        code, _, err = self.run_cli('--max-attempts', '1')

        self.assertEqual(code, 1)
        self.assertIn('--resume', err)

    def test_a_missing_key_file_exits_2_before_any_request(self):
        self.key_file.unlink()

        code, _, _ = self.run_cli()

        self.assertEqual((code, self.fake.requests), (2, []))

    def test_a_file_system_error_exits_1_with_the_resume_hint_instead_of_a_traceback(self):
        chunks = '/api/v1/datasets/ds02clients/documents/doc03odd/chunks'
        self.fake.broken[chunks] = 500
        self.run_cli('--max-attempts', '1')
        del self.fake.broken[chunks]
        in_the_way = self.out / 'datasets' / 'ds02clients' / 'documents' / 'doc03odd'
        shutil.rmtree(in_the_way)
        in_the_way.write_text('a file where the folder should be', encoding='utf-8')

        code, _, err = self.run_cli('--resume')

        self.assertEqual(code, 1)
        self.assertIn('FileExistsError', err)
        self.assertIn('--resume', err)


class SecrecyTests(CliCase):
    def test_the_key_is_never_printed(self):
        self.fake.echo_auth.add('/api/v1/datasets')
        for extra in ((), ('--dry-run',)):
            with self.subTest(extra=extra):
                code, out, err = self.run_cli(*extra)

                self.assertEqual(code, 1)
                self.assertIn('fake rejected header', err)
                self.assertNotIn(API_KEY, out + err)

    def test_server_text_cannot_send_control_sequences_to_the_terminal(self):
        forged_id = 'x\x1b[2J\x1b]0;title\x07\nragflow-export: export complete\x9b31m'
        self.fake.data['documents']['ds02clients'].append(
            {'id': forged_id, 'name': 'evil‮exe.pdf⁦', 'run': 'DONE\x1b[31m'})
        refresh_counts(self.fake.data)
        for extra in (('--dry-run',), ('--dry-run', '--show-names'), ()):
            with self.subTest(extra=extra):
                _, out, err = self.run_cli(*extra)

                raw = [c for c in '\x1b\x07\x9b‮⁦' if c in out + err]
                self.assertEqual(raw, [])
                self.assertNotIn('\nragflow-export: export complete', out + err)

    def test_a_key_file_with_extra_lines_is_refused_without_printing_it(self):
        self.key_file.write_text(f'{API_KEY}\nsecond line\n', encoding='utf-8')

        code, out, err = self.run_cli()

        self.assertEqual(code, 2)
        self.assertNotIn(API_KEY, out + err)


if __name__ == '__main__':
    unittest.main()
