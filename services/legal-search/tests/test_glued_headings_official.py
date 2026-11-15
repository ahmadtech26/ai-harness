"""The glued-heading strip (owner, 2026-11-14 §7) against the published and the official texts, by checks that do not
use the strip rule (the owner's points 11 and 5):
- the stored text is the text as published (parsed, corrections applied) less exactly the heading `glued` records and
  the whitespace before it, and nothing else;
- no official text of an article the strip changed ends with the words the strip removed from it;
- the stored text of an article the strip changed ends with the last ENDING_WORDS words of one of its official texts,
  spelling folded (ENDING_DIFFERS pins the articles where none does, each with why);
- an article the strip changed that has no official text (the Majalla) lost a markdown heading line of its shard.
A cut of law text breaks one of them: a cut larger than `glued` records breaks the first; a heading that takes the
law's last line with it, or law text the official texts spell otherwise, breaks the third.

The official texts are the evidence lines of the content tree, docs/verification/evidence/<law>.jsonl, beside content/
in a content checkout ({law_slug, number, suffix, source, text, url, …}). VERIFICATION_EVIDENCE_DIR names the folder
(the test stack mounts it at /verification-evidence), else it is the folder beside CONTENT_DIR
(<CONTENT_DIR>/../docs/verification/evidence). The tests that need it skip, saying why, when there is no such folder or
it holds no <law>.jsonl: a checkout without the content tree (a server-only branch) has none, and Docker mounts an
empty folder for a missing source; they never pass on nothing. An official text is a line whose source is gazette or
bureau and whose url is not on qistas.com (Qistas is a helper source, never the Gazette, whether its lines are labelled
qistas or, before the content PR relabelled them, gazette). A line without text is no text.

The comparisons use the verification's own normalisation, v1, copied below from tools/verification/v1.py of the
content tree (not imported across trees; not the search normalisation), and then ignore punctuation as v1's compare
does when it calls a difference 'formatting' (its PUNCT class, replaced by a space). Trailing punctuation therefore does
not count: the strip only ever removes an ending without punctuation, so an official text that ends with the same words
and then a full stop («… الوفاء.») matches. The match is on whole words («… ابالغاءات» does not end with «الغاءات»).
The ending check also folds the spellings the sources differ in most (FOLD: alef with hamza or madda, the hamza seats
ؤ and ئ, ة and ى)."""

import json
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import pytest

from legal_search.corpus import parse_law
from legal_search.corrections import apply_corrections, load_corrections
from legal_search.ingest import prepare
from legal_search.registry import load_registry
from tests.test_glued_headings import RESIDUE

# --- v1, copied from the content tree's tools/verification/v1.py (owner's decision, 2026-11-14): Unicode NFC; tatweel
# and diacritics removed; Arabic-Indic and Extended Arabic-Indic digits to ASCII; whitespace and line breaks collapsed.
# The character classes are the file's, character for character.
TATWEEL = 'ـ'
DIACRITICS = re.compile('[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۨ-ۭ]')
DIGITS = ({ord(c): str(i) for i, c in enumerate('٠١٢٣٤٥٦٧٨٩')}
          | {ord(c): str(i) for i, c in enumerate('۰۱۲۳۴۵۶۷۸۹')})
SPACE = re.compile(r'\s+')
# punctuation for the formatting test only (never removed by v1 itself)
PUNCT = re.compile(r'[\.,،؛;:\-–—_\(\)\[\]\{\}«»"\'!?؟…/\\*]')


def v1(text: str) -> str:
    text = unicodedata.normalize('NFC', text)
    text = text.replace(TATWEEL, '')
    text = DIACRITICS.sub('', text)
    text = text.translate(DIGITS)
    return SPACE.sub(' ', text).strip()


def _no_punct(text: str) -> str:
    return SPACE.sub(' ', PUNCT.sub(' ', text)).strip()
# --- end of the copy.


