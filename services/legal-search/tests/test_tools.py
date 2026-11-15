import os
import re
from dataclasses import replace

import pytest
from psycopg import AsyncConnection

from legal_search import db, flags, post_search, tools
from legal_search.caps import Caps
from legal_search.citation import format_articles
from legal_search.corpus import Article
from legal_search.guard_settings import GuardSettings
from legal_search.registry import Law
from legal_search.search_config import DEFAULT
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

CAPS = Caps(per_answer=8, daily=300, max_results=5)
CALLER = tools.Caller('u1', 'm1', 'c1')

# The four texts the owner approved (plan S2, S3 and S5b; Owner answers OQ1), written out here rather than read
# from tools, so a change to any of them fails these tests (Codex round 1). The fork and the edition copy them
# byte for byte.
CAP_ANSWER = ('تم بلوغ الحد المسموح من النصوص لهذه الإجابة. لا تستدعِ أدوات المكتبة بعد الآن في هذه الإجابة؛ '
              'أجب بما استُرجع وحده، واذكر للمستخدم بموضوعها النقاط التي بقيت دون نص مسترجع.')
CAP_DAILY = ('تم بلوغ الحد المسموح من النصوص لهذا اليوم في هذا الحساب. لا تستدعِ أدوات المكتبة بعد الآن في هذه الإجابة؛ '
             'أجب بما استُرجع وحده، واذكر للمستخدم بموضوعها النقاط التي بقيت دون نص مسترجع، وأن حد اليوم قد بلغ.')
BUDGET_LINE = 'النصوص المتبقية لهذه الإجابة: {left} من {per_answer}.'
ALL_SERVED = ('كل ما وجده هذا البحث سبق تقديمه في هذه الإجابة؛ '
              'استشهد به كما ورد، أو ابحث بمصطلح آخر إن احتجت إلى غيره.')


def _line(left: int, per_answer: int = 8) -> str:
    """The remaining-budget line a reply ends with (plan S3)."""
    return BUDGET_LINE.format(left=left, per_answer=per_answer)


LAWS = [Law(slug='civil-code', title='القانون المدني الأردني', folder='c'), Law(slug='penal-code', title='قانون العقوبات الأردني', folder='p')]
ARTICLES = [
    Article('civil-code', 'x', 1, '', 'تسري نصوص هذا القانون على المسائل التي تتناولها.', 's', 'a.md'),
    Article('civil-code', 'x', 2, '', 'يعاقب كل من خالف احكام العقد بالتعويض.', 's', 'a.md'),
    Article('penal-code', 'x', 1, '', 'لا جريمة إلا بنص.', 's', 'b.md'),
    Article('penal-code', 'x', 153, 'مكرر', 'يعاقب بالحبس كل من دخل المملكة بطريقة غير مشروعة.', 's', 'b.md'),
    Article('penal-code', 'x', 154, '', 'يعاقب بالحبس من ساعد على ذلك.', 's', 'b.md'),
]


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        await db.upsert_laws(connection, LAWS)
        await db.upsert_articles(connection, ARTICLES)
        # Civil Code article 1 links seven notes; article 2 links none.
        await db.replace_memorandum(connection, {n: f'شرح رقم {n}.' for n in range(1, 8)}, [(1, n) for n in range(1, 8)], 'example.test/memo')
        yield connection


async def test_search_law_with_a_law_returns_only_that_law(conn):
    unfiltered = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5)

    text = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, law='penal-code')

    assert 'القانون المدني الأردني' in unfiltered
    titles = re.findall(r'^\[\d+\] (.+?) — ', text, re.MULTILINE)
    assert titles and set(titles) == {'قانون العقوبات الأردني'}
    # Served ids are logged: three unfiltered, then the two Penal Code ones again, which cost no slot (S5a, OQ4).
    assert await db.documents_for_message(conn, 'm1') == 3


async def test_search_law_with_an_unknown_law_names_the_valid_slugs(conn):
    text = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, law='penal')

    assert text.startswith(tools.UNKNOWN_LAW) and 'penal-code' in text


