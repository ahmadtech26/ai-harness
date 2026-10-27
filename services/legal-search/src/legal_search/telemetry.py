"""Staff evidence for choosing the guard settings (spec C.3): per-user-day telemetry over a window of the
retrieval log (Asia/Amman calendar days) and, below, the simulation of candidate settings. Pure functions
over detector events; admin.py loads the events."""

import math
from collections import Counter, defaultdict, deque
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from legal_search.detector import (
    DISTINCT_WINDOW,
    LEVELS,
    RUN_TOOLS,
    Event,
    RollingTotal,
    Verdict,
    amman_day,
    article_key,
    assess,
    cap_reaches,
    longest_run,
    longest_streak,
    run_size,
)
from legal_search.guard_settings import GuardSettings

MAX_DAYS = 30


def percentiles(values: Sequence[int]) -> dict:
    """Nearest-rank p50, p90, p99 and the maximum; zeros when there are no values."""
    ordered = sorted(values)
    if not ordered:
        return {'p50': 0, 'p90': 0, 'p99': 0, 'max': 0}

    def rank(p: int) -> int:
        return ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1]

    return {'p50': rank(50), 'p90': rank(90), 'p99': rank(99), 'max': ordered[-1]}


def user_days(events: Sequence[Event], settings: GuardSettings) -> list[dict]:
    """One user's activity per Asia/Amman day: distinct articles, longest run, and cap hits (served calls that
    brought the rolling 24 h total up to the daily cap)."""
    by_day: dict = defaultdict(list)
    for event in events:
        by_day[amman_day(event.at)].append(event)
    hits: dict = defaultdict(int)
    for event in cap_reaches(events, settings.daily):
        hits[amman_day(event.at)] += 1
    days = []
    for day in sorted(by_day):
        day_events = by_day[day]
        runs: dict[str, list[Event]] = defaultdict(list)
        for event in day_events:
            if event.tool in RUN_TOOLS and event.law is not None and event.number is not None:
                runs[event.law].append(event)
        days.append({
            'day': day.isoformat(),
            'distinct': len(set().union(*(event.keys for event in day_events))),
            'longest_run': max((run_size(longest_run(law_events, settings.run_gap)) for law_events in runs.values()), default=0),
            'cap_hits': hits[day],
        })
    return days


def telemetry(events_by_user: dict[str, list[Event]], settings: GuardSettings, open_flags: dict[str, int]) -> dict:
    """Distributions over user-days (p50, p90, p99, max), the number of active users and the open flags."""
    days = [day for events in events_by_user.values() for day in user_days(events, settings)]
    return {
        'users': len(events_by_user),
        'user_days': len(days),
        'distinct_articles': percentiles([day['distinct'] for day in days]),
        'longest_run': percentiles([day['longest_run'] for day in days]),
        'cap_hits': percentiles([day['cap_hits'] for day in days]),
        'open_flags': open_flags,
    }


def _rank(level: str | None) -> int:
    return LEVELS.index(level or 'none')


def _reached(value: int, suspected: int, proven: int | None = None) -> str:
    if proven is not None and value >= proven:
        return 'proven'
    return 'suspected' if value >= suspected else 'none'


