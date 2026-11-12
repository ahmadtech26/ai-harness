"""The keyword engine behind db.search (recall plan Task 3.1): one in-memory BM25 index (bm25.Index) per index key,
derived only from Postgres and rebuilt when the articles change, with today's Postgres search as the runtime fallback.

    index key   (analyser, the wf_* word-form flags that are on): both decide the document tokens, so two configs that
                differ in either never share an index (about 50 MiB each).
    version     index_state's (created, version) pair, bumped by every write to articles and read at most every
                max_age seconds. The pair, not the counter: a recreated table starts its counter again.
    build       the articles are read on the caller's connection, in id order, then analysed and indexed in a worker
                thread that holds no connection, and swapped in whole.
    strict      (evaluation) a cold or stale index is built and awaited; a failed build or search raises
                EngineUnavailable and never falls back.
    otherwise   a cold index falls back to the Postgres search while it builds, a stale one is served until its
                rebuild is swapped in, and an engine error falls back; each fallback episode raises one
                keyword_engine_fallback alert.

bm25.Index.search trusts its caller (a repeated term doubles its score, a one-letter one reaches thousands of words)
and never reads Settings.stoplist, so the query terms come only from Analyser.query_terms, with the stoplist applied
here, and at most MAX_TERMS of them (review 2026-11-11 (c), (e)).
"""

import asyncio
import math
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, fields
from datetime import datetime

from psycopg import AsyncConnection

from legal_search import bm25, db
from legal_search.alerts import alert
from legal_search.analysis import Analyser, Lexicon, analyser_of
from legal_search.metrics import DEPTH
from legal_search.search_config import SearchConfig

# The distinct query terms one search may hold, the first ones in the query; the rest are dropped (review 2026-11-11
# (c)). 48, not 32: 32 would cut inputs the plan measures (eval questions reach 39 terms, query and question joined 42,
# and 7 to 31 of the 80 joined items exceed 32, by analyser and stoplist), while logged traffic has 9 words at most.
# The costliest two-letter words on the host, under T-B2 and with proximity: 32 cost 313.5 ms and 648 ms, 48 cost
# 412 ms and 856 ms on a first search (cap_cost.py, Task 3.1); uncapped, 674 cost 894 ms and 15.5 s, and a
# 300-character input cap would still allow 630 ms and 1.9 s.
MAX_TERMS = 48

# ORDER BY id: the candidate cut keeps the first loaded of documents tied at its edge (bm25.Index.search), so the load
# order must not change across restarts or row rewrites. The heading column arrives with Task 3.4.
LOAD = "SELECT id, law_slug, number, suffix, law_title, text, '' AS heading FROM articles ORDER BY id"

Key = tuple[str, frozenset[str]]
Version = tuple[datetime, int] | None

# Builds run one at a time, off the event loop and outside any request: a build started by a search that falls back
# outlives that search's connection and event loop.
_BUILDER = ThreadPoolExecutor(max_workers=1, thread_name_prefix='keyword-engine-build')


class EngineUnavailable(RuntimeError):
    """A strict search the engine could not answer: its index could not be built or read, or its search failed."""


@dataclass(frozen=True)
class Built:
    index: bm25.Index
    analyser: Analyser       # the one the documents were analysed with: queries must be analysed with it too
    version: Version         # the index_state pair read before the articles were


def settings_of(config: SearchConfig) -> bm25.Settings:
    return bm25.Settings(config.prefix_mode, config.prefix_weight, config.title_weight, config.heading_weight,
                         config.proximity_weight, config.proximity_window, config.df_drop, config.stoplist,
                         config.synonyms)


def index_key(config: SearchConfig) -> Key:
    flags = frozenset(f.name for f in fields(config) if f.name.startswith('wf_') and getattr(config, f.name))
    return config.analyser, flags


