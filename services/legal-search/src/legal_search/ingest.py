"""Load one law's statute shards into Postgres.

    legal-search-ingest --law-dir <.../القانون-المدني-الأردني> --law-slug civil-code
"""

import argparse
import asyncio
from pathlib import Path

from psycopg import AsyncConnection

from legal_search import db
from legal_search.corpus import parse_law


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
