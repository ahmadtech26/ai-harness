"""Arabic normalisation shared by ingestion and search, so stored and queried forms always agree.

Folds the spelling variants the corpus mixes (hamza forms of alef, ta marbuta, alef maqsura), drops
diacritics and tatweel, and strips common clitic prefixes (و ف ب ك ل and the article ال) from words.
"""

import re

_DIACRITICS = re.compile('[ً-ْٰـ]')  # harakat, superscript alef, tatweel
_NON_WORD = re.compile(r'[^\w\s]', re.UNICODE)
_FOLD = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ى': 'ي', 'ة': 'ه', 'ؤ': 'و', 'ئ': 'ي'})
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')

# Longest first, so "وال" is tried before "و". A prefix is removed only if a 3-letter stem remains.
_PREFIXES = ('وال', 'بال', 'كال', 'فال', 'لل', 'ال', 'و', 'ف', 'ب', 'ك', 'ل')
_MIN_STEM = 3


def fold(text: str) -> str:
    """Character-level folding: diacritics, letter variants, Arabic-Indic digits."""
    return _DIACRITICS.sub('', text).translate(_FOLD).translate(_DIGITS)


def stem(word: str) -> str:
    for prefix in _PREFIXES:
        if word.startswith(prefix) and len(word) - len(prefix) >= _MIN_STEM:
            return word[len(prefix):]
    return word


def folded_words(text: str) -> list[str]:
    """The words of `text` after folding, before any prefix is stripped (the BM25 analysers stem them their own way)."""
    return _NON_WORD.sub(' ', fold(text)).split()


def tokens(text: str) -> list[str]:
    """Normalised search tokens of `text`."""
    return [stem(word) for word in folded_words(text)]


def normalize(text: str) -> str:
    """Space-joined tokens, as stored for full-text search."""
    return ' '.join(tokens(text))