def pool_of(settings: bm25.Settings) -> int:
    """The candidates bm25.Index.search keeps, whatever depth it is asked for: Tantivy's top 50, or 200 to rerank by
    proximity (the bench's CANDIDATES and CANDIDATES_RERANK)."""
    return bm25.CANDIDATES_RERANK if settings.proximity_weight > 0.0 else bm25.CANDIDATES


def query_of(analyser: Analyser, query: str, settings: bm25.Settings) -> tuple[list[str], list[list[str]]]:
    """The terms and synonym members a query searches: its first MAX_TERMS query terms (in order, de-duplicated, two
    letters or more, without stopwords when the stoplist is on), and the synonym members of the words up to the first
    term dropped, so a long query searches exactly what its first MAX_TERMS terms alone would."""
    tokens = analyser.tokens(query)
    terms = analyser.query_terms(tokens, stoplist=settings.stoplist)
    if len(terms) > MAX_TERMS:
        tokens = tokens[:tokens.index(terms[MAX_TERMS])]
        terms = terms[:MAX_TERMS]
    return terms, analyser.synonym_members(tokens) if settings.synonyms else []


def build(key: Key, version: Version, rows: list[tuple]) -> Built:
    """The index of the loaded rows (LOAD's columns), each article's text, heading and law title analysed as the
    bench's build_index does (run_parity.py); GuardLight's lexicon is the served texts'."""
    name, _ = key
    texts = [row[5] for row in rows]
    analyser = analyser_of(name, Lexicon.from_texts(texts) if name == 'guardlight' else Lexicon({}))
    docs = [bm25.Doc(article_id, law_slug, number, suffix, tuple(analyser.tokens(text)),
                     tuple(analyser.tokens(heading)), tuple(analyser.tokens(law_title)))
            for article_id, law_slug, number, suffix, law_title, text, heading in rows]
    return Built(bm25.Index.build(docs), analyser, version)


class EngineCache:
    """One built index per index key and the version pair it was built from, and the fallback episode."""

    max_age = 30.0  # seconds between two reads of index_version (as guard_settings.SettingsCache)

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()  # the build thread swaps indexes in under it
        self._generation = 0
        self.clear()

    def clear(self) -> None:
        """Forget every index, pending build and version read; a build still running is not swapped in."""
        with self._lock:
            self._generation += 1
            self._built: dict[Key, Built] = {}
            self._pending: dict[Key, tuple[Version, Future]] = {}
            self._failed: dict[Key, float] = {}
        self._version: Version = None
        self._read_at = -math.inf
        self.falling_back = False

    async def ensure(self, conn: AsyncConnection, config: SearchConfig, *, wait: bool = True) -> Built | None:
        """The index for `config`, current with the articles. With `wait` (strict searches, a warm-up), a cold or
        stale index is built, or its build already under way joined, and awaited. Without it, that build is started
        and what can be served now is returned: the stale index meanwhile, or None while there is none. A failed
        build is started again no sooner than max_age later, unless someone waits for it."""
        key = index_key(config)
        version = await self._current_version(conn)
        built = self._built.get(key)
        if built is not None and built.version == version:
            return built
        with self._lock:
            pending = self._pending.get(key)
        if pending is not None and pending[0] == version:
            future = pending[1]
        elif not wait and self._clock() - self._failed.get(key, -math.inf) < self.max_age:
            return built
        else:
            future = await self._start(conn, key, version)
        return await asyncio.wrap_future(future) if wait else built

    async def _current_version(self, conn: AsyncConnection) -> Version:
        now = self._clock()
        if now - self._read_at >= self.max_age:
            async with conn.transaction():  # a savepoint inside a call's transaction: a failed read leaves it usable
                self._version = await db.index_version(conn)
            self._read_at = now
        return self._version

    async def _start(self, conn: AsyncConnection, key: Key, version: Version) -> Future:
        future: Future = Future()
        # Running, so never cancelled: a waiter cancelled by its call's deadline must not fail the others' build.
        future.set_running_or_notify_cancel()
        generation = self._generation
        with self._lock:
            self._pending[key] = (version, future)
        try:
            async with conn.transaction():
                rows = await (await conn.execute(LOAD)).fetchall()
        except BaseException as error:
            self._settle(generation, key, future, error=error)
            raise
        _BUILDER.submit(self._build, generation, key, version, rows, future)
        return future

    def _build(self, generation: int, key: Key, version: Version, rows: list[tuple], future: Future) -> None:
        try:
            built = build(key, version, rows)
        except BaseException as error:
            self._settle(generation, key, future, error=error)
            return
        self._settle(generation, key, future, built=built)

    def _settle(self, generation: int, key: Key, future: Future, built: Built | None = None,
                error: BaseException | None = None) -> None:
        with self._lock:
            if generation == self._generation:
                if built is not None:
                    self._built[key] = built
                    self._failed.pop(key, None)
                else:
                    self._failed[key] = self._clock()
                if self._pending.get(key, (None, None))[1] is future:
                    del self._pending[key]
        if built is not None:
            future.set_result(built)
        else:
            # A cancelled load must not cancel the strict searches waiting on the same build.
            future.set_exception(error if isinstance(error, Exception) else RuntimeError(f'build interrupted: {error!r}'))

    def fell_back(self, reason: str) -> None:
        """One alert per fallback episode: from the first fallback to the next search the engine answers."""
        if not self.falling_back:
            self.falling_back = True
            alert('keyword_engine_fallback', reason=reason)

    def served(self) -> None:
        self.falling_back = False


