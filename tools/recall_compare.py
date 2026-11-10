"""Compare retrieval runs item by item: list parity, rescued/kept/lost, served-set recall (recall plan, Task 1.4).

    recall_compare.py parity --candidate SRC --reference SRC [--k 10]
        -> "identical N/M"; for each differing item: id, first differing rank, both keys. Exit 0 only when N == M.
    recall_compare.py items --candidate SRC --reference SRC [--a0 SRC] [--split split.json] [--half-b all|none]
        -> per half (all/A/B): recall@5, MRR, hit@5, per-law floor; rescued/kept/lost by hit@5 against the reference
           (and against A0); items up/down by recall@5, by name; paired bootstrap of candidate minus reference.
    recall_compare.py served --first SRC --second SRC [--slots 8] [--first-k 5] [--skip-served] [--split split.json]
        -> served-set recall: the top first-k of FIRST, then the next (slots - first-k) of SECOND (skipping the keys
           already served with --skip-served), against the control, the top `slots` of FIRST; by half; bootstrap of
           the difference.
    Every subcommand also takes --ls-src DIR and --basis README.md; items and served take --evalset eval.jsonl.

SRC is `eval:<eval-L.json>` (a `legal-search-eval run` report) or `rows:<rows.jsonl>#<cfg>` (the bench's rows,
{"cfg", "id", "ranked"} per line). Quote a rows: source in the shell: a cfg holds `|`. Git Bash does not convert a
/d/... path inside a source, so on Windows a leading /<drive>/ is read as <DRIVE>:/.
- Two runs compare only on the same set and corpus: a difference in set_sha256 or corpus_sha256 is refused (spec :526).
  An eval: report that names neither is refused. A rows: source takes both values from its basis README (--basis,
  default README.md beside the rows file); a rows: source with no such file is refused, since its inputs could not be
  checked. A run with no items is refused. The corpus, set and index digests of every source are printed, with an
  eval: run's label and use_law_filter.
- A rows: source takes each item's expected articles and law from --evalset (the bench's eval.jsonl, `expected` and
  `scored_law`); without it, from the eval: source it is compared with. Expected articles that disagree are refused.
- The metrics are legal_search.metrics' own (spec :526): from --ls-src, by default services/legal-search/src beside
  this folder when it exists, else the installed package (the eval image, where tools/gates.sh runs the tests).
- Halves come from --split; without it there is one block over every item and no bootstrap, which resamples in
  split.json key order. The bootstrap is the bench's (rag-bench py/report.py bootstrap(): seed 20261106, 10,000
  resamples); an interval end within 1e-9 of zero is read as zero.
- --half-b none prints half A only: no half-B line and no figure or item name over every item, since half B equals
  twice the whole set minus half A (recall plan §3). There is no asymmetric mode.
Host: python -X utf8 -I -B tools/recall_compare.py ...  (stdlib only; Python 3.11 or later)
"""

import argparse
import importlib
import json
import os
import random
import re
import sys
from pathlib import Path

LS_SRC = Path(__file__).resolve().parents[1] / 'services' / 'legal-search' / 'src'
WINDOWS = os.name == 'nt'  # where Git Bash hands /d/... over unconverted inside a source (plan §0)
SAME_INPUTS = ('set_sha256', 'corpus_sha256')  # as tools/release_eval.py: runs on another set or corpus do not compare
DIGESTS = ('corpus_sha256', 'set_sha256', 'index_sha256')
HALVES = ('all', 'A', 'B')
SEED, RESAMPLES, ZERO = 20261106, 10000, 1e-9
NO_SPLIT = 'not computed (it resamples in split.json key order: pass --split)'

_metrics = None


def metrics(ls_src: Path | None = None):
    """legal_search.metrics, imported once: from ls_src (default LS_SRC) when that folder exists, else installed."""
    global _metrics
    if _metrics is None:
        src = ls_src or LS_SRC
        if src.is_dir() and str(src) not in sys.path:
            sys.path.insert(0, str(src))
        _metrics = importlib.import_module('legal_search.metrics')
    return _metrics


