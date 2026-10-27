"""The sweep detector (spec C.1): a pure function over one user's retrieval events and the guard settings.

An event is one tool call, served or refused (a retrieval_log row), or the call being decided (id None).
Signals:
  run          the longest chain of distinct articles of one law, over get_article/get_memorandum attempts in
               time order inside run_window: each number within run_gap of the previous one (either
               direction); a larger jump starts a new chain; other laws' events and searches are ignored.
  distinct_7d  distinct articles requested or served in the last 7 days (search results count)
  cap_days     consecutive Asia/Amman calendar days on each of which a served call brought the user's rolling
               24 h total of served documents up to the daily cap (refusals never count; the cap stays rolling)
"""

from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from legal_search.guard_settings import GuardSettings

RUN_TOOLS = frozenset({'get_article', 'get_memorandum'})
LEVELS = ('none', 'suspected', 'proven')
AMMAN = ZoneInfo('Asia/Amman')
DISTINCT_WINDOW = timedelta(days=7)
DAY = timedelta(hours=24)


def article_key(law: str, number: int, suffix: str | None) -> str:
    return f'{law}|{number}|{suffix or ""}'


def keys_of(tool: str, law: str | None, number: int | None, suffix: str | None, served: Iterable[str]) -> frozenset[str]:
    """The articles an event touches: those served, plus the requested one for get_article/get_memorandum."""
    keys = set(served)
    if tool in RUN_TOOLS and law is not None and number is not None:
        keys.add(article_key(law, number, suffix))
    return frozenset(keys)


@dataclass(frozen=True)
class Event:
    id: int | None              # retrieval_log id; None for the call being decided
    at: datetime                # timezone-aware
    tool: str
    law: str | None = None      # requested_law
    number: int | None = None   # requested_number
    suffix: str | None = None   # requested_suffix
    outcome: str | None = None  # served | capped | throttled | suspended; None while being decided
    keys: frozenset[str] = frozenset()
    documents: int = 0          # articles plus memorandum notes served
    candidates: frozenset[str] = frozenset()  # a search refused or trimmed: the articles it was decided on


@dataclass(frozen=True)
class Signal:
    kind: str                   # run | distinct_7d | cap_days
    level: str                  # suspected | proven
    value: int
    threshold: int
    since: datetime
    until: datetime
    law: str | None = None
    first: int | None = None    # a run's article range
    last: int | None = None
    after_flag: bool = False    # computed only from events after the flag opened (escalation)

    def evidence(self) -> dict:
        data = {
            'kind': self.kind, 'level': self.level, 'value': self.value, 'threshold': self.threshold,
            'since': self.since.isoformat(), 'until': self.until.isoformat(), 'after_flag': self.after_flag,
        }
        if self.law is not None:
            data['law'] = self.law
        if self.first is not None:
            data['first'], data['last'] = self.first, self.last
        return data


@dataclass(frozen=True)
class Verdict:
    level: str                  # none | suspected | proven
    signals: tuple[Signal, ...] = ()


def _level(value: int, suspected: int, proven: int | None) -> str | None:
    if proven is not None and value >= proven:
        return 'proven'
    return 'suspected' if value >= suspected else None


def run_size(chain: Sequence[Event]) -> int:
    return len({article_key(event.law, event.number, event.suffix) for event in chain})


def longest_run(events: Sequence[Event], gap: int) -> list[Event]:
    """The events of the longest chain (counted in distinct articles) among one law's attempts, in order."""
    best: list[Event] = []
    best_size = 0
    chain: list[Event] = []
    seen: set[str] = set()
    for event in events:
        if chain and abs(event.number - chain[-1].number) > gap:
            chain, seen = [], set()
        chain.append(event)
        seen.add(article_key(event.law, event.number, event.suffix))
        if len(seen) > best_size:
            best, best_size = list(chain), len(seen)
    return best


