"""The BM25 index (recall plan Task 2.2), ported from the bench (engine.rs) and its checked Python re-scoring
(.hq/scratch/recall-gap-2026-11-09/anatomy/tb2_bm25.py, 80/80 top-10 lists identical to the bench's T-B2).

Expected scores are written from Tantivy's formula, never read back from the engine. The tests from
test_fieldnorm_steps_double_every_eight_values_up_to_tantivys_last_entry on pin what Gate P2 cannot see (it compares
top-10 lists on 80 items, all in dis-max) or saw only through the corpus (review 2026-11-11, engine lens)."""

import math

import pytest

from legal_search import bm25
from legal_search.bm25 import Doc, Index, Settings, fieldnorm_table, quantise

BASE = Settings('dismax', 0.5, 0.0, 0.0, 0.0, 16, 0.0, True, True)


def settings(**changes):
    values = {**BASE.__dict__, **changes}
    return Settings(**values)


def doc(doc_id, body, law='civil-code', number=None, heading=(), title=(), suffix=''):
    return Doc(doc_id, law, number if number is not None else doc_id, suffix, tuple(body), tuple(heading), tuple(title))


def idf_of(df, n):
    """Tantivy's idf: ln(1 + (N − df + 0.5) / (df + 0.5)), over the whole index."""
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


def bm25_of(tf, dl, avg, df, n):
    """Tantivy's BM25 written out: idf · (1 + k1) · tf / (tf + k1 · (1 − b + b · dl / avg)), dl quantised."""
    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
    return idf * 2.2 * tf / (tf + 1.2 * (1 - 0.75 + 0.75 * quantise(dl) / avg))


def ids(ranked):
    return [doc_id for doc_id, _ in ranked]


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
    # df 2 of 3 documents, not 1 of 1 within the law. The filter itself is scoreless, as in tb2_bm25.py; the bench's
    # filter is a scored Must clause that adds a per-law constant to every hit (engine-6), so its ranks are the same.
    assert filtered[0][1] == whole[1]


def test_ties_break_on_number_then_codepoint_slug_then_suffix():
    # The suffixed civil-code no. 2 is inserted before the plain one, so insertion order cannot pass for the suffix rule.
    docs = [doc(1, ['عقد'], law='penal-code', number=2), doc(2, ['عقد'], number=2, suffix='مكرر'),
            doc(3, ['عقد'], number=2), doc(4, ['عقد'], number=1, suffix='مكرر'), doc(5, ['عقد'], law='penal-code', number=1)]

    ranked = Index.build(docs).search(['عقد'], [], BASE, None, 10)

    assert ids(ranked) == [4, 5, 3, 2, 1]


def test_proximity_rewards_close_pairs_only_inside_the_window_and_the_pool(monkeypatch):
    filler = ['حشو'] * 20
    # Doc 2 has one more token than doc 1, so the pool of one below is decided by score, not by a tie (engine-4).
    docs = [doc(1, ['عقد', 'بيع'] + filler), doc(2, ['عقد'] + filler + ['بيع', 'حشو']), doc(3, ['اخر'] * 22)]
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


# Field lengths above 40 (engine-1). Tantivy stores a length as the largest table value not above it; the average
# is over the raw lengths (tantivy src/query/bm25.rs:109-111, src/fieldnorm/code.rs).

def test_fieldnorm_steps_double_every_eight_values_up_to_tantivys_last_entry():
    table = fieldnorm_table()

    assert (len(table), table[48:50], table[57], table[255]) == (256, [56, 60], 96, 2013265944)


def test_a_long_body_is_scored_with_its_quantised_length_and_the_raw_average():
    docs = [doc(1, ['عقد'] + ['حشو'] * 58), doc(2, ['عقد'])]          # 59 and 1 tokens: raw average 30

    ranked = dict(Index.build(docs).search(['عقد'], [], BASE, None, 10))

    norm = 56                                                           # 59 is stored as 56 (table: … 56, 60 …)
    assert math.isclose(ranked[1], idf_of(2, 2) * 2.2 / (1 + 1.2 * (0.25 + 0.75 * norm / 30)), rel_tol=1e-12)


# Title and heading fields (engine-0). T-B2 is heading 1.0 and title 0.5.

FIELD_DOCS = [doc(1, ['عقد'], heading=['بيع'], title=['مدني']), doc(2, ['عقد'], title=['مدني']),
              doc(3, ['بيع'], title=['عمل'])]


