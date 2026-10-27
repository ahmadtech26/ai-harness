from datetime import timedelta

from legal_search.detector import Event, Verdict, detect
from legal_search.guard_settings import GuardSettings
from tests.guard_fixtures import T0, search, walk

SETTINGS = GuardSettings()
HOUR = timedelta(hours=1)


def _keys(law, numbers):
    return {f'{law}|{number}|' for number in numbers}


def _searches(count, start, first_id=1, law='civil-code'):
    """Searches of five new articles each, ten minutes apart, covering `count` distinct articles of `law`."""
    return [
        search(first_id + i, start + i * timedelta(minutes=10), _keys(law, range(i * 5 + 1, i * 5 + 6)), law)
        for i in range(count // 5)
    ]


def _kinds(verdict):
    return {signal.kind: signal.level for signal in verdict.signals}


def _cap_day(first_id, at):
    """A call that served a full daily cap (300), then a call the daily cap refused an hour later."""
    return [
        Event(id=first_id, at=at, tool='search_law', outcome='served', documents=300),
        Event(id=first_id + 1, at=at + HOUR, tool='search_law', outcome='capped'),
    ]


def test_three_hundred_distinct_articles_in_seven_days_are_suspected():
    events = _searches(300, T0)

    verdict = detect(events, SETTINGS, events[-1].at)

    assert _kinds(verdict) == {'distinct_7d': 'suspected'}


def test_seven_hundred_fifty_distinct_articles_are_proven():
    events = _searches(750, T0)

    verdict = detect(events, SETTINGS, events[-1].at)

    assert (verdict.level, _kinds(verdict)['distinct_7d']) == ('proven', 'proven')


def test_articles_older_than_seven_days_are_not_counted():
    events = _searches(150, T0) + _searches(150, T0 + timedelta(days=8), first_id=31, law='commerce')

    verdict = detect(events, SETTINGS, events[-1].at)

    assert verdict.level == 'none'


def test_refused_attempts_count_toward_distinct_coverage():
    events = walk(range(1, 901, 3), outcome='throttled')  # 300 articles, three apart: no run, nothing served

    verdict = detect(events, SETTINGS, events[-1].at)

    assert _kinds(verdict) == {'distinct_7d': 'suspected'}


def test_the_daily_cap_reached_on_two_consecutive_amman_days_is_suspected():
    # Two cap episodes on consecutive Amman days, UTC days 18 and 20. The first is reached across Amman
    # midnight: 150 documents at 19:00 UTC on 18 October (22:00 in Amman), 150 more at 21:30 UTC (00:30 on the
    # 19th in Amman). The second is reached at 20:00 UTC on 20 October (23:00 on the 20th in Amman).
    first = T0.replace(day=18, hour=19)
    events = [
        Event(id=1, at=first, tool='search_law', outcome='served', documents=150),
        Event(id=2, at=first + timedelta(minutes=150), tool='search_law', outcome='served', documents=150),
        Event(id=3, at=first + timedelta(minutes=210), tool='search_law', outcome='capped'),
        *_cap_day(4, T0.replace(hour=20)),
    ]

    verdict = detect(events, SETTINGS, events[-1].at)

    assert _kinds(verdict) == {'cap_days': 'suspected'}


def test_one_cap_episode_across_amman_midnight_is_one_cap_day():
    # The cap reached at 22:00 in Amman (19:00 UTC), then refusals at 23:30 and at 00:30: the second refusal
    # is on the next Amman day, but the cap was reached once.
    reached = T0.replace(hour=19)
    events = [
        Event(id=1, at=reached, tool='search_law', outcome='served', documents=300),
        Event(id=2, at=reached + timedelta(minutes=90), tool='search_law', outcome='capped'),
        Event(id=3, at=reached + timedelta(minutes=150), tool='search_law', outcome='capped'),
    ]

    verdict = detect(events, SETTINGS, events[-1].at)

    assert verdict.level == 'none'


def test_the_daily_cap_reached_on_non_consecutive_days_is_not_suspected():
    events = _cap_day(1, T0) + _cap_day(3, T0 + timedelta(days=2))

    verdict = detect(events, SETTINGS, events[-1].at)

    assert verdict.level == 'none'


def test_a_refusal_below_the_daily_cap_is_not_a_cap_day():
    # Per-answer cap refusals on consecutive days: only 8 documents served in the 24 hours before each.
    events = [
        Event(id=1, at=T0, tool='search_law', outcome='served', documents=8),
        Event(id=2, at=T0 + HOUR, tool='search_law', outcome='capped'),
        Event(id=3, at=T0 + timedelta(days=1), tool='search_law', outcome='served', documents=8),
        Event(id=4, at=T0 + timedelta(days=1, hours=1), tool='search_law', outcome='capped'),
    ]

    verdict = detect(events, SETTINGS, events[-1].at)

    assert verdict.level == 'none'


def test_the_cap_total_is_a_rolling_24_hour_window():
    # 200 documents on each of three consecutive days, each day's exactly 24 hours after the day before's, each
    # followed by a refusal: the earlier 200 has just left the window, as the daily cap's
    # `created_at > now() - 24 h` drops it, so no 24 hours ever hold 300.
    events = []
    for day in range(3):
        at = T0 + day * timedelta(hours=24)
        events += [
            Event(id=2 * day + 1, at=at, tool='search_law', outcome='served', documents=200),
            Event(id=2 * day + 2, at=at + HOUR, tool='search_law', outcome='capped'),
        ]

    verdict = detect(events, SETTINGS, events[-1].at)

    assert verdict.level == 'none'


def test_heavy_but_legitimate_topic_research_is_not_flagged():
    # A day of research across five laws: 48 searches (240 distinct articles) and 25 article reads that never
    # step through a law, with the neighbouring pairs a lawyer reads together.
    laws = ['civil-code', 'commerce', 'companies', 'labour', 'civil-procedure']
    events = [
        search(i + 1, T0 + i * timedelta(minutes=10), _keys(laws[i % 5], range(i * 5 + 1, i * 5 + 6)), laws[i % 5])
        for i in range(48)
    ]
    reads = (
        [('civil-code', n) for n in (87, 88, 105, 148, 149, 202, 246, 300)]
        + [('commerce', n) for n in (12, 40, 41, 90, 133)]
        + [('companies', n) for n in (5, 6, 60, 120)]
        + [('labour', n) for n in (22, 23, 30, 70)]
        + [('civil-procedure', n) for n in (3, 50, 51, 110)]
    )
    for j, (law, number) in enumerate(reads):
        events += walk([number], law=law, first_id=100 + j, start=T0 + timedelta(minutes=5 + j * 17))
    events.sort(key=lambda event: event.at)

    verdict = detect(events, SETTINGS, events[-1].at)

    assert verdict == Verdict('none')
