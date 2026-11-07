#!/usr/bin/env bash
# Build a release image: the Harness gates, then the fork image plus the content skills (and, for drills, extra skill folders).
#   deploy/release/build.sh <tag> <platform-sha> (--allow-draft | --production) [--extra <dir>]...
# Exactly one mode:
# --allow-draft  staging and drills: `tools/gates.sh checks`, where the skills, the law registry, the corrections and the
#                starter prompts need not be approved yet. No git call, nothing recorded, no label.
# --production   before anything else the Harness must be committed (`git status --porcelain` empty), the AI Platform
#                checkout (PLATFORM_DIR, default the sibling AI Platform) must be at <platform-sha> with nothing
#                uncommitted, since the fork gate runs on its working tree, and the platform image must carry
#                BUILD_COMMIT=<platform-sha> (deploy/release/build-platform.sh builds it from the committed tree); then
#                `tools/gates.sh --release` with every step but docker, the released versions written to
#                content/skills/RELEASED.json, and the image labelled org.iqraa.harness-commit. --extra is refused.
# IQRAA_IMAGE_PREFIX  image name prefix (default: iqraa): builds on $prefix/platform:<platform-sha>, tags $prefix/release:<tag>
# IQRAA_BUILD_DIR     where the stage folder <tag>-<timestamp> goes (default: deploy/release/.build)
# The scenarios do not run here: they need this image on the staging stack, so they are the next step (deploy/staging/README.md).
set -euo pipefail

usage() { echo "usage: $0 <tag> <platform-sha> (--allow-draft | --production) [--extra <dir>]..." >&2; exit 2; }
valid_tag() { [[ "$1" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; }  # Docker's tag grammar

[ $# -ge 2 ] && valid_tag "$1" && valid_tag "$2" || usage
tag=$1; platform=$2; shift 2
mode=""; extra_dirs=()
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-draft|--production) [ -z "$mode" ] || usage; mode=${1#--}; shift ;;
    --extra) [ $# -ge 2 ] && [ -n "$2" ] && [[ "$2" != -* ]] || usage; extra_dirs+=("$2"); shift 2 ;;
    *) echo "unknown argument: $1" >&2; usage ;;
  esac
done
[ -n "$mode" ] || usage
if [ "$mode" = production ] && [ ${#extra_dirs[@]} -gt 0 ]; then
  echo "--extra is for staging and drills: a production release ships the content skills only" >&2
  exit 2
fi

here="$(cd "$(dirname "$0")" && pwd)"
harness="$(cd "$here/../.." && pwd)"
prefix="${IQRAA_IMAGE_PREFIX:-iqraa}"
export IQRAA_IMAGE_PREFIX="$prefix"  # tools/gates.sh builds $prefix/skill-tools, the image skill-stage runs below
builds="${IQRAA_BUILD_DIR:-$here/.build}"
winpath() { (cd "$1" && (pwd -W 2>/dev/null || pwd)); }
extras=()
for dir in "${extra_dirs[@]}"; do
  resolved="$(cd "$dir" 2>/dev/null && pwd)" || { echo "--extra $dir: no such folder" >&2; exit 2; }
  extras+=("$resolved")
done

if [ "$mode" = production ]; then
  # Before anything else: a production release is built from the committed Harness only.
  dirty="$(git -C "$harness" status --porcelain)" || { echo "production: git status failed in $harness" >&2; exit 1; }
  if [ -n "$dirty" ]; then
    echo "production builds only a committed Harness: commit or remove these first (git status --porcelain):" >&2
    printf '%s\n' "$dirty" >&2
    exit 1
  fi
  harness_commit="$(git -C "$harness" rev-parse --short HEAD)"

  # The fork gate runs jest and tsc on the AI Platform working tree, so that tree must be the commit the platform image
  # was built from, with nothing uncommitted: otherwise the suites pass for code the release does not ship.
  platform_dir="${PLATFORM_DIR:-$harness/../AI Platform}"  # sibling repository, as build-platform.sh and platform.sh
  platform_head="$(git -C "$platform_dir" rev-parse --short HEAD)" \
    || { echo "production: git cannot read the AI Platform checkout $platform_dir (PLATFORM_DIR)" >&2; exit 1; }
  if [ "$platform_head" != "$platform" ]; then
    echo "production gates the fork at $platform, but the AI Platform checkout $platform_dir is at $platform_head: check out $platform there first" >&2
    exit 1
  fi
  platform_dirty="$(git -C "$platform_dir" status --porcelain)" \
    || { echo "production: git status failed in $platform_dir" >&2; exit 1; }
  if [ -n "$platform_dirty" ]; then
    echo "production gates only the committed fork: the AI Platform checkout $platform_dir has these changes (git status --porcelain):" >&2
    printf '%s\n' "$platform_dirty" >&2
    exit 1
  fi
  export PLATFORM_DIR="$platform_dir"  # the fork gate (deploy/dev/platform.sh) mounts the checkout checked here
fi

env_lines="$(docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$prefix/platform:$platform")" \
  || { echo "no image $prefix/platform:$platform: build it with deploy/release/build-platform.sh" >&2; exit 1; }
if [ "$mode" = production ]; then
  # build-platform.sh tags <sha> and bakes BUILD_COMMIT=<sha> from the committed archive; a hand-built image need not.
  commit="$(printf '%s\n' "$env_lines" | sed -n 's/^BUILD_COMMIT=//p')"
  if [ "$commit" != "$platform" ]; then
    echo "production builds only on a platform image from build-platform.sh: $prefix/platform:$platform carries BUILD_COMMIT=${commit:-(none)}, not $platform" >&2
    exit 1
  fi
fi

# The checks live in tools/gates.sh, which also builds $prefix/skill-tools.
gates=(checks)
if [ "$mode" = production ]; then gates=(--release checks skills plan legal-search eval node fork); fi
bash "$harness/tools/gates.sh" "${gates[@]}"

mkdir -p "$builds"
stage="$builds/$tag-$(date +%Y%m%d%H%M%S)"
mkdir "$stage"

mounts=(-v "$(winpath "$harness"):/w:ro" -v "$(winpath "$stage"):/out")
args=(skill-stage --content /w/content --out /out --tag "$tag" --platform "$platform")
for i in "${!extras[@]}"; do
  mounts+=(-v "$(winpath "${extras[$i]}"):/extra/$i:ro"); args+=(--extra "/extra/$i")
done
if [ "$mode" = production ]; then
  mounts+=(-v "$(winpath "$harness/content/skills"):/record"); args+=(--record /record/RELEASED.json)
fi
MSYS_NO_PATHCONV=1 docker run --rm "${mounts[@]}" "$prefix/skill-tools" "${args[@]}"

build=(-q -f "$here/Dockerfile" --build-arg PLATFORM="$platform" --build-arg PLATFORM_REPO="$prefix/platform" -t "$prefix/release:$tag")
if [ "$mode" = production ]; then build+=(--label "org.iqraa.harness-commit=$harness_commit"); fi
docker build "${build[@]}" "$stage" >/dev/null
echo "built $prefix/release:$tag ($mode) from $prefix/platform:$platform (stage: $stage)"
