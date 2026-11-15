"""The glued-heading strip (owner, 2026-11-14 §7) against the published and the official texts, by checks that do not
use the strip rule (the owner's points 11 and 5):
- the stored text is the text as published (parsed, corrections applied) less exactly the heading `glued` records and
  the whitespace before it, and nothing else;
- no official text of an article the strip changed ends with the words the strip removed from it;
- the stored text of an article the strip changed ends as one of its official texts does: their last ENDING_WORDS
  words, and more while those occur more than once in either text, spelling folded; where none does, ENDING_DIFFERS
  pins the article with why and with the stored text's own ending, words that occur once in it, which the stored text
  must still end with;
- an article the strip changed that has no official text (the Majalla) lost a markdown heading line of its shard.
So a cut of law text taken with a heading fails one of them: a cut larger than `glued` records fails the first; any
other cut, of one word or a whole paragraph, however the official texts spell the words cut, leaves the stored text
without the ending the third asks for, an official text's or its pin's (the fourth, for an article without an official
text). The third can miss a cut only where the stored text held that ending once more, earlier, and the official text
does not: cut back to there, the stored text holds it once and ends with it.

The official texts are the evidence lines of the content tree, docs/verification/evidence/<law>.jsonl, beside content/
in a content checkout ({law_slug, number, suffix, source, text, url, …}). VERIFICATION_EVIDENCE_DIR names the folder
(the test stack mounts it at /verification-evidence), else it is the folder beside CONTENT_DIR
(<CONTENT_DIR>/../docs/verification/evidence). Where the mounted content has verification records
(<CONTENT_DIR>/corpus/verification/<law>.jsonl), a missing folder, or one with no <law>.jsonl, fails the tests that
need it; without records (a server-only branch, whose stack mounts the empty folder Docker makes for a missing source)
they skip, saying why. They never pass on nothing. An official text is a line whose source is gazette or bureau and
whose url is not on qistas.com (Qistas is a helper source, never the Gazette, whether its lines are labelled qistas or,
before the content PR relabelled them, gazette). A line without text is no text. The lines are keyed by the corpus's
article numbers; where the Bureau numbers articles otherwise (RENUMBERED), an article is compared with its own Bureau
text.

The comparisons use the verification's own normalisation, v1, copied below from tools/verification/v1.py of the
content tree (not imported across trees; not the search normalisation), and then ignore punctuation as v1's compare
does when it calls a difference 'formatting' (its PUNCT class, replaced by a space). Trailing punctuation therefore does
not count: the strip only ever removes an ending without punctuation, so an official text that ends with the same words
and then a full stop («… الوفاء.») matches. The match is on whole words («… ابالغاءات» does not end with «الغاءات»).
The ending check also folds the spellings the sources differ in most (FOLD: alef with hamza or madda, the hamza seats
ؤ and ئ, ة and ى), and reads an official text without a full stop written as a zero at its end, nor the title line the
Bureau puts after one (official_text)."""

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

# The ending check compares an official text's last three words with the stored text's, and more while those occur
# more than once in either text (ending_of): civil-code 1058's ¶2 and ¶3 both end «… وامتنع الآخر يجبر على المهاياة»,
# so three words alone would let a cut of ¶3 pass. Cutting the last sentence or line off each official text (9,400 cuts
# that take at least one word) leaves none that still ends as the text does; three words alone let 1.0% through. Fewer
# words would pin fewer articles (55 at two, 70 at three, 90 at four: their official spelling or version differs at the
# end), but a shorter ending is likelier to occur once more in the stored text where the official text lacks it, and a
# cut back to that place would pass.
ENDING_WORDS = 3
FOLD = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ؤ': 'و', 'ئ': 'ي', 'ة': 'ه', 'ى': 'ي'})
# A full stop the source wrote as a zero («… ديناراً 0»), and the closing punctuation that ends a line of text.
ZERO = re.compile(r'(?:^|\s)0\s*$')
CLOSING = '.:؛;،,)»"…!؟?-–—]'
TITLE_WORDS = 6
LIST_MARKER = re.compile(r'^\s*(?:[أ-ي]\s*[.\-–)]|\(?[0-9]+\s*[.\-–)])')

