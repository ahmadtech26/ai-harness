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

`caps` are the normal caps of the caller's tier (server.py passes `caps=guard.caps_for(caller.tier)` from the same
snapshot); without `guard` no flag is consulted and nothing is detected. Each row records the caller's tier, which the
detector reads back (guard_settings.TIERED). `config` is the search config
search_law ranks with: the server's own (search_config.search_config_from_env), DEFAULT unless the timing stack
sets one."""

import time
from dataclasses import dataclass, replace

from psycopg import AsyncConnection

from legal_search import db, post_search, spans
from legal_search import guard as sweep
from legal_search.caps import Caps, Grant, grant, left_for_answer
from legal_search.citation import format_articles, format_memorandum
from legal_search.detector import article_key
from legal_search.events import Attempt
from legal_search.guard_settings import GuardSettings
from legal_search.search_config import DEFAULT, SearchConfig, tag

CAP_PREFIX = 'تم بلوغ الحد المسموح من النصوص'
CAP_ANSWER = (CAP_PREFIX + ' لهذه الإجابة. لا تستدعِ أدوات المكتبة بعد الآن في هذه الإجابة؛ '
              'أجب بما استُرجع وحده، واذكر للمستخدم بموضوعها النقاط التي بقيت دون نص مسترجع.')
CAP_DAILY = (CAP_PREFIX + ' لهذا اليوم في هذا الحساب. لا تستدعِ أدوات المكتبة بعد الآن في هذه الإجابة؛ '
             'أجب بما استُرجع وحده، واذكر للمستخدم بموضوعها النقاط التي بقيت دون نص مسترجع، وأن حد اليوم قد بلغ.')
NOT_FOUND_SEARCH = 'لم يُعثر على مواد مطابقة في المصادر المحمّلة.'
NOT_FOUND_ARTICLE = 'هذه المادة غير موجودة في المصادر المحمّلة.'
MEMORANDUM_HINT = 'للمادة مذكرة إيضاحية (get_memorandum)'
MEMORANDUM_LAW = 'civil-code'
SUSPENDED = 'تم إيقاف الوصول إلى المكتبة القانونية لهذا الحساب مؤقتًا. يُرجى التواصل مع الدعم.'
UNKNOWN_LAW = 'رمز القانون غير معروف'
QUERY_TOO_LONG = 'عبارة البحث أطول من الحد المسموح. يُرجى البحث بكلمات مفتاحية أقل.'
# The last line of every reply that serves under the caps (plan S3): what this answer may still receive, of its tier's
# allowance (decision.caps.per_answer, never the settings' fallback).
BUDGET_LINE = 'النصوص المتبقية لهذه الإجابة: {left} من {per_answer}.'
# A search whose every result was served to this answer already (plan S5b, with skip_served): its own first line, so the
# fork never reads it as a real not-found or a cap.
ALL_SERVED = 'كل ما وجده هذا البحث سبق تقديمه في هذه الإجابة؛ استشهد به كما ورد، أو ابحث بمصطلح آخر إن احتجت إلى غيره.'


@dataclass(frozen=True)
class Caller:
    user: str
    message: str | None
    conversation: str | None
    tier: str | None = None  # the X-Iqraa-Tier value when it is a plain id; None otherwise (timing.py passes none)


async def _used(conn: AsyncConnection, caller: Caller) -> tuple[int, int]:
    """The texts already served to this answer (none without a message id) and to this user in the last 24 hours."""
    used_for_answer = await db.documents_for_message(conn, caller.message) if caller.message else 0
    return used_for_answer, await db.documents_for_user_today(conn, caller.user)


async def _budget(conn: AsyncConnection, caps: Caps | None, caller: Caller, requested: int,
                  repeat: bool = False) -> Grant:
    """What this call may return under `caps` (nothing when suspended), and which cap refused it. `repeat`: the text
    was served to this answer already, so only the per-call and daily bounds apply (plan S5a)."""
    if caps is None:
        return Grant(0, None)
    used_for_answer, used_today = await _used(conn, caller)
    return grant(requested, 0 if repeat else used_for_answer, used_today, caps)


def _per_call(requested: int, used_today: int, caps: Caps) -> int:
    """The texts one call may return before the answer's allowance: the per-call and daily bounds, which count every
    text, a repeat too (plan S5a)."""
    return max(0, min(requested, caps.max_results, caps.daily - used_today))


def _grant_in_order(ids: list[int], served: frozenset[int], requested: int, used_for_answer: int, used_today: int,
                    caps: Caps) -> Grant:
    """How many of `ids` (a search's articles or a memorandum page's notes) this call may serve, in order (plan S5a):
    the per-call and daily bounds count every text; the answer's allowance counts only a text not yet served to it, so
    the list ends before the first new text past that allowance. With no texts at all, the grant of a new one
    (caps.grant): a cap already spent still refuses the call."""
    if not ids:
        return grant(requested, used_for_answer, used_today, caps)
    left_new, count = caps.per_answer - used_for_answer, 0
    for text_id in ids[:_per_call(requested, used_today, caps)]:
        if text_id not in served:
            if left_new <= 0:
                break
            left_new -= 1
        count += 1
    if count > 0:
        return Grant(count, None)
    return Grant(0, 'daily' if caps.daily - used_today <= 0 else 'per_answer')


def _with_budget(text: str, left: int, caps: Caps) -> str:
    """The reply with the remaining-budget line as its LAST line. The first line is never touched: the fork's guard
    (grounding.ts isLibraryText, notFoundKeysOf) and client (output.ts) read a reply by how it starts. The line holds no
    «المادة», so the guard's cross-reference reader finds no citation in it (F5 proves it)."""
    return f'{text}\n\n{BUDGET_LINE.format(left=left, per_answer=caps.per_answer)}'


