"""Read a SKILL.md: a YAML frontmatter block between `---` lines, then the body."""

from dataclasses import dataclass

import yaml


class FrontmatterError(ValueError):
    pass


@dataclass(frozen=True)
class SkillDoc:
    frontmatter: dict
    body: str


def parse_skill_md(text: str) -> SkillDoc:
    text = text.replace('\r\n', '\n')
    if not text.startswith('---\n'):
        raise FrontmatterError('SKILL.md must start with a --- frontmatter block')
    end = text.find('\n---\n', 3)
    if end == -1:
        raise FrontmatterError('frontmatter block is not closed with a --- line')
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError as error:
        raise FrontmatterError(f'frontmatter is not valid YAML: {error}') from error
    if not isinstance(data, dict):
        raise FrontmatterError('frontmatter must be a mapping')
    return SkillDoc(frontmatter=data, body=text[end + 5:])