# Where the Bureau numbers an article otherwise than the corpus (customs: law 33/2018 art. 53 added an article 249 and
# renumbered 249-253 as 250-254; the Bureau's consolidated text has no article for the corpus's 250), the number of its
# Bureau article, as the article's record says («numbering: the stored text is closest to the Bureau's article N»). The
# evidence lines are keyed by the corpus's numbers and hold the Bureau's article of that number, so the article's own
# Bureau text is the line keyed N, and the Bureau line keyed 250 is not the corpus's 250's text. Before this, the
# corpus's 253 was compared with the line keyed 253, the Bureau's 253, which is the corpus's 254, and passed only
# because both end «… أحكام هذا القانون».
RENUMBERED = {('customs', 251, ''): 250, ('customs', 252, ''): 251, ('customs', 253, ''): 252}

# The articles the strip changed whose stored text ends as none of their official texts do (folded), each with why and
# with the stored text's own ending (its last words, as few as occur only once in it, at least ENDING_WORDS): the test
# asserts the stored text still ends with it, so a cut of law text from a pinned article fails too. None of them is a
# cut: for each, raw == stored + glued, and no official text holds the words removed (both asserted).
ENDING_DIFFERS = {
    # 'list': the list of the next article's headings the strip leaves (RESIDUE's 'list' in test_glued_headings.py).
    ('commerce', 15, ''): ('list', 'صور الرسائل ج'),
    ('commerce', 140, ''): ('list', 'ليس لامر 3'),
    ('commerce', 228, ''): ('list', 'محل الانشاء د'),
    ('commerce', 229, ''): ('list', 'على مصرف 2'),
    ('commerce', 230, ''): ('list', 'او الحامل 4'),
    ('commerce', 239, ''): ('list', 'تظهير لحامله 4'),
    ('commerce', 245, ''): ('list', 'خارج المملكة 3'),
    ('execution', 107, ''): ('list', 'النفقات التنفيذية ب'),
    ('labour', 30, ''): ('list', 'بالعودة للعمل و'),
    # 'spelling': the same words in other letter forms or spacing, or with a letter missing (ours / the Bureau's).
    ('commerce', 14, ''): ('spelling', 'بالصلح الواقي والافلاس'),  # «والافلاس» / «و الافلاس»
    ('commerce', 210, ''): ('spelling', 'بمقتضى نسخة اخرى'),  # «نسخة اخرى» / «نسخةاخرى»
    ('commerce', 213, ''): ('spelling', 'بمقتضى متنه الاصلي'),  # «بمقتضى» / «بمقضى»
    ('commerce', 222, ''): ('spelling', 'انشا السند المحرر'),  # «انشا» / «انشاء»
    ('commerce', 265, ''): ('spelling', 'المتعلقة بسند السحب'),  # «بسند السحب» / «بسندالسحب»
    ('commerce', 283, ''): ('spelling', 'الطرفين تفيد العكس'),  # «ارادة الطرفين» / «ارادةالطرفين»
    ('companies', 193, ''): ('spelling', 'امام الهيئة العامة'),  # «الهيئة العامة» / «الهيئةالعامة»
    ('customs', 34, ''): ('spelling', 'لما تحده الدائرة'),  # «تحده» / «تحدده»
    ('customs', 39, ''): ('spelling', 'على ذلك المستند'),  # «المستند» / «المستد»
    ('customs', 54, ''): ('spelling', 'البري او الجوي'),  # «او الجوي» / «اوالجوي»
    ('customs', 93, ''): ('spelling', 'الخاصة بالرقابة عليها'),  # «بالرقابة عليها» / «بالرقابةعليها»
    ('maritime-commerce', 91, ''): ('spelling', 'ورده الى ديوانها'),  # «ورده» / «وروده»
    ('maritime-commerce', 130, ''): ('spelling', 'ومسؤوليته تظلان كاملتين'),  # «ومسؤوليته» / «ومسئوليته»
    ('maritime-commerce', 184, ''): ('spelling', 'عدا خطا الواسق'),  # «ما عدا خطا» / «ماعدا خطأ»
    ('maritime-commerce', 261, ''): ('spelling', 'صاحب الشئ المتضرر'),  # «الشئ» / «الشيء»
    ('maritime-commerce', 265, ''): ('spelling', 'بين اصحاب العلاقة'),  # «الخاصة بين» / «الخاصةبين»
    ('maritime-commerce', 340, ''): ('spelling', 'ولا ان يمنعه'),  # «ولا» / «و لا»
    # 'wording': another word or word form, or a word more or less (ours / the Bureau's).
    ('commerce', 72, ''): ('wording', 'فيها عند الاقتضاء'),  # «فيها» / «فيه»
    ('commerce', 163, ''): ('wording', 'تجاه بمقتضى السند'),  # «تجاه» / «تجاهه»
    ('commerce', 167, ''): ('wording', 'تعني خمسة عشرة يوما'),  # «خمسة عشرة» / «خمسة عشر»
    ('commerce', 205, ''): ('wording', 'تبرا بهذا الوفاء'),  # «بهذا الوفاء» / «بهذه الوفاء»
    # «مقام الاحتجاج» / «مقامه الاحتجاج»
    ('commerce', 266, ''): ('wording', 'تقديمه او تقديم الاحتجاج او ما يقوم مقام الاحتجاج'),
    ('commerce', 288, ''): ('wording', 'وتسمى اسنادا مختلطة'),  # «اسنادا» / «اسناد»
    ('companies', 30, ''): ('wording', 'الشريك بعد وفاته'),  # «الشريك» / «الشركة»
    ('companies', 43, ''): ('wording', 'وكانه شريك متضامن'),  # «وكانه» / «كأنه»
    ('companies', 159, ''): ('wording', 'المسؤولية ام لا'),  # «ام لا» / «او لا»
    ('companies', 221, ''): ('wording', 'تاريخ التحويل القائمة'),  # «القائمة» / «قائمة»
    ('companies', 287, ''): ('wording', 'محددة وبصورة خطية'),  # «وبصورة» / «بصورة»
    ('companies', 288, ''): ('wording', 'احكام هذا القانون'),  # «احكام هذا القانون» / «أحكام القانون»
    ('customs', 7, ''): ('wording', 'فيها بقرار المدير'),  # «بقرار المدير» / «بقرار من المدير»
    ('labour', 76, ''): ('wording', 'فيه واجره واجازته'),  # «واجازته» / «وإجازاته»
    ('maritime-commerce', 33, ''): ('wording', 'بمسعى صاحب العلاقة'),  # «بمسعى صاحب» / «بمسعى الفريق صاحب»
    ('maritime-commerce', 153, ''): ('wording', 'ايا كانت الحالة'),  # «ايا» / «اية»
    ('maritime-commerce', 256, ''): ('wording', 'السفينة والحمولة وتفرعاتها'),  # «وتفرعاتها» / «وتفرعاتهما»
    ('maritime-commerce', 270, ''): ('wording', 'عن طريق التحاص'),  # «التحاص» / «التقاص»
    ('maritime-commerce', 288, ''): ('wording', 'الذي تتيحه السفينة'),  # «تتيحه السفينة» / «تتيحه له السفينة»
    ('maritime-commerce', 325, ''): ('wording', 'لم يقع الطارئ'),  # «الطارئ» / «طارئ»
    ('maritime-commerce', 332, ''): ('wording', 'ان يثبتوا الخطر'),  # «الخطر» / «الخطر الحربي»
    ('maritime-commerce', 366, ''): ('wording', 'توقيفها بامر السلطة'),  # «بامر السلطة» / «بامر من السلطة»
    # 'version': the official text ends otherwise: ours has a paragraph more, an amendment's (companies 6, 34, 66 and
    # 279, customs 131, 191, 193 and 244, sales-tax 2), or another last sentence (the rest).
    ('companies', 6, ''): ('version', 'المعاملات الالكترونية النافذ'),
    ('companies', 13, ''): ('version', 'الموقع الالكتروني للدائرة'),
    ('companies', 34, ''): ('version', 'بديونهم على الشركة'),
    ('companies', 66, ''): ('version', 'مديري الشركة ذات المسؤولية المحدودة'),
    ('companies', 160, ''): ('version', 'الهيئة لهذه الغاية'),
    ('companies', 279, ''): ('version', 'بكلتا هاتين العقوبتين'),
    ('customs', 32, ''): ('version', 'يصدر لهذه الغاية'),
    ('customs', 128, ''): ('version', 'المحلية الداخلة في صنعها'),
    ('customs', 131, ''): ('version', 'عمل المركز الجمركي'),
    ('customs', 149, ''): ('version', 'يصدر لهذه الغاية'),
    ('customs', 156, ''): ('version', 'يصدر لهذه الغاية'),
    ('customs', 191, ''): ('version', 'علمه بوقوع الحجز'),
    ('customs', 193, ''): ('version', 'من تاريخ صدوره'),
    ('customs', 244, ''): ('version', 'إليهم من التركة'),
    ('labour', 103, ''): ('version', 'تاريخ المصادقة عليه'),
    ('labour', 110, ''): ('version', 'تاريخ المصادقة عليه'),
    ('sales-tax', 2, ''): ('version', 'قرارات معمول بها'),
    # 'merged مكرر': ours goes on with the article's «مكرر» («المادة 21 مكررة» …); the Bureau's and Gazette's do not.
    ('execution', 21, ''): ('merged مكرر', 'الطرف الآخر بذلك'),
    ('execution', 117, ''): ('merged مكرر', 'قبل نفاذ أحكامه'),
    ('sales-tax', 4, ''): ('merged مكرر', 'على تنسيب الوزير'),
    # 'repeal': the Bureau's text is the repeal, «ملغاة بمقتضى نظام معدل رقم 22 لسنة 2017».
    ('evidence', 20, ''): ('repeal', 'في يد المدين'),
    # 'bureau link': the Bureau's text ends with a link to an attachment on lob.gov.jo.
    ('customs', 14, ''): ('bureau link', 'في الجريدة الرسمية'),
}
# court-fees: the Bureau's own text ends with the next article's heading, the schedule's next row title without
# «رسوم» («… خمسون ديناراً 0 الدعاوى المتعلقة بالتحكيم»), on a line after its full stop written as a zero. For each the
# value says whether a Gazette text is there; where it is, it ends as the stored text does, as the Bureau's does up to
# its last zero. 6, 7, 8, 23, 24, 32 and 40 have one; 18, 21 and 22 do not.
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


