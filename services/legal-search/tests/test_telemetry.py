from dataclasses import replace
from datetime import timedelta

import pytest

from legal_search import telemetry
from legal_search.detector import Event, assess
from legal_search.guard_settings import GuardSettings
from legal_search.telemetry import percentiles, simulate, user_days
from tests.guard_fixtures import T0, MINUTE, pending, search, walk

SETTINGS = GuardSettings()


def test_percentiles_use_the_nearest_rank():
    result = (percentiles(list(range(1, 101))), percentiles([]), percentiles([1, 2, 3, 4, 5])['p50'])

    assert result == ({'p50': 50, 'p90': 90, 'p99': 99, 'max': 100}, {'p50': 0, 'p90': 0, 'p99': 0, 'max': 0}, 3)


def test_user_days_are_asia_amman_calendar_days():
    # 20:30 and 21:30 UTC on 20 October are 23:30 on the 20th and 00:30 on the 21st in Amman; the second call
    # brings the rolling 24 h total to the daily cap, so its cap hit is on the 21st.
    first, second = walk([1, 2], start=T0.replace(hour=20, minute=30), step=timedelta(hours=1))

    days = user_days([first, replace(second, documents=299)], SETTINGS)

    assert [(d['day'], d['distinct'], d['longest_run'], d['cap_hits']) for d in days] == [
        ('2026-10-20', 1, 1, 0), ('2026-10-21', 1, 1, 1)]


# Plan S4b: a call is capped at its own tier's daily cap, so a cap hit is counted against that cap (Codex round 1: every
# tier was counted against the base 300). Any other tier, and none, has the base cap.
DAILY_PER_TIER = replace(SETTINGS, daily_advanced=400, daily_expert=600)


def _served(at, documents, tier):
    """A search_law call that served `documents` texts under `tier`."""
    return Event(id=None, at=at, tool='search_law', outcome='served', documents=documents, tier=tier)


@pytest.mark.parametrize(('tier', 'hits'), [('iqraa-fast', [1, 0]), ('iqraa-advanced', [0, 1]), ('iqraa-expert', [0, 1]),
                                            ('iqraa-other', [1, 0]), (None, [1, 0])])
def test_a_cap_hit_is_counted_against_the_daily_cap_of_the_calls_tier(tier, hits):
    # 300 texts on the 20th (11:00 in Amman), 300 more on the 21st (07:00), inside the rolling 24 h: 600 in all.
    events = [_served(T0, 300, tier), _served(T0 + timedelta(hours=20), 300, tier)]

    days = user_days(events, DAILY_PER_TIER)

    assert [(d['day'], d['cap_hits']) for d in days] == [('2026-10-20', hits[0]), ('2026-10-21', hits[1])]


@pytest.mark.parametrize(('tier', 'hits'), [('iqraa-advanced', [0, 1]), ('iqraa-expert', [0, 0])])
def test_a_rolling_total_between_the_advanced_and_expert_caps_is_a_hit_on_advanced_only(tier, hits):
    # 450 in all: past the advanced 400, short of the expert 600 (round 2 review: 300 + 300 crossed both at once).
    events = [_served(T0, 300, tier), _served(T0 + timedelta(hours=20), 150, tier)]

    days = user_days(events, DAILY_PER_TIER)

    assert [(d['day'], d['cap_hits']) for d in days] == [('2026-10-20', hits[0]), ('2026-10-21', hits[1])]


def test_a_user_on_two_tiers_hits_each_cap_on_its_own_tiers_call():
    # The fast call reaches the fast 300, then an expert call reaches the expert 600: two hits, not the expert one alone.
    events = [_served(T0, 300, 'iqraa-fast'), _served(T0 + MINUTE, 300, 'iqraa-expert')]

    days = user_days(events, DAILY_PER_TIER)

    assert [d['cap_hits'] for d in days] == [2]