CACHE = EngineCache()


async def search(conn: AsyncConnection, query: str, limit: int, law: str | None, config: SearchConfig,
                 strict: bool) -> list[db.Found]:
    """db.search with ranker='bm25': the engine's best max(limit, DEPTH) ids, read back from Postgres in the engine's
    order and truncated to `limit` last.

    A depth above the candidate pool is refused (ValueError), where the pool would silently cut it (review 2026-11-11
    (d)). The pool is not raised to 400: it stays the bench's 50, or 200 with proximity, at which Gate P2 and the T rows
    were measured. Callers ask for DEPTH (evaluation) or a search_law budget (max_results, 5); a top-50 consumer asks
    for 50, which the pool holds, its ties at the cut kept stable by LOAD's ORDER BY id; a 100-deep reference is read
    from the bench's rows (basis-rows-depth100.jsonl, made with a pool of 400)."""
    if limit <= 0:
        return []
    settings = settings_of(config)
    depth = max(limit, DEPTH)
    if depth > pool_of(settings):
        raise ValueError(f'the keyword engine ranks at most {pool_of(settings)} candidates with these settings; '
                         f'{depth} were asked for')
    try:
        built = await CACHE.ensure(conn, config, wait=strict)
    except Exception as error:
        if strict:
            raise EngineUnavailable(f'the keyword index could not be built ({type(error).__name__})') from error
        return await _fallback(conn, query, limit, law, config, f'build failed: {type(error).__name__}')
    if built is None:
        return await _fallback(conn, query, limit, law, config, 'cold')
    terms, members = query_of(built.analyser, query, settings)
    if not terms:
        CACHE.served()
        return []
    try:
        ranked = await asyncio.to_thread(built.index.search, terms, members, settings, law, depth)
    except Exception as error:
        if strict:
            raise EngineUnavailable(f'the keyword engine failed ({type(error).__name__})') from error
        return await _fallback(conn, query, limit, law, config, f'search failed: {type(error).__name__}')
    CACHE.served()
    found = await db.found_by_ids(conn, [doc_id for doc_id, _ in ranked])
    return found[:limit]


async def _fallback(conn: AsyncConnection, query: str, limit: int, law: str | None, config: SearchConfig,
                    reason: str) -> list[db.Found]:
    """Today's Postgres search, with the alert line (REQ-RAG-025). The reason never carries the query: it is the
    user's text."""
    CACHE.fell_back(reason)
    return await db._pg_search(conn, query, limit, law, config)
