"""The law registry (content/corpus/laws.json) as the ingest reads it, and law-directory.md's counts.

corpus-ci (tools/skills) enforces the registry's full rules: schema, sources, ISO dates, review. This
module reads the fields the service stores and fails fast on what it cannot use."""

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class Gap:
    number: int
    suffix: str
    reason: str


@dataclass(frozen=True)
class Law:
    slug: str
    title: str
    folder: str
    number: int | None = None
    year: int | None = None
    gazette_issue: int | None = None
    gazette_date: date | None = None
    gazette_url: str | None = None
    amendment_law: int | None = None
    amendment_year: int | None = None
    amendment_gazette_issue: int | None = None
    amendment_gazette_date: date | None = None
    amendment_url: str | None = None
    note: str | None = None
    known_gaps: tuple[Gap, ...] = ()
    approved: bool = False


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _law(entry: dict) -> Law:
    try:
        gazette = entry.get('gazette') or {}
        amendment = entry.get('amendment') or {}
        return Law(
            slug=entry['slug'],
            title=entry['title'],
            folder=entry['folder'],
            number=entry.get('number'),
            year=entry.get('year'),
            gazette_issue=gazette.get('issue'),
            gazette_date=_date(gazette.get('date')),
            gazette_url=gazette.get('source_url'),
            amendment_law=amendment.get('law'),
            amendment_year=amendment.get('year'),
            amendment_gazette_issue=amendment.get('gazette_issue'),
            amendment_gazette_date=_date(amendment.get('gazette_date')),
            amendment_url=amendment.get('source_url'),
            note=entry.get('note'),
            known_gaps=tuple(Gap(g['number'], g.get('suffix', ''), g['reason']) for g in entry.get('known_gaps', [])),
            approved=(entry.get('review') or {}).get('status') == 'approved',
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise RegistryError(f'registry entry {entry.get("slug", "?")!r}: {error!r}') from error


def load_registry(path: Path) -> list[Law]:
    laws = [_law(entry) for entry in json.loads(path.read_text(encoding='utf-8'))['laws']]
    slugs = [law.slug for law in laws]
    duplicates = sorted({slug for slug in slugs if slugs.count(slug) > 1})
    if duplicates:
        raise RegistryError(f'duplicate slugs in the registry: {", ".join(duplicates)}')
    return laws


_DIRECTORY_ROW = re.compile(r'^\|[^|]*\|\s*`(?P<folder>[^`]+)`\s*\|\s*(?P<count>[0-9]+)\s*\|')


def directory_counts(path: Path) -> dict[str, int]:
    """Folder → article count, from the rows of law-directory.md's table."""
    counts = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        match = _DIRECTORY_ROW.match(line.strip())
        if match:
            counts[match.group('folder')] = int(match.group('count'))
    return counts
