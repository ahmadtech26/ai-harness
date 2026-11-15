"""Glued headings (owner, 2026-11-14 §7): the stored text of an article never ends with a heading that belongs to the
next article. headings.extract finds that heading (it moves it into the next article's heading field); the ingest now
also strips it from the article's text, and the heading field keeps it. What heading text the strip leaves at the end
of an article is pinned (RESIDUE, the owner's point 12); test_glued_headings_official.py checks the strip against the
Gazette and Bureau texts (point 11)."""

import os
import re
from collections import Counter
from pathlib import Path

import pytest

from legal_search.corpus import Article, parse_law
from legal_search.corrections import apply_corrections, load_corrections
from legal_search.headings import PARAGRAPHS, STATUTORY_ENDINGS, bleeds, extract, glued_headings, strip_glued
from legal_search.ingest import prepare
from legal_search.registry import Law, load_registry


def article(law, number, text, suffix=''):
    return Article(law, f'قانون {law}', number, suffix, text, 'source', 'shard')


# A bleed law (2 of 3 articles end in a sentence that is the next article's heading).
BLEEDING = [
    article('labour', 1, 'يلتزم العامل بأداء العمل. الفصل التعسفي'),
    article('labour', 2, 'إذا فصل العامل دون سبب جاز له المطالبة بالتعويض. مكافأة نهاية الخدمة'),
    article('labour', 3, 'يستحق العامل المكافأة عن مدة خدمته.'),
]
# Under the bleed rate (2 of 7 end in a sentence tail, a paragraph tail counting too): a sentence tail is not a heading
# here, a paragraph tail is.
STEADY = [
    article('civil-code', 1, 'العقد شريعة المتعاقدين. أحكام عامة'),
    article('civil-code', 2, 'يلتزم البائع بتسليم المبيع.\n\nضمان العيوب'),
    article('civil-code', 3, 'يلتزم المشتري بدفع الثمن.'),
    article('civil-code', 4, 'ينعقد البيع بالإيجاب والقبول.'),
    article('civil-code', 5, 'يصح البيع بثمن مؤجل.'),
    article('civil-code', 6, 'يجوز اشتراط الخيار.'),
    article('civil-code', 7, 'ينتقل الملك بالعقد.'),
]


def test_the_glued_heading_is_the_one_the_next_article_takes_as_its_heading():
    assert glued_headings(BLEEDING, extract(BLEEDING)) == {
        ('labour', 1, ''): 'الفصل التعسفي',
        ('labour', 2, ''): 'مكافأة نهاية الخدمة',
    }
    # civil-code 1's sentence tail is not taken (the law does not bleed); 2's paragraph tail is.
    assert glued_headings(STEADY, extract(STEADY)) == {('civil-code', 2, ''): 'ضمان العيوب'}


def test_a_heading_that_only_begins_the_next_heading_is_glued_too():
    # The next article has its own leading heading as well: its heading field is «tail + own heading».
    articles = [
        article('penal-code', 51, 'تسقط الأحكام الجزائية بالتقادم.\n\nالفصل الرابع- في سقوط الأحكام الجزائية'),
        article('penal-code', 52, 'أسباب سقوط الأحكام الجزائية\n\nتسقط الأحكام بالوفاة والعفو العام.'),
    ]
    headings = extract(articles)

    assert headings[('penal-code', 52, '')] == 'الفصل الرابع- في سقوط الأحكام الجزائية أسباب سقوط الأحكام الجزائية'
    assert glued_headings(articles, headings) == {('penal-code', 51, ''): 'الفصل الرابع- في سقوط الأحكام الجزائية'}


def test_stripping_removes_exactly_the_heading_and_nothing_else():
    cleaned = strip_glued(BLEEDING, glued_headings(BLEEDING, extract(BLEEDING)))

    assert [a.text for a in cleaned] == [
        'يلتزم العامل بأداء العمل.',
        'إذا فصل العامل دون سبب جاز له المطالبة بالتعويض.',
        'يستحق العامل المكافأة عن مدة خدمته.',
    ]
    assert cleaned[2] is BLEEDING[2]  # an article without a glued heading is the same object
    assert [a.text for a in strip_glued(STEADY, glued_headings(STEADY, extract(STEADY)))][1] == 'يلتزم البائع بتسليم المبيع.'