class _Tracker:
    """One user's events, one pass in log order, under the detector's rules: for each event, decided as the
    pending call after all earlier ones, the highest level its signals reach. A window moving forward only
    drops events, so only the event being decided can lift a signal past a level the earlier calls did not
    reach: the tracker follows the chain that event extends (per law), the 7-day distinct articles and the cap
    days, and replay() runs the full detector only at an event where the level changes."""

    def __init__(self, settings: GuardSettings) -> None:
        self.settings = settings
        self.run_window = timedelta(hours=settings.run_window_hours)
        self.chains: dict[str, tuple[deque[Event], Counter]] = {}   # law -> its chain's attempts in the window
        self.last_number: dict[str, int] = {}
        self.recent: deque[Event] = deque()                          # events inside the 7-day window
        self.keys: Counter = Counter()                               # their article keys
        self.total = RollingTotal(settings.daily)
        self.reaches: deque[datetime] = deque()                      # cap crossings inside the 7-day window
        self.reach_days: Counter = Counter()
        self.logged: Event | None = None                             # the previous event, now in the log

    def level(self, event: Event) -> str:
        if self.logged is not None and self.total.add(self.logged):
            self.reaches.append(self.logged.at)
            self.reach_days[amman_day(self.logged.at)] += 1
        self.logged = event
        return max(self._run(event), self._distinct(event), self._cap_days(event.at), key=_rank)

    def _run(self, event: Event) -> str:
        if event.tool not in RUN_TOOLS or event.law is None or event.number is None:
            return 'none'
        attempts, counts = self.chains.setdefault(event.law, (deque(), Counter()))
        previous = self.last_number.get(event.law)
        if previous is not None and abs(event.number - previous) > self.settings.run_gap:
            attempts.clear()
            counts.clear()
        while attempts and attempts[0].at <= event.at - self.run_window:
            _drop(counts, [_key(attempts.popleft())])
        attempts.append(event)
        counts[_key(event)] += 1
        self.last_number[event.law] = event.number
        return _reached(len(counts), self.settings.suspected_run, self.settings.proven_run)

    def _distinct(self, event: Event) -> str:
        while self.recent and self.recent[0].at <= event.at - DISTINCT_WINDOW:
            _drop(self.keys, self.recent.popleft().keys)
        self.recent.append(event)
        self.keys.update(event.keys)
        # A search refused or trimmed was decided on its candidates: they count for this decision only.
        pending = len(self.keys) + sum(1 for key in event.candidates if key not in self.keys)
        return _reached(pending, self.settings.suspected_distinct_7d, self.settings.proven_distinct_7d)

    def _cap_days(self, now: datetime) -> str:
        while self.reaches and self.reaches[0] <= now - DISTINCT_WINDOW:
            _drop(self.reach_days, [amman_day(self.reaches.popleft())])
        streak, _ = longest_streak(self.reach_days)
        return _reached(streak, self.settings.suspected_cap_days)


def _key(event: Event) -> str:
    return article_key(event.law, event.number, event.suffix)


def _drop(counts: Counter, keys) -> None:
    for key in keys:
        counts[key] -= 1
        if not counts[key]:
            del counts[key]


def _pending(event: Event) -> Event:
    """A logged event as the call being decided (what the guard saw): no id, no outcome, nothing served yet,
    and a search's keys are the candidates it was decided on when it logged them (refused or trimmed)."""
    return replace(event, id=None, outcome=None, documents=0, keys=event.candidates or event.keys)


def replay(events: Sequence[Event], settings: GuardSettings) -> tuple[Verdict, datetime | None]:
    """The level the guard would have reached on one user's events (log order) under `settings`, and when it
    last changed (the flag opening, or its escalation): each event decided in turn as the pending call, a flag
    opened at the first signal (from that call's log row) and escalated as decide() would. One pass over the
    events; the full detector (detector.assess) runs only at an event where the tracker sees the level change."""
    level, flag_from, changed_at, signals = 'none', None, None, ()
    tracker, after = _Tracker(settings), None  # `after`: the events after the flag's opening call only
    for index, event in enumerate(events):
        reached = tracker.level(event)
        if after is not None and after.level(event) != 'none':
            reached = 'proven'
        if _rank(reached) <= _rank(level):
            continue
        verdict = assess([*events[:index], _pending(event)], settings, event.at, flag_from)
        if level == 'none' and verdict.level != 'none':
            level, flag_from, changed_at, signals = verdict.level, event.id, event.at, verdict.signals
            if settings.proven_if_signal_while_throttled:
                after = _Tracker(settings)
        elif level == 'suspected' and verdict.level == 'proven':
            level, changed_at, signals = 'proven', event.at, signals + verdict.signals
        if level == 'proven':
            break
    return Verdict(level, signals), changed_at


def simulate(events_by_user: dict[str, list[Event]], settings: GuardSettings, since: datetime | None = None) -> list[dict]:
    """The users whose flag would have opened or escalated under `settings` after `since` (None: at any time),
    with their signals; earlier events are history only. Reads only; writes nothing."""
    flagged = []
    for user_id in sorted(events_by_user):
        verdict, changed_at = replay(events_by_user[user_id], settings)
        if verdict.level != 'none' and (since is None or changed_at > since):
            flagged.append({'user_id': user_id, 'level': verdict.level,
                            'signals': [signal.evidence() for signal in verdict.signals]})
    return flagged