def _parts(source: str) -> tuple[str, Path, str | None]:
    kind, colon, rest = source.partition(':')
    cfg = None
    if kind == 'rows':
        rest, hash_, cfg = rest.rpartition('#')
        if not hash_ or not cfg:
            raise SystemExit(f'refused: a rows: source names its config after #: {source!r}')
    if kind not in ('eval', 'rows') or not colon or not rest:
        raise SystemExit(f'refused: a source is eval:<report.json> or rows:<rows.jsonl>#<cfg>: {source!r}')
    drive = re.match(r'/([A-Za-z])/', rest)
    if WINDOWS and drive:
        rest = f'{drive.group(1).upper()}:/{rest[3:]}'
    return kind, Path(rest), cfg


def source_path(source: str) -> Path:
    return _parts(source)[1]


def _key(key) -> tuple[str, int, str]:
    law, number, suffix = key
    return str(law), int(number), str(suffix)


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _basis_run(readme: Path) -> dict:
    text = readme.read_text(encoding='utf-8')
    run = {'basis': str(readme)}
    for field in SAME_INPUTS:
        values = set(re.findall(rf'\b{field}\W+([0-9a-f]{{64}})\b', text))
        if len(values) != 1:
            raise SystemExit(f'refused: the basis README {readme} names {len(values)} values of {field}, not one')
        run[field] = values.pop()
    return run


def load(source: str, evalset: Path | None = None, basis: Path | None = None) -> dict:
    """{'source', 'kind', 'run': the report's run, or for rows: the basis README's digests, 'items': {id: item}},
    where an item is {'law', 'expected': frozenset of keys or None, 'ranked': tuple of keys}."""
    kind, path, cfg = _parts(source)
    items: dict[str, dict] = {}
    if kind == 'eval':
        report = json.loads(path.read_text(encoding='utf-8'))
        run, rows = report['run'], report['items']
        for field in SAME_INPUTS:
            if not run.get(field):
                raise SystemExit(f'refused: {source} names no {field}, so it cannot be checked against another run')
    else:
        rows = [row for row in _lines(path) if row.get('cfg') == cfg]
        if not rows:
            raise SystemExit(f'refused: no line of {path} has cfg {cfg!r}')
        readme = basis or path.parent / 'README.md'
        if not readme.is_file():
            raise SystemExit(f'refused: {source} has no basis README at {readme}, so its set and corpus cannot be '
                             'checked: pass --basis <the README.md that names them>')
        run = _basis_run(readme)
    if not rows:
        raise SystemExit(f'refused: {source} holds no items')
    for row in rows:
        if row['id'] in items:
            raise SystemExit(f'refused: {source} has item {row["id"]} twice')
        expected = frozenset(map(_key, row['expected'])) if 'expected' in row else None
        items[row['id']] = {'law': row.get('law'), 'expected': expected, 'ranked': tuple(map(_key, row['ranked']))}
    if kind == 'rows' and evalset is not None:
        truth = {row['id']: row for row in _lines(evalset)}
        if set(truth) != set(items):
            raise SystemExit(f'refused: {source} and {evalset} hold different items')
        for item_id, item in items.items():
            item['law'] = truth[item_id]['scored_law']
            item['expected'] = frozenset(map(_key, truth[item_id]['expected']))
    return {'source': source, 'kind': kind, 'run': run, 'items': items}


def same_inputs(*runs: dict) -> None:
    """Refuse runs that differ in set or corpus, or in item ids; borrow expected articles where a run has none."""
    for field in SAME_INPUTS:
        if len({run['run'][field] for run in runs}) > 1:
            raise SystemExit(f'refused: the runs differ in {field}: '
                             + '; '.join(f'{run["source"]} {run["run"][field]}' for run in runs))
    ids = set(runs[0]['items'])
    for run in runs[1:]:
        if set(run['items']) != ids:
            raise SystemExit(f'refused: {runs[0]["source"]} and {run["source"]} hold different items')
    known = [run for run in runs if all(item['expected'] is not None for item in run['items'].values())]
    for item_id in ids:
        if len({run['items'][item_id]['expected'] for run in known}) > 1:
            raise SystemExit(f'refused: the runs expect different articles for {item_id}')
    for run in runs:
        for item_id, item in run['items'].items():
            if item['expected'] is None and known:
                source = known[0]['items'][item_id]
                item['law'], item['expected'] = source['law'], source['expected']


def _need_expected(*runs: dict) -> None:
    for run in runs:
        if any(item['expected'] is None for item in run['items'].values()):
            raise SystemExit(f'refused: {run["source"]} has no expected articles: pass --evalset')


