r"""The output-contract snapshot (spec REQ-RAG-050): every article and every Civil Code memorandum note as the
library serves it, in one file. A change that ships must leave it byte-identical.

    legal-search-contract --out <file>

writes the snapshot (creating the file's folder) and prints its sha256 and the article and note counts. It reads the
database DATABASE_URL (or DATABASE_URL_FILE) names in one REPEATABLE READ, READ ONLY transaction, so a write made
while it runs can neither tear the snapshot nor come from it. It refuses a database with no articles or no notes (a
wrong DATABASE_URL), and exits 1 without writing the file.

The file is UTF-8 with '\n' line ends, one record per article, then one per note. A record is a key line, '\n', the
served text, '\n'. Only key lines start with «@@ »: a served text with a line that does would make the file
ambiguous, so the snapshot raises ContractError naming the record instead.
- `@@ article <law>:<number>` or `@@ article <law>:<number>:<suffix>` (grounding.ts's key form), then
  `format_articles([found])`, the article alone. Articles are in key order: law slug, number, suffix, the strings
  compared by code point in Python (as the BM25 engine breaks ties), never by the database's collation, so the file
  does not depend on the database's locale. Each `Found` comes from db's own row query and row mapping (`_SELECT`,
  `_found`), as search and get_article build theirs.
- `@@ note <note_no>`, in note_no order, then get_memorandum's reply when its page holds this one note: for the
  lowest Civil Code article the note explains, at the note's offset among that article's notes, with that article's
  note count, read through db.memorandum_count and db.memorandum_page. The memorandum loader gives each article at
  most one note, so on its corpus that is get_memorandum(article)'s whole reply. A note linked to no article is
  served by no tool, so its text is empty (the record is the key line and an empty line).
"""

import argparse
import asyncio
import hashlib
from pathlib import Path

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from legal_search import db
from legal_search.citation import format_articles, format_memorandum

KEY_LINE = '@@ '


class ContractError(Exception):
    """The snapshot cannot be taken or written in its format."""


def _record(key: str, text: str) -> str:
    if any(line.startswith(KEY_LINE) for line in text.split('\n')):
        raise ContractError(f'{key}: a line of its served text starts with «{KEY_LINE}», which only key lines may')
    return f'{KEY_LINE}{key}\n{text}\n'


def _article_key(found: db.Found) -> str:
    return f'{found.law_slug}:{found.number}' + (f':{found.suffix}' if found.suffix else '')


async def _article_records(conn: AsyncConnection) -> list[str]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(db._SELECT)
        found = [db._found(row) for row in await cur.fetchall()]
    found.sort(key=lambda article: (article.law_slug, article.number, article.suffix))
    return [_record(f'article {_article_key(article)}', format_articles([article])) for article in found]


async def _served_note(conn: AsyncConnection, note_no: int, article: int,
                       pages: dict[int, tuple[int, list[db.Note]]]) -> str:
    """get_memorandum(article, offset)'s reply when its page holds one note; `pages` keeps each article's note count
    and notes."""
    if article not in pages:
        total = await db.memorandum_count(conn, article)
        pages[article] = total, await db.memorandum_page(conn, article, 0, total)
    total, page = pages[article]
    offset = [note.note_no for note in page].index(note_no)
    return format_memorandum(article, offset, [page[offset]], total)


async def _note_records(conn: AsyncConnection) -> list[str]:
    cur = await conn.execute(
        """
        SELECT n.note_no, min(k.article_number)
        FROM memorandum_notes n LEFT JOIN memorandum_links k ON k.note_no = n.note_no
        GROUP BY n.note_no ORDER BY n.note_no
        """
    )
    pages: dict[int, tuple[int, list[db.Note]]] = {}
    records = []
    for note_no, article in await cur.fetchall():
        text = '' if article is None else await _served_note(conn, note_no, article, pages)
        records.append(_record(f'note {note_no}', text))
    return records


async def _snapshot(conn: AsyncConnection) -> tuple[bytes, int, int]:
    articles = await _article_records(conn)
    notes = await _note_records(conn)
    return ''.join(articles + notes).encode('utf-8'), len(articles), len(notes)


async def snapshot(conn: AsyncConnection) -> bytes:
    """Every article, then every memorandum note, each after its key line (the module docstring gives the format)."""
    return (await _snapshot(conn))[0]


async def _take(conninfo: str) -> tuple[bytes, int, int]:
    async with await AsyncConnection.connect(conninfo, autocommit=True) as conn:
        async with conn.transaction():
            await conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            return await _snapshot(conn)


def main() -> None:
    parser = argparse.ArgumentParser(prog='legal-search-contract', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, required=True, help='the snapshot file to write')
    args = parser.parse_args()
    try:
        data, articles, notes = asyncio.run(_take(db.database_url()))
        if not articles or not notes:
            raise ContractError(f'the database holds {articles} articles and {notes} memorandum notes, and the snapshot '
                                'needs both (is DATABASE_URL the corpus database?)')
    except ContractError as error:
        raise SystemExit(f'legal-search-contract: {error}; nothing written') from error
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(f'wrote {args.out}: sha256 {hashlib.sha256(data).hexdigest()}, {articles} articles, {notes} notes')


if __name__ == '__main__':
    main()
