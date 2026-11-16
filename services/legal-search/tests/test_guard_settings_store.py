import os

import pytest
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from legal_search.guard_settings import (
    GuardSettings,
    SettingsCache,
    SettingsError,
    ensure_settings,
    history,
    load_settings,
    update_settings,
)
from tests.pg import fresh

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

ENV_DEFAULTS = GuardSettings(per_answer=6, daily=200, max_results=4)


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        yield connection


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_first_start_seeds_the_settings_from_the_environment_caps_once(conn):
    with pytest.raises(SettingsError):  # defaults that break a rule are refused and stored nowhere
        await ensure_settings(conn, GuardSettings(daily=5))

    await ensure_settings(conn, ENV_DEFAULTS)

    await ensure_settings(conn, GuardSettings())

    assert await load_settings(conn) == ENV_DEFAULTS
    assert [(entry['changed_by'], entry['previous']) for entry in await history(conn)] == [('environment', None)]


async def test_an_update_records_who_when_why_and_the_previous_values(conn):
    await ensure_settings(conn, GuardSettings())

    updated = await update_settings(conn, {'suspected_run': 13}, 'staff-1', 'fewer false positives')

    latest = (await history(conn))[0]
    assert updated.suspected_run == 13 and await load_settings(conn) == updated
    assert (latest['changed_by'], latest['reason'], latest['previous']['suspected_run'], latest['settings']['suspected_run']) == (
        'staff-1', 'fewer false positives', 12, 13)
    assert latest['changed_at']

    # A missing key takes its default and a retired key is ignored.
    await conn.execute("UPDATE guard_settings SET settings = (settings - 'run_gap') || '{\"retired\": 1}'::jsonb")
    assert await load_settings(conn) == updated


@pytest.mark.parametrize(
    ('changes', 'rule'),
    [({'suspected_run': 30}, 'suspected_below_proven'), ({'proven_if_signal_while_throttled': 'false'}, 'boolean')],
    ids=['suspected_run', 'boolean'],
)
async def test_an_invalid_update_is_rejected_with_its_rule_and_changes_nothing(conn, changes, rule):
    await ensure_settings(conn, GuardSettings())

    with pytest.raises(SettingsError) as error:
        await update_settings(conn, changes, 'staff-1', 'r')

    assert error.value.rule == rule
    assert await load_settings(conn) == GuardSettings() and len(await history(conn)) == 1


async def test_an_update_without_a_reason_is_rejected(conn):
    await ensure_settings(conn, GuardSettings())

    with pytest.raises(SettingsError) as error:
        await update_settings(conn, {'suspected_run': 13}, 'staff-1', '  ')

    assert (error.value.rule, error.value.category) == ('reason_required', 'bad_request')


async def test_the_cache_serves_the_loaded_settings_until_thirty_seconds_have_passed(conn):
    await ensure_settings(conn, GuardSettings())
    clock = FakeClock()
    cache = SettingsCache(clock=clock)
    await cache.get(conn)
    await update_settings(conn, {'suspected_run': 13}, 'staff-1', 'test')

    clock.now += 29.9
    before_expiry = (await cache.get(conn)).suspected_run
    clock.now += 0.1
    at_expiry = (await cache.get(conn)).suspected_run

    assert (before_expiry, at_expiry) == (12, 13)


async def test_the_cache_age_counts_from_the_start_of_the_read():
    clock = FakeClock()
    reads = []

    async def slow_load(conn):
        reads.append(clock.now)
        clock.now += 5.0  # the read takes five seconds
        return GuardSettings(suspected_run=12 + len(reads))

    cache = SettingsCache(clock=clock, loader=slow_load)
    await cache.get(None)  # starts at 1000.0, ends at 1005.0

    clock.now = 1029.9
    before_expiry = (await cache.get(None)).suspected_run
    clock.now = 1030.0
    at_expiry = (await cache.get(None)).suspected_run

    assert (before_expiry, at_expiry) == (13, 14)


