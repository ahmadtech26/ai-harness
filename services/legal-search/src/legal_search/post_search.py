"""The texts already served to one answer (plan 2026-11-14 S5a and S5b; recall plan Task 6.4): read from the
retrieval log rows that carry the answer's message id, as db.documents_for_message counts them. A repeated fetch of one
of them costs no slot of the answer's allowance, and a search with skip_served leaves them out."""

from psycopg import AsyncConnection


async def served_ids_for_message(conn: AsyncConnection, message: str | None) -> frozenset[int]:
    """The article ids already served to this answer (retrieval_log.article_ids of its rows); none without a message."""
    return await _served(conn, 'article_ids', message)


async def served_note_ids_for_message(conn: AsyncConnection, message: str | None) -> frozenset[int]:
    """The memorandum note numbers already served to this answer (retrieval_log.note_ids of its rows)."""
    return await _served(conn, 'note_ids', message)


async def _served(conn: AsyncConnection, column: str, message: str | None) -> frozenset[int]:
    if not message:
        return frozenset()
    cur = await conn.execute(f'SELECT DISTINCT unnest({column}) FROM retrieval_log WHERE message_id = %s', (message,))
    return frozenset(row[0] for row in await cur.fetchall())
