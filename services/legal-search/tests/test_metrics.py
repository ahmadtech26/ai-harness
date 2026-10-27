import argparse
import pytest

from legal_search.evaluate import EvalError, _label, compare
from legal_search.metrics import Scored, hit_at, keep_decision, recall_at, reciprocal_rank, summarise

A, B = ('civil-code', 1, ''), ('civil-code', 2, '')
X, Y, Z, W, V = (('civil-code', n, '') for n in (91, 92, 93, 94, 95))


def test_recall_at_k_is_the_fraction_of_expected_articles_in_the_top_k():
    ranked = (X, A, Y, Z, W, B)

    assert (recall_at(frozenset({A, B}), ranked, 5), recall_at(frozenset({A, B}), ranked, 10)) == (0.5, 1.0)


def test_hit_at_k_counts_an_item_with_any_expected_article_in_the_top_k():
    assert hit_at(frozenset({A, B}), (X, Y, Z, W, A), 5) == 1.0
    assert hit_at(frozenset({A, B}), (X, Y, Z, W, V, A), 5) == 0.0


def test_reciprocal_rank_is_one_over_the_rank_of_the_first_expected_article():
    assert reciprocal_rank(frozenset({A, B}), (X, Y, B, A)) == pytest.approx(1 / 3)


def test_reciprocal_rank_is_zero_when_nothing_expected_is_in_the_top_ten():
    ranked = tuple(('penal-code', n, '') for n in range(1, 11)) + (A,)

    assert reciprocal_rank(frozenset({A}), ranked) == 0.0


def test_summary_averages_items_overall_and_per_law():
    # Items 2 and 3 have an expected article at rank 6, so every @5 differs from its @10.
    scored = [
        Scored('civil-code', frozenset({A}), (A,)),  # recall 1, hit 1, rr 1
        Scored('civil-code', frozenset({A, B}), (X, A, Y, Z, W, B)),  # recall@5 0.5, recall@10 1, hit 1, rr 0.5
        Scored('majalla', frozenset({('majalla', 76, '')}), (X, Y, Z, W, V, ('majalla', 76, ''))),  # recall@5 0, recall@10 1, hit@5 0, hit@10 1, rr 1/6
    ]

    summary = summarise(scored)

    assert summary['overall'] == {'recall@5': 0.5, 'recall@10': 1.0, 'hit@5': 0.6667, 'hit@10': 1.0, 'mrr': 0.5556, 'items': 3}
    assert summary['per_law'] == {
        'civil-code': {'recall@5': 0.75, 'recall@10': 1.0, 'hit@5': 1.0, 'hit@10': 1.0, 'mrr': 0.75, 'items': 2},
        'majalla': {'recall@5': 0.0, 'recall@10': 1.0, 'hit@5': 0.0, 'hit@10': 1.0, 'mrr': 0.1667, 'items': 1},
    }


def _metrics(recall5: float, mrr: float, per_law: dict[str, float]) -> dict:
    # Every metric is filled, so compare() can print its deltas over these too.
    overall = {'recall@5': recall5, 'recall@10': recall5, 'hit@5': recall5, 'hit@10': recall5, 'mrr': mrr}
    return {'overall': overall, 'per_law': {law: {**overall, 'recall@5': value} for law, value in per_law.items()}}


BEFORE = _metrics(0.60, 0.50, {'civil-code': 0.70, 'penal-code': 0.50})


def test_a_step_that_raises_overall_recall_without_lowering_any_law_is_kept():
    after = _metrics(0.65, 0.50, {'civil-code': 0.80, 'penal-code': 0.50})

    assert keep_decision(BEFORE, after) == (True, [])


def test_a_step_that_lowers_one_law_is_reverted_even_when_overall_recall_rises():
    after = _metrics(0.70, 0.55, {'civil-code': 0.90, 'penal-code': 0.40})

    lines = compare({'run': {'label': 'baseline', 'set_sha256': 'a', 'corpus_sha256': 'c'}, 'metrics': BEFORE},
                    {'run': {'label': 'c1', 'set_sha256': 'a', 'corpus_sha256': 'c'}, 'metrics': after})

    assert keep_decision(BEFORE, after) == (False, ['penal-code recall@5 drops 0.5000 -> 0.4000'])
    # compare() passes the runs in the right order and prints the verdict the tuning steps act on.
    assert 'verdict: REVERT (penal-code recall@5 drops 0.5000 -> 0.4000)' in lines and 'identical: no' in lines


def test_a_step_that_lowers_overall_mrr_is_reverted():
    after = _metrics(0.65, 0.45, {'civil-code': 0.80, 'penal-code': 0.50})

    assert keep_decision(BEFORE, after) == (False, ['overall mrr drops 0.5000 -> 0.4500'])


def test_a_step_that_changes_nothing_is_reverted():
    assert keep_decision(BEFORE, BEFORE) == (False, ['no change in overall recall@5 or MRR'])


@pytest.mark.parametrize('field', ['set_sha256', 'corpus_sha256'])
def test_compare_refuses_runs_on_different_sets_or_corpora(field):
    incumbent = {'run': {'set_sha256': 'a', 'corpus_sha256': 'c'}, 'metrics': BEFORE}
    candidate = {'run': {**incumbent['run'], field: 'other'}, 'metrics': BEFORE}

    with pytest.raises(EvalError, match=f'the runs differ in {field}'):
        compare(incumbent, candidate)


def test_labels_keep_report_files_inside_the_out_directory():
    # A label becomes eval-<label>.json under --out: no separators, no leading dot, nothing a path could climb with.
    assert _label('c5-boost-0.5') == 'c5-boost-0.5'
    for label in ('../baseline', 'a/b', '.hidden', 'Baseline', 'final\n', ''):
        with pytest.raises(argparse.ArgumentTypeError):
            _label(label)
