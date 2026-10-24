from pathlib import Path

DESCRIPTION = 'Method for testing skill CI with a description long enough to pass.'


def make_skill(root: Path, folder: str, *, name: str | None = None, description: str = DESCRIPTION,
               version: str = '1.0.0', extra_metadata: str = '', body: str = '# Body\n',
               files: dict[str, bytes] | None = None) -> Path:
    path = root / folder
    path.mkdir(parents=True)
    frontmatter = (
        f'---\nname: {name or folder}\ndescription: {description}\nmetadata:\n'
        f'  version: "{version}"\n{extra_metadata}---\n\n'
    )
    (path / 'SKILL.md').write_text(frontmatter + body, encoding='utf-8')
    for relative, data in (files or {}).items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return path
