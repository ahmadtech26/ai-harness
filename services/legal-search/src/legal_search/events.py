"""Retrieval-log rows as sweep-detector events (spec C.1). Every tool call is a row, served or refused."""

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


async def load_user_events(conn: AsyncConnection, user_id: str, after_log_id: int, span: timedelta) -> tuple[list[Event], datetime]:
    """The user's events after log id `after_log_id` (the watermark) and within `span` of now, in log
    order, and the database's now (the decision time)."""
    now = await _now(conn)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            _EVENTS + ' WHERE r.user_id = %s AND r.id > %s AND r.created_at > %s ORDER BY r.id',
            (user_id, after_log_id, now - span),
        )
        return [_event(row) for row in await cur.fetchall()], now


# One telemetry or simulation request reads at most this many events; a larger window is refused, never cut.
MAX_EVENTS = 200_000


class TooManyEvents(Exception):
    """The window holds more events than one telemetry or simulation request reads."""


def load_window_sync(conninfo: str, span: timedelta) -> tuple[dict[str, list[Event]], datetime]:
    """Every user's events of the last `span`, in log order (watermarks ignored: raw behaviour), and the
    database's now. Raises TooManyEvents, before reading any, when the window holds more than MAX_EVENTS.
    Blocking, on a connection of its own: admin.py runs it in a worker thread, because decoding up to
    MAX_EVENTS rows into events takes seconds that would otherwise hold the event loop."""
    with psycopg.connect(conninfo, autocommit=True) as conn:
        now = conn.execute('SELECT now()').fetchone()[0]
        since = now - span
        count = conn.execute(
            'SELECT count(*) FROM (SELECT 1 FROM retrieval_log WHERE created_at > %s LIMIT %s) AS window_rows',
            (since, MAX_EVENTS + 1),
        ).fetchone()[0]
        if count > MAX_EVENTS:
            raise TooManyEvents(f'the window holds more than {MAX_EVENTS} events; choose fewer days')
        by_user: dict[str, list[Event]] = defaultdict(list)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_EVENTS + ' WHERE r.created_at > %s ORDER BY r.user_id, r.id', (since,))
            while rows := cur.fetchmany(2_000):  # a batch at a time: the event loop gets the interpreter in between
                for row in rows:
                    by_user[row['user_id']].append(_event(row))
    return dict(by_user), now
