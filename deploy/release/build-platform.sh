#!/usr/bin/env bash
# Build the platform image (the LibreChat fork) from the committed tree of the AI Platform checkout.
#   deploy/release/build-platform.sh [--rollback-tag <name>]
# --rollback-tag  first keep the current $prefix/platform:phase1 as $prefix/platform:<name>, the image to roll back to.
#                 An existing <name> is never tagged again, so a re-run cannot overwrite the rollback target with the new build.
# PLATFORM_DIR        the AI Platform checkout (default: the sibling of this Harness)
# IQRAA_IMAGE_PREFIX  image name prefix (default: iqraa)
# IQRAA_BUILD_DIR     where the exported tree and the build log go (default: deploy/release/.build)
# Tags $prefix/platform:<short sha> and $prefix/platform:phase1; the log is $IQRAA_BUILD_DIR/build-<sha>.log.
set -euo pipefail

usage() { echo "usage: $0 [--rollback-tag <name>]" >&2; exit 2; }
valid_tag() { [[ "$1" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; }  # Docker's tag grammar

rollback=""
while [ $# -gt 0 ]; do
  case "$1" in
    --rollback-tag)
      [ $# -ge 2 ] && valid_tag "$2" || usage
      rollback=$2; shift 2 ;;
    *) usage ;;
  esac
done

here="$(cd "$(dirname "$0")" && pwd)"
harness="$(cd "$here/../.." && pwd)"
platform_dir="${PLATFORM_DIR:-$harness/../AI Platform}"  # sibling repository
prefix="${IQRAA_IMAGE_PREFIX:-iqraa}"
builds="${IQRAA_BUILD_DIR:-$here/.build}"

sha="$(git -C "$platform_dir" rev-parse --short HEAD)"
branch="$(git -C "$platform_dir" rev-parse --abbrev-ref HEAD)"

if [ -n "$rollback" ]; then
  # The build itself moves phase1 and the sha tag, so neither can hold the rollback target.
  if [ "$rollback" = phase1 ] || [ "$rollback" = "$sha" ]; then
    echo "--rollback-tag $rollback: the build retags $prefix/platform:$rollback, so it cannot be the rollback target" >&2
    exit 2
  fi
  # Guarded: a re-run must never overwrite the rollback target with the new build.
  if docker image inspect "$prefix/platform:$rollback" >/dev/null 2>&1; then
    echo "kept $prefix/platform:$rollback as it is"
  else
    docker image tag "$prefix/platform:phase1" "$prefix/platform:$rollback"
    echo "tagged $prefix/platform:phase1 as $prefix/platform:$rollback"
  fi
fi

dir="$builds/$sha"
log="$builds/build-$sha.log"
mkdir -p "$dir"
if [ -n "$(ls -A "$dir")" ]; then
  echo "build dir $dir is not empty: use it as is or remove it by hand" >&2
  exit 1
fi

# The committed tree only, with LF endings whatever the checkout's autocrlf says.
git -C "$platform_dir" -c core.autocrlf=false archive --format=tar HEAD | tar -x -C "$dir"

echo "building $prefix/platform:$sha (branch $branch), log: $log"
status=0
docker build --progress=plain -f "$dir/Dockerfile.multi" --target api-build \
  -t "$prefix/platform:$sha" -t "$prefix/platform:phase1" \
  --build-arg BUILD_COMMIT="$sha" --build-arg BUILD_BRANCH="$branch" \
  "$dir" >"$log" 2>&1 || status=$?
echo "docker build exit=$status" | tee -a "$log"
exit "$status"
