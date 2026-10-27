"""corpus-ci: check the law registry and the corrections file (content/corpus) against the corpus folders.

    corpus-ci --content /w/content --corpus /w/jordanian-law/references/القوانين-الأردنية            # staging
    corpus-ci --content /w/content --corpus /w/jordanian-law/references/القوانين-الأردنية --release  # production
"""

import argparse
import json
import sys
from pathlib import Path

from skill_tools import corpus_checks
from skill_tools.checks import Problem


def run(content: Path, corpus: Path, release: bool) -> list[Problem]:
    folder = content / 'corpus'
    registry = json.loads((folder / 'laws.json').read_text(encoding='utf-8'))
    corrections = json.loads((folder / 'corrections.json').read_text(encoding='utf-8'))
    return corpus_checks.check_all(registry, corrections, corpus, release)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--content', type=Path, required=True)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--release', action='store_true', help='require an approved review on every entry and on the corrections')
    args = parser.parse_args(argv)
    problems = run(args.content, args.corpus, args.release)
    for problem in problems:
        print(f'FAIL {problem.skill}: {problem.rule}: {problem.message}')
    if problems:
        sys.exit(1)
    print('corpus-ci: registry and corrections pass' + (' (release)' if args.release else ''))
