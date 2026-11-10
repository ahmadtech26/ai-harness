"""Search tuning settings (plan-phase3-retrieval-eval). Every field's default is what db.search does in
production; the evaluation runner overrides fields with --config name=value to measure a candidate, and a kept
candidate becomes the new default (P3-results tuning log)."""

from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class SearchConfig:
    # ts_rank_cd normalisation bit mask: 0 ignores document length (PostgreSQL 17 text-search docs, "Ranking").
    rank_normalization: int = 4  # adopted 2026-10-27, eval-c2-rank-4 (P3-results tuning log)
    # Add legal synonyms (synonyms.GROUPS) to queries (candidate C4).
    synonyms: bool = True  # adopted 2026-10-28, eval-c4-synonyms
    # Which search ranks: 'pg' is today's Postgres search (ts_rank_cd), 'bm25' the in-process BM25 engine.
    ranker: str = 'pg'
    # The BM25 levers, one field per lever (recall plan 2026-11-09, Task 1.1). They apply only with ranker='bm25'
    # (validate). Their defaults are the bench's dis-max base `r2|base` (rag-bench py/configs.py round2: mode dismax,
    # exp_w 0.5, analyser today, stoplist on, no title, heading or proximity weight, no df-drop), so each bench lever
    # row is this base with one field changed. One exception: proximity_window is 16, the window of the b3d and
    # round-3 rows; `r2|base` keeps the engine's default of 8 (engine.rs Cfg), unread at proximity_weight 0.
    prefix_mode: str = 'dismax'  # a term's prefix expansions scored as a sum, a dis-max, or not expanded (exact)
    prefix_weight: float = 0.5  # the boost on an expansion that is not the term itself (exp_w)
    title_weight: float = 0.0  # the law-title field (w_title)
    heading_weight: float = 0.0  # the article-heading field (w_head)
    proximity_weight: float = 0.0  # the proximity bonus after BM25 (prox_l); 0 is off
    proximity_window: int = 16  # words (prox_w); read only when proximity_weight > 0, as in `r2|b3d|l2.0|w16`
    analyser: str = 'today'  # 'today' (normalize.tokens) or 'guardlight' (the bench's stem_fixed + strip_one_suffix)
    df_drop: float = 0.0  # drop query terms in more than this share of articles, the rarest kept (df_drop); 0 is off
    stoplist: bool = True  # drop stopwords from the query

    def __post_init__(self):
        validate(self)


RANKERS = ('pg', 'bm25')
PREFIX_MODES = ('sum', 'dismax', 'exact')
ANALYSERS = ('today', 'guardlight')
BM25_FIELDS = ('prefix_mode', 'prefix_weight', 'title_weight', 'heading_weight', 'proximity_weight',
               'proximity_window', 'analyser', 'df_drop', 'stoplist')


def validate(config: SearchConfig) -> None:
    """Refuse a value outside a field's choices, and a BM25 field changed from its default while ranker='pg', where
    the Postgres search would silently ignore it."""
    for name, choices in (('ranker', RANKERS), ('prefix_mode', PREFIX_MODES), ('analyser', ANALYSERS)):
        value = getattr(config, name)
        if value not in choices:
            raise ValueError(f'{name} must be one of {", ".join(choices)}, not {value!r}')
    if config.ranker == 'pg':
        for field in fields(config):
            if field.name in BM25_FIELDS and getattr(config, field.name) != field.default:
                raise ValueError(f'{field.name} applies only with ranker=bm25')


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
