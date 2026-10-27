"""Retrieval metrics (spec B.2) and the tuning keep rule (REQ-EVL-004). Pure functions over ranked keys.

recall@k: the fraction of an item's expected articles in its top k, averaged over items.
hit@k: the share of items with at least one expected article in the top k.
MRR: the reciprocal rank of the first expected article found (0 if none in the top DEPTH), averaged.
"""

from dataclasses import dataclass
from statistics import fmean

Key = tuple[str, int, str]  # (law slug, number, suffix)
DEPTH = 10  # results fetched per item
PRECISION = 4  # decimals reported; the keep rule compares reported values
METRICS = ('recall@5', 'recall@10', 'hit@5', 'hit@10', 'mrr')


@dataclass(frozen=True)
class Scored:
    """One item's outcome: the law it is reported under, its expected keys, the ranked keys returned."""

    law: str
    expected: frozenset[Key]
    ranked: tuple[Key, ...]


def recall_at(expected: frozenset[Key], ranked: tuple[Key, ...], k: int) -> float:
    return len(expected & set(ranked[:k])) / len(expected)


def hit_at(expected: frozenset[Key], ranked: tuple[Key, ...], k: int) -> float:
    return 1.0 if expected & set(ranked[:k]) else 0.0


def reciprocal_rank(expected: frozenset[Key], ranked: tuple[Key, ...]) -> float:
    for rank, key in enumerate(ranked[:DEPTH], 1):
        if key in expected:
            return 1 / rank
    return 0.0


def item_metrics(scored: Scored) -> dict[str, float]:
    expected, ranked = scored.expected, scored.ranked
    return {
        'recall@5': recall_at(expected, ranked, 5),
        'recall@10': recall_at(expected, ranked, 10),
        'hit@5': hit_at(expected, ranked, 5),
        'hit@10': hit_at(expected, ranked, 10),
        'mrr': reciprocal_rank(expected, ranked),
    }


def _mean(rows: list[dict[str, float]]) -> dict:
    summary: dict = {name: round(fmean(row[name] for row in rows), PRECISION) for name in METRICS}
    summary['items'] = len(rows)
    return summary


def summarise(scored: list[Scored]) -> dict:
    """{'overall': means, 'per_law': {law: means}}, laws sorted by slug; each block also counts its items."""
    rows: list[dict[str, float]] = []
    by_law: dict[str, list[dict[str, float]]] = {}
    for item in scored:
        row = item_metrics(item)
        rows.append(row)
        by_law.setdefault(item.law, []).append(row)
    return {'overall': _mean(rows), 'per_law': {law: _mean(by_law[law]) for law in sorted(by_law)}}


def keep_decision(incumbent: dict, candidate: dict) -> tuple[bool, list[str]]:
    """REQ-EVL-004 plus two guards. A step is kept only if overall recall@5 and overall MRR do not drop, no
    law's recall@5 drops, and overall recall@5 or MRR rises. Returns (keep, the reasons it is not kept)."""
    reasons = []
    before, after = incumbent['overall'], candidate['overall']
    for name in ('recall@5', 'mrr'):
        if after[name] < before[name]:
            reasons.append(f'overall {name} drops {before[name]:.4f} -> {after[name]:.4f}')
    for law, row in sorted(incumbent['per_law'].items()):
        new = candidate['per_law'].get(law, {}).get('recall@5', 0.0)
        if new < row['recall@5']:
            reasons.append(f'{law} recall@5 drops {row["recall@5"]:.4f} -> {new:.4f}')
    if not reasons and after['recall@5'] == before['recall@5'] and after['mrr'] == before['mrr']:
        reasons.append('no change in overall recall@5 or MRR')
    return not reasons, reasons


def targets_missed(metrics: dict, *, recall5: float, law_floor: float, mrr: float) -> list[str]:
    """Each agreed target (REQ-EVL-003) the run misses; empty when every target is met."""
    overall = metrics['overall']
    missed = []
    if overall['recall@5'] < recall5:
        missed.append(f'overall recall@5 {overall["recall@5"]:.4f} < {recall5:g}')
    missed += [f'{law} recall@5 {row["recall@5"]:.4f} < {law_floor:g}'
               for law, row in metrics['per_law'].items() if row['recall@5'] < law_floor]
    if overall['mrr'] < mrr:
        missed.append(f'overall MRR {overall["mrr"]:.4f} < {mrr:g}')
    return missed
