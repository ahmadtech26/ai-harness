"""Sweep flags and watermarks (spec C.2). A user has at most one open flag: the partial unique index
`sweep_flags_one_open` with `ON CONFLICT ... DO NOTHING`, so of two calls opening a flag at once the second
waits for the first's transaction and then opens nothing (its own log row still commits). Clearing records
who and when and moves the user's watermark to the newest retrieval_log id, so the detector only counts the
events after it and a cleared sweep does not fire again from its old events."""

from dataclasses import asdict, dataclass
from datetime import datetime

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class Flag:
    id: int
    user_id: str
    level: str                  # suspected | proven
    status: str                 # open | cleared
    opened_at: datetime
    opened_log_id: int          # the retrieval_log row of the call that opened it
    escalated_at: datetime | None
    escalated_log_id: int | None
    evidence: dict              # {"opened": [signal, ...], "escalated": [signal, ...]}
    cleared_at: datetime | None
    cleared_by: str | None
    clear_reason: str | None

    def as_dict(self) -> dict:
        data = asdict(self)
        for key in ('opened_at', 'escalated_at', 'cleared_at'):
            if data[key] is not None:
                data[key] = data[key].isoformat()
        return data


_COLUMNS = (
    'id, user_id, level, status, opened_at, opened_log_id, escalated_at, escalated_log_id, evidence, '
    'cleared_at, cleared_by, clear_reason'
)


async def _one(conn: AsyncConnection, query: str, params: tuple) -> Flag | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        row = await cur.fetchone()
    return Flag(**row) if row else None


async def open_flag(conn: AsyncConnection, user_id: str) -> Flag | None:
    return await _one(conn, f"SELECT {_COLUMNS} FROM sweep_flags WHERE user_id = %s AND status = 'open'", (user_id,))


async def open_new(conn: AsyncConnection, user_id: str, level: str, log_id: int, signals: list[dict]) -> Flag | None:
    """Opens a flag at log row `log_id`; None when the user already has an open flag."""
    return await _one(
        conn,
        f"""
        INSERT INTO sweep_flags (user_id, level, opened_log_id, evidence) VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) WHERE status = 'open' DO NOTHING
        RETURNING {_COLUMNS}
        """,
        (user_id, level, log_id, Jsonb({'opened': signals})),
    )


async def escalate(conn: AsyncConnection, flag_id: int, log_id: int, signals: list[dict]) -> Flag | None:
    """Raises an open suspected flag to proven at log row `log_id`; None if it is no longer open and suspected."""
    return await _one(
        conn,
        f"""
        UPDATE sweep_flags SET level = 'proven', escalated_at = now(), escalated_log_id = %s,
          evidence = evidence || jsonb_build_object('escalated', %s::jsonb)
        WHERE id = %s AND status = 'open' AND level = 'suspected'
        RETURNING {_COLUMNS}
        """,
        (log_id, Jsonb(signals), flag_id),
    )


async def clear(conn: AsyncConnection, user_id: str, who: str, reason: str | None) -> Flag | None:
    """Clears the user's open flag and moves their watermark, in one statement; None without an open flag."""
    return await _one(
        conn,
        f"""
        WITH cleared AS (
          UPDATE sweep_flags SET status = 'cleared', cleared_at = now(), cleared_by = %s, clear_reason = %s
          WHERE user_id = %s AND status = 'open'
          RETURNING {_COLUMNS}
        ), mark AS (
          INSERT INTO guard_watermarks (user_id, since, since_log_id)
          SELECT user_id, cleared_at, (SELECT COALESCE(max(id), 0) FROM retrieval_log) FROM cleared
          ON CONFLICT (user_id) DO UPDATE SET since = EXCLUDED.since, since_log_id = EXCLUDED.since_log_id
        )
        SELECT * FROM cleared
        """,
        (who, reason, user_id),
    )


async def watermark(conn: AsyncConnection, user_id: str) -> int:
    """The retrieval_log id after which the user's events count (0: all)."""
    cur = await conn.execute('SELECT since_log_id FROM guard_watermarks WHERE user_id = %s', (user_id,))
    row = await cur.fetchone()
    return row[0] if row else 0


async def list_flags(conn: AsyncConnection, status: str | None = 'open', limit: int = 500) -> list[Flag]:
    """Flags with `status` (None: all), newest first."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f'SELECT {_COLUMNS} FROM sweep_flags WHERE (%s::text IS NULL OR status = %s) '
            'ORDER BY opened_at DESC, id DESC LIMIT %s',
            (status, status, limit),
        )
        return [Flag(**row) for row in await cur.fetchall()]


async def open_counts(conn: AsyncConnection) -> dict[str, int]:
    cur = await conn.execute("SELECT level, count(*) FROM sweep_flags WHERE status = 'open' GROUP BY level")
    counts = {'suspected': 0, 'proven': 0}
    counts.update({level: count for level, count in await cur.fetchall()})
    return counts
