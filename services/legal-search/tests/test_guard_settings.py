from dataclasses import replace

import pytest

from legal_search.guard_settings import GuardSettings, SettingsError, loosened, merged, validate

DEFAULTS = GuardSettings()


def _with(**changes) -> dict:
    return {**DEFAULTS.as_dict(), **changes}


def _rule(**changes) -> str:
    with pytest.raises(SettingsError) as error:
        validate(_with(**changes))
    return error.value.rule


def test_rejects_a_non_positive_value_naming_the_rule():
    with pytest.raises(SettingsError) as error:
        validate(_with(run_gap=0))

    assert error.value.rule == 'positive' and 'run_gap' in error.value.message


def test_rejects_a_suspected_threshold_at_or_above_its_proven_threshold():
    with pytest.raises(SettingsError) as error:
        validate(_with(suspected_distinct_7d=750))

    assert error.value.rule == 'suspected_below_proven'


def test_rejects_a_suspected_run_at_or_above_the_proven_run():
    with pytest.raises(SettingsError) as error:
        validate(_with(suspected_run=30))

    assert error.value.rule == 'suspected_below_proven' and 'suspected_run' in error.value.message


def test_rejects_a_throttle_cap_at_or_above_the_daily_cap():
    with pytest.raises(SettingsError) as error:
        validate(_with(throttle_daily_cap=300))

    assert error.value.rule == 'throttle_below_daily'


def test_rejects_an_unknown_setting():
    with pytest.raises(SettingsError) as error:
        validate(_with(suspected_runs=12))

    assert error.value.rule == 'unknown_setting' and 'suspected_runs' in error.value.message


def test_rejects_a_missing_setting():
    values = _with()
    del values['run_gap']

    with pytest.raises(SettingsError) as error:
        validate(values)

    assert error.value.rule == 'missing_setting' and 'run_gap' in error.value.message


def test_rejects_a_boolean_where_a_count_is_expected():
    rules = [_rule(suspected_run=True), _rule(daily=300.5)]  # nor is a fraction a count

    assert rules == ['positive', 'positive']


def test_rejects_a_flag_that_is_not_a_boolean():
    rules = [_rule(proven_if_signal_while_throttled='no'), _rule(proven_if_signal_while_throttled=1)]

    assert rules == ['boolean', 'boolean']


def test_rejects_a_value_above_its_ceiling():
    rules = [_rule(run_window_hours=721), _rule(daily=1_000_001)]

    # A raised daily cap raises every tier's with it: the base must stay the lowest (plan S4b, fallback_is_lowest).
    accepted = validate(_with(run_window_hours=720, daily=1_000_000, daily_advanced=1_000_000, daily_expert=1_000_000))

    assert rules == ['too_large', 'too_large']
    assert (accepted.run_window_hours, accepted.daily) == (720, 1_000_000)


def test_merged_applies_changes_over_the_current_settings():
    result = merged(DEFAULTS, {'suspected_run': 13})

    assert (result.suspected_run, result.proven_run, result.daily) == (13, 30, 300)


def test_narrowing_the_run_gap_or_window_counts_as_a_loosening():
    # R1 n=18: a narrower gap or window catches fewer runs, so lowering either one loosens the guard.
    previous = GuardSettings()

    changed = loosened(previous, replace(previous, run_gap=1, run_window_hours=1))

    assert changed == ['run_gap', 'run_window_hours']


def test_widening_the_run_gap_or_window_is_not_a_loosening():
    previous = GuardSettings()

    changed = loosened(previous, replace(previous, run_gap=3, run_window_hours=48))

    assert changed == []


# Plan S4 and S4b (owner 2026-11-14): the allowance, the daily cap and the 7-day alarm per tier. Each base setting is
# the fast tier's and the fallback of every other tier, and validate keeps it the lowest.
TIERED = replace(DEFAULTS, per_answer_advanced=11, per_answer_expert=16, daily_advanced=400, daily_expert=600)


def test_each_tier_has_its_own_caps_and_any_other_tier_the_lowest():
    tiers = ['iqraa-fast', 'iqraa-advanced', 'iqraa-expert', None, 'none', 'iqraa-other', '{{LIBRECHAT_BODY_IQRAATIER}}']

    caps = [TIERED.caps_for(tier) for tier in tiers]

    assert [(c.per_answer, c.daily, c.max_results) for c in caps] == [
        (8, 300, 5), (11, 400, 5), (16, 600, 5), (8, 300, 5), (8, 300, 5), (8, 300, 5), (8, 300, 5)]


def test_validate_refuses_per_answer_above_a_tier_field():
    with pytest.raises(SettingsError) as error:
        validate(_with(per_answer=9))

    assert error.value.rule == 'fallback_is_lowest' and 'per_answer_advanced' in error.value.message


def test_validate_refuses_a_daily_cap_or_a_7_day_alarm_above_a_tier_field():
    rules = [_rule(daily=301), _rule(suspected_distinct_7d=301), _rule(daily_expert=299)]

    assert rules == ['fallback_is_lowest'] * 3


def test_a_tiers_7_day_alarm_stays_below_the_proven_threshold():
    assert _rule(suspected_distinct_7d_expert=750) == 'suspected_below_proven'


def test_the_timing_raise_passes_validate():
    from legal_search.timing import RAISED

    raised = validate(_with(**RAISED))

    assert raised.caps_for('iqraa-expert') == raised.caps_for(None)  # no tier is refused before another on the stack
