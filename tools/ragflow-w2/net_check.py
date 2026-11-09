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

The hosted run (README.md, «Hosted run (owner, 2026-11-09)») adds checks through an HTTP proxy:
  ... --proxy ragbench-rf-proxy:3128 --tunnel openrouter.ai:443 \
      --tunnel-refused huggingface.co:443 --tunnel-refused 1.1.1.1:443
--proxy host:port           the proxy the two checks below go through.
--tunnel host:port          the proxy must answer «CONNECT host:port» with 200, and a TLS handshake with that
                            host must then complete, its certificate verified for that name against the system's
                            CA store (--cafile replaces the store; tests only). A certificate the proxy forged, as
                            TLS interception would, fails. Nothing is sent after the handshake: no request, no
                            credential. It is the positive control of the refusals below.
--tunnel-refused host:port  the proxy must answer «CONNECT host:port» with 403, a refusal by its own rules. A 200
                            (the tunnel opened) fails, and so does any other status: a 503, for one, means the
                            rules let the request through and the connection beyond failed.
A proxy that does not answer fails every check that goes through it.

And a record of what answers on one address, made for the internal network's gateway (README.md, H3 and H0 (f)):
  ... --scan 10.231.47.1 [--scan-ports 1-65535] [--scan-timeout 1]
--scan IP           a TCP connect to every port of --scan-ports (both ends included), each socket closed as soon as
                    it opens: nothing is sent. It prints the count of each outcome (connected, refused, timeout, or
                    an errno), the ports that connected and the ports that timed out (the first 200 of each). It is
                    recorded, not checked: it never changes the exit status. An IP address only, not a name.

Prints one line per target, exits 0 only when every target behaves as asked (2: refused before checking).
Standard library only.
"""

from __future__ import annotations

import argparse
import errno
import ipaddress
import socket
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor

BLOCKED_ERRNOS = {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ETIMEDOUT}
HEAD_LIMIT = 64 * 1024
SCAN_WORKERS = 256
SCAN_LISTED = 200


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


def authority(host: str, port: int) -> str:
    return f'[{host}]:{port}' if ':' in host else f'{host}:{port}'


def connect_via(proxy: tuple[str, int], host: str, port: int, timeout: float):
    """Send «CONNECT host:port» to the proxy and read its answer's head. (status, X-Squid-Error or '', socket); the
    socket is open only when the status is 200. Raises OSError when the proxy does not answer."""
    sock = socket.create_connection(proxy, timeout=timeout)
    try:
        where = authority(host, port)
        sock.sendall(f'CONNECT {where} HTTP/1.1\r\nHost: {where}\r\n\r\n'.encode('ascii'))
        head = b''
        while b'\r\n\r\n' not in head and len(head) < HEAD_LIMIT:
            chunk = sock.recv(4096)
            if not chunk:
                break
            head += chunk
        lines = head.split(b'\r\n\r\n', 1)[0].decode('latin-1').split('\r\n')
        parts = lines[0].split(' ', 2)
        if len(parts) < 2 or not parts[0].startswith('HTTP/') or not parts[1].isdigit():
            raise OSError(f'no HTTP status line ({len(head)} bytes)')
        status = int(parts[1])
        squid_error = next((line.split(':', 1)[1].strip() for line in lines[1:]
                            if line.lower().startswith('x-squid-error:')), '')
    except BaseException:
        sock.close()
        raise
    if status != 200:
        sock.close()
        return status, squid_error, None
    return status, squid_error, sock


def tunnel(proxy, host: str, port: int, timeout: float, context: ssl.SSLContext) -> tuple[bool, str]:
    try:
        status, squid_error, sock = connect_via(proxy, host, port, timeout)
    except OSError as error:
        return False, f'the proxy did not answer ({type(error).__name__})'
    if sock is None:
        return False, f'CONNECT {status}' + (f' ({squid_error})' if squid_error else '')
    try:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            version = tls.version()
    except (ssl.SSLError, ssl.CertificateError, OSError) as error:
        sock.close()
        return False, f'CONNECT 200, TLS failed ({type(error).__name__}: {str(error)[:120]})'
    return True, f'CONNECT 200, TLS verified ({version}, certificate for {host})'


def refused(proxy, host: str, port: int, timeout: float) -> tuple[bool, str]:
    try:
        status, squid_error, sock = connect_via(proxy, host, port, timeout)
    except OSError as error:
        return False, f'the proxy did not answer ({type(error).__name__})'
    if sock is not None:
        sock.close()
        return False, 'CONNECT 200: the proxy opened the tunnel'
    if status != 403:
        return False, f'CONNECT {status}: not a refusal by the proxy\'s rules'
    return True, f'CONNECT 403' + (f' ({squid_error})' if squid_error else '')


def probe(host: str, port: int, timeout: float) -> str:
    """One TCP connect, closed as soon as it opens, nothing sent: 'connected', 'refused', 'timeout' or 'errno N'."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return 'connected'
    except socket.timeout:
        return 'timeout'
    except ConnectionRefusedError:
        return 'refused'
    except OSError as error:
        return f'errno {error.errno}'


