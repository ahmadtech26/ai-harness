#!/usr/bin/env python3
"""timed_run.py: run a command and keep its output with a timestamp on every line.

Usage (inside ragbench-rf-runner):
  python3 -I -B /w2/timed_run.py --log /out/<engine>/run-<arm>.log -- python3 -I -B /w1/run_w1.py ...

Why: run_w1.py prints one progress line per request («n/160 field id: ...», run_w1.py:367-380) but
no time. fallback_items.py needs the time each request ended, to check its matching of the server's
DEBUG lines against the requests. The stamps come from this container's clock, which is the clock of
the Docker VM that also stamps `docker logs --timestamps` (one kernel for every container).

It starts the command with its stdout and stderr joined, reads it line by line, writes
«<UTC time, microseconds>Z<TAB><line>» to --log as each line arrives, and repeats the line on its own
stderr. The first log line is «<time>\t# timed_run start», the last «<time>\t# timed_run exit <code>».
It exits with the command's exit code. It refuses a --log that exists. It never reads the API key:
the command line holds only the key file's path, and any «ragflow-…» word in it is masked anyway.
Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

KEY_WORD = re.compile(r'ragflow-\S+')


def stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def main(argv: list[str] | None = None, *, echo=None) -> int:
    echo = echo or sys.stderr
    ap = argparse.ArgumentParser(description='Run a command and timestamp each output line.')
    ap.add_argument('--log', required=True, type=Path)
    ap.add_argument('command', nargs=argparse.REMAINDER, help='-- then the command and its arguments')
    args = ap.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        print('refused: give the command after --', file=echo)
        return 2
    if args.log.exists():
        print(f'refused: {args.log} already exists', file=echo)
        return 2
    with open(args.log, 'x', encoding='utf-8', newline='\n') as log:
        log.write(f'{stamp()}\t# timed_run start: {KEY_WORD.sub("ragflow-[MASKED]", " ".join(command))}\n')
        log.flush()
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, encoding='utf-8', errors='replace', bufsize=1)
        with child.stdout:
            for line in child.stdout:
                line = line.rstrip('\n')
                log.write(f'{stamp()}\t{line}\n')
                log.flush()
                print(line, file=echo, flush=True)
        code = child.wait()
        log.write(f'{stamp()}\t# timed_run exit {code}\n')
    return code


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
