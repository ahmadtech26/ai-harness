"""Parse statute shards (`### المادة N` sections) into article records."""

import re
from dataclasses import dataclass
from pathlib import Path

from legal_search.normalize import fold

# The suffix is «مكرر» plus at most one word; a dash is never that word (`153 مكرر — –` is article 153 مكرر).
_HEADING = re.compile(
    r'^###\s+المادة\s+(?P<number>[0-9٠-٩]+)\s*(?P<suffix>مكرر(?:\s+[^\s—–-]\S*)?)?\s*(?:[—–-]\s*(?P<inline>.*))?$'
)
# What follows «— » on a heading line when it holds no words (e.g. «):», «–», «ــ»): not article text.
_PUNCTUATION_ONLY = re.compile(r'^[\s:;.,()\[\]—–\-ـ]*$')
_FRONTMATTER = re.compile(r'\A---\n.*?\n---\n', re.DOTALL)
_SEPARATOR = re.compile(r'^\s*---\s*$')


@dataclass(frozen=True)
class Article:
    law_slug: str
    law_title: str
    number: int
    suffix: str
    text: str
    source: str
    shard: str

    @property
    def label(self) -> str:
        return f'المادة {self.number}' + (f' {self.suffix}' if self.suffix else '')


def _frontmatter_value(header: str, key: str) -> str:
    match = re.search(rf'^{key}:\s*(.+)$', header, re.MULTILINE)
    return match.group(1).strip().strip('"') if match else ''


def parse_shard(path: Path, law_slug: str) -> list[Article]:
    raw = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    header_match = _FRONTMATTER.match(raw)
    header = header_match.group(0) if header_match else ''
    law_title = _frontmatter_value(header, 'parent_law')
    source = _frontmatter_value(header, 'source')
    body = raw[len(header):]

    articles: list[Article] = []
    current: dict | None = None
    lines: list[str] = []

    def flush() -> None:
        if current is None:
            return
        # Keep paragraph breaks (verbatim quotation depends on them); collapse runs of blank lines.
        text = re.sub(r'\n{3,}', '\n\n', '\n'.join([current['inline'], *lines])).strip()
        if text:
            articles.append(
                Article(law_slug, law_title, current['number'], current['suffix'], text, source, path.name)
            )

    for line in body.split('\n'):
        heading = _HEADING.match(line.strip())
        if heading:
            flush()
            inline = (heading.group('inline') or '').strip()
            current = {
                'number': int(fold(heading.group('number'))),
                'suffix': (heading.group('suffix') or '').strip(),
                'inline': '' if _PUNCTUATION_ONLY.match(inline) else inline,
            }
            lines = []
        elif current is not None and not _SEPARATOR.match(line):
            lines.append(line.strip())
    flush()
    return articles


def parse_law(directory: Path, law_slug: str) -> list[Article]:
    """All articles of one law, from its `sections/*.md` shards in file order."""
    articles: list[Article] = []
    for shard in sorted((directory / 'sections').glob('*.md')):
        articles.extend(parse_shard(shard, law_slug))
    return articles
