import json
from pathlib import Path

import pytest

from skill_tools import stage
from skill_tools.digest import folder_digest
from tests.helpers import make_skill


def _content(root: Path) -> Path:
    content = root / 'content'
    make_skill(content / 'skills', 'alpha', files={'references/a.md': b'one\r\ntwo\r\n'})
    return content


def test_copies_content_and_extra_skills_with_lf_line_endings(tmp_path: Path):
    content = _content(tmp_path)
    extra = tmp_path / 'extra'
    make_skill(extra, 'beta')

    stage.stage(content, [extra], tmp_path / 'out', tag='t1', platform='abc123')

    assert (tmp_path / 'out/skills/alpha/references/a.md').read_bytes() == b'one\ntwo\n'
    assert (tmp_path / 'out/skills/beta/SKILL.md').is_file()


def test_writes_a_manifest_with_each_skill_version_and_digest(tmp_path: Path):
    content = _content(tmp_path)

    manifest = stage.stage(content, [], tmp_path / 'out', tag='t1', platform='abc123')

    on_disk = json.loads((tmp_path / 'out/skills/RELEASE.json').read_text(encoding='utf-8'))
    assert on_disk == manifest
    assert manifest == {'tag': 't1', 'platform': 'abc123', 'skills': [{
        'name': 'alpha', 'version': '1.0.0', 'digest': folder_digest(content / 'skills/alpha'), 'source': 'content'}]}


def test_rejects_two_skills_with_the_same_name(tmp_path: Path):
    content = _content(tmp_path)
    extra = tmp_path / 'extra'
    make_skill(extra, 'alpha')

    with pytest.raises(SystemExit, match="duplicate skill name 'alpha'"):
        stage.stage(content, [extra], tmp_path / 'out', tag='t1', platform='abc123')


def test_record_writes_only_content_skills(tmp_path: Path):
    content = _content(tmp_path)
    extra = tmp_path / 'extra'
    make_skill(extra, 'beta')
    manifest = stage.stage(content, [extra], tmp_path / 'out', tag='t1', platform='abc123')
    record = tmp_path / 'RELEASED.json'

    stage.record(manifest, record)

    assert json.loads(record.read_text(encoding='utf-8')) == {'skills': {
        'alpha': {'version': '1.0.0', 'digest': folder_digest(content / 'skills/alpha')}}}
