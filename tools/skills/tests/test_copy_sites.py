"""skill-ci's copy-site check: no model-facing file names a site from content/corpus/copy-sites.json."""

import json
from pathlib import Path

import pytest

from skill_tools import ci, copy_sites
from tests.helpers import make_skill

# The names of content/corpus/copy-sites.json, as the check reads them from the content tree.
NAMES = ['jordan-lawyer.com', 'aqel-lawfirm.com', 'adaleh.info', 'حماة الحق', 'حُماة الحق', 'محامي الأردن', 'محامي الاردن']
SPECIALIST = {'name': 'عقل — المستشار القانوني', 'description': 'تحليل القضايا من نصوص المكتبة القانونية.',
              'instructionsFile': '../prompts/aqel-v1.3-librechat.md', 'skills': ['demo-skill', 'jordanian-case-analysis'],
              'tools': []}


def write_list(content: Path, names: object = NAMES) -> None:
    (content / 'corpus').mkdir(parents=True, exist_ok=True)
    (content / 'corpus' / 'copy-sites.json').write_text(
        json.dumps({'note': 'fixture', 'names': names}, ensure_ascii=False), encoding='utf-8')


def _content(root: Path) -> Path:
    content = root / 'content'
    make_skill(content / 'skills', 'demo-skill', files={'references/notes.md': 'ابحث في المكتبة القانونية.\n'.encode()})
    make_skill(content / 'skills', 'jordanian-case-analysis', body='# Method\n\nCite the library.\n')
    (content / 'prompts').mkdir()
    (content / 'prompts' / 'aqel-v1.3-librechat.md').write_text('# AQEL\n\nأنت عقل.\n', encoding='utf-8')
    (content / 'prompts' / 'aqel-v1.5-librechat.md').write_text('# AQEL\n\nأنت عقل.\n', encoding='utf-8')
    (content / 'starters').mkdir()
    (content / 'starters' / 'starters.ar.json').write_text('{"starters": ["ما مدة الاستئناف؟"]}\n', encoding='utf-8')
    (content / 'specialists').mkdir()
    (content / 'specialists' / 'aqel.json').write_text(json.dumps(SPECIALIST, ensure_ascii=False), encoding='utf-8')
    (content / 'tiers.json').write_text('{"tiers": [{"label": "عقل سريع", "description": "إجابات سريعة."}]}\n', encoding='utf-8')
    write_list(content)
    return content


def _append(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding='utf-8') + text, encoding='utf-8')


def test_clean_content_passes_and_the_product_names_are_not_hits(tmp_path: Path):
    result = copy_sites.check(_content(tmp_path))

    assert (result.problems, result.pinned, result.scanned) == ([], [], 8)


# (model-facing file, appended text, the name reported). One per place the owner listed, and the catalog text.
PLACES = [
    ('skills/demo-skill/SKILL.md', 'Commentary: jordan-lawyer.com\n', 'jordan-lawyer.com'),
    ('skills/demo-skill/references/notes.md', 'المصدر: موقع حماة الحق\n', 'حماة الحق'),
    ('prompts/aqel-v1.5-librechat.md', 'انقل عن https://aqel-lawfirm.com/ar/tashree3at/9\n', 'aqel-lawfirm.com'),
    ('starters/starters.ar.json', '{"x": "من موقع محامي الاردن"}\n', 'محامي الاردن'),
    ('specialists/aqel.json', '\n{"note": "adaleh.info"}\n', 'adaleh.info'),
    ('tiers.json', '{"description": "بحسب محامي الأردن"}\n', 'محامي الأردن'),
]


@pytest.mark.parametrize(('relative', 'text', 'name'), PLACES)
def test_a_name_in_a_model_facing_file_fails(tmp_path: Path, relative: str, text: str, name: str):
    content = _content(tmp_path)
    _append(content / relative, text)

    problems = copy_sites.check(content).problems

    assert [(p.skill, p.rule, p.message.split(' names ')[1]) for p in problems] == [(relative, 'copy-site', f'the copy site «{name}»')]


def test_a_name_in_a_skill_catalog_description_fails(tmp_path: Path):
    content = tmp_path / 'content'
    make_skill(content / 'skills', 'catalogued', description='Checklists drawn from jordan-lawyer.com commentary, for disputes.')
    write_list(content)

    assert [(p.skill, p.message) for p in copy_sites.check(content).problems] == [
        ('skills/catalogued/SKILL.md', 'line 3 names the copy site «jordan-lawyer.com»')]


def test_a_name_in_a_pinned_file_is_reported_not_failed(tmp_path: Path):
    content = _content(tmp_path)
    _append(content / 'prompts' / 'aqel-v1.3-librechat.md', 'jordan-lawyer.com\n')
    _append(content / 'skills' / 'jordanian-case-analysis' / 'SKILL.md', 'حُماة الحق\n')

    result = copy_sites.check(content)

    assert result.problems == []
    assert result.pinned == ['prompts/aqel-v1.3-librechat.md:4: names the copy site «jordan-lawyer.com»',
                             'skills/jordanian-case-analysis/SKILL.md:11: names the copy site «حماة الحق»']


@pytest.mark.parametrize(('text', 'found'), [
    ('ينظم قانون نقابة المحامين شؤون المحامي الأردني', []),  # statutory term, not the site title
    ('لمحامي الأردن', ['محامي الأردن']),  # one attached preposition
    ('حُمـاة الحقّ', ['حماة الحق']),  # tatweel and diacritics
    ('WWW.Jordan-Lawyer.COM/post', ['jordan-lawyer.com']),
    ('https://www.adaleh.info/Art.aspx', ['adaleh.info']),
    ('aqel-lawfirm.company', []),
    ('حماة الحقوق', []),
    ('عقل — اقرأ للمحاماة', []),
])
def test_matches_whole_names_only(text: str, found: list[str]):
    assert [name for _, name in copy_sites.find_names(text, NAMES)] == found


def test_the_list_is_required_and_never_names_the_product(tmp_path: Path):
    content = tmp_path / 'content'
    content.mkdir()
    missing = copy_sites.check(content).problems
    write_list(content, NAMES + ['AQEL'])
    product = copy_sites.check(content).problems
    write_list(content, [])
    empty = copy_sites.check(content).problems

    assert [p.message for p in missing + product + empty] == [
        'missing: the list of copy-site names', "lists the product's own name 'AQEL'",
        'must be {"names": [non-empty strings], "note": ...}']


def test_skill_ci_fails_on_a_name_and_lists_pinned_hits(tmp_path: Path, capsys):
    content = _content(tmp_path)
    _append(content / 'prompts' / 'aqel-v1.3-librechat.md', 'jordan-lawyer.com\n')
    _append(content / 'skills' / 'demo-skill' / 'references' / 'notes.md', 'adaleh.info\n')

    with pytest.raises(SystemExit) as exit_info:
        ci.main(['--content', str(content)])

    assert exit_info.value.code == 1
    assert capsys.readouterr().out.splitlines() == [
        'NOTE pinned, not changed, listed for the owner: prompts/aqel-v1.3-librechat.md:4: names the copy site «jordan-lawyer.com»',
        'FAIL skills/demo-skill/references/notes.md: copy-site: line 2 names the copy site «adaleh.info»',
    ]


def test_skill_ci_passes_clean_content_and_says_how_much_it_scanned(tmp_path: Path, capsys):
    ci.main(['--content', str(_content(tmp_path))])

    assert capsys.readouterr().out.splitlines() == ['skill-ci: all skills pass; no copy-site name in 8 model-facing files']
