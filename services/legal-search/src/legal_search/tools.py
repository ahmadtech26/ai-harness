"""The legal library tools' behaviour, independent of MCP: caps, the retrieval log and the text the
model receives. server.py registers each function as an MCP tool. Every call is logged, served or not."""

from dataclasses import dataclass

from psycopg import AsyncConnection

from legal_search import db
from legal_search.caps import Caps, allowed
from legal_search.citation import format_articles, format_memorandum

CAP_REACHED = 'تم بلوغ الحد المسموح من النصوص لهذه الإجابة أو لهذا اليوم. يُرجى الاعتماد على ما سبق استرجاعه.'
NOT_FOUND_SEARCH = 'لم يُعثر على مواد مطابقة في المصادر المحمّلة.'
NOT_FOUND_ARTICLE = 'هذه المادة غير موجودة في المصادر المحمّلة.'
MEMORANDUM_HINT = 'للمادة مذكرة إيضاحية (get_memorandum)'
MEMORANDUM_LAW = 'civil-code'


@dataclass(frozen=True)
class Caller:
    user: str
    message: str | None
    conversation: str | None


async def _budget(conn: AsyncConnection, caps: Caps, caller: Caller, requested: int) -> int:
    used_for_answer = await db.documents_for_message(conn, caller.message) if caller.message else 0
    used_today = await db.documents_for_user_today(conn, caller.user)
    return allowed(requested, used_for_answer, used_today, caps)


async def _log(conn: AsyncConnection, caller: Caller, tool: str, query: str,
               article_ids: list[int] | None = None, note_ids: list[int] | None = None) -> None:
    await db.log_retrieval(conn, user_id=caller.user, message_id=caller.message, conversation_id=caller.conversation,
                           tool=tool, query=query, article_ids=article_ids or [], note_ids=note_ids or [])


async def _unknown_law(conn: AsyncConnection, law: str) -> str | None:
    """None for a loaded law; otherwise the message naming the slugs the library has."""
    slugs = await db.law_slugs(conn)
    if law in slugs:
        return None
    return f'رمز القانون غير معروف: {law}. الرموز المتاحة: {"، ".join(slugs)}.'


async def search_law(conn: AsyncConnection, caps: Caps, caller: Caller, query: str, limit: int = 5,
                     law: str | None = None) -> str:
    law = (law or '').strip() or None  # models often send "" for an optional argument
    if law is not None:
        unknown = await _unknown_law(conn, law)
        if unknown:
            await _log(conn, caller, 'search_law', query)
            return unknown
    remaining = await _budget(conn, caps, caller, limit)
    found = await db.search(conn, query, remaining, law=law) if remaining > 0 else []
    await _log(conn, caller, 'search_law', query, [article.id for article in found])
    if remaining == 0:
        return CAP_REACHED
    return format_articles(found) or NOT_FOUND_SEARCH


async def get_article(conn: AsyncConnection, caps: Caps, caller: Caller, number: int, suffix: str = '',
                      law: str = 'civil-code') -> str:
    law = law.strip() or 'civil-code'
    suffix = suffix.strip()
    query = f'{law}:{number}{suffix}'
    unknown = await _unknown_law(conn, law)
    if unknown:
        await _log(conn, caller, 'get_article', query)
        return unknown
    remaining = await _budget(conn, caps, caller, 1)
    article = await db.get_article(conn, law, number, suffix) if remaining > 0 else None
    await _log(conn, caller, 'get_article', query, [article.id] if article else [])
    if remaining == 0:
        return CAP_REACHED
    if article is None:
        return NOT_FOUND_ARTICLE
    text = format_articles([article])
    if law == MEMORANDUM_LAW and await db.memorandum_count(conn, number) > 0:
        text += f'\n{MEMORANDUM_HINT}'
    return text


async def get_memorandum(conn: AsyncConnection, caps: Caps, caller: Caller, article: int, offset: int = 0) -> str:
    """One page of the Civil Code memorandum notes linked to `article`, in note_no order; each note is capped and logged."""
    offset = max(offset, 0)
    query = f'{MEMORANDUM_LAW}:memorandum:{article}@{offset}'
    total = await db.memorandum_count(conn, article)
    if total == 0:
        await _log(conn, caller, 'get_memorandum', query)
        return f'لا توجد ملاحظات في المذكرة الإيضاحية مرتبطة بالمادة {article} من القانون المدني الأردني.'
    if offset >= total:
        await _log(conn, caller, 'get_memorandum', query)
        return f'لا ملاحظات بعد الموضع {offset}: للمادة {article} {total} ملاحظة في المذكرة الإيضاحية.'
    remaining = await _budget(conn, caps, caller, min(caps.max_results, total - offset))
    notes = await db.memorandum_page(conn, article, offset, remaining) if remaining > 0 else []
    await _log(conn, caller, 'get_memorandum', query, note_ids=[note.note_no for note in notes])
    if remaining == 0:
        return CAP_REACHED
    return format_memorandum(article, offset, notes, total)
