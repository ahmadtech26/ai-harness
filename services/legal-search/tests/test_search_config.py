from dataclasses import dataclass

import pytest

from legal_search.search_config import with_overrides


@dataclass(frozen=True)
class Knobs:
    level: int = 0
    weight: float = 0.0
    enabled: bool = False
    name: str = ''


def test_overrides_coerce_values_to_the_field_types():
    assert with_overrides(Knobs(), ['level=4', 'weight=0.5', 'enabled=true', 'name=query']) == Knobs(4, 0.5, True, 'query')
    assert with_overrides(Knobs(enabled=True), ['enabled=false']) == Knobs(enabled=False)
    with pytest.raises(ValueError, match="enabled takes true or false, not 'yes'"):
        with_overrides(Knobs(), ['enabled=yes'])


def test_an_unknown_setting_is_rejected_naming_the_valid_ones():
    with pytest.raises(ValueError, match='settings: enabled, level, name, weight'):
        with_overrides(Knobs(), ['levle=4'])