def test_telemetry_reports_per_user_day_distributions_users_and_open_flags():
    sweeper = walk([*range(1, 23, 2), 24])  # eleven articles two apart (run_gap), then a jump of three: a run of 11
    reader = [
        search(100, T0, {'labour|1|', 'labour|2|', 'labour|3|'}),
        Event(id=101, at=T0 + timedelta(minutes=5), tool='search_law', outcome='capped'),
        Event(id=102, at=T0 + timedelta(minutes=6), tool='search_law', outcome='capped'),
    ]
    capper = [Event(id=200, at=T0, tool='search_law', outcome='served', documents=300)]

    report = telemetry.telemetry({'sweeper': sweeper, 'reader': reader, 'capper': capper}, SETTINGS,
                                 {'suspected': 1, 'proven': 0})

    assert (report['users'], report['user_days']) == (3, 3)
    assert report['distinct_articles'] == {'p50': 3, 'p90': 12, 'p99': 12, 'max': 12}
    assert (report['longest_run']['max'], report['cap_hits']['max']) == (11, 1)
    assert report['open_flags'] == {'suspected': 1, 'proven': 0}


def test_simulate_lists_the_users_who_would_be_flagged_with_their_signals():
    walker = walk(range(1, 12))  # 11 sequential articles: under the default 12, over a candidate 10
    reader = walk([3, 40, 90], law='labour', first_id=50)

    result = simulate({'walker': walker, 'reader': reader}, replace(SETTINGS, suspected_run=10))

    assert [(u['user_id'], u['level'], u['signals'][0]['kind'], u['signals'][0]['value']) for u in result] == [
        ('walker', 'suspected', 'run', 10)]


def test_simulate_replays_escalation_after_a_suspected_flag():
    sweeper = walk(range(1, 25))

    result = simulate({'sweeper': sweeper}, SETTINGS)

    assert [(u['level'], [s['after_flag'] for s in u['signals']]) for u in result] == [('proven', [False, True])]


def test_simulate_decides_each_event_as_the_call_the_guard_decided():
    # The cap is reached on the second Amman day by the last call. The guard decided that call before it was
    # served (nothing served yet: one cap day), so no flag opened; its logged row would count two.
    capper = [
        Event(id=1, at=T0 - timedelta(days=1), tool='search_law', outcome='served', documents=300),
        Event(id=2, at=T0, tool='search_law', outcome='served', documents=300),
    ]
    # The walker's twelfth article opens the flag on the run alone: the 289 documents it then served would make
    # its logged row a second cap day too.
    walker = [
        Event(id=1, at=T0 - timedelta(days=1), tool='search_law', outcome='served', documents=300),
        *walk(range(1, 12), first_id=2),
        replace(walk([12], first_id=13, start=T0 + 11 * MINUTE)[0], documents=289),
    ]

    result = simulate({'capper': capper, 'walker': walker}, SETTINGS)

    assert [(u['user_id'], [s['kind'] for s in u['signals']]) for u in result] == [('walker', ['run'])]


def test_simulate_counts_history_before_the_window_but_reports_only_flags_opened_or_escalated_in_it():
    since = T0
    # 290 distinct articles in the ten hours before the window, ten more inside it: 300 in 7 days.
    coverer = [
        search(i + 1, since - timedelta(hours=10) + i * MINUTE, {f'civil-code|{i * 5 + n}|' for n in range(1, 6)})
        for i in range(60)
    ]
    coverer[58:] = [replace(event, at=since + (j + 1) * MINUTE) for j, event in enumerate(coverer[58:])]
    early = walk(range(1, 13), start=since - 11 * MINUTE, first_id=1000)  # flagged at `since`: not inside the window
    late = walk(range(1, 25), start=since - 12 * MINUTE, first_id=2000)   # flagged before the window, proven inside it

    result = simulate({'coverer': coverer, 'early': early, 'late': late}, SETTINGS, since)

    assert [(u['user_id'], u['level'], u['signals'][0]['kind']) for u in result] == [
        ('coverer', 'suspected', 'distinct_7d'), ('late', 'proven', 'run')]


