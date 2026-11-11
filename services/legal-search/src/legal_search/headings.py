"""Article headings for the keyword engine's heading field (recall plan Task 2.3), ported from the bench's
.hq/scratch/rag-bench/py/extract.py, `build(copy=True)` (the T-B2 variant «copyhead»). Pure; the text is never changed.

An article's heading is
    the previous article's trailing heading: its last paragraph when that reads as a heading (short, unpunctuated,
    after a paragraph that ended a sentence), or, in a law where at least BLEED_RATE of the articles end that way,
    the words after its last sentence end;
    plus the article's own leading unpunctuated short paragraphs (or the opening words of a structural heading).

    python -m legal_search.headings --registry … --corrections … --corpus … [--compare FILE]
prints the number of articles whose heading differs from FILE's ({law, number, suffix, heading} rows) and the first 20.
Python 3.11 syntax only.
"""

import argparse
import json
import re
from collections.abc import Iterable
from pathlib import Path

from legal_search.corpus import Article

TERMINAL = '.:؛;،,)»"…!؟?-–—ـ]('
MAX_HEADING_WORDS = 12
BLEED_RATE = 0.30
STRUCTURAL = re.compile(r'^(?:#+\s*)?(?:ال)?(?:باب|فصل|فرع|قسم|كتاب|جزء|مبحث|نبذة)\b')
MARKER_START = re.compile(r'^\s*(?:[أ-ي]\s*[.\-–)]|\(?[0-9٠-٩]+\s*[.\-–)])')
MARKER_INSIDE = re.compile(r'\s(?:[أابجدهوزحطيكل]\s*[.\-–]|[0-9٠-٩]{1,2}\s*[.\-–])\s')
# Only the first sentence-end is a boundary: a period glued to the next word («القانون.استيراد») counts too.
LAST_SENTENCE = re.compile(r'^(?P<head>.*[.؛])\s*(?P<tail>[^.؛\n]+)$', re.DOTALL)
PARAGRAPHS = re.compile(r'\n\s*\n')

Key = tuple[str, int, str]


def words(text: str) -> int:
    return len(text.split())


def unpunctuated(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and stripped[-1] not in TERMINAL


def tail_paragraph(text: str) -> str | None:
    """The last paragraph, when it reads as a heading: short, unpunctuated, after a paragraph that ended a sentence."""
    paragraphs = PARAGRAPHS.split(text.strip())
    if len(paragraphs) < 2:
        return None
    last, before = paragraphs[-1].strip(), paragraphs[-2].strip()
    if last.startswith('#'):
        return last
    if words(last) > MAX_HEADING_WORDS or not unpunctuated(last) or MARKER_START.match(last):
        return None
    if before and before[-1] not in '.؛:':
        return None  # a list running on («الكتابة / الشهادة / الإقرار»), not a heading
    return last


def tail_sentence(text: str) -> str | None:
    """The words after the last sentence end, when the article does not end in punctuation («... العمل. الفصل التعسفي»)."""
    stripped = text.strip()
    if not unpunctuated(stripped):
        return None
    match = LAST_SENTENCE.match(stripped)
    if not match:
        return None
    tail = match['tail'].strip()
    if not tail or words(tail) > MAX_HEADING_WORDS or MARKER_START.match(tail):
        return None
    return tail


def head_heading(text: str) -> str:
    """The article's own heading: unpunctuated short first paragraphs, or a structural heading running into the text
    (up to a list marker, else its first MAX_HEADING_WORDS words)."""
    paragraphs = PARAGRAPHS.split(text.strip())
    taken: list[str] = []
    while len(paragraphs) - len(taken) > 1:
        paragraph = paragraphs[len(taken)].strip()
        if words(paragraph) <= MAX_HEADING_WORDS and unpunctuated(paragraph) and not MARKER_START.match(paragraph):
            taken.append(paragraph)
        else:
            break
    if taken:
        return ' '.join(taken)
    if STRUCTURAL.match(text.strip()) and paragraphs:
        first = paragraphs[0].strip()
        marker = MARKER_INSIDE.search(first)
        if marker and words(first[:marker.start()]) <= 25:
            return first[:marker.start()].strip()
        return ' '.join(first.split()[:MAX_HEADING_WORDS])
    return ''


def extract(articles: Iterable[Article]) -> dict[Key, str]:
    """Each article's heading, by (law, number, suffix). `articles` in file order, as ingest.prepare returns them."""
    by_law: dict[str, list[Article]] = {}
    for item in articles:
        by_law.setdefault(item.law_slug, []).append(item)
    headings: dict[Key, str] = {}
    for law_articles in by_law.values():
        bleeds = sum(1 for a in law_articles if tail_sentence(a.text)) / len(law_articles) >= BLEED_RATE
        previous_tail = ''
        for index, item in enumerate(law_articles):
            heading = [previous_tail] if previous_tail else []
            previous_tail = ''
            if index + 1 < len(law_articles):
                previous_tail = tail_paragraph(item.text) or (tail_sentence(item.text) if bleeds else None) or ''
            own = head_heading(item.text)
            if own:
                heading.append(own)
            headings[(item.law_slug, item.number, item.suffix)] = ' '.join(h for h in heading if h)
    return headings


def main() -> None:
    from legal_search.corrections import load_corrections
    from legal_search.ingest import prepare
    from legal_search.registry import load_registry

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--corrections', type=Path, required=True)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    prepared = prepare(load_registry(args.registry), load_corrections(args.corrections), args.corpus)
    headings = extract(a for law_articles in prepared.articles.values() for a in law_articles)
    if args.compare is None:
        print(f'{len(headings)} articles, {sum(1 for h in headings.values() if h)} with a heading')
        return
    expected = {}
    with args.compare.open(encoding='utf-8') as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                expected[(row['law'], row['number'], row['suffix'])] = row['heading']
    mismatches = [key for key in sorted(set(headings) | set(expected)) if headings.get(key) != expected.get(key)]
    print(f'{len(mismatches)} mismatches of {len(expected)}')
    for key in mismatches[:20]:
        print(f'  {key}: got {headings.get(key)!r}, expected {expected.get(key)!r}')


if __name__ == '__main__':
    main()
