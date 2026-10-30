# Staging stack (Phase 1)

A local, production-shaped stack for the Phase 1 acceptance scenarios (1, 4, 8, 9, 10, 11 in
`.hq/docs/audits/librechat-platform/I-upstream-and-tests.md` I.4). No provider keys: a mock model
answers every call and logs it, so "did anything reach the provider" is an observable fact.

| Service | What it is |
|---|---|
| `proxy` | nginx, the only published port (`127.0.0.1:3080`); adds the narrow content-security policy |
| `librechat` | a release image `iqraa/release:staging` (fork image + content skills, `deploy/release/build.sh`) |
| `mongo` | MongoDB replica set (the ledger needs transactions) |
| `postgres`, `legal-search`, `legal-search-ingest` | the legal library: the 22 laws of `content/corpus/laws.json` (corrections in `corrections.json`) and the Civil Code memorandum, MCP tools `search_law` / `get_article` / `get_memorandum` |
| `mock-llm` | OpenAI-compatible mock; every request goes to `out/llm-requests.jsonl` |
| `secrets-init` | generates JWT, credential, MCP, database and sign-in (`iqraa_auth`, `iqraa_staging`) secrets into a volume |

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

The driver creates fresh accounts on every run (by phone, codes read from the sink; the staff account is made with the staff bootstrap runner, see «Sign-in on staging»), releases the «عقل» specialist with `content/release.mjs` onto
the mock model, and on staging only lists one extra skill (`staging-listed`) on it so scenario 1 can
load a skill on demand. It writes `out/scenarios-report.json`.

`out/` is git-ignored: the model log holds full prompts, including the AQEL instructions and skill bodies.

## Sign-in on staging (passwordless)

No passwords exist: `/api/auth/login`, `/register`, `/requestPasswordReset`, `/resetPassword`,
`/2fa/verify-temp` and `/api/admin/login/local` answer 403 `IQRAA_PASSWORDS_OFF`, and the fork refuses to start
unless `compose.yaml` sets the six `ALLOW_*` switches to `false`. Accounts sign up with a phone and a WhatsApp
code, add an email later (bound only after its code), and sign in with a phone or email plus a delivered code,
an authenticator-app code or a backup code. Staff (ADMIN) sign in with an app or backup code only.

- **The sink.** `iqraa.json` `auth.delivery: "sink"`: codes are not sent; each one is a row in the MongoDB
  collection `iqraa_auth_sink` (`to`, `channel`, `purpose`, `code`, 10-minute expiry). The fork starts with the
  sink only where `/secrets/iqraa_staging` exists (made by `secrets-init`; production has none). The driver
  reads the newest row for an identifier with `mongoQuery` (`lib.mjs` `withSinkCode`, `newestSinkRow`).
- **Secrets.** `secrets-init` adds `iqraa_auth` (64 hex characters, the code and audit keys, exported by the
  LibreChat entrypoint as `IQRAA_AUTH_SECRET`) and `iqraa_staging`. An existing volume gets them the next time
  `secrets-init` runs: `docker compose run --rm -T --no-deps secrets-init` (a `--no-deps` recreate of librechat skips it).
- **Limits.** `iqraa.json` `auth.limits` are raised for one driver address: a full run makes about 40 code
  requests and 43 verifications, and a busy hour (an `auth` run, the full run, a rerun, the RTL check and the
  drills) about 102 and 118, so 300 requests and 400 verifications per IP per hour, 10 requests per identifier
  per 15 minutes and 30 per day (the drills customer takes 5). Production keeps the fork defaults (3, 10, 20, 60).
- **The driver.** `lib.mjs` `customer()` signs up by phone (`+96279` and 7 digits, checked free in
  `iqraa_identities`) and signs in again by WhatsApp code after the plan membership. App codes are RFC 6238
  (`totp.cjs`, `node --test totp.test.mjs`); a code's 30 s step is accepted once, so a second app sign-in waits
  for the next step. `SCENARIOS=auth node scenarios.mjs` runs the sign-in acceptance alone.
- **RTL check.** `ui/run-rtl-check.mjs` signs a phone-only customer in on the code screens with an app code and
  then a backup code (the browser container cannot read the sink), and checks the account menu shows the phone,
  never the `@phone.iqraa.invalid` placeholder.
- **Real WhatsApp.** Not exercised here. One real code to a real phone waits for Meta's approval of the Arabic
  authentication template (spec «Acceptance → Manual»).

### Staff bootstrap (operators)