def parity(cand: dict, ref: dict, k: int = 10) -> tuple[int, list[dict]]:
    """(items whose top k equal the reference's in order, the others with their first differing rank and keys)."""
    same_inputs(cand, ref)
    identical, diffs = 0, []
    for item_id in sorted(cand['items']):
        a, b = cand['items'][item_id]['ranked'][:k], ref['items'][item_id]['ranked'][:k]
        if a == b:
            identical += 1
            continue
        rank = next((n for n, (x, y) in enumerate(zip(a, b), 1) if x != y), min(len(a), len(b)) + 1)
        diffs.append({'id': item_id, 'rank': rank, 'candidate': a[rank - 1] if rank <= len(a) else None,
                      'reference': b[rank - 1] if rank <= len(b) else None})
    return identical, diffs


def bootstrap(d: list[float], n: int = RESAMPLES, seed: int = SEED) -> tuple[float, float, float] | None:
    """(mean, 2.5% end, 97.5% end) of a paired difference list: the bench's bootstrap(), ends within 1e-9 read as 0."""
    if not d:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(n))
    lo, hi = means[int(0.025 * n)], means[int(0.975 * n) - 1]
    return sum(d) / len(d), 0.0 if abs(lo) < ZERO else lo, 0.0 if abs(hi) < ZERO else hi


def _scores(run: dict) -> dict[str, dict[str, float]]:
    if 'scores' not in run:
        m = metrics()
        run['scores'] = {item_id: m.item_metrics(m.Scored(item['law'], item['expected'], item['ranked']))
                         for item_id, item in run['items'].items()}
    return run['scores']


def _order(runs: tuple[dict, ...], split_path: Path | None) -> tuple[list[str], dict[str, str] | None]:
    ids = set(runs[0]['items'])
    if split_path is None:
        return sorted(ids), None
    split = json.loads(Path(split_path).read_text(encoding='utf-8'))
    if ids - set(split):
        raise SystemExit(f'refused: {len(ids - set(split))} items are not in {split_path}')
    return [item_id for item_id in split if item_id in ids], split


def _figures(run: dict, ids: list[str]) -> dict:
    m = metrics()
    scored = [m.Scored(run['items'][i]['law'], run['items'][i]['expected'], run['items'][i]['ranked']) for i in ids]
    summary = m.summarise(scored)
    law, row = min(summary['per_law'].items(), key=lambda entry: (entry[1]['recall@5'], entry[0]))
    below = sum(1 for row_ in summary['per_law'].values() if row_['recall@5'] < 0.6)
    return {**{name: summary['overall'][name] for name in ('recall@5', 'mrr', 'hit@5')},
            'floor': {'law': law, 'recall@5': row['recall@5'], 'laws_below_0.60': below}}


def _versus(cand: dict, ref: dict, ids: list[str], ordered: bool) -> dict:
    c, r = _scores(cand), _scores(ref)
    out = {'rescued': [i for i in ids if c[i]['hit@5'] == 1.0 and r[i]['hit@5'] != 1.0],
           'kept': [i for i in ids if c[i]['hit@5'] == 1.0 and r[i]['hit@5'] == 1.0],
           'lost': [i for i in ids if c[i]['hit@5'] != 1.0 and r[i]['hit@5'] == 1.0],
           'up': [i for i in ids if c[i]['recall@5'] > r[i]['recall@5']],
           'down': [i for i in ids if c[i]['recall@5'] < r[i]['recall@5']]}
    out['boot'] = {name: bootstrap([c[i][name] - r[i][name] for i in ids]) if ordered else None
                   for name in ('recall@5', 'mrr')}
    return out


def items(cand: dict, ref: dict, split_path: Path | None = None, a0: dict | None = None,
          halves: tuple[str, ...] = HALVES) -> dict:
    """{half: {'n', 'candidate', 'reference'[, 'a0'], rescued/kept/lost/up/down/boot against the reference
    [, 'vs_a0': the same against A0]}}, item ids in split.json key order. Without a split: one block, 'all'."""
    runs = (cand, ref) + ((a0,) if a0 else ())
    same_inputs(*runs)
    _need_expected(*runs)
    order, split = _order(runs, split_path)
    out = {}
    for half in (halves if split else ('all',)):
        ids = [i for i in order if half == 'all' or split[i] == half]
        if not ids:
            continue
        block = {'n': len(ids), 'candidate': _figures(cand, ids), 'reference': _figures(ref, ids),
                 **_versus(cand, ref, ids, split is not None)}
        if a0:
            block['a0'] = _figures(a0, ids)
            block['vs_a0'] = _versus(cand, a0, ids, split is not None)
        out[half] = block
    return out


