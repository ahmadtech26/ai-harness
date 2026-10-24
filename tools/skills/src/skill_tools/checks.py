"""Skill CI rules. Every check returns a list of problems; an empty list means the rule passes.
Name and description limits mirror LibreChat's own validation (`packages/data-schemas/src/methods/skill.ts`);
the size and file limits are the platform's (SKILL.md ≤ 20,000 characters; files ≤ LibreChat's 256 KB read limit)."""

import re
from dataclasses import dataclass
from pathlib import Path

from skill_tools.digest import folder_digest
from skill_tools.frontmatter import FrontmatterError, parse_skill_md

MAX_SKILL_MD_CHARS = 20_000
MAX_FILE_BYTES = 262_144
NAME_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]*$')
MAX_NAME = 64
MIN_DESCRIPTION = 20
MAX_DESCRIPTION = 1024
RESERVED_PREFIXES = ('anthropic-', 'claude-')
RESERVED_WORDS = {'help', 'clear', 'compact', 'model', 'exit', 'quit', 'settings', 'anthropic', 'claude'}
SEMVER = re.compile(r'^(\d+)\.(\d+)\.(\d+)$')
RELATIVE_PATH = re.compile(r'^[a-zA-Z0-9._\-/]+$')  # LibreChat RELATIVE_PATH_CHARS; enforced at boot


@dataclass(frozen=True)
class Problem:
    skill: str
    rule: str
    message: str


@dataclass(frozen=True)
class Skill:
    folder: Path
    frontmatter: dict
    text: str

    @property
    def id(self) -> str:
        return self.folder.name


def load_skill(folder: Path) -> tuple[Skill | None, list[Problem]]:
    path = folder / 'SKILL.md'
    if not path.is_file():
        return None, [Problem(folder.name, 'skill-md', 'SKILL.md is missing')]
    try:
        text = path.read_bytes().decode('utf-8').replace('\r\n', '\n')
    except UnicodeDecodeError:
        return None, [Problem(folder.name, 'utf8', 'SKILL.md: not UTF-8')]
    try:
        doc = parse_skill_md(text)
    except FrontmatterError as error:
        return None, [Problem(folder.name, 'frontmatter', str(error))]
    return Skill(folder, doc.frontmatter, text), []


def metadata(skill: Skill) -> dict:
    value = skill.frontmatter.get('metadata')
    return value if isinstance(value, dict) else {}


def check_name(skill: Skill) -> list[Problem]:
    name = skill.frontmatter.get('name')
    if not isinstance(name, str) or name != skill.id:
        return [Problem(skill.id, 'name-folder', f'frontmatter name {name!r} must equal the folder name')]
    if len(name) > MAX_NAME or not NAME_PATTERN.match(name):
        return [Problem(skill.id, 'name-format', 'name must be kebab-case, at most 64 characters')]
    if name.startswith(RESERVED_PREFIXES) or name in RESERVED_WORDS:
        return [Problem(skill.id, 'name-reserved', f'{name!r} is reserved by LibreChat')]
    return []


def check_description(skill: Skill) -> list[Problem]:
    description = skill.frontmatter.get('description')
    if not isinstance(description, str) or not MIN_DESCRIPTION <= len(description.strip()) <= MAX_DESCRIPTION:
        return [Problem(skill.id, 'description', f'description must be {MIN_DESCRIPTION}–{MAX_DESCRIPTION} characters')]
    return []


def check_size(skill: Skill) -> list[Problem]:
    if len(skill.text) > MAX_SKILL_MD_CHARS:
        return [Problem(skill.id, 'size', f'SKILL.md has {len(skill.text)} characters (limit {MAX_SKILL_MD_CHARS})')]
    return []


