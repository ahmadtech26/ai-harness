"""The BM25 index (recall plan Task 2.2), ported from the bench (engine.rs) and its checked Python re-scoring
(.hq/scratch/recall-gap-2026-11-09/anatomy/tb2_bm25.py, 80/80 top-10 lists identical to the bench's T-B2)."""

import math

from legal_search import bm25
from legal_search.bm25 import Doc, Index, Settings, fieldnorm_table, quantise

BASE = Settings('dismax', 0.5, 0.0, 0.0, 0.0, 16, 0.0, True, True)


def settings(**changes):
    values = {**BASE.__dict__, **changes}
    return Settings(**values)


def doc(doc_id, body, law='civil-code', number=None, heading=(), title=()):
    return Doc(doc_id, law, number if number is not None else doc_id, '', tuple(body), tuple(heading), tuple(title))


def bm25_of(tf, dl, avg, df, n):
    """Tantivy's BM25 written out: idf · (1 + k1) · tf / (tf + k1 · (1 − b + b · dl / avg)), dl quantised."""
    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
    return idf * 2.2 * tf / (tf + 1.2 * (1 - 0.75 + 0.75 * quantise(dl) / avg))


def test_bm25_score_of_a_toy_corpus_matches_the_hand_computed_value():
    docs = [doc(1, ['عقد', 'بيع']), doc(2, ['عقد', 'عقد', 'ايجار']), doc(3, ['بيع'])]

    ranked = Index.build(docs).search(['عقد'], [], BASE, None, 10)

    avg = (2 + 3 + 1) / 3
    assert [doc_id for doc_id, _ in ranked] == [2, 1]
    assert math.isclose(ranked[0][1], bm25_of(2, 3, avg, 2, 3), rel_tol=1e-12)
    assert math.isclose(ranked[1][1], bm25_of(1, 2, avg, 2, 3), rel_tol=1e-12)


def test_fieldnorm_quantisation_matches_tantivy():
    assert fieldnorm_table()[:42] == list(range(41)) + [42] and quantise(43) == 42


def test_dismax_takes_the_best_expansion_with_prefixes_at_half_weight():
    # Doc 1 holds the exact term and a longer word that starts with it; doc 2 holds only the longer word.
    docs = [doc(1, ['عقد', 'عقده']), doc(2, ['عقده', 'بيع']), doc(3, ['بيع', 'بيع'])]
    index = Index.build(docs)

    dismax = dict(index.search(['عقد'], [], BASE, None, 10))
    summed = dict(index.search(['عقد'], [], settings(prefix_mode='sum'), None, 10))

    avg = 2.0
    exact, longer_1 = bm25_of(1, 2, avg, 1, 3), bm25_of(1, 2, avg, 2, 3)
    assert math.isclose(dismax[1], max(exact, 0.5 * longer_1), rel_tol=1e-12)
    assert math.isclose(summed[1], exact + 0.5 * longer_1, rel_tol=1e-12)
    assert math.isclose(dismax[2], 0.5 * bm25_of(1, 2, avg, 2, 3), rel_tol=1e-12)


def test_exact_mode_never_expands_a_prefix():
    docs = [doc(1, ['عقده']), doc(2, ['بيع'])]

    ranked = Index.build(docs).search(['عقد'], [], settings(prefix_mode='exact'), None, 10)

    assert ranked == []


def test_the_law_filter_keeps_idf_from_the_whole_corpus():
    docs = [doc(1, ['عقد'], law='civil-code'), doc(2, ['عقد'], law='penal-code'), doc(3, ['بيع'], law='penal-code')]
    index = Index.build(docs)

    whole = dict(index.search(['عقد'], [], BASE, None, 10))
    filtered = index.search(['عقد'], [], BASE, 'civil-code', 10)

    assert [doc_id for doc_id, _ in filtered] == [1]
    assert filtered[0][1] == whole[1]          # df 2 of 3 documents, not 1 of 1 within the law


def test_ties_break_on_number_then_codepoint_slug_then_suffix():
    docs = [Doc(1, 'penal-code', 2, '', ('عقد',), (), ()), Doc(2, 'civil-code', 2, '', ('عقد',), (), ()),
            Doc(3, 'civil-code', 1, '', ('عقد',), (), ()), Doc(4, 'civil-code', 2, 'مكرر', ('عقد',), (), ())]

    ranked = Index.build(docs).search(['عقد'], [], BASE, None, 10)

    assert [doc_id for doc_id, _ in ranked] == [3, 2, 4, 1]


def test_proximity_rewards_close_pairs_only_inside_the_window_and_the_pool(monkeypatch):
    filler = ['حشو'] * 20
    docs = [doc(1, ['عقد', 'بيع'] + filler), doc(2, ['عقد'] + filler + ['بيع']), doc(3, ['اخر'] * 22)]
    index = Index.build(docs)
    plain = dict(index.search(['عقد', 'بيع'], [], BASE, None, 10))
    near = settings(proximity_weight=2.0, proximity_window=16)

    boosted = dict(index.search(['عقد', 'بيع'], [], near, None, 10))

    rarest = math.log(1 + (3 - 2 + 0.5) / (2 + 0.5))      # both terms are in 2 of 3 documents
    assert math.isclose(boosted[1], plain[1] + 2.0 * rarest / 1, rel_tol=1e-12)   # adjacent: distance 1
    assert boosted[2] == plain[2]                                                 # 21 apart: outside the window
    monkeypatch.setattr(bm25, 'CANDIDATES_RERANK', 1)
    pooled = dict(index.search(['عقد', 'بيع'], [], near, None, 10))
    assert sorted(pooled) == [1]                                                  # only the pool is kept and scored


def test_df_drop_keeps_the_rarest_term():
    common = [doc(i, ['شائع', 'متوسط']) for i in range(1, 9)]
    docs = common + [doc(9, ['شائع', 'نادر']), doc(10, ['شائع'])]
    index = Index.build(docs)

    dropped = index.search(['شائع', 'نادر'], [], settings(df_drop=0.5), None, 10)
    all_common = index.search(['شائع', 'متوسط'], [], settings(df_drop=0.5), None, 10)

    assert [doc_id for doc_id, _ in dropped] == [9]                      # «شائع» (df 10 > 5) dropped, «نادر» kept
    assert sorted(doc_id for doc_id, _ in all_common) == list(range(1, 9))   # both over the limit: «متوسط» (df 8) kept


def test_a_multi_word_synonym_scores_as_a_phrase_in_the_body():
    docs = [doc(1, ['مرور', 'زمان', 'دعوي']), doc(2, ['زمان', 'مرور']), doc(3, ['دعوي'])]

    ranked = dict(Index.build(docs).search(['دعوي'], [['مرور', 'زمان']], BASE, None, 10))

    assert set(ranked) == {1, 3} and ranked[1] > ranked[3]     # «زمان مرور» in the wrong order is no phrase


def test_no_terms_returns_nothing():
    assert Index.build([Doc(1, 'x', 1, '', ('عقد',), (), ())]).search([], [], BASE, None, 10) == []