def _decided_one_by_one(events, settings):
    """The reference: each event decided in turn, as the pending call, with the full detector (quadratic); and
    how many times the level changed (1 at the flag, 1 more at its escalation)."""
    level, flag_from, signals, changes = 'none', None, (), 0
    for index, event in enumerate(events):
        verdict = assess([*events[:index], pending(event)], settings, event.at, flag_from)
        if level == 'none' and verdict.level != 'none':
            level, flag_from, signals, changes = verdict.level, event.id, verdict.signals, 1
        elif level == 'suspected' and verdict.level == 'proven':
            level, signals, changes = 'proven', signals + verdict.signals, changes + 1
        if level == 'proven':
            break
    return level, [signal.evidence() for signal in signals], changes


def _users():
    """Users that exercise every signal, its window and the escalation (ids ascending in log order)."""
    day = T0.replace(hour=0)
    return {
        'sweeper': walk(range(1, 41)),
        'slow-walker': walk(range(1, 31), step=timedelta(hours=1)),  # 24 articles fit in run_window
        'two-laws': [
            *walk(range(1, 7)), *walk([50, 52, 51, 49], law='labour', first_id=7, start=T0 + 6 * MINUTE),
            *walk([7, 8, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23], first_id=11, start=T0 + 10 * MINUTE),
        ],
        'capper': [
            Event(id=1, at=day.replace(day=15, hour=19), tool='search_law', outcome='served', documents=300),
            Event(id=2, at=day.replace(day=15, hour=21, minute=30), tool='search_law', outcome='capped'),
            Event(id=3, at=day.replace(day=17, hour=22), tool='search_law', outcome='served', documents=300),
            Event(id=4, at=day.replace(day=19, hour=20), tool='search_law', outcome='served', documents=300),
            Event(id=5, at=day.replace(day=19, hour=21), tool='search_law', outcome='capped'),
            *[search(6 + i, day.replace(day=20, hour=9) + i * MINUTE, {f'labour|{i + 1}|'}) for i in range(30)],
        ],
        'window-edge': [  # 299 distinct articles in every 7 days, never 300
            *[search(1 + i, T0 - timedelta(days=7) + i * MINUTE, {f'commerce|{i}|'}) for i in range(299)],
            *[search(300 + i, T0 + i * MINUTE, {f'commerce|{1000 + i}|'}) for i in range(50)],
        ],
        'escalating-coverer': [
            *walk(range(1, 13)),
            *[search(13 + i, T0 + timedelta(hours=1) + i * MINUTE, {f'civil-code|{i * 5 + n}|' for n in range(1, 6)})
              for i in range(70)],
        ],
        'bulk': [search(1 + i, T0 + i * MINUTE, {f'commerce|{i * 5 + n}|' for n in range(1, 6)}) for i in range(160)],
        # Plan S4b: the 7-day alarm and the cap days take the highest tier logged in the window.
        'expert-reader': [search(1 + i, T0 + i * MINUTE, {f'commerce|{i * 5 + n}|' for n in range(1, 6)}, tier='iqraa-expert')
                          for i in range(70)],  # 350 distinct: under the expert alarm when it is raised
        'tier-falls-back': [  # the expert call leaves the window: the last call, one new article, meets the fast alarm
            search(1, T0, {'commerce|9999|'}, tier='iqraa-expert'),
            *[search(2 + i, T0 + (i + 1) * MINUTE, {f'commerce|{i * 5 + n}|' for n in range(1, 6)}) for i in range(70)],
            search(72, T0 + timedelta(days=7, minutes=1), {'commerce|8888|'}),
        ],
        'expert-capper': [  # 400 a day on two days: the expert cap is not reached, the fast one is
            Event(id=1, at=day.replace(day=15, hour=19), tool='search_law', outcome='served', documents=400, tier='iqraa-expert'),
            Event(id=2, at=day.replace(day=16, hour=19, minute=30), tool='search_law', outcome='served', documents=400,
                  tier='iqraa-expert'),
            Event(id=3, at=day.replace(day=17, hour=8), tool='search_law', outcome='capped', tier='iqraa-expert'),
        ],
        'advanced-capper': [  # 450 a day on two days: the advanced cap is reached too
            Event(id=1, at=day.replace(day=15, hour=19), tool='search_law', outcome='served', documents=450, tier='iqraa-advanced'),
            Event(id=2, at=day.replace(day=16, hour=19, minute=30), tool='search_law', outcome='served', documents=450,
                  tier='iqraa-advanced'),
            Event(id=3, at=day.replace(day=17, hour=8), tool='search_law', outcome='capped', tier='iqraa-advanced'),
        ],
        'capper-falls-back': [  # the expert call leaves the window after the two fast cap days: then they count
            Event(id=1, at=day.replace(day=13, hour=0, minute=30), tool='search_law', outcome='served', tier='iqraa-expert'),
            Event(id=2, at=day.replace(day=14, hour=20), tool='search_law', outcome='served', documents=300),
            Event(id=3, at=day.replace(day=15, hour=20, minute=30), tool='search_law', outcome='served', documents=300),
            Event(id=4, at=day.replace(day=20, hour=1), tool='search_law', outcome='served', documents=1),
        ],
        'refused-searcher': [  # a refused search is decided on its candidates; they count for that call only
            *[search(1 + i, T0 + i * MINUTE, {f'commerce|{i * 5 + n}|' for n in range(1, 6)}) for i in range(59)],
            Event(id=60, at=T0 + 59 * MINUTE, tool='search_law', outcome='throttled',
                  candidates=frozenset({f'commerce|{n}|' for n in range(1000, 1004)})),  # 295 + 4: under 300
            search(61, T0 + 60 * MINUTE, {'commerce|2000|'}),                            # 296
            Event(id=62, at=T0 + 61 * MINUTE, tool='search_law', outcome='throttled',
                  candidates=frozenset({f'commerce|{n}|' for n in range(3000, 3004)})),  # 296 + 4: 300
        ],
    }


