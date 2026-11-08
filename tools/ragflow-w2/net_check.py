#!/usr/bin/env python3
"""net_check.py: prove what a container can and cannot reach, with a positive control. No curl needed.

  python3 -I -B /w2/net_check.py --reach 127.0.0.1:9380 --reach ragbench-rf-tei:80 \
      --block 1.1.1.1:443 --block huggingface.co:443 --block host.docker.internal:443

--reach host:port   a TCP connection must open (the positive control: the same tool, the same
                    container, an internal target).
--block host:port   no TCP connection may open. Only these failures count as blocked: the name does
                    not resolve, the network or host is unreachable, or the attempt times out.
                    «Connection refused» does NOT count: it means a host answered, so the path is open
                    and only the port is closed.
Prints one line per target, exits 0 only when every target behaves as asked. Standard library only.
"""

from __future__ import annotations

import argparse
import errno
import socket
import sys

BLOCKED_ERRNOS = {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ETIMEDOUT}


def target(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(':')
    if not host or not port.isdigit():
        raise argparse.ArgumentTypeError(f'{text!r} is not host:port')
    return host.strip('[]'), int(port)


def attempt(host: str, port: int, timeout: float) -> tuple[str, str]:
    """('connected' | 'blocked' | 'other', what happened)"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return 'connected', 'connected'
    except socket.gaierror as error:
        return 'blocked', f'no address ({error.args[0]})'
    except socket.timeout:
        return 'blocked', 'timed out'
    except OSError as error:
        kind = 'blocked' if error.errno in BLOCKED_ERRNOS else 'other'
        return kind, f'{type(error).__name__} (errno {error.errno})'


def main(argv: list[str] | None = None, *, stdout=None) -> int:
    stdout = stdout or sys.stdout
    ap = argparse.ArgumentParser(description='Check reachability with a positive control.')
    ap.add_argument('--reach', action='append', type=target, default=[])
    ap.add_argument('--block', action='append', type=target, default=[])
    ap.add_argument('--timeout', type=float, default=5.0)
    args = ap.parse_args(argv)
    if not args.reach or not args.block:
        print('refused: give at least one --reach (the positive control) and one --block', file=stdout)
        return 2
    good = True
    for want, targets in (('connected', args.reach), ('blocked', args.block)):
        for host, port in targets:
            kind, outcome = attempt(host, port, args.timeout)
            good &= kind == want
            verb = 'reach' if want == 'connected' else 'block'
            print(f'{"ok  " if kind == want else "FAIL"} {verb} {host}:{port}: {outcome}', file=stdout)
    return 0 if good else 1


if __name__ == '__main__':
    sys.exit(main())