async def _budgeted(conn: AsyncConnection, caller: Caller, caps: Caps, text: str) -> str:
    """`text` with the budget line, its remainder read after this call's log row, as the next call's budget counts it."""
    return _with_budget(text, left_for_answer(*await _used(conn, caller), caps), caps)


@dataclass(frozen=True)
class _Call:
    """What a call's log row records besides its attempt (FRP 2.6, plan S6): when the tool was entered (its duration is
    taken when the row is written), and for search_law the model's limit and the engine tag once a search runs."""
    started: float
    limit: int | None = None
    engine: str | None = None


async def _record(conn: AsyncConnection, call: _Call, caller: Caller, attempt: Attempt, query: str,
                  decision: sweep.Decision, outcome: str, article_ids: list[int] | None = None,
                  note_ids: list[int] | None = None, candidate_ids: list[int] | None = None,
                  cap_bound: str | None = None) -> None:
    """The call's log row and its flag change in one transaction; the alerts once it has committed."""
    async with conn.transaction():
        log_id = await db.log_retrieval(
            conn, user_id=caller.user, message_id=caller.message, conversation_id=caller.conversation,
            tool=attempt.tool, query=query, article_ids=article_ids or [], note_ids=note_ids or [],
            requested_law=attempt.law, requested_number=attempt.number, requested_suffix=attempt.suffix,
            outcome=outcome, candidate_ids=candidate_ids, duration_ms=(time.perf_counter() - call.started) * 1000.0,
            requested_limit=call.limit, engine=call.engine, cap_bound=cap_bound, tier=caller.tier,
        )
        alerts = await sweep.commit(conn, caller.user, decision, log_id)
    sweep.raise_alerts(alerts)


async def _refuse(conn: AsyncConnection, call: _Call, caller: Caller, attempt: Attempt, query: str,
                  decision: sweep.Decision, bound: str | None = None, candidate_ids: list[int] | None = None) -> str:
    """Logs a call that serves nothing under the guard's decision; returns the text the model receives. `bound` is
    the cap that refused it (caps.Grant), logged as cap_bound. A throttled account gets the daily text whichever cap
    refused it, so the reply never speaks of the sweep guard."""
    await _record(conn, call, caller, attempt, query, decision, decision.refusal, candidate_ids=candidate_ids,
                  cap_bound=bound)
    if decision.suspended:
        return SUSPENDED
    return CAP_DAILY if bound == 'daily' or decision.refusal == 'throttled' else CAP_ANSWER


