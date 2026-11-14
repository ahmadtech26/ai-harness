"""Normalisation v1 (owner's decision, 2026-11-14), applied the same way to the stored text, the Gazette text and the
Bureau text: Unicode NFC; tatweel and diacritics removed; digit shapes unified (Arabic-Indic and Extended
Arabic-Indic to ASCII); whitespace and line breaks collapsed. Nothing else: no letter folding (hamza, ة/ه, ى/ي stay),
no prefix stripping, punctuation kept.

compare(stored, other) -> (equal: bool, difference: None | 'formatting' | 'body'): 'formatting' when the two differ
only in punctuation and the spacing around it."""
import re
import unicodedata

TATWEEL = 'ـ'
DIACRITICS = re.compile('[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۨ-ۭ]')
DIGITS = {ord(c): str(i) for i, c in enumerate('٠١٢٣٤٥٦٧٨٩')} | {ord(c): str(i) for i, c in enumerate('۰۱۲۳۴۵۶۷۸۹')}
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


def compare(stored: str, other: str):
    a, b = v1(stored), v1(other)
    if a == b:
        return True, None
    if _no_punct(a) == _no_punct(b):
        return False, 'formatting'
    return False, 'body'


if __name__ == '__main__':
    assert v1('أ-  يحقــ للعامل ٣ ۴') == 'أ- يحق للعامل 3 4'
    assert v1('تُشكل') == 'تشكل'
    assert compare('اذا', 'إذا') == (False, 'body')
    assert compare('التالية:-', 'التالية:') == (False, 'formatting')
    assert compare('نص  النص\n', 'نص النص') == (True, None)
    print('v1 self-test ok')
