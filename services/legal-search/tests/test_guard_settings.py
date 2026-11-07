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

    accepted = validate(_with(run_window_hours=720, daily=1_000_000))

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