BOUNDARIES = replace(SETTINGS, proven_run=25, proven_if_signal_while_throttled=False)  # the slow walker's 24 stay below
TIGHT = GuardSettings(suspected_run=4, proven_run=8, run_gap=1, run_window_hours=6, suspected_distinct_7d=40,
                      proven_distinct_7d=100, suspected_cap_days=2, throttle_daily_cap=5, daily=20)


TIERS = replace(SETTINGS, daily_advanced=400, daily_expert=600, suspected_distinct_7d_advanced=400,
                suspected_distinct_7d_expert=600)


@pytest.mark.parametrize('settings', [SETTINGS, BOUNDARIES, TIGHT, TIERS], ids=['defaults', 'boundaries', 'tight', 'tiers'])
def test_simulate_agrees_with_deciding_every_event_in_turn(settings, monkeypatch):
    users = _users()
    expected = {user: _decided_one_by_one(events, settings) for user, events in users.items()}
    calls = []
    monkeypatch.setattr(telemetry, 'assess', lambda *args: calls.append(args[2]) or assess(*args))

    result = simulate(users, settings)

    assert {u['user_id']: (u['level'], u['signals']) for u in result} == {
        user: (level, signals) for user, (level, signals, _) in expected.items() if level != 'none'}
    assert len(calls) == sum(changes for _, _, changes in expected.values())  # the full detector only at a change


def test_simulate_runs_the_full_detector_only_where_the_level_changes(monkeypatch):
    calls = []
    monkeypatch.setattr(telemetry, 'assess', lambda *args: calls.append(args[2]) or assess(*args))
    reader = [search(i + 1, T0 + i * MINUTE, {f'civil-code|{i % 50 + 1}|'}) for i in range(3000)]
    sweeper = walk(range(1, 41), first_id=5000)

    simulate({'reader': reader, 'sweeper': sweeper}, SETTINGS)

    assert calls == [sweeper[11].at, sweeper[23].at]  # the flag at article 12, its escalation at 24


def test_simulate_takes_the_highest_tier_logged_in_the_window():
    tiered = ('expert-reader', 'tier-falls-back', 'expert-capper', 'advanced-capper', 'capper-falls-back')
    users = {user: events for user, events in _users().items() if user in tiered}

    result = simulate(users, TIERS)

    assert [(u['user_id'], u['signals'][0]['kind']) for u in result] == [
        ('advanced-capper', 'cap_days'), ('capper-falls-back', 'cap_days'), ('tier-falls-back', 'distinct_7d')]
