"""Load one law's statute shards into Postgres.

    legal-search-ingest --law-dir <.../القانون-المدني-الأردني> --law-slug civil-code
"""

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from dataclasses import replace as with_changes
from pathlib import Path

from psycopg import AsyncConnection

from legal_search import db
from legal_search.corpus import Article, parse_law
from legal_search.corrections import Correction, apply_corrections
from legal_search.registry import Law, directory_counts

SHORT_ARTICLE = 15  # characters; shorter articles are reported (often «ملغاة»), never refused


class IngestError(ValueError):
    pass


@dataclass(frozen=True)
class Prepared:
    laws: list[Law]
    articles: dict[str, list[Article]]  # law slug -> articles in file order, corrections applied
    short: list[Article]


def _label(number: int, suffix: str) -> str:
    return f'المادة {number}' + (f' {suffix}' if suffix else '')


def _law_articles(law: Law, corrections: list[Correction], corpus: Path, counts: dict[str, int]) -> list[Article]:
    directory = corpus / law.folder
    if not (directory / 'sections').is_dir():
        raise IngestError(f'{law.slug}: folder not found: {directory}')
    if law.folder not in counts:
        raise IngestError(f'{law.slug}: folder {law.folder} is not listed in law-directory.md')
    parsed = [with_changes(article, law_title=law.title) for article in parse_law(directory, law.slug)]
    articles = apply_corrections(parsed, [c for c in corrections if c.law == law.slug])
    keys = Counter((a.number, a.suffix) for a in articles)
    duplicates = sorted(key for key, n in keys.items() if n > 1)
    if duplicates:
        raise IngestError(f'{law.slug}: duplicate article {_label(*duplicates[0])}')
    present_gaps = [gap for gap in law.known_gaps if (gap.number, gap.suffix) in keys]
    if present_gaps:
        raise IngestError(f'{law.slug}: known gap {_label(present_gaps[0].number, present_gaps[0].suffix)} is present')
    expected = counts[law.folder] - len(law.known_gaps)
    if len(articles) != expected:
        raise IngestError(
            f'{law.slug}: parsed {len(articles)} articles, expected {expected} '
            f'(directory {counts[law.folder]} minus {len(law.known_gaps)} known gaps)'
        )
    return articles


def prepare(laws: list[Law], corrections: list[Correction], corpus: Path) -> Prepared:
    """Parse, correct and check every law before anything is written; raises IngestError on any defect."""
    unknown = sorted({c.law for c in corrections} - {law.slug for law in laws})
    if unknown:
        raise IngestError(f'corrections name laws not in the registry: {", ".join(unknown)}')
    counts = directory_counts(corpus / 'law-directory.md')
    articles = {law.slug: _law_articles(law, corrections, corpus, counts) for law in laws}
    short = [a for law_articles in articles.values() for a in law_articles if len(a.text) < SHORT_ARTICLE]
    return Prepared(laws, articles, short)


async def ingest(conninfo: str, law_dir: Path, law_slug: str) -> int:
    articles = parse_law(law_dir, law_slug)
    if not articles:
        raise SystemExit(f'no articles found under {law_dir}')
    async with await AsyncConnection.connect(conninfo) as conn:
        await db.create_schema(conn)
        async with conn.transaction():
            return await db.upsert_articles(conn, articles)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--law-dir', type=Path, required=True)
    parser.add_argument('--law-slug', required=True)
    args = parser.parse_args()
    count = asyncio.run(ingest(db.database_url(), args.law_dir, args.law_slug))
    print(f'ingested {count} articles into {args.law_slug}')


if __name__ == '__main__':
    main()
