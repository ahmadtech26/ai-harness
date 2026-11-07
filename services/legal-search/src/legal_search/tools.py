"""The legal library tools' behaviour, independent of MCP: the sweep guard, the caps, the retrieval log and
the text the model receives. server.py registers each function as an MCP tool.

Every call writes exactly one log row, served or refused, with what it asked for (requested_law,
requested_number, requested_suffix) and its outcome (served, capped, throttled, suspended): these rows are
the sweep detector's events. A search that serves fewer articles than it was decided on (refused or
trimmed) also logs those candidates (candidate_ids), so the simulation decides it as the guard did. The
guard decides before the budget is computed, so the call that crosses a threshold is served (or refused)
under the new state, and a suspended user's every retrieval gets the suspension message. The log row and
any flag change are written in one transaction; alerts follow it.
`conn` must be an autocommit connection (every caller's is): on a plain one, `conn.transaction()` is only a
savepoint, and an alert would go out before the real commit.

`caps` are the normal caps. `guard` is the current guard settings (server.py passes `caps=guard.caps` from
the same snapshot); without `guard` no flag is consulted and nothing is detected."""

from dataclasses import dataclass

from psycopg import AsyncConnection

from legal_search import db
from legal_search import guard as sweep
from legal_search.caps import Caps, allowed
from legal_search.citation import format_articles, format_memorandum
from legal_search.detector import article_key
from legal_search.events import Attempt
from legal_search.guard_settings import GuardSettings

CAP_REACHED = 'تم بلوغ الحد المسموح من النصوص لهذه الإجابة أو لهذا اليوم. يُرجى الاعتماد على ما سبق استرجاعه.'
NOT_FOUND_SEARCH = 'لم يُعثر على مواد مطابقة في المصادر المحمّلة.'
NOT_FOUND_ARTICLE = 'هذه المادة غير موجودة في المصادر المحمّلة.'
MEMORANDUM_HINT = 'للمادة مذكرة إيضاحية (get_memorandum)'
MEMORANDUM_LAW = 'civil-code'
SUSPENDED = 'تم إيقاف الوصول إلى المكتبة القانونية لهذا الحساب مؤقتًا. يُرجى التواصل مع الدعم.'
UNKNOWN_LAW = 'رمز القانون غير معروف'


@dataclass(frozen=True)
class Caller:
    user: str
    message: str | None
    conversation: str | None


async def _budget(conn: AsyncConnection, caps: Caps | None, caller: Caller, requested: int) -> int:
    """Documents this call may return under `caps` (none when suspended)."""
    if caps is None:
        return 0
    used_for_answer = await db.documents_for_message(conn, caller.message) if caller.message else 0
    used_today = await db.documents_for_user_today(conn, caller.user)
    return allowed(requested, used_for_answer, used_today, caps)


async def _record(conn: AsyncConnection, caller: Caller, attempt: Attempt, query: str, decision: sweep.Decision,
                  outcome: str, article_ids: list[int] | None = None, note_ids: list[int] | None = None,
                  candidate_ids: list[int] | None = None) -> None:
    """The call's log row and its flag change in one transaction; the alerts once it has committed."""
    async with conn.transaction():
        log_id = await db.log_retrieval(
            conn, user_id=caller.user, message_id=caller.message, conversation_id=caller.conversation,
            tool=attempt.tool, query=query, article_ids=article_ids or [], note_ids=note_ids or [],
            requested_law=attempt.law, requested_number=attempt.number, requested_suffix=attempt.suffix,
            outcome=outcome, candidate_ids=candidate_ids,
        )
        alerts = await sweep.commit(conn, caller.user, decision, log_id)
    sweep.raise_alerts(alerts)


async def _refuse(conn: AsyncConnection, caller: Caller, attempt: Attempt, query: str, decision: sweep.Decision,
                  candidate_ids: list[int] | None = None) -> str:
    """Logs a call that serves nothing under the guard's decision; returns the text the model receives."""
    await _record(conn, caller, attempt, query, decision, decision.refusal, candidate_ids=candidate_ids)
    return SUSPENDED if decision.suspended else CAP_REACHED


async def _unknown_law(conn: AsyncConnection, law: str) -> str | None:
    """None for a loaded law; otherwise the message naming the slugs the library has. It never repeats `law`: the
    caller's text would come back as if the library had printed it (R1 n=7)."""
    slugs = await db.law_slugs(conn)
    if law in slugs:
        return None
    return f'{UNKNOWN_LAW}. الرموز المتاحة: {"، ".join(slugs)}.'