async def _unknown_law(conn: AsyncConnection, law: str) -> str | None:
    """None for a loaded law; otherwise the message naming the slugs the library has. It never repeats `law`: the
    caller's text would come back as if the library had printed it (R1 n=7)."""
    slugs = await db.law_slugs(conn)
    if law in slugs:
        return None
    return f'{UNKNOWN_LAW}. الرموز المتاحة: {"، ".join(slugs)}.'


async def search_law(conn: AsyncConnection, caps: Caps, caller: Caller, query: str, limit: int = 5,
                     law: str | None = None, guard: GuardSettings | None = None, max_query: int | None = None,
                     config: SearchConfig = DEFAULT) -> str:
    call = _Call(time.perf_counter(), limit)
    law = (law or '').strip() or None  # models often send "" for an optional argument (plan A)
    # A query above `max_query` characters is not searched, and only its first `max_query` are stored (R2 n=19);
    # None sets no bound (the owner sets it with the retrieval eval).
    too_long = max_query is not None and len(query) > max_query
    if too_long:
        query = query[:max_query]
    # A suspended user is refused before the search and its budget sums run, as by the other tools (R3 n=11).
    suspended = await sweep.suspension(conn, guard, caller.user)
    if suspended is not None:
        return await _refuse(conn, call, caller, Attempt('search_law', law, tier=caller.tier), query, suspended)
    if too_long or law is not None:
        fixed = QUERY_TOO_LONG if too_long else await _unknown_law(conn, law)  # the answer instead of a search
        if fixed:
            attempt = Attempt('search_law', law, tier=caller.tier)
            decision = await sweep.decide(conn, guard, caps, caller.user, attempt)
            if decision.suspended:
                return await _refuse(conn, call, caller, attempt, query, decision)
            await _record(conn, call, caller, attempt, query, decision, 'served')
            return fixed
    # The candidates are what this call would serve under the normal caps; the guard decides on them. The search runs as
    # deep as the per-call and daily bounds, which count every article; the answer's allowance counts only an article
    # not yet served to it (S5a), so a repeat is served even at a full allowance.
    # The spans time the whole-call splits (REQ-RAG-021); they record nothing unless a timing collector is set.
    async with spans.span('budget'):
        used_for_answer, used_today = await _used(conn, caller)
    served = await post_search.served_ids_for_message(conn, caller.message)
    # With skip_served, the articles already served to this answer are left out before the guard decides (S5b).
    excluded = served if config.skip_served else frozenset()
    async with spans.span('search'):
        ranked = await db.search(conn, query, _per_call(limit, used_today, caps), law=law, config=config,
                                 exclude_ids=excluded)
    budget = _grant_in_order([article.id for article in ranked], served, limit, used_for_answer, used_today, caps)
    candidates = ranked[:budget.count]
    call = replace(call, engine=tag(config))
    attempt = Attempt('search_law', law, keys=frozenset(article_key(f.law_slug, f.number, f.suffix) for f in candidates),
                      tier=caller.tier)
    async with spans.span('guard'):
        decision = await sweep.decide(conn, guard, caps, caller.user, attempt)
    candidate_ids = [article.id for article in candidates]
    if decision.suspended:  # this very call proved the sweep: nothing is served, and its candidates are logged
        return await _refuse(conn, call, caller, attempt, query, decision, None, candidate_ids)
    remaining = _grant_in_order(candidate_ids, served, limit, *await _used(conn, caller), decision.caps)
    if remaining.count == 0:
        return await _refuse(conn, call, caller, attempt, query, decision, remaining.bound, candidate_ids)
    found = candidates[:remaining.count]
    async with spans.span('log'):
        await _record(conn, call, caller, attempt, query, decision, 'served', [article.id for article in found],
                      candidate_ids=candidate_ids if len(found) < len(candidates) else None)
    if found:
        text = format_articles(found)
    elif excluded and await db.search(conn, query, 1, law=law, config=config):
        text = ALL_SERVED  # it matched, but only what this answer has already: never a real not-found (S5b)
    else:
        text = NOT_FOUND_SEARCH
    return await _budgeted(conn, caller, decision.caps, text)


