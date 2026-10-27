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


def test_query_stopwords_drop_question_and_filler_words():
    # «متى» (a question word) and «القانون» go; «الأردني» stays: it can be the question's subject.
    query = 'متى أسترد العربون في القانون الأردني'

    assert db.build_tsquery(query, SearchConfig(query_stopwords=False)) == 'متي:* | استرد:* | عربون:* | قانون:* | اردني:*'
    assert db.build_tsquery(query, SearchConfig(query_stopwords=True)) == 'استرد:* | عربون:* | اردني:*'
    # Plan A's rule, kept in `query_terms`: a repeated term counts once and a one-letter term goes.
    assert db.build_tsquery('العربون د عربون', SearchConfig(query_stopwords=False)) == 'عربون:*'