def _run_signal(events: Sequence[Event], settings: GuardSettings, now: datetime) -> Signal | None:
    since = now - timedelta(hours=settings.run_window_hours)
    by_law: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.tool in RUN_TOOLS and event.law is not None and event.number is not None and event.at > since:
            by_law[event.law].append(event)
    chain = max((longest_run(law_events, settings.run_gap) for law_events in by_law.values()), key=run_size, default=[])
    size = run_size(chain)
    level = _level(size, settings.suspected_run, settings.proven_run)
    if level is None:
        return None
    numbers = [event.number for event in chain]
    threshold = settings.proven_run if level == 'proven' else settings.suspected_run
    return Signal('run', level, size, threshold, chain[0].at, chain[-1].at, chain[0].law, min(numbers), max(numbers))


def amman_day(moment: datetime) -> date:
    return moment.astimezone(AMMAN).date()


class RollingTotal:
    """Documents served to one user in the last 24 h, fed the user's calls in time order (one pass)."""

    def __init__(self, daily: int) -> None:
        self.daily = daily
        self.total = 0
        self._served: deque[Event] = deque()

    def add(self, event: Event) -> bool:
        """Counts `event`; True when it is a served call that brings the total from below the daily cap up to it."""
        while self._served and self._served[0].at <= event.at - DAY:
            self.total -= self._served.popleft().documents
        if event.outcome != 'served' or event.documents <= 0:
            return False
        before = self.total
        self._served.append(event)
        self.total += event.documents
        return before < self.daily <= self.total


def cap_reaches(events: Sequence[Event], daily: int) -> list[Event]:
    """The served calls that brought the user's rolling 24 h total of served documents up to `daily`."""
    total = RollingTotal(daily)
    return [event for event in events if total.add(event)]


def longest_streak(days: Iterable[date]) -> tuple[int, date | None]:
    """The longest run of consecutive calendar days among `days`, and the day it ends on."""
    best, best_end, streak, previous = 0, None, 0, None
    for day in sorted(set(days)):
        streak = streak + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        if streak > best:
            best, best_end = streak, day
        previous = day
    return best, best_end


def _distinct_signal(events: Sequence[Event], settings: GuardSettings, now: datetime) -> Signal | None:
    recent = [event for event in events if event.at > now - DISTINCT_WINDOW]
    keys = set().union(*(event.keys for event in recent))
    level = _level(len(keys), settings.suspected_distinct_7d, settings.proven_distinct_7d)
    if level is None:
        return None
    threshold = settings.proven_distinct_7d if level == 'proven' else settings.suspected_distinct_7d
    return Signal('distinct_7d', level, len(keys), threshold, recent[0].at, recent[-1].at)


def _cap_days_signal(events: Sequence[Event], settings: GuardSettings, now: datetime) -> Signal | None:
    days = [amman_day(event.at) for event in cap_reaches(events, settings.daily) if event.at > now - DISTINCT_WINDOW]
    best, best_end = longest_streak(days)
    if best < settings.suspected_cap_days:
        return None
    start = best_end - timedelta(days=best - 1)
    return Signal('cap_days', 'suspected', best, settings.suspected_cap_days,
                  datetime.combine(start, time.min, AMMAN), datetime.combine(best_end, time.max, AMMAN))


def detect(events: Sequence[Event], settings: GuardSettings, now: datetime) -> Verdict:
    """The user's signals at `now` over `events` (time order; the call being decided last)."""
    candidates = (
        _run_signal(events, settings, now),
        _distinct_signal(events, settings, now),
        _cap_days_signal(events, settings, now),
    )
    signals = tuple(signal for signal in candidates if signal is not None)
    level = max((signal.level for signal in signals), key=LEVELS.index, default='none')
    return Verdict(level, signals)


def assess(events: Sequence[Event], settings: GuardSettings, now: datetime, flag_from_id: int | None = None) -> Verdict:
    """`detect`, plus the escalation of an open suspected flag opened at log row `flag_from_id`: with
    proven_if_signal_while_throttled, a suspected-level signal computed only from the events after that row
    (the call being decided included) is proven. Any proven-level signal is proven in any case."""
    verdict = detect(events, settings, now)
    if flag_from_id is None or verdict.level == 'proven' or not settings.proven_if_signal_while_throttled:
        return verdict
    after = detect([event for event in events if event.id is None or event.id > flag_from_id], settings, now)
    if after.level == 'none':
        return verdict
    return Verdict('proven', tuple(replace(signal, after_flag=True) for signal in after.signals))