def test_the_last_article_of_a_law_keeps_its_ending():
    articles = BLEEDING[:2]
    assert ('labour', 2, '') not in glued_headings(articles, extract(articles))


def test_a_listed_statutory_ending_is_never_stripped():
    # civil-code 288 ends with a paragraph of law that lacks its full stop; the Bureau's 288 ends with the same words.
    assert ('civil-code', 288, '') in STATUTORY_ENDINGS
    articles = [
        article('civil-code', 288, 'يكون المتبوع مسؤولا عن فعل تابعه.\n\nولمن أدى الضمان ان يرجع بما دفع، على المحكوم عليه به'),
        article('civil-code', 289, 'الفرع الرابع\n\nصور من المسؤولية\n\nجناية العجماء جبار.'),
    ]

    assert glued_headings(articles, extract(articles)) == {}


def test_prepare_stores_the_text_without_its_glued_heading_and_keeps_the_heading_for_the_index(tmp_path: Path):
    sections = tmp_path / 'corpus' / 'civil' / 'sections'
    sections.mkdir(parents=True)
    (sections / '00.md').write_text(
        '---\nparent_law: x\nsource: example.test\n---\n\n'
        '### المادة 1\n\nنص المادة الأولى من القانون.\n\nالفصل الثاني احكام العقد\n\n---\n\n'
        '### المادة 2\n\nنص المادة الثانية من القانون.\n', encoding='utf-8')
    (tmp_path / 'corpus' / 'law-directory.md').write_text(
        '| القانون | slug | المواد | الأقسام | الحالة | الفئة |\n|---|---|---|---|---|---|\n'
        '| law | `civil` | 2 | 1 | complete | x |\n', encoding='utf-8')

    prepared = prepare([Law(slug='civil-code', title='القانون المدني', folder='civil')], [], tmp_path / 'corpus')

    assert [a.text for a in prepared.articles['civil-code']] == ['نص المادة الأولى من القانون.', 'نص المادة الثانية من القانون.']
    assert prepared.headings['civil-code'] == {('civil-code', 1, ''): '', ('civil-code', 2, ''): 'الفصل الثاني احكام العقد'}
    assert prepared.glued == {('civil-code', 1, ''): 'الفصل الثاني احكام العقد'}


# What is still heading text at the end of an article after the strip (the owner's point 12), pinned so that it
# cannot grow silently. 'stacked': a markdown heading line stacked above the one the strip took (the Majalla, where a
# «## الباب …» line stands over the «## الفصل …» line that is the next article's heading). 'list': the strip took the
# last item of a list of the next article's headings and left the rest of the list, down to that item's marker
# (commerce 15 ends «… دفاتر التجار أ. دفتر يومية ب. دفتر صور الرسائل ج.»; item ج., «دفتر الجرد والميزانية», is 16's
# heading). 'rule': the strip rule run again on the stored text with the law's bleed status before the strip (none).
RESIDUE = {
    **{('majalla', number, ''): 'stacked' for number in (
        196, 236, 261, 299, 360, 432, 462, 496, 521, 581, 595, 620, 633, 658, 679, 721, 728, 772, 803, 836, 860, 911,
        1007, 1113, 1233, 1307, 1328, 1430, 1459, 1547, 1555, 1586, 1683, 1735, 1753, 1791, 1828)},
    **{('commerce', number, ''): 'list' for number in (15, 140, 228, 229, 230, 239, 245)},
    ('execution', 107, ''): 'list',
    ('labour', 30, ''): 'list',
}
LIST_END = re.compile(r'(?:^|\s)(?:[أ-ي]|هـ|[0-9٠-٩]{1,2})\s*[.\-–)]$')  # a list item's marker with nothing after it


