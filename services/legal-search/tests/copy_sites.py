"""The shared list of copy-site names, and the scan the output tests run with it.

The list is one file in the content tree, content/corpus/copy-sites.json (the content PR on demo-fixes-2026-11-11 adds
it). Until the mounted content tree (CONTENT_DIR) has it, the tests read tests/fixtures/copy-sites.json, the same
file; test_copy_sites.py fails if the two ever differ."""

import json
import os
import re
from pathlib import Path

FIXTURE = Path(__file__).parent / 'fixtures' / 'copy-sites.json'
# The product's own names: never in the list, and the scan never finds a copy site in them.
PRODUCT_NAMES = ('عقل', 'AQEL', 'aqel', 'اقرأ للمحاماة')
_MARKS = re.compile('[ً-ْٰـ]')  # Arabic diacritics and tatweel


def content_list() -> Path | None:
    """content/corpus/copy-sites.json of the mounted content tree, when it has one."""
    content = os.environ.get('CONTENT_DIR')
    path = Path(content) / 'corpus' / 'copy-sites.json' if content else None
    return path if path is not None and path.is_file() else None


def list_path() -> Path:
    return content_list() or FIXTURE


def names(path: Path | None = None) -> list[str]:
    return json.loads((path or list_path()).read_text(encoding='utf-8'))['names']


def _fold(text: str) -> str:
    return _MARKS.sub('', text).casefold()


def found_in(text: str, listed: list[str]) -> list[str]:
    """The listed names `text` contains, as the list's `match` says: substrings once diacritics and tatweel are removed
    from both, Latin letters in any case."""
    folded = _fold(text)
    return [name for name in listed if _fold(name) in folded]


def without(output: str, *statutory: str) -> str:
    """`output` without each statutory text (an article's, a memorandum note's): each is removed where it first stands
    on lines of its own, between the heading above it and the source line below it. What is left is the headings,
    source lines, labels and notes the scan reads. Fails if a text is not there."""
    for text in statutory:
        at = output.find(f'\n{text}\n')
        assert at >= 0, f'statutory text not on lines of its own in the output: {text[:60]!r}'
        output = output[:at + 1] + output[at + 1 + len(text):]
    return output