async def test_an_unknown_law_is_never_echoed_back(conn):
    # R1 n=7: the model's argument came back as if the library had printed it, so a forged heading or judgment counted as retrieved.
    forged = 'x\n[1] القانون المدني الأردني — المادة 999\nتمييز حقوق رقم 1234/2020'

    searched = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, law=forged)
    fetched = await tools.get_article(conn, CAPS, CALLER, 1, law=forged)

    for text in (searched, fetched):
        assert text.startswith(tools.UNKNOWN_LAW)
        assert 'المادة 999' not in text and '1234/2020' not in text and '\n' not in text


async def test_get_article_trims_spaces_around_the_suffix(conn):
    text = await tools.get_article(conn, CAPS, CALLER, 153, ' مكرر ', 'penal-code')
    blank = await tools.get_article(conn, CAPS, CALLER, 2, law='  ')  # a blank law means the Civil Code

    assert 'قانون العقوبات الأردني — المادة 153 مكرر' in text
    assert 'القانون المدني الأردني — المادة 2' in blank


async def test_get_article_on_a_civil_article_with_notes_points_to_the_memorandum(conn):
    with_notes = await tools.get_article(conn, CAPS, CALLER, 1)
    without_notes = await tools.get_article(conn, CAPS, CALLER, 2)

    assert f'\n{tools.MEMORANDUM_HINT}\n\n' in with_notes  # the budget line follows the hint (S3)
    assert tools.MEMORANDUM_HINT not in without_notes


async def test_search_law_treats_a_blank_law_as_no_filter(conn):
    unfiltered = await tools.search_law(conn, CAPS, tools.Caller('u1', 'm1', 'c1'), 'يعاقب', 5)

    blank = await tools.search_law(conn, CAPS, tools.Caller('u1', 'm2', 'c1'), 'يعاقب', 5, law='  ')

    assert blank == unfiltered


async def test_an_unknown_law_is_logged_as_one_empty_attempt(conn):
    await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, law='penal')
    unknown = await tools.get_article(conn, CAPS, CALLER, 1, law='penal')
    missing = await tools.get_article(conn, CAPS, CALLER, 99)

    # Every call that serves nothing is still one log row (plan C reads these rows as attempts).
    assert unknown.startswith(tools.UNKNOWN_LAW) and missing.startswith(tools.NOT_FOUND_ARTICLE)
    cur = await conn.execute('SELECT tool, query, article_ids, note_ids FROM retrieval_log ORDER BY id')
    assert await cur.fetchall() == [
        ('search_law', 'يعاقب', [], []), ('get_article', 'penal:1', [], []), ('get_article', 'civil-code:99', [], []),
    ]


async def test_get_article_gives_the_memorandum_hint_only_for_the_civil_code(conn):
    # Memorandum links key on the article number alone: penal-code article 1 must not inherit civil-code's notes.
    text = await tools.get_article(conn, CAPS, CALLER, 1, law='penal-code')

    assert 'قانون العقوبات الأردني — المادة 1' in text
    assert tools.MEMORANDUM_HINT not in text


async def test_an_article_slug_is_known_before_its_registry_entry_loads(conn):
    await db.upsert_articles(conn, [Article('labour', 'قانون العمل', 2, '', 'يقصد بالعامل كل شخص.', 's', 'l.md')])

    text = await tools.get_article(conn, CAPS, CALLER, 2, law='labour')

    assert 'المادة 2' in text
    assert not text.startswith('رمز القانون غير معروف')


async def test_get_memorandum_returns_the_first_page_with_the_remaining_count(conn):
    text = await tools.get_memorandum(conn, CAPS, CALLER, 1)

    assert [int(n) for n in re.findall(r'\[ملاحظة (\d+)\]', text)] == [1, 2, 3, 4, 5]
    assert 'الملاحظات المتبقية: 2' in text and 'offset=5' in text