def _interval(boot: tuple[float, float, float] | None) -> str:
    return 'n/a' if boot is None else f'{boot[0]:+.4f} [{boot[1]:+.4f}, {boot[2]:+.4f}]'


def _names(ids: list[str]) -> str:
    return ' '.join(ids) or '-'


def _title(half: str, n: int) -> str:
    """'== all (80 items)', '== half A (40 items)': `all` stands as a word, so a check for it can find it."""
    return f'== {"all" if half == "all" else f"half {half}"} ({n} items)'


def _versus_lines(name: str, v: dict) -> list[str]:
    boot = v['boot']
    lines = [f'   vs {name}: rescued {len(v["rescued"])}, kept {len(v["kept"])}, lost {len(v["lost"])} (by hit@5); '
             f'recall@5 up {len(v["up"])}, down {len(v["down"])}',
             f'      rescued: {_names(v["rescued"])}', f'      kept:    {_names(v["kept"])}',
             f'      lost:    {_names(v["lost"])}', f'      up:      {_names(v["up"])}',
             f'      down:    {_names(v["down"])}']
    if boot['recall@5'] is None and boot['mrr'] is None:
        lines.append(f'      bootstrap: {NO_SPLIT}')
    else:
        lines.append(f'      bootstrap, candidate minus {name}: recall@5 {_interval(boot["recall@5"])}; '
                     f'MRR {_interval(boot["mrr"])}')
    return lines


def render_items(out: dict, half_b: str = 'all') -> str:
    if half_b not in ('all', 'none'):
        raise ValueError(f'half_b must be all or none, not {half_b!r}')
    lines = []
    for half in (h for h in (HALVES if half_b == 'all' else ('A',)) if h in out):
        block = out[half]
        lines.append(_title(half, block['n']))
        for name in ('candidate', 'reference', 'a0'):
            if name in block:
                f, floor = block[name], block[name]['floor']
                lines.append(f'   {name:<9}  recall@5 {f["recall@5"]:.4f}  MRR {f["mrr"]:.4f}  hit@5 {f["hit@5"]:.4f}  '
                             f'floor {floor["recall@5"]:.2f} {floor["law"]} '
                             f'(laws below 0.60: {floor["laws_below_0.60"]})')
        lines += _versus_lines('reference', block)
        if 'vs_a0' in block:
            lines += _versus_lines('A0', block['vs_a0'])
    return '\n'.join(lines)


def served(first: dict, second: dict, slots: int = 8, first_k: int = 5, skip: bool = False) -> dict[str, float]:
    """{id: served-set recall}: the top first_k of FIRST, then the next slots - first_k of SECOND."""
    same_inputs(first, second)
    _need_expected(first)
    out = {}
    for item_id, item in first['items'].items():
        head = item['ranked'][:first_k]
        rest = tuple(key for key in second['items'][item_id]['ranked'] if not skip or key not in head)
        shown = head + rest[:slots - first_k]
        out[item_id] = metrics().recall_at(item['expected'], shown, len(shown))
    return out


def control(first: dict, slots: int = 8) -> dict[str, float]:
    """{id: recall over the top `slots` of FIRST}: the same number of slots, all from the first wording."""
    return {item_id: metrics().recall_at(item['expected'], item['ranked'], slots)
            for item_id, item in first['items'].items()}


def render_served(first: dict, second: dict, split_path: Path | None, slots: int, first_k: int, skip: bool) -> str:
    got = served(first, second, slots=slots, first_k=first_k, skip=skip)
    base = control(first, slots)
    order, split = _order((first, second), split_path)
    lines = [f'served: top {first_k} of first, then {slots - first_k} of second'
             f'{" skipping repeats" if skip else ""}; control: top {slots} of first']
    for half in (HALVES if split else ('all',)):
        ids = [i for i in order if half == 'all' or split[i] == half]
        if not ids:
            continue
        diff = [got[i] - base[i] for i in ids]
        boot = _interval(bootstrap(diff)) if split else NO_SPLIT
        lines.append(f'{_title(half, len(ids))}: served recall {sum(got[i] for i in ids) / len(ids):.4f}, '
                     f'control {sum(base[i] for i in ids) / len(ids):.4f}; served minus control {boot}; '
                     f'items up {sum(1 for x in diff if x > 0)}, down {sum(1 for x in diff if x < 0)}')
    return '\n'.join(lines)


