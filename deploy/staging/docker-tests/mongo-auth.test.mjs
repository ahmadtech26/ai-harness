// O-34: MongoDB requires authentication, both on a volume a release before O-34 wrote without it (the upgrade) and on
// empty volumes. LibreChat and the staff bootstrap runner sign in as iqraa_app (readWrite on LibreChat), the driver's
// query.js and reconcile.js as iqraa_reader (read on LibreChat); mongo's health check, scripts/mongo-bootstrap.js,
// initiates the replica set and makes both users and iqraa_admin.
//   node --test deploy/staging/docker-tests/mongo-auth.test.mjs
// Upgrade, project hardening-o34m-up on 127.0.0.1:3184: docker-tests/fixtures/compose.before-db-auth.yaml runs
// secrets-init and mongod without authentication and writes a row with no sign-in, then the real compose.yaml (with
// compose.isolated.yaml) brings up the proxy and all it waits for over those volumes, as an upgrade of staging would.
// Empty, project hardening-o34m-empty on 127.0.0.1:3185: the real compose.yaml from nothing. Builds
// hardening-test/release:o34m; each project is removed, volumes included, before and after its flow. No password
// reaches a command line or this test's output: the scripts that need one read it from /secrets in the container.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import { before, test } from 'node:test';
// A namespace import: RUNNER is asserted in its own step, so its absence fails that step, not the whole file.
import * as lib from '../lib.mjs';
import { buildRelease, compose, destroy, ensureLegalSearch, saveLogs, STAGING_DIR, waitReady } from './isolated.mjs';

// Outside 3091-3098: the client previews (stage2-preview-<port>) take 3091-3097 and stack-ops 3098.
const UPGRADE = { project: 'hardening-o34m-up', port: '3184' };
const EMPTY = { project: 'hardening-o34m-empty', port: '3185' };
const FIXTURE = 'docker-tests/fixtures/compose.before-db-auth.yaml';
// What isolated.mjs compose() runs; repeated here only for the calls that need stdin or a failing exit.
const ISOLATED_FILES = ['-f', 'compose.yaml', '-f', 'docker-tests/compose.isolated.yaml'];
const FLOW_TIMEOUT_MS = 45 * 60_000; // the ingest loads every law first, on a spinning disk
const BOOT_BUDGET_MS = 20 * 60_000; // then LibreChat has its 300 s start period
const UNAUTHENTICATED_URI = 'mongodb://mongo:27017/LibreChat?replicaSet=rs0';
const SECRET_MODES = [
  '/secrets/mongo_keyfile 400 999:999',
  '/secrets/mongo_admin_password 400 0:0',
  '/secrets/mongo_app_password 400 0:0',
  '/secrets/mongo_reader_password 400 0:0',
  '/secrets/mongo_uri 400 1000:1000',
];
const EXPECTED_USERS = { iqraa_admin: ['root@admin'], iqraa_app: ['readWrite@LibreChat'], iqraa_reader: ['read@LibreChat'] };