async def test_get_memorandum_from_an_offset_returns_the_rest(conn):
    text = await tools.get_memorandum(conn, CAPS, CALLER, 1, offset=5)

    assert [int(n) for n in re.findall(r'\[ملاحظة (\d+)\]', text)] == [6, 7]
    assert text.endswith('لا ملاحظات أخرى لهذه المادة.\n\n' + _line(6))


async def test_get_memorandum_logs_each_note_against_the_caps(conn):
    await tools.get_memorandum(conn, CAPS, CALLER, 1)

    cur = await conn.execute('SELECT tool, query, note_ids FROM retrieval_log')
    assert await cur.fetchall() == [('get_memorandum', 'civil-code:memorandum:1@0', [1, 2, 3, 4, 5])]
    assert await db.documents_for_message(conn, 'm1') == 5


async def test_get_memorandum_is_cut_to_what_the_answer_cap_leaves(conn):
    caps = Caps(per_answer=4, daily=300, max_results=5)
    await tools.get_article(conn, caps, CALLER, 1)  # this answer has already used one of its four

    text = await tools.get_memorandum(conn, caps, CALLER, 1)

    assert [int(n) for n in re.findall(r'\[ملاحظة (\d+)\]', text)] == [1, 2, 3]
    assert 'الملاحظات المتبقية: 4' in text
    # The answer has now used all four: each tool refuses and logs an empty attempt.
    refused = [await tools.get_memorandum(conn, caps, CALLER, 1, offset=3), await tools.get_article(conn, caps, CALLER, 2),
               await tools.search_law(conn, caps, CALLER, 'يعاقب', 5)]
    assert refused == [CAP_ANSWER] * 3
    cur = await conn.execute('SELECT article_ids, note_ids FROM retrieval_log ORDER BY id OFFSET 2')
    assert await cur.fetchall() == [([], [])] * 3


async def test_get_memorandum_without_notes_says_none_exist(conn):
    text = await tools.get_memorandum(conn, CAPS, CALLER, 2)

    assert text == 'لا توجد ملاحظات في المذكرة الإيضاحية مرتبطة بالمادة 2 من القانون المدني الأردني.\n\n' + _line(8)
    cur = await conn.execute('SELECT query, note_ids FROM retrieval_log')
    assert await cur.fetchall() == [('civil-code:memorandum:2@0', [])]


async def test_get_memorandum_past_the_last_note_says_so_and_logs_an_empty_attempt(conn):
    text = await tools.get_memorandum(conn, CAPS, CALLER, 1, offset=7)

    assert text == 'لا ملاحظات بعد الموضع 7: للمادة 1 7 ملاحظة في المذكرة الإيضاحية.\n\n' + _line(8)
    cur = await conn.execute('SELECT query, note_ids FROM retrieval_log')
    assert await cur.fetchall() == [('civil-code:memorandum:1@7', [])]


async def test_a_search_above_the_query_bound_is_not_run_and_only_the_bound_is_stored(conn, monkeypatch):
    # R2 n=19: a pasted contract was ranked on a shared connection and stored whole in the retrieval log.
    searched = []
    real = db.search

    async def spy(*args, **kwargs):
        searched.append(args[1])
        return await real(*args, **kwargs)

    monkeypatch.setattr(db, 'search', spy)

    text = await tools.search_law(conn, CAPS, CALLER, 'يعاقب كل من خالف العقد ' * 250, 5, max_query=200)

    cur = await conn.execute('SELECT length(query), article_ids FROM retrieval_log')
    assert (text, searched) == (tools.QUERY_TOO_LONG, [])
    assert await cur.fetchall() == [(200, [])]


# FRP 2.2 / plan S2: a refusal says which cap refused it; neither text names a number or the sweep guard.
async def test_a_search_refused_at_the_answer_cap_gets_CAP_ANSWER(conn):
    caps = Caps(per_answer=2, daily=300, max_results=5)
    await tools.search_law(conn, caps, CALLER, 'يعاقب', 5)  # serves two of the three matches: the answer's cap
    new = await db.search(conn, 'جريمة', 5)  # a match no search has served: a repeat would be free (S5a)

    text = await tools.search_law(conn, caps, CALLER, 'جريمة', 5)

    assert [(f.law_slug, f.number) for f in new] == [('penal-code', 1)] and text == CAP_ANSWER


