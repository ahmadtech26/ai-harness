"""The retrieval evaluation gate of a release: a run may not fall below the committed baseline.

    release_eval.py check --report R --baseline B            # exit 1 on a regression, or on another set or corpus
    release_eval.py write-baseline --report R --baseline B   # keep a run's numbers as the new baseline

R is the eval-<label>.json of `legal-search-eval run`. Runs in the legal-search eval image, where legal_search is
importable. A change that moves the numbers on purpose (retrieval, the set or the corpus) refreshes the baseline:
the eval step of tools/gates.sh prints the folder holding eval-release.json; run write-baseline on it in the same
image with deploy/release mounted writable, and commit deploy/release/eval-baseline.json with the change.
The agreed targets are printed and decide nothing: whether they block a release is the owner's call.
"""

import argparse
import json
from pathlib import Path

from legal_search.metrics import keep_decision, targets_missed

TARGETS = {'recall5': 0.80, 'law_floor': 0.60, 'mrr': 0.60}  # agreed 2026-10-27, P3-results "Agreed targets"
UNCHANGED = 'no change in overall recall@5 or MRR'  # stops a tuning step; a release that changes nothing passes
SAME_INPUTS = ('set_sha256', 'corpus_sha256')  # numbers from another set or corpus do not compare
REFRESH = 'release_eval.py write-baseline --report <report> --baseline <baseline>'


def targets_lines(metrics: dict) -> list[str]:
    missed = targets_missed(metrics, **TARGETS)
    return ['targets: MISSED', *(f'  {line}' for line in missed)] if missed else ['targets: MET']


def check(report: dict, baseline: dict) -> tuple[int, list[str]]:
    """(the exit code, the lines to print). The targets are printed on every path and never change the code."""
    targets = targets_lines(report['metrics'])
    differing = [field for field in SAME_INPUTS if report['run'][field] != baseline['run'][field]]
    if differing:
        return 1, [f'retrieval gate: FAIL, the report and the baseline differ in {" and ".join(differing)}',
                   f'if that change is intended, refresh the baseline from a run on it and commit it: {REFRESH}',
                   *targets]
    _, reasons = keep_decision(baseline['metrics'], report['metrics'])
    regressions = [reason for reason in reasons if reason != UNCHANGED]
    if regressions:
        return 1, ['retrieval gate: FAIL', *(f'  {reason}' for reason in regressions), *targets]
    before, after = baseline['metrics']['overall'], report['metrics']['overall']
    return 0, [f'retrieval gate: PASS, overall recall@5 {before["recall@5"]:.4f} -> {after["recall@5"]:.4f}, '
               f'MRR {before["mrr"]:.4f} -> {after["mrr"]:.4f}',
               *targets]


def baseline_of(report: dict) -> dict:
    return {'run': report['run'], 'metrics': report['metrics']}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('check', 'write-baseline'):
        command = commands.add_parser(name)
        command.add_argument('--report', type=Path, required=True)
        command.add_argument('--baseline', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = _load(args.report)
        if args.command == 'write-baseline':
            text = json.dumps(baseline_of(report), ensure_ascii=False, indent=1, sort_keys=True) + '\n'
            args.baseline.write_text(text, encoding='utf-8')
            print(f'wrote {args.baseline}')
            return 0
        code, lines = check(report, _load(args.baseline))
    except (OSError, ValueError, KeyError, TypeError) as error:  # a gate that cannot compare does not pass
        print(f'retrieval gate: FAIL, cannot compare: {error!r}\nA baseline comes from: {REFRESH}')
        return 1
    print('\n'.join(lines))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
