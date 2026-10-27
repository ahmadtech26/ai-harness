from dataclasses import dataclass

import pytest

from legal_search import db
from legal_search.search_config import SearchConfig, with_overrides


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


def test_synonyms_add_the_other_members_of_a_matched_group():
    assert db.build_tsquery('تقادم دعوى الدين', SearchConfig(synonyms=True)) == (
        'تقادم:* | دعوي:* | دين:* | (مرور:* <-> زمان:*) | (مرور:* <-> زمن:*)')
    # «الضمان» joins «التعويض» only as «ضمان الضرر»: bare «ضمان» also means warranty or guarantee.
    assert db.build_tsquery('التعويض', SearchConfig(synonyms=True)) == 'تعويض:* | (ضمان:* <-> ضرر:*)'
    assert db.build_tsquery('ضمان العيب', SearchConfig(synonyms=True)) == 'ضمان:* | عيب:*'


def test_a_multiword_member_in_the_query_adds_the_single_word_synonym():
    assert db.build_tsquery('مرور الزمان على الدعوى', SearchConfig(synonyms=True)) == (
        'مرور:* | زمان:* | دعوي:* | تقادم:* | (مرور:* <-> زمن:*)')
    # Maritime Commerce and Civil Procedure write «مرور الزمن» (e.g. «الدفع بمرور الزمن»).
    assert db.build_tsquery('الدفع بمرور الزمن', SearchConfig(synonyms=True)) == (
        'دفع:* | مرور:* | زمن:* | تقادم:* | (مرور:* <-> زمان:*)')
    assert db.build_tsquery('ضمان الضرر', SearchConfig(synonyms=True)) == 'ضمان:* | ضرر:* | تعويض:*'