async def test_a_call_refused_at_the_daily_cap_gets_CAP_DAILY(conn):
    caps = Caps(per_answer=8, daily=2, max_results=5)
    await tools.search_law(conn, caps, CALLER, 'يعاقب', 5)  # two texts today: the day's cap

    texts = [await tools.search_law(conn, caps, tools.Caller('u1', 'm2', 'c1'), 'يعاقب', 5),
             await tools.search_law(conn, caps, CALLER, 'يعاقب', 5)]  # both caps spent: the daily one is named

    assert texts == [CAP_DAILY] * 2


async def test_a_throttled_account_gets_CAP_DAILY_and_no_word_of_a_throttle(conn):
    settings = replace(GuardSettings(), per_answer=2)
    await flags.open_new(conn, 'u1', 'suspected', 0, [])
    await tools.search_law(conn, settings.caps, CALLER, 'يعاقب', 5, guard=settings)  # two texts: the answer's cap

    # Refused at the answer's cap, under the throttle: the daily text, as for any throttled refusal.
    text = await tools.get_article(conn, settings.caps, CALLER, 1, guard=settings)

    cur = await conn.execute('SELECT outcome FROM retrieval_log ORDER BY id DESC LIMIT 1')
    assert (text, (await cur.fetchone())[0]) == (CAP_DAILY, 'throttled')


async def test_a_suspended_account_still_gets_SUSPENDED(conn):
    settings = GuardSettings()
    await flags.open_new(conn, 'u1', 'proven', 0, [])

    texts = [await tools.search_law(conn, settings.caps, CALLER, 'يعاقب', 5, guard=settings),
             await tools.get_article(conn, settings.caps, CALLER, 1, guard=settings),
             await tools.get_memorandum(conn, settings.caps, CALLER, 1, guard=settings)]

    assert texts == [tools.SUSPENDED] * 3


async def test_get_article_and_get_memorandum_refuse_with_the_same_two_texts(conn):
    at_answer_cap = Caps(per_answer=1, daily=300, max_results=5)
    at_daily_cap = Caps(per_answer=8, daily=1, max_results=5)
    await tools.get_article(conn, at_answer_cap, CALLER, 2)  # one text for m1, and one today

    texts = [await tools.get_article(conn, at_answer_cap, CALLER, 1),
             await tools.get_memorandum(conn, at_answer_cap, CALLER, 1),
             await tools.get_article(conn, at_daily_cap, tools.Caller('u1', 'm2', 'c1'), 1),
             await tools.get_memorandum(conn, at_daily_cap, tools.Caller('u1', 'm2', 'c1'), 1)]

    assert texts == [CAP_ANSWER, CAP_ANSWER, CAP_DAILY, CAP_DAILY]


def test_every_cap_reply_begins_with_CAP_PREFIX():
    # The fork's guard and client recognise a cap of either kind (and of the old image) by this prefix.
    assert tools.CAP_ANSWER.startswith(tools.CAP_PREFIX) and tools.CAP_DAILY.startswith(tools.CAP_PREFIX)


# FRP 2.3 / plan S3: every reply that went through a budget computation ends with the remaining-budget line, read after
# the call's own log row. Replies are compared with format_articles(...), never literal article text (invariant 5).
async def test_a_served_search_ends_with_the_budget_line_after_the_last_articles_details_line(conn):
    found = await db.search(conn, 'يعاقب', 5)

    text = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5)

    assert len(found) == 3 and text == format_articles(found) + '\n\n' + _line(5)


async def test_the_line_counts_this_call_5_served_of_8_leaves_3(conn):
    text = await tools.get_memorandum(conn, CAPS, CALLER, 1)

    assert re.findall(r'\[ملاحظة (\d+)\]', text) == ['1', '2', '3', '4', '5'] and text.endswith('\n\n' + _line(3))


