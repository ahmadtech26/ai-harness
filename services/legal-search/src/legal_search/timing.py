"""legal-search-timing: the whole `search_law` call, timed through MCP (REQ-RAG-021, Task 1.5).

    legal-search-timing --url http://legal-search:8000/mcp --secret-file /secrets/legal_search
                        --set /content/eval/retrieval-v1.jsonl --field query|question|fused
                        --users 1,5,20 --repeat 5 --spans /spans/calls.jsonl --out <timing.json>

It runs in the timing stack only (compose.timing.yaml: Postgres on tmpfs, its own image tag, test-only secret),
never against staging. Its figures are labelled «substitute, not launch-class» (spec :185).

Before the timed runs it waits for the server's /health, then raises the guard settings through the admin API
(PUT /admin/guard-settings: guard_settings.update_settings, who «timing», why «timing stack», and the server's
settings cache is invalidated): the caps and every detector threshold, so that no timed call is refused. It seeds
the run's heavy user (`timing-<tag>-heavy`) with `--heavy-rows` back-dated retrieval_log rows spread over the 8-day
look-back (a direct INSERT; the report records the seed's shape: a stress bound, not a typical user).

Every run has its own users, named with its `--run-tag` (default: the field and 6 random hex digits), so a run's
users start with no history from an earlier run on the same stack: the guard loads 8 days of it. `--run-tag ''`
gives the plan's names, `timing-<level>-<n>` and `timing-heavy`. At each level of `--users`, that many virtual
callers run at once. Every caller is its own user (`timing-<tag>-<level>-<n>`), so no caller waits behind another's
per-user lock, and every call gets a fresh message id, so the per-answer cap never applies. Each caller first makes
`--warmup` untimed calls (the figures are warm ones); then the callers share the set's texts, `--repeat` times over,
one call at a time each, so each user's history grows during the level (the report records its rows before and
after). The heavy user is then timed alone at 1 caller: the guard-load split. Every search is a stateless JSON-RPC
tools/call with no `law` argument (the whole library is searched) and `limit` 5, in the form of tests/mcp.py.

Every response is checked: an article list or the not-found text is a timed search; anything else (a cap or
suspension refusal, another fixed reply, a tool or protocol error) is counted apart, and the run fails unless that
count is 0. The server's span lines (`--spans`) are joined by message id: lock wait, pool wait, guard-settings
load, budget, search, guard, log, `other` (the server total less those spans), and transport (client total less
server total). The report is written before any failure exits.

`--field fused` joins each item's query and question: a two-form stand-in for REQ-RAG-021's «2-to-3-form fused
queries», labelled as such in the report.
"""

import argparse
import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from psycopg import AsyncConnection

from legal_search import db
from legal_search.evalset import EvalSet, parse_evalset
from legal_search.guard_settings import GuardSettings, validate
from legal_search.tools import NOT_FOUND_SEARCH

LABEL = 'substitute, not launch-class'
FIELDS = ('query', 'question', 'fused')
FUSED_NOTE = "query and question joined: a two-form stand-in for REQ-RAG-021's 2-to-3-form fused queries"
LIMIT = 5
STAFF, REASON = 'timing', 'timing stack'
# A run tag goes into user ids, which the server accepts only as plain ids (server.PLAIN_ID).
TAG = re.compile('[A-Za-z0-9_-]*')
WARMUP_NOTE = ('untimed calls by each caller before each level and before the heavy run, so the figures are warm '
               "ones, as the spec's bench rows are; their log rows count in the caller's history")
