# Staging stack (Phase 1)

A local, production-shaped stack for the Phase 1 acceptance scenarios (1, 4, 8, 9, 10, 11 in
`.hq/docs/audits/librechat-platform/I-upstream-and-tests.md` I.4). No provider keys: a mock model
answers every call and logs it, so "did anything reach the provider" is an observable fact.

| Service | What it is |
|---|---|
| `proxy` | nginx, the only published port (`127.0.0.1:3080`); adds the narrow content-security policy |
| `librechat` | a release image `iqraa/release:staging` (fork image + content skills, `deploy/release/build.sh`) |
| `mongo` | MongoDB replica set (the ledger needs transactions) |
| `postgres`, `legal-search`, `legal-search-ingest` | the legal library: Civil Code articles, MCP tools `search_law` / `get_article` |
| `mock-llm` | OpenAI-compatible mock; every request goes to `out/llm-requests.jsonl` |
| `secrets-init` | generates JWT, credential, MCP and database secrets into a volume on first start |

## Run

```bash
# 1. Build the fork image from the committed tree (not the working copy) with upstream's Dockerfile.multi
cd "../../../AI Platform"
SHA=$(git rev-parse --short HEAD)
DIR="../.hq/scratch/platform-build/$SHA"; mkdir -p "$DIR"
git -c core.autocrlf=false archive --format=tar HEAD | tar -x -C "$DIR"
docker build -f "$DIR/Dockerfile.multi" --target api-build \
  -t "iqraa/platform:$SHA" -t iqraa/platform:phase1 \
  --build-arg BUILD_COMMIT="$SHA" --build-arg BUILD_BRANCH=main "$DIR"

# 1b. Build the staging release (skill CI, then fork image + content skills)
cd "/d/Iqraa Law/AI Harness"
deploy/release/build.sh staging "$SHA" --allow-draft

# 2. Start the stack and run the scenarios
cd "../AI Harness/deploy/staging"
docker compose up -d --build
node scenarios.mjs            # exit 0 = all scenarios, proxy checks and reconciliation pass
```

The driver creates fresh accounts on every run (throwaway passwords, held in memory only; the staff
account is promoted through `mongosh`), releases the «عقل» specialist with `content/release.mjs` onto
the mock model, and on staging only lists one extra skill (`staging-listed`) on it so scenario 1 can
load a skill on demand. It writes `out/scenarios-report.json`.

`out/` is git-ignored: the model log holds full prompts, including the AQEL instructions and skill bodies.

## Reconciliation

`scripts/reconcile.js` is the daily ledger reconciliation (read-only):

```bash
docker compose exec -T mongo mongosh LibreChat --quiet --file /scripts/reconcile.js
```

It checks that every transaction and the whole book sum to zero, that wallets equal their postings and
their open reservations, that every settled reservation has exactly one usage event with the same
amount (and nothing else does), that no hold outlives its expiry, and that each reservation's postings
match its status. It summarises the window's spend and flags settlements made at the estimate because
the provider reported no usage. It exits 1 when an invariant fails.

Why `Dockerfile.multi`: on this Docker Desktop (WSL2 kernel 6.18), the main `Dockerfile`'s
`npm prune --production` deadlocked twice in the kernel (npm's worker threads stuck in `rename` and an
ext4 journal wait). `Dockerfile.multi` installs production dependencies fresh (`npm ci --omit=dev`) and
never prunes. Its image runs as root from `/app/api`; production should build as the `node` user.

## Staging-only settings

- `LIMIT_MESSAGE_USER=true`, `MESSAGE_USER_MAX=30` per minute: scenario 11 bursts past it.
- The concurrent-message limiter is left off, so scenario 8's parallel chats are bounded by the credit
  ledger alone. Production should turn it on as well.
- `test-skills/` holds two marker skills used only by scenario 1.
- Content-security policy: LibreChat's own nonce policy for scripts (`CSP_ENABLED`, enforcing) plus the
  proxy's policy narrowing `img-src`, `connect-src`, `frame-src` and `frame-ancestors` (G-security T7).

## Release drills (scenarios 5 and 14)

Run `node scenarios.mjs` once first (it creates the `PLAN_PRO` role and the «عقل» specialist), then:

```bash
cd "/d/Iqraa Law/AI Harness"
PLATFORM=$(docker image inspect iqraa/platform:phase1 --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^BUILD_COMMIT=//p')
S=deploy/staging/drill-skills
deploy/release/build.sh drill-r1 "$PLATFORM" --allow-draft --extra $S/r1 --extra $S/listed
deploy/release/build.sh drill-r2 "$PLATFORM" --allow-draft --extra $S/r2 --extra $S/listed
deploy/release/build.sh drill-r3 "$PLATFORM" --allow-draft --extra $S/r2
cd deploy/staging && node drills.mjs
```

The drill swaps LibreChat between the three releases (each restart takes a minute or two), creates a
drill specialist, rolls back image and specialist, and removes a skill; it restores
`iqraa/release:staging` at the end, even on failure.

## Scenario 3 (pinned skill through summarisation)

Summarisation is off in normal staging (summary calls would change other scenarios' call counts). Run it alone:

```bash
cd "/d/Iqraa Law/AI Harness/deploy/staging"
cat librechat.yaml summary-overlay.yaml > out/librechat.summary.yaml
docker compose -f compose.yaml -f compose.summary.yaml up -d --no-deps librechat   # wait for /readyz 200
SCENARIOS=3 node scenarios.mjs
docker compose up -d --no-deps librechat                                           # back to normal staging
```