async def search_law(conn: AsyncConnection, caps: Caps, caller: Caller, query: str, limit: int = 5,
                     law: str | None = None, guard: GuardSettings | None = None) -> str:
    law = (law or '').strip() or None  # models often send "" for an optional argument (plan A)
    if law is not None:
        unknown = await _unknown_law(conn, law)
        if unknown:
            attempt = Attempt('search_law', law)
            decision = await sweep.decide(conn, guard, caps, caller.user, attempt)
            if decision.suspended:
                return await _refuse(conn, caller, attempt, query, decision)
            await _record(conn, caller, attempt, query, decision, 'served')
            return unknown
    # The candidates are what this call would serve under the normal caps; the guard decides on them.
    candidates = await db.search(conn, query, await _budget(conn, caps, caller, limit), law=law)
    attempt = Attempt('search_law', law, keys=frozenset(article_key(f.law_slug, f.number, f.suffix) for f in candidates))
    decision = await sweep.decide(conn, guard, caps, caller.user, attempt)
    candidate_ids = [article.id for article in candidates]
    remaining = await _budget(conn, decision.caps, caller, limit)
    if remaining == 0:
        return await _refuse(conn, caller, attempt, query, decision, candidate_ids)
    found = candidates[:remaining]
    await _record(conn, caller, attempt, query, decision, 'served', [article.id for article in found],
                  candidate_ids=candidate_ids if len(found) < len(candidates) else None)
    return format_articles(found) or NOT_FOUND_SEARCH


async def get_article(conn: AsyncConnection, caps: Caps, caller: Caller, number: int, suffix: str = '',
                      law: str = 'civil-code', guard: GuardSettings | None = None) -> str:
    law = law.strip() or 'civil-code'  # plan A: a blank law is the default
    suffix = suffix.strip()
    query = f'{law}:{number}{suffix}'
    attempt = Attempt('get_article', law, number, suffix)
    decision = await sweep.decide(conn, guard, caps, caller.user, attempt)
    if decision.suspended:
        return await _refuse(conn, caller, attempt, query, decision)
    unknown = await _unknown_law(conn, law)
    if unknown:
        await _record(conn, caller, attempt, query, decision, 'served')
        return unknown
    if await _budget(conn, decision.caps, caller, 1) == 0:
        return await _refuse(conn, caller, attempt, query, decision)
    article = await db.get_article(conn, law, number, suffix)
    await _record(conn, caller, attempt, query, decision, 'served', [article.id] if article else [])
    if article is None:
        return NOT_FOUND_ARTICLE
    text = format_articles([article])
    if law == MEMORANDUM_LAW and await db.memorandum_count(conn, number) > 0:
        text += f'\n{MEMORANDUM_HINT}'
    return text


async def get_memorandum(conn: AsyncConnection, caps: Caps, caller: Caller, article: int, offset: int = 0,
                         guard: GuardSettings | None = None) -> str:
    """One page of the Civil Code memorandum notes linked to `article`, in note_no order; each note is capped
    and logged. The call is a detector event for the Civil Code article it names."""
    offset = max(offset, 0)
    query = f'{MEMORANDUM_LAW}:memorandum:{article}@{offset}'
    attempt = Attempt('get_memorandum', MEMORANDUM_LAW, article, '')
    decision = await sweep.decide(conn, guard, caps, caller.user, attempt)
    if decision.suspended:
        return await _refuse(conn, caller, attempt, query, decision)
    total = await db.memorandum_count(conn, article)
    if total == 0:
        await _record(conn, caller, attempt, query, decision, 'served')
        return f'لا توجد ملاحظات في المذكرة الإيضاحية مرتبطة بالمادة {article} من القانون المدني الأردني.'
    if offset >= total:
        await _record(conn, caller, attempt, query, decision, 'served')
        return f'لا ملاحظات بعد الموضع {offset}: للمادة {article} {total} ملاحظة في المذكرة الإيضاحية.'
    remaining = await _budget(conn, decision.caps, caller, min(decision.caps.max_results, total - offset))
    if remaining == 0:
        return await _refuse(conn, caller, attempt, query, decision)
    notes = await db.memorandum_page(conn, article, offset, remaining)
    await _record(conn, caller, attempt, query, decision, 'served', note_ids=[note.note_no for note in notes])
    return format_memorandum(article, offset, notes, total)