# What each derived split holds besides its name (tools.search_law and server.serialised).
SPLITS_NOTE = {
    'transport': ('client total less server_ms; server_ms starts inside the search_law tool, so transport also holds '
                  "the secret check, the MCP SDK's per-request session and JSON-RPC handling, argument validation, the "
                  'caller identity read and the span-line append, besides the network'),
    'other': ('server_ms less its spans: BEGIN, the advisory lock statement, the suspension check, the second budget '
              'read, formatting the answer, the COMMIT of the outer transaction and the alert hand-off'),
    'budget': "the first of the call's two budget reads only (two statements); the second is in other",
    'log': "the log row and the guard's flag change (_record, a savepoint); the outer transaction's COMMIT is in other",
}
# The caps and every detector threshold, raised so that no timed call is refused or throttled (each pair stays
# suspected < proven, and throttle_daily_cap < daily, as guard_settings.validate requires). max_results stays the
# number of articles a search returns; run_gap and run_window_hours keep their values, so the look-back the guard
# loads stays 8 days.
RAISED = {
    'per_answer': 1_000_000,
    'daily': 1_000_000,
    'throttle_daily_cap': 999_999,
    'suspected_run': 999_999,
    'proven_run': 1_000_000,
    'suspected_distinct_7d': 999_999,
    'proven_distinct_7d': 1_000_000,
    'suspected_cap_days': 1_000_000,
}
SPAN_NAMES = ('lock_wait', 'pool_wait', 'guard_settings', 'budget', 'search', 'guard', 'log')
TIMED = ('served', 'not_found')
# Seeded rows: search_law calls that served 5 articles each, spread over the look-back less an hour of margin.
HEAVY_SPAN_SECONDS = 8 * 86_400 - 3_600
_SEEDED = "SELECT count(*) FROM retrieval_log WHERE user_id = %s AND message_id LIKE 'timing-seed-%%'"
_SEED = """
INSERT INTO retrieval_log (user_id, message_id, tool, article_ids, outcome, created_at)
SELECT %(user)s, 'timing-seed-' || n, 'search_law',
       ARRAY(SELECT a.ids[1 + ((n * 5 + j) %% cardinality(a.ids))] FROM generate_series(0, 4) AS j),
       'served', now() - make_interval(secs => n * %(step)s)
FROM generate_series(1, %(rows)s) AS n, (SELECT array_agg(id ORDER BY id) AS ids FROM articles) AS a
"""
_IN_WINDOW = "SELECT count(*) FROM retrieval_log WHERE user_id = %s AND created_at > now() - interval '8 days'"
_ROWS_OF = 'SELECT count(*) FROM retrieval_log WHERE user_id = ANY (%s)'


def run_tag(field: str) -> str:
    """A fresh tag for one run: its field and 6 random hex digits."""
    return f'{field}-{uuid.uuid4().hex[:6]}'


def _prefix(tag: str) -> str:
    return f'timing-{tag}-' if tag else 'timing-'


def callers(tag: str, level: int) -> list[str]:
    """The users of one level of the run tagged `tag`: one per virtual caller."""
    return [f'{_prefix(tag)}{level}-{n}' for n in range(1, level + 1)]


def heavy_user(tag: str) -> str:
    """The run's seeded heavy user."""
    return f'{_prefix(tag)}heavy'


def heavy_seed_note(rows: int, daily: int = GuardSettings().daily) -> str:
    searches = daily // LIMIT
    return (f'a stress bound, not a typical user: {rows} rows. Under the default daily cap of {daily} articles, a user '
            f'served {LIMIT} articles a search gets about {searches} searches a day, about {8 * searches} rows in 8 '
            'days; searches that serve fewer articles and refused calls are logged too, and only those take a real '
            'user to this count')