def scan(host: str, ports: range, timeout: float) -> dict[str, list[int]]:
    """{outcome: [port, ...]} for every port, in port order."""
    with ThreadPoolExecutor(max_workers=max(1, min(SCAN_WORKERS, len(ports)))) as pool:
        outcomes = list(pool.map(lambda port: probe(host, port, timeout), ports))
    found: dict[str, list[int]] = {}
    for port, outcome in zip(ports, outcomes):
        found.setdefault(outcome, []).append(port)
    return found


def scan_range(text: str) -> range | None:
    low, dash, high = text.partition('-')
    if not (dash and low.isdigit() and high.isdigit() and 1 <= int(low) <= int(high) <= 65535):
        return None
    return range(int(low), int(high) + 1)


def scan_lines(host: str, ports: range, found: dict[str, list[int]]) -> list[str]:
    def listed(numbers: list) -> str:
        more = len(numbers) - SCAN_LISTED
        return (' '.join(map(str, numbers[:SCAN_LISTED])) or 'none') + (f' and {more} more' if more > 0 else '')

    counts = ', '.join(f'{outcome} {len(numbers)}' for outcome, numbers in sorted(found.items()))
    other = [f'{port} {outcome}' for outcome, numbers in sorted(found.items())
             if outcome not in ('connected', 'refused', 'timeout') for port in numbers]
    return [f'scan {host} ports {ports[0]}-{ports[-1]} (nothing sent; recorded, not a check): {counts}',
            f'scan connected: {listed(found.get("connected", []))}',
            f'scan timed out: {listed(found.get("timeout", []))}',
            'scan other: ' + (', '.join(other[:SCAN_LISTED]) or 'none')]


def main(argv: list[str] | None = None, *, stdout=None) -> int:
    stdout = stdout or sys.stdout
    ap = argparse.ArgumentParser(description='Check reachability with a positive control.')
    ap.add_argument('--reach', action='append', type=target, default=[])
    ap.add_argument('--block', action='append', type=target, default=[])
    ap.add_argument('--proxy', type=target)
    ap.add_argument('--tunnel', action='append', type=target, default=[])
    ap.add_argument('--tunnel-refused', action='append', type=target, default=[])
    ap.add_argument('--cafile', help='trust this CA file instead of the system store (tests only)')
    ap.add_argument('--timeout', type=float, default=5.0)
    ap.add_argument('--scan', metavar='IP', help='record what answers on this address (never a check)')
    ap.add_argument('--scan-ports', metavar='LOW-HIGH', help='with --scan (default: 1-65535)')
    ap.add_argument('--scan-timeout', type=float, default=1.0, help='seconds per port (default: %(default)s)')
    args = ap.parse_args(argv)
    if not args.reach or not args.block:
        print('refused: give at least one --reach (the positive control) and one --block', file=stdout)
        return 2
    if args.scan is None and args.scan_ports is not None:
        print('refused: --scan-ports needs --scan', file=stdout)
        return 2
    ports = scan_range(args.scan_ports or '1-65535')
    if args.scan is not None:
        try:
            ipaddress.ip_address(args.scan)
        except ValueError:
            print(f'refused: --scan takes an IP address, not {args.scan!r}', file=stdout)
            return 2
        if ports is None:
            print(f'refused: --scan-ports must be LOW-HIGH within 1-65535, not {args.scan_ports!r}', file=stdout)
            return 2
    if (args.tunnel or args.tunnel_refused) and args.proxy is None:
        print('refused: --tunnel and --tunnel-refused need --proxy', file=stdout)
        return 2
    if args.tunnel_refused and not args.tunnel:
        print('refused: --tunnel-refused needs at least one --tunnel (the positive control through the proxy)',
              file=stdout)
        return 2
    good = True
    for want, targets in (('connected', args.reach), ('blocked', args.block)):
        for host, port in targets:
            kind, outcome = attempt(host, port, args.timeout)
            good &= kind == want
            verb = 'reach' if want == 'connected' else 'block'
            print(f'{"ok  " if kind == want else "FAIL"} {verb} {host}:{port}: {outcome}', file=stdout)
    if args.proxy is not None:
        via = authority(*args.proxy)
        context = ssl.create_default_context(cafile=args.cafile)
        for host, port in args.tunnel:
            ok, outcome = tunnel(args.proxy, host, port, args.timeout, context)
            good &= ok
            print(f'{"ok  " if ok else "FAIL"} tunnel {authority(host, port)} via {via}: {outcome}', file=stdout)
        for host, port in args.tunnel_refused:
            ok, outcome = refused(args.proxy, host, port, args.timeout)
            good &= ok
            print(f'{"ok  " if ok else "FAIL"} refused {authority(host, port)} by {via}: {outcome}', file=stdout)
    if args.scan is not None:
        for line in scan_lines(args.scan, ports, scan(args.scan, ports, args.scan_timeout)):
            print(line, file=stdout, flush=True)
    return 0 if good else 1


if __name__ == '__main__':
    sys.exit(main())
