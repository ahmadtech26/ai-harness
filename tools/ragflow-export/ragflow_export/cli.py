"""ragflow-export: copy datasets, documents and parsed chunks out of a RAGFlow server, read-only.

    python -m ragflow_export --base-url https://ragflow.example.org --api-key-file <file outside any repository>
                             [--out <folder inside a quarantine>] [--dataset ID_OR_NAME ...] [--dry-run] [--resume]

The key is read from a file and is never accepted on the command line. See README.md.
Exit codes: 0 done, 1 stopped or incomplete (resumable), 2 refused before anything was sent or written,
130 interrupted.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Callable, TextIO

from ragflow_export.client import RagflowClient, load_api_key
from ragflow_export.errors import ExportError, IncompleteExport, Refused
from ragflow_export.exporter import STATE_NAME, ExportOptions, dry_run, export, for_terminal


def default_out_dir() -> Path:
    root = 'D:/Iqraa Law' if os.name == 'nt' else '/mnt/d/Iqraa Law'
    return Path(root) / '.hq' / 'quarantine' / 'ragflow-export'


def _bounded_int(low: int, high: int) -> Callable[[str], int]:
    def parse(text: str) -> int:
        value = int(text)
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f'must be between {low} and {high}')
        return value
    return parse


def _positive_float(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError('must be above 0')
    return value


class _QuietParser(argparse.ArgumentParser):
    """An argument parser whose errors never repeat what was typed, in case what was typed is the key.

    argparse would echo it in "unrecognized arguments: ..." and "invalid value: ...". Only the list of
    missing required options is kept, because it names this parser's own options and nothing typed.
    """

    def error(self, message: str):
        if not message.startswith('the following arguments are required:'):
            message = ('unrecognized or invalid arguments; they are not repeated here, in case one of them is the '
                       'key. The key is read only from --api-key-file; see --help')
        self.print_usage(sys.stderr)
        self.exit(2, f'{self.prog}: error: {message}\n')


def build_parser() -> argparse.ArgumentParser:
    # allow_abbrev=False: otherwise "--api-key <key>" would be taken as "--api-key-file <key>",
    # and an error about the missing "file" would print the key.
    parser = _QuietParser(prog='ragflow-export', description=__doc__, allow_abbrev=False,
                          formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base-url', required=True, help='e.g. https://ragflow.example.org (no credentials in it)')
    parser.add_argument('--api-key-file', required=True, type=Path,
                        help='file holding only the API key; keep it outside every repository')
    parser.add_argument('--out', type=Path, default=default_out_dir(),
                        help='export folder; must not exist or be empty (default: %(default)s)')
    parser.add_argument('--dataset', action='append', default=[], metavar='ID_OR_NAME',
                        help='export only this dataset (repeatable); matches an id or an exact name')
    parser.add_argument('--dry-run', action='store_true', help='list datasets and documents only; write nothing')
    parser.add_argument('--resume', action='store_true', help='continue an unfinished export in --out')
    parser.add_argument('--show-names', action='store_true',
                        help='print dataset and document names in a dry run (they may hold client facts)')
    parser.add_argument('--probe-version', action='store_true',
                        help='also GET /api/v1/system/version, a route whose path is not confirmed')
    parser.add_argument('--page-size', type=_bounded_int(1, 1000), default=30)
    parser.add_argument('--timeout', type=_positive_float, default=60.0, help='seconds per request')
    parser.add_argument('--max-attempts', type=_bounded_int(1, 20), default=5,
                        help='attempts per request on 429, 5xx or a dropped connection')
    parser.add_argument('--ca-file', type=Path, help='CA bundle for a server with a private certificate')
    parser.add_argument('--allow-insecure-http', action='store_true',
                        help='allow http:// to a host other than this machine (sends the key unencrypted)')
    parser.add_argument('--allow-non-quarantine-out', action='store_true',
                        help='allow an --out that is not inside a folder named "quarantine"')
    return parser


def _never_crash_on_encoding(stream: TextIO) -> None:
    """Arabic names must not crash a console or pipe whose encoding cannot show them."""
    encoding = (getattr(stream, 'encoding', None) or '').lower().replace('-', '')
    if encoding != 'utf8' and hasattr(stream, 'reconfigure'):
        try:
            stream.reconfigure(errors='backslashreplace')
        except (ValueError, OSError):
            pass


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None, stderr: TextIO | None = None,
         sleep: Callable[[float], object] = time.sleep) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    for stream in (stdout, stderr):
        _never_crash_on_encoding(stream)
    args = build_parser().parse_args(argv)
    redact: Callable[[str], str] = str

    def say(message: str) -> None:
        print(f'ragflow-export: {for_terminal(redact(message))}', file=stderr)

    def say_resume_hint() -> None:
        if not args.dry_run and (args.out / STATE_NAME).is_file():
            say('the export is unfinished; run the same command again with --resume to continue it')

    try:
        client = RagflowClient(args.base_url, load_api_key(args.api_key_file), timeout=args.timeout,
                               max_attempts=args.max_attempts, sleep=sleep,
                               allow_insecure_http=args.allow_insecure_http, ca_file=args.ca_file)
        redact = client.redact
        options = ExportOptions(out_dir=args.out, dataset_filter=tuple(args.dataset), resume=args.resume,
                                page_size=args.page_size, allow_non_quarantine_out=args.allow_non_quarantine_out,
                                probe_version=args.probe_version, show_names=args.show_names)
        if args.dry_run:
            dry_run(client, options, out=stdout)
            return 0
        export(client, options, log=say)
        print(args.out / 'manifest.json', file=stdout)
        return 0
    except IncompleteExport as error:
        say(str(error))
        say('run the same command again with --resume to retry the failed documents')
        return 1
    except Refused as error:
        say(f'refused: {error}')
        return 2
    except ExportError as error:
        say(f'stopped: {type(error).__name__}: {error}')
        say_resume_hint()
        return 1
    except OSError as error:
        # A disk, permission or state-file problem: name it and the path, without a traceback.
        where = f': {error.filename}' if error.filename else ''
        say(f'stopped: {type(error).__name__}{where}')
        say_resume_hint()
        return 1
    except KeyboardInterrupt:
        say('interrupted; run the same command again with --resume to continue')
        return 130
