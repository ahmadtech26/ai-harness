"""legal-search-eval: check the retrieval evaluation set, run it against the ingested corpus, compare runs.

    legal-search-eval check                                        # the set against the corpus (no database)
    legal-search-eval run --label <label> [--reset] [--use-law-filter] [--config name=value ...]
                          [--field query|question] [--queries <side file>]
    legal-search-eval compare <incumbent label> <candidate label>  # deltas and the keep rule (REQ-EVL-004)
    legal-search-eval targets <label> --recall5 X --law-floor Y --mrr Z   # the agreed targets (REQ-EVL-003)

Paths default to the test stack's mounts (/content, /corpus, /evidence). `run` ingests the registry with
legal-search's own ingest and calls db.search directly: no caps, no MCP, no retrieval log, DEPTH results per
item. It writes eval-<label>.json and eval-<label>.md, and exits 1 when the memorandum data check fails. The
same corpus, set and code give the same numbers. `--field question` searches each item's question instead of its
query (REQ-RAG-032). `--queries` takes each item's query and law from a JSONL side file of {id, query, law} rows,
one per item (recorded queries, O-94), and the run records the file's sha256; it does not combine with
`--field question`.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, get_args

from psycopg import AsyncConnection

from legal_search import db
from legal_search.corrections import CorrectionError, load_corrections
from legal_search.evalset import EvalSet, EvalSetError, Item, corpus_problems, coverage, coverage_problems, parse_evalset
from legal_search.ingest import IngestError, Prepared, ingest, prepare
from legal_search.memorandum import MemorandumError, load_memorandum, load_memorandum_corrections
from legal_search.metrics import DEPTH, PRECISION, Key, Scored, item_metrics, keep_decision, summarise, targets_missed
from legal_search.registry import RegistryError, load_registry
from legal_search.search_config import DEFAULT, SearchConfig, with_overrides

CORPUS_TABLES = 'memorandum_links, memorandum_notes, articles, laws'
RESET_FLAG = 'LEGAL_SEARCH_EVAL_RESET'

ERRORS = (EvalSetError, IngestError, RegistryError, CorrectionError, MemorandumError, OSError)

Field = Literal['query', 'question']  # the item text `run` searches


@dataclass(frozen=True)
class Sources:
    evalset: Path
    registry: Path
    corrections: Path
    corpus: Path


def check_sources(sources: Sources, *, with_coverage: bool = True) -> tuple[EvalSet, Prepared, list[str]]:
    """Parse the set and check it against the corpus the registry ingest would load (no database)."""
    evalset = parse_evalset(sources.evalset.read_text(encoding='utf-8'))
    prepared = prepare(load_registry(sources.registry), load_corrections(sources.corrections), sources.corpus)
    memorandum = load_memorandum(sources.corpus, corrections=load_memorandum_corrections(sources.corrections))
    # Plan A gives at most one explaining note per article, so the links map article -> note.
    problems = corpus_problems(evalset, prepared.articles, dict(memorandum.links))
    if with_coverage:
        problems += coverage_problems(evalset, prepared.articles)
    return evalset, prepared, problems


class EvalError(RuntimeError):
    pass


def compare(incumbent: dict, candidate: dict) -> list[str]:
    """Lines comparing two runs: deltas, whether the numbers are identical, the keep verdict and a log row."""
    for field in ('set_sha256', 'corpus_sha256'):
        if incumbent['run'][field] != candidate['run'][field]:
            raise EvalError(f'cannot compare: the runs differ in {field} (re-run the incumbent on the current set and corpus)')
    before, after = incumbent['metrics'], candidate['metrics']
    lines = [f'overall {name} {before["overall"][name]:.4f} -> {after["overall"][name]:.4f}'
             for name in ('recall@5', 'recall@10', 'hit@5', 'mrr')]
    for law, row in before['per_law'].items():
        new = after['per_law'].get(law, {}).get('recall@5', 0.0)
        if new != row['recall@5']:
            lines.append(f'{law} recall@5 {row["recall@5"]:.4f} -> {new:.4f}')
    lines.append(f'identical: {"yes" if before == after else "no"}')
    keep, reasons = keep_decision(before, after)
    lines.append('verdict: KEEP' if keep else f'verdict: REVERT ({"; ".join(reasons)})')
    lines.append('log-row: ' + log_row(candidate))
    return lines


def log_row(report: dict) -> str:
    """The P3-results tuning-log row for a run."""
    overall = report['metrics']['overall']
    law, lowest = min(report['metrics']['per_law'].items(), key=lambda entry: (entry[1]['recall@5'], entry[0]))
    return (f'| {report["run"]["label"]} | {_settings(report["run"])} | {overall["recall@5"]:.4f} | {overall["recall@10"]:.4f} '
            f'| {overall["hit@5"]:.4f} | {overall["mrr"]:.4f} | {law} {lowest["recall@5"]:.4f} |')


def _settings(run: dict) -> str:
    parts = ['law filter'] if run.get('use_law_filter') else []
    parts += [f'{name}={value}' for name, value in sorted(run.get('config', {}).items())]
    return ', '.join(parts) or 'defaults'


async def run_eval(conninfo: str, sources: Sources, label: str, *, use_law_filter: bool = False, reset: bool = False,
                   config: SearchConfig = DEFAULT, field: Field = 'query', queries: Path | None = None) -> dict:
    """Ingest the registry, search every item (DEPTH results, no caps) and return the report. Each item searches its
    `field`, or, with a `queries` side file, its row's query; the law (the item's, or the row's) applies only with
    use_law_filter."""
    if field not in get_args(Field):
        raise EvalError(f'field must be one of {", ".join(get_args(Field))}, not {field!r}')
    if queries is not None and field != 'query':
        raise EvalError(f'field {field!r} does not apply with a side file: its rows give each item its query')
    evalset, prepared, problems = check_sources(sources, with_coverage=False)
    if problems:
        raise EvalError('the evaluation set fails its checks:\n' + '\n'.join(problems))
    if queries is None:
        inputs, queries_sha256 = [(item, getattr(item, field), item.law) for item in evalset.items], None
    else:
        rows, queries_sha256 = _side_file(queries, evalset.items)
        inputs = [(item, *rows[item.id]) for item in evalset.items]
    keys = frozenset((a.law_slug, a.number, a.suffix) for articles in prepared.articles.values() for a in articles)
    if reset:
        await _reset(conninfo)
    async with await AsyncConnection.connect(conninfo, autocommit=True) as conn:
        await _require_only_the_registry(conn, keys, complete=False)  # a database holding other articles stops here, unwritten
    await ingest(conninfo, sources.registry, sources.corrections, sources.corpus)
    async with await AsyncConnection.connect(conninfo, autocommit=True) as conn:
        await _require_only_the_registry(conn, keys, complete=True)
        results = [await _score(conn, item, text, law if use_law_filter else None, config) for item, text, law in inputs]
        memorandum = await memorandum_check(conn, evalset.items)
        corpus_sha256 = await corpus_digest(conn)
    return {
        'run': {
            'label': label, 'set': evalset.name, 'set_review': evalset.review_status, 'set_sha256': evalset.sha256,
            'corpus_sha256': corpus_sha256, 'use_law_filter': use_law_filter, 'depth': DEPTH, 'config': asdict(config),
            'field': field, 'queries_sha256': queries_sha256,
        },
        'metrics': summarise([scored for scored, _ in results]),
        'memorandum': memorandum,
        'coverage': coverage(evalset),
        'items': [row for _, row in results],
    }


def _side_file(path: Path, items: tuple[Item, ...]) -> tuple[dict[str, tuple[str, str | None]], str]:
    """Each id's (query, law) from the side file's {id, query, law} rows, and the sha256 of the file's bytes.

    Every item needs exactly one row; rows for ids outside the set are ignored. A row is a JSON object with a string
    id, a string query (an empty one is a recorded call that searches nothing, as db.search returns [] for it) and a
    law that is a slug string, null or absent, read as tools.search_law reads it: stripped, and blank means none. Lines
    split on '\\n' only, as parse_evalset's do, so a query may hold U+2028. Every problem is reported, with its line,
    in one EvalError raised before run_eval resets or ingests anything."""
    data = path.read_bytes()
    rows: dict[str, tuple[str, str | None]] = {}
    twice: dict[str, None] = {}  # ids named more than once, each once, in file order
    problems: list[str] = []
    for number, line in enumerate(data.decode('utf-8').replace('\r\n', '\n').split('\n'), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            problems.append(f'line {number}: not JSON ({error.msg})')
            continue
        shape = _side_row_problems(row)
        if shape:
            problems.extend(f'line {number}: {problem}' for problem in shape)
            continue
        if row['id'] in rows:
            twice[row['id']] = None
        rows[row['id']] = (row['query'], (row.get('law') or '').strip() or None)
    wanted = {item.id for item in items}
    problems += [f'no row for item {item.id}' for item in items if item.id not in rows]
    problems += [f'more than one row for item {item_id}' for item_id in twice if item_id in wanted]
    if problems:
        raise EvalError(f'side file {path}: ' + '; '.join(problems))
    return rows, hashlib.sha256(data).hexdigest()


def _side_row_problems(row: object) -> list[str]:
    if not isinstance(row, dict):
        return ['must be a JSON object']
    problems = [f'{key} must be a string' for key in ('id', 'query') if not isinstance(row.get(key), str)]
    if not isinstance(row.get('law'), str | None):
        problems.append('law must be a slug string or null')
    return problems


async def _score(conn: AsyncConnection, item: Item, text: str, law: str | None, config: SearchConfig) -> tuple[Scored, dict]:
    found = await db.search(conn, text, DEPTH, law=law, config=config)
    ranked = tuple((article.law_slug, article.number, article.suffix) for article in found)
    scored = Scored(item.scored_law, frozenset(expected.key for expected in item.expected), ranked)
    row = {
        'id': item.id, 'law': item.scored_law, 'query': text, 'law_filter': law,
        'expected': [list(expected.key) for expected in item.expected], 'ranked': [list(key) for key in ranked],
    }
    row.update({name: round(value, PRECISION) for name, value in item_metrics(scored).items()})
    return scored, row


async def memorandum_check(conn: AsyncConnection, items: tuple[Item, ...]) -> dict:
    """Data check (spec B.1 ‡): for every memorandum item, get_memorandum's query for its Civil Code article must
    serve exactly its expected_notes (the article's own note). A mismatch is a linkage bug, not a retrieval score."""
    checked, mismatched = 0, []
    for item in items:
        if not item.expected_notes:
            continue
        checked += 1
        article = item.expected[0].number  # parse_evalset: exactly one expected article
        served = [note.note_no for note in await db.memorandum_page(conn, article, 0, 10_000)]
        if served != list(item.expected_notes):
            mismatched.append(f'{item.id}: article {article} serves notes {served}, expected {list(item.expected_notes)}')
    return {'items_checked': checked, 'mismatched': mismatched, 'pass': not mismatched}


async def corpus_digest(conn: AsyncConnection) -> str:
    """sha256 over every article's key and normalised text: two runs compare only on the same corpus."""
    cur = await conn.execute('SELECT law_slug, number, suffix, norm FROM articles ORDER BY law_slug, number, suffix')
    digest = hashlib.sha256()
    for row in await cur.fetchall():
        digest.update(json.dumps(list(row), ensure_ascii=False).encode('utf-8'))
    return digest.hexdigest()


async def _require_only_the_registry(conn: AsyncConnection, keys: frozenset[Key], *, complete: bool) -> None:
    """Refuse a database holding articles the registry does not give (a wrong DATABASE_URL). Before the ingest
    (complete=False) nothing has been written yet; after it the database must hold exactly the registry's keys."""
    cur = await conn.execute("SELECT to_regclass('articles') IS NOT NULL")
    held: list[Key] = []
    if (await cur.fetchone())[0]:
        cur = await conn.execute('SELECT law_slug, number, suffix FROM articles')
        held = [tuple(row) for row in await cur.fetchall()]
    outside = [key for key in held if key not in keys]
    if outside or (complete and len(held) != len(keys)):
        raise EvalError(f'the database holds {len(held)} articles, {len(outside)} outside the registry, which gives '
                        f'{len(keys)}; run against the test stack with --reset')


async def _reset(conninfo: str) -> None:
    """Drop the corpus tables (the ingest recreates them). Only where the test stack sets RESET_FLAG."""
    if os.environ.get(RESET_FLAG) != '1':
        raise EvalError(f'--reset drops the corpus tables; it runs only where {RESET_FLAG}=1 (the test stack)')
    async with await AsyncConnection.connect(conninfo, autocommit=True) as conn:
        await conn.execute(f'DROP TABLE IF EXISTS {CORPUS_TABLES} CASCADE')


def write_report(report: dict, out: Path) -> tuple[Path, Path]:
    """eval-<label>.json (the whole report, keys sorted) and eval-<label>.md (the tables and the misses)."""
    out.mkdir(parents=True, exist_ok=True)
    stem = f'eval-{report["run"]["label"]}'
    json_path, md_path = out / f'{stem}.json', out / f'{stem}.md'
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    md_path.write_text(markdown(report), encoding='utf-8')
    return json_path, md_path


def _key_text(key: list) -> str:
    law, number, suffix = key
    return f'{law} {number}' + (f' {suffix}' if suffix else '')


def _row(scope: str, row: dict) -> str:
    return (f'| {scope} | {row["items"]} | {row["recall@5"]:.4f} | {row["recall@10"]:.4f} | {row["hit@5"]:.4f} '
            f'| {row["hit@10"]:.4f} | {row["mrr"]:.4f} |')


def markdown(report: dict) -> str:
    run, metrics, memo = report['run'], report['metrics'], report['memorandum']
    lines = [
        f'# Retrieval evaluation — {run["label"]}',
        '',
        f'Set `{run["set"]}` (review {run["set_review"]}, sha256 `{run["set_sha256"][:12]}`); corpus sha256 '
        f'`{run["corpus_sha256"][:12]}`; settings: {_settings(run)}; {run["depth"]} results per item.',
        '',
        '| scope | items | recall@5 | recall@10 | hit@5 | hit@10 | MRR |',
        '|---|---|---|---|---|---|---|',
        _row('**overall**', metrics['overall']),
        *(_row(law, row) for law, row in metrics['per_law'].items()),
        '',
        f'Memorandum data check: {memo["items_checked"]} items, '
        + ('each served exactly its expected note.' if memo['pass'] else f'MISMATCH {"; ".join(memo["mismatched"])}.'),
        '',
        '## Items below full recall@5',
        '',
    ]
    for item in report['items']:
        if item['recall@5'] < 1:
            top = ', '.join(_key_text(key) for key in item['ranked'][:5]) or '(no results)'
            want = ', '.join(_key_text(key) for key in item['expected'])
            lines.append(f'- `{item["id"]}` «{item["query"]}»: expected {want}; top 5: {top}')
    return '\n'.join(lines) + '\n'


def _check(sources: Sources) -> None:
    evalset, _, problems = check_sources(sources)
    memorandum = sum(1 for item in evalset.items if item.expected_notes)
    print(f'evalset {evalset.name}: {len(evalset.items)} items (review {evalset.review_status}), {memorandum} memorandum items')
    print('coverage: ' + ', '.join(f'{law} {count}' for law, count in coverage(evalset).items()))
    for problem in problems:
        print(f'PROBLEM {problem}')
    print(f'{len(problems)} problems')
    if problems:
        raise SystemExit(1)


def _sources(args: argparse.Namespace) -> Sources:
    return Sources(args.evalset, args.registry, args.corrections, args.corpus)


_LABEL = re.compile(r'[a-z0-9][a-z0-9.-]*')


def _label(value: str) -> str:
    """A run label: it names eval-<label>.{json,md} inside --out, so it may hold no path separator or leading dot."""
    if not _LABEL.fullmatch(value):
        raise argparse.ArgumentTypeError(f'labels are lowercase letters, digits, dots and dashes: {value!r}')
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='legal-search-eval', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--set', dest='evalset', type=Path, default=Path('/content/eval/retrieval-v1.jsonl'))
    parser.add_argument('--registry', type=Path, default=Path('/content/corpus/laws.json'))
    parser.add_argument('--corrections', type=Path, default=Path('/content/corpus/corrections.json'))
    parser.add_argument('--corpus', type=Path, default=Path(os.environ.get('CORPUS_DIR', '/corpus')))
    parser.add_argument('--out', type=Path, default=Path('/evidence'))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check', help='check the set against the corpus (no database)')
    run = commands.add_parser('run', help='ingest the registry, search every item, write the report')
    run.add_argument('--label', required=True, type=_label)
    run.add_argument('--use-law-filter', action='store_true', help="pass each item's law to search")
    run.add_argument('--reset', action='store_true', help=f'drop the corpus tables first (only where {RESET_FLAG}=1)')
    run.add_argument('--config', action='append', default=[], metavar='NAME=VALUE', help='override a SearchConfig field')
    run.add_argument('--field', choices=get_args(Field), default='query', help='the item text to search')
    run.add_argument('--queries', type=Path, metavar='PATH', help='a JSONL side file of {id, query, law} rows, one per item, searched instead')
    compare_command = commands.add_parser('compare', help='compare two runs in --out and apply the keep rule')
    compare_command.add_argument('incumbent', type=_label)
    compare_command.add_argument('candidate', type=_label)
    targets = commands.add_parser('targets', help='check a run against the agreed targets')
    targets.add_argument('label', type=_label)
    targets.add_argument('--recall5', type=float, required=True)
    targets.add_argument('--law-floor', type=float, required=True)
    targets.add_argument('--mrr', type=float, required=True)
    return parser


def _load(out: Path, label: str) -> dict:
    path = out / f'eval-{label}.json'
    if not path.exists():
        raise EvalError(f'no report {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == 'check':
            _check(_sources(args))
        elif args.command == 'run':
            report = asyncio.run(run_eval(db.database_url(), _sources(args), args.label,
                                          use_law_filter=args.use_law_filter, reset=args.reset, config=with_overrides(DEFAULT, args.config),
                                          field=args.field, queries=args.queries))
            json_path, md_path = write_report(report, args.out)
            overall = report['metrics']['overall']
            print(f'wrote {json_path.name} and {md_path.name}: recall@5 {overall["recall@5"]:.4f}, recall@10 '
                  f'{overall["recall@10"]:.4f}, MRR {overall["mrr"]:.4f}, memorandum '
                  f'{"pass" if report["memorandum"]["pass"] else "FAIL"}')
            if not report['memorandum']['pass']:
                raise SystemExit(1)  # the report is written as evidence; a linkage bug must still fail the run
        elif args.command == 'compare':
            print('\n'.join(compare(_load(args.out, args.incumbent), _load(args.out, args.candidate))))
        else:
            missed = targets_missed(_load(args.out, args.label)['metrics'], recall5=args.recall5, law_floor=args.law_floor, mrr=args.mrr)
            print('targets: MET' if not missed else 'targets: MISSED\n' + '\n'.join(f'  {line}' for line in missed))
    except (EvalError, ValueError, *ERRORS) as error:
        raise SystemExit(f'legal-search-eval: {error}') from error


if __name__ == '__main__':
    main()
