"""Postgres storage: the law registry, articles with an Arabic-normalised full-text index, the Civil Code
explanatory memorandum, and the retrieval log."""

import os
from dataclasses import dataclass
from datetime import date

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from legal_search.corpus import Article
from legal_search.normalize import normalize, tokens
from legal_search.registry import Law
from legal_search.search_config import DEFAULT, SearchConfig
from legal_search.synonyms import synonym_terms

# Run at every service start and every ingest. CREATE … IF NOT EXISTS never changes a table a deployed
# database already has: a new column on an existing table goes in as ALTER TABLE … ADD COLUMN IF NOT
# EXISTS after the CREATE statements, as note_ids does.
SCHEMA = """
CREATE TABLE IF NOT EXISTS laws (
  slug TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  number INT,
  year INT,
  gazette_issue INT,
  gazette_date DATE,
  gazette_url TEXT,
  amendment_law INT,
  amendment_year INT,
  amendment_gazette_issue INT,
  amendment_gazette_date DATE,
  amendment_url TEXT,
  note TEXT,
  approved BOOLEAN NOT NULL DEFAULT false
);
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
CREATE TABLE IF NOT EXISTS memorandum_notes (
  note_no INT PRIMARY KEY,
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS memorandum_links (
  article_number INT NOT NULL,
  note_no INT NOT NULL REFERENCES memorandum_notes (note_no) ON DELETE CASCADE,
  PRIMARY KEY (article_number, note_no)
);
CREATE TABLE IF NOT EXISTS retrieval_log (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  message_id TEXT,
  conversation_id TEXT,
  tool TEXT NOT NULL,
  query TEXT,
  article_ids BIGINT[] NOT NULL DEFAULT '{}',
  note_ids BIGINT[] NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS note_ids BIGINT[] NOT NULL DEFAULT '{}';
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS requested_law TEXT;
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS requested_number INT;
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS requested_suffix TEXT;
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS outcome TEXT NOT NULL DEFAULT 'served'
  CHECK (outcome IN ('served', 'capped', 'throttled', 'suspended'));
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS candidate_ids BIGINT[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS retrieval_log_user_time ON retrieval_log (user_id, created_at);
CREATE INDEX IF NOT EXISTS retrieval_log_message ON retrieval_log (message_id);
-- Telemetry and simulation read a window by time alone (R3 n=14); without it each request scans the whole log.
CREATE INDEX IF NOT EXISTS retrieval_log_created ON retrieval_log (created_at);
CREATE TABLE IF NOT EXISTS guard_settings (
  id INT PRIMARY KEY CHECK (id = 1),
  settings JSONB NOT NULL,
  updated_by TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS guard_settings_history (
  id BIGSERIAL PRIMARY KEY,
  changed_by TEXT NOT NULL,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  reason TEXT NOT NULL,
  previous JSONB,
  settings JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS sweep_flags (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  level TEXT NOT NULL CHECK (level IN ('suspected', 'proven')),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'cleared')),
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  opened_log_id BIGINT NOT NULL,
  escalated_at TIMESTAMPTZ,
  escalated_log_id BIGINT,
  evidence JSONB NOT NULL,
  cleared_at TIMESTAMPTZ,
  cleared_by TEXT,
  clear_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS sweep_flags_one_open ON sweep_flags (user_id) WHERE status = 'open';
CREATE TABLE IF NOT EXISTS guard_watermarks (
  user_id TEXT PRIMARY KEY,
  since TIMESTAMPTZ NOT NULL,
  since_log_id BIGINT NOT NULL
);
"""

# Function words that would otherwise match nearly every article.
STOPWORDS = frozenset(
    normalize(word)
    for word in 'في من على الى إلى عن ان أن إن ما هل او أو ثم قد لا لم لن هو هي هذا هذه ذلك التي الذي كان مع اذا إذا عند'.split()
)


def database_url() -> str:
    """`DATABASE_URL`, or the contents of `DATABASE_URL_FILE` so credentials stay out of the environment."""
    if os.environ.get('DATABASE_URL'):
        return os.environ['DATABASE_URL']
    path = os.environ.get('DATABASE_URL_FILE')
    if not path:
        raise RuntimeError('DATABASE_URL or DATABASE_URL_FILE is required')
    with open(path, encoding='utf-8') as handle:
        return handle.read().strip()


@dataclass(frozen=True)
class LawMeta:
    """The registry's citation fields for an article's law; None where the registry has no value."""

    number: int | None = None
    year: int | None = None
    gazette_issue: int | None = None
    gazette_date: date | None = None
    amendment_law: int | None = None
    amendment_year: int | None = None
    amendment_gazette_issue: int | None = None
    amendment_gazette_date: date | None = None
    note: str | None = None
    approved: bool = False


@dataclass(frozen=True)
class Found:
    id: int
    law_slug: str
    number: int
    suffix: str
    law_title: str
    label: str
    text: str
    source: str
    verified: bool
    law: LawMeta = LawMeta()


