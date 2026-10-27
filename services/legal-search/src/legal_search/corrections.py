"""Data corrections (content/corpus/corrections.json), applied to parsed articles before loading.

    replace  {law, number, suffix?, occurrence?, text}                           new text for one article
    split    {law, number, suffix?, occurrence?, marker, second: {number, suffix?}}
             the text from `marker` on becomes a second article
    relabel  {law, number, suffix?, occurrence?, new_suffix}                     a new suffix for one article

Every correction also carries `reason` and `source`. `occurrence` (default 1) picks among the parsed
articles of that law with the same number and suffix, in file order. A correction that matches no
article fails the run: the source changed and the correction must be revisited."""

import json
from dataclasses import dataclass
from dataclasses import replace as with_changes
from pathlib import Path

from legal_search.corpus import Article


class CorrectionError(ValueError):
    pass


@dataclass(frozen=True)
class Correction:
    type: str
    law: str
    number: int
    suffix: str = ''
    occurrence: int = 1
    text: str | None = None
    marker: str | None = None
    second_number: int | None = None
    second_suffix: str = ''
    new_suffix: str | None = None

    @property
    def target(self) -> str:
        label = f'{self.law} المادة {self.number}' + (f' {self.suffix}' if self.suffix else '')
        return f'{label} (occurrence {self.occurrence})'


_TYPE_FIELDS = {'replace': ('text',), 'split': ('marker', 'second'), 'relabel': ('new_suffix',)}


def _correction(entry: dict) -> Correction:
    kind = entry.get('type')
    if kind not in _TYPE_FIELDS:
        raise CorrectionError(f'unknown correction type {kind!r}')
    missing = [key for key in ('law', 'number', 'reason', 'source', *_TYPE_FIELDS[kind]) if key not in entry]
    if missing:
        raise CorrectionError(f'{kind} correction is missing {", ".join(missing)}')
    second = entry.get('second') or {}
    if kind == 'split' and not isinstance(second.get('number'), int):
        raise CorrectionError('split correction is missing second.number')
    return Correction(
        type=kind,
        law=entry['law'],
        number=entry['number'],
        suffix=entry.get('suffix', ''),
        occurrence=entry.get('occurrence', 1),
        text=entry.get('text'),
        marker=entry.get('marker'),
        second_number=second.get('number'),
        second_suffix=second.get('suffix', ''),
        new_suffix=entry.get('new_suffix'),
    )


def load_corrections(path: Path) -> list[Correction]:
    return [_correction(entry) for entry in json.loads(path.read_text(encoding='utf-8'))['corrections']]


def _index_of(articles: list[Article], correction: Correction) -> int:
    seen = 0
    for index, article in enumerate(articles):
        if (article.law_slug, article.number, article.suffix) == (correction.law, correction.number, correction.suffix):
            seen += 1
            if seen == correction.occurrence:
                return index
    raise CorrectionError(f'{correction.type} correction matched nothing: {correction.target}')


def _split(article: Article, correction: Correction) -> list[Article]:
    if article.text.count(correction.marker) != 1:
        raise CorrectionError(f'split marker must occur exactly once in {correction.target}')
    at = article.text.index(correction.marker)
    first, second = article.text[:at].strip(), article.text[at:].strip()
    if not first:
        raise CorrectionError(f'split marker leaves no text for the first article: {correction.target}')
    return [
        with_changes(article, text=first),
        with_changes(article, number=correction.second_number, suffix=correction.second_suffix, text=second),
    ]


def apply_corrections(articles: list[Article], corrections: list[Correction]) -> list[Article]:
    """The articles after every correction, applied in file order."""
    result = list(articles)
    for correction in corrections:
        index = _index_of(result, correction)
        article = result[index]
        if correction.type == 'replace':
            result[index] = with_changes(article, text=correction.text)
        elif correction.type == 'relabel':
            result[index] = with_changes(article, suffix=correction.new_suffix)
        else:
            result[index:index + 1] = _split(article, correction)
    return result