@pytest.mark.skipif(not (os.environ.get('CORPUS_DIR') and os.environ.get('CONTENT_DIR')), reason='real corpus not mounted')
def test_the_real_corpus_keeps_no_glued_heading_beyond_the_pinned_residue(capsys):
    """Over the whole library: how many articles ended with the next article's heading before the ingest strips it (and
    how many ended with exactly that heading, the owner's count), and how many still end with heading text after it
    (RESIDUE): by the same rule, with each law's bleed status from before the strip, which the strip itself lowers
    (a status recomputed from the cleaned text would hide what is left); by a stacked «##» heading; by a list of
    headings the strip took the last item of."""
    corpus_files = Path(os.environ['CONTENT_DIR']) / 'corpus'
    laws, corrections = load_registry(corpus_files / 'laws.json'), load_corrections(corpus_files / 'corrections.json')
    corpus = Path(os.environ['CORPUS_DIR'])
    prepared = prepare(laws, corrections, corpus)
    published = {law.slug: apply_corrections(parse_law(corpus / law.folder, law.slug),
                                             [c for c in corrections if c.law == law.slug]) for law in laws}
    raw = {(a.law_slug, a.number, a.suffix): a.text.strip() for articles in published.values() for a in articles}

    before = Counter(key[0] for key in prepared.glued)
    exactly = Counter(key[0] for key, tail in prepared.glued.items()
                      if _ends_with_words(raw[key], prepared.headings[key[0]][_next(prepared, key)]))
    lowered = sorted(slug for slug, articles in prepared.articles.items() if bleeds(published[slug]) != bleeds(articles))
    rule = {key for slug, articles in prepared.articles.items()
            for key in glued_headings(articles, prepared.headings[slug], law_bleeds=bleeds(published[slug]))}
    stacked = {(slug, a.number, a.suffix) for slug, articles in prepared.articles.items() for a in articles
               if PARAGRAPHS.split(a.text.strip())[-1].strip().startswith('#')}
    listed = {key for key, tail in prepared.glued.items()
              if _on_one_line(raw[key], tail) and LIST_END.search(_stored(prepared, key))}
    residue = {**{key: 'rule' for key in rule}, **{key: 'stacked' for key in stacked}, **{key: 'list' for key in listed}}
    after = {kind: Counter(key[0] for key, found in residue.items() if found == kind) for kind in ('rule', 'stacked', 'list')}

    with capsys.disabled():
        print('\nglued headings, before → after the ingest strips them (of which the whole next heading); after: heading '
              'text still at the end (by the rule with the bleed status before the strip, stacked «##» headings, '
              'lists without their last item)')
        for slug in sorted(set(before) | {key[0] for key in residue}, key=lambda s: (-before[s], s)):
            found = [after[kind][slug] for kind in after]
            print(f'  {slug}: {before[slug]} ({exactly[slug]}) → {sum(found)} ({", ".join(map(str, found))})')
        found = [sum(after[kind].values()) for kind in after]
        print(f'  all: {sum(before.values())} ({sum(exactly.values())}) → {sum(found)} ({", ".join(map(str, found))})')
        print(f'  laws whose bleed status the strip lowers: {", ".join(lowered) or "none"}')

    assert sum(before.values()) > 1500
    assert residue == RESIDUE
    assert ('civil-code', 288, '') not in prepared.glued
    assert sum(len(a) for a in prepared.articles.values()) == 6592


def _stored(prepared, key) -> str:
    return next(a.text for a in prepared.articles[key[0]] if (a.number, a.suffix) == key[1:])


def _on_one_line(text: str, tail: str) -> bool:
    """Whether the heading stripped from the end of `text` stood on the same line as the text before it."""
    head = text[: -len(tail)]
    return '\n' not in head[len(head.rstrip()):]


def _next(prepared, key):
    articles = prepared.articles[key[0]]
    index = next(i for i, a in enumerate(articles) if (a.number, a.suffix) == key[1:])
    following = articles[index + 1]
    return (key[0], following.number, following.suffix)


def _ends_with_words(text: str, words: str) -> bool:
    tail = words.split()
    return bool(tail) and text.split()[-len(tail):] == tail
