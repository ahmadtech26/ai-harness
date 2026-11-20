from pathlib import Path

from skill_tools import checks
from tests.helpers import make_skill


def _load(folder: Path) -> checks.Skill:
    skill, problems = checks.load_skill(folder)
    assert problems == []
    return skill


def _format_problems(skill: checks.Skill) -> list[checks.Problem]:
    return (checks.check_name(skill) + checks.check_description(skill) + checks.check_size(skill)
            + checks.check_files(skill) + checks.check_version(skill))


def test_a_valid_skill_passes_every_format_rule(tmp_path: Path):
    skill = _load(make_skill(tmp_path, 'good-skill', files={'references/a.md': 'نص'.encode()}))

    assert _format_problems(skill) == []


def test_rejects_a_name_that_differs_from_its_folder_or_breaks_librechat_rules(tmp_path: Path):
    other = _load(make_skill(tmp_path, 'folder-a', name='folder-b'))
    upper = _load(make_skill(tmp_path, 'Bad_Name'))
    reserved = _load(make_skill(tmp_path, 'claude-helper'))

    rules = [[p.rule for p in checks.check_name(s)] for s in (other, upper, reserved)]

    assert rules == [['name-folder'], ['name-format'], ['name-reserved']]


def test_rejects_a_missing_or_too_long_description(tmp_path: Path):
    short = _load(make_skill(tmp_path, 'short-desc', description='too short'))
    long = _load(make_skill(tmp_path, 'long-desc', description='x' * 1025))

    assert [p.rule for p in checks.check_description(short) + checks.check_description(long)] == [
        'description', 'description']


def test_rejects_a_description_longer_than_the_skill_catalog_passes(tmp_path: Path):
    at_limit = _load(make_skill(tmp_path, 'at-limit', description='ن' * 250))
    over = _load(make_skill(tmp_path, 'over-limit', description='Jordanian ' + 'x' * 241))

    assert checks.check_catalog_description(at_limit) == []
    assert [(p.rule, '251 characters' in p.message) for p in checks.check_catalog_description(over)] == [
        ('catalog-description', True)]


def test_rejects_a_skill_md_over_20000_characters(tmp_path: Path):
    skill = _load(make_skill(tmp_path, 'big-skill', body='ن' * 20_001))

    assert [p.rule for p in checks.check_size(skill)] == ['size']


def test_rejects_a_file_over_256_kb_or_not_utf8(tmp_path: Path):
    skill = _load(make_skill(tmp_path, 'files-skill', files={
        'references/big.md': b'a' * 262_145,
        'references/latin1.md': 'café'.encode('latin-1'),
    }))

    assert sorted(p.message.split(':')[0] for p in checks.check_files(skill)) == [
        'references/big.md', 'references/latin1.md']


def test_rejects_a_file_path_librechat_cannot_load(tmp_path: Path):
    skill = _load(make_skill(tmp_path, 'path-skill', files={'references/قائمة.md': b'x'}))

    assert [p.message.split(':')[0] for p in checks.check_files(skill)] == ['references/قائمة.md']


def test_rejects_a_version_that_is_not_semver(tmp_path: Path):
    skill = _load(make_skill(tmp_path, 'ver-skill', version='v1'))

    assert [p.rule for p in checks.check_version(skill)] == ['version']
