#!/usr/bin/env bash
# Run a command inside the Platform (LibreChat fork) dev container.
#   deploy/dev/platform.sh 'npm ci'
#   deploy/dev/platform.sh 'cd packages/api && npx jest src/iqraa'
# The repository is bind-mounted at /work; every workspace's node_modules lives in a Docker volume so
# installs stay inside the Docker VM (fast, and out of reach of host file scanners).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here/../../Platform"
if platform="$(pwd -W 2>/dev/null)"; then :; else platform="$(pwd)"; fi  # Windows path under Git Bash, POSIX elsewhere
cd - >/dev/null
image="node:24-bookworm"

volumes=()
for ws in . api client packages/api packages/client packages/data-provider packages/data-schemas; do
  name="iqraa-nm-$(echo "$ws" | tr '/.' '--' | sed 's/^-*//;s/-*$//')"
  [ "$name" = "iqraa-nm-" ] && name="iqraa-nm-root"
  volumes+=(-v "${name}:/work/${ws}/node_modules")
done

MSYS_NO_PATHCONV=1 docker run --rm -i \
  -v "${platform}:/work" \
  "${volumes[@]}" \
  -v iqraa-npm-cache:/root/.npm \
  -v iqraa-mongo-binaries:/root/.cache/mongodb-binaries \
  -w /work \
  -e CI=true \
  "$image" bash -lc "$*"
