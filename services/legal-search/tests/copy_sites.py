"""The copy-site list, and the scan the output tests run with it.

The list is one file, content/corpus/copy-sites.json of the mounted content tree (CONTENT_DIR): the scan reads its
names from there and from nowhere else, and a test that needs it skips while the tree has none (`needs_list`).

The scan finds a listed name as a substring once Arabic diacritics and tatweel are removed from both, Latin letters in
any case: stricter than skill-ci's rule (the list's own note), which also wants no letter or digit joined to the name,
so it finds at least what skill-ci finds. It reads a tool's whole output, statutory text included, for every name but
STATUTORY_TERMS, which it reads outside the statutory text only."""

import json
import os
import re
from pathlib import Path

import pytest

LIST = 'content/corpus/copy-sites.json'
# The product's own names: never in the list, and the scan never finds a copy site in them.
PRODUCT_NAMES = ('عقل', 'AQEL', 'aqel', 'اقرأ للمحاماة')
# The one exception: the site title's «محامي الأردن» is in the law's own words «المحامي الأردني» (bar-association 9
# says «للمحامي الاردني»), so these two are not looked for in an article's or a note's text.
STATUTORY_TERMS = ('محامي الأردن', 'محامي الاردن')
_MARKS = re.compile('[ً-ْٰـ]')  # Arabic diacritics and tatweel


def list_path() -> Path | None:
    """content/corpus/copy-sites.json of the mounted content tree, when it has one."""
    content = os.environ.get('CONTENT_DIR')
    path = Path(content) / 'corpus' / 'copy-sites.json' if content else None
    return path if path is not None and path.is_file() else None


needs_list = pytest.mark.skipif(list_path() is None, reason=f'the mounted content tree (CONTENT_DIR) has no {LIST}')


def names() -> list[str]:
    path = list_path()
    assert path is not None, f'no {LIST} in CONTENT_DIR'
    return json.loads(path.read_text(encoding='utf-8'))['names']


def _fold(text: str) -> str:
    return _MARKS.sub('', text).casefold()


def found_in(text: str, listed: list[str]) -> list[str]:
    """The listed names `text` contains: substrings once diacritics and tatweel are removed from both, Latin letters in
    any case."""
    folded = _fold(text)
    return [name for name in listed if _fold(name) in folded]


def in_statutory_text(listed: list[str]) -> list[str]:
    """The names the scan looks for in statutory text too: every listed name but STATUTORY_TERMS."""
    terms = {_fold(term) for term in STATUTORY_TERMS}
    return [name for name in listed if _fold(name) not in terms]


def without(output: str, *statutory: str) -> str:
    """`output` without each statutory text (an article's, a memorandum note's): each is removed where it first stands
    on lines of its own, between the heading above it and the source line below it. What is left is the headings,
    source lines, labels and notes. Fails if a text is not there."""
    for text in statutory:
        at = output.find(f'\n{text}\n')
        assert at >= 0, f'statutory text not on lines of its own in the output: {text[:60]!r}'
        output = output[:at + 1] + output[at + 1 + len(text):]
    return output


def scan(output: str, statutory: list[str], listed: list[str]) -> list[str]:
    """The listed names a tool's output holds: any name outside its statutory texts (`statutory`, each on lines of its
    own), and any name but STATUTORY_TERMS anywhere, the statutory texts included."""
    hits = set(found_in(without(output, *statutory), listed)) | set(found_in(output, in_statutory_text(listed)))
    return [name for name in listed if name in hits]
