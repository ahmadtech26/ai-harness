"""skill-ci: check every skill under <content>/skills against the release rules, and that no model-facing file names a
copy site from <content>/corpus/copy-sites.json (skill_tools.copy_sites; a name in a pinned file is reported, not failed).

    skill-ci --content /w/content            # staging: drafts allowed
    skill-ci --content /w/content --release  # production release: every skill must be approved
"""

import argparse
import json
import sys
from pathlib import Path

from skill_tools import checks, copy_sites


def run(content: Path, release: bool) -> list[checks.Problem]:
    skills_dir = content / 'skills'
    released_file = skills_dir / 'RELEASED.json'
    released = json.loads(released_file.read_text(encoding='utf-8'))['skills'] if released_file.is_file() else {}
    specialists = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((content / 'specialists').glob('*.json'))]
    problems: list[checks.Problem] = []
    names: set[str] = set()
    for folder in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill, load_problems = checks.load_skill(folder)
        problems += load_problems
        if skill is None:
            continue
        names.add(skill.id)
        problems += (
            checks.check_name(skill) + checks.check_description(skill) + checks.check_size(skill)
            + checks.check_files(skill) + checks.check_version(skill)
            + checks.check_version_bump(skill, released) + checks.check_secrets(skill)
            + checks.check_override_phrases(skill) + checks.check_required_tools(skill, specialists)
        )
        problems += checks.check_catalog_description(skill)
        if release:
            problems += checks.check_review(skill)
    for specialist in specialists:
        for listed in specialist.get('skills', []):
            if listed not in names:
                problems.append(checks.Problem(listed, 'specialist-skill',
                                               f'specialist {specialist.get("name")!r} lists a skill that does not exist'))
    return problems + copy_sites.check(content).problems


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--content', type=Path, required=True)
    parser.add_argument('--release', action='store_true', help='require an approved review on every skill')
    args = parser.parse_args(argv)
    problems = run(args.content, args.release)
    sites = copy_sites.check(args.content)
    for note in sites.pinned:
        print(f'NOTE pinned, not changed, listed for the owner: {note}')
    for problem in problems:
        print(f'FAIL {problem.skill}: {problem.rule}: {problem.message}')
    if problems:
        sys.exit(1)
    print('skill-ci: all skills pass' + (' (release)' if args.release else '')
          + f'; no copy-site name in {sites.scanned} model-facing files'
          + (f' (pinned files: {len(sites.pinned)} listed above)' if sites.pinned else ''))