The first staff account, and every staff account the driver makes, comes from the runner
`config/iqraa-bootstrap-staff.js` in the LibreChat image. It runs inside the container and reads its secrets
there. From this folder (Git Bash; `MSYS_NO_PATHCONV` keeps the container paths as typed):

```bash
export MSYS_NO_PATHCONV=1
RUNNER='export IQRAA_AUTH_SECRET=$(cat /secrets/iqraa_auth) CREDS_KEY=$(cat /secrets/creds_key) CREDS_IV=$(cat /secrets/creds_iv) && exec node /app/config/iqraa-bootstrap-staff.js "$@"'
PHONE=+9627XXXXXXXX   # the staff member's WhatsApp number, E.164
docker compose exec -T librechat sh -c "$RUNNER" runner request --phone "$PHONE"           # {"sent":true}
node --input-type=module -e "import { newestSinkRow } from './lib.mjs'; console.log(newestSinkRow('$PHONE', 'signup')?.code)"   # staging: the code from the sink
docker compose exec -T librechat sh -c "$RUNNER" runner enrol --phone "$PHONE" --name 'الاسم' --code <code>
# prints {"userId","otpauthUrl","backupCodes"} once: add the otpauth URL to the authenticator app, keep the backup codes offline
docker compose exec -T librechat sh -c "$RUNNER" runner promote --phone "$PHONE" --app-code <current app code>   # {"userId","role":"ADMIN"}
docker compose exec -T librechat sh -c "$RUNNER" runner unlock --phone "$PHONE"   # {"unlocked":true,"account":true}: support clears a lock (--email <email> works too)
```

Ten wrong codes lock an identifier for 15 minutes, a later lock for 1 hour, every further one for 24 hours;
a staff account's third and later locks have no end, and every staff lock writes an `ALERT auth_staff_locked`
line in the LibreChat log. `unlock --phone <phone>` (or `--email <email>`) clears the lock and the failed
attempts of that identifier and of its account, a manual staff lock included, and works for a phone nobody
has signed up with too (strangers can lock one). The driver never uses it.

On production the code arrives by WhatsApp instead of the sink. `promote` assigns the role through the same
check as `POST /api/admin/roles/:name/members` (hook L5), which refuses a staff role to an account without the
app. `content/release.mjs` then signs in with `IQRAA_STAFF_IDENTIFIER` and a current `IQRAA_STAFF_APP_CODE`
(or takes a session token in `IQRAA_STAFF_TOKEN`, as the driver passes it).

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

## Library guard (Phase 3)

legal-search decides every library call with the sweep guard (detector, flags, throttle, suspension).
Staff use the fork's `/api/iqraa/admin/library/*` routes (a proxy of legal-search's `/admin` API behind
the shared secret: `flags`, `flags/:userId/clear`, `guard-settings`, `guard-settings/history`,
`guard-settings/simulate`, `telemetry`) and `/api/iqraa/admin/accounts/:userId/suspend` / `unsuspend`.
`iqraa.json` names the API (`legalSearch.url`); LibreChat already has `LEGAL_SEARCH_SECRET`.

- `SCENARIOS=guard node scenarios.mjs` runs the scripted sweep (articles 1–40 of the Penal Code: suspected
  at 12, proven at 24) and the staff checks. It calls the MCP endpoint from inside the legal-search
  container (`scripts/mcp-calls.py` piped to `python3 -I -`; the script reads the secret there), because
  legal-search is not published to the host.
- Alerts are JSON lines at error level in `docker compose logs legal-search`: `sweep_flag_opened`,
  `sweep_flag_escalated`, `sweep_refused`.
- The reconciliation step prints `open sweep flags: suspected N, proven M` from the staff `flags` route.
- Guard settings live in legal-search's database and survive restarts. The scenario changes
  `max_results` and puts it back, so each run adds two rows to the settings history.

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
docker compose -f compose.yaml -f compose.summary.yaml up -d --no-deps --force-recreate librechat   # wait for /readyz 200
SCENARIOS=3 node scenarios.mjs     # narrows the specialist's window to S3_MAX_CONTEXT_TOKENS (default 9000)
docker compose up -d --no-deps --force-recreate librechat                                           # back to normal staging
SCENARIOS=2 node scenarios.mjs     # re-releases the specialist with its normal window
```

`--force-recreate` matters: compose does not recreate a container when only a mounted file changed.
The release folds always-apply skills into the specialist's instructions (`content/compose.mjs`), so
scenario 3 also checks the pinned method rides in the system prompt exactly once.
