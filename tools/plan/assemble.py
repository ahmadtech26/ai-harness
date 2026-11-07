#!/usr/bin/env python3
"""Renders the plan's chunks with mkplan.py (the one beside this file) and joins them into the plan file.

    assemble.py --build <folder> --plan <output file> --chunk <name> [--chunk <name>...]

The chunks are joined in the order given. A line still starting with @@ afterwards is a directive mkplan did not
recognize; each one is reported.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

MKPLAN = Path(__file__).resolve().parent / 'mkplan.py'
NL = chr(10)
CR = chr(13)


def leftovers(plan: str) -> list[str]:
    return re.findall(r'^@@.*$', plan, re.M)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Renders the plan chunks with mkplan.py and joins them into the plan.')
    parser.add_argument('--build', required=True, type=Path, help='the plan build folder')
    parser.add_argument('--plan', required=True, type=Path, help='the plan file to write')
    parser.add_argument('--chunk', required=True, action='append', help='a chunk file name in <build>/chunks; repeat it')
    args = parser.parse_args(argv)
    r = subprocess.run([sys.executable, str(MKPLAN), '--build', str(args.build), '--', *args.chunk],
                       capture_output=True, text=True, encoding='utf-8')
    print(r.stdout[-400:])
    print(r.stderr[-1500:])
    if r.returncode != 0:
        print('mkplan failed with exit code', r.returncode, '- no plan written')
        return r.returncode
    parts = [(args.build / 'chunks' / 'out' / n).read_bytes().decode('utf-8').replace(CR + NL, NL) for n in args.chunk]
    plan = NL.join(parts)
    args.plan.write_bytes(plan.encode('utf-8'))
    print('plan chars', len(plan), 'lines', plan.count(NL))
    left = leftovers(plan)
    print('leftover directives', len(left))
    for line in left:
        print(' ', line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
