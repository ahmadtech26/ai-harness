"""Guard settings (spec C.3): the sweep detector's thresholds and the extraction caps, held in Postgres so
staff can change them without a restart. One current row (`guard_settings`) and an append-only history
(`guard_settings_history`: who, when, why, the previous values). The environment's caps only seed the row
on first start. Readers go through SettingsCache, so a change takes effect within CACHE_SECONDS."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, fields

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from legal_search.alerts import alert
from legal_search.caps import Caps

CACHE_SECONDS = 30.0


class SettingsError(ValueError):
    """A rejected setting or settings change. `rule` names the rule it breaks (returned to staff as is);
    `category` is the admin API's error: `invalid_settings` for a value, `bad_request` for a change without
    its staff member or reason."""

    def __init__(self, rule: str, message: str, category: str = 'invalid_settings') -> None:
        super().__init__(f'{rule}: {message}')
        self.rule = rule
        self.message = message
        self.category = category


@dataclass(frozen=True)
class GuardSettings:
    suspected_run: int = 12
    proven_run: int = 30
    run_gap: int = 2
    run_window_hours: int = 24
    suspected_distinct_7d: int = 300
    proven_distinct_7d: int = 750
    suspected_cap_days: int = 2
    throttle_daily_cap: int = 10
    proven_if_signal_while_throttled: bool = True
    max_results: int = 5
    per_answer: int = 8
    daily: int = 300

    @property
    def caps(self) -> Caps:
        return Caps(per_answer=self.per_answer, daily=self.daily, max_results=self.max_results)

    def as_dict(self) -> dict:
        return asdict(self)


NAMES = tuple(field.name for field in fields(GuardSettings))
_FLAGS = ('proven_if_signal_while_throttled',)
_PAIRS = (('suspected_run', 'proven_run'), ('suspected_distinct_7d', 'proven_distinct_7d'))
# A wider gap or window catches more runs, so these loosen the guard when they fall (R1 n=18).
_LOOSER_WHEN_LOWER = ('run_gap', 'run_window_hours')
# Ceilings: every window must stay a usable time span (a huge run_window overflows the date arithmetic on
# every retrieval), and no count needs to exceed a million.
MAX_COUNT = 1_000_000
CEILINGS = {'run_window_hours': 720}


def validate(values: dict) -> GuardSettings:
    """GuardSettings from a complete mapping; SettingsError names the first rule broken."""
    unknown = sorted(set(values) - set(NAMES))
    if unknown:
        raise SettingsError('unknown_setting', f'unknown settings: {", ".join(unknown)}')
    missing = [name for name in NAMES if name not in values]
    if missing:
        raise SettingsError('missing_setting', f'missing settings: {", ".join(missing)}')
    for name in NAMES:
        value = values[name]
        if name in _FLAGS:
            if type(value) is not bool:
                raise SettingsError('boolean', f'{name} must be true or false, got {value!r}')
            continue
        if type(value) is not int or value <= 0:
            raise SettingsError('positive', f'{name} must be a positive integer, got {value!r}')
        ceiling = CEILINGS.get(name, MAX_COUNT)
        if value > ceiling:
            raise SettingsError('too_large', f'{name} must be at most {ceiling}, got {value}')
    for low, high in _PAIRS:
        if values[low] >= values[high]:
            raise SettingsError('suspected_below_proven', f'{low} ({values[low]}) must be below {high} ({values[high]})')
    if values['throttle_daily_cap'] >= values['daily']:
        raise SettingsError(
            'throttle_below_daily',
            f'throttle_daily_cap ({values["throttle_daily_cap"]}) must be below daily ({values["daily"]})',
        )
    return GuardSettings(**values)


def loosened(previous: GuardSettings, updated: GuardSettings) -> list[str]:
    """The settings a change made more permissive: a higher cap or threshold, a narrower run gap or window,
    or the escalation switched off."""
    names = []
    for name in NAMES:
        before, after = getattr(previous, name), getattr(updated, name)
        if name in _FLAGS:
            looser = before and not after
        elif name in _LOOSER_WHEN_LOWER:
            looser = after < before
        else:
            looser = after > before
        if looser:
            names.append(name)
    return names


def merged(current: GuardSettings, changes: dict) -> GuardSettings:
    """`current` with `changes` applied, validated as a whole."""
    return validate({**current.as_dict(), **changes})


def _settings_from(stored: dict) -> GuardSettings:
    """Stored values over today's defaults: a setting added later starts at its default; a dropped one is ignored."""
    known = {name: value for name, value in stored.items() if name in NAMES}
    return validate({**GuardSettings().as_dict(), **known})