def query_terms(query: str, config: SearchConfig = DEFAULT) -> list[str]:
    """The query's searchable terms in order: normalised, de-duplicated, no stopwords or one-letter tokens."""
    return [term for term in dict.fromkeys(tokens(query)) if term not in STOPWORDS and len(term) >= 2]


def build_tsquery(query: str, config: SearchConfig = DEFAULT) -> str | None:
    """OR of prefix terms, so inflected forms still match; None when nothing searchable remains."""
    terms = query_terms(query, config)
    parts = [f'{term}:*' for term in terms]
    if config.synonyms:
        parts += [term for term in synonym_terms(tokens(query)) if term not in parts]
    return ' | '.join(parts) or None


async def create_schema(conn: AsyncConnection) -> None:
    await conn.execute(SCHEMA)


async def upsert_laws(conn: AsyncConnection, laws: list[Law]) -> int:
    async with conn.cursor() as cur:
        for law in laws:
            await cur.execute(
                """
                INSERT INTO laws (slug, title, number, year, gazette_issue, gazette_date, gazette_url, amendment_law,
                  amendment_year, amendment_gazette_issue, amendment_gazette_date, amendment_url, note, approved)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET
                  title = EXCLUDED.title, number = EXCLUDED.number, year = EXCLUDED.year,
                  gazette_issue = EXCLUDED.gazette_issue, gazette_date = EXCLUDED.gazette_date,
                  gazette_url = EXCLUDED.gazette_url, amendment_law = EXCLUDED.amendment_law,
                  amendment_year = EXCLUDED.amendment_year, amendment_gazette_issue = EXCLUDED.amendment_gazette_issue,
                  amendment_gazette_date = EXCLUDED.amendment_gazette_date, amendment_url = EXCLUDED.amendment_url,
                  note = EXCLUDED.note, approved = EXCLUDED.approved
                """,
                (
                    law.slug, law.title, law.number, law.year, law.gazette_issue, law.gazette_date, law.gazette_url,
                    law.amendment_law, law.amendment_year, law.amendment_gazette_issue, law.amendment_gazette_date,
                    law.amendment_url, law.note, law.approved,
                ),
            )
    return len(laws)


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


async def prune_articles(conn: AsyncConnection, law_slug: str, keep: set[tuple[int, str]]) -> int:
    """Delete this law's articles whose (number, suffix) is not in `keep`; returns how many went."""
    ordered = sorted(keep)
    cur = await conn.execute(
        """
        DELETE FROM articles a
        WHERE a.law_slug = %s
          AND (a.number, a.suffix) NOT IN (SELECT k.n, k.s FROM unnest(%s::int[], %s::text[]) AS k (n, s))
        """,
        (law_slug, [number for number, _ in ordered], [suffix for _, suffix in ordered]),
    )
    return cur.rowcount


# Every result joins its law's registry row; LEFT JOIN so an article never disappears for want of one.
_SELECT = """
SELECT a.id, a.law_slug, a.number, a.suffix, COALESCE(l.title, a.law_title) AS law_title, a.label, a.text,
       a.source, a.verified_at, l.number AS law_number, l.year AS law_year, l.gazette_issue, l.gazette_date,
       l.amendment_law, l.amendment_year, l.amendment_gazette_issue, l.amendment_gazette_date, l.note,
       COALESCE(l.approved, false) AS approved
FROM articles a LEFT JOIN laws l ON l.slug = a.law_slug
"""


def _found(row: dict) -> Found:
    return Found(
        id=row['id'],
        law_slug=row['law_slug'],
        number=row['number'],
        suffix=row['suffix'],
        law_title=row['law_title'],
        label=row['label'],
        text=row['text'],
        source=row['source'],
        verified=row['verified_at'] is not None,
        law=LawMeta(
            number=row['law_number'],
            year=row['law_year'],
            gazette_issue=row['gazette_issue'],
            gazette_date=row['gazette_date'],
            amendment_law=row['amendment_law'],
            amendment_year=row['amendment_year'],
            amendment_gazette_issue=row['amendment_gazette_issue'],
            amendment_gazette_date=row['amendment_gazette_date'],
            note=row['note'],
            approved=row['approved'],
        ),
    )


async def search(conn: AsyncConnection, query: str, limit: int, law: str | None = None,
                 config: SearchConfig = DEFAULT) -> list[Found]:
    """Ranked keyword search, optionally within one law; ties break on number, law and suffix (deterministic)."""
    tsquery = build_tsquery(query, config)
    if tsquery is None or limit <= 0:
        return []
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            _SELECT
            + """
            CROSS JOIN to_tsquery('simple', %s) q
            WHERE a.tsv @@ q AND (%s::text IS NULL OR a.law_slug = %s)
            ORDER BY ts_rank_cd(a.tsv, q, %s::int) DESC, a.number ASC, a.law_slug ASC, a.suffix ASC
            LIMIT %s
            """,
            (tsquery, law, law, config.rank_normalization, limit),
        )
        return [_found(row) for row in await cur.fetchall()]


async def get_article(conn: AsyncConnection, law_slug: str, number: int, suffix: str) -> Found | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_SELECT + ' WHERE a.law_slug = %s AND a.number = %s AND a.suffix = %s', (law_slug, number, suffix))
        row = await cur.fetchone()
        return _found(row) if row else None