async def test_a_throttled_accounts_line_shows_the_smaller_daily_remainder(conn):
    settings = replace(GuardSettings(), throttle_daily_cap=6)
    await flags.open_new(conn, 'u1', 'suspected', 0, [])

    text = await tools.get_memorandum(conn, settings.caps, CALLER, 1, guard=settings)  # five notes of the six a day

    assert text.endswith('\n\n' + _line(1))


async def test_get_articles_line_comes_after_the_memorandum_hint(conn):
    article = await db.get_article(conn, 'civil-code', 1, '')

    text = await tools.get_article(conn, CAPS, CALLER, 1)

    assert text == format_articles([article]) + f'\n{tools.MEMORANDUM_HINT}\n\n' + _line(7)


async def test_a_not_found_reply_keeps_its_fixed_first_line_and_ends_with_the_line(conn):
    texts = [await tools.search_law(conn, CAPS, CALLER, 'طائرة', 5), await tools.get_article(conn, CAPS, CALLER, 99)]

    assert texts == [tools.NOT_FOUND_SEARCH + '\n\n' + _line(8), tools.NOT_FOUND_ARTICLE + '\n\n' + _line(8)]


async def test_a_refusal_a_suspension_an_unknown_law_and_a_query_that_is_too_long_carry_no_budget_line(conn):
    settings = GuardSettings()
    spent = Caps(per_answer=1, daily=300, max_results=5)
    await tools.get_article(conn, spent, CALLER, 2)
    refused = await tools.get_article(conn, spent, CALLER, 1)
    unknown = await tools.get_article(conn, CAPS, CALLER, 1, law='penal')
    too_long = await tools.search_law(conn, CAPS, CALLER, 'يعاقب ' * 50, 5, max_query=20)
    await flags.open_new(conn, 'u2', 'proven', 0, [])
    suspended = await tools.search_law(conn, settings.caps, tools.Caller('u2', 'm9', 'c1'), 'يعاقب', 5, guard=settings)

    assert (refused, suspended, too_long) == (CAP_ANSWER, tools.SUSPENDED, tools.QUERY_TOO_LONG)
    assert unknown.startswith(tools.UNKNOWN_LAW) and BUDGET_LINE.partition('{')[0] not in unknown


# Plan S4 and S4b: the server passes settings.caps_for(caller.tier); each tier is refused after its own allowance and
# its own daily cap. guard=None: these walks are about the caps, not the sweep detector.
TIERS = ('iqraa-fast', 'iqraa-advanced', 'iqraa-expert')
LABOUR = [Article('labour', 'قانون العمل', n, '', f'نص المادة {n} من قانون العمل للاختبار.', 's', 'l.md') for n in range(1, 21)]


async def test_each_tier_is_refused_after_its_own_allowance(conn):
    await db.upsert_articles(conn, LABOUR)
    settings = replace(GuardSettings(), per_answer_advanced=11, per_answer_expert=16)

    refused_at = []
    for tier in TIERS:
        caller = tools.Caller(f'u-{tier}', f'm-{tier}', 'c1', tier)
        texts = [await tools.get_article(conn, settings.caps_for(tier), caller, n, law='labour') for n in range(1, 18)]
        refused_at.append(texts.index(CAP_ANSWER) + 1)

    assert refused_at == [9, 12, 17]


async def test_each_tier_is_refused_after_its_own_daily_cap(conn):
    await db.upsert_articles(conn, LABOUR)
    settings = replace(GuardSettings(), daily=2, daily_advanced=3, daily_expert=4, throttle_daily_cap=1)

    refused_at = []
    for tier in (*TIERS, 'iqraa-other', None):
        texts = [await tools.get_article(conn, settings.caps_for(tier), tools.Caller(f'u-{tier}', f'm-{tier}-{n}', 'c1', tier),
                                         n, law='labour') for n in range(1, 7)]
        refused_at.append(texts.index(CAP_DAILY) + 1)

    assert refused_at == [3, 4, 5, 3, 3]  # an unknown tier, and none, get the lowest


