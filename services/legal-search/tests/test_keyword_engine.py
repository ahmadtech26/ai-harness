"""The keyword engine behind db.search (recall plan Task 3.1, with the review notes of 2026-11-11 (b)-(e)).

Today's Postgres search finds most of these articles too, so a test that only read the results would pass through
the fallback: every engine-path test runs strict, counts the alerts, or records what reaches bm25.Index.search."""

import asyncio
import os
import threading

import pytest
from psycopg import AsyncConnection

from legal_search import bm25, db, keyword_engine
from legal_search.analysis import Today
from legal_search.corpus import Article
from legal_search.search_config import DEFAULT, with_overrides
from tests.pg import TABLES, fresh
from tests.test_search import ARTICLES

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

BM25 = with_overrides(DEFAULT, ['ranker=bm25'])
CIVIL = 'القانون المدني الأردني'


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        await db.upsert_articles(connection, ARTICLES)
        yield connection


def spy(monkeypatch) -> list[list[str]]:
    """The query terms of every call that reaches bm25.Index.search."""
    calls: list[list[str]] = []
    real = bm25.Index.search

    def recording(self, terms, *args, **kwargs):
        calls.append(list(terms))
        return real(self, terms, *args, **kwargs)

    monkeypatch.setattr(bm25.Index, 'search', recording)
    return calls


def boom(*args, **kwargs):
    raise RuntimeError('boom')


def fallbacks(alert_caplog) -> int:
    return sum('keyword_engine_fallback' in record.message for record in alert_caplog.records)


# The plan's tests (Task 3.1, Step 1), as written there.

async def test_bm25_results_are_found_rows_by_id_in_engine_order(conn, monkeypatch):
    calls = []
    real = bm25.Index.search
    monkeypatch.setattr(bm25.Index, 'search', lambda self, *a, **k: calls.append(1) or real(self, *a, **k))
    found = await db.search(conn, 'ما حكم العربون؟', 5, config=BM25, strict=True)
    assert calls and found and found[0].label == 'المادة 107' and all(isinstance(f, db.Found) for f in found)


async def test_the_engine_rebuilds_after_articles_change(conn, monkeypatch, alert_caplog):
    monkeypatch.setattr(keyword_engine.CACHE, 'max_age', 0)
    assert await db.search(conn, 'السفتجة', 5, config=BM25, strict=True) == []
    await db.upsert_articles(conn, [Article('civil-code', 'القانون المدني الأردني', 999, '', 'السفتجة ورقة.', 's', 'b.md')])
    assert [f.number for f in await db.search(conn, 'السفتجة', 5, config=BM25, strict=True)] == [999]
    assert not any('keyword_engine_fallback' in r.message for r in alert_caplog.records)


async def test_a_strict_search_on_a_cold_cache_waits_for_the_build(conn):
    keyword_engine.CACHE.clear()
    assert [f.label for f in await db.search(conn, 'العربون', 5, config=BM25, strict=True)][:1] == ['المادة 107']


