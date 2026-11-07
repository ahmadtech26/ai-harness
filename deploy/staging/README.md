# Staging stack

A local, production-shaped stack for the acceptance scenarios: the passwordless fork (sign-in by a code, which staging
reads from a sink), the three chat-only tiers with the closed legal library and the citation guard, and the credit
ledger. No provider keys: the tiers run on a mock model that answers every call and logs it, so "did anything reach the
provider" is an observable fact. The scenarios began as I.4 of `.hq/docs/audits/librechat-platform/I-upstream-and-tests.md`
and grew with each plan since; the header of `scenarios.mjs` lists them.

**The demo overlay.** A demo overlay can exist outside this repository (`.hq/docs/plans/plan-chat-only-tiers.prompt.md`,
Task 37): a guest gateway container, its own `librechat.yaml` and `iqraa.json` mounted over these, and a real provider
behind the tiers. Every staging check here assumes it is off: with it mounted, a restart runs another configuration than
the one under test. When it is off, `docker ps -q --filter name=iqraa-staging-guest` prints nothing and no mount of the
librechat container (`docker inspect`, `.Mounts`) names a demo folder. Take it off with its own restore step (Task 37
names it) before any run below. Since O-34 the overlay must change before it is next turned on: `MONGO_URI` is no longer
in LibreChat's environment, so an overlay that replaces LibreChat's entrypoint must export
`MONGO_URI=$$(cat /secrets/mongo_uri)` as this `compose.yaml`'s entrypoint does (without it LibreChat exits at start
with "Please define the MONGO_URI environment variable" and restarts in a loop), and any extra service that talks to
MongoDB, the guest gateway among them, needs a credentialed URI read from the secrets volume, since mongod refuses an
unauthenticated client. `mongo_uri` is 0400 uid 1000, which a container running as `node` reads.

