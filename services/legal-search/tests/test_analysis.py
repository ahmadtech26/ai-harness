"""The keyword engine's analysers (recall plan Task 2.1), ported from the bench's engine/src/analyser.rs."""

from legal_search.analysis import GuardLight, Lexicon, Today, analyser_of
from legal_search.normalize import tokens


def test_stopwords_are_analysed_with_the_same_analyser():
    lex = Lexicon.from_texts(['عقد'])
    analyser = GuardLight(lex)

    terms = analyser.query_terms(analyser.tokens('ما هو في من على'), stoplist=True)

    assert terms == []


def test_synonym_groups_are_analysed_with_the_same_analyser():
    from legal_search.synonyms import RAW_GROUPS
    analyser = GuardLight(Lexicon.from_texts([' '.join(m for group in RAW_GROUPS for m in group)]))

    groups = analyser.synonym_groups()

    assert groups == [[analyser.tokens(m) for m in group] for group in RAW_GROUPS]


def test_guard_keeps_a_one_letter_prefix_when_the_rest_is_not_attested():
    lex = Lexicon.from_texts(['وكيل وكيل'])          # «كيل» (3 letters, so long enough to strip) is never attested,

    out = GuardLight(lex).tokens('وكيل')

    assert out == ['وكيل']                            # and «وكيل» ends in no SUFFIXES entry (analyser.rs:37)


def test_guard_strips_a_one_letter_prefix_when_the_rest_is_attested():
    lex = Lexicon.from_texts(['عقد عقد عقد وعقد'])

    out = GuardLight(lex).tokens('وعقد')

    assert out == ['عقد']


def test_protected_words_are_never_stripped():
    lex = Lexicon.from_texts(['دون دون دون بدون'])

    out = GuardLight(lex).tokens('بدون')

    assert out == ['بدون']


def test_guardlight_strips_at_most_one_suffix():
    lex = Lexicon.from_texts(['شركات'])

    out = GuardLight(lex).tokens('الشركات')

    # stem_fixed drops «ال», then strip_one_suffix drops «ات» (analyser.rs:37, :142-151) and stops there.
    assert out == ['شرك']


def test_today_is_the_live_search_analyser():
    # Fails if Today drifts from normalize.tokens, which the Postgres search and the index use today: the BM25
    # engine's default must analyse exactly as the live search does (parity at Task 3.3).
    text = 'وبالشركات والمستأجر، فالعقد للمحكمة: المادة (٢٥) «تعسفياً»'

    out = Today().tokens(text)

    assert out == tokens(text)


def test_query_terms_keep_order_drop_duplicates_and_one_letter_tokens():
    analyser = Today()

    terms = analyser.query_terms(['عقد', 'و', 'عقد', 'بيع', 'في'], stoplist=False)

    assert terms == ['عقد', 'بيع', 'في']


def test_analyser_of_names_the_two_configured_analysers():
    lex = Lexicon.from_texts(['عقد'])

    assert isinstance(analyser_of('today', lex), Today)
    assert isinstance(analyser_of('guardlight', lex), GuardLight)
