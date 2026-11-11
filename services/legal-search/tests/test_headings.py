"""Heading extraction for the keyword engine's heading field (recall plan Task 2.3), ported from the bench's
py/extract.py (`build(copy=True)`)."""

from legal_search.corpus import Article
from legal_search.headings import extract


def article(law, number, text):
    return Article(law, f'قانون {law}', number, '', text, 'source', 'shard')


# Two of three articles end in a sentence that is the next article's heading: the law bleeds (rate 2/3 >= 0.30).
BLEEDING = [
    article('labour', 1, 'يلتزم العامل بأداء العمل. الفصل التعسفي'),
    article('labour', 2, 'إذا فصل العامل دون سبب جاز له المطالبة بالتعويض. مكافأة نهاية الخدمة'),
    article('labour', 3, 'يستحق العامل المكافأة عن مدة خدمته.'),
]
# One of four ends in such a sentence (rate 1/4 < 0.30): no sentence tail moves in this law.
STEADY = [
    article('civil-code', 1, 'العقد شريعة المتعاقدين. أحكام عامة'),
    article('civil-code', 2, 'يلتزم البائع بتسليم المبيع.'),
    article('civil-code', 3, 'يلتزم المشتري بدفع الثمن.'),
    article('civil-code', 4, 'ينعقد البيع بالإيجاب والقبول.'),
]


def test_a_trailing_heading_moves_to_the_next_article_in_a_bleed_law():
    headings = extract(BLEEDING)

    assert headings[('labour', 2, '')] == 'الفصل التعسفي'
    assert headings[('labour', 3, '')] == 'مكافأة نهاية الخدمة'
    assert headings[('labour', 1, '')] == ''


def test_a_law_under_the_bleed_rate_moves_no_trailing_heading():
    headings = extract(STEADY)

    assert headings[('civil-code', 2, '')] == ''


def test_leading_unpunctuated_paragraphs_are_the_articles_own_heading():
    own = [article('evidence', 1, 'الإثبات بالكتابة\n\nالسند الرسمي هو الذي ينظمه موظف عام.')]

    headings = extract(own)

    assert headings[('evidence', 1, '')] == 'الإثبات بالكتابة'


def test_a_trailing_paragraph_heading_moves_in_any_law():
    # A short unpunctuated last paragraph after a sentence end is a heading wherever the law (extract.py tail_paragraph).
    articles = STEADY[:1] + [article('civil-code', 2, 'يلتزم البائع بتسليم المبيع.\n\nضمان العيوب')] + STEADY[2:]

    headings = extract(articles)

    assert headings[('civil-code', 3, '')] == 'ضمان العيوب'


def test_the_body_text_is_never_changed():
    before = [a.text for a in BLEEDING + STEADY]

    extract(BLEEDING + STEADY)

    assert [a.text for a in BLEEDING + STEADY] == before
