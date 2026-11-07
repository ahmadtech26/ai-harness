#!/usr/bin/env bash
# Run the Harness gates, one step after another, and stop at the first that fails.
#   tools/gates.sh [--list] [--release] [step ...]
# --list     print the steps in their default order and run nothing
# --release  the production checks: skill-ci, corpus-ci and the starter prompts must be approved
# With no step named every step runs, in the order --list prints; named steps run in the order given.
# Env: IQRAA_IMAGE_PREFIX (default iqraa), IQRAA_GATES_PROJECT (default release-gates; the compose projects are
# <it>-tests and <it>-eval), PLATFORM_DIR (the AI Platform checkout for the fork step; read by deploy/dev/platform.sh).
# Prints "== <step>" before each step and "PASS <step>" after it; the first failure prints "FAIL <step>" and exits 1.
# An unknown step or option exits 2 before anything runs.
set -euo pipefail

steps_all=(checks skills plan legal-search eval node docker fork)
usage="usage: $0 [--list] [--release] [step ...]   steps: ${steps_all[*]}"

list=0; release=0; steps=()
for arg in "$@"; do
  case "$arg" in
    --list) list=1 ;;
    --release) release=1 ;;
    -h|--help) echo "$usage"; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; echo "$usage" >&2; exit 2 ;;
    *)
      case " ${steps_all[*]} " in
        *" $arg "*) steps+=("$arg") ;;
        *) echo "unknown step: $arg" >&2; echo "$usage" >&2; exit 2 ;;
      esac ;;
  esac
done
if [ "$list" = 1 ]; then printf '%s\n' "${steps_all[@]}"; exit 0; fi
[ ${#steps[@]} -gt 0 ] || steps=("${steps_all[@]}")

prefix="${IQRAA_IMAGE_PREFIX:-iqraa}"
project="${IQRAA_GATES_PROJECT:-release-gates}"
unset IQRAA_EVAL_OUT  # the eval step names its own folder; no other step may see one
cd "$(dirname "$0")/.."  # the Harness root: every path below is relative to it
winpath() { (cd "$1" && (pwd -W 2>/dev/null || pwd)); }

# A step function returns non-zero at its first failing command. They are called inside `if`, where bash ignores
# set -e, so every command that can fail carries its own `|| return`.

# The checks that used to live in deploy/release/build.sh: skill CI, corpus CI, the tiers, the reviewed starter prompts
# and the guard's law names.
step_checks() {
  local whole
  whole="$(winpath .)" || return
  local ci=(skill-ci --content /w/content)
  local corpus_ci=(corpus-ci --content /w/content --corpus "/w/jordanian-law/references/القوانين-الأردنية")
  local starters=(content/starters.mjs check content/starters/starters.ar.json)
  if [ "$release" = 1 ]; then ci+=(--release); corpus_ci+=(--release); starters+=(--release); fi
  docker build -q -t "$prefix/skill-tools" tools/skills >/dev/null || return
  MSYS_NO_PATHCONV=1 docker run --rm -v "$whole:/w:ro" "$prefix/skill-tools" "${ci[@]}" || return
  MSYS_NO_PATHCONV=1 docker run --rm -v "$whole:/w:ro" "$prefix/skill-tools" "${corpus_ci[@]}" || return
  node content/tiers.mjs check || return
  node "${starters[@]}" || return
  node content/grounding-laws.mjs check
}

# The skill tools' own pytest suite, in the image's test stage.
step_skills() {
  docker build -q --target test -t "$prefix/skill-tools-test" tools/skills >/dev/null || return
  MSYS_NO_PATHCONV=1 docker run --rm "$prefix/skill-tools-test" pytest -q
}

step_plan() {
  local plan
  plan="$(winpath tools/plan)" || return  # a missing folder fails here, before docker could mount an empty path
  MSYS_NO_PATHCONV=1 docker run --rm -v "$plan:/p:ro" -w /p \
    python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 \
    python -B -m unittest test_plan_tools
}

# The legal-search suite on its own database, which is removed afterwards whether the suite passed or not.
search() { MSYS_NO_PATHCONV=1 docker compose -p "$project-tests" -f services/legal-search/compose.test.yaml "$@"; }
step_legal_search() {
  local rc=0
  search run --rm --build tests || rc=1
  search down -v || rc=1
  return "$rc"
}

# The retrieval evaluation against the committed baseline (tools/release_eval.py), with its evidence in a new folder
# (deploy/release/compose.eval.yaml mounts IQRAA_EVAL_OUT at /evidence). The database goes afterwards in any case.
evaluate() {
  MSYS_NO_PATHCONV=1 IQRAA_EVAL_OUT="$out" docker compose -p "$project-eval" \
    -f services/legal-search/compose.test.yaml -f deploy/release/compose.eval.yaml "$@"
}
step_eval() {
  local out tools baseline rc=0
  out="$(mktemp -d)" || return
  out="$(winpath "$out")" || return
  tools="$(winpath tools)" || return
  baseline="$(winpath deploy/release)" || return
  echo "eval evidence: $out"
  evaluate run --rm --build eval check \
    && evaluate run --rm --build eval run --label release --reset \
    && evaluate run --rm --entrypoint python -v "$tools:/tools:ro" -v "$baseline:/baseline:ro" eval \
      /tools/release_eval.py check --report /evidence/eval-release.json --baseline /baseline/eval-baseline.json \
    && evaluate run --rm --entrypoint python -v "$tools:/tools:ro" -w /tools eval -B -m unittest test_release_eval \
    || rc=1
  evaluate down -v || rc=1
  return "$rc"
}

# node --test over the given glob patterns (quoted by the caller, expanded here): a pattern with no match is dropped,
# and no match at all fails rather than letting a bare `node --test` run whatever it discovers. Leading arguments that
# start with -- are node's own options, passed before the files.
node_tests() {
  local pattern files=() options=()
  while [ $# -gt 0 ] && [[ "$1" == --* ]]; do options+=("$1"); shift; done
  shopt -s nullglob
  for pattern in "$@"; do files+=($pattern); done
  shopt -u nullglob
  [ ${#files[@]} -gt 0 ] || { echo "no test files match: $*" >&2; return 1; }
  node --test ${options[@]+"${options[@]}"} "${files[@]}"
}
step_node() { node_tests 'content/*.test.mjs' 'deploy/staging/*.test.mjs' 'deploy/release/*.test.mjs' 'deploy/*.test.mjs' 'tools/*.test.mjs'; }
# One file at a time: each boots one or more whole compose projects, each with its own network, and run together they
# exhaust Docker's address pools ("all predefined address pools have been fully subnetted").
step_docker() { node_tests --test-concurrency=1 'deploy/staging/docker-tests/*.test.mjs'; }

# The fork's own suites and types, in the dev container.
step_fork() {
  bash deploy/dev/platform.sh 'cd packages/api && npx jest src/iqraa && npx tsc --noEmit' || return
  bash deploy/dev/platform.sh 'cd client && npx jest src/iqraa'
}

for step in "${steps[@]}"; do
  echo "== $step"
  if "step_${step//-/_}"; then
    echo "PASS $step"
  else
    echo "FAIL $step"
    exit 1
  fi
done
