// The staging stack's operating contract (O-34, O-46, O-68, O-69, O-102): what `docker compose config` resolves compose.yaml
// to with no IQRAA_ variable and an empty env file, so every default is the one checked. `config` starts nothing,
// pulls nothing and reads no secret:
//   node --test deploy/staging/compose.contract.test.mjs
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const LONG_RUNNING = ['mongo', 'postgres', 'legal-search', 'mock-llm', 'librechat', 'proxy', 'reconcile-daily'];
const ONE_SHOT = ['secrets-init', 'postgres-roles', 'legal-search-ingest'];
// LibreChat's writable folders (api/config/paths.js uploads and imageOutput; winston under the cwd /app/api).
const DATA_VOLUMES = { 'staging-uploads': '/app/uploads', 'staging-images': '/app/client/public/images', 'staging-logs': '/app/api/logs' };

const scratch = mkdtempSync(path.join(os.tmpdir(), 'compose-contract-'));
after(() => rmSync(scratch, { recursive: true, force: true }));
// An empty env file in place of a .env beside compose.yaml, which compose would otherwise read.
const emptyEnv = path.join(scratch, 'empty.env');
writeFileSync(emptyEnv, '');

function resolve(vars = {}) {
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(IQRAA|COMPOSE|RECONCILE)_/.test(key)));
  const run = spawnSync('docker', ['compose', '--env-file', emptyEnv, '-f', 'compose.yaml', 'config', '--format', 'json'], {
    cwd: HERE,
    encoding: 'utf8',
    env: { ...env, MSYS_NO_PATHCONV: '1', ...vars },
  });
  if (run.error) throw run.error;
  assert.equal(run.status, 0, `docker compose config exited ${run.status}: ${run.stderr}`);
  return JSON.parse(run.stdout);
}

const config = resolve();
const services = config.services;

test('the stack has the services this contract names, and no other', () => {
  assert.deepEqual(Object.keys(services).sort(), [...LONG_RUNNING, ...ONE_SHOT].sort());
});

test('every service rotates its log: json-file, 5 files of 20 MB', () => {
  const wrong = Object.entries(services)
    .filter(([, s]) => s.logging?.driver !== 'json-file' || s.logging?.options?.['max-size'] !== '20m' || s.logging?.options?.['max-file'] !== '5')
    .map(([name, s]) => `${name}: ${JSON.stringify(s.logging ?? null)}`);
  assert.deepEqual(wrong, []);
});

test('the long-running services restart unless stopped; the one-shots never restart', () => {
  const policies = Object.fromEntries(Object.entries(services).map(([name, s]) => [name, s.restart ?? null]));
  assert.deepEqual(policies, {
    ...Object.fromEntries(LONG_RUNNING.map((name) => [name, 'unless-stopped'])),
    ...Object.fromEntries(ONE_SHOT.map((name) => [name, 'no'])),
  });
});

test('every long-running service and the ingest have a memory and a CPU limit, the CPUs at most 2 by default', () => {
  const wrong = [...LONG_RUNNING, 'legal-search-ingest']
    .map((name) => [name, services[name]])
    .filter(([, s]) => !(Number(s.mem_limit) > 0) || !(Number(s.cpus) > 0) || Number(s.cpus) > 2)
    .map(([name, s]) => `${name}: mem_limit ${s.mem_limit}, cpus ${s.cpus}`);
  // A cpus value above the host's CPU count makes Docker refuse the container, so the defaults fit a small server.
  assert.deepEqual(wrong, []);
});

test('LibreChat is healthy only once /readyz answers, not /health', () => {
  const check = services.librechat.healthcheck;
  assert.ok(check?.test, 'librechat has no health check');
  assert.ok(check.test.some((arg) => arg.endsWith('/readyz')), JSON.stringify(check.test));
  assert.equal(check.test.some((arg) => arg.includes('/health')), false, JSON.stringify(check.test));
  assert.ok(check.start_period, 'no start_period: a slow first start would count as failures');
});

test('the proxy opens only once LibreChat is healthy', () => {
  assert.equal(services.proxy.depends_on?.librechat?.condition, 'service_healthy');
});