async def test_an_engine_error_falls_back_to_postgres_with_one_alert(conn, monkeypatch, alert_caplog):
    monkeypatch.setattr(bm25.Index, 'search', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    found = await db.search(conn, 'العربون', 5, config=BM25)
    assert found == await db.search(conn, 'العربون', 5)
    assert sum('keyword_engine_fallback' in r.message for r in alert_caplog.records) == 1


async def test_strict_mode_raises_instead_of_falling_back(conn, monkeypatch):
    monkeypatch.setattr(bm25.Index, 'search', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    with pytest.raises(keyword_engine.EngineUnavailable):
        await db.search(conn, 'العربون', 5, config=BM25, strict=True)


# The plan's other behaviours (Task 3.1, «Behaviors»).

async def test_found_rows_follow_the_engine_order_not_the_id_order(conn, monkeypatch):
    ranked = []
    real = bm25.Index.search

    def recording(self, *args, **kwargs):
        result = real(self, *args, **kwargs)
        ranked.extend(doc_id for doc_id, _ in result)
        return result

    monkeypatch.setattr(bm25.Index, 'search', recording)

    found = await db.search(conn, 'العقد', 5, config=BM25, strict=True)

    # 108 is the shorter of the two articles with «العقد», so it ranks first although it was stored second
    assert ranked != sorted(ranked) and [f.id for f in found] == ranked


async def test_bm25_respects_the_limit_and_the_law_filter(conn):
    await db.upsert_articles(conn, [Article('penal-code', 'قانون العقوبات', 1, '', 'العقد المزور باطل.', 's', 'p.md')])

    best = await db.search(conn, 'العقد', 1, config=BM25, strict=True)
    civil = await db.search(conn, 'العقد', 5, law='civil-code', config=BM25, strict=True)

    assert [(f.law_slug, f.number) for f in best] == [('penal-code', 1)] and [f.number for f in civil] == [108, 107]


async def test_two_bm25_runs_are_identical(conn):
    first = await db.search(conn, 'العقد العربون', 5, config=BM25, strict=True)
    keyword_engine.CACHE.clear()

    rebuilt = await db.search(conn, 'العقد العربون', 5, config=BM25, strict=True)
    again = await db.search(conn, 'العقد العربون', 5, config=BM25, strict=True)

    assert len(first) == 2 and first == rebuilt == again


async def test_a_recreated_schema_never_serves_a_stale_index(conn, monkeypatch):
    monkeypatch.setattr(keyword_engine.CACHE, 'max_age', 0)
    assert [f.number for f in await db.search(conn, 'العربون', 5, config=BM25, strict=True)] == [107]
    before = await db.index_version(conn)

    await conn.execute(f'DROP TABLE IF EXISTS {TABLES} CASCADE')          # no CACHE.clear(): the cache must notice
    await db.create_schema(conn)
    await db.upsert_articles(conn, [Article('civil-code', CIVIL, 999, '', 'السفتجة ورقة.', 's', 'b.md')])
    after = await db.index_version(conn)
    found = await db.search(conn, 'السفتجة', 5, config=BM25, strict=True)

    assert after[1] == before[1] and [f.number for f in found] == [999]   # the same counter, another table


async def test_configs_with_different_analysers_never_share_an_index(conn):
    today = await keyword_engine.CACHE.ensure(conn, BM25)

    light = await keyword_engine.CACHE.ensure(conn, with_overrides(BM25, ['analyser=guardlight']))

    assert (today.analyser.name, light.analyser.name) == ('today', 'guardlight') and light.index is not today.index


async def test_strict_mode_raises_when_the_build_fails(conn, monkeypatch, alert_caplog):
    monkeypatch.setattr(keyword_engine, 'build', boom)

    with pytest.raises(keyword_engine.EngineUnavailable):
        await db.search(conn, 'العربون', 5, config=BM25, strict=True)

    assert fallbacks(alert_caplog) == 0


async def test_every_write_to_the_articles_bumps_the_index_version(conn):
    stored = await db.index_version(conn)

    await db.upsert_articles(conn, ARTICLES[:1])
    upserted = await db.index_version(conn)
    await db.prune_articles(conn, 'civil-code', {(107, ''), (108, '')})
    pruned = await db.index_version(conn)

    assert stored[1] < upserted[1] < pruned[1] and stored[0] == upserted[0] == pruned[0]


async def test_a_cancelled_wait_does_not_fail_another_wait_for_the_same_build(conn, monkeypatch):
    started, release = threading.Event(), threading.Event()
    real = keyword_engine.build

    def held(*args):
        started.set()
        release.wait(30)
        return real(*args)

    monkeypatch.setattr(keyword_engine, 'build', held)
    try:
        first = asyncio.create_task(keyword_engine.CACHE.ensure(conn, BM25))
        await asyncio.to_thread(started.wait, 30)            # the build runs, and `first` waits for it
        first.cancel()                                       # as a call's deadline would
        second = asyncio.create_task(keyword_engine.CACHE.ensure(conn, BM25))   # joins the same build
        with pytest.raises(asyncio.CancelledError):
            await first
    finally:
        release.set()

    built = await second

    assert [doc.id for doc in built.index.docs] == [1, 2, 3]


async def test_a_cold_cache_falls_back_to_postgres_while_it_builds(conn, monkeypatch, alert_caplog):
    calls = spy(monkeypatch)

    found = await db.search(conn, 'العربون', 5, config=BM25)

    assert found == await db.search(conn, 'العربون', 5) and calls == [] and fallbacks(alert_caplog) == 1


async def test_an_error_of_a_built_engine_falls_back_to_postgres(conn, monkeypatch, alert_caplog):
    await keyword_engine.CACHE.ensure(conn, BM25)                        # built: the fallback is the error's
    monkeypatch.setattr(bm25.Index, 'search', boom)

    found = await db.search(conn, 'العربون', 5, config=BM25)

    assert found == await db.search(conn, 'العربون', 5) and fallbacks(alert_caplog) == 1


async def test_a_fallback_episode_raises_one_alert_until_the_engine_serves_again(conn, monkeypatch, alert_caplog):
    await keyword_engine.CACHE.ensure(conn, BM25)

    with monkeypatch.context() as broken:
        broken.setattr(bm25.Index, 'search', boom)
        await db.search(conn, 'العربون', 5, config=BM25)
        await db.search(conn, 'العقد', 5, config=BM25)
    await db.search(conn, 'العربون', 5, config=BM25)                      # served by the engine: the episode ends
    with monkeypatch.context() as broken:
        broken.setattr(bm25.Index, 'search', boom)
        await db.search(conn, 'العربون', 5, config=BM25)

    assert fallbacks(alert_caplog) == 2


async def test_a_failed_rebuild_raises_an_alert_while_the_stale_index_is_served(conn, monkeypatch, alert_caplog):
    # A stale index is served until its rebuild is swapped in: a rebuild that fails in the build thread must say so,
    # or a bm25 server would go on serving an outdated corpus without an alert line (final review, Chunk 3).
    monkeypatch.setattr(keyword_engine.CACHE, 'max_age', 0)
    await keyword_engine.CACHE.ensure(conn, BM25)                                     # built at this version
    await db.upsert_articles(conn, [Article('civil-code', CIVIL, 999, '', 'السفتجة ورقة.', 's', 'b.md')])
    monkeypatch.setattr(keyword_engine, 'build', boom)
    calls = spy(monkeypatch)

    found = await db.search(conn, 'العربون', 5, config=BM25)                          # the stale index serves it
    await asyncio.wrap_future(keyword_engine._BUILDER.submit(lambda: None))          # the one build thread is done

    assert calls and [f.number for f in found] == [107] and fallbacks(alert_caplog) == 0
    assert sum('keyword_engine_build_failed' in record.message for record in alert_caplog.records) == 1


# (c) A bound on the input: at most MAX_TERMS distinct terms, the first ones in the query.

_TODAY = Today()
_LETTERS = 'بتثجحخدذرزسشصضطظعغفقكلمنهوي'
# 200 distinct two-letter words the analyser keeps as they are, in reverse code-point order: the query's first terms
# are the last in sorted order, so a cap that kept the first terms in sorted order would keep the query's last ones.
WORDS = [word for word in sorted({a + b for a in _LETTERS for b in _LETTERS}, reverse=True)
         if _TODAY.query_terms(_TODAY.tokens(word)) == [word]][:200]
CAP = keyword_engine.MAX_TERMS
CAP_ARTICLES = [
    Article('civil-code', CIVIL, 901, '', ' '.join(WORDS[:3]) + '.', 's', 'c.md'),       # three kept terms
    Article('civil-code', CIVIL, 902, '', WORDS[CAP - 1] + '.', 's', 'c.md'),           # the last kept term
    Article('civil-code', CIVIL, 903, '', WORDS[CAP] + '.', 's', 'c.md'),               # the first term cut
    Article('civil-code', CIVIL, 904, '', ' '.join(WORDS[-6:]) + '.', 's', 'c.md'),     # six of the last terms
]


async def test_at_most_max_terms_distinct_terms_reach_the_index_the_first_ones(conn, monkeypatch):
    await db.upsert_articles(conn, CAP_ARTICLES)
    calls = spy(monkeypatch)

    capped = await db.search(conn, ' '.join(WORDS), 10, config=BM25, strict=True)
    alone = await db.search(conn, ' '.join(WORDS[:CAP]), 10, config=BM25, strict=True)

    assert len(WORDS) == 200 and [len(terms) for terms in calls] == [CAP, CAP]
    assert capped == alone and {901, 902} <= {f.number for f in capped}


# (d) Depth, and the order of the load.

@pytest.mark.parametrize(('levers', 'pool'), [([], 50), (['proximity_weight=2.0'], 200)])
async def test_a_depth_above_the_candidate_pool_is_refused(conn, alert_caplog, levers, pool):
    config = with_overrides(BM25, levers)

    served = await db.search(conn, 'العقد', pool, config=config, strict=True)
    with pytest.raises(ValueError, match='candidate'):
        await db.search(conn, 'العقد', pool + 1, config=config)              # refused, not a fallback

    assert [f.number for f in served] == [108, 107] and fallbacks(alert_caplog) == 0


async def test_the_engine_loads_the_articles_in_id_order(conn):
    await db.upsert_articles(conn, ARTICLES[:1])                          # a new row version: a plain scan meets it last
    cur = await conn.execute('SELECT id FROM articles')
    stored = [row[0] for row in await cur.fetchall()]

    built = await keyword_engine.CACHE.ensure(conn, BM25)

    assert stored != sorted(stored) and [doc.id for doc in built.index.docs] == sorted(stored)


# (e) The terms come only from Analyser.query_terms, with the stoplist applied here.

@pytest.mark.parametrize(('query', 'reached'), [
    ('العربون العربون', [['عربون']]),                # a repeated word reaches it once
    ('ب العربون', [['عربون']]),                       # a one-letter word never
    ('ما هو في من على', []),                          # only stopwords: nothing to search, so no call at all
])
async def test_only_the_analysers_query_terms_reach_the_index(conn, monkeypatch, query, reached):
    calls = spy(monkeypatch)

    await db.search(conn, query, 5, config=BM25, strict=True)

    assert calls == reached


@pytest.mark.parametrize(('stoplist', 'reached'), [('true', ['حكم', 'عربون']), ('false', ['ما', 'حكم', 'عربون'])])
async def test_the_stoplist_setting_decides_whether_stopwords_reach_the_index(conn, monkeypatch, stoplist, reached):
    calls = spy(monkeypatch)

    await db.search(conn, 'ما حكم العربون', 5, config=with_overrides(BM25, [f'stoplist={stoplist}']), strict=True)

    assert calls == [reached]


# The heading field (Task 3.4): the index reads the heading stored with each article.

async def test_a_word_only_in_the_stored_heading_finds_its_article_under_heading_weight(conn):
    await db.upsert_articles(conn, ARTICLES[2:], {('civil-code', 465, ''): 'السفتجة'})   # in no article's text

    found = await db.search(conn, 'السفتجة', 5, config=with_overrides(BM25, ['heading_weight=1.0']), strict=True)

    assert [f.number for f in found] == [465]
