import json

import os
from pathlib import Path
import pytest

from legal_search.corpus import Article
from legal_search.evalset import EvalSetError, corpus_problems, coverage_problems, parse_evalset
from legal_search.evaluate import Sources, check_sources

HEADER = {'set': 'retrieval-v1', 'review': {'status': 'draft'}}
ITEM = {
    'id': 'civil-code-01',
    'question': 'دفعت عربونًا ثم تراجعت عن الشراء، فهل أسترده؟',
    'query': 'العربون التراجع عن البيع استرداد',
    'expected': [{'law': 'civil-code', 'number': 107}],
    'notes': 'القانون-المدني-الأردني/sections/01-المواد-87-205.md',
}


def _text(*items, header=HEADER) -> str:
    lines = (header, *(items or (ITEM,)))
    return '\n'.join(json.dumps(line, ensure_ascii=False) for line in lines) + '\n'


def test_a_valid_set_parses_with_its_review_status():
    evalset = parse_evalset(_text())

    assert evalset.review_status == 'draft'
    assert [(item.id, item.expected[0].key, item.law) for item in evalset.items] == [('civil-code-01', ('civil-code', 107, ''), None)]
    # The fingerprint covers the items, not the header: the lawyer's approval does not force a re-measure.
    approved = {'set': 'retrieval-v1', 'review': {'status': 'approved', 'approved_by': 'x', 'approved_on': '2026-11-02'}}
    assert parse_evalset(_text(header=approved)).sha256 == evalset.sha256
    assert parse_evalset(_text({**ITEM, 'query': 'العربون استرداده'})).sha256 != evalset.sha256


def test_a_header_without_a_review_status_is_rejected():
    with pytest.raises(EvalSetError, match='header: review.status must be "draft" or "approved"'):
        parse_evalset(_text(header={'set': 'retrieval-v1'}))


def test_an_approved_set_without_approver_and_date_is_rejected():
    with pytest.raises(EvalSetError, match='approved_by') as raised:
        parse_evalset(_text(header={'set': 'retrieval-v1', 'review': {'status': 'approved'}}))

    assert 'approved_on' in str(raised.value)


def test_an_item_whose_law_filter_differs_from_its_expected_law_is_rejected():
    with pytest.raises(EvalSetError, match=r"line 2 \(civil-code-01\): law 'majalla' differs from the expected law 'civil-code'"):
        parse_evalset(_text({**ITEM, 'law': 'majalla'}))


def test_a_query_outside_two_to_eight_content_words_is_rejected():
    # 'العربون في و': a stopword and a one-letter token are not content words, so it has one.
    for query in ('العربون', 'العربون في و', 'العربون العقد البيع الشراء الثمن المبيع التسليم الفسخ الرد'):
        with pytest.raises(EvalSetError, match='content words; use 2 to 8'):
            parse_evalset(_text({**ITEM, 'query': query}))


def _without(key: str) -> dict:
    return {name: value for name, value in ITEM.items() if name != key}


# (the items, the exact problem line parse_evalset must report). One case per rule.
ITEM_RULE_BREAKS = [
    ([{**ITEM, 'id': 'civil-code-1'}],
     'line 2 (civil-code-1): id must be "<law slug>-[<word>-]NN" with the slug of its expected law (civil-code)'),
    ([{**ITEM, 'id': 'majalla-01'}],
     'line 2 (majalla-01): id must be "<law slug>-[<word>-]NN" with the slug of its expected law (civil-code)'),
    ([{**ITEM, 'expected': [{'law': 'civil-code', 'number': 107}, {'law': 'majalla', 'number': 76}]}],
     'line 2 (civil-code-01): every expected article must belong to one law'),
    ([{**ITEM, 'expected': [{'law': 'civil-code', 'number': 107}, {'law': 'civil-code', 'number': 107}]}],
     'line 2 (civil-code-01): an expected article is listed twice'),
    ([{**ITEM, 'expected': [{'law': 'civil-code', 'number': 107}, {'law': 'civil-code', 'number': 108}], 'expected_notes': [74]}],
     'line 2 (civil-code-01): expected_notes need exactly one civil-code expected article'),
    ([ITEM, ITEM], 'duplicate id civil-code-01'),
    ([{**ITEM, 'extra': 1}], "line 2: unknown keys ['extra']"),
    ([_without('notes')], "line 2: missing keys ['notes']"),
]


