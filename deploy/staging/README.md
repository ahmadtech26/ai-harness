# Staging stack (Phase 1)

A local, production-shaped stack for the Phase 1 acceptance scenarios (1, 4, 8, 9, 10, 11 in
`.hq/docs/audits/librechat-platform/I-upstream-and-tests.md` I.4). No provider keys: a mock model
answers every call and logs it, so "did anything reach the provider" is an observable fact.

| Service | What it is |
|---|---|
| `proxy` | nginx, the only published port (`127.0.0.1:3080`); adds the narrow content-security policy |
| `librechat` | the fork image `iqraa/platform:phase1`, built from the `AI Platform` repository's committed tree |
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