OFFICIAL = ('gazette', 'bureau')
EVIDENCE_DIR = 'VERIFICATION_EVIDENCE_DIR'
# The articles whose official text ends with the words the strip removed while the stored text, after the strip, still
# ends with them: the official ending is kept, and the copy taken off is the next article's heading. commerce 203 ends
# «… الذي يصبح فيه تقديم الاحتجاج لعدم الوفاء.» in the Bureau's text and «… يصح فيه تقديم الاحتجاج لعدم الوفاء.» in
# the stored one; «تقديم الاحتجاج لعدم الوفاء» after it is 204's heading.
ENDING_KEPT = frozenset({('commerce', 203, '')})
ARTICLE_LINE = re.compile(r'^###\s+المادة\s+(?P<number>[0-9٠-٩]+)\s*(?P<suffix>مكرر(?:\s+[^\s—–-]\S*)?)?')

# The ending check compares the last three words of each official text with the stored text's. Any cut of law text
# changes the stored text's last word, so one word would do but for coincidences: cutting the last sentence or line off
# each official text leaves one that still ends with its own last 1, 2, 3 or 4 words in 2.5%, 1.5%, 1.0% and 0.7% of the
# 9,400 cases. Three words keep that near 1% while each word more pins about 20 articles more whose official spelling or
# version differs (62, 77 and 98 articles at 2, 3 and 4 words).
ENDING_WORDS = 3
FOLD = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ؤ': 'و', 'ئ': 'ي', 'ة': 'ه', 'ى': 'ي'})

