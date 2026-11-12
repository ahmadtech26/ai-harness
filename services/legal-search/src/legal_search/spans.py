"""Optional per-call timing spans (REQ-RAG-021, Task 1.5).

    with spans.collect() as got:          # a list of (name, milliseconds), in the order the spans end
        async with spans.span('search'):
            ...

Spans go to the collector of the current context. With no collector set, `span` records nothing and reads no
clock: the shipping server pays the context-variable read and the async context manager's setup (a few
microseconds per span, seven per search_law call). Only the timing stack's server sets a collector (server.py,
LEGAL_SEARCH_TIMING_SPANS=1).

A span timed where the collector cannot be read, such as a worker thread, is handed over with `add` (the keyword
engine's engine_wait and engine, inside search: keyword_engine.Searches).
"""

import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar

Span = tuple[str, float]
_COLLECTOR: ContextVar[list[Span] | None] = ContextVar('timing_spans', default=None)


def current() -> list[Span] | None:
    """The current context's collector, or None."""
    return _COLLECTOR.get()


@contextmanager
def collect() -> Iterator[list[Span]]:
    """Collects the spans that end inside the block, in order, into the list it yields."""
    got: list[Span] = []
    token = _COLLECTOR.set(got)
    try:
        yield got
    finally:
        _COLLECTOR.reset(token)


def add(name: str, ms: float) -> None:
    """Records a span timed elsewhere as `name` when a collector is set; does nothing otherwise."""
    got = _COLLECTOR.get()
    if got is not None:
        got.append((name, ms))


@asynccontextmanager
async def span(name: str) -> AsyncIterator[None]:
    """Times the block as `name` when a collector is set; does nothing otherwise."""
    got = _COLLECTOR.get()
    if got is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        got.append((name, (time.perf_counter() - started) * 1000.0))
