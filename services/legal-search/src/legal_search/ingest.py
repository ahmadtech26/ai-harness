r"""Load every law in the registry, and the Civil Code memorandum, into Postgres. Idempotent.

    legal-search-ingest --registry <content/corpus/laws.json> --corrections <content/corpus/corrections.json> \
        --corpus <jordanian-law/references/القوانين-الأردنية> [--check-verification]

Every law is parsed, corrected and checked first (count = law-directory.md minus known gaps; no duplicate
article), and the memorandum's links are read from its own headings with the corrections file's `memorandum`
entries applied; any defect stops the run before anything is written. Then one transaction upserts the laws
and articles, each article with the heading headings.extract reads from its law's text as published (the keyword
engine's heading field, stored with heading_origin 'site'; the text itself is stored unchanged), deletes articles
no longer in the source, sets every article's verification from the records in `verification/` beside the registry
(verification.match: verified only when the record says so for the text being stored; NULL otherwise, also where an
earlier run set it), and replaces the memorandum tables. A record that verifies nothing for another reason than its
result is printed as a verification problem; it never stops the run.

--check-verification writes nothing and needs no database: it parses the laws as the ingest does and checks the records
against the texts (verification.match), printing every problem; it exits 1 if there is any, for instance a verified
record whose text_sha256 is no longer the sha256 of its article's text.
"""

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from dataclasses import replace as with_changes
from pathlib import Path

from psycopg import AsyncConnection

from legal_search import db, verification
from legal_search.corpus import Article, parse_law
from legal_search.corrections import Correction, CorrectionError, apply_corrections, load_corrections
from legal_search.headings import extract as extract_headings
from legal_search.memorandum import Memorandum, MemorandumError, load_memorandum, load_memorandum_corrections
from legal_search.registry import Law, RegistryError, directory_counts, load_registry

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


async def ingest(conninfo: str, registry: Path, corrections: Path,
                 corpus: Path) -> tuple[Prepared, Memorandum, verification.Matched]:
    prepared = prepare(load_registry(registry), load_corrections(corrections), corpus)
    memorandum = load_memorandum(corpus, load_memorandum_corrections(corrections))
    matched = verification.match(prepared.articles, verification.records_dir(registry))
    async with await AsyncConnection.connect(conninfo) as conn:
        await db.create_schema(conn)
        # Commit the schema step at once: `ALTER TABLE … ADD COLUMN IF NOT EXISTS` takes an exclusive lock on
        # retrieval_log and articles even when the column exists, and holding it through the load would stall every
        # tool call of a running service. The load below is then one real transaction (not a savepoint).
        await conn.commit()
        async with conn.transaction():
            await db.upsert_laws(conn, prepared.laws)
            for slug, articles in prepared.articles.items():
                # The headings come from the text prepare returns, which is stored as it is: an O-42 clean-up of the
                # text must never run before this, or the titles it removes are lost as headings (review 2026-11-11 (f)).
                await db.upsert_articles(conn, articles, extract_headings(articles))
                await db.prune_articles(conn, slug, {(a.number, a.suffix) for a in articles})
            await db.set_verification(conn, matched.verified)
            await db.replace_memorandum(conn, memorandum.notes, memorandum.links, memorandum.source)
    return prepared, memorandum, matched


def check_verification(registry: Path, corrections: Path, corpus: Path) -> tuple[Prepared, verification.Matched]:
    """--check-verification: the records against the texts prepare returns; nothing is written."""
    prepared = prepare(load_registry(registry), load_corrections(corrections), corpus)
    return prepared, verification.match(prepared.articles, verification.records_dir(registry))


def _report(matched: verification.Matched, registry: Path) -> None:
    for problem in matched.problems:
        print(f'verification problem: {problem}')
    results = ', '.join(f'{count} {result}' for result, count in matched.results.items())
    print(f'verification: {len(matched.verified)} articles verified, from {matched.records} records in {matched.files} '
          f'files ({results}) in {verification.records_dir(registry)}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--corrections', type=Path, required=True)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--check-verification', action='store_true',
                        help='check the verification records against the parsed texts; write nothing')
    args = parser.parse_args()
    if args.check_verification:
        try:
            _, matched = check_verification(args.registry, args.corrections, args.corpus)
        except (IngestError, RegistryError, CorrectionError) as error:
            raise SystemExit(f'verification check failed: {error}') from error
        _report(matched, args.registry)
        if matched.problems:
            raise SystemExit(f'verification check failed: {len(matched.problems)} problem(s)')
        print('verification check passed')
        return
    try:
        prepared, memorandum, matched = asyncio.run(
            ingest(db.database_url(), args.registry, args.corrections, args.corpus))
    except (IngestError, RegistryError, CorrectionError, MemorandumError) as error:
        raise SystemExit(f'ingest failed: {error}') from error
    for law in prepared.laws:
        print(f'ingested {len(prepared.articles[law.slug])} articles into {law.slug}')
    for article in prepared.short:
        print(f'short article ({len(article.text)} characters): {article.law_slug} {article.label}')
    print(f'ingested {len(memorandum.notes)} memorandum notes and {len(memorandum.links)} links')
    print(f'memorandum articles without a note: {", ".join(map(str, memorandum.uncovered)) or "none"}')
    print(f'ingested {sum(len(a) for a in prepared.articles.values())} articles from {len(prepared.laws)} laws')
    _report(matched, args.registry)


if __name__ == '__main__':
    main()
