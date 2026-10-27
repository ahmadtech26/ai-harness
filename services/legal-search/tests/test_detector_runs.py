from datetime import timedelta

from legal_search.detector import detect
from legal_search.guard_settings import GuardSettings
from tests.guard_fixtures import T0, MINUTE, search, walk

SETTINGS = GuardSettings()


def _run(verdict):
    return next((signal for signal in verdict.signals if signal.kind == 'run'), None)


def test_an_ascending_walk_of_twelve_articles_is_a_suspected_run():
    events = walk(range(1, 13))

    verdict = detect(events, SETTINGS, events[-1].at + MINUTE)

    run = _run(verdict)
    assert verdict.level == 'suspected'
    assert (run.law, run.value, run.first, run.last) == ('penal-code', 12, 1, 12)
    assert (run.since, run.until, run.threshold) == (events[0].at, events[-1].at, 12)


def test_a_walk_one_short_of_the_threshold_is_not_flagged():
    events = walk(range(1, 12))

    verdict = detect(events, SETTINGS, events[-1].at)

    assert verdict.level == 'none'


def test_a_descending_walk_with_steps_within_run_gap_is_a_run():
    events = walk([40, 38, 37, 35, 34, 32, 31, 29, 28, 26, 25, 23])

    verdict = detect(events, SETTINGS, events[-1].at)

    run = _run(verdict)
    assert (verdict.level, run.value, run.first, run.last) == ('suspected', 12, 23, 40)


def test_a_jump_beyond_run_gap_breaks_the_run():
    jump = walk([1, 2, 3, 4, 5, 6, 10, 11, 12, 13, 14, 15])
    interleaved = walk([1, 7, 2, 8, 3, 9, 4, 10, 5, 11, 6, 12])  # in time order every step is a jump

    assert detect(jump, SETTINGS, jump[-1].at).level == 'none'
    assert detect(interleaved, SETTINGS, interleaved[-1].at).level == 'none'


def test_a_jump_of_one_more_than_run_gap_breaks_the_run():
    events = walk([1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14])

    verdict = detect(events, SETTINGS, events[-1].at)

    assert verdict.level == 'none'


def test_a_walk_through_the_memorandum_is_a_run():
    events = walk(range(1, 13), law='civil-code', tool='get_memorandum')

    verdict = detect(events, SETTINGS, events[-1].at)

    assert (verdict.level, _run(verdict).law) == ('suspected', 'civil-code')


def test_other_laws_and_searches_do_not_break_or_extend_a_run():
    events = [
        *walk(range(1, 7)),
        *walk([50], law='labour', first_id=7, start=T0 + 6 * MINUTE),
        search(8, T0 + 7 * MINUTE, {'civil-code|1|'}),
        *walk(range(7, 13), first_id=9, start=T0 + 8 * MINUTE),
    ]

    verdict = detect(events, SETTINGS, events[-1].at)

    run = _run(verdict)
    assert (verdict.level, run.law, run.value) == ('suspected', 'penal-code', 12)


def test_attempts_older_than_the_run_window_are_not_counted():
    events = walk(range(1, 7)) + walk(range(7, 13), first_id=7, start=T0 + timedelta(hours=25))

    verdict = detect(events, SETTINGS, events[-1].at)

    assert verdict.level == 'none'


def test_repeating_an_article_does_not_lengthen_the_run():
    events = walk([*range(1, 12), 11])

    verdict = detect(events, SETTINGS, events[-1].at)

    assert verdict.level == 'none'


def test_repeating_an_article_inside_the_chain_does_not_lengthen_the_run():
    events = walk([1, 2, 3, 4, 5, 6, 5, 7, 8, 9, 10, 11, 12])

    verdict = detect(events, SETTINGS, events[-1].at)

    run = _run(verdict)
    assert (verdict.level, run.value, run.first, run.last) == ('suspected', 12, 1, 12)


def test_thirty_sequential_articles_are_a_proven_run():
    events = walk(range(1, 31))

    verdict = detect(events, SETTINGS, events[-1].at)

    assert (verdict.level, _run(verdict).value, _run(verdict).threshold) == ('proven', 30, 30)