def split_zero(text: str) -> tuple[str, str]:
    """(the text without a full stop written as a zero at its end, the title line after such a zero, or '')."""
    text = text.translate(DIGITS).rstrip()
    lines = text.split('\n')
    last, title = lines[-1].strip(), ''
    if (len(lines) > 1 and ZERO.search(lines[-2]) and last and last[-1] not in CLOSING and not ZERO.search(last)
            and not LIST_MARKER.match(last) and len(last.split()) <= TITLE_WORDS):
        text, title = '\n'.join(lines[:-1]).rstrip(), last
    return ZERO.sub('', text).rstrip(), title


def official_text(text: str) -> str:
    return split_zero(text)[0]


def occurrences(sequence: list[str], part: list[str]) -> int:
    return sum(1 for i in range(len(sequence) - len(part) + 1) if sequence[i:i + len(part)] == part)


def ending_of(text: list[str], other: list[str]) -> list[str]:
    """`text`'s last ENDING_WORDS words, and more while they occur more than once in it or in `other`."""
    n = min(ENDING_WORDS, len(text))
    while n < len(text) and (occurrences(text, text[-n:]) > 1 or occurrences(other, text[-n:]) > 1):
        n += 1
    return text[-n:]


def ends_as(stored: str, official: str) -> bool:
    """Whether `stored` ends as the official text does (official_text, folded), on ending_of's words."""
    theirs, ours = folded(official_text(official)), folded(stored)
    ending = ending_of(theirs, ours)
    return bool(ending) and ours[-len(ending):] == ending


