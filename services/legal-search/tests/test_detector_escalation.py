from dataclasses import replace

from legal_search.detector import assess
from legal_search.guard_settings import GuardSettings
from tests.guard_fixtures import pending, walk

SETTINGS = GuardSettings()
SWEEP = walk(range(1, 25))  # ids 1..24; the flag opened on the call for article 12 (log id 12)


def test_twelve_sequential_attempts_after_the_flag_escalate_to_proven():
    events = [*SWEEP[:23], pending(SWEEP[23])]

    verdict = assess(events, SETTINGS, SWEEP[23].at, flag_from_id=12)

    escalation = verdict.signals[0]
    assert verdict.level == 'proven'
    assert (escalation.kind, escalation.value, escalation.first, escalation.last, escalation.after_flag) == (
        'run', 12, 13, 24, True)


def test_events_before_the_flag_do_not_count_toward_escalation():
    events = [*SWEEP[:22], pending(SWEEP[22])]  # article 23: eleven attempts after the flag

    verdict = assess(events, SETTINGS, SWEEP[22].at, flag_from_id=12)

    assert verdict.level == 'suspected'


def test_without_proven_if_signal_while_throttled_a_suspected_level_signal_does_not_escalate():
    settings = replace(SETTINGS, proven_if_signal_while_throttled=False)
    events = [*SWEEP[:23], pending(SWEEP[23])]

    verdict = assess(events, settings, SWEEP[23].at, flag_from_id=12)

    assert verdict.level == 'suspected'


def test_a_proven_level_signal_escalates_regardless_of_the_setting():
    settings = replace(SETTINGS, proven_if_signal_while_throttled=False)
    events = walk(range(1, 31))

    verdict = assess(events, settings, events[-1].at, flag_from_id=12)

    assert verdict.level == 'proven'
