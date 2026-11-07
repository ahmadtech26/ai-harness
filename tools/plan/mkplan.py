#!/usr/bin/env python3
"""Assembles the plan from chunk templates in <build>/chunks/*.md, each rendered to <build>/chunks/out/<name>.

    mkplan.py --build <folder> [--pristine <folder>] <chunk name>...

The build folder holds the new files under one folder per root (fork/, harness/), and chunks/, stages/ and logs/.
The pristine folder (default <build>/tmp/pristine, where pin_pristine.py writes) holds the old files under the same
roots: the real AI Platform / AI Harness files at the plan's base commits.

Directives (each on its own line):
  @@FILE <path> [lang]            the whole file, from the build copy (fork/ or harness/), as a fenced block
  @@EDITS <path>                  the edits that turn the pristine file (the real AI Platform / AI Harness repo) into the
                                  build file, as replace-this-with-that blocks; the context grows until each old block
                                  is found exactly once in the pristine file
  @@EDITSFROM <path> <old>        the same, from another old file (path relative to the build folder)
  @@STAGEEDITS <new> <path>       the same, to another new file (new relative to the build folder, old = pristine <path>)
  @@DIFFSTAGES <old> <new>        the edits between two files of the build folder
  @@LOG <name> [n]                the first n lines (default all) of logs/<name>.txt, as plain lines
"""
import argparse
import difflib
import re
from pathlib import Path

LANG = {'.ts': 'ts', '.tsx': 'tsx', '.js': 'js', '.mjs': 'js', '.cjs': 'js', '.json': 'json', '.py': 'python', '.yaml': 'yaml', '.md': 'markdown'}
NL = chr(10)


def default_pristine(build: Path) -> Path:
    return build / 'tmp' / 'pristine'


def fence(text: str, lang: str) -> str:
    ticks = '````' if '```' in text else '```'
    return ticks + lang + NL + text.rstrip(NL) + NL + ticks


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8').replace(chr(13) + NL, NL)


def split(spec: str):
    root, _, rel = spec.partition('/')
    return root, rel


def edits(spec: str, build: Path, pristine: Path, old_path=None, new_path=None) -> str:
    root, rel = split(spec)
    new = read(Path(new_path) if new_path else build / root / rel).split(NL)
    old = read(Path(old_path) if old_path else pristine / root / rel).split(NL)
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    changes = [(i1, i2, new[j1:j2]) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != 'equal']
    text = NL.join(old)
    lang = LANG.get(Path(rel).suffix, '')
    out = []
    k = 0
    while k < len(changes):
        group = [changes[k]]
        k += 1
        ctx = 2
        while True:
            a = max(0, group[0][0] - ctx)
            b = min(len(old), group[-1][1] + ctx)
            while k < len(changes) and changes[k][0] <= b:
                group.append(changes[k])
                k += 1
                b = min(len(old), group[-1][1] + ctx)
            old_block = NL.join(old[a:b])
            if text.count(old_block) == 1 or (a == 0 and b == len(old)) or ctx > 60:
                break
            ctx += 1
        pos = a
        parts = []
        for i1, i2, replacement in group:
            parts += old[pos:i1] + replacement
            pos = i2
        parts += old[pos:b]
        new_block = NL.join(parts)
        assert text.count(old_block) == 1, f'{spec}: a replace block is not unique (context {ctx})'
        out.append('Replace:' + NL + NL + fence(old_block, lang) + NL + NL + 'with:' + NL + NL + fence(new_block, lang) + NL)
    return NL.join(out) if out else '(no change)' + NL


def render(text: str, build: Path, pristine: Path) -> str:
    lines = []
    for line in text.split(NL):
        m = re.match(r'^@@(FILE|EDITS|EDITSFROM|STAGEEDITS|DIFFSTAGES|LOG)\s+(\S+)(?:\s+(\S+))?\s*$', line)
        if not m:
            lines.append(line)
            continue
        kind, arg, extra = m.groups()
        if kind == 'FILE':
            root, rel = split(arg)
            lines.append(fence(read(build / root / rel), extra or LANG.get(Path(rel).suffix, '')))
        elif kind == 'EDITS':
            lines.append(edits(arg, build, pristine))
        elif kind == 'EDITSFROM':
            lines.append(edits(arg, build, pristine, build / extra))
        elif kind == 'STAGEEDITS':
            lines.append(edits(extra, build, pristine, None, build / arg))
        elif kind == 'DIFFSTAGES':
            lines.append(edits('x/' + Path(extra).name, build, pristine, build / arg, build / extra))
        else:
            body = read(build / 'logs' / (arg + '.txt')).split(NL)
            n = int(extra) if extra else len(body)
            lines.append(NL.join(l for l in body[:n] if l != ''))
    return NL.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Renders plan chunks from <build>/chunks into <build>/chunks/out.')
    parser.add_argument('--build', required=True, type=Path, help='the plan build folder')
    parser.add_argument('--pristine', type=Path, help='the old files, one folder per root (default <build>/tmp/pristine)')
    parser.add_argument('chunks', nargs='+', metavar='chunk', help='a chunk file name in <build>/chunks')
    args = parser.parse_args(argv)
    pristine = args.pristine or default_pristine(args.build)
    for name in args.chunks:
        src = args.build / 'chunks' / name
        dst = args.build / 'chunks' / 'out' / name
        dst.parent.mkdir(exist_ok=True)
        dst.write_text(render(read(src), args.build, pristine), encoding='utf-8')
        print(name, len(dst.read_text(encoding='utf-8').split(NL)), 'lines')


if __name__ == '__main__':
    main()