def own_ending(stored: str) -> list[str]:
    """The stored text's last ENDING_WORDS words, and more while they occur more than once in it: what a pin keeps."""
    return ending_of(words(stored).split(), [])


def official(line: dict) -> bool:
    host = urlparse(line.get('url') or '').hostname or ''
    on_qistas = host == 'qistas.com' or host.endswith('.qistas.com')
    return line.get('source') in OFFICIAL and not on_qistas and bool(line.get('text'))


def own_lines(lines: dict, key: tuple) -> list[dict]:
    """The official lines of `key`'s own text: its Gazette lines, and its Bureau line, which RENUMBERED moves."""
    taken = {(law, number, suffix) for (law, _, suffix), number in RENUMBERED.items()}
    bureau = (key[0], RENUMBERED[key], key[2]) if key in RENUMBERED else key
    found = [line for line in lines.get(key, []) if line['source'] != 'bureau']
    if key in RENUMBERED or bureau not in taken:
        found += [line for line in lines.get(bureau, []) if line['source'] == 'bureau']
    return [line for line in found if official(line)]


def evidence_dir() -> Path | None:
    named = os.environ.get(EVIDENCE_DIR)
    if named:
        return Path(named)
    content = os.environ.get('CONTENT_DIR')
    beside = Path(content).parent / 'docs' / 'verification' / 'evidence' if content else None
    return beside if beside is not None and beside.is_dir() else None


