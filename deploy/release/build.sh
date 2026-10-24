#!/usr/bin/env bash
# Build a release image: skill CI, then the fork image plus the content skills (and extra skill folders).
#   deploy/release/build.sh <tag> <platform-sha> [--allow-draft] [--record] [--extra <dir>]...
# --allow-draft  staging and drills: skills need not be approved yet
# --record       production: write the released versions to content/skills/RELEASED.json
set -euo pipefail

[ $# -ge 2 ] || { echo "usage: $0 <tag> <platform-sha> [--allow-draft] [--record] [--extra <dir>]..."; exit 2; }
tag=$1; platform=$2; shift 2
allow_draft=0; record=0; extras=()
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-draft) allow_draft=1; shift ;;
    --record) record=1; shift ;;
    --extra) extras+=("$(cd "$2" && pwd)"); shift 2 ;;
    *) echo "unknown argument: $1"; exit 2 ;;
  esac
done

here="$(cd "$(dirname "$0")" && pwd)"
harness="$(cd "$here/../.." && pwd)"
winpath() { (cd "$1" && (pwd -W 2>/dev/null || pwd)); }
docker image inspect "iqraa/platform:$platform" >/dev/null

stage="$harness/../.hq/scratch/release-build/$tag-$(date +%Y%m%d%H%M%S)"
mkdir -p "$stage"

docker build -q -t iqraa/skill-tools "$harness/tools/skills" >/dev/null
ci=(skill-ci --content /w/content)
[ "$allow_draft" = 1 ] || ci+=(--release)
MSYS_NO_PATHCONV=1 docker run --rm -v "$(winpath "$harness"):/w:ro" iqraa/skill-tools "${ci[@]}"

mounts=(-v "$(winpath "$harness"):/w:ro" -v "$(winpath "$stage"):/out")
args=(skill-stage --content /w/content --out /out --tag "$tag" --platform "$platform")
for i in "${!extras[@]}"; do
  mounts+=(-v "$(winpath "${extras[$i]}"):/extra/$i:ro"); args+=(--extra "/extra/$i")
done
if [ "$record" = 1 ]; then
  mounts+=(-v "$(winpath "$harness/content/skills"):/record"); args+=(--record /record/RELEASED.json)
fi
MSYS_NO_PATHCONV=1 docker run --rm "${mounts[@]}" iqraa/skill-tools "${args[@]}"

docker build -q -f "$here/Dockerfile" --build-arg PLATFORM="$platform" -t "iqraa/release:$tag" "$stage" >/dev/null
echo "built iqraa/release:$tag from iqraa/platform:$platform (stage: $stage)"
