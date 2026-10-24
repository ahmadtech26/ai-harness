from pathlib import Path

import pytest

from skill_tools.digest import folder_digest
from skill_tools.frontmatter import FrontmatterError, parse_skill_md


def test_parses_frontmatter_and_body():
    doc = parse_skill_md('---\nname: x\nmetadata:\n  version: "1.0.0"\n---\n\n# Body\n')

    assert doc.frontmatter == {'name': 'x', 'metadata': {'version': '1.0.0'}}
    assert doc.body == '\n# Body\n'


def test_rejects_a_file_without_a_closed_frontmatter_block():
    with pytest.raises(FrontmatterError, match='not closed'):
        parse_skill_md('---\nname: x\n# no closing line\n')


def _skill(root: Path, newline: str) -> Path:
    folder = root / 'demo'
    (folder / 'references').mkdir(parents=True)
    (folder / 'SKILL.md').write_bytes(f'---{newline}name: demo{newline}---{newline}نص{newline}'.encode())
    (folder / 'references' / 'a.md').write_bytes(f'line 1{newline}line 2{newline}'.encode())
    return folder


def test_digest_is_the_same_for_crlf_and_lf_copies(tmp_path: Path):
    lf = _skill(tmp_path / 'lf', '\n')
    crlf = _skill(tmp_path / 'crlf', '\r\n')

    assert folder_digest(lf) == folder_digest(crlf)


def test_digest_changes_when_a_file_changes(tmp_path: Path):
    folder = _skill(tmp_path, '\n')
    before = folder_digest(folder)

    (folder / 'references' / 'a.md').write_text('line 1\nline 2 changed\n', encoding='utf-8')

    assert folder_digest(folder) != before
