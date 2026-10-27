"""A fresh legal-search schema for database tests (they share one Postgres and run one at a time)."""

from psycopg import AsyncConnection

from legal_search import db

TABLES = 'memorandum_links, memorandum_notes, articles, laws, retrieval_log'


async def fresh(conn: AsyncConnection) -> None:
    await conn.execute(f'DROP TABLE IF EXISTS {TABLES} CASCADE')
    await db.create_schema(conn)
