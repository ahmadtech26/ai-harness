import json
from pathlib import Path

import pytest

from skill_tools import ci
from tests.helpers import make_skill

SPECIALIST = {'name': 'aqel', 'skills': ['good-skill'], 'tools': []}


def _content(root: Path, *, skills: list[str], review: str = 'draft') -> Path:
    content = root / 'content'
    for name in skills:
        make_skill(content / 'skills', name, extra_metadata=f'  review:\n    status: {review}\n')
    (content / 'specialists').mkdir(parents=True)
    (content / 'specialists' / 'aqel.json').write_text(json.dumps(SPECIALIST), encoding='utf-8')
    return content


def test_exits_non_zero_and_names_each_problem(tmp_path: Path, capsys):
    content = _content(tmp_path, skills=['good-skill'])
    make_skill(content / 'skills', 'Bad_Name')

    with pytest.raises(SystemExit) as exit_info:
        ci.main(['--content', str(content)])

    assert exit_info.value.code == 1
    assert 'FAIL Bad_Name: name-format' in capsys.readouterr().out


def test_passes_clean_content_unless_release_requires_review(tmp_path: Path):
    content = _content(tmp_path, skills=['good-skill'])

    assert ci.run(content, release=False) == []
    assert [p.rule for p in ci.run(content, release=True)] == ['review']


def test_flags_a_specialist_listing_a_missing_skill(tmp_path: Path):
    content = _content(tmp_path, skills=[])
    (content / 'skills').mkdir(parents=True)

    assert [(p.skill, p.rule) for p in ci.run(content, release=False)] == [('good-skill', 'specialist-skill')]


def test_reports_a_skill_whose_skill_md_is_missing_or_unparseable(tmp_path: Path):
    content = _content(tmp_path, skills=['good-skill'])
    (content / 'skills' / 'no-skill-md').mkdir()
    broken = content / 'skills' / 'broken-frontmatter'
    broken.mkdir()
    (broken / 'SKILL.md').write_text('---\nname: broken-frontmatter\n', encoding='utf-8')

    assert sorted((p.skill, p.rule) for p in ci.run(content, release=False)) == [
        ('broken-frontmatter', 'frontmatter'), ('no-skill-md', 'skill-md')]