def test_a_heading_match_uses_the_heading_average_over_all_documents():
    index = Index.build(FIELD_DOCS)

    ranked = dict(index.search(['بيع'], [], settings(heading_weight=1.0), None, 10))

    # heading lengths 1, 0 and 0: average 1/3, not 1 (the non-empty headings only); heading df 1 of 3
    assert math.isclose(ranked[1], bm25_of(1, 1, 1 / 3, 1, 3), rel_tol=1e-12)


def test_the_heading_score_is_multiplied_by_the_heading_weight():
    index = Index.build(FIELD_DOCS)

    ranked = dict(index.search(['بيع'], [], settings(heading_weight=0.5), None, 10))

    assert math.isclose(ranked[1], 0.5 * bm25_of(1, 1, 1 / 3, 1, 3), rel_tol=1e-12)


def test_a_title_match_is_scored_by_the_title_weight():
    index = Index.build(FIELD_DOCS)

    ranked = index.search(['مدني'], [], settings(title_weight=0.5), None, 10)

    expected = 0.5 * bm25_of(1, 1, 1.0, 2, 3)                          # title lengths 1, 1, 1; title df 2 of 3
    assert ids(ranked) == [1, 2] and all(math.isclose(score, expected, rel_tol=1e-12) for _, score in ranked)


def test_a_field_of_weight_zero_is_not_searched():
    index = Index.build(FIELD_DOCS)

    ranked = index.search(['مدني'], [], BASE, None, 10)

    assert ranked == []                                                 # not two hits that score 0


def test_each_field_scores_a_term_with_its_own_document_frequency():
    docs = [doc(1, ['بيع'], heading=['بيع']), doc(2, ['بيع']), doc(3, ['عقد'])]     # body df 2, heading df 1

    ranked = dict(Index.build(docs).search(['بيع'], [], settings(heading_weight=1.0), None, 10))

    assert math.isclose(ranked[1], bm25_of(1, 1, 1.0, 2, 3) + bm25_of(1, 1, 1 / 3, 1, 3), rel_tol=1e-12)


# The law filter and the candidate cut (engine-2, engine-4; the cut is Tantivy's top 50, or 200 with proximity).

@pytest.mark.parametrize('proximity_weight', [0.0, 2.0])
def test_the_law_filter_applies_before_the_candidate_cut(proximity_weight):
    # 201 penal-code articles outscore the one civil-code article (tf 2 against 1): more than either pool holds.
    docs = [doc(i, ['عقد', 'عقد'], law='penal-code') for i in range(1, 202)] + [doc(202, ['عقد', 'حشو'])]

    ranked = Index.build(docs).search(['عقد'], [], settings(proximity_weight=proximity_weight), 'civil-code', 10)

    assert ids(ranked) == [202]


@pytest.mark.parametrize(('proximity_weight', 'pool'), [(0.0, 50), (2.0, 200)])
def test_the_candidate_pool_caps_the_results_whatever_the_depth(proximity_weight, pool):
    docs = [doc(i, ['عقد', 'بيع']) for i in range(1, 202)]            # 201 equal documents

    ranked = Index.build(docs).search(['عقد', 'بيع'], [], settings(proximity_weight=proximity_weight), None, 300)

    assert ids(ranked) == list(range(1, pool + 1))


def test_ties_at_the_candidate_cut_keep_the_first_inserted_document(monkeypatch):
    # Inserted first: Doc.id 7, article 9; second: Doc.id 3, article 1. Equal scores and a pool of one. Tantivy keeps
    # the lower DocId, which is the insertion order (the bench adds documents in x-*.jsonl line order).
    docs = [doc(7, ['عقد'], number=9), doc(3, ['عقد'], number=1)]
    monkeypatch.setattr(bm25, 'CANDIDATES', 1)

    ranked = Index.build(docs).search(['عقد'], [], BASE, None, 10)

    assert ids(ranked) == [7]


# Proximity (engine-3): per pair of query terms, min(idf) / distance for the closest distance, if 0 < distance ≤ window.

PROXIMITY_DOCS = [doc(1, ['عقد', 'بيع']), doc(2, ['عقد'] + ['حشو'] * 15 + ['بيع']),
                  doc(3, ['عقد'] + ['حشو'] * 16 + ['بيع']), doc(4, ['بيع']), doc(5, ['اخر'])]
NEAR = settings(proximity_weight=2.0, proximity_window=16)