def percentiles(values: list[float]) -> dict:
    """Nearest-rank p50, p95 and p99 (the value at rank ceil(p/100 * n) of the sorted values), the maximum and n."""
    ordered = sorted(values)
    n = len(ordered)

    def rank(p: int) -> float | None:
        return ordered[-(-p * n // 100) - 1] if n else None

    return {'p50': rank(50), 'p95': rank(95), 'p99': rank(99), 'max': ordered[-1] if n else None, 'n': n}


def reply_text(status: int, body: str) -> tuple[bool, str]:
    """(ok, text) of one tools/call response: ok only for HTTP 200 with a JSON-RPC result that is not a tool error.
    Stateless streamable HTTP answers with one server-sent event or with plain JSON (as tests/mcp.py reads it)."""
    if status != 200:
        return False, body[:120]
    data = [line[5:].strip() for line in body.splitlines() if line.startswith('data:')]
    try:
        message = json.loads(data[-1] if data else body)
    except ValueError:
        return False, body[:120]
    result = message.get('result') if isinstance(message, dict) else None
    if not isinstance(result, dict):
        return False, json.dumps(message.get('error') if isinstance(message, dict) else message, ensure_ascii=False)[:120]
    text = ''.join(part.get('text', '') for part in result.get('content') or [] if isinstance(part, dict))
    return not result.get('isError'), text


def outcome(status: int, body: str) -> str:
    """'served' for an article list, 'not_found' for the not-found text (both are timed searches); 'refused' for
    anything else: a cap or suspension refusal, another fixed reply, a tool or protocol error."""
    ok, text = reply_text(status, body)
    if ok and text == NOT_FOUND_SEARCH:
        return 'not_found'
    if ok and text.startswith('[1] '):
        return 'served'
    return 'refused'


@dataclass(frozen=True)
class Call:
    message: str
    client_ms: float
    outcome: str


def tally(calls: list[Call], lines: dict[str, dict] | None = None) -> dict:
    """Counts and client percentiles over the timed searches only; with the server's span lines (by message id),
    the server total, each span, `other` (the server total less its spans) and transport (client less server)."""
    timed = [call for call in calls if call.outcome in TIMED]
    out = {
        'calls': len(calls),
        'timed': len(timed),
        'not_found': sum(call.outcome == 'not_found' for call in calls),
        'refused': sum(call.outcome not in TIMED for call in calls),
        'client_ms': percentiles([call.client_ms for call in timed]),
    }
    if lines is None:
        return out
    joined = [(call, lines[call.message]) for call in timed if call.message in lines]
    names = list(SPAN_NAMES) + sorted({name for _, line in joined for name, _ in line['spans']} - set(SPAN_NAMES))
    out.update({
        'joined': len(joined),
        'unjoined': len(timed) - len(joined),
        'server_ms': percentiles([line['server_ms'] for _, line in joined]),
        'transport_ms': percentiles([call.client_ms - line['server_ms'] for call, line in joined]),
        'spans_ms': {
            **{name: percentiles([sum(ms for got, ms in line['spans'] if got == name)
                                  for _, line in joined if any(got == name for got, _ in line['spans'])])
               for name in names},
            'other': percentiles([line['server_ms'] - sum(ms for _, ms in line['spans']) for _, line in joined]),
        },
    })
    return out


def _runs(report: dict) -> list[tuple[str, dict]]:
    runs = [(f'{level["users"]} caller(s)', level) for level in report.get('levels', [])]
    if report.get('heavy'):
        runs.append((f'heavy user {report["heavy"]["user_names"]}', report['heavy']))
    return runs


def require_no_refusals(report: dict) -> None:
    """SystemExit naming every run that had a call that was not a timed search."""
    refused = [f'{name}: {run["refused"]} refused' for name, run in _runs(report) if run['refused']]
    if refused:
        raise SystemExit('legal-search-timing: FAIL, not every call was a timed search: ' + '; '.join(refused))


def require_joined(report: dict) -> None:
    """SystemExit naming every run with a timed call that has no server span line."""
    unjoined = [f'{name}: {run["unjoined"]} without a span line' for name, run in _runs(report) if run.get('unjoined')]
    if unjoined:
        raise SystemExit('legal-search-timing: FAIL, ' + '; '.join(unjoined))


def texts(evalset: EvalSet, field: str) -> list[str]:
    """Each item's searched text, in set order."""
    if field == 'fused':
        return [f'{item.query} {item.question}' for item in evalset.items]
    return [getattr(item, field) for item in evalset.items]


def read_span_lines(path: Path) -> dict[str, dict]:
    """The server's span lines by message id (a message id is fresh per call); none when the file is missing, so
    every timed call counts as unjoined and the run fails after its report is written."""
    lines: dict[str, dict] = {}
    if not path.exists():
        return lines
    for raw in path.read_text(encoding='utf-8').splitlines():
        if raw.strip():
            line = json.loads(raw)
            lines[line['message']] = line
    return lines


@dataclass(frozen=True)
class Target:
    url: str
    secret: str


async def _call(client, target: Target, user: str, text: str, samples: list[dict]) -> Call:
    message = uuid.uuid4().hex
    started = time.perf_counter()
    try:
        response = await client.post(
            target.url,
            headers={'x-iqraa-secret': target.secret, 'x-iqraa-user': user, 'x-iqraa-message': message,
                     'accept': 'application/json, text/event-stream'},
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                  'params': {'name': 'search_law', 'arguments': {'query': text, 'limit': LIMIT}}},
        )
        status, body = response.status_code, response.text
    except httpx.HTTPError as error:
        status, body = 0, f'{type(error).__name__}: {error}'
    call = Call(message, (time.perf_counter() - started) * 1000.0, outcome(status, body))
    if call.outcome not in TIMED and len(samples) < 5:
        samples.append({'user': user, 'status': status, 'reply': reply_text(status, body)[1][:120]})
    return call


async def _run(client, target: Target, users: list[str], work: list[str], warmup: int,
               samples: list[dict]) -> tuple[list[Call], list[Call]]:
    """Untimed warm-up calls by every caller, then the timed calls: the callers share `work`, one call at a time each."""
    async def warm(user: str) -> list[Call]:
        return [await _call(client, target, user, text, samples) for text in work[:warmup]]

    queue: asyncio.Queue[str] = asyncio.Queue()
    for text in work:
        queue.put_nowait(text)

    async def timed(user: str) -> list[Call]:
        calls = []
        while not queue.empty():
            calls.append(await _call(client, target, user, queue.get_nowait(), samples))
        return calls

    warmed = [call for calls in await asyncio.gather(*(warm(user) for user in users)) for call in calls]
    done = [call for calls in await asyncio.gather(*(timed(user) for user in users)) for call in calls]
    return warmed, done


async def _wait_ready(client, base: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if (await client.get(f'{base}/health')).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            raise SystemExit(f'legal-search-timing: {base}/health did not answer 200 within {timeout:.0f} s')
        await asyncio.sleep(1)


async def _raise_guard_settings(client, base: str, secret: str) -> dict:
    validate({**GuardSettings().as_dict(), **RAISED})  # fail here, before the stack is used, on a bad raise
    response = await client.put(f'{base}/admin/guard-settings',
                                headers={'x-iqraa-secret': secret, 'x-iqraa-staff': STAFF},
                                json={'settings': RAISED, 'reason': REASON})
    if response.status_code != 200:
        raise SystemExit(f'legal-search-timing: raising the guard settings failed: {response.status_code} {response.text[:200]}')
    return response.json()['settings']


async def _seed_heavy_user(conninfo: str, user: str, rows: int) -> dict:
    async with await AsyncConnection.connect(conninfo, autocommit=True) as conn:
        seeded = (await (await conn.execute(_SEEDED, (user,))).fetchone())[0]
        if seeded == 0 and rows > 0:
            await conn.execute(_SEED, {'user': user, 'rows': rows, 'step': HEAVY_SPAN_SECONDS / rows})
            seeded = rows
    return {'user': user, 'seeded_rows': seeded, 'outcome': 'served', 'articles_per_row': LIMIT,
            'spread_seconds': HEAVY_SPAN_SECONDS, 'spacing_seconds': HEAVY_SPAN_SECONDS / seeded if seeded else None,
            'note': heavy_seed_note(seeded)}


async def _count(conninfo: str, query: str, value: object) -> int:
    async with await AsyncConnection.connect(conninfo, autocommit=True) as conn:
        return (await (await conn.execute(query, (value,))).fetchone())[0]


def _users(spec: str) -> list[int]:
    try:
        levels = [int(part) for part in spec.split(',') if part.strip()]
    except ValueError as error:
        raise argparse.ArgumentTypeError(f'--users takes whole numbers separated by commas, not {spec!r}') from error
    if not levels or any(level < 1 for level in levels):
        raise argparse.ArgumentTypeError(f'--users takes positive whole numbers, not {spec!r}')
    return levels


def _tag(value: str) -> str:
    if not TAG.fullmatch(value):
        raise argparse.ArgumentTypeError(f'--run-tag takes letters, digits, _ and - only, not {value!r}')
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='legal-search-timing', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default='http://legal-search:8000/mcp', help="the server's MCP endpoint")
    parser.add_argument('--secret-file', type=Path, required=True, help="the server's shared secret (the timing stack's)")
    parser.add_argument('--set', dest='evalset', type=Path, default=Path('/content/eval/retrieval-v1.jsonl'))
    parser.add_argument('--field', choices=FIELDS, default='query', help='the item text searched')
    parser.add_argument('--users', type=_users, default=[1, 5, 20], help='concurrency levels, e.g. 1,5,20')
    parser.add_argument('--repeat', type=int, default=5, help='passes over the set at each level')
    parser.add_argument('--warmup', type=int, default=1, help='untimed calls per caller before each level')
    parser.add_argument('--heavy-rows', type=int, default=10_000,
                        help="back-dated retrieval_log rows seeded for the run's heavy user (0: no guard-load split)")
    parser.add_argument('--run-tag', type=_tag,
                        help="the run's tag in its user names (default: the field and 6 random hex digits; "
                             "'' gives the plan's timing-<level>-<n> and timing-heavy)")
    parser.add_argument('--spans', type=Path, help="the server's span file (LEGAL_SEARCH_TIMING_FILE), read-only")
    parser.add_argument('--ready-timeout', type=float, default=300.0, help='seconds to wait for /health')
    parser.add_argument('--out', type=Path, required=True, help='the timing JSON to write')
    return parser


def render(report: dict) -> str:
    def cell(stats: dict | None) -> str:
        if not stats or not stats['n']:
            return '-'
        return '/'.join(f'{stats[p]:.1f}' for p in ('p50', 'p95', 'p99'))

    head = (f"legal-search-timing ({report['label']}): field {report['field']}, run tag {report['run_tag']!r}, "
            f"{report['set']['items']} items x {report['repeat']}, p50/p95/p99 ms")
    rows = [head]
    for name, run in _runs(report):
        spans_ms = run.get('spans_ms', {})
        parts = [f"client {cell(run['client_ms'])}"]
        if 'server_ms' in run:
            parts += [f"server {cell(run['server_ms'])}", f"transport {cell(run['transport_ms'])}"]
            parts += [f'{span} {cell(spans_ms.get(span))}' for span in (*SPAN_NAMES, 'other')]
        rows.append(f"{name}: timed {run['timed']} (not found {run['not_found']}), refused {run['refused']}; " + ', '.join(parts))
    return '\n'.join(rows)


async def _measure(args: argparse.Namespace, evalset: EvalSet, secret: str) -> dict:
    target = Target(args.url, secret)
    base = str(httpx.URL(args.url).join('/')).rstrip('/')
    conninfo = db.database_url()
    work = texts(evalset, args.field) * args.repeat
    tag = run_tag(args.field) if args.run_tag is None else args.run_tag
    samples: list[dict] = []
    report: dict = {
        'tool': 'legal-search-timing', 'label': LABEL, 'requirement': 'REQ-RAG-021',
        'set': {'name': evalset.name, 'sha256': evalset.sha256, 'items': len(evalset.items)},
        'field': args.field, 'field_note': FUSED_NOTE if args.field == 'fused' else None,
        'law': None, 'law_note': 'no law argument: every search covers the whole library', 'limit': LIMIT,
        'run_tag': tag, 'repeat': args.repeat, 'warmup_per_caller': args.warmup, 'warmup_note': WARMUP_NOTE,
        'splits_note': SPLITS_NOTE,
        'spans_file': str(args.spans) if args.spans else None,
        'started_at': datetime.now(UTC).isoformat(timespec='seconds'),
    }
    limits = httpx.Limits(max_connections=max(args.users) + 5, max_keepalive_connections=max(args.users) + 5)
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0), limits=limits) as client:
        await _wait_ready(client, base, args.ready_timeout)
        report['guard_settings'] = await _raise_guard_settings(client, base, secret)
        report['guard_settings_change'] = {'who': STAFF, 'why': REASON, 'raised': sorted(RAISED)}
        if args.heavy_rows > 0:
            report['heavy_seed'] = await _seed_heavy_user(conninfo, heavy_user(tag), args.heavy_rows)
        levels: list[tuple[dict, list[Call]]] = []
        for level in args.users:
            users = callers(tag, level)
            prior = await _count(conninfo, _ROWS_OF, users)
            warmed, done = await _run(client, target, users, work, args.warmup, samples)
            levels.append(({'users': level, 'user_names': f'{users[0]}..{users[-1]}', 'prior_rows': prior,
                            'rows_after': await _count(conninfo, _ROWS_OF, users),
                            'warmup_refused': sum(call.outcome not in TIMED for call in warmed)}, done))
        heavy = None
        if args.heavy_rows > 0:
            user = heavy_user(tag)
            in_window = await _count(conninfo, _IN_WINDOW, user)
            warmed, done = await _run(client, target, [user], work, args.warmup, samples)
            heavy = ({'users': 1, 'user_names': user, 'rows_in_window_before': in_window,
                      'rows_in_window_after': await _count(conninfo, _IN_WINDOW, user),
                      'warmup_refused': sum(call.outcome not in TIMED for call in warmed)}, done)
    lines = read_span_lines(args.spans) if args.spans else None
    report['levels'] = [{**meta, **tally(done, lines)} for meta, done in levels]
    if heavy is not None:
        report['heavy'] = {**heavy[0], **tally(heavy[1], lines)}
    report['refusal_samples'] = samples
    report['ended_at'] = datetime.now(UTC).isoformat(timespec='seconds')
    return report


def main() -> None:
    args = _parser().parse_args()
    if args.repeat < 1 or args.warmup < 0 or args.heavy_rows < 0:
        raise SystemExit('legal-search-timing: --repeat must be at least 1, --warmup and --heavy-rows at least 0')
    evalset = parse_evalset(args.evalset.read_text(encoding='utf-8'))
    secret = args.secret_file.read_text(encoding='utf-8').strip()
    report = asyncio.run(_measure(args, evalset, secret))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(render(report))
    print(f'wrote {args.out}')
    warm_refused = [run for _, run in _runs(report) if run.get('warmup_refused')]
    if warm_refused:
        raise SystemExit('legal-search-timing: FAIL, a warm-up call was refused')
    require_no_refusals(report)
    if args.spans:
        require_joined(report)


if __name__ == '__main__':
    main()
