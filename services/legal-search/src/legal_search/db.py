"""Postgres storage: articles with an Arabic-normalised full-text index, and the retrieval log."""

from dataclasses import dataclass

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from legal_search.corpus import Article
from legal_search.normalize import normalize, tokens

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
  id BIGSERIAL PRIMARY KEY,
  law_slug TEXT NOT NULL,
  law_title TEXT NOT NULL,
  number INT NOT NULL,
  suffix TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL,
  text TEXT NOT NULL,
  norm TEXT NOT NULL,
  tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', norm)) STORED,
  source TEXT NOT NULL DEFAULT '',
  shard TEXT NOT NULL DEFAULT '',
  verified_at DATE,
  UNIQUE (law_slug, number, suffix)
);
CREATE INDEX IF NOT EXISTS articles_tsv ON articles USING GIN (tsv);
CREATE TABLE IF NOT EXISTS retrieval_log (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  message_id TEXT,
  conversation_id TEXT,
  tool TEXT NOT NULL,
  query TEXT,
  article_ids BIGINT[] NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS retrieval_log_user_time ON retrieval_log (user_id, created_at);
CREATE INDEX IF NOT EXISTS retrieval_log_message ON retrieval_log (message_id);
"""

# Function words that would otherwise match nearly every article.
STOPWORDS = frozenset(
    normalize(word)
    for word in 'في من على الى إلى عن ان أن إن ما هل او أو ثم قد لا لم لن هو هي هذا هذه ذلك التي الذي كان مع اذا إذا عند'.split()
)


@dataclass(frozen=True)
class Found:
    id: int
    law_title: str
    label: str
    text: str
    source: str
    verified: bool


def build_tsquery(query: str) -> str | None:
    """OR of prefix terms, so inflected forms still match; None when nothing searchable remains."""
    terms = [term for term in dict.fromkeys(tokens(query)) if term not in STOPWORDS and len(term) >= 2]
    return ' | '.join(f'{term}:*' for term in terms) or None


async def create_schema(conn: AsyncConnection) -> None:
    await conn.execute(SCHEMA)


async def upsert_articles(conn: AsyncConnection, articles: list[Article]) -> int:
    async with conn.cursor() as cur:
        for article in articles:
            await cur.execute(
                """
                INSERT INTO articles (law_slug, law_title, number, suffix, label, text, norm, source, shard)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (law_slug, number, suffix) DO UPDATE SET
                  law_title = EXCLUDED.law_title, label = EXCLUDED.label, text = EXCLUDED.text,
                  norm = EXCLUDED.norm, source = EXCLUDED.source, shard = EXCLUDED.shard
                """,
                (
                    article.law_slug,
                    article.law_title,
                    article.number,
                    article.suffix,
                    article.label,
                    article.text,
                    normalize(article.text),
                    article.source,
                    article.shard,
                ),
            )
    return len(articles)


def _found(row: dict) -> Found:
    return Found(row['id'], row['law_title'], row['label'], row['text'], row['source'], row['verified_at'] is not None)


async def search(conn: AsyncConnection, query: str, limit: int) -> list[Found]:
    tsquery = build_tsquery(query)
    if tsquery is None or limit <= 0:
        return []
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT a.id, a.law_title, a.label, a.text, a.source, a.verified_at
            FROM articles a, to_tsquery('simple', %s) q
            WHERE a.tsv @@ q
            ORDER BY ts_rank_cd(a.tsv, q) DESC, a.number ASC
            LIMIT %s
            """,
            (tsquery, limit),
        )
        return [_found(row) for row in await cur.fetchall()]


async def get_article(conn: AsyncConnection, law_slug: str, number: int, suffix: str) -> Found | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT id, law_title, label, text, source, verified_at FROM articles
            WHERE law_slug = %s AND number = %s AND suffix = %s
            """,
            (law_slug, number, suffix),
        )
        row = await cur.fetchone()
        return _found(row) if row else None


async def log_retrieval(
    conn: AsyncConnection,
    *,
    user_id: str,
    message_id: str | None,
    conversation_id: str | None,
    tool: str,
    query: str | None,
    article_ids: list[int],
) -> None:
    await conn.execute(
        """
        INSERT INTO retrieval_log (user_id, message_id, conversation_id, tool, query, article_ids)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (user_id, message_id, conversation_id, tool, query, article_ids),
    )


async def documents_for_message(conn: AsyncConnection, message_id: str) -> int:
    cur = await conn.execute(
        'SELECT COALESCE(SUM(cardinality(article_ids)), 0) FROM retrieval_log WHERE message_id = %s', (message_id,)
    )
    return int((await cur.fetchone())[0])


async def documents_for_user_today(conn: AsyncConnection, user_id: str) -> int:
    cur = await conn.execute(
        """
        SELECT COALESCE(SUM(cardinality(article_ids)), 0) FROM retrieval_log
        WHERE user_id = %s AND created_at > now() - interval '24 hours'
        """,
        (user_id,),
    )
    return int((await cur.fetchone())[0])