def test_a_close_pair_earns_the_smaller_idf_of_its_two_terms():
    index = Index.build(PROXIMITY_DOCS)
    plain = dict(index.search(['عقد', 'بيع'], [], BASE, None, 10))

    near = dict(index.search(['عقد', 'بيع'], [], NEAR, None, 10))

    # «عقد» is in 3 of 5 documents and «بيع» in 4, so the pair is worth idf(4, 5); adjacent, distance 1
    assert math.isclose(near[1], plain[1] + 2.0 * idf_of(4, 5) / 1, rel_tol=1e-12)


def test_the_proximity_window_includes_its_last_position():
    index = Index.build(PROXIMITY_DOCS)
    plain = dict(index.search(['عقد', 'بيع'], [], BASE, None, 10))

    near = dict(index.search(['عقد', 'بيع'], [], NEAR, None, 10))

    assert math.isclose(near[2], plain[2] + 2.0 * idf_of(4, 5) / 16, rel_tol=1e-12)   # 16 apart, window 16: counted
    assert near[3] == plain[3]                                                         # 17 apart: not counted


def test_two_query_terms_on_one_token_earn_no_proximity_bonus():
    # «عقد» and «عقده» both reach «عقده». Their closest distance is 0 (position 0), which cancels the pair, although
    # the second «عقده» is 2 positions further on.
    index = Index.build([doc(1, ['عقده', 'حشو', 'عقده']), doc(2, ['حشو'])])
    plain = dict(index.search(['عقد', 'عقده'], [], BASE, None, 10))

    near = dict(index.search(['عقد', 'عقده'], [], NEAR, None, 10))

    assert near == plain


def test_proximity_reaches_prefix_expansions_and_weighs_them_by_their_summed_df():
    # «عقد» reaches itself (df 1) and «عقده» (df 1): summed df 2, against 1 for «بيع»
    index = Index.build([doc(1, ['عقده', 'بيع']), doc(2, ['عقد']), doc(3, ['اخر']), doc(4, ['اخر']), doc(5, ['اخر'])])
    plain = dict(index.search(['عقد', 'بيع'], [], BASE, None, 10))

    near = dict(index.search(['عقد', 'بيع'], [], NEAR, None, 10))

    assert math.isclose(near[1], plain[1] + 2.0 * idf_of(2, 5) / 1, rel_tol=1e-12)


# Multi-word synonym members: body phrases over the words' expansions (engine-5).

PHRASE_DOCS = [doc(1, ['مرور', 'زمان', 'دعوي']), doc(2, ['مرور', 'حشو', 'زمان']), doc(3, ['دعوي']),
               doc(4, ['مرور', 'زمان', 'مرور', 'زمان'])]


def test_a_synonym_phrase_scores_its_count_with_the_summed_idf_of_its_words():
    index = Index.build(PHRASE_DOCS)

    ranked = dict(index.search(['دعوي'], [['مرور', 'زمان']], BASE, None, 10))

    # doc 4 holds the phrase twice and no query term; body lengths 3, 3, 1 and 4 (average 11/4); each word df 3 of 4
    norm = 1.2 * (0.25 + 0.75 * 4 / (11 / 4))
    assert math.isclose(ranked[4], (idf_of(3, 4) + idf_of(3, 4)) * 2.2 * 2 / (2 + norm), rel_tol=1e-12)


def test_a_phrase_needs_its_words_next_to_each_other():
    index = Index.build(PHRASE_DOCS)

    ranked = dict(index.search(['دعوي'], [['مرور', 'زمان']], BASE, None, 10))

    assert set(ranked) == {1, 3, 4}                                     # doc 2 has both words, one apart


def test_a_phrase_expands_to_at_most_64_word_combinations():
    # 65 words start with «عقد», one per document, all of df 1: the 65th in code-point order is cut.
    tails = sorted(a + b for a in 'ابتثج' for b in 'ابتثجحخدذرزسش')
    docs = [doc(i, ['عقد' + tail, 'بيع'], law={64: 'kept', 65: 'cut'}.get(i, 'rest')) for i, tail in enumerate(tails, 1)]
    index = Index.build(docs)

    kept = index.search(['غائب'], [['عقد', 'بيع']], BASE, 'kept', 10)
    cut = index.search(['غائب'], [['عقد', 'بيع']], BASE, 'cut', 10)

    assert (ids(kept), cut) == ([64], [])