def check_files(skill: Skill) -> list[Problem]:
    problems = []
    for path in sorted(skill.folder.rglob('*')):
        relative = path.relative_to(skill.folder).as_posix()
        if path.is_symlink():
            problems.append(Problem(skill.id, 'files', f'{relative}: symlinks are not allowed'))
            continue
        if not RELATIVE_PATH.match(relative):
            problems.append(Problem(skill.id, 'files', f'{relative}: LibreChat accepts only a-z A-Z 0-9 . _ - / in file paths'))
        if path.is_file():
            data = path.read_bytes()
            if len(data) > MAX_FILE_BYTES:
                problems.append(Problem(skill.id, 'files', f'{relative}: {len(data)} bytes (limit {MAX_FILE_BYTES})'))
            try:
                data.decode('utf-8')
            except UnicodeDecodeError:
                problems.append(Problem(skill.id, 'files', f'{relative}: not UTF-8'))
    return problems


def parse_version(value: object) -> tuple[int, int, int] | None:
    match = SEMVER.match(value) if isinstance(value, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def check_version(skill: Skill) -> list[Problem]:
    if parse_version(metadata(skill).get('version')) is None:
        return [Problem(skill.id, 'version', 'metadata.version must be a quoted semver string such as "1.0.0"')]
    return []


# Patterns, not values: a match is reported by file and kind only, never echoed.
SECRET_PATTERNS = {
    'provider key': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}'),
    'AWS access key': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    'private key': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    'credential assignment': re.compile(r'(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*["\']?[A-Za-z0-9/+_-]{12,}'),
}
# Phrases that try to override the system prompt or claim permissions. Heuristic: extend as needed.
OVERRIDE_PHRASES = (
    'ignore previous instructions', 'ignore all previous instructions', 'disregard the system prompt',
    'reveal your instructions', 'developer mode', 'you have admin', 'you are authorized to',
    'تجاهل التعليمات', 'تجاهل جميع التعليمات', 'اكشف التعليمات', 'لديك صلاحية', 'صلاحيات المسؤول',
)


def _text_files(skill: Skill) -> list[tuple[str, str]]:
    files = []
    for path in sorted(skill.folder.rglob('*')):
        if path.is_file() and not path.is_symlink():
            try:
                files.append((path.relative_to(skill.folder).as_posix(), path.read_bytes().decode('utf-8')))
            except UnicodeDecodeError:
                continue
    return files


def check_version_bump(skill: Skill, released: dict) -> list[Problem]:
    entry = released.get(skill.id)
    current = parse_version(metadata(skill).get('version'))
    if not entry or current is None or folder_digest(skill.folder) == entry.get('digest'):
        return []
    previous = parse_version(entry.get('version'))
    if previous is not None and current <= previous:
        return [Problem(skill.id, 'version-bump',
                        f'content changed since release {entry.get("version")}; raise metadata.version')]
    return []


def check_secrets(skill: Skill) -> list[Problem]:
    return [
        Problem(skill.id, 'secret', f'{relative}: looks like a {kind}')
        for relative, text in _text_files(skill)
        for kind, pattern in SECRET_PATTERNS.items()
        if pattern.search(text)
    ]


def check_override_phrases(skill: Skill) -> list[Problem]:
    problems = []
    for relative, text in _text_files(skill):
        lowered = text.lower()
        found = [phrase for phrase in OVERRIDE_PHRASES if phrase in lowered]
        if found:
            problems.append(Problem(skill.id, 'override', f'{relative}: contains {found[0]!r}'))
    return problems


def check_required_tools(skill: Skill, specialists: list[dict]) -> list[Problem]:
    requires = metadata(skill).get('requires')
    required = set(requires.get('tools', [])) if isinstance(requires, dict) else set()
    problems = []
    for specialist in specialists:
        if skill.id not in specialist.get('skills', []):
            continue
        # LibreChat names MCP tools "<tool>_mcp_<server>".
        offered = {tool.split('_mcp_')[0] for tool in specialist.get('tools', [])}
        missing = sorted(required - offered)
        if missing:
            problems.append(Problem(skill.id, 'tools',
                                    f'specialist {specialist.get("name")!r} lists this skill but lacks {", ".join(missing)}'))
    return problems


def check_review(skill: Skill) -> list[Problem]:
    review = metadata(skill).get('review')
    review = review if isinstance(review, dict) else {}
    if review.get('status') != 'approved' or not review.get('approved_by') or not review.get('approved_on'):
        return [Problem(skill.id, 'review', 'release needs metadata.review: status approved, approved_by, approved_on')]
    return []