def records() -> list[Path]:
    """The mounted content's verification records, <CONTENT_DIR>/corpus/verification/<law>.jsonl, those not empty."""
    folder = Path(os.environ['CONTENT_DIR']) / 'corpus' / 'verification'
    return sorted(path for path in folder.glob('*.jsonl') if path.stat().st_size) if folder.is_dir() else []


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


def test_the_ending_check_takes_more_words_where_the_last_three_repeat():
    # civil-code 1058's shape: ¶2 and ¶3 end with the same three words, so ¶3 cut leaves that ending in place.
    whole = '1. يجبر على المهاياة.\n\n2. وإذا امتنع الآخر يجبر على المهاياة.\n\n3. وإذا امتنع الأخير يجبر على المهاياة.'
    cut = whole[: whole.rindex('\n\n')]

    assert ending_of(folded(whole), []) == ['الاخير', 'يجبر', 'علي', 'المهاياه']
    assert ends_as(whole, whole) and not ends_as(cut, whole)
    assert own_ending(cut) == ['الآخر', 'يجبر', 'على', 'المهاياة']    # a pin takes as many words as are unique


def test_an_official_text_is_read_without_its_zero_full_stop_and_the_title_after_it():
    assert split_zero('رسم مقداره خمسون ديناراً 0\nالدعاوى المتعلقة بالتحكيم') == ('رسم مقداره خمسون ديناراً',
                                                                              'الدعاوى المتعلقة بالتحكيم')
    assert split_zero('الموازنة العامة للدولة ٠') == ('الموازنة العامة للدولة', '')
    # A line of law text after the zero stays (landlords-tenants 2: a definition, with its full stop).
    assert split_zero('السابقة له 0\nالعرصة: الارض الخالية من البناء.')[1] == ''
    assert split_zero('أ- في الدعوى 0\nب- في طلب إعادة المحاكمة 0') == ('أ- في الدعوى 0\nب- في طلب إعادة المحاكمة', '')


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


def _no_evidence(reason: str) -> None:
    """Fail where the mounted content has verification records (the evidence belongs with them), else skip."""
    found = records()
    if found:
        pytest.fail(f'{reason}; the mounted content has verification records ({len(found)} files in '
                    f'{found[0].parent}), so the official checks must run: mount docs/verification/evidence or set '
                    f'{EVIDENCE_DIR}', pytrace=False)
    pytest.skip(f'{reason}, and the mounted content has no verification records (a checkout without the content tree, '
                "whose stack mounts the empty folder Docker makes for a missing source)")