# The articles the strip changed whose stored text ends with none of their official texts' last ENDING_WORDS words
# (folded), each with why. None of them is a cut: for each, the stored text is the published text less its glued
# heading (raw == stored + glued), and no official text holds the removed words anywhere.
ENDING_DIFFERS = {
    # 'list': the list of the next article's headings the strip leaves (RESIDUE in test_glued_headings.py).
    **dict.fromkeys([('commerce', n, '') for n in (15, 140, 228, 229, 230, 239, 245)]
                    + [('execution', 107, ''), ('labour', 30, '')], 'list'),
    # 'bureau glues': the Bureau's own text ends with the next article's heading (the schedule's next row, without
    # «رسوم»), and there is no Gazette text: 18 «الأحكام البدائية», 21 «الاستئنافات الحقوقية», 22 «تمييز الأحكام
    # الحقوقية». See BUREAU_GLUES.
    **dict.fromkeys([('court-fees', n, '') for n in (18, 21, 22)], 'bureau glues'),
    # 'zero': the official text ends with its full stop written as a zero («… العامة 0»): court-fees 28 (Bureau),
    # income-tax 76 (Bureau and Gazette), landlords-tenants 5 (Bureau).
    **dict.fromkeys([('court-fees', 28, ''), ('income-tax', 76, ''), ('landlords-tenants', 5, '')], 'zero'),
    # 'spelling': the same ending, spelled, spaced or worded slightly otherwise (ours / the Bureau's).
    ('commerce', 14, ''): 'spelling',             # «والافلاس» / «و الافلاس»
    ('commerce', 72, ''): 'spelling',             # «يطعنا فيها» / «يطعنا فيه»
    ('commerce', 163, ''): 'spelling',            # «والملتزمين تجاه» / «تجاهه»
    ('commerce', 167, ''): 'spelling',            # «خمسة عشرة يوما» / «خمسة عشر»
    ('commerce', 205, ''): 'spelling',            # «بهذا الوفاء» / «بهذه الوفاء»
    ('commerce', 210, ''): 'spelling',            # «نسخة اخرى» / «نسخةاخرى»
    ('commerce', 213, ''): 'spelling',            # «بمقتضى» / «بمقضى»
    ('commerce', 222, ''): 'spelling',            # «من انشا» / «من انشاء»
    ('commerce', 265, ''): 'spelling',            # «بسند السحب» / «بسندالسحب»
    ('commerce', 266, ''): 'spelling',            # «مقام الاحتجاج» / «مقامه الاحتجاج»
    ('commerce', 283, ''): 'spelling',            # «ارادة الطرفين» / «ارادةالطرفين»
    ('commerce', 288, ''): 'spelling',            # «اسنادا مختلطة» / «اسناد مختلطة»
    ('companies', 30, ''): 'spelling',            # «على الشريك» / «على الشركة»
    ('companies', 43, ''): 'spelling',            # «وكانه» / «كأنه»
    ('companies', 159, ''): 'spelling',           # «ام لا» / «او لا»
    ('companies', 193, ''): 'spelling',           # «الهيئة العامة» / «الهيئةالعامة»
    ('companies', 221, ''): 'spelling',           # «التحويل القائمة» / «التحويل قائمة»
    ('companies', 287, ''): 'spelling',           # «وبصورة خطية» / «بصورة خطية»
    ('companies', 288, ''): 'spelling',           # «احكام هذا القانون» / «أحكام القانون»
    ('customs', 7, ''): 'spelling',               # «بقرار المدير» / «بقرار من المدير»
    ('customs', 34, ''): 'spelling',              # «تحده» / «تحدده»
    ('customs', 39, ''): 'spelling',              # «المستند» / «المستد»
    ('customs', 54, ''): 'spelling',              # «او الجوي» / «اوالجوي»
    ('customs', 93, ''): 'spelling',              # «بالرقابة عليها» / «بالرقابةعليها»
    ('labour', 76, ''): 'spelling',               # «واجازته» / «وإجازاته»
    ('maritime-commerce', 33, ''): 'spelling',    # «بمسعى صاحب» / «بمسعى الفريق صاحب»
    ('maritime-commerce', 91, ''): 'spelling',    # «ورده» / «وروده»
    ('maritime-commerce', 130, ''): 'spelling',   # «ومسؤوليته» / «ومسئوليته»
    ('maritime-commerce', 153, ''): 'spelling',   # «ايا كانت» / «اية كانت»
    ('maritime-commerce', 184, ''): 'spelling',   # «ما عدا» / «ماعدا»
    ('maritime-commerce', 256, ''): 'spelling',   # «وتفرعاتها» / «وتفرعاتهما»
    ('maritime-commerce', 261, ''): 'spelling',   # «الشئ» / «الشيء»
    ('maritime-commerce', 265, ''): 'spelling',   # «الخاصة بين» / «الخاصةبين»
    ('maritime-commerce', 270, ''): 'spelling',   # «التحاص» / «التقاص»
    ('maritime-commerce', 288, ''): 'spelling',   # «تتيحه السفينة» / «تتيحه له السفينة»
    ('maritime-commerce', 325, ''): 'spelling',   # «الطارئ» / «طارئ»
    ('maritime-commerce', 332, ''): 'spelling',   # «الخطر» / «الخطر الحربي» (not in ours before the strip either)
    ('maritime-commerce', 340, ''): 'spelling',   # «ولا» / «و لا»
    ('maritime-commerce', 366, ''): 'spelling',   # «بامر السلطة» / «بامر من السلطة»
    # 'version': the official text ends otherwise: another wording of the last sentence, a paragraph more or less, or
    # the Bureau's own addition (customs 14: a link to an attachment; evidence 20: «ملغاة بمقتضى نظام معدل رقم 22 لسنة
    # 2017»). execution 21 and 117 and sales-tax 4: the Gazette's text too.
    **dict.fromkeys([('companies', n, '') for n in (6, 13, 34, 66, 160, 279)]
                    + [('customs', n, '') for n in (14, 32, 128, 131, 149, 156, 191, 193, 244, 252)]
                    + [('evidence', 20, ''), ('execution', 21, ''), ('execution', 117, ''), ('labour', 103, ''),
                       ('labour', 110, ''), ('sales-tax', 2, ''), ('sales-tax', 4, '')], 'version'),
}
# court-fees: the Bureau's own text ends with the next article's heading, the schedule's next row title without
# «رسوم» («… خمسون ديناراً 0 الدعاوى المتعلقة بالتحكيم»), after its full stop written as a zero. For each the value
# says whether a Gazette text is there; where it is, it ends as the stored text does. 6, 7, 8, 23, 24, 32 and 40 have
# one; 18, 21 and 22 do not (ENDING_DIFFERS).
BUREAU_GLUES = {('court-fees', n, ''): n not in (18, 21, 22) for n in (6, 7, 8, 18, 21, 22, 23, 24, 32, 40)}