test('LibreChat keeps uploads, images and logs in named volumes, which secrets-init hands to uid 1000', () => {
  const mounted = (service) => Object.fromEntries((service.volumes ?? []).filter((v) => v.type === 'volume').map((v) => [v.source, v.target]));
  const librechat = mounted(services.librechat);
  const init = mounted(services['secrets-init']);
  for (const [volume, target] of Object.entries(DATA_VOLUMES)) {
    assert.equal(librechat[volume], target, `librechat mounts ${volume} at ${librechat[volume]}`);
    assert.match(init[volume] ?? '', /^\/volumes\//, `secrets-init mounts ${volume} at ${init[volume]}`);
    assert.ok(config.volumes?.[volume], `${volume} is not a top-level volume`);
  }
  assert.ok(services['secrets-init'].entrypoint.join('\n').includes("execSync('chown -R 1000:1000 /volumes')"));
});

// O-34: legal-search connects as legal_app, which postgres-roles creates and hands the schema to; an ingest that ran
// before it would write as a role that does not exist yet, or, on an old volume, into tables legal_app cannot alter.
test('the ingest waits for postgres-roles, which runs once Postgres is healthy and the secrets exist', () => {
  const roles = services['postgres-roles'];
  assert.ok(roles, 'no postgres-roles service');
  assert.equal(services['legal-search-ingest'].depends_on?.['postgres-roles']?.condition, 'service_completed_successfully');
  assert.equal(roles.depends_on?.postgres?.condition, 'service_healthy');
  assert.equal(roles.depends_on?.['secrets-init']?.condition, 'service_completed_successfully');
  // Its psql must be the server's own version, and the image is already pinned and pulled for postgres.
  assert.equal(roles.image, services.postgres.image);
});

// O-34: the secrets volume holds mongod's replica-set key, owned by uid 999 so that mongod can read it, and the pgvector
// image runs its server as uid 999 too. Holding the key signs in as __system, past every MongoDB user. So postgres and
// postgres-roles mount only the files they read, each by its subpath, read-only; the server's uid reads none of them.
test('postgres and postgres-roles mount only their own secret files, never the whole secrets volume', () => {
  const own = { postgres: ['pg_password'], 'postgres-roles': ['pg_app_password', 'pg_password'] };
  for (const [name, files] of Object.entries(own)) {
    const secrets = (services[name].volumes ?? []).filter((volume) => volume.source === 'staging-secrets');
    assert.deepEqual(secrets.map((volume) => volume.volume?.subpath).sort(), files, `${name}: ${JSON.stringify(secrets)}`);
    for (const volume of secrets) {
      assert.equal(volume.target, `/secrets/${volume.volume.subpath}`, `${name}: ${JSON.stringify(volume)}`);
      assert.equal(volume.read_only, true, `${name} mounts /secrets/${volume.volume.subpath} writable`);
    }
  }
  assert.equal(services.postgres.environment?.POSTGRES_PASSWORD_FILE, '/secrets/pg_password');
});

// O-34: --keyFile turns MongoDB's authorization on; the key and the passwords come from the secrets volume, which
// secrets-init fills first. MONGO_INITDB_* would apply to an empty volume only, so an upgraded one would keep no user.
test('mongod requires authentication, with the key file from the secrets volume, after secrets-init', () => {
  const mongo = services.mongo;
  const command = mongo.command ?? [];
  assert.equal(command[command.indexOf('--keyFile') + 1], '/secrets/mongo_keyfile', JSON.stringify(command));
  assert.equal(mongo.depends_on?.['secrets-init']?.condition, 'service_completed_successfully');
  const secrets = (mongo.volumes ?? []).find((v) => v.source === 'staging-secrets');
  assert.equal(secrets?.target, '/secrets');
  assert.equal(secrets?.read_only, true, 'mongo mounts the secrets writable');
  assert.deepEqual(Object.keys(mongo.environment ?? {}).filter((key) => key.startsWith('MONGO_INITDB')), []);
});

// The health check initiates the replica set and creates the users, so a healthy mongo is one LibreChat can sign in to.
test("mongo's health check is the bootstrap script, with a start period; LibreChat waits for it", () => {
  const check = services.mongo.healthcheck;
  assert.deepEqual(check?.test, ['CMD', 'mongosh', '--quiet', '--file', '/scripts/mongo-bootstrap.js']);
  assert.ok(check.start_period, 'no start_period: the first start would count as failures');
  assert.equal(services.librechat.depends_on?.mongo?.condition, 'service_healthy');
});

// In the environment, the URI and its password would show in `docker inspect` and in every exec session.
test('LibreChat has no MONGO_URI in its environment; its entrypoint reads it from the secrets volume', () => {
  assert.equal('MONGO_URI' in (services.librechat.environment ?? {}), false, 'librechat still sets MONGO_URI');
  // `config` prints the file's $$ escape as it is (Compose v5.6.0).
  assert.match(services.librechat.entrypoint.join('\n'), /MONGO_URI=\$\$?\(cat \/secrets\/mongo_uri\)/);
});

test('the concurrent-message limiter is on, above scenario 8\'s six parallel chats; the message limit stays', () => {
  const env = services.librechat.environment;
  assert.equal(env.LIMIT_CONCURRENT_MESSAGES, 'true');
  assert.ok(Number(env.CONCURRENT_MESSAGE_MAX) > 6, `CONCURRENT_MESSAGE_MAX is ${env.CONCURRENT_MESSAGE_MAX}`);
  assert.deepEqual([env.LIMIT_MESSAGE_USER, env.MESSAGE_USER_MAX, env.MESSAGE_USER_WINDOW], ['true', '30', '1']);
});

// O-102: reconcile.js runs on a schedule, not only when the driver or an operator calls it. The loop itself, its report
// file and its ALERT line are proven in a container by docker-tests/reconcile-daily.test.mjs.
const RECONCILE_URI = 'mongodb://mongo:27017/LibreChat?replicaSet=rs0';
const reconcileCommand = (c) => [...(c.services['reconcile-daily']?.entrypoint ?? []), ...(c.services['reconcile-daily']?.command ?? [])].join('\n');

test('reconcile-daily runs reconcile.js with mongo\'s pinned image once mongo is healthy, with the scripts and secrets read-only', () => {
  const daily = services['reconcile-daily'];
  assert.ok(daily, 'no reconcile-daily service');
  assert.equal(daily.image, services.mongo.image);
  assert.equal(daily.depends_on?.mongo?.condition, 'service_healthy');
  assert.equal(daily.depends_on?.['secrets-init']?.condition, 'service_completed_successfully');
  const mounts = Object.fromEntries((daily.volumes ?? []).map((v) => [v.target, v]));
  assert.equal(mounts['/scripts']?.type, 'bind');
  assert.equal(path.basename(mounts['/scripts'].source), 'scripts');
  assert.equal(mounts['/scripts'].read_only, true, 'reconcile-daily mounts the scripts writable');
  assert.equal(mounts['/secrets']?.source, 'staging-secrets');
  assert.equal(mounts['/secrets'].read_only, true, 'reconcile-daily mounts the secrets writable');
  assert.equal(mounts['/reports']?.source, 'staging-reports');
  assert.ok(config.volumes?.['staging-reports'], 'staging-reports is not a top-level volume');
  const command = reconcileCommand(config);
  assert.ok(command.includes(`mongosh '${RECONCILE_URI}' --quiet --file /scripts/reconcile.js`), command);
  assert.match(command, /\/reports\/reconcile-/);
  assert.match(command, /ALERT reconcile_failed status=/);
});

test('reconcile-daily has a low memory and CPU limit', () => {
  const daily = services['reconcile-daily'];
  assert.ok(Number(daily?.mem_limit) > 0 && Number(daily.mem_limit) <= 512 * 1024 * 1024, `mem_limit ${daily?.mem_limit}`);
  assert.ok(Number(daily.cpus) > 0 && Number(daily.cpus) <= 1, `cpus ${daily.cpus}`);
});

test('reconcile-daily sleeps a day by default; RECONCILE_INTERVAL_SECONDS shortens it', () => {
  assert.match(reconcileCommand(config), /\bsleep 86400\b/);
  assert.match(reconcileCommand(resolve({ RECONCILE_INTERVAL_SECONDS: '5' })), /\bsleep 5\b/);
});

// reconcile.js signs in as iqraa_reader from /secrets inside the container (hardening-14), so neither the command nor
// the environment, which `docker inspect` shows, needs a password or a URI that carries one.
test('reconcile-daily holds no secret in its command or its environment', () => {
  const daily = services['reconcile-daily'];
  assert.ok(daily, 'no reconcile-daily service');
  const command = reconcileCommand(config);
  assert.doesNotMatch(command, /mongodb(\+srv)?:\/\/[^\s'"/]*@/, 'a URI with a user in it');
  assert.doesNotMatch(command, /\/secrets\//, 'the command reads the secrets volume itself');
  const mongosh = command.split('\n').filter((line) => line.includes('mongosh'));
  assert.ok(mongosh.length > 0, command);
  for (const line of mongosh) assert.doesNotMatch(line, /(^|\s)(--password|--username|--authenticationDatabase|-p|-u)(\s|=|$)/, line);
  assert.deepEqual(Object.keys(daily.environment ?? {}).filter((key) => /PASS|SECRET|TOKEN|KEY|URI|AUTH/i.test(key)), []);
});

const published = (c) => c.services.proxy.ports.map((p) => `${p.host_ip}:${p.published}->${p.target}`);
const origins = (c) => [c.services.librechat.environment.DOMAIN_CLIENT, c.services.librechat.environment.DOMAIN_SERVER];

test('with no IQRAA_PORT the proxy publishes 127.0.0.1:3080 and LibreChat names that origin', () => {
  assert.deepEqual(published(config), ['127.0.0.1:3080->8080']);
  assert.deepEqual(origins(config), ['http://localhost:3080', 'http://localhost:3080']);
});

test('IQRAA_PORT moves the published port and both origins together', () => {
  const moved = resolve({ IQRAA_PORT: '3099' });
  assert.deepEqual(published(moved), ['127.0.0.1:3099->8080']);
  assert.deepEqual(origins(moved), ['http://localhost:3099', 'http://localhost:3099']);
});
