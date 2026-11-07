// O-34: legal-search reaches Postgres as legal_app, a role that owns the legal schema and is no superuser, both on a
// volume a release before the role wrote (the upgrade) and on empty volumes.
//   node --test deploy/staging/docker-tests/pg-role.test.mjs
// Upgrade, project hardening-o34pg-up: docker-tests/fixtures/compose.before-db-auth.yaml ingests and runs legal-search
// as the postgres superuser, then the real compose.yaml (with compose.isolated.yaml) is brought up over that running
// stack, as an upgrade of staging would be. Empty, project hardening-o34pg-empty: the real compose.yaml from nothing.
// Neither starts the proxy or publishes a port, and each project is removed, volumes included, before and after its flow.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { compose, DEFAULT_RELEASE, destroy, ensureLegalSearch, saveLogs, STAGING_DIR } from './isolated.mjs';

const UPGRADE = 'hardening-o34pg-up';
const EMPTY = 'hardening-o34pg-empty';
const APP_ROLE = 'legal_app';
const FIXTURE = 'docker-tests/fixtures/compose.before-db-auth.yaml';
// What isolated.mjs compose() runs; repeated here only for the calls that need stdin, which compose() cannot pass.
const ISOLATED_FILES = ['-f', 'compose.yaml', '-f', 'docker-tests/compose.isolated.yaml'];
const MCP_CALLS = path.join(STAGING_DIR, 'scripts', 'mcp-calls.py');
const FLOW_TIMEOUT_MS = 45 * 60_000; // the ingest loads every law, twice in the upgrade, on a spinning disk
const SEARCH_BUDGET_MS = 3 * 60_000; // legal-search opens its port a few seconds after it starts

// Fixed queries only, run as the superuser over the postgres container's socket.
const QUERIES = {
  owners: `
SELECT 'table ' || tablename, tableowner FROM pg_tables WHERE schemaname = 'public'
UNION ALL SELECT 'database ' || datname, pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()
UNION ALL SELECT 'schema ' || nspname, pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'public'
ORDER BY 1;`,
  articles: 'SELECT count(*) FROM articles;',
  retrievals: 'SELECT count(*) FROM retrieval_log;',
  appRole: "SELECT rolsuper, rolcreatedb, rolcreaterole, rolcanlogin FROM pg_roles WHERE rolname = 'legal_app';",
  // The sessions other than this one, as "role application_name": once the ingest and postgres-roles have exited,
  // legal-search's pool.
  sessions: `
SELECT DISTINCT usename || ' ' || application_name FROM pg_stat_activity
WHERE datname = 'legal' AND backend_type = 'client backend' AND pid <> pg_backend_pid() ORDER BY 1;`,
};
// What compose.yaml's legal-search connects as (PGAPPNAME names the service).
const APP_SESSION = 'legal_app legal-search';
// Run inside legal-search with the URL legal-search itself reads, so it proves the password as well as the role.
const SERVICE_ROLE = `
import os, psycopg
with open(os.environ['DATABASE_URL_FILE'], encoding='utf-8') as handle:
    url = handle.read().strip()
with psycopg.connect(url) as conn:
    print(*conn.execute('SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user').fetchone())
`;

function guard(project) {
  if (!/^hardening-o34pg-[a-z0-9-]+$/.test(project)) throw new Error(`refusing compose project "${project}"`);
}