async def law_slugs(conn: AsyncConnection) -> list[str]:
    # Articles count too, so a law stays usable if the service starts before its registry row is loaded.
    cur = await conn.execute('SELECT slug FROM laws UNION SELECT law_slug FROM articles ORDER BY 1')
    return [row[0] for row in await cur.fetchall()]


@dataclass(frozen=True)
class Note:
    note_no: int
    text: str
    source: str
    first_article: int | None = None  # the lowest and highest Civil Code article linked to this note
    last_article: int | None = None


async def replace_memorandum(conn: AsyncConnection, notes: dict[int, str], links: list[tuple[int, int]], source: str) -> None:
    """Make the memorandum tables equal to the source: upsert notes, replace links, drop vanished notes."""
    await conn.execute('DELETE FROM memorandum_links')
    async with conn.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO memorandum_notes (note_no, text, source) VALUES (%s, %s, %s)
            ON CONFLICT (note_no) DO UPDATE SET text = EXCLUDED.text, source = EXCLUDED.source
            """,
            [(note_no, text, source) for note_no, text in sorted(notes.items())],
        )
        await cur.executemany('INSERT INTO memorandum_links (article_number, note_no) VALUES (%s, %s)', links)
    await conn.execute('DELETE FROM memorandum_notes WHERE NOT (note_no = ANY(%s::int[]))', (sorted(notes),))


async def memorandum_count(conn: AsyncConnection, article_number: int) -> int:
    cur = await conn.execute('SELECT count(*) FROM memorandum_links WHERE article_number = %s', (article_number,))
    return int((await cur.fetchone())[0])


async def memorandum_page(conn: AsyncConnection, article_number: int, offset: int, limit: int) -> list[Note]:
    """Up to `limit` notes linked to a Civil Code article, in note_no order, starting at `offset`; each carries
    the lowest and highest article linked to it (the articles the note explains)."""
    if limit <= 0:
        return []
    cur = await conn.execute(
        """
        SELECT n.note_no, n.text, n.source, s.first_article, s.last_article
        FROM memorandum_links k
        JOIN memorandum_notes n ON n.note_no = k.note_no
        JOIN (SELECT note_no, min(article_number) AS first_article, max(article_number) AS last_article
              FROM memorandum_links GROUP BY note_no) s ON s.note_no = k.note_no
        WHERE k.article_number = %s ORDER BY n.note_no LIMIT %s OFFSET %s
        """,
        (article_number, limit, offset),
    )
    return [Note(*row) for row in await cur.fetchall()]


async def log_retrieval(
    conn: AsyncConnection,
    *,
    user_id: str,
    message_id: str | None,
    conversation_id: str | None,
    tool: str,
    query: str | None,
    article_ids: list[int],
    note_ids: list[int] | None = None,
    requested_law: str | None = None,
    requested_number: int | None = None,
    requested_suffix: str | None = None,
    outcome: str = 'served',
    candidate_ids: list[int] | None = None,
) -> int:
    """One row per tool call, served or refused (the sweep detector's events); returns the row's id.
    `candidate_ids`: the articles a search was decided on, when it served fewer of them (refused or trimmed)."""
    cur = await conn.execute(
        """
        INSERT INTO retrieval_log (user_id, message_id, conversation_id, tool, query, article_ids, note_ids,
          requested_law, requested_number, requested_suffix, outcome, candidate_ids)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (user_id, message_id, conversation_id, tool, query, article_ids, note_ids or [], requested_law,
         requested_number, requested_suffix, outcome, candidate_ids or []),
    )
    return (await cur.fetchone())[0]


async def purge_user(conn: AsyncConnection, user_id: str) -> None:
    """Deletes everything legal-search holds on a user: their retrieval log rows, their sweep flags (cleared ones
    included) and their watermark, in one transaction (R2 n=33). Nothing calls it yet: the account erasure that
    will, and the retention of cleared flags, are the owner's."""
    async with conn.transaction():
        for table in ('sweep_flags', 'guard_watermarks', 'retrieval_log'):
            await conn.execute(f'DELETE FROM {table} WHERE user_id = %s', (user_id,))


async def documents_for_message(conn: AsyncConnection, message_id: str) -> int:
    """Articles plus memorandum notes already served for this answer."""
    cur = await conn.execute(
        'SELECT COALESCE(SUM(cardinality(article_ids) + cardinality(note_ids)), 0) FROM retrieval_log WHERE message_id = %s',
        (message_id,),
    )
    return int((await cur.fetchone())[0])


async def documents_for_user_today(conn: AsyncConnection, user_id: str) -> int:
    """Articles plus memorandum notes served to this user in the last 24 hours."""
    cur = await conn.execute(
        """
        SELECT COALESCE(SUM(cardinality(article_ids) + cardinality(note_ids)), 0) FROM retrieval_log
        WHERE user_id = %s AND created_at > now() - interval '24 hours'
        """,
        (user_id,),
    )
    return int((await cur.fetchone())[0])