def test_the_phrase_cap_keeps_the_most_frequent_combinations(monkeypatch):
    # «عقد» (df 2) is commoner than «عقده» (df 1): with room for one combination, «عقد بيع» is the one kept.
    docs = [doc(1, ['عقده', 'بيع']), doc(2, ['عقد', 'بيع']), doc(3, ['عقد']), doc(4, ['حشو'])]
    monkeypatch.setattr(bm25, 'MAX_PHRASE_COMBINATIONS', 1)

    ranked = Index.build(docs).search(['غائب'], [['عقد', 'بيع']], BASE, None, 10)

    assert ids(ranked) == [2]


# df-drop edges (engine-7; engine.rs:433-437, :457-466): the limit is int(df_drop · N), a term's df is summed over its
# expansions and capped at N, and the first attested minimum is kept.

DF_LIMIT_DOCS = [doc(i, ['سبع', 'ثمان']) for i in range(1, 8)] + [doc(8, ['ثمان']), doc(9, ['اخر']), doc(10, ['نادر'])]
EQUAL_DF_DOCS = [doc(1, ['شائع']), doc(2, ['شائع', 'كثير']), doc(3, ['شائع', 'كثير']), doc(4, ['كثير'])]


def test_df_drop_keeps_a_term_whose_frequency_equals_the_limit():
    index = Index.build(DF_LIMIT_DOCS)

    ranked = index.search(['سبع', 'نادر'], [], settings(df_drop=0.75), None, 20)

    assert sorted(ids(ranked)) == [1, 2, 3, 4, 5, 6, 7, 10]           # «سبع»: df 7, limit int(7.5) = 7, kept


def test_df_drop_truncates_the_limit():
    index = Index.build(DF_LIMIT_DOCS)

    ranked = index.search(['ثمان', 'نادر'], [], settings(df_drop=0.75), None, 20)

    assert ids(ranked) == [10]                                          # «ثمان»: df 8 > int(7.5), dropped


def test_df_drop_counts_a_terms_prefix_expansions():
    index = Index.build([doc(1, ['عقد']), doc(2, ['عقده']), doc(3, ['عقده']), doc(4, ['نادر'])])

    ranked = index.search(['عقد', 'نادر'], [], settings(df_drop=0.5), None, 10)

    assert ids(ranked) == [4]                                           # «عقد»: df 1 + 2 = 3 > int(2.0), dropped


def test_df_drop_caps_a_terms_summed_frequency_at_the_number_of_documents():
    docs = [doc(1, ['عقد', 'عقده']), doc(2, ['عقد', 'عقده']), doc(3, ['عقد', 'عقده', 'نادر'])]

    ranked = Index.build(docs).search(['عقد', 'نادر'], [], settings(df_drop=1.0), None, 10)

    assert sorted(ids(ranked)) == [1, 2, 3]                             # «عقد»: df 3 + 3 capped at 3 = the limit, kept


@pytest.mark.parametrize(('terms', 'expected'), [(['شائع', 'كثير'], [1, 2, 3]), (['كثير', 'شائع'], [2, 3, 4])])
def test_df_drop_keeps_the_first_of_equally_rare_terms(terms, expected):
    index = Index.build(EQUAL_DF_DOCS)

    ranked = index.search(terms, [], settings(df_drop=0.5), None, 10)

    assert sorted(ids(ranked)) == expected                              # both df 3 > int(2.0): the first is kept


def test_df_drop_never_takes_an_absent_term_as_the_rarest():
    index = Index.build(EQUAL_DF_DOCS)

    ranked = index.search(['غائب', 'شائع'], [], settings(df_drop=0.5), None, 10)

    assert sorted(ids(ranked)) == [1, 2, 3]                             # «غائب» has df 0: «شائع» is the rarest, kept


# The synonyms flag and the depth.

SYNONYM_DOCS = [doc(1, ['بيع']), doc(2, ['عقد']), doc(3, ['بيع', 'عقد'])]


def test_a_one_word_synonym_member_scores_as_the_term_would():
    index = Index.build(SYNONYM_DOCS)

    ranked = index.search(['غائب'], [['بيع']], BASE, None, 10)

    assert ranked == index.search(['بيع'], [], BASE, None, 10) and ids(ranked) == [1, 3]


def test_synonyms_off_ignores_the_members():
    index = Index.build(SYNONYM_DOCS)

    ranked = index.search(['غائب'], [['بيع']], settings(synonyms=False), None, 10)

    assert ranked == []


def test_results_stop_at_the_requested_depth():
    index = Index.build(SYNONYM_DOCS)

    ranked = index.search(['بيع'], [], BASE, None, 1)

    assert ids(ranked) == [1]
