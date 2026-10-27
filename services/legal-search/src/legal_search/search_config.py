"""Search tuning settings (plan-phase3-retrieval-eval). Every field's default is what db.search does in
production; the evaluation runner overrides fields with --config name=value to measure a candidate, and a kept
candidate becomes the new default (P3-results tuning log)."""

from dataclasses import dataclass, fields, replace

from legal_search.normalize import normalize

# Words a query carries that name the question or the law rather than its subject. In an OR of prefix terms they
# also match unrelated words (`اي:*` matches «ايجار», `مدي:*` matches «مدين»), so they add noise. «الأردني» is not
# here: it is the subject of some questions (jurisdiction over Jordanians abroad, Jordanian vs foreign companies).
QUERY_STOPWORDS = frozenset(
    normalize(word)
    # Not «بشأن»: it normalises to «شان», which would also drop the noun in «ذوي الشأن» / «صاحب الشأن».
    for word in 'كيف متى ماذا لماذا كم أي هناك يوجد حول بخصوص مدى مسألة حالة حالات القانون قانون المادة مادة المواد نص'.split()
)


@dataclass(frozen=True)
class SearchConfig:
    # ts_rank_cd normalisation bit mask: 0 ignores document length (PostgreSQL 17 text-search docs, "Ranking").
    rank_normalization: int = 4  # adopted 2026-10-27, eval-c2-rank-4 (P3-results tuning log)
    # Also drop QUERY_STOPWORDS from queries (candidate C3).
    query_stopwords: bool = False


DEFAULT = SearchConfig()


def with_overrides(base, items: list[str]):
    """`base` (a dataclass) with each `name=value` applied, coerced to the field's type; unknown names fail."""
    known = {field.name: field for field in fields(base)}
    changes = {}
    for item in items:
        name, separator, value = item.partition('=')
        if not separator or name not in known:
            raise ValueError(f'unknown setting {item!r}; settings: {", ".join(sorted(known)) or "(none)"}')
        changes[name] = _coerce(known[name].type, name, value)
    return replace(base, **changes)


def _coerce(kind: type, name: str, value: str):
    if kind is bool:
        if value not in ('true', 'false'):
            raise ValueError(f'{name} takes true or false, not {value!r}')
        return value == 'true'
    if kind is int:
        return int(value)
    if kind is float:
        return float(value)
    return value