// mongosh scripts, fixed text with no secret in it; each reaches the container on stdin.
const SECRET = "const secret = (name) => require('fs').readFileSync('/secrets/' + name, 'utf8').trim();";
const AS_ADMIN = `${SECRET}\ndb.getSiblingDB('admin').auth('iqraa_admin', secret('mongo_admin_password'));`;
const SCRIPTS = {
  // Before O-34 no user exists, so a session needs no sign-in.
  seedWithoutAuth: (row) => `db.iqraa_probe.insertOne(${JSON.stringify(row)});\nprint(db.iqraa_probe.countDocuments({}));`,
  // On empty volumes no session without a sign-in is left: iqraa_admin, which the bootstrap made, writes the row.
  seedAsAdmin: (row) => `${AS_ADMIN}\ndb.getSiblingDB('LibreChat').iqraa_probe.insertOne(${JSON.stringify(row)});\nprint(db.getSiblingDB('LibreChat').iqraa_probe.countDocuments({}));`,
  readerWrite: (row) => `${SECRET}
db.auth('iqraa_reader', secret('mongo_reader_password'));
let write;
try {
  db.iqraa_probe.insertOne({ _id: 'o34m-reader-write' });
  write = 'written';
} catch (error) {
  write = error.codeName ?? error.message;
}
print(JSON.stringify({ read: db.iqraa_probe.countDocuments({ _id: ${JSON.stringify(row._id)} }), write }));`,
  users: () => `${AS_ADMIN}
const out = {};
for (const [name, home] of [['iqraa_admin', 'admin'], ['iqraa_app', 'LibreChat'], ['iqraa_reader', 'LibreChat']]) {
  const user = db.getSiblingDB(home).getUser(name);
  out[name] = user === null ? null : { roles: user.roles.map((r) => r.role + '@' + r.db).sort(), id: EJSON.stringify(user.userId) };
}
print(JSON.stringify(out));`,
  // The sessions LibreChat's container holds, idle ones included; a driver's monitoring connection has no user.
  connections: () => `${AS_ADMIN}
const client = process.env.O34M_CLIENT + ':';
const ops = db.getSiblingDB('admin').aggregate([{ $currentOp: { allUsers: true, idleConnections: true } }]).toArray();
const mine = ops.filter((op) => String(op.client ?? '').startsWith(client));
const signedIn = mine.filter((op) => (op.effectiveUsers ?? []).length > 0);
const users = [...new Set(signedIn.flatMap((op) => op.effectiveUsers.map((u) => u.user + '@' + u.db)))].sort();
print(JSON.stringify({ connections: mine.length, signedIn: signedIn.length, users }));`,
};

let image;

before(() => {
  image = buildRelease('o34m');
});

const envOf = (flow) => ({ IQRAA_IMAGE: image, IQRAA_ISOLATED_PORT: flow.port });

function guard(project) {
  if (!/^hardening-o34m-[a-z0-9-]+$/.test(project)) throw new Error(`refusing compose project "${project}"`);
}

/** A mongodb:// URI with its user and password, should one ever reach an error message. */
const redact = (text) => String(text ?? '').replace(/mongodb:\/\/[^@\s/]*@/g, 'mongodb://<redacted>@');

