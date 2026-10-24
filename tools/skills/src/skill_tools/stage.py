"""skill-stage: copy a release's skills into a build folder (LF line endings) with RELEASE.json.

    skill-stage --content /w/content --out /out --tag staging --platform 1b5062d32 [--extra /extra/0 ...]
                [--record /rw/content/skills/RELEASED.json]

The build folder is the context of deploy/release/Dockerfile: <out>/skills/<name>/... and
<out>/skills/RELEASE.json. Extra folders hold drill or test skills that ship in that image only.
"""

import argparse
import json
from pathlib import Path

from skill_tools import checks
from skill_tools.digest import folder_digest, read_normalised, skill_files


def stage(content: Path, extras: list[Path], out: Path, *, tag: str, platform: str) -> dict:
    target = out / 'skills'
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f'{target} is not empty')
    sources = [(folder, 'content') for folder in sorted((content / 'skills').iterdir()) if folder.is_dir()]
    sources += [(folder, 'extra') for root in extras for folder in sorted(root.iterdir()) if folder.is_dir()]
    seen: dict[str, Path] = {}
    entries = []
    for folder, origin in sources:
        skill, problems = checks.load_skill(folder)
        if skill is None:
            raise SystemExit('; '.join(f'{p.skill}: {p.message}' for p in problems))
        name = skill.frontmatter.get('name')
        if name in seen:
            raise SystemExit(f'duplicate skill name {name!r}: {seen[name]} and {folder}')
        seen[name] = folder
        for path in skill_files(folder):
            destination = target / folder.name / path.relative_to(folder)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(read_normalised(path))
        entries.append({
            'name': name,
            'version': str(checks.metadata(skill).get('version', '')),
            'digest': folder_digest(folder),
            'source': origin,
        })
    manifest = {'tag': tag, 'platform': platform, 'skills': entries}
    (target / 'RELEASE.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


def record(manifest: dict, path: Path) -> None:
    released = {entry['name']: {'version': entry['version'], 'digest': entry['digest']}
                for entry in manifest['skills'] if entry['source'] == 'content'}
    path.write_text(json.dumps({'skills': released}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--content', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--platform', required=True)
    parser.add_argument('--extra', type=Path, action='append', default=[])
    parser.add_argument('--record', type=Path, help='write the content skills as the released set')
    args = parser.parse_args(argv)
    manifest = stage(args.content, args.extra, args.out, tag=args.tag, platform=args.platform)
    if args.record:
        record(manifest, args.record)
    print(f'staged {len(manifest["skills"])} skills for {args.tag}')