async def get_article(conn: AsyncConnection, caps: Caps, caller: Caller, number: int, suffix: str = '',
                      law: str = 'civil-code', guard: GuardSettings | None = None) -> str:
    call = _Call(time.perf_counter())
    law = law.strip() or 'civil-code'  # plan A: a blank law is the default
    suffix = suffix.strip()
    query = f'{law}:{number}{suffix}'
    attempt = Attempt('get_article', law, number, suffix, tier=caller.tier)
    decision = await sweep.decide(conn, guard, caps, caller.user, attempt)
    if decision.suspended:
        return await _refuse(conn, call, caller, attempt, query, decision)
    unknown = await _unknown_law(conn, law)
    if unknown:
        await _record(conn, call, caller, attempt, query, decision, 'served')
        return unknown
    # The article first: one already served to this answer costs no slot of its allowance (S5a).
    article = await db.get_article(conn, law, number, suffix)
    repeat = article is not None and article.id in await post_search.served_ids_for_message(conn, caller.message)
    allowance = await _budget(conn, decision.caps, caller, 1, repeat)
    if allowance.count == 0:
        return await _refuse(conn, call, caller, attempt, query, decision, allowance.bound)
    await _record(conn, call, caller, attempt, query, decision, 'served', [article.id] if article else [])
    if article is None:
        return await _budgeted(conn, caller, decision.caps, NOT_FOUND_ARTICLE)
    text = format_articles([article])
    if law == MEMORANDUM_LAW and await db.memorandum_count(conn, number) > 0:
        text += f'\n{MEMORANDUM_HINT}'
    return await _budgeted(conn, caller, decision.caps, text)


async def get_memorandum(conn: AsyncConnection, caps: Caps, caller: Caller, article: int, offset: int = 0,
                         guard: GuardSettings | None = None) -> str:
    """One page of the Civil Code memorandum notes linked to `article`, in note_no order; each note is capped
    and logged. The call is a detector event for the Civil Code article it names."""
    call = _Call(time.perf_counter())
    offset = max(offset, 0)
    query = f'{MEMORANDUM_LAW}:memorandum:{article}@{offset}'
    attempt = Attempt('get_memorandum', MEMORANDUM_LAW, article, '', tier=caller.tier)
    decision = await sweep.decide(conn, guard, caps, caller.user, attempt)
    if decision.suspended:
        return await _refuse(conn, call, caller, attempt, query, decision)
    total = await db.memorandum_count(conn, article)
    if total == 0:
        await _record(conn, call, caller, attempt, query, decision, 'served')
        return await _budgeted(conn, caller, decision.caps,
                             f'لا توجد ملاحظات في المذكرة الإيضاحية مرتبطة بالمادة {article} من القانون المدني الأردني.')
    if offset >= total:
        await _record(conn, call, caller, attempt, query, decision, 'served')
        return await _budgeted(conn, caller, decision.caps,
                             f'لا ملاحظات بعد الموضع {offset}: للمادة {article} {total} ملاحظة في المذكرة الإيضاحية.')
    # The page first: a note already served to this answer costs no slot of its allowance (S5a).
    page = await db.memorandum_page(conn, article, offset, min(decision.caps.max_results, total - offset))
    served = await post_search.served_note_ids_for_message(conn, caller.message)
    remaining = _grant_in_order([note.note_no for note in page], served, len(page), *await _used(conn, caller),
                                decision.caps)
    if remaining.count == 0:
        return await _refuse(conn, call, caller, attempt, query, decision, remaining.bound)
    notes = page[:remaining.count]
    await _record(conn, call, caller, attempt, query, decision, 'served', note_ids=[note.note_no for note in notes])
    return await _budgeted(conn, caller, decision.caps, format_memorandum(article, offset, notes, total))