async def ensure_settings(conn: AsyncConnection, defaults: GuardSettings) -> GuardSettings:
    """First start: the current row from `defaults` (the environment's caps), with a history entry. Never overwrites."""
    defaults = validate(defaults.as_dict())
    async with conn.transaction():
        cur = await conn.execute(
            "INSERT INTO guard_settings (id, settings, updated_by) VALUES (1, %s, 'environment') "
            'ON CONFLICT (id) DO NOTHING RETURNING id',
            (Jsonb(defaults.as_dict()),),
        )
        if await cur.fetchone() is not None:
            await conn.execute(
                'INSERT INTO guard_settings_history (changed_by, reason, previous, settings) VALUES (%s, %s, NULL, %s)',
                ('environment', 'first start: defaults from the environment', Jsonb(defaults.as_dict())),
            )
    return await load_settings(conn)


async def load_settings(conn: AsyncConnection) -> GuardSettings:
    cur = await conn.execute('SELECT settings FROM guard_settings WHERE id = 1')
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError('guard settings are not initialised (ensure_settings runs at service start)')
    return _settings_from(row[0])


async def current(conn: AsyncConnection) -> dict:
    """The current settings, who changed them last and when (the admin API's GET)."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute('SELECT settings, updated_by, updated_at FROM guard_settings WHERE id = 1')
        row = await cur.fetchone()
    return {
        'settings': _settings_from(row['settings']).as_dict(),
        'updated_by': row['updated_by'],
        'updated_at': row['updated_at'].isoformat(),
    }


async def update_settings(conn: AsyncConnection, changes: dict, who: str | None, why: str | None) -> GuardSettings:
    """Applies `changes` over the current settings and records who, when, why and the previous values.
    Raises SettingsError (and changes nothing) for a missing staff member or reason, or an invalid value."""
    if not (who or '').strip():
        raise SettingsError('staff_required', 'the staff member making the change is required', 'bad_request')
    if not (why or '').strip():
        raise SettingsError('reason_required', 'a reason is required', 'bad_request')
    async with conn.transaction():
        cur = await conn.execute('SELECT settings FROM guard_settings WHERE id = 1 FOR UPDATE')
        previous = _settings_from((await cur.fetchone())[0])
        updated = merged(previous, changes)
        await conn.execute(
            'UPDATE guard_settings SET settings = %s, updated_by = %s, updated_at = now() WHERE id = 1',
            (Jsonb(updated.as_dict()), who.strip()),
        )
        await conn.execute(
            'INSERT INTO guard_settings_history (changed_by, reason, previous, settings) VALUES (%s, %s, %s, %s)',
            (who.strip(), why.strip(), Jsonb(previous.as_dict()), Jsonb(updated.as_dict())),
        )
    looser = loosened(previous, updated)
    if looser:
        # A loosening must be noticed, not only kept in the history table (R1 n=18).
        alert('guard_settings_loosened', changed_by=who.strip(), reason=why.strip(), loosened=looser,
              previous={name: getattr(previous, name) for name in looser},
              settings={name: getattr(updated, name) for name in looser})
    return updated


async def history(conn: AsyncConnection, limit: int = 100) -> list[dict]:
    """Settings changes, newest first."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            'SELECT id, changed_by, changed_at, reason, previous, settings FROM guard_settings_history '
            'ORDER BY id DESC LIMIT %s',
            (limit,),
        )
        rows = await cur.fetchall()
    return [{**row, 'changed_at': row['changed_at'].isoformat()} for row in rows]


class SettingsCache:
    """The current settings, re-read once they are `ttl` seconds old, so a change applies within `ttl`. A read's
    age counts from when it started, and a read that an invalidate() overtakes is returned but not kept."""

    def __init__(self, ttl: float = CACHE_SECONDS, clock: Callable[[], float] = time.monotonic,
                 loader: Callable[[AsyncConnection], Awaitable[GuardSettings]] = load_settings) -> None:
        self._ttl = ttl
        self._clock = clock
        self._loader = loader
        self._value: GuardSettings | None = None
        self._loaded_at = 0.0
        self._generation = 0

    async def get(self, conn: AsyncConnection) -> GuardSettings:
        if self._value is not None and self._clock() - self._loaded_at < self._ttl:
            return self._value
        started, generation = self._clock(), self._generation
        value = await self._loader(conn)
        if generation == self._generation:  # no invalidate() while reading: the value is no older than `started`
            self._value, self._loaded_at = value, started
        return value

    def invalidate(self) -> None:
        """The next `get` reads the database, and a read already under way is not kept (the admin API calls
        this after a change in this process)."""
        self._generation += 1
        self._value = None
