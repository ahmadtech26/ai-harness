"""Event builders for the detector, telemetry and simulation tests (no database)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from legal_search.detector import Event, keys_of

T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)


def walk(numbers, *, law='penal-code', first_id=1, start=T0, step=MINUTE, tool='get_article', outcome='served'):
    """One attempt per number, in order, `step` apart, with ids from `first_id`."""
    return [
        Event(id=first_id + index, at=start + index * step, tool=tool, law=law, number=number, suffix='',
              outcome=outcome, keys=keys_of(tool, law, number, '', ()), documents=1 if outcome == 'served' else 0)
        for index, number in enumerate(numbers)
    ]


def search(event_id, at, keys, law=None):
    """A search_law call that served the given article keys ('law|number|suffix')."""
    return Event(id=event_id, at=at, tool='search_law', law=law, outcome='served', keys=frozenset(keys),
                 documents=len(keys))


def pending(event):
    """The same attempt as the call being decided: not logged yet (a search refused or trimmed is decided on
    the candidates it logged)."""
    return replace(event, id=None, outcome=None, documents=0, keys=event.candidates or event.keys)
