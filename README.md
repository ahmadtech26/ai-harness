# AI Harness

Iqraa Law is a law-only Arabic legal assistant for Jordanian law, built on a fork of LibreChat. The work is split
across two repositories that are checked out side by side:

- **AI Platform**: the LibreChat v0.8.8 fork, the application itself. Its own code lives in `packages/api/src/iqraa`
  and `client/src/iqraa`.
- **AI Harness** (this repository): everything around the application. The content that ships in it (the AQEL prompt,
  skills, tiers, starter prompts, the law registry), the Jordanian law library, the `legal-search` service that serves
  that library, the local staging stack, and the gates and build scripts that turn both repositories into a release.

The scripts expect the fork in a folder named `AI Platform` next to this one. Set `PLATFORM_DIR` to point them
somewhere else.

## What is where

| Folder | What it holds |
|---|---|
| `content` | What ships in a release: the AQEL prompt (`prompts/`), the specialist (`specialists/aqel.json`), the customer tiers (`tiers.json`), plan roles (`roles.json`), reviewed starter prompts (`starters/`), the content skills (`skills/`), the law registry, aliases and corrections (`corpus/`), the retrieval evaluation set (`eval/`), and the Node scripts that check and release them (`release.mjs`, `tiers.mjs`, `starters.mjs`, `grounding-laws.mjs`). |
| `deploy/dev` | `platform.sh`: runs a command in the AI Platform dev container: through the checkout's own `tools/dev.sh run` when it has one (AI Platform since the split), else in a LibreChat checkout inside a pinned Node container, with each workspace's `node_modules` in a Docker volume and `/tmp` on a RAM disk. |
| `deploy/release` | Release builds: `build-platform.sh` (the fork image), `build.sh` (the release image), the release `Dockerfile`, the retrieval baseline `eval-baseline.json` and the eval overlay `compose.eval.yaml`. |
| `deploy/staging` | The local, production-shaped staging stack (`compose.yaml`) and its acceptance driver (`scenarios.mjs`), drills, mock model and Docker tests. See `deploy/staging/README.md`. |
| `jordanian-law` | The law library as a skill (`SKILL.md`): 22 Jordanian laws verbatim with the Civil Code explanatory memorandum (`references/القوانين-الأردنية`), and practitioner commentary that is context, not authority (`references/docs`). |
| `services/legal-search` | The library service: an MCP server (`search_law`, `get_article`, `get_memorandum`) over Postgres with Arabic full-text search, the ingest that loads the registry with its corrections, the retrieval evaluation, and the sweep guard with its caps and retrieval log. |
| `tools/skills` | The skill tools image: `skill-ci` (checks the content skills), `corpus-ci` (checks the law registry, corrections and verification records against the library) and `skill-stage` (copies a release's skills into a build folder). |
| `tools/verification` | The verification pass's tools: `v1.py` (normalisation `v1`) and `dump_texts.py` (the stored texts, from `recall-plan`'s `legal_search`). See `content/corpus/verification/README.md`. |
| `tools/plan` | The implementation-plan generator: `mkplan.py` renders plan chunks, `assemble.py` joins them, `pin_pristine.py` pins the "before" files to the plan's base commits. |

Also at the top of `tools/`: `gates.sh` (below) and `release_eval.py`, the retrieval gate that compares a run with
`deploy/release/eval-baseline.json`. `deploy/pins.test.mjs` checks that every image the Harness builds from or runs is
pinned by digest.

## Run the gates

Run the scripts from bash (Git Bash on Windows) at the repository root:

```bash
tools/gates.sh                      # every step, in order, stopping at the first failure
tools/gates.sh --list               # print the steps and run nothing
tools/gates.sh node checks          # only the named steps, in the order given
tools/gates.sh --release            # the production checks: drafts are refused (see «Rules»)
```

Each step prints `== <step>`, then `PASS <step>` or `FAIL <step>`. The steps, in their default order:

| Step | What it runs | Needs |
|---|---|---|
| `checks` | `skill-ci` and `corpus-ci` in the `tools/skills` image, then `content/tiers.mjs check`, `content/starters.mjs check` and `content/grounding-laws.mjs check` | Docker, Node |
| `skills` | the skill tools' own pytest suite (the image's `test` stage) | Docker |
| `plan` | the plan tools' unit tests in a pinned `python:3.12-slim` container | Docker |
| `legal-search` | the service's pytest suite against its own Postgres (`services/legal-search/compose.test.yaml`); the project and its volumes are removed afterwards | Docker Compose |
| `eval` | the retrieval evaluation and `tools/release_eval.py check` against the committed baseline; it prints the temporary folder that holds the evidence | Docker Compose |
| `node` | `node --test` over the test files in `content`, `deploy`, `deploy/staging`, `deploy/release` and `tools` | Node; the Docker CLI, for `deploy/staging/compose.contract.test.mjs`, which runs `docker compose config` (it starts nothing) |
| `docker` | `deploy/staging/docker-tests`, one file at a time (`--test-concurrency=1`): each file boots whole compose projects, and run together they exhaust Docker's network address pools. The tests run under their own `hardening-*` names, build a throwaway `hardening-test/` image on the current `iqraa/platform:phase1` where they need one, rebuild `hardening-test/legal-search:isolated` from `services/legal-search` every run, never use port 3080, the client previews' 3091-3097 or the staging project, and remove what they made, volumes included | Docker, Node; `iqraa/platform:phase1` for the tests that build a release image |
| `fork` | the fork's `src/iqraa` Jest suites and `tsc --noEmit` in `packages/api`, then the `client` suites, through `deploy/dev/platform.sh` | Docker, the AI Platform checkout (`PLATFORM_DIR`) |