async def test_a_call_logs_its_tier_or_null_without_one(conn):
    # Plan S6's tier column, written from S4b on: the detector reads it back for the highest tier in the window.
    from legal_search import events

    await tools.get_article(conn, CAPS, tools.Caller('u1', 'm1', 'c1', 'iqraa-expert'), 1)
    await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5)

    cur = await conn.execute('SELECT tier FROM retrieval_log ORDER BY id')
    history, _ = await events.load_user_events(conn, 'u1', 0, events.BASE_LOOKBACK)
    assert [row[0] for row in await cur.fetchall()] == [event.tier for event in history] == ['iqraa-expert', None]


# Plan S5a (owner 2026-11-14, OQ4): a text already served in this answer costs no slot of its allowance. A repeat still
# counts against the daily cap, and the per-call bound counts every text.
async def test_a_repeated_get_article_is_served_and_costs_no_slot(conn):
    first = await tools.get_article(conn, CAPS, CALLER, 2)

    again = await tools.get_article(conn, CAPS, CALLER, 2)

    assert again == first and again.endswith('\n\n' + _line(7))
    assert await db.documents_for_message(conn, 'm1') == 1


async def test_a_repeated_get_article_is_served_at_the_answer_cap_but_not_past_the_daily_cap(conn):
    caps = Caps(per_answer=1, daily=2, max_results=5)
    served = await tools.get_article(conn, caps, CALLER, 2)
    refused = await tools.get_article(conn, caps, CALLER, 1)  # a new text past the answer's one

    repeats = [await tools.get_article(conn, caps, CALLER, 2) for _ in range(2)]  # the day's second text, then none

    assert served.startswith('[1] ') and (refused, repeats) == (CAP_ANSWER, [served, CAP_DAILY])


async def test_a_repeated_memorandum_page_is_served_and_costs_no_slot(conn):
    first = await tools.get_memorandum(conn, CAPS, CALLER, 1)

    again = await tools.get_memorandum(conn, CAPS, CALLER, 1)

    assert again == first and again.endswith('\n\n' + _line(3))
    assert await db.documents_for_message(conn, 'm1') == 5


async def test_a_memorandum_page_ends_before_the_first_new_note_past_the_answer_cap(conn):
    caps = Caps(per_answer=6, daily=300, max_results=5)
    await tools.get_memorandum(conn, caps, CALLER, 1)  # notes 1-5: five of the six

    text = await tools.get_memorandum(conn, caps, CALLER, 1, offset=3)  # 4 and 5 again, 6 new, 7 past the cap

    assert re.findall(r'\[ملاحظة (\d+)\]', text) == ['4', '5', '6'] and text.endswith('\n\n' + _line(0, 6))


# Codex round 1: a search ran only as deep as the answer's unused slots, so with skip_served off a repeat was cut, or
# refused at a full allowance. The per-call and daily bounds count every result; the allowance only a new article.
async def _answered(conn, searched: int, used: int) -> list:
    """The labour search's ranking, after the answer m1 was served its first `searched` results, then other labour
    articles until it had used `used` of its eight."""
    await db.upsert_articles(conn, LABOUR)
    ranked = await db.search(conn, 'العمل', 5, law='labour')
    await tools.search_law(conn, CAPS, CALLER, 'العمل', searched, law='labour')
    others = [article.number for article in LABOUR if article.number not in {found.number for found in ranked}]
    for number in others[:used - searched]:
        await tools.get_article(conn, CAPS, CALLER, number, law='labour')
    return ranked


async def test_five_repeats_at_7_of_8_are_all_served_and_still_count_for_the_day(conn):
    ranked = await _answered(conn, 5, 7)
    today = await db.documents_for_user_today(conn, 'u1')

    again = await tools.search_law(conn, CAPS, CALLER, 'العمل', 5, law='labour')

    assert again == format_articles(ranked) + '\n\n' + _line(1)
    assert await db.documents_for_user_today(conn, 'u1') == today + 5


