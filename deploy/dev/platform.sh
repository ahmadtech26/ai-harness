#!/usr/bin/env bash
# Run a command inside the AI Platform dev container.
#   deploy/dev/platform.sh 'npm ci'
#   deploy/dev/platform.sh 'cd packages/api && npx jest src/iqraa'
# PLATFORM_DIR  the AI Platform checkout (default: the sibling of this Harness)
# AI Platform after the 2026-11-07 split is no LibreChat checkout: when PLATFORM_DIR holds tools/dev.sh, `tools/dev.sh
# assemble` first brings its .assembled tree in step with the checkout's working tree, then the command goes to
# `tools/dev.sh run`, which runs it in the same container on that tree. So the command never meets the tree as it was
# last assembled, and a failed assemble is this script's status, with the command not run. Otherwise PLATFORM_DIR is a
# LibreChat checkout (the fork before the split), and the command runs in it as follows.
# /tmp is a RAM disk: the fork suite starts a test MongoDB per suite, whose synced journal writes stall on a spinning
# disk (measured 2026-11-03: 4.5 MB/s, setup timeouts in random suites; on the RAM disk 1.4 GB/s, 600 tests in 17 s).
# The repository is bind-mounted at /work; every workspace's node_modules lives in a Docker volume so
# installs stay inside the Docker VM (fast, and out of reach of host file scanners).
# Exit status: the command's own.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
platform_dir="${PLATFORM_DIR:-$here/../../../AI Platform}"  # sibling repository
if [ -f "$platform_dir/tools/dev.sh" ]; then
  bash "$platform_dir/tools/dev.sh" assemble
  exec bash "$platform_dir/tools/dev.sh" run "$*"
fi
cd "$platform_dir"
if platform="$(pwd -W 2>/dev/null)"; then :; else platform="$(pwd)"; fi  # Windows path under Git Bash, POSIX elsewhere
cd - >/dev/null
image="node:24-bookworm@sha256:6449e19d8184d84062525b6a7524def03146c2cb04a7f08b076680d0e8e4240a"  # pinned (O-57)

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
  --tmpfs /tmp:rw,size=16g,mode=1777 \
  -w /work \
  -e CI=true \
  "$image" bash -lc "$*"
