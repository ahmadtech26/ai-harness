"""The glued-heading strip (owner, 2026-11-14 §7) against the official texts, by a check that does not use the strip
rule (the owner's point 11): no article the strip changed has a Gazette or Bureau text that ends with the words the
strip removed from it. Such an ending would mean that the strip cut law text, not the next article's heading.

The official texts are the evidence lines of the content tree, docs/verification/evidence/<law>.jsonl, beside content/
in a content checkout ({law_slug, number, suffix, source, text, url, …}). That folder is not in this tree, and the test
stack does not mount it (the eval service's /evidence is the eval's own output folder): VERIFICATION_EVIDENCE_DIR names
it, else it is the folder beside CONTENT_DIR (<CONTENT_DIR>/../docs/verification/evidence); without it the tests that
need it are skipped. An official text is a line whose source is gazette or bureau and whose url is not on qistas.com:
the penal code's Qistas readings are labelled gazette until the content PR relabels them qistas, and Qistas is a helper
source, never the Gazette. A line without text is no text.

A stripped article without an official text (the Majalla: it has no evidence file and no official source) is checked in
its source shard instead: the words removed are the last line of the article's block there, a markdown heading line.

The comparison uses the verification's own normalisation, v1, copied below from tools/verification/v1.py of the
content tree (not imported across trees; not the search normalisation), and then ignores punctuation as v1's compare
does when it calls a difference 'formatting' (its PUNCT class, replaced by a space). Trailing punctuation therefore does
not count: the strip only ever removes an ending without punctuation, so an official text that ends with the same words
and then a full stop («… الوفاء.») matches. The match is on whole words («… ابالغاءات» does not end with «الغاءات»)."""

import json
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import pytest

from legal_search.corrections import load_corrections
from legal_search.ingest import prepare
from legal_search.registry import load_registry

# --- v1, copied from the content tree's tools/verification/v1.py (owner's decision, 2026-11-14): Unicode NFC; tatweel
# and diacritics removed; Arabic-Indic and Extended Arabic-Indic digits to ASCII; whitespace and line breaks collapsed.
# The character classes are the file's, written here with \u escapes (its diacritic ranges hold combining marks).
TATWEEL = 'ـ'
DIACRITICS = re.compile('[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۨ-ۭ]')
DIGITS = ({ord(c): str(i) for i, c in enumerate('٠١٢٣٤٥٦٧٨٩')}
          | {ord(c): str(i) for i, c in enumerate('۰۱۲۳۴۵۶۷۸۹')})
SPACE = re.compile(r'\s+')
# punctuation for the formatting test only (never removed by v1 itself)
PUNCT = re.compile(r'[\.,،؛;:\-–—_\(\)\[\]\{\}\xab\xbb"\'!?؟…/\\*]')


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


def words(text: str) -> str:
    """The text as the check compares it: v1, then without punctuation."""
    return _no_punct(v1(text))


def ends_with(text: str, ending: str) -> bool:
    """Whether `text` ends with the words of `ending`, punctuation ignored, on a word boundary."""
    text, ending = words(text), words(ending)
    return bool(ending) and (text == ending or text.endswith(' ' + ending))


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


@pytest.fixture(scope='module')
def stripped():
    """The stripped articles, each (key, the words removed, the article as stored), the laws, every evidence line of
    each article, and the evidence folder."""
    if not (os.environ.get('CORPUS_DIR') and os.environ.get('CONTENT_DIR')):
        pytest.skip('real corpus not mounted')
    folder = evidence_dir()
    if folder is None:
        pytest.skip(f'no verification evidence folder: set {EVIDENCE_DIR}, or mount the content checkout so that '
                    'docs/verification/evidence is beside CONTENT_DIR')
    if not folder.is_dir():
        pytest.skip(f'{EVIDENCE_DIR} names no folder: {folder}')
    corpus_files = Path(os.environ['CONTENT_DIR']) / 'corpus'
    prepared = prepare(load_registry(corpus_files / 'laws.json'), load_corrections(corpus_files / 'corrections.json'),
                       Path(os.environ['CORPUS_DIR']))
    stored = {(slug, a.number, a.suffix): a for slug, articles in prepared.articles.items() for a in articles}
    lines: dict = {}
    for path in sorted(folder.glob('*.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                row = json.loads(line)
                lines.setdefault((row['law_slug'], row['number'], row['suffix']), []).append(row)
    articles = [(key, removed, stored[key]) for key, removed in sorted(prepared.glued.items())]
    return articles, prepared.laws, lines, folder


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
