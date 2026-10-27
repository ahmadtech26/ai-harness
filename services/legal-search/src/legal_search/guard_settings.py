"""Guard settings (spec C.3): the sweep detector's thresholds and the extraction caps. Staff change them at
run time; storage, history and the cache follow below the validation."""

from dataclasses import asdict, dataclass, fields

from legal_search.caps import Caps


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


def merged(current: GuardSettings, changes: dict) -> GuardSettings:
    """`current` with `changes` applied, validated as a whole."""
    return validate({**current.as_dict(), **changes})