def words(text: str) -> str:
    """The text as the check compares it: v1, then without punctuation."""
    return _no_punct(v1(text))


def ends_with(text: str, ending: str) -> bool:
    """Whether `text` ends with the words of `ending`, punctuation ignored, on a word boundary."""
    text, ending = words(text), words(ending)
    return bool(ending) and (text == ending or text.endswith(' ' + ending))


def folded(text: str) -> list[str]:
    return words(text).translate(FOLD).split()


def ends_as(stored: str, official_text: str) -> bool:
    """Whether `stored` ends with the last ENDING_WORDS words of `official_text`, folded."""
    last = folded(official_text)[-ENDING_WORDS:]
    return bool(last) and folded(stored)[-len(last):] == last


def official(line: dict) -> bool:
    host = urlparse(line.get('url') or '').hostname or ''
    on_qistas = host == 'qistas.com' or host.endswith('.qistas.com')
    return line.get('source') in OFFICIAL and not on_qistas and bool(line.get('text'))


def evidence_dir() -> Path | None:
    named = os.environ.get(EVIDENCE_DIR)
    if named:
        return Path(named)
    content = os.environ.get('CONTENT_DIR')
    beside = Path(content).parent / 'docs' / 'verification' / 'evidence' if content else None
    return beside if beside is not None and beside.is_dir() else None


def test_v1_is_the_verification_normalisation():
    # The self-test of tools/verification/v1.py, for the copy.
    assert v1('أ-  يحقــ للعامل ٣ ۴') == 'أ- يحق للعامل 3 4'
    assert v1('تُشكل') == 'تشكل'
    assert v1('نص  النص\n') == 'نص النص'


def test_an_ending_matches_on_whole_words_with_punctuation_ignored():
    assert ends_with('ويجب ان يقع الوفاء في الميعاد.', 'الميعاد')                  # a full stop after the words
    assert ends_with('الفصل الرابع - في سقوط الأحكام', 'الفصل الرابع- في سقوط الأحكام')  # spacing around a dash
    assert ends_with('تَطبيق عقوبة أشد', 'تطبيق عقوبة أشد')                          # diacritics
    assert not ends_with('تنشر في الجريدة الرسمية ابالغاءات', 'الغاءات')              # part of a word


def test_the_ending_check_folds_spelling_and_compares_the_last_words_only():
    assert ends_as('ويخضع للقواعد العامة المبينة أعلاه.', 'تخضع للقواعد العامه المبينه اعلاه')  # ة/ه, أ/ا, full stop
    assert ends_as('كما جرى عليه العمل', 'وذلك كما جري عليه العمل.')                      # ى/ي; the last three words
    assert not ends_as('يعاقب بالحبس مدة لا تزيد على سنة.', 'يعاقب بالحبس مدة لا تزيد على سنة أو بالغرامة.')


@pytest.fixture(scope='module')
def corpus():
    """ingest.prepare's result and each law's articles as published: parsed and corrected, before the strip."""
    if not (os.environ.get('CORPUS_DIR') and os.environ.get('CONTENT_DIR')):
        pytest.skip('real corpus not mounted')
    corpus_files = Path(os.environ['CONTENT_DIR']) / 'corpus'
    laws, corrections = load_registry(corpus_files / 'laws.json'), load_corrections(corpus_files / 'corrections.json')
    folder = Path(os.environ['CORPUS_DIR'])
    published = {law.slug: apply_corrections(parse_law(folder / law.folder, law.slug),
                                             [c for c in corrections if c.law == law.slug]) for law in laws}
    return prepare(laws, corrections, folder), published