| Service | What it is |
|---|---|
| `proxy` | nginx, the only published port (`127.0.0.1:3080`; `IQRAA_PORT` moves it and LibreChat's origin together); adds the narrow content-security policy and the Arabic default-language cookie. It forwards the Host header with its port (`$http_host`, O-156), so a sign-in on a non-default port passes LibreChat's same-origin check |
| `librechat` | the release image `iqraa/release:staging` (fork image + content skills, `deploy/release/build.sh`), running as `node` (uid 1000); sign-in by code only, the three tiers, the citation guard in `shadow` |
| `mongo` | MongoDB replica set (the ledger needs transactions) with authentication on; its health check `scripts/mongo-bootstrap.js` initiates the set and creates the users (see «Secrets and database users») |
| `reconcile-daily` | the ledger reconciliation `scripts/reconcile.js`, once at start and then daily (see «Reconciliation») |
| `postgres`, `postgres-roles`, `legal-search`, `legal-search-ingest` | the legal library: the 22 laws of `content/corpus/laws.json` (corrections in `corrections.json`) and the Civil Code memorandum, MCP tools `search_law` / `get_article` / `get_memorandum`. `postgres-roles` (one-shot, `scripts/pg-roles.sql`) gives legal-search its own role, `legal_app`, before every ingest |
| `mock-llm` | OpenAI-compatible mock; every request goes to `out/llm-requests.jsonl` |
| `secrets-init` | one-shot: generates the secrets into the `staging-secrets` volume, sets their modes and owners, and hands LibreChat's data volumes to uid 1000 |

## Run

From the Harness root, in Git Bash:

```bash
# 1. The fork image, from the committed tree of the AI Platform checkout (PLATFORM_DIR; default: the sibling
#    "AI Platform" of this Harness), with upstream's Dockerfile.multi. Tags iqraa/platform:<short sha> and :phase1.
#    --rollback-tag <name> first keeps the current :phase1 as iqraa/platform:<name>, and never retags an existing <name>.
deploy/release/build-platform.sh
SHA=$(docker image inspect iqraa/platform:phase1 --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^BUILD_COMMIT=//p')

# 2. The staging release: the Harness checks, then the fork image plus the content skills, as iqraa/release:staging
deploy/release/build.sh staging "$SHA" --allow-draft

# 3. Start the stack and run the scenarios
cd deploy/staging
docker compose up -d --build  # builds legal-search only: the LibreChat release is never built or pulled here
node scenarios.mjs            # exit 0 = all scenarios, proxy checks and reconciliation pass
```

`build-platform.sh` exports the tree to `deploy/release/.build/<sha>` and writes its log to
`deploy/release/.build/build-<sha>.log`; `build.sh` stages each release in `deploy/release/.build/<tag>-<timestamp>`.
That folder is git-ignored; `IQRAA_BUILD_DIR` moves it, and `IQRAA_IMAGE_PREFIX` replaces `iqraa` in the tags both
scripts make (compose then needs `IQRAA_IMAGE`, and the drills name `iqraa/` releases). The
platform build refuses a build folder that is not empty, so a second build of the same commit needs
`deploy/release/.build/<sha>` removed first.

Every build here uses `--allow-draft` (staging and the drills): `tools/gates.sh checks`, where the skills, the law
registry, the corrections and the starter prompts need not be approved yet, and nothing is recorded. `--production`
stops before anything else unless the Harness is committed (`git status --porcelain` empty), the AI Platform checkout
(`PLATFORM_DIR`) is at `<sha>` with nothing uncommitted (the `fork` gate runs on that working tree), and the platform
image carries `BUILD_COMMIT=<sha>`, which `build-platform.sh` bakes in from the committed tree. It then runs
`tools/gates.sh --release` with every step but `docker` (skill-ci, corpus-ci and the starter prompts must be approved),
writes the released versions to `content/skills/RELEASED.json`, labels the image `org.iqraa.harness-commit`, and refuses
`--extra`. The driver below writes tier ids into the tracked `iqraa.json` and `librechat.yaml` on every run, so a
checkout that runs staging refuses `--production` until both are restored to their committed form (or the build runs
from a clean checkout); and the `RELEASED.json` a production build writes is to be committed before the next one.

**Why `Dockerfile.multi`, and the `node` user.** On this Docker Desktop (WSL2 kernel 6.18), the main `Dockerfile`'s
`npm prune --production` deadlocked twice in the kernel (npm's worker threads stuck in `rename` and an ext4 journal
wait). `Dockerfile.multi` installs production dependencies fresh (`npm ci --omit=dev`) and never prunes. Its image has no
`USER` line and runs as root from `/app/api`; the release built on it (`deploy/release/Dockerfile`) runs as `node`
(uid 1000, O-40). Root keeps the code and the skills; `node` owns only the folders LibreChat writes to, `/app/uploads`,
`/app/client/public/images` and `/app/api/logs` (`/app/data` is already 1777 in the platform image), and `secrets-init`
hands the matching volumes to uid 1000, volumes a root release wrote first included. `docker-tests/nonroot.test.mjs`
checks that the release writes there and nowhere in its code or skills.

The driver creates fresh accounts on every run (by phone, codes read from the sink; the staff account is made with the staff bootstrap runner, see «Sign-in on staging»), releases the three tier agents (`content/release.mjs`, from `content/tiers.json`) onto
the mock model, writes their ids into `librechat.yaml` and `iqraa.json` (`content/tiers.mjs apply`; the first run on a stack
recreates LibreChat once), and on staging only lists one extra skill (`staging-listed`) on the «عقل سريع» agent so scenario 1 can
load a skill on demand. It writes `out/scenarios-report.json`.

`out/` is git-ignored: the model log holds full prompts, including the AQEL instructions and skill bodies.

**A second stack.** `COMPOSE_PROJECT_NAME` overrides the project name in `compose.yaml` (`iqraa-staging`), so the
containers, the network and the volumes are that project's own, and `IQRAA_PORT` moves the published port and
LibreChat's `DOMAIN_CLIENT` / `DOMAIN_SERVER` together. The driver needs both exported as well (its `docker compose` calls
name no project), and `LIBRECHAT_URL=http://127.0.0.1:<port>` (it defaults to 3080). Run a second stack from its own
checkout: `mock-llm` binds `./out`, so from this folder it would write into this stack's `out/llm-requests.jsonl`, which
the driver reconciles against. Both stacks share the images, and `up --build` rebuilds `iqraa/legal-search:phase1` from
whichever checkout runs it. `docker-tests/` boots its copies with `-p hardening-*` and `docker-tests/compose.isolated.yaml`
(its own port, 3186 unless a test names another, outside 3080 and the client previews' 3091-3097; a throwaway
legal-search tag, rebuilt from `services/legal-search` on every run; the mock's log kept in its container).

## Operating the stack

- **Restart.** The long-running services (`mongo`, `reconcile-daily`, `postgres`, `legal-search`, `mock-llm`,
  `librechat`, `proxy`) are `unless-stopped`: they come back after a crash and whenever Docker starts, so Docker Desktop
  brings staging up on its port at every start until `docker compose stop`, which Docker remembers. The one-shots
  (`secrets-init`, `postgres-roles`, `legal-search-ingest`) never restart, or they would loop. A service an operator
  stops stays stopped: scenario 7 stops legal-search and brings it back itself.
- **Health.** LibreChat is healthy once `/readyz` answers, never `/health` (O-46): `/health` answers as soon as the server
  listens, before MCP and agent startup finish, and a first chat sent in that window ended without a model call in 2 of 7
  drill runs. The driver waits on `/readyz` too, and a production health check and load balancer must use `/readyz`.
  Health gates only the proxy's start: Docker restarts a container that exits, not one that turns unhealthy.
- **Limits.** Memory and CPUs per service; an environment variable raises each default when compose runs. Docker refuses
  a container whose CPUs exceed the host's count, so the defaults stay low for a small server.

  | Service | Memory | CPUs | Override |
  |---|---|---|---|
  | `mongo` | 4g | 2 | `IQRAA_MEM_MONGO`, `IQRAA_CPUS_MONGO` |
  | `librechat` | 4g | 2 | `IQRAA_MEM_LIBRECHAT`, `IQRAA_CPUS_LIBRECHAT` |
  | `postgres` | 2g | 2 | `IQRAA_MEM_POSTGRES`, `IQRAA_CPUS_POSTGRES` |
  | `legal-search`, `legal-search-ingest` | 2g | 2 | `IQRAA_MEM_LEGAL_SEARCH`, `IQRAA_CPUS_LEGAL_SEARCH` |
  | `mock-llm` | 512m | 1 | `IQRAA_MEM_MOCK`, `IQRAA_CPUS_MOCK` |
  | `reconcile-daily` | 384m | 0.5 | `IQRAA_MEM_RECONCILE`, `IQRAA_CPUS_RECONCILE` |
  | `proxy` | 256m | 1 | `IQRAA_MEM_PROXY`, `IQRAA_CPUS_PROXY` |

  Measured idle: mongo 541 MiB, librechat 287, legal-search 61, postgres 48, mock-llm 25, proxy 18; reconcile-daily
  peaked at 187 MiB on a near-empty ledger. `reconcile.js` holds every reservation and usage event in memory, so a ledger
  that outgrows its limit shows as `ALERT reconcile_failed status=137`.
- **Logs.** Every container's log rotates at 5 files of 20 MB (`json-file`). LibreChat also writes its own logs to the
  `staging-logs` volume.
- **Volumes.** `staging-secrets`, `staging-mongo`, `staging-postgres`; LibreChat's three (O-69): `staging-uploads`
  (`/app/uploads`), `staging-images` (`/app/client/public/images`) and `staging-logs` (`/app/api/logs`); and
  `staging-reports` for reconcile-daily. A recreate, `--force-recreate` included, keeps them all, so applying a
  configuration change no longer loses uploads or logs; only `docker compose down -v` removes them. `staging-secrets`
  belongs with the two databases: removed alone, the new passwords match neither (mongo's health check never changes a
  user that exists, and Postgres keeps the superuser password of its first start), so remove all of them or none.

## Secrets and database users (O-34)

`secrets-init` writes each file once and never replaces it, except `database_url` and `mongo_uri`, which it rewrites on
every run. The modes and owners marked «every run» are set again on every run, so an older volume gets them too; the
others keep the mode they were made with.

| File | Mode | Read by |
|---|---|---|
| `jwt`, `jwt_refresh`, `creds_key`, `creds_iv`, `iqraa_auth`, `mock_llm` | 0444 | LibreChat's entrypoint (`iqraa_auth`: the code and audit keys) |
| `legal_search` | 0444 | legal-search and LibreChat: the library API's shared secret |
| `iqraa_staging` | 0444 | the fork: the sink starts only where it exists |
| `pg_password` | 0400 root, every run | the Postgres entrypoint and `postgres-roles`: the superuser |
| `pg_app_password` | 0400 root, every run | `postgres-roles`, which sets `legal_app`'s password from it |
| `database_url` | 0400 uid 10001, every run | legal-search and the ingest (uid 10001) connect with it as `legal_app`, which owns the law library |
| `mongo_keyfile` | 0400 uid 999, every run | mongod, which refuses a key others can read; `--keyFile` turns authorization on. The key signs in as `__system`, past every user, and the Postgres server runs as uid 999 too, so `postgres` and `postgres-roles` never mount the whole volume (below) |
| `mongo_admin_password`, `mongo_app_password`, `mongo_reader_password` | 0400 root, every run | mongo's health check, which creates the users; `scripts/query.js` and `scripts/reconcile.js` read only the reader's. All as root in their containers |
| `mongo_uri` | 0400 uid 1000, every run | LibreChat's entrypoint and the runners: `iqraa_app`'s URI |

- **MongoDB** (`scripts/mongo-bootstrap.js`): `iqraa_admin` (root, the health check's own sign-in), `iqraa_app`
  (readWrite on `LibreChat`: LibreChat and the staff bootstrap runner) and `iqraa_reader` (read on `LibreChat`: the
  driver's `scripts/query.js`, `scripts/reconcile.js` and reconcile-daily). The health check creates a user that is
  missing and never changes one that exists: a password rotation or a role change is an operator's `updateUser`.
- **Postgres** (`scripts/pg-roles.sql`): `legal_app` owns the `legal` database and its `public` schema and is no
  superuser (no `CREATEDB`, no `CREATEROLE`); it cannot create an extension, so the script creates `vector` as the
  superuser first. Its password is set from `pg_app_password` on every run.
- **`MONGO_URI` is not in LibreChat's environment**, where `docker inspect` would show it: the entrypoint exports it from
  `mongo_uri`. A `docker compose exec` session does not have it, so each runner command below exports it itself.
- **`postgres` and `postgres-roles` mount single files** of `staging-secrets` by volume subpath: `postgres` only
  `pg_password`, `postgres-roles` that and `pg_app_password`, each read-only at `/secrets/<name>`. A volume subpath
  needs Docker Engine 26 or later and a Compose that knows `volume.subpath` (checked here on Engine 29.9 and
  Compose 5.6). Docker resolves it when the container starts, after `secrets-init` has written the file, and a file
  mounted this way is the one that existed then: both are written once and never replaced.
  `compose.contract.test.mjs` and `docker-tests/pg-role.test.mjs` check it.
- **Residual.** Every other service that reads a secret (all but `mock-llm`, the proxy, `postgres` and
  `postgres-roles`) still mounts the whole `staging-secrets` volume, not only its own files. The modes are the only
  separation: legal-search (uid 10001) can read every 0444 file, LibreChat's JWT and credential keys among them, and
  anything running as root in one of those containers (`secrets-init`, `reconcile-daily`, mongo's health check) reads
  them all, mongo's key included. One secret per service is the draft fix
  (`.hq/docs/audits/librechat-platform/PROOF-security-review.md`).

## Upgrading an existing stack

The first `docker compose up -d` with this `compose.yaml` over volumes an earlier release wrote (no database users,
LibreChat as root, no data volumes) does this:

1. `secrets-init` adds every file that is missing, never replacing one; writes `database_url` for `legal_app` and
   `mongo_uri` for `iqraa_app`; sets the modes and owners above (`pg_app_password` and `database_url` were 0444 before); and hands `staging-uploads`, `staging-images` and
   `staging-logs` to uid 1000.
2. `mongo` is recreated with `--keyFile`. No user exists on the old data yet, so its health check, through MongoDB's
   localhost exception, creates `iqraa_admin` and then `iqraa_app` and `iqraa_reader`; mongo turns healthy only once
   they exist. `MONGO_INITDB_*` is not used: the image applies it to an empty volume only.
3. `postgres-roles` creates `legal_app` and hands it the `legal` database, its schema and every existing table (their
   indexes and sequences go with them); `legal-search-ingest` then runs as `legal_app`.
4. `legal-search` is recreated, because its definition gained `PGAPPNAME`, and reconnects as `legal_app`. A later change
   to `database_url` alone does not recreate it: `docker compose up -d --force-recreate legal-search`.
5. `librechat` is recreated and signs in to MongoDB as `iqraa_app`. Its data volumes start empty: what an older container
   held in those folders lived in that container and is not carried over.
6. `reconcile-daily` starts and runs its first reconciliation at once, into the new `staging-reports`.

Every long-running service is recreated at that first `up`, since the restart policy, the limits and the log rotation
changed each definition. A release built before O-40 still runs on this compose as root; rebuild `iqraa/release:staging`
(step 2 of «Run») to run as `node`. `docker-tests/mongo-auth.test.mjs` and `docker-tests/pg-role.test.mjs` boot both
paths, an upgrade over volumes written the old way and empty volumes, in isolated projects.

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
there, `MONGO_URI` among them (`lib.mjs` `RUNNER`). From this folder (Git Bash; `MSYS_NO_PATHCONV` keeps the container
paths as typed):

```bash
export MSYS_NO_PATHCONV=1
RUNNER='export IQRAA_AUTH_SECRET=$(cat /secrets/iqraa_auth) CREDS_KEY=$(cat /secrets/creds_key) CREDS_IV=$(cat /secrets/creds_iv) MONGO_URI=$(cat /secrets/mongo_uri) && exec node /app/config/iqraa-bootstrap-staff.js "$@"'
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

`scripts/reconcile.js` is the ledger reconciliation (read-only; it signs in as `iqraa_reader`). The `reconcile-daily`
service runs it at start and then every `RECONCILE_INTERVAL_SECONDS` (86400 unless set when compose runs), writes each
run's output to `/reports/reconcile-<UTC date>.json` in the `staging-reports` volume (a later run that day replaces it),
and logs one line per run: `reconcile ok <its JSON>`, or `ALERT reconcile_failed status=<n> <output>` when an invariant
fails; the loop goes on after a failure. Nothing pages anyone: no alert channel is configured, so the ALERT line is only
a line in the service's log. From this folder:

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T mongo mongosh LibreChat --quiet --file /scripts/reconcile.js   # by hand, as the driver does
docker compose logs reconcile-daily | grep -E 'reconcile ok|ALERT reconcile_failed'                      # one line per run
MSYS_NO_PATHCONV=1 docker compose exec -T reconcile-daily sh -c 'cat /reports/reconcile-$(date -u +%F).json'   # today's report
```

It checks that every transaction and the whole book sum to zero, that wallets equal their postings and
their open reservations, that every settled reservation has exactly one usage event with the same
amount (and nothing else does), that no hold outlives its expiry, and that each reservation's postings
match its status. It summarises the window's spend and flags settlements made at the estimate because
the provider reported no usage. It exits 1 when an invariant fails. The open sweep flags need a staff session, which
reconcile-daily does not have, so they stay in the driver's report and legal-search's own alert lines.

**Against the provider's export.** `provider-compare.mjs` compares the usage ledger (`iqraa_usage_events`) with a
provider's usage export per UTC day and model, in tokens only (the provider's money units are unknown):

```bash
node provider-compare.mjs --export <csv> [--usage <json file>] [--tolerance-pct n] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
```

The export is a neutral CSV with a header row: `date` (a UTC day), `model`, `input_tokens`, `output_tokens`, and
optionally `cache_read_tokens` and `cache_write_tokens`; a quoted cell is refused. No provider is chosen, so mapping
its export onto these columns, and its model names onto the ledger's, waits for that choice. Without `--usage` it
reads every event from this stack's MongoDB through `lib.mjs`, within a 1 MB output limit: export a larger ledger to a
`--usage` file. Settlements made at the estimate carry no provider tokens and are counted apart. It prints one JSON line
and exits 0 when both sides agree within the tolerance (1 % by default), 1 when not, and 2 when it cannot read its
input. No real export has been compared yet.

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
- The concurrent-message limiter is on at 8 (`LIMIT_CONCURRENT_MESSAGES=true`, `CONCURRENT_MESSAGE_MAX=8`), above
  scenario 8's six parallel chats, which stay bounded by the credit ledger. Scenario `concurrent` proves it: of ten
  starts eight run and the last two are refused (429, `concurrent`) without reaching the model, and turns that end or
  are stopped give their slots back. Production must set `LIMIT_CONCURRENT_MESSAGES=true` itself, with
  `CONCURRENT_MESSAGE_MAX` (2, or the chosen value): unset, LibreChat's limiter is off and lets every message through
  (the fork's `packages/api/src/middleware/concurrency.ts` checks `isEnabled(LIMIT_CONCURRENT_MESSAGES)`; 2 is only
  the default maximum once it is on), and the fork does not check these settings at start-up (O-34). Without Redis the
  count lives in the LibreChat process's memory, read and then written, so starts sent together can race past it: a
  soft limit (the scenario awaits each start before the next).
- `test-skills/` holds two marker skills used only by scenario 1.
- Content-security policy: LibreChat's own nonce policy for scripts (`CSP_ENABLED`, enforcing) plus the
  proxy's policy narrowing `img-src`, `connect-src`, `frame-src` and `frame-ancestors` (G-security T7).

## Release drills (scenarios 5 and 14)

Run `node scenarios.mjs` once first (it creates the plan roles and the tiers), then, from the Harness root:

```bash
PLATFORM=$(docker image inspect iqraa/platform:phase1 --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^BUILD_COMMIT=//p')
S=deploy/staging/drill-skills
deploy/release/build.sh drill-r1 "$PLATFORM" --allow-draft --extra $S/r1 --extra $S/listed
deploy/release/build.sh drill-r2 "$PLATFORM" --allow-draft --extra $S/r2 --extra $S/listed
deploy/release/build.sh drill-r3 "$PLATFORM" --allow-draft --extra $S/r2
cd deploy/staging && node drills.mjs
```

The drill swaps LibreChat between the three releases (each restart takes a minute or two), edits the
«عقل سريع» tier agent (a customer can chat only with a tier), rolls back image and agent, and removes a skill; it restores
`iqraa/release:staging` at the end, even on failure, and releases the tiers again to put the agent back.

## Scenario 3 (pinned skill through summarisation)

Summarisation is off in normal staging (summary calls would change other scenarios' call counts). Run it alone, from
this folder:

```bash
cat librechat.yaml summary-overlay.yaml > out/librechat.summary.yaml
docker compose -f compose.yaml -f compose.summary.yaml up -d --no-deps --force-recreate librechat   # wait for /readyz 200
SCENARIOS=3 node scenarios.mjs     # narrows the specialist's window to S3_MAX_CONTEXT_TOKENS (default 9000)
docker compose up -d --no-deps --force-recreate librechat                                           # back to normal staging
SCENARIOS=2 node scenarios.mjs     # re-releases the specialist with its normal window
```

`--force-recreate` matters: compose does not recreate a container when only a mounted file changed.
The release folds always-apply skills into the specialist's instructions (`content/compose.mjs`), so
scenario 3 also checks the pinned method rides in the system prompt exactly once.

## Chat-only tiers (scenario `chatonly`)

The customer product is chat only, with three named tiers and a closed corpus (`.hq/docs/specs/spec-chat-only-tiers-closed-corpus.md`).

- **Tiers.** `content/tiers.json` is the source of record. The driver's setup releases one private agent per tier and runs
  `node content/tiers.mjs apply --resolved out/tiers-resolved.json --yaml librechat.yaml --iqraa iqraa.json`, which rewrites the
  `modelSpecs` block (between the `BEGIN`/`END iqraa:modelSpecs` markers) and `iqraa.json` `tiers`; it prints `changed` the first time
  and the driver then **recreates** LibreChat (never a restart). To move a tier to another model:
  `node content/tiers.mjs set-model <key> <provider> <model> --note "<why>" --prices deploy/staging/iqraa.json`, then release.
- **Usage.** Metering settles each tier turn on the usage the provider reports; with none, the turn is charged its full hold
  and the log says only `provider reported no usage`. A custom endpoint reports usage only when asked, and LibreChat (since
  v0.8.9-rc1) refuses `streamUsage` on an agent, so the ask lives on the endpoint: `addParams: { streamUsage: true }` under
  `MockLLM` here, and under every endpoint a tier runs on in production. `tiers.mjs apply` (and `tiers.mjs check --yaml <file>`)
  refuses a `librechat.yaml` without it, `librechat.test.mjs` checks this file, and the tier lint refuses the key on the agent.
  Settlements at the estimate in the daily reconcile report mean the endpoint lost it.
- **The guard.** `iqraa.json` `grounding.mode` is `shadow` (log only) or `block` (replace an ungrounded answer with the fixed
  message); `off` skips it. Change it, recreate LibreChat, and run `SCENARIOS=chatonly node scenarios.mjs`: the scenario reads the
  mode from the file and checks the matching behaviour, also for an answer the customer stops halfway (the mock streams a
  `FINAL_TEXT` a word at a time when the prompt also carries `SLOW_STREAM:<ms>`; the stop route saves that partial answer, and in
  `block` mode neither the stored row nor the final event of the stop may hold the replaced text). The full driver and the RTL check
  run in `shadow` mode: the mock's demo answer cites an article without retrieving it, which `block` would replace.
- **A refused turn.** A tier turn the provider refuses (quota, model not found) shows the fork's fixed Arabic notice, never the
  provider's words, which can name the private model; the fork's own refusals (credits, suspension) keep their text. `PROVIDER_ERROR`
  in the prompt makes the mock answer a 400 whose text names the model, and check `providerErrorHidden` reads what the customer can read.
- **What a customer reads of a chat.** `customer-filter.ts` removes the model and provider keys and every provider error text from the
  stream, the chat status, the messages and a fork; check `modelHiddenInConversation` reads those routes while a turn runs, by name and by key.
- **The census.** `node ui/run-rtl-check.mjs --census` signs a customer in through a real browser and walks every flow a customer has:
  the starter gallery by keyboard (Enter, Space, Tab, focus rings), the RTL and 390 px captures (saved to `out/shots`, or to
  `IQRAA_SHOTS_DIR`), a starter, title generation, feedback, regenerate, message edit, resume after a reload, search, a file attach,
  conversation rename and archive, the settings tabs, the archived list, a language change, logout last. It lists every `/api` call
  the client made (`out/census.json`); a 403 `IQRAA_FORBIDDEN` outside `EXPECTED_DENIED` (favorites, speech) means `customer-api.ts`
  lacks a route the client needs, and any other non-2xx fails the run. A flow whose control is not found fails, it is never skipped.
  The census has passed: the Regression row of `.hq/docs/audits/librechat-platform/CHATONLY-results.md` records CENSUS PASS.
  `out/census.json` is git-ignored run output, so that file is the record.
- **Stored events.** `iqraa_guard_events` holds each guarded turn; the answer text only on an ungrounded or unsearched one
  (`grounding.answerRetentionDays`, 14 days; the rest `retentionDays`). Replay them through the current extractor with
  `config/iqraa-guard-eval.js` before switching to `block`. Its header's export predates MongoDB authentication: the export
  signs in as `iqraa_reader` first, reading the password inside the mongo container. From this folder:

  ```bash
  export MSYS_NO_PATHCONV=1
  docker compose exec -T mongo mongosh LibreChat --quiet --eval "db.auth('iqraa_reader', require('fs').readFileSync('/secrets/mongo_reader_password', 'utf8').trim()); db.iqraa_guard_events.find().forEach((d) => print(EJSON.stringify(d)))" > out/guard-events.jsonl
  docker compose exec -T librechat node /app/config/iqraa-guard-eval.js /dev/stdin /config/grounding-laws.json < out/guard-events.jsonl
  ```

  It prints one JSON report and exits 1 when a logged verdict differs from the replay. The events file holds answer text, so
  it stays in `out/`.
- **Uploads.** `fileConfig` in `librechat.yaml`: PDF, Word and plain text, 5 MB each, 10 MB together, three files (the count is
  enforced by the client only). The limits are set under `agents` and again under `default`, because the upload route looks them up
  by the `endpoint` field of the form, which the client chooses, and spelled out for `anthropic`, `assistants` and `azureAssistants`,
  whose built-in entries (ten files for `anthropic`) LibreChat keeps and `default` does not override. The scenario probes
  `endpoint: openAI` and `endpoint: anthropic`.
- **Footer.** `CUSTOM_FOOTER` in `compose.yaml` («Iqraa LAW AI»). The client prints it from `GET /api/config` (`customFooter`); the
  shell page `index.html` holds only a flag, so check the footer through `/api/config`, not by grepping the page.

## Arriving with the fork-fixes merge

Not in the fork image staging runs today: these arrive with the merge of the fork's `fork-fixes` branch and the first
release built after it.

- **A cap on WhatsApp codes.** `iqraa.json` `auth.limits.whatsappCodesPerHour` (300) and `whatsappCodesPerDay` (2000)
  count every code request for a phone, across every number and address. They are draft defaults, chosen with no price per
  message or traffic figure to hand; the owner sets the numbers. They count on staging too: a phone code's channel is
  WhatsApp whatever `auth.delivery` says, and staging's `iqraa.json` does not set them (a busy hour, above, makes about
  102 requests). A refused request answers like any other limit, `IQRAA_AUTH_LIMITED`.
- **Guard events erased with a conversation, once switched on.** `grounding.eraseOnConversationDelete` (default `false`):
  when `true`, a customer's successful `DELETE /api/convos` naming a conversation erases that conversation's
  `iqraa_guard_events` rows, and `DELETE /api/convos/all` erases all of that customer's. `false` keeps Decision 15: the
  rows expire on their own. The owner turns it on; staging leaves it unset.
- **The support runner.** `config/iqraa-support.js` in the LibreChat image: `find`, `erase-plan`, `erase`, `request-code`,
  `change-phone`, `release-phone` and `title-costs` (usage in its header). Every command but `title-costs` takes
  `--by <staff user id>`, an account that holds a staff role, and first writes a `runner:<command>` row to
  `iqraa_staff_audit` (who, what, whom and the status; never a body or a phone number), refusing when it cannot. Where the
  staging marker exists, `erase`, `request-code`, `change-phone` and `release-phone` refuse (`IQRAA_SUPPORT_STAGING_REFUSED`),
  so on staging only `find`, `erase-plan` and `title-costs` run. Staff requests on `/api/admin` and `/api/iqraa/admin` write
  a row each as well, and one whose row cannot be written is answered 503. Nothing deletes an audit row: how long they are
  kept is the owner's decision, not made yet. Like the bootstrap runner it needs `MONGO_URI` exported in the exec session
  (its header's «already in the container's environment» predates O-34). From this folder, with `PHONE` set:

  ```bash
  export MSYS_NO_PATHCONV=1
  SUPPORT='export IQRAA_AUTH_SECRET=$(cat /secrets/iqraa_auth) CREDS_KEY=$(cat /secrets/creds_key) CREDS_IV=$(cat /secrets/creds_iv) MONGO_URI=$(cat /secrets/mongo_uri) && exec node /app/config/iqraa-support.js "$@"'
  docker compose exec -T librechat sh -c "$SUPPORT" support find --phone "$PHONE" --by <staff user id>
  ```

- **Two new alerts**, error-level lines in `docker compose logs librechat`:
  - `ALERT auth_whatsapp_cap_reached window=<hour|day>`: phone code requests reached the cap, so every sign-up and sign-in
    by phone code is refused until the window passes; look for a flood in `iqraa_auth_events` before raising the cap in
    `iqraa.json` (then recreate LibreChat).
  - `ALERT customer_name_filtered key=<key> path=<path>`: a response to a customer carried a provider or private model name
    under a key the chat filter does not remove, and the value check removed it (the value is not logged); add the key to
    `customer-filter.ts`, or find why that route sends it. Raised once per key and path per process.
- **Refusals a customer reads.** On a tier turn the fork's own refusals (credits, suspension, no account, a model without
  a price, a stopped run) reach the customer as the Arabic text only, with no `(IQRAA_…)` code; staff and non-tier reads
  keep the code. The driver's refusal checks that look for the code change with the merge.