async def test_a_read_that_an_invalidate_overtakes_is_not_kept():
    clock = FakeClock()
    stored = [GuardSettings(suspected_run=13), GuardSettings(suspected_run=14)]
    cache = None

    async def load_during_a_change(conn):
        value = stored.pop(0)
        if value.suspected_run == 13:
            cache.invalidate()  # a settings change lands while this read is under way
        return value

    cache = SettingsCache(clock=clock, loader=load_during_a_change)

    during = (await cache.get(None)).suspected_run
    after = (await cache.get(None)).suspected_run

    assert (during, after) == (13, 14)


# Plan S4 / S4b: the live row predates the tier fields (STATE.md P1). A stored row without them must load unchanged in
# effect, every tier at the row's own base value (a tier's allowance at least 8), and never fail validation on load (a
# fail-closed outage).
LIVE_ROW = {'daily': 300, 'run_gap': 2, 'per_answer': 8, 'proven_run': 30, 'max_results': 5, 'suspected_run': 12,
            'run_window_hours': 24, 'proven_distinct_7d': 750, 'suspected_cap_days': 2, 'throttle_daily_cap': 10,
            'suspected_distinct_7d': 300, 'proven_if_signal_while_throttled': True}


async def _stored(conn, settings: dict) -> GuardSettings:
    await conn.execute("INSERT INTO guard_settings (id, settings, updated_by) VALUES (1, %s, 'environment')",
                       (Jsonb(settings),))
    return await load_settings(conn)


async def test_a_stored_row_without_the_tier_fields_loads_them_as_8(conn):
    loaded = await _stored(conn, LIVE_ROW)

    assert [loaded.caps_for(tier) for tier in ('iqraa-advanced', 'iqraa-expert')] == [loaded.caps] * 2
    assert (loaded.per_answer_advanced, loaded.per_answer_expert, loaded.daily_expert) == (8, 8, 300)


async def test_a_stored_row_with_per_answer_10_and_no_tier_fields_loads(conn):
    loaded = await _stored(conn, {**LIVE_ROW, 'per_answer': 10})

    assert (loaded.per_answer, loaded.per_answer_advanced, loaded.per_answer_expert) == (10, 10, 10)


async def test_a_stored_row_with_per_answer_2_and_no_tier_fields_gives_the_tiers_8(conn):
    # Plan S4: a missing tier allowance is max(8, the stored per_answer), never below the code default (Codex round 1).
    loaded = await _stored(conn, {**LIVE_ROW, 'per_answer': 2})

    assert (loaded.per_answer, loaded.per_answer_advanced, loaded.per_answer_expert) == (2, 8, 8)


async def test_a_stored_row_with_a_lowered_7_day_alarm_and_no_tier_fields_loads(conn):
    loaded = await _stored(conn, {**LIVE_ROW, 'suspected_distinct_7d': 200, 'proven_distinct_7d': 250})

    assert (loaded.suspected_distinct_7d_advanced, loaded.suspected_distinct_7d_expert) == (200, 200)


async def test_a_loosening_change_raises_one_alert_and_a_tightening_one_none(conn, alert_caplog):
    # R1 n=18: raising a cap or a threshold was recorded only in the history table.
    import json

    await ensure_settings(conn, GuardSettings())

    # A raised daily cap raises every tier's with it: the base must stay the lowest (plan S4b, fallback_is_lowest).
    await update_settings(conn, {'daily': 400, 'daily_advanced': 400, 'daily_expert': 400, 'suspected_run': 11},
                          'staff-1', 'busy week')
    await update_settings(conn, {'daily': 350}, 'staff-1', 'back down')
    await update_settings(conn, {'proven_if_signal_while_throttled': False}, 'staff-2', 'test')

    alerts = [json.loads(r.getMessage()) for r in alert_caplog.records if r.name == 'legal_search.alerts']
    assert [(a['event'], a['changed_by'], a['loosened']) for a in alerts] == [
        ('guard_settings_loosened', 'staff-1', ['daily', 'daily_advanced', 'daily_expert']),
        ('guard_settings_loosened', 'staff-2', ['proven_if_signal_while_throttled']),
    ]