function docker(args, input) {
  const result = spawnSync('docker', args, {
    cwd: STAGING_DIR,
    env: { ...process.env, MSYS_NO_PATHCONV: '1', IQRAA_IMAGE: DEFAULT_RELEASE },
    input,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  return result;
}

function ok(result, what) {
  if (result.status !== 0) throw new Error(`${what} exited ${result.status}:\n${`${result.stderr}\n${result.stdout}`.trim().slice(-4000)}`);
  return result.stdout;
}

const fixtureChecked = new Set();

/** `docker compose` on the pre-O-34 fixture, in deploy/staging; refuses a configuration with an iqraa/ image or a port. */
function fixture(project, args) {
  guard(project);
  const base = ['compose', '-p', project, '--project-directory', '.', '-f', FIXTURE];
  if (!fixtureChecked.has(project)) {
    const config = JSON.parse(ok(docker([...base, 'config', '--format', 'json']), 'fixture config'));
    const problems = [];
    if (config.name !== project) problems.push(`the project resolves to "${config.name}"`);
    for (const [name, service] of Object.entries(config.services ?? {})) {
      if (/(^|\/)iqraa\//.test(String(service.image ?? ''))) problems.push(`${name} uses ${service.image}`);
      if ((service.ports ?? []).length > 0) problems.push(`${name} publishes a port`);
    }
    if (problems.length > 0) throw new Error(`refusing the fixture under ${project}: ${problems.join('; ')}`);
    fixtureChecked.add(project);
  }
  return ok(docker([...base, ...args]), `fixture ${args.join(' ')}`);
}

/** `exec -T` in the real stack with `input` on stdin; returns the raw result, so a refusal can be asserted. */
function execIn(project, service, args, input) {
  guard(project);
  return docker(['compose', '-p', project, ...ISOLATED_FILES, 'exec', '-T', service, ...args], input);
}

/** One of QUERIES; one '|'-separated row per line. */
function query(project, name) {
  const psql = ['psql', '-U', 'postgres', '-d', 'legal', '-v', 'ON_ERROR_STOP=1', '-q', '-A', '-t', '-F', '|', '-f', '-'];
  const out = ok(execIn(project, 'postgres', psql, QUERIES[name]), `psql ${name}`);
  return out.split('\n').map((line) => line.trim()).filter(Boolean);
}

const owners = (project) => query(project, 'owners').map((row) => row.split('|'));
const countOf = (project, name) => Number(query(project, name)[0]);
const containerOf = (project, service) => compose(project, ['ps', '-a', '-q', service]).trim();
const startedAt = (id) => ok(docker(['inspect', '--format', '{{.State.StartedAt}}', id]), 'docker inspect').trim();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** search_law through legal-search's MCP endpoint, as lib.mjs mcpCalls does but in this project; retried until it answers. */
async function mcpSearch(project) {
  const plan = Buffer.from(JSON.stringify({ user: 'o34-role-probe', calls: [{ tool: 'search_law', arguments: { query: 'العقد', law: 'civil-code' } }] }), 'utf8').toString('base64');
  const script = readFileSync(MCP_CALLS, 'utf8');
  const deadline = Date.now() + SEARCH_BUDGET_MS;
  let last;
  while (Date.now() < deadline) {
    last = execIn(project, 'legal-search', ['python3', '-I', '-', plan], script);
    if (last.status === 0) return JSON.parse(last.stdout.trim().split('\n').filter(Boolean).pop()).results[0];
    await sleep(3000);
  }
  throw new Error(`no MCP answer within ${SEARCH_BUDGET_MS} ms: ${String(last?.stderr ?? '').trim().slice(-1000)}`);
}

/** A subtest that also records its name in `failed`, so the flow knows to save the stack's logs. */
const stepper = (t, failed) => (name, fn) => t.test(name, async (st) => {
  try {
    await fn(st);
  } catch (error) {
    failed.push(name);
    throw error;
  }
});

/** The assertions both flows share, one subtest each, once the real compose.yaml has started legal-search. */
async function checkAppRole(step, project, { articles }) {
  await step('the user in database_url is legal_app, no superuser, and its password works', (st) => {
    const seen = ok(execIn(project, 'legal-search', ['python3', '-I', '-'], SERVICE_ROLE), 'python3').trim();
    st.diagnostic(`legal-search connects as: ${seen}`);
    assert.equal(seen, `${APP_ROLE} False`);
    assert.deepEqual(query(project, 'appRole'), ['f|f|f|t'], 'legal_app: superuser, createdb, createrole, login');
  });

  await step('legal_app owns every public table, the schema and the database', (st) => {
    const rows = owners(project);
    st.diagnostic(rows.map((row) => row.join(' -> ')).join(', '));
    assert.ok(rows.filter(([name]) => name.startsWith('table ')).length > 0, 'no table in the public schema');
    assert.deepEqual(rows.filter(([, owner]) => owner !== APP_ROLE), []);
  });

  await step(articles === null ? 'the ingest loaded articles' : 'the article count is unchanged after the ingest ran again as legal_app', (st) => {
    const now = countOf(project, 'articles');
    st.diagnostic(`articles: ${articles === null ? '' : `${articles} before, `}${now} now`);
    assert.ok(now > 0, 'no article');
    if (articles !== null) assert.equal(now, articles);
  });

  await step('an MCP search through legal-search returns an article and writes a retrieval_log row, as legal_app', async (st) => {
    const before = countOf(project, 'retrievals');
    const text = await mcpSearch(project);
    const after = countOf(project, 'retrievals');
    const sessions = query(project, 'sessions');
    st.diagnostic(`retrieval_log ${before} -> ${after}; legal-search's sessions: ${sessions.join(', ')}; result: ${text.split('\n')[0]}`);
    assert.match(text, /^\[\d+\] .*المادة/m);
    assert.equal(after, before + 1);
    // Old sessions here would be a legal-search that kept the superuser's connections through the upgrade.
    assert.deepEqual(sessions, [APP_SESSION]);
  });

  await step("legal-search (uid 10001) cannot read the superuser's password", (st) => {
    assert.equal(ok(execIn(project, 'legal-search', ['id', '-u']), 'id -u').trim(), '10001');
    const read = execIn(project, 'legal-search', ['cat', '/secrets/pg_password']);
    // Never print read.stdout: if the read worked, it holds the password.
    st.diagnostic(`exec -T legal-search cat /secrets/pg_password: exit ${read.status}, ${read.stderr.trim()}`);
    assert.notEqual(read.status, 0, 'legal-search read /secrets/pg_password');
    assert.match(read.stderr, /Permission denied/);
    assert.equal(ok(execIn(project, 'postgres', ['stat', '-c', '%a %U', '/secrets/pg_password']), 'stat').trim(), '400 root');
  });

  // O-34: postgres mounts its one secret, not the volume that holds mongod's key, which is owned by uid 999 for mongod;
  // the Postgres server runs as uid 999 too, and the key signs in to MongoDB as __system.
  await step('the postgres container holds only pg_password, which its server (uid 999) cannot read', (st) => {
    const listed = ok(execIn(project, 'postgres', ['ls', '-A', '/secrets']), 'ls /secrets').trim();
    st.diagnostic(`postgres /secrets: ${listed}`);
    assert.equal(listed, 'pg_password');
    const read = execIn(project, 'postgres', ['setpriv', '--reuid=999', '--regid=999', '--clear-groups', 'cat', '/secrets/pg_password']);
    // Never print read.stdout: if the read worked, it holds the password.
    st.diagnostic(`as 999, cat /secrets/pg_password: exit ${read.status}, ${read.stderr.trim()}`);
    assert.notEqual(read.status, 0, 'uid 999 read /secrets/pg_password');
    assert.match(read.stderr, /Permission denied/);
  });

  // legal_app owns the law library, so its password and URL are no more readable than the superuser's: LibreChat
  // (uid 1000) mounts the same volume and never needs Postgres.
  await step("legal_app's password is 0400 root (postgres-roles), its URL 0400 for legal-search (10001)", (st) => {
    const stat = ok(execIn(project, 'legal-search', ['stat', '-c', '%n %a %u', '/secrets/pg_app_password', '/secrets/database_url']), 'stat');
    st.diagnostic(stat.trim().split('\n').join(', '));
    assert.deepEqual(stat.trim().split('\n'), ['/secrets/pg_app_password 400 0', '/secrets/database_url 400 10001']);
  });

  await step('a second `up -d postgres-roles` exits 0, runs the script again and changes nothing', (st) => {
    const first = containerOf(project, 'postgres-roles');
    assert.ok(first, 'no postgres-roles container');
    const firstStart = startedAt(first);
    compose(project, ['up', '-d', 'postgres-roles']); // throws on a non-zero exit
    const again = containerOf(project, 'postgres-roles');
    const exit = ok(docker(['wait', again]), 'docker wait').trim();
    st.diagnostic(`postgres-roles started ${firstStart}, again ${startedAt(again)}, exit ${exit}`);
    assert.equal(exit, '0');
    assert.notEqual(startedAt(again), firstStart, 'postgres-roles did not run again');
    assert.deepEqual(owners(project).filter(([, owner]) => owner !== APP_ROLE), []);
  });
}

async function flow(t, project, body) {
  destroy(project); // a run that died before its cleanup: start from empty volumes
  const failed = [];
  try {
    ensureLegalSearch(project);
    await body(stepper(t, failed));
  } catch (error) {
    failed.push(error.message.split('\n')[0]);
    throw error;
  } finally {
    if (failed.length > 0) {
      try {
        t.diagnostic(`the stack's logs: ${saveLogs(project)}`);
      } catch (saving) {
        t.diagnostic(`its logs could not be saved: ${saving.message.split('\n')[0]}`);
      }
    }
    destroy(project);
  }
}

test('upgrade: a volume the superuser wrote is handed to legal_app in place', { timeout: FLOW_TIMEOUT_MS }, (t) =>
  flow(t, UPGRADE, async (step) => {
    // The release before O-34, running: the ingest and legal-search as the superuser. `up` waits for the ingest.
    fixture(UPGRADE, ['up', '-d', 'legal-search']);
    let articles = null;
    await step('before: the superuser owns every public table, the ingest loaded articles, legal-search serves as postgres', async (st) => {
      const before = owners(UPGRADE);
      articles = countOf(UPGRADE, 'articles');
      const text = await mcpSearch(UPGRADE);
      const sessions = query(UPGRADE, 'sessions');
      st.diagnostic(`${before.map((row) => row.join(' -> ')).join(', ')}; articles: ${articles}; sessions: ${sessions.join(', ')}`);
      assert.ok(before.filter(([name]) => name.startsWith('table ')).length > 0, 'no table in the public schema');
      assert.deepEqual(before.filter(([name, owner]) => name.startsWith('table ') && owner !== 'postgres'), []);
      assert.ok(articles > 0, 'no article');
      assert.match(text, /^\[\d+\] .*المادة/m);
      assert.deepEqual(sessions, ['postgres']);
    });
    assert.ok(articles > 0, 'the release before O-34 did not come up with articles');

    compose(UPGRADE, ['up', '-d', 'legal-search']);
    await checkAppRole(step, UPGRADE, { articles });
  }));

test('empty volumes: the real compose.yaml from nothing', { timeout: FLOW_TIMEOUT_MS }, (t) =>
  flow(t, EMPTY, async (step) => {
    compose(EMPTY, ['up', '-d', 'legal-search']);
    await checkAppRole(step, EMPTY, { articles: null });
  }));
