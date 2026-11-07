"""The plan generators: mkplan.py renders a chunk's directives, assemble.py joins the rendered chunks into the plan,
pin_pristine.py pins the old files the edits start from. From tools/plan, stdlib only:
    python -B -m unittest test_plan_tools -v
Every file lives in a temporary build folder, and pin_pristine gets a fake `git show`, so no repository is read."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import assemble
import mkplan
import pin_pristine

NL = '\n'
T3 = '```'


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))
    return path


class BuildFolder(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.build = Path(tmp.name) / 'build'
        self.pristine = self.build / 'tmp' / 'pristine'
        self.build.mkdir()

    def pair(self, rel: str, old: str, new: str):
        write(self.pristine / rel, old)
        write(self.build / rel, new)

    def render(self, text: str) -> str:
        return mkplan.render(text, self.build, self.pristine)


class EditsTest(BuildFolder):
    def test_a_changed_file_renders_replace_with_blocks(self):
        self.pair('fork/app.py', 'one\ntwo\nthree\nfour\nfive\n', 'one\ntwo\nTHREE\nfour\nfive\n')
        self.assertEqual(
            self.render('@@EDITS fork/app.py'),
            'Replace:\n\n```python\none\ntwo\nthree\nfour\nfive\n```\n\n'
            'with:\n\n```python\none\ntwo\nTHREE\nfour\nfive\n```\n',
        )

    def test_the_context_grows_until_the_old_block_is_found_exactly_once(self):
        stanza = [f's{i}' for i in range(1, 8)]
        old = ['top', *stanza, 'SEPARATOR', *stanza, 'bottom', '']
        new = list(old)
        new[12] = 'S4'  # s4 of the second stanza
        old_text = NL.join(old)
        self.assertEqual(old_text.count(NL.join(stanza)), 2)  # three lines either side are not enough
        self.pair('fork/app.py', old_text, NL.join(new))
        old_block = NL.join(['SEPARATOR', *stanza, 'bottom'])
        self.assertEqual(old_text.count(old_block), 1)
        self.assertEqual(
            self.render('@@EDITS fork/app.py'),
            f'Replace:\n\n```python\n{old_block}\n```\n\n'
            f'with:\n\n```python\n{old_block.replace("s4", "S4")}\n```\n',
        )

    def test_identical_files_render_no_change(self):
        self.pair('harness/run.sh', 'echo hi\n', 'echo hi\n')
        self.assertEqual(self.render('@@EDITS harness/run.sh'), '(no change)\n')


class FileTest(BuildFolder):
    def test_a_file_holding_three_backticks_is_fenced_with_four(self):
        write(self.build / 'fork/README.md', f'Run:\n{T3}sh\nnpm test\n{T3}\n')
        self.assertEqual(self.render('@@FILE fork/README.md'), f'````markdown\nRun:\n{T3}sh\nnpm test\n{T3}\n````')

    def test_any_other_file_is_fenced_with_three_in_its_language_or_the_one_named(self):
        write(self.build / 'fork/a.py', 'x = 1\n')
        self.assertEqual(self.render('@@FILE fork/a.py'), f'{T3}python\nx = 1\n{T3}')
        self.assertEqual(self.render('@@FILE fork/a.py text'), f'{T3}text\nx = 1\n{T3}')


class MkplanMainTest(BuildFolder):
    def run_main(self, *argv: str) -> str:
        with contextlib.redirect_stdout(io.StringIO()):
            mkplan.main(['--build', str(self.build), *argv])
        return (self.build / 'chunks' / 'out' / 'chunk-0.md').read_text(encoding='utf-8')

    def test_the_pristine_defaults_to_build_tmp_pristine_and_pristine_overrides_it(self):
        write(self.build / 'chunks' / 'chunk-0.md', 'intro\n@@EDITS fork/app.py\n')
        self.pair('fork/app.py', 'old\n', 'new\n')
        self.assertIn('Replace:\n\n```python\nold\n```', self.run_main('chunk-0.md'))
        other = self.build.parent / 'elsewhere'
        write(other / 'fork/app.py', 'new\n')
        self.assertEqual(self.run_main('--pristine', str(other), 'chunk-0.md'), 'intro\n(no change)\n\n')


class AssembleTest(BuildFolder):
    def assemble(self, *chunks: str):
        plan = self.build.parent / 'plan.prompt.md'
        argv = ['--build', str(self.build), '--plan', str(plan)]
        for name in chunks:
            argv += ['--chunk', name]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = assemble.main(argv)
        return code, plan, out.getvalue()

    def test_assemble_joins_the_chunks_in_order_and_reports_leftover_directives(self):
        write(self.build / 'fork/x.py', 'x = 1\n')
        write(self.build / 'chunks' / 'chunk-a.md', '# Part A\n@@FILE fork/x.py\n')
        write(self.build / 'chunks' / 'chunk-b.md', '# Part B\n@@EDITS fork/x.py one two\n@@SHOUT hello\n')
        code, plan, out = self.assemble('chunk-b.md', 'chunk-a.md')  # no mkplan.py in the build folder
        self.assertEqual(code, 0, out)
        text = plan.read_bytes().decode('utf-8')
        self.assertEqual(text, '# Part B\n@@EDITS fork/x.py one two\n@@SHOUT hello\n\n# Part A\n```python\nx = 1\n```\n')
        self.assertEqual(assemble.leftovers(text), ['@@EDITS fork/x.py one two', '@@SHOUT hello'])
        self.assertIn('leftover directives 2', out)
        self.assertIn('@@SHOUT hello', out)

    def test_a_clean_plan_reports_no_leftover_directive(self):
        write(self.build / 'chunks' / 'chunk-a.md', '# Part A\n')
        code, _, out = self.assemble('chunk-a.md')
        self.assertEqual(code, 0, out)
        self.assertIn('leftover directives 0', out)

    def test_a_failing_mkplan_writes_no_plan(self):
        write(self.build / 'chunks' / 'chunk-a.md', '# Part A\n')
        code, plan, out = self.assemble('chunk-a.md', 'chunk-missing.md')
        self.assertNotEqual(code, 0)
        self.assertIn('chunk-missing.md', out)
        self.assertFalse(plan.exists())


class FakeGit:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        repo, ref = cmd[2], cmd[4]
        return SimpleNamespace(stdout=f'{Path(repo).name} {ref}\r\n'.encode('utf-8') + b'\xff')


class PinPristineTest(BuildFolder):
    FORK = Path('/repos/AI Platform')
    HARNESS = Path('/repos/AI Harness')
    REPOS = ['--repo', f'fork={FORK}@aaa111', '--repo', f'harness={HARNESS}@bbb222']

    def pin(self, *argv: str, git=None):
        with contextlib.redirect_stdout(io.StringIO()):
            pin_pristine.main(['--build', str(self.build), *argv], run=git or FakeGit())

    def test_the_edited_paths_are_pinned_with_the_bytes_git_show_returns(self):
        write(self.build / 'chunks' / 'chunk-0.md', '\n'.join([
            '@@EDITS fork/api/hooks.py',
            '@@FILE fork/api/whole.py',
            '@@EDITSFROM fork/api/index.ts stages/index-t1.ts',
        ]))
        write(self.build / 'chunks' / 'chunk-1.md', '\n'.join([
            '@@STAGEEDITS stages/run-g1.sh harness/deploy/run.sh',
            '@@DIFFSTAGES stages/a.py stages/b.py',
            '@@LOG red 3',
        ]))
        write(self.build / 'chunks' / 'notes.md', '@@EDITS fork/not-a-chunk.py\n')
        git = FakeGit()
        self.pin(*self.REPOS, git=git)
        self.assertEqual(
            [cmd for cmd, _ in git.calls],
            [
                ['git', '-C', str(self.FORK), 'show', 'aaa111:api/hooks.py'],
                ['git', '-C', str(self.FORK), 'show', 'aaa111:api/index.ts'],
                ['git', '-C', str(self.HARNESS), 'show', 'bbb222:deploy/run.sh'],
            ],
        )
        for _, kwargs in git.calls:
            self.assertEqual(kwargs, {'capture_output': True, 'check': True})
        written = sorted(p.relative_to(self.pristine).as_posix() for p in self.pristine.rglob('*') if p.is_file())
        self.assertEqual(written, ['fork/api/hooks.py', 'fork/api/index.ts', 'harness/deploy/run.sh'])
        self.assertEqual((self.pristine / 'fork/api/hooks.py').read_bytes(), b'AI Platform aaa111:api/hooks.py\r\n\xff')
        self.assertEqual((self.pristine / 'harness/deploy/run.sh').read_bytes(), b'AI Harness bbb222:deploy/run.sh\r\n\xff')

    def test_a_root_without_a_repo_stops_before_any_git_call(self):
        write(self.build / 'chunks' / 'chunk-0.md', '@@EDITS fork/a.py\n@@EDITS harness/b.py\n')
        git = FakeGit()
        with self.assertRaises(SystemExit) as stop:
            self.pin('--repo', f'fork={self.FORK}@aaa111', git=git)
        self.assertIn('harness', str(stop.exception.code))
        self.assertEqual(git.calls, [])
        self.assertFalse(self.pristine.exists())

    def test_a_repo_is_root_equals_path_at_sha(self):
        self.assertEqual(pin_pristine.repo_spec('fork=/srv/a@b/AI Platform@232b3b595'),
                         ('fork', (Path('/srv/a@b/AI Platform'), '232b3b595')))
        for bad in ('fork=/srv/repo', 'fork/srv/repo@abc', 'web=/srv/repo@abc', 'fork=@abc', 'fork=/srv/repo@'):
            with self.subTest(bad), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.pin('--repo', bad)


if __name__ == '__main__':
    unittest.main()
