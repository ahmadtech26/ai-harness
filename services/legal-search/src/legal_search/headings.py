"""Article headings for the keyword engine's heading field (recall plan Task 2.3), ported from the bench's
.hq/scratch/rag-bench/py/extract.py, `build(copy=True)` (the T-B2 variant «copyhead»). extract is pure; the text is never changed there.

An article's heading is
    the previous article's trailing heading: its last paragraph when that reads as a heading (short, unpunctuated,
    after a paragraph that ended a sentence), or, in a law where at least BLEED_RATE of the articles end that way,
    the words after its last sentence end;
    plus the article's own leading unpunctuated short paragraphs (or the opening words of a structural heading).

The trailing heading an article lends to the next one is not part of that article's text (owner, 2026-11-14 §7: in
1,750 articles the stored text ended with the next article's heading). glued_headings names it for every article whose
text ends with a heading that equals or begins the next article's heading, and strip_glued removes it; the ingest
(ingest.prepare) extracts the headings from the text as published first, then stores the text without them.

    python -m legal_search.headings --registry … --corrections … --corpus … [--compare FILE]
prints the number of articles whose heading differs from FILE's ({law, number, suffix, heading} rows) and the first 20.
Python 3.11 syntax only.
"""

import argparse
import json
import re
from collections.abc import Iterable
from dataclasses import replace
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


def bleeds(law_articles: list[Article]) -> bool:
    """Whether the law's articles end in a sentence-heading often enough (BLEED_RATE) for a sentence tail to count."""
    return bool(law_articles) and sum(1 for a in law_articles if tail_sentence(a.text)) / len(law_articles) >= BLEED_RATE


def trailing_heading(text: str, law_bleeds: bool) -> str | None:
    """The heading at the end of an article's text that belongs to what follows, if any."""
    return tail_paragraph(text) or (tail_sentence(text) if law_bleeds else None)


def extract(articles: Iterable[Article]) -> dict[Key, str]:
    """Each article's heading, by (law, number, suffix). `articles` in file order, as parsed (the text as published:
    ingest.prepare calls this before it strips the glued headings)."""
    by_law: dict[str, list[Article]] = {}
    for item in articles:
        by_law.setdefault(item.law_slug, []).append(item)
    headings: dict[Key, str] = {}
    for law_articles in by_law.values():
        law_bleeds = bleeds(law_articles)
        previous_tail = ''
        for index, item in enumerate(law_articles):
            heading = [previous_tail] if previous_tail else []
            previous_tail = ''
            if index + 1 < len(law_articles):
                previous_tail = trailing_heading(item.text, law_bleeds) or ''
            own = head_heading(item.text)
            if own:
                heading.append(own)
            headings[(item.law_slug, item.number, item.suffix)] = ' '.join(h for h in heading if h)
    return headings


# Article endings that the rule below would take for a heading but that are statutory text: the article's last paragraph
# lacks its full stop. Each is checked against the Bureau's text of the article, which ends with the same words.
STATUTORY_ENDINGS: frozenset[Key] = frozenset({
    ('civil-code', 288, ''),  # «ولمن أدى الضمان ان يرجع بما دفع، على المحكوم عليه به» (Bureau 536, art. 288(2))
})


def glued_headings(law_articles: list[Article], headings: dict[Key, str]) -> dict[Key, str]:
    """For one law's articles in file order and the headings extract gave them: each article (but the last) whose text
    ends with a trailing heading that equals or begins the next article's heading, with that heading; never one listed
    in STATUTORY_ENDINGS."""
    law_bleeds = bleeds(law_articles)
    glued: dict[Key, str] = {}
    for index, item in enumerate(law_articles[:-1]):
        key = (item.law_slug, item.number, item.suffix)
        tail = trailing_heading(item.text, law_bleeds)
        following = law_articles[index + 1]
        next_heading = headings.get((following.law_slug, following.number, following.suffix), '')
        if tail and key not in STATUTORY_ENDINGS and (next_heading == tail or next_heading.startswith(tail + ' ')):
            glued[key] = tail
    return glued


def strip_glued(law_articles: list[Article], glued: dict[Key, str]) -> list[Article]:
    """The articles with each glued heading cut from the end of the text (and the whitespace before it); every other
    article is returned as it is."""
    out = []
    for item in law_articles:
        tail = glued.get((item.law_slug, item.number, item.suffix))
        if tail:
            text = item.text.strip()
            if not text.endswith(tail):
                raise ValueError(f'{item.law_slug} {item.label}: the glued heading is not at the end of the text')
            item = replace(item, text=text[: -len(tail)].rstrip())
        out.append(item)
    return out


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
    headings = {key: heading for law_headings in prepared.headings.values() for key, heading in law_headings.items()}
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
