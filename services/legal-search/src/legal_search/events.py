"""Retrieval-log rows as sweep-detector events (spec C.1). Every tool call is a row, served or refused."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from legal_search.detector import Event, keys_of
from legal_search.guard_settings import GuardSettings

# The detector's longest look-back: 7 days of coverage plus the 24 h behind the oldest cap crossing.
BASE_LOOKBACK = timedelta(days=8)
# Rows fetched and decoded at a time; the event loop gets the interpreter in between.
BATCH = 2_000

_EVENTS = """
SELECT r.id, r.user_id, r.created_at, r.tool, r.requested_law, r.requested_number, r.requested_suffix, r.outcome,
       cardinality(r.article_ids) + cardinality(r.note_ids) AS documents,
       ARRAY(SELECT a.law_slug || '|' || a.number || '|' || a.suffix FROM articles a WHERE a.id = ANY (r.article_ids)) AS served,
       ARRAY(SELECT a.law_slug || '|' || a.number || '|' || a.suffix FROM articles a WHERE a.id = ANY (r.candidate_ids)) AS candidates
FROM retrieval_log r
"""


@dataclass(frozen=True)
class Attempt:
    """What one tool call asks for. For search_law, `keys` are the articles it would serve."""

    tool: str
    law: str | None = None
    number: int | None = None
    suffix: str | None = None
    keys: frozenset[str] = frozenset()

    def event(self, now: datetime) -> Event:
        """This call as the event being decided (no log id yet)."""
        return Event(id=None, at=now, tool=self.tool, law=self.law, number=self.number, suffix=self.suffix,
                     keys=keys_of(self.tool, self.law, self.number, self.suffix, self.keys))


def lookback(settings: GuardSettings) -> timedelta:
    return max(BASE_LOOKBACK, timedelta(hours=settings.run_window_hours))


def _event(row: dict) -> Event:
    return Event(
        id=row['id'], at=row['created_at'], tool=row['tool'], law=row['requested_law'],
        number=row['requested_number'], suffix=row['requested_suffix'], outcome=row['outcome'],
        keys=keys_of(row['tool'], row['requested_law'], row['requested_number'], row['requested_suffix'], row['served']),
        documents=row['documents'], candidates=frozenset(row['candidates']),
    )


async def _now(conn: AsyncConnection) -> datetime:
    cur = await conn.execute('SELECT now()')
    return (await cur.fetchone())[0]


def _events(rows: list[dict]) -> list[Event]:
    return [_event(row) for row in rows]


async def load_user_events(conn: AsyncConnection, user_id: str, after_log_id: int, span: timedelta) -> tuple[list[Event], datetime]:
    """The user's events after log id `after_log_id` (the watermark) and within `span` of now, in log
    order, and the database's now (the decision time). Rows come a batch at a time and are decoded in a
    worker thread, so a long history does not hold the event loop that serves every user (R1 n=14)."""
    now = await _now(conn)
    history: list[Event] = []
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            _EVENTS + ' WHERE r.user_id = %s AND r.id > %s AND r.created_at > %s ORDER BY r.id',
            (user_id, after_log_id, now - span),
        )
        while rows := await cur.fetchmany(BATCH):
            history += await asyncio.to_thread(_events, rows)
    return history, now


# One telemetry or simulation request reads at most this many events of one user. A user with more in the window
# is left out and named, never cut: the ceiling was global, so one customer could refuse the request for every
# other (R1 n=15).
MAX_EVENTS = 200_000
# ...and at most this many in total, the memory bound of one request (R1 n=15): past it the largest users are
# left out and named too.
MAX_TOTAL_EVENTS = 1_000_000


def load_window_sync(conninfo: str, span: timedelta) -> tuple[dict[str, list[Event]], datetime, list[str]]:
    """Every user's events of the last `span`, in log order (watermarks ignored: raw behaviour), the database's
    now, and the users left out, none of whose events is read: those with more than MAX_EVENTS events in the
    window, and, smallest users first, those that would take the total past MAX_TOTAL_EVENTS.
    Blocking, on a connection of its own: admin.py runs it in a worker thread, because decoding the rows into
    events takes seconds that would otherwise hold the event loop."""
    with psycopg.connect(conninfo, autocommit=True) as conn:
        now = conn.execute('SELECT now()').fetchone()[0]
        since = now - span
        counts = conn.execute(
            'SELECT user_id, count(*) FROM retrieval_log WHERE created_at > %s GROUP BY user_id', (since,),
        ).fetchall()
        left_out, total = [], 0
        for user_id, count in sorted(counts, key=lambda row: (row[1], row[0])):  # smallest first
            if count > MAX_EVENTS or total + count > MAX_TOTAL_EVENTS:
                left_out.append(user_id)
            else:
                total += count
        left_out.sort()
        by_user: dict[str, list[Event]] = defaultdict(list)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_EVENTS + ' WHERE r.created_at > %s AND NOT (r.user_id = ANY (%s)) ORDER BY r.user_id, r.id',
                        (since, left_out))
            while rows := cur.fetchmany(BATCH):  # a batch at a time: the event loop gets the interpreter in between
                for row in rows:
                    by_user[row['user_id']].append(_event(row))
    return dict(by_user), now, left_out
