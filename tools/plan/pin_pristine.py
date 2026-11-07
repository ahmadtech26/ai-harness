#!/usr/bin/env python3
"""Pins the plan generator's "pristine" to the plan's base commits, now that the working trees hold the changes.

    pin_pristine.py --build <folder> --repo fork=<path>@<sha> --repo harness=<path>@<sha>

Every file a chunk in <build>/chunks/chunk-*.md edits (@@EDITS, @@EDITSFROM, @@STAGEEDITS) is read with
`git show <sha>:<rel>` from its root's repository, which only reads, and written to <build>/tmp/pristine/<root>/<rel>,
the default --pristine of mkplan.py.
"""
import argparse
import re
import subprocess
from pathlib import Path

from mkplan import default_pristine

ROOTS = ('fork', 'harness')


def repo_spec(spec: str):
    """<root>=<path>@<sha> as (root, (path, sha)); the sha follows the last @."""
    root, eq, rest = spec.partition('=')
    path, at, sha = rest.rpartition('@')
    if not (eq and at and path and sha) or root not in ROOTS:
        raise argparse.ArgumentTypeError(f'{spec!r} is not <{"|".join(ROOTS)}>=<path>@<sha>')
    return root, (Path(path), sha)


def edited_paths(build: Path) -> set[str]:
    paths = set()
    for chunk in sorted((build / 'chunks').glob('chunk-*.md')):
        for line in chunk.read_text(encoding='utf-8').splitlines():
            m = re.match(r'^@@(EDITS|EDITSFROM)\s+(\S+)', line)
            if m:
                paths.add(m.group(2))
            m = re.match(r'^@@STAGEEDITS\s+\S+\s+(\S+)', line)
            if m:
                paths.add(m.group(1))
    return paths


def main(argv=None, run=subprocess.run):
    parser = argparse.ArgumentParser(description='Pins the files the plan edits to the base commits.')
    parser.add_argument('--build', required=True, type=Path, help='the plan build folder')
    parser.add_argument('--repo', required=True, action='append', type=repo_spec, metavar='ROOT=PATH@SHA',
                        help=f'the repository and base commit of a root ({", ".join(ROOTS)}); repeat it')
    args = parser.parse_args(argv)
    repos = dict(args.repo)
    out = default_pristine(args.build)
    paths = edited_paths(args.build)
    missing = sorted({spec.partition('/')[0] for spec in paths} - repos.keys())
    if missing:
        raise SystemExit(f'no --repo for {", ".join(missing)}, which the chunks edit')
    for spec in sorted(paths):
        root, _, rel = spec.partition('/')
        repo, sha = repos[root]
        data = run(['git', '-C', str(repo), 'show', f'{sha}:{rel}'], capture_output=True, check=True).stdout
        dest = out / root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    print('pinned', len(paths), 'files at', {k: v[1] for k, v in repos.items()})


if __name__ == '__main__':
    main()