async def test_a_search_of_repeats_only_at_8_of_8_is_served_not_refused(conn):
    ranked = await _answered(conn, 5, 8)

    again = await tools.search_law(conn, CAPS, CALLER, 'العمل', 5, law='labour')

    assert again == format_articles(ranked) + '\n\n' + _line(0)


async def test_a_search_past_the_allowance_ends_before_its_first_new_article(conn):
    ranked = await _answered(conn, 2, 7)  # the first two again, one new for the eighth slot, then a new one past it

    again = await tools.search_law(conn, CAPS, CALLER, 'العمل', 5, law='labour')

    assert again == format_articles(ranked[:3]) + '\n\n' + _line(0)


async def test_a_new_article_past_the_allowance_ends_the_search_before_the_repeats_after_it(conn):
    # [new, new, repeat, repeat, repeat] at 7 of 8: the eighth slot goes to the first new article and the list ends at
    # the second, as a memorandum page does (S5a); counting on past it would serve both new ones, nine in all.
    await db.upsert_articles(conn, LABOUR)
    ranked = await db.search(conn, 'العمل', 5, law='labour')
    others = [article.number for article in LABOUR if article.number not in {found.number for found in ranked}]
    for number in [found.number for found in ranked[2:]] + others[:4]:
        await tools.get_article(conn, CAPS, CALLER, number, law='labour')

    again = await tools.search_law(conn, CAPS, CALLER, 'العمل', 5, law='labour')

    assert (again, await db.documents_for_message(conn, 'm1')) == (format_articles(ranked[:1]) + '\n\n' + _line(0), 8)


# Plan S5b (FRP 2.8 / RP 6.4, amended): with skip_served, a search leaves out the articles already served to the answer.
SKIP = replace(DEFAULT, skip_served=True)
SKIP_BM25 = replace(DEFAULT, skip_served=True, ranker='bm25')


async def test_a_second_search_in_the_same_answer_serves_no_article_twice(conn):
    ranked = await db.search(conn, 'يعاقب', 5)
    await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 2, config=SKIP)

    second = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, config=SKIP)

    assert second == format_articles(ranked[2:]) + '\n\n' + _line(5)


async def test_another_message_is_unaffected(conn):
    await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 2, config=SKIP)

    other = await tools.search_law(conn, CAPS, tools.Caller('u1', 'm2', 'c1'), 'يعاقب', 5, config=SKIP)

    assert other.startswith(format_articles(await db.search(conn, 'يعاقب', 5)))


async def test_the_guard_decides_on_the_list_after_the_exclusion(conn, monkeypatch):
    ranked = await db.search(conn, 'يعاقب', 5)
    await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 2, config=SKIP)
    decided = []
    real = tools.sweep.decide

    async def spy(conn, settings, caps, user, attempt):
        decided.append(attempt.keys)
        return await real(conn, settings, caps, user, attempt)

    monkeypatch.setattr(tools.sweep, 'decide', spy)

    await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, config=SKIP, guard=GuardSettings())

    assert decided == [frozenset(f'{f.law_slug}|{f.number}|{f.suffix}' for f in ranked[2:])]


@pytest.mark.parametrize('config', [SKIP, SKIP_BM25], ids=['pg', 'bm25'])
async def test_the_skip_applies_under_both_rankers(conn, config):
    from legal_search import keyword_engine

    if config.ranker == 'bm25':
        await keyword_engine.CACHE.ensure(conn, config)  # built: the search is the engine's, not the fallback's
    await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 2, config=config)

    second = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, config=config)

    served = await post_search.served_ids_for_message(conn, 'm1')
    cur = await conn.execute('SELECT article_ids FROM retrieval_log ORDER BY id')
    first_ids, second_ids = [row[0] for row in await cur.fetchall()]
    assert len(first_ids) == 2 and len(second_ids) == 1 and not set(first_ids) & set(second_ids)
    assert served == frozenset(first_ids + second_ids) and second.startswith('[1] ')