def test_each_item_rule_break_is_reported_with_its_line():
    missed = []
    for items, expected in ITEM_RULE_BREAKS:
        with pytest.raises(EvalSetError) as raised:
            parse_evalset(_text(*items))
        if expected not in str(raised.value).split('\n'):
            missed.append((expected, str(raised.value)))

    assert missed == []


ART_107 = Article(
    'civil-code', 'القانون المدني الأردني', 107, '',
    'دفع العربون وقت ابرام العقد يفيد ان لكل من المتعاقدين الحق في العدول عنه الا إذا قضى الاتفاق بغير ذلك.',
    'https://example.test', '01-المواد-87-205.md',
)
ARTICLES = {'civil-code': [ART_107], 'majalla': []}
# Article -> the note explaining it (dict(load_memorandum(...).links)): the real note on 107 is 74; note 78 only
# cites the Syrian code's article 107.
EXPLAINING = {107: 74}


def test_an_expected_article_missing_from_the_corpus_is_reported():
    evalset = parse_evalset(_text({**ITEM, 'expected': [{'law': 'civil-code', 'number': 108}]}))

    assert corpus_problems(evalset, ARTICLES, EXPLAINING) == ['civil-code-01: civil-code 108 is not in the corpus']


def test_an_unknown_law_slug_is_reported():
    evalset = parse_evalset(_text({**ITEM, 'id': 'penal-01', 'expected': [{'law': 'penal', 'number': 1}]}))

    assert corpus_problems(evalset, ARTICLES, EXPLAINING) == ["penal-01: unknown law 'penal'"]


def test_a_query_copying_four_content_words_of_the_expected_article_is_reported():
    evalset = parse_evalset(_text({**ITEM, 'query': 'دفع العربون وقت إبرام العقد'}))

    assert corpus_problems(evalset, ARTICLES, EXPLAINING) == ['civil-code-01: query copies «دفع عربون وقت ابرام» from civil-code المادة 107']


def test_expected_notes_must_be_the_note_explaining_the_expected_article():
    citing = parse_evalset(_text({**ITEM, 'expected_notes': [78]}))
    extra = parse_evalset(_text({**ITEM, 'expected_notes': [74, 78]}))
    own = parse_evalset(_text({**ITEM, 'expected_notes': [74]}))

    assert corpus_problems(citing, ARTICLES, EXPLAINING) == [
        'civil-code-01: expected_notes [78] must be [74], the note explaining civil-code 107'
    ]
    # Exactly the explaining note: a superset that contains it is still wrong.
    assert corpus_problems(extra, ARTICLES, EXPLAINING) == [
        'civil-code-01: expected_notes [74, 78] must be [74], the note explaining civil-code 107'
    ]
    assert corpus_problems(own, ARTICLES, EXPLAINING) == []
    assert corpus_problems(own, ARTICLES, {}) == [
        'civil-code-01: civil-code 107 has no explaining memorandum note; drop expected_notes'
    ]


def test_coverage_below_the_minimum_is_reported_per_law():
    laws = ['civil-code', 'civil-procedure', 'criminal-procedure', 'labour', 'majalla', 'penal-code']

    problems = coverage_problems(parse_evalset(_text()), laws)

    # Every minimum of REQ-EVL-002, each pinned: per law (default 2, raised for five laws), memorandum, total.
    assert problems == [
        'coverage: civil-code has 1 items, needs at least 12',
        'coverage: civil-procedure has 0 items, needs at least 5',
        'coverage: criminal-procedure has 0 items, needs at least 5',
        'coverage: labour has 0 items, needs at least 2',
        'coverage: majalla has 0 items, needs at least 5',
        'coverage: penal-code has 0 items, needs at least 6',
        'coverage: 0 memorandum items, needs at least 6',
        'coverage: 1 items, needs at least 75',
    ]


@pytest.mark.skipif(not (os.environ.get('CORPUS_DIR') and os.environ.get('CONTENT_DIR')), reason='real corpus not mounted')
def test_the_real_set_passes_its_checks():
    content = Path(os.environ['CONTENT_DIR'])
    sources = Sources(
        content / 'eval' / 'retrieval-v1.jsonl',
        content / 'corpus' / 'laws.json',
        content / 'corpus' / 'corrections.json',
        Path(os.environ['CORPUS_DIR']),
    )

    evalset, _, problems = check_sources(sources)

    assert problems == []
    assert len(evalset.items) >= 75