Python never runs on the host, with two exceptions: the skill tools, `legal-search`, the plan tools' tests and the eval
gate all run in containers, as the steps above do. The first exception is `tools/plan/pin_pristine.py`, which reads the
plan's base commits with `git show` from the checkouts themselves; the pinned `python:3.12-slim` image has no git, so it
runs on the host, where git and both checkouts are (`python3 -I tools/plan/pin_pristine.py --build <folder> --repo
fork=<path>@<sha> --repo harness=<path>@<sha>`). It only reads the repositories. The second is the verification pass's
tools (`tools/verification`), run by hand (`content/corpus/verification/README.md`); the `skills` step's image does not
hold them and skips their test, which `uv run pytest -q` in `tools/skills` runs. Node runs on the host for the `.mjs`
scripts and tests.

The `fork` step keeps the fork's `node_modules` in Docker volumes. On a new machine, install them once with
`deploy/dev/platform.sh 'npm ci'` before the first run.

Since the 2026-11-07 split AI Platform holds only our work, so when `PLATFORM_DIR` has `tools/dev.sh`, `platform.sh`
runs its `assemble` and then hands the command to its `run`: `.assembled`, the tree `tools/dev.sh assemble` keeps, is
first brought in step with the AI Platform working tree, and the command runs on it in the same pinned container, with
that tree's own `iqraa-ap-nm-*` volumes. So the `fork` step tests the working tree as it is, never the tree as it was
last assembled, and an assemble that fails fails the step. `deploy/dev/platform.sh 'npm ci'` (an assemble, then the
same as `tools/dev.sh install`) installs into it. A `PLATFORM_DIR` without `tools/dev.sh` is a LibreChat checkout and
runs as before.

Settings: `IQRAA_IMAGE_PREFIX` (default `iqraa`) names the images, `IQRAA_GATES_PROJECT` (default `release-gates`)
names the compose projects of the `legal-search` and `eval` steps, and `PLATFORM_DIR` names the fork checkout.

## Build a release

Two scripts, in this order:

1. `deploy/release/build-platform.sh [--rollback-tag <name>]` builds the fork image from the **committed** tree of
   the AI Platform checkout (uncommitted changes are not in it) and tags it `iqraa/platform:<short sha>` and
   `iqraa/platform:phase1`. `--rollback-tag` first keeps the current `phase1` under that name and never overwrites
   an existing one.
2. `deploy/release/build.sh <tag> <platform-sha> (--allow-draft | --production) [--extra <dir>]...` builds
   `iqraa/release:<tag>`: the platform image plus the content skills, run as the unprivileged `node` user. Exactly
   one mode:
   - `--allow-draft`, for staging and drills: runs `tools/gates.sh checks` and accepts content that is still draft.
     It makes no git call, records nothing and adds no label. `--extra <dir>` adds drill or test skill folders to
     that image only.
   - `--production`: the Harness must be committed (`git status --porcelain` empty), the AI Platform checkout
     (`PLATFORM_DIR`) must be at `<platform-sha>` with nothing uncommitted, because the `fork` gate runs its suites
     on that working tree (since the split, on the `.assembled` tree `platform.sh` assembles from it before each run,
     which a clean checkout makes the committed state), and
     the platform image must carry `BUILD_COMMIT=<platform-sha>`, which only `build-platform.sh` guarantees. It then
     runs `tools/gates.sh --release` with every step but `docker`, writes the released skill versions to
     `content/skills/RELEASED.json` and labels the image with the Harness commit.
     `--extra` is refused.

   Two things leave the Harness uncommitted around a production build. The staging driver writes the tier agent ids
   into the tracked `deploy/staging/iqraa.json` and `deploy/staging/librechat.yaml` on every run (`content/tiers.mjs
   apply`), so a checkout that runs staging refuses `--production` until those two files are restored to their
   committed form, or the build runs from a clean checkout. And the build itself writes `content/skills/RELEASED.json`:
   commit it, as the record of what the release ships, before the next production build, which would refuse it.

Build output (exported trees, logs, stage folders) goes to `deploy/release/.build`, which git ignores. `build.sh`
does not run the acceptance scenarios: they need the image running on the staging stack, which is the next step.

## Staging

How to start the staging stack, sign in, and run the scenarios and drills is in `deploy/staging/README.md`.

## Rules a newcomer must know

- **No secrets in files.** The stack's secrets (JWT, credential, database, MCP and sign-in keys) are generated by
  the `secrets-init` service into a Docker volume on first start. Do not write a secret into a file in this
  repository, and never commit an `.env` file (git ignores `.env` and `.env.*`).
- **The citation guard stays in shadow mode in production.** Its setting is `grounding.mode` in the fork's
  `iqraa.json` configuration (on staging, `deploy/staging/iqraa.json`), and it is `shadow`: an ungrounded answer is
  logged, not replaced. Moving to `block` is the owner's decision, not a configuration change to make on your own.
- **Content approvals belong to the owner and a lawyer.** The skills, the law registry entries, the corrections, the
  starter prompts and the evaluation set each carry a review status, and all are `draft` today. Only the owner or
  the reviewing lawyer sets `approved`, with their name and date. Never fill those fields on their behalf.
  Production builds (`--release`, `--production`) refuse a draft skill, registry entry, corrections file or starter
  set, so they fail until that review is done.
- **Law text is not edited.** The statute files under `jordanian-law/references` stay verbatim. A fix to a parsed
  article is an entry in `content/corpus/corrections.json`, with its reason and source, and it stays draft until
  reviewed.