async def test_a_search_whose_results_were_all_served_gets_ALL_SERVED_with_the_budget_line(conn):
    await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, config=SKIP)  # all three

    again = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5, config=SKIP)
    nothing = await tools.search_law(conn, CAPS, CALLER, 'طائرة', 5, config=SKIP)  # matches nothing at all

    assert again == ALL_SERVED + '\n\n' + _line(5)
    assert nothing == tools.NOT_FOUND_SEARCH + '\n\n' + _line(5)


async def test_with_the_flag_off_the_search_is_unchanged(conn):
    ranked = await db.search(conn, 'يعاقب', 5)
    await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 2)

    second = await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 5)

    assert second == format_articles(ranked) + '\n\n' + _line(5)  # the two served again cost no slot (S5a)


# FRP 2.6 / plan S6: retrieval_log's duration, the model's limit, the engine and the cap bound (the tier: S4b).
async def test_a_served_search_logs_its_duration_the_models_limit_and_the_engine_tag(conn):
    await tools.search_law(conn, CAPS, CALLER, 'يعاقب', 4, config=SKIP)

    cur = await conn.execute('SELECT duration_ms, requested_limit, engine, cap_bound FROM retrieval_log')
    duration, limit, engine, bound = await cur.fetchone()
    assert duration > 0 and (limit, engine, bound) == (4, 'pg:skip_served=True', None)


async def test_a_refused_call_logs_its_cap_bound(conn):
    at_answer_cap = Caps(per_answer=1, daily=300, max_results=5)
    await tools.get_article(conn, at_answer_cap, CALLER, 1)
    await tools.search_law(conn, at_answer_cap, CALLER, 'يعاقب', 5)
    await tools.get_memorandum(conn, Caps(per_answer=8, daily=1, max_results=5), tools.Caller('u1', 'm2', 'c1'), 1)

    cur = await conn.execute('SELECT outcome, cap_bound FROM retrieval_log ORDER BY id')
    assert await cur.fetchall() == [('served', None), ('capped', 'per_answer'), ('capped', 'daily')]


async def test_get_article_and_get_memorandum_log_a_duration_and_neither_limit_nor_engine(conn):
    await tools.get_article(conn, CAPS, CALLER, 1)
    await tools.get_memorandum(conn, CAPS, CALLER, 1)

    cur = await conn.execute('SELECT duration_ms > 0, requested_limit, engine FROM retrieval_log ORDER BY id')
    assert await cur.fetchall() == [(True, None, None)] * 2


# Codex round 1: requested_limit is an INT column, and the model's limit is any whole number. One beyond INT's range is
# logged at the nearest bound, and the call answers as it did before the column existed.
@pytest.mark.parametrize(('limit', 'logged'), [(2**31 - 1, 2**31 - 1), (2**31, 2**31 - 1), (-2**31 - 1, -2**31)],
                         ids=['int-max', 'past-int-max', 'past-int-min'])
async def test_a_limit_beyond_the_int_column_is_logged_at_its_bound(conn, limit, logged):
    await tools.search_law(conn, CAPS, CALLER, 'يعاقب', limit)

    cur = await conn.execute('SELECT requested_limit FROM retrieval_log')
    assert await cur.fetchall() == [(logged,)]


async def test_an_oversized_limit_is_still_served_up_to_max_results(conn):
    await db.upsert_articles(conn, LABOUR)
    found = await db.search(conn, 'العمل', 5, law='labour')

    text = await tools.search_law(conn, CAPS, CALLER, 'العمل', 2**31, law='labour')

    assert text == format_articles(found) + '\n\n' + _line(3)


async def test_create_schema_runs_twice_without_error_on_a_database_that_has_the_columns(conn):
    await db.create_schema(conn)
    await db.create_schema(conn)

    cur = await conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'retrieval_log' "
        "AND column_name IN ('duration_ms', 'requested_limit', 'engine', 'cap_bound', 'tier') ORDER BY 1")
    assert [row[0] for row in await cur.fetchall()] == ['cap_bound', 'duration_ms', 'engine', 'requested_limit', 'tier']