@pytest.fixture(scope='module')
def stripped(corpus):
    """The stripped articles, each (key, the words removed, the article as stored), the laws, every evidence line of
    each article, and the evidence folder."""
    folder = evidence_dir()
    if folder is None:
        pytest.skip(f'no verification evidence folder: set {EVIDENCE_DIR}, or mount the content checkout so that '
                    'docs/verification/evidence is beside CONTENT_DIR')
    if not folder.is_dir():
        pytest.skip(f'{EVIDENCE_DIR} names no folder: {folder}')
    if not any(folder.glob('*.jsonl')):
        pytest.skip(f'the verification evidence folder holds no <law>.jsonl: {folder} (a checkout without the content '
                    "tree's docs/verification/evidence; Docker mounts an empty folder for a missing source)")
    prepared, _ = corpus
    stored = {(slug, a.number, a.suffix): a for slug, articles in prepared.articles.items() for a in articles}
    lines: dict = {}
    for path in sorted(folder.glob('*.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                row = json.loads(line)
                lines.setdefault((row['law_slug'], row['number'], row['suffix']), []).append(row)
    articles = [(key, removed, stored[key]) for key, removed in sorted(prepared.glued.items())]
    return articles, prepared.laws, lines, folder


def test_the_stored_text_is_the_published_text_less_exactly_its_glued_heading(corpus):
    """raw == stored + glued: the text as published ends with the glued heading, and without it and the whitespace
    before it is the stored text, character for character; an article with no glued heading is stored as published."""
    prepared, published = corpus
    wrong = []
    for slug, articles in prepared.articles.items():
        for article, raw in zip(articles, published[slug], strict=True):
            key = (slug, article.number, article.suffix)
            assert (raw.number, raw.suffix) == key[1:]
            text, tail = raw.text.strip(), prepared.glued.get(key, '')
            if not text.endswith(tail) or text[:len(text) - len(tail)].rstrip() != article.text:
                wrong.append(key)

    assert wrong == []


def test_no_official_text_ends_with_the_words_the_strip_removed(stripped, capsys):
    articles, _, lines, folder = stripped
    covered = {key: [line for line in lines.get(key, []) if official(line)] for key, _, _ in articles}
    covered = {key: found for key, found in covered.items() if found}
    ending = {key for key, removed, _ in articles
              if any(ends_with(line['text'], removed) for line in covered.get(key, []))}
    # Law text cut: the official text ends with the removed words and the stored text no longer does, or the official
    # text ends with them twice.
    cut = sorted(key for key, removed, article in articles if key in ending
                 and (not ends_with(article.text, removed)
                      or any(ends_with(line['text'], f'{removed} {removed}') for line in covered[key])))
    sources = Counter('+'.join(sorted({line['source'] for line in covered[key]})) for key in covered)
    without = Counter(key[0] for key, _, _ in articles if key not in covered)

    with capsys.disabled():
        print(f'\nglued headings stripped: {len(articles)}; with a Gazette or Bureau text: {len(covered)} '
              f'({", ".join(f"{source} {n}" for source, n in sorted(sources.items()))}); without one: '
              f'{sum(without.values())} ({", ".join(f"{law} {n}" for law, n in sorted(without.items()))}); '
              f'official text ending with the removed words: {len(ending)}, of them law text cut: {len(cut)}')

    assert cut == []
    assert ending == ENDING_KEPT
    # Every stripped article of a law with an evidence file has an official text; the rest are checked in their shards.
    assert sorted(law for law in without if (folder / f'{law}.jsonl').exists()) == []


def test_the_stored_text_ends_as_an_official_text_does(stripped, capsys):
    """Each article the strip changed ends with the last ENDING_WORDS words of one of its official texts, folded, unless
    ENDING_DIFFERS pins it: a cut of law text would leave the stored text short of that ending, however the official
    texts spell the words cut, and whether or not the cut went with a heading."""
    articles, _, lines, _ = stripped
    differs = set()
    for key, _, article in articles:
        texts = [line['text'] for line in lines.get(key, []) if official(line)]
        if texts and not any(ends_as(article.text, text) for text in texts):
            differs.add(key)
    with capsys.disabled():
        groups = Counter(ENDING_DIFFERS.get(key, 'NOT PINNED') for key in differs)
        print(f'\nstripped articles ending with none of their official texts\' last {ENDING_WORDS} words: '
              f'{len(differs)} ({", ".join(f"{group} {n}" for group, n in sorted(groups.items()))})')

    assert sorted(differs - set(ENDING_DIFFERS)) == []     # a new one: law text may have been cut
    assert sorted(set(ENDING_DIFFERS) - differs) == []     # a pin that no longer differs
    assert {key for key, why in ENDING_DIFFERS.items() if why == 'list'} == \
        {key for key, kind in RESIDUE.items() if kind == 'list'}
    # Nor does any official text of a pinned article hold the words removed from it, anywhere.
    removed = {key: ' '.join(folded(tail)) for key, tail, _ in articles}
    assert sorted(key for key in ENDING_DIFFERS for line in lines.get(key, [])
                  if official(line) and removed[key] in ' '.join(folded(line['text']))) == []


def test_the_bureau_glues_the_next_court_fees_heading_where_the_gazette_does_not(stripped):
    articles, _, lines, _ = stripped
    removed = {key: tail for key, tail, _ in articles}
    stored = {key: article.text for key, _, article in articles}
    for key, with_gazette in BUREAU_GLUES.items():
        by_source = {line['source']: line['text'] for line in lines[key] if official(line)}
        bureau = folded(by_source['bureau'])
        title = bureau[len(bureau) - bureau[::-1].index('0'):]     # after the Bureau's last full stop, written «0»
        assert title and folded(removed[key])[-len(title):] == title, key   # the next heading the strip removed
        assert not ends_as(stored[key], by_source['bureau']), key
        assert ('gazette' in by_source) == with_gazette, key
        if with_gazette:
            assert ends_as(stored[key], by_source['gazette']), key


def test_a_stripped_article_without_an_official_text_lost_a_heading_line_of_its_shard(stripped, capsys):
    articles, laws, lines, _ = stripped
    folders = {law.slug: law.folder for law in laws}
    unchecked = [(key, removed, article) for key, removed, article in articles
                 if not any(official(line) for line in lines.get(key, []))]
    corpus = Path(os.environ['CORPUS_DIR'])
    not_a_heading_line = [key for key, removed, article in unchecked
                          if _last_line(corpus / folders[key[0]] / 'sections' / article.shard, key) != removed
                          or not removed.startswith('#')]
    with capsys.disabled():
        print(f'\nstripped articles without an official text: {len(unchecked)}, each the last line of its block in the '
              f'shard and a markdown heading: {len(unchecked) - len(not_a_heading_line)}')

    assert not_a_heading_line == []


def _last_line(shard: Path, key: tuple) -> str | None:
    """The last line with text (not a «---» separator) between the article's «### المادة» line in the shard and the
    next one: the source's own last line of the article's block."""
    block: list[str] | None = None
    for line in shard.read_text(encoding='utf-8').replace('\r\n', '\n').split('\n'):
        stripped_line = line.strip()
        heading = ARTICLE_LINE.match(stripped_line)
        if heading:
            if block is not None:
                break
            if (key[1], key[2]) == (int(heading['number'].translate(DIGITS)), (heading['suffix'] or '').strip()):
                block = []
        elif block is not None and stripped_line and stripped_line != '---':
            block.append(stripped_line)
    return block[-1] if block else None