function docker(args, { input, env = {} } = {}) {
  const result = spawnSync('docker', args, {
    cwd: STAGING_DIR,
    env: { ...process.env, MSYS_NO_PATHCONV: '1', ...env },
    input,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  return result;
}

function ok(result, what) {
  if (result.status !== 0) throw new Error(`${what} exited ${result.status}:\n${redact(`${result.stderr}\n${result.stdout}`.trim().slice(-4000))}`);
  return result.stdout;
}

const lines = (text) => String(text ?? '').split('\n').map((line) => line.trim()).filter(Boolean);

const fixtureChecked = new Set();

/** `docker compose` on the pre-O-34 fixture, in deploy/staging; refuses a configuration with an iqraa/ image or a port. */
function fixture(flow, args, input) {
  guard(flow.project);
  const base = ['compose', '-p', flow.project, '--project-directory', '.', '-f', FIXTURE];
  if (!fixtureChecked.has(flow.project)) {
    const config = JSON.parse(ok(docker([...base, 'config', '--format', 'json'], { env: envOf(flow) }), 'fixture config'));
    const problems = [];
    if (config.name !== flow.project) problems.push(`the project resolves to "${config.name}"`);
    for (const [name, service] of Object.entries(config.services ?? {})) {
      if (/(^|\/)iqraa\//.test(String(service.image ?? ''))) problems.push(`${name} uses ${service.image}`);
      if ((service.ports ?? []).length > 0) problems.push(`${name} publishes a port`);
    }
    if (problems.length > 0) throw new Error(`refusing the fixture under ${flow.project}: ${problems.join('; ')}`);
    fixtureChecked.add(flow.project);
  }
  return docker([...base, ...args], { input, env: envOf(flow) });
}

/** `exec -T` in the real stack, with `input` on stdin; returns the raw result, so a refusal can be asserted. */
function execIn(flow, service, args, input) {
  guard(flow.project);
  return docker(['compose', '-p', flow.project, ...ISOLATED_FILES, 'exec', '-T', service, ...args], { input, env: envOf(flow) });
}

/** One of SCRIPTS through mongosh in a mongo container: written to /tmp from stdin, then run with --file. */
const RUN_STDIN = 'cat > "$0" && exec mongosh LibreChat --quiet --file "$0"';
const mongoScript = (flow, name, text, { viaFixture = false, env = [] } = {}) => {
  const args = ['sh', '-c', RUN_STDIN, `/tmp/o34m-${name}.js`];
  if (viaFixture) return fixture(flow, ['exec', '-T', 'mongo', ...args], text);
  guard(flow.project);
  return docker(['compose', '-p', flow.project, ...ISOLATED_FILES, 'exec', '-T', ...env.flatMap((e) => ['-e', e]), 'mongo', ...args], { input: text, env: envOf(flow) });
};

/** query.js as lib.mjs mongoQuery runs it: the request base64-encoded in IQRAA_QUERY. */
function queryJs(flow, query) {
  const encoded = Buffer.from(JSON.stringify(query), 'utf8').toString('base64');
  guard(flow.project);
  return docker(
    ['compose', '-p', flow.project, ...ISOLATED_FILES, 'exec', '-T', '-e', `IQRAA_QUERY=${encoded}`, 'mongo', 'mongosh', 'LibreChat', '--quiet', '--file', '/scripts/query.js'],
    { env: envOf(flow) },
  );
}

let unauthenticatedRuns = 0;

/** A count from a second container on the project's network that never signs in. */
function unauthenticatedRead(flow) {
  guard(flow.project);
  const config = JSON.parse(compose(flow.project, ['config', '--format', 'json'], envOf(flow)));
  unauthenticatedRuns += 1;
  return docker([
    'run', '--rm', '--name', `${flow.project}-unauth-${process.pid}-${unauthenticatedRuns}`, '--network', `${flow.project}_default`,
    config.services.mongo.image, 'mongosh', UNAUTHENTICATED_URI, '--quiet', '--eval', 'print(db.iqraa_probe.countDocuments({}))',
  ]);
}

const containerOf = (flow, service) => {
  const id = compose(flow.project, ['ps', '-q', service], envOf(flow)).trim();
  assert.ok(id, `no ${service} container`);
  return id;
};
const inspect = (id, format) => ok(docker(['inspect', '--format', format, id]), 'docker inspect').trim();

/** A subtest that also records its name in `failed`, so the flow knows to save the stack's logs. */
const stepper = (t, failed) => (name, fn) => t.test(name, async (st) => {
  try {
    await fn(st);
  } catch (error) {
    failed.push(name);
    throw error;
  }
});

function usersOf(flow) {
  return JSON.parse(lines(ok(mongoScript(flow, 'users', SCRIPTS.users()), 'users script')).pop());
}

/** The assertions both flows share, one subtest each, once the real compose.yaml answers /readyz. */
async function checkAuth(step, flow, row) {
  await step('the key file is 0400 for mongod (999), the passwords 0400 root, the URI 0400 for LibreChat (1000)', (st) => {
    const stat = ok(execIn(flow, 'mongo', ['stat', '-c', '%n %a %u:%g', ...SECRET_MODES.map((entry) => entry.split(' ')[0])]), 'stat');
    st.diagnostic(lines(stat).join(', '));
    assert.deepEqual(lines(stat), SECRET_MODES);
  });

  await step('a second container that does not sign in is refused', (st) => {
    const read = unauthenticatedRead(flow);
    const said = lines(`${read.stdout}\n${read.stderr}`).pop() ?? '';
    st.diagnostic(`exit ${read.status}: ${redact(said)}`);
    assert.notEqual(read.status, 0, 'an unauthenticated count succeeded');
    // A name or connection failure is no refusal.
    assert.match(said, /requires authentication/);
  });

  await step('query.js signs in as iqraa_reader and returns the row, on one JSON line', (st) => {
    const out = ok(queryJs(flow, { op: 'find', collection: 'iqraa_probe', filter: { _id: row._id } }), 'query.js');
    st.diagnostic(out.trim());
    assert.equal(lines(out).length, 1, 'query.js printed more than one line');
    assert.deepEqual(JSON.parse(lines(out)[0]), [row]);
  });

  await step('reconcile.js signs in as iqraa_reader, exits 0 and prints ok true on one JSON line', (st) => {
    const run = execIn(flow, 'mongo', ['mongosh', 'LibreChat', '--quiet', '--file', '/scripts/reconcile.js']);
    st.diagnostic(`exit ${run.status}: ${redact(run.stdout.trim()).slice(0, 600)} ${redact(run.stderr.trim()).slice(-600)}`);
    assert.equal(run.status, 0);
    assert.equal(lines(run.stdout).length, 1, 'reconcile.js printed more than one line');
    assert.equal(JSON.parse(lines(run.stdout)[0]).ok, true);
  });

  await step('iqraa_reader reads the row and is refused a write', (st) => {
    const out = ok(mongoScript(flow, 'reader-write', SCRIPTS.readerWrite(row)), 'reader script');
    st.diagnostic(out.trim());
    assert.deepEqual(JSON.parse(lines(out).pop()), { read: 1, write: 'Unauthorized' });
  });

  await step("lib.mjs's RUNNER, in LibreChat's container, signs in as iqraa_app and sends a code to the sink", (st) => {
    assert.equal(typeof lib.RUNNER, 'string', 'lib.mjs exports no RUNNER');
    const phone = `+96279${crypto.randomInt(0, 10_000_000).toString().padStart(7, '0')}`;
    const run = execIn(flow, 'librechat', ['sh', '-c', lib.RUNNER, 'iqraa-bootstrap-staff', 'request', '--phone', phone]);
    st.diagnostic(`request --phone ${phone}: exit ${run.status}, ${redact(lines(run.stdout).pop() ?? '')} ${redact(lines(run.stderr).pop() ?? '')}`);
    assert.equal(run.status, 0);
    assert.deepEqual(JSON.parse(lines(run.stdout).pop()), { sent: true });
    // Read back as iqraa_reader; neither the row nor its code is printed.
    const sink = JSON.parse(lines(ok(queryJs(flow, { op: 'find', collection: 'iqraa_auth_sink', filter: { to: phone } }), 'query.js sink')).pop());
    assert.equal(sink.length, 1, `${sink.length} sink rows for ${phone}`);
  });

  await step('LibreChat is signed in as iqraa_app, which has readWrite on LibreChat only, and has no MONGO_URI in its environment', (st) => {
    const librechat = containerOf(flow, 'librechat');
    const environment = JSON.parse(inspect(librechat, '{{json .Config.Env}}'));
    assert.deepEqual(environment.filter((entry) => entry.startsWith('MONGO_URI=')).map(() => 'MONGO_URI=<redacted>'), []);
    const ip = inspect(librechat, '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}').split(' ')[0];
    const seen = JSON.parse(lines(ok(mongoScript(flow, 'connections', SCRIPTS.connections(), { env: [`O34M_CLIENT=${ip}`] }), 'connections script')).pop());
    const users = usersOf(flow);
    st.diagnostic(`LibreChat (${ip}): ${JSON.stringify(seen)}; roles: ${JSON.stringify(Object.fromEntries(Object.entries(users).map(([name, u]) => [name, u?.roles ?? null])))}`);
    assert.ok(seen.signedIn > 0, 'LibreChat holds no signed-in connection');
    assert.deepEqual(seen.users, ['iqraa_app@LibreChat']);
    assert.deepEqual(Object.fromEntries(Object.entries(users).map(([name, u]) => [name, u?.roles ?? null])), EXPECTED_USERS);
  });

  await step("LibreChat's container (uid 1000) cannot read mongo's passwords or its key file", (st) => {
    assert.equal(ok(execIn(flow, 'librechat', ['id', '-u']), 'id -u').trim(), '1000');
    for (const file of ['mongo_admin_password', 'mongo_app_password', 'mongo_reader_password', 'mongo_keyfile']) {
      // Into /dev/null: if the read worked, its output would be the secret.
      const read = execIn(flow, 'librechat', ['sh', '-c', 'cat -- "$0" > /dev/null', `/secrets/${file}`]);
      st.diagnostic(`cat /secrets/${file}: exit ${read.status}, ${read.stderr.trim()}`);
      assert.notEqual(read.status, 0, `librechat read /secrets/${file}`);
      assert.match(read.stderr, /Permission denied/);
    }
  });

  await step('a second pass of the bootstrap exits 0 and changes no user', (st) => {
    const before = usersOf(flow);
    const run = execIn(flow, 'mongo', ['mongosh', '--quiet', '--file', '/scripts/mongo-bootstrap.js']);
    st.diagnostic(`exit ${run.status}: ${redact(run.stdout.trim())} ${redact(run.stderr.trim()).slice(-300)}`);
    assert.equal(run.status, 0);
    assert.deepEqual(usersOf(flow), before);
  });
}

async function flow(t, target, body) {
  // Another stack answering on the port would pass /readyz for this one.
  const busy = await fetch(`http://127.0.0.1:${target.port}/`, { signal: AbortSignal.timeout(3000) }).then(() => true, () => false);
  assert.equal(busy, false, `something already answers on 127.0.0.1:${target.port}`);
  destroy(target.project, envOf(target)); // a run that died before its cleanup: start from empty volumes
  const failed = [];
  try {
    ensureLegalSearch(target.project, envOf(target));
    await body(stepper(t, failed));
  } catch (error) {
    failed.push(error.message.split('\n')[0]);
    throw error;
  } finally {
    if (failed.length > 0) {
      try {
        t.diagnostic(`the stack's logs: ${saveLogs(target.project, envOf(target))}`);
      } catch (saving) {
        t.diagnostic(`its logs could not be saved: ${saving.message.split('\n')[0]}`);
      }
    }
    destroy(target.project, envOf(target));
  }
}

/** The real compose.yaml up to the proxy (not `up --wait`: the one-shots exit), then /readyz through it. */
async function upToReady(target) {
  const started = Date.now();
  compose(target.project, ['up', '-d', 'proxy'], envOf(target));
  await waitReady(target.port, Math.max(0, BOOT_BUDGET_MS - (Date.now() - started)));
}

test('upgrade: a volume mongod wrote without authentication takes it in place', { timeout: FLOW_TIMEOUT_MS }, (t) =>
  flow(t, UPGRADE, async (step) => {
    const row = { _id: 'o34m-probe', note: 'written before database auth' };
    // The release before O-34: its secrets-init, then mongod with no --keyFile, initiated by its health check.
    ok(fixture(UPGRADE, ['up', '-d', 'secrets-init']), 'fixture up secrets-init');
    const init = lines(ok(fixture(UPGRADE, ['ps', '-a', '-q', 'secrets-init']), 'fixture ps'))[0];
    assert.equal(ok(docker(['wait', init]), 'docker wait').trim(), '0', 'the fixture secrets-init failed');
    ok(fixture(UPGRADE, ['up', '-d', '--wait', '--wait-timeout', '300', 'mongo']), 'fixture up mongo');
    let unauthenticated = false;
    await step('before: mongod takes a row with no sign-in, and a second container reads it with none', (st) => {
      const seeded = lines(ok(mongoScript(UPGRADE, 'seed', SCRIPTS.seedWithoutAuth(row), { viaFixture: true }), 'seed')).pop();
      const read = unauthenticatedRead(UPGRADE);
      st.diagnostic(`seeded, count ${seeded}; unauthenticated count from a second container: exit ${read.status}, ${lines(`${read.stdout}\n${read.stderr}`).pop()}`);
      assert.equal(seeded, '1');
      assert.equal(read.status, 0);
      assert.equal(lines(read.stdout).pop(), '1');
      unauthenticated = true;
    });
    assert.ok(unauthenticated, 'the release before O-34 did not come up without authentication');

    await upToReady(UPGRADE);
    await checkAuth(step, UPGRADE, row);
  }));

test('empty volumes: the real compose.yaml from nothing', { timeout: FLOW_TIMEOUT_MS }, (t) =>
  flow(t, EMPTY, async (step) => {
    const row = { _id: 'o34m-probe', note: 'written as iqraa_admin' };
    await upToReady(EMPTY);
    await step('iqraa_admin, which the bootstrap made, writes a row', (st) => {
      const seeded = lines(ok(mongoScript(EMPTY, 'seed', SCRIPTS.seedAsAdmin(row)), 'seed as iqraa_admin')).pop();
      st.diagnostic(`count ${seeded}`);
      assert.equal(seeded, '1');
    });
    await checkAuth(step, EMPTY, row);
  }));