@pytest.fixture(scope='module')
def stripped(corpus):
    """The stripped articles, each (key, the words removed, the article as stored), the laws, every evidence line of
    each article, and the evidence folder."""
    folder = evidence_dir()
    if folder is None:
        _no_evidence(f'no verification evidence folder: set {EVIDENCE_DIR}, or mount the content checkout so that '
                     'docs/verification/evidence is beside CONTENT_DIR')
    elif not folder.is_dir():
        _no_evidence(f'{EVIDENCE_DIR} names no folder: {folder}')
    elif not any(folder.glob('*.jsonl')):
        _no_evidence(f'the verification evidence folder holds no <law>.jsonl: {folder}')
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


def test_the_bureau_numbers_are_the_records(corpus):
    """RENUMBERED is what the records say: every record whose notes find the stored text closest to another Bureau
    article, and that article."""
    found = records()
    if not found:
        pytest.skip('the mounted content has no verification records')
    noted = {}
    for path in found:
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                row = json.loads(line)
                closest = re.search(r"closest to the Bureau's article (\d+)", row.get('notes') or '')
                if closest:
                    noted[(row['law_slug'], row['number'], row['suffix'])] = int(closest[1])

    assert noted == RENUMBERED


def test_no_official_text_ends_with_the_words_the_strip_removed(stripped, capsys):
    articles, _, lines, folder = stripped
    covered = {key: own_lines(lines, key) for key, _, _ in articles}
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
    """Each article the strip changed ends as one of its official texts does (ends_as), or as its pin says: a cut of law
    text would leave the stored text short of that ending, however the official texts spell the words cut, and whether
    or not the cut went with a heading."""
    articles, _, lines, _ = stripped
    differs = {key for key, _, article in articles if (texts := [line['text'] for line in own_lines(lines, key)])
               and not any(ends_as(article.text, text) for text in texts)}
    # A pinned article must still end as pinned: its own ending, words that occur once in it.
    moved = sorted(key for key, _, article in articles
                   if key in ENDING_DIFFERS and own_ending(article.text) != ENDING_DIFFERS[key][1].split())
    with capsys.disabled():
        groups = Counter(ENDING_DIFFERS[key][0] if key in ENDING_DIFFERS else 'NOT PINNED' for key in differs)
        print(f'\nstripped articles ending as none of their official texts do: {len(differs)} '
              f'({", ".join(f"{group} {n}" for group, n in sorted(groups.items()))})')

    assert sorted(differs - set(ENDING_DIFFERS)) == []     # a new one: law text may have been cut
    assert sorted(set(ENDING_DIFFERS) - differs) == []     # a pin whose article now ends as an official text does
    assert moved == []                                      # a pinned article no longer ends as pinned: a cut?
    assert {key for key, (why, _) in ENDING_DIFFERS.items() if why == 'list'} == \
        {key for key, kind in RESIDUE.items() if kind == 'list'}
    # Nor does any official text of a pinned article hold the words removed from it, anywhere.
    removed = {key: ' '.join(folded(tail)) for key, tail, _ in articles}
    assert sorted(key for key in ENDING_DIFFERS for line in own_lines(lines, key)
                  if removed[key] in ' '.join(folded(line['text']))) == []


def test_the_bureau_glues_the_next_court_fees_heading_where_the_gazette_does_not(stripped):
    articles, _, lines, _ = stripped
    removed = {key: tail for key, tail, _ in articles}
    stored = {key: article.text for key, _, article in articles}
    for key, with_gazette in BUREAU_GLUES.items():
        by_source = {line['source']: line['text'] for line in own_lines(lines, key)}
        title = folded(split_zero(by_source['bureau'])[1])
        assert title and folded(removed[key])[-len(title):] == title, key   # the next heading the strip removed
        assert ends_as(stored[key], by_source['bureau']), key                # the rest ends as the stored text does
        assert ('gazette' in by_source) == with_gazette, key
        if with_gazette:
            assert ends_as(stored[key], by_source['gazette']), key


def test_a_stripped_article_without_an_official_text_lost_a_heading_line_of_its_shard(stripped, capsys):
    articles, laws, lines, _ = stripped
    folders = {law.slug: law.folder for law in laws}
    unchecked = [(key, removed, article) for key, removed, article in articles if not own_lines(lines, key)]
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
