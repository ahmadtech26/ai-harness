from dataclasses import dataclass

import pytest

from legal_search import db
from legal_search.search_config import DEFAULT, SEARCH_CONFIG, SearchConfig, search_config_from_env, with_overrides


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


def test_bm25_defaults_are_the_bench_dismax_base():
    c = with_overrides(DEFAULT, ['ranker=bm25'])
    assert (c.prefix_mode, c.prefix_weight, c.title_weight, c.heading_weight, c.proximity_weight,
            c.proximity_window, c.analyser, c.df_drop, c.stoplist) == ('dismax', 0.5, 0.0, 0.0, 0.0, 16, 'today', 0.0, True)


def test_a_bm25_setting_is_refused_while_the_ranker_is_postgres():
    with pytest.raises(ValueError, match='ranker=bm25'):
        with_overrides(DEFAULT, ['heading_weight=1.0'])


@pytest.mark.parametrize('item', ['ranker=tantivy', 'analyser=snowball', 'prefix_mode=fuzzy'])
def test_an_unknown_ranker_analyser_or_prefix_mode_is_refused(item):
    name = item.partition('=')[0]
    with pytest.raises(ValueError, match=f'^{name} must be one of'):
        with_overrides(DEFAULT, ['ranker=bm25', item] if not item.startswith('ranker=') else [item])


def test_overrides_set_float_and_string_fields():
    c = with_overrides(DEFAULT, ['ranker=bm25', 'proximity_weight=2.0', 'analyser=guardlight'])
    assert (c.proximity_weight, c.analyser) == (2.0, 'guardlight')


# One value off its default for each of the nine BM25 fields, so a field left out of the guard fails here.
@pytest.mark.parametrize('item', ['prefix_mode=sum', 'prefix_weight=1.0', 'title_weight=0.5', 'heading_weight=1.0',
                                  'proximity_weight=2.0', 'proximity_window=8', 'analyser=guardlight', 'df_drop=0.1',
                                  'stoplist=false'])
def test_every_bm25_setting_is_refused_while_the_ranker_is_postgres(item):
    name = item.partition('=')[0]

    with pytest.raises(ValueError, match=f'^{name} applies only with ranker=bm25$'):
        with_overrides(DEFAULT, [item])

    assert getattr(with_overrides(DEFAULT, ['ranker=bm25', item]), name) != getattr(DEFAULT, name)


def test_a_config_built_directly_is_validated():
    with pytest.raises(ValueError, match='^ranker must be one of'):
        SearchConfig(ranker='tantivy')
    with pytest.raises(ValueError, match='^heading_weight applies only with ranker=bm25$'):
        SearchConfig(heading_weight=1.0)


def test_search_config_from_env_reads_overrides_and_defaults_when_unset(monkeypatch):
    # Recall plan Task 3.2: only the timing stack sets the variable; unset, the server runs DEFAULT, as today.
    monkeypatch.delenv(SEARCH_CONFIG, raising=False)
    unset = search_config_from_env()
    monkeypatch.setenv(SEARCH_CONFIG, 'ranker=bm25, heading_weight=1.0')

    configured = search_config_from_env()

    assert unset is DEFAULT
    assert configured == with_overrides(DEFAULT, ['ranker=bm25', 'heading_weight=1.0'])


def test_search_config_from_env_refuses_an_unknown_setting(monkeypatch):
    monkeypatch.setenv(SEARCH_CONFIG, 'ranker=bm25,heading=1.0')

    with pytest.raises(ValueError, match="^unknown setting 'heading=1.0'"):
        search_config_from_env()
