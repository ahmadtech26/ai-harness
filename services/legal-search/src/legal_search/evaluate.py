"""legal-search-eval: the retrieval evaluation set's checks (the runner is added by plan B chunk 2).

    legal-search-eval check     # the set against the registry corpus: schema, keys, notes, copying, coverage

Paths default to the test stack's mounts (/content, /corpus).
"""

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from legal_search.corrections import CorrectionError, load_corrections
from legal_search.evalset import EvalSet, EvalSetError, corpus_problems, coverage, coverage_problems, parse_evalset
from legal_search.ingest import IngestError, Prepared, prepare
from legal_search.memorandum import MemorandumError, load_memorandum, load_memorandum_corrections
from legal_search.registry import RegistryError, load_registry

ERRORS = (EvalSetError, IngestError, RegistryError, CorrectionError, MemorandumError, OSError)


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='legal-search-eval', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--set', dest='evalset', type=Path, default=Path('/content/eval/retrieval-v1.jsonl'))
    parser.add_argument('--registry', type=Path, default=Path('/content/corpus/laws.json'))
    parser.add_argument('--corrections', type=Path, default=Path('/content/corpus/corrections.json'))
    parser.add_argument('--corpus', type=Path, default=Path(os.environ.get('CORPUS_DIR', '/corpus')))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check', help='check the set against the corpus (no database)')
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == 'check':
            _check(_sources(args))
    except ERRORS as error:
        raise SystemExit(f'legal-search-eval: {error}') from error


if __name__ == '__main__':
    main()
