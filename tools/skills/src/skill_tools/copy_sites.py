"""Copy-site names stay out of the model-facing content (owner, 2026-11-14: «Hide all copy sites»), run by skill-ci.

The names are `names` in content/corpus/copy-sites.json, the one list the legal-search tests read as well. The
model-facing files: every file of every skill (SKILL.md, whose frontmatter description is the skill catalog's text, and
its references), the prompts, the starters, the specialists, and tiers.json (each tier agent carries its description).
A name in one of them fails skill-ci, except in the files pinned to the live instructions (the v1.3 edition and the
pinned skill), which must not change: a name there is reported for the owner and does not fail.

A name matches ignoring case, tatweel and Arabic diacritics, where no letter or digit is joined to it on either side,
except one attached و/ف/ب/ل/ك before it: «المحامي الأردني», a statutory term, is not the site title «محامي الأردن»."""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from skill_tools.checks import Problem

LIST = 'corpus/copy-sites.json'
PINNED_FILES = ('prompts/aqel-v1.3-librechat.md',)
PINNED_FOLDERS = ('skills/jordanian-case-analysis/',)
PRODUCT_NAMES = ('عقل', 'aqel', 'اقرأ للمحاماة')
_MARKS = re.compile('[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۨ-ۭـ]')
_PROCLITICS = set('وفبلك')


@dataclass
class Result:
    problems: list[Problem] = field(default_factory=list)
    pinned: list[str] = field(default_factory=list)  # hits in the pinned files, for the owner
    scanned: int = 0


def fold(text: str) -> str:
    return _MARKS.sub('', unicodedata.normalize('NFC', text)).casefold()


def _joined(line: str, index: int) -> bool:
    return 0 <= index < len(line) and line[index].isalnum()


def find_names(text: str, names: list[str]) -> list[tuple[int, str]]:
    """(line number, name) for each listed name the text names, one per name and line."""
    folded_names = {}
    for name in names:
        folded_names.setdefault(fold(name), name)
    hits = []
    for number, raw in enumerate(text.split('\n'), 1):
        line = fold(raw)
        for folded, name in folded_names.items():
            start = line.find(folded)
            while start != -1:
                end = start + len(folded)
                before = start - 1
                if before >= 0 and line[before] in _PROCLITICS and not _joined(line, before - 1):
                    before = -1
                if not _joined(line, before) and not _joined(line, end):
                    hits.append((number, name))
                    break
                start = line.find(folded, start + 1)
    return hits


def model_facing_files(content: Path) -> list[str]:
    """Content-relative paths of the model-facing files, sorted."""
    files = [path for folder in ('skills', 'prompts', 'starters') if (content / folder).is_dir()
             for path in (content / folder).rglob('*') if path.is_file()]
    files += sorted((content / 'specialists').glob('*.json')) + [content / 'tiers.json']
    paths = {path.relative_to(content).as_posix() for path in files if path.is_file() and not path.is_symlink()}
    # skills/RELEASED.json is the release record (versions and digests), not a skill; caches are not content.
    return sorted(path for path in paths if path != 'skills/RELEASED.json' and '__pycache__/' not in path)


def is_pinned(relative: str) -> bool:
    return relative in PINNED_FILES or relative.startswith(PINNED_FOLDERS)


def load_names(content: Path) -> tuple[list[str], list[Problem]]:
    path = content / LIST
    if not path.is_file():
        return [], [Problem(LIST, 'copy-sites', 'missing: the list of copy-site names')]
    try:
        names = json.loads(path.read_text(encoding='utf-8')).get('names')
    except (ValueError, AttributeError):
        names = None
    if not (isinstance(names, list) and names and all(isinstance(n, str) and n.strip() for n in names)):
        return [], [Problem(LIST, 'copy-sites', 'must be {"names": [non-empty strings], "note": ...}')]
    products = [name for name in names if fold(name).strip() in {fold(p) for p in PRODUCT_NAMES}]
    if products:
        return [], [Problem(LIST, 'copy-sites', f'lists the product\'s own name {products[0]!r}')]
    return names, []


def check(content: Path) -> Result:
    names, problems = load_names(content)
    result = Result(problems=problems)
    if not names:
        return result
    for relative in model_facing_files(content):
        try:
            text = (content / relative).read_bytes().decode('utf-8')
        except UnicodeDecodeError:
            continue
        result.scanned += 1
        for line, name in find_names(text, names):
            if is_pinned(relative):
                result.pinned.append(f'{relative}:{line}: names the copy site «{name}»')
            else:
                result.problems.append(Problem(relative, 'copy-site', f'line {line} names the copy site «{name}»'))
    return result