def _header(role: str, run: dict) -> str:
    """The source, its digests (index_sha256 'n/a' where the run has none) and, for an eval: run, its label and
    use_law_filter, so a run with the law filter set beside one without it shows."""
    info = run['run']
    shown = [f'{d} {info.get(d) or "n/a"}' for d in DIGESTS]
    shown += [f'{field} {json.dumps(info[field])}' for field in ('label', 'use_law_filter') if field in info]
    where = f' (from {info["basis"]})' if 'basis' in info else ''
    return f'{role}: {run["source"]}: ' + ', '.join(shown) + where


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--ls-src', type=Path, help='the legal-search src folder that holds legal_search.metrics')
    common.add_argument('--basis', type=Path, help="a rows: source's basis README (default: README.md beside it)")
    scoring = argparse.ArgumentParser(add_help=False)
    scoring.add_argument('--evalset', type=Path, help="the bench's eval.jsonl: expected articles for rows: sources")
    scoring.add_argument('--split', type=Path, help='split.json: halves A and B, in its key order')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('parity', parents=[common])
    p.add_argument('--candidate', required=True)
    p.add_argument('--reference', required=True)
    p.add_argument('--k', type=int, default=10)
    p = commands.add_parser('items', parents=[common, scoring])
    p.add_argument('--candidate', required=True)
    p.add_argument('--reference', required=True)
    p.add_argument('--a0')
    p.add_argument('--half-b', choices=('all', 'none'), default='all')
    p = commands.add_parser('served', parents=[common, scoring])
    p.add_argument('--first', required=True)
    p.add_argument('--second', required=True)
    p.add_argument('--slots', type=int, default=8)
    p.add_argument('--first-k', type=int, default=5)
    p.add_argument('--skip-served', action='store_true')
    args = parser.parse_args(argv)
    if args.ls_src is not None and not args.ls_src.is_dir():
        parser.error(f'--ls-src {args.ls_src} is not a folder')
    evalset = getattr(args, 'evalset', None)
    if args.command == 'parity':
        if args.k < 1:
            parser.error('--k must be at least 1')
        cand, ref = load(args.candidate, basis=args.basis), load(args.reference, basis=args.basis)
        identical, diffs = parity(cand, ref, k=args.k)
        print('\n'.join((_header('candidate', cand), _header('reference', ref))))
        print(f'identical {identical}/{len(cand["items"])} (top {args.k})')
        show = lambda key: '-' if key is None else json.dumps(list(key), ensure_ascii=False)
        for diff in diffs:
            print(f'  {diff["id"]}: rank {diff["rank"]}: candidate {show(diff["candidate"])}, '
                  f'reference {show(diff["reference"])}')
        return 0 if identical == len(cand['items']) else 1
    module = metrics(args.ls_src)
    if args.command == 'items':
        if args.half_b == 'none' and args.split is None:
            parser.error('--half-b none needs --split')
        cand, ref = load(args.candidate, evalset, args.basis), load(args.reference, evalset, args.basis)
        a0 = load(args.a0, evalset, args.basis) if args.a0 else None
        out = items(cand, ref, args.split, a0=a0, halves=HALVES if args.half_b == 'all' else ('A',))
        heads = [_header('candidate', cand), _header('reference', ref)] + ([_header('A0', a0)] if a0 else [])
        print('\n'.join([*heads, f'metrics: {module.__file__}', render_items(out, half_b=args.half_b)]))
        return 0
    if not 0 <= args.first_k <= args.slots:
        parser.error('--first-k must lie between 0 and --slots')
    first, second = load(args.first, evalset, args.basis), load(args.second, evalset, args.basis)
    text = render_served(first, second, args.split, args.slots, args.first_k, args.skip_served)
    print('\n'.join([_header('first', first), _header('second', second), f'metrics: {module.__file__}', text]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
