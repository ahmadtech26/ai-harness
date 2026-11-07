// O-102: reconcile-daily runs scripts/reconcile.js on a schedule. Each run writes /reports/reconcile-<UTC date>.json and
// logs `reconcile ok <its JSON>`, or `ALERT reconcile_failed status=<n> <output>` when an invariant fails, and the loop
// goes on after a failure: Docker's restart policy must not be what keeps it alive.
//   node --test deploy/staging/docker-tests/reconcile-daily.test.mjs
// Project hardening-o102 with RECONCILE_INTERVAL_SECONDS=5: secrets-init, mongo and reconcile-daily only (its
// depends_on), no port published, no image built; removed, volumes included, before and after. The unbalanced posting
// is written as iqraa_admin by a mongosh script that reaches a file in the mongo container on stdin and reads the
// password from /secrets there, so no password reaches a command line or this test's output.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import { test } from 'node:test';
import { compose, DEFAULT_RELEASE, destroy, saveLogs, STAGING_DIR } from './isolated.mjs';

const PROJECT = 'hardening-o102';
const ENV = { RECONCILE_INTERVAL_SECONDS: '5' };
// What isolated.mjs compose() runs; repeated here only for the calls that need stdin or both output streams.
const ISOLATED_FILES = ['-f', 'compose.yaml', '-f', 'docker-tests/compose.isolated.yaml'];
const FLOW_TIMEOUT_MS = 20 * 60_000; // mongo's first start on a spinning disk, then a few five-second rounds
const LINE_BUDGET_MS = 3 * 60_000;
const REPORT = /^reconcile-(\d{4}-\d{2}-\d{2})\.json$/;

const SECRET = "const secret = (name) => require('fs').readFileSync('/secrets/' + name, 'utf8').trim();";
/** A mongosh script, fixed text with no secret in it: one posting of `amount` on `txId`, as iqraa_admin. */
const POSTING = (txId, amount) => `${SECRET}
db.getSiblingDB('admin').auth('iqraa_admin', secret('mongo_admin_password'));
const written = db.getSiblingDB('LibreChat').iqraa_postings.insertOne({
  txId: ${JSON.stringify(txId)}, account: 'user:o102-probe:available', kind: 'o102-probe', amount: ${Number(amount)}, createdAt: new Date(),
});
print(JSON.stringify({ acknowledged: written.acknowledged }));`;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
/** The JSON object an ALERT line carries after its status, before any stderr text the line appends. */
function jsonIn(line) {
  const start = line.indexOf('{');
  for (let end = line.lastIndexOf('}'); end > start; end = line.lastIndexOf('}', end - 1)) {
    try {
      return JSON.parse(line.slice(start, end + 1));
    } catch {
      // a shorter span
    }
  }
  throw new Error(`no JSON object in: ${line.slice(0, 400)}`);
}
const lines = (text) => String(text ?? '').split('\n').map((line) => line.trim()).filter(Boolean);
/** A mongodb:// URI with its user and password, should one ever reach an error message. */
const redact = (text) => String(text ?? '').replace(/mongodb:\/\/[^@\s/]*@/g, 'mongodb://<redacted>@');

function docker(args, { input } = {}) {
  const result = spawnSync('docker', args, {
    cwd: STAGING_DIR,
    env: { ...process.env, MSYS_NO_PATHCONV: '1', IQRAA_IMAGE: DEFAULT_RELEASE, ...ENV },
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

const containerOf = (service) => {
  const id = compose(PROJECT, ['ps', '-q', service], ENV).trim();
  assert.ok(id, `no running ${service} container`);
  return id;
};
const inspect = (id, format) => ok(docker(['inspect', '--format', format, id]), 'docker inspect').trim();

/** Every line reconcile-daily has logged, stdout and stderr both (the ALERT goes to stderr). */
const logOf = (id) => {
  const result = docker(['logs', id]);
  ok(result, 'docker logs');
  return lines(`${result.stdout}\n${result.stderr}`);
};

/** Polls the log until `count` lines match `pattern`; returns the matching lines. */
async function waitForLines(id, pattern, count = 1) {
  const deadline = Date.now() + LINE_BUDGET_MS;
  let seen = [];
  while (Date.now() < deadline) {
    seen = logOf(id).filter((line) => pattern.test(line));
    if (seen.length >= count) return seen;
    await sleep(2000);
  }
  const tail = logOf(id).slice(-8).map((line) => redact(line).slice(0, 400));
  throw new Error(`${seen.length} of ${count} lines matching ${pattern} within ${LINE_BUDGET_MS} ms; the log ends:\n${tail.join('\n')}`);
}

/** The posting script through mongosh in the mongo container: written to /tmp from stdin, then run with --file. */
function post(txId, amount) {
  const run = docker(
    ['compose', '-p', PROJECT, ...ISOLATED_FILES, 'exec', '-T', 'mongo', 'sh', '-c', 'cat > "$0" && exec mongosh --quiet --file "$0"', `/tmp/o102-posting-${amount < 0 ? 'minus' : 'plus'}.js`],
    { input: POSTING(txId, amount) },
  );
  return JSON.parse(lines(ok(run, 'the posting script')).pop());
}

/** The report files in staging-reports, and the content of the one named for `date`. */
function reports() {
  const out = ok(docker(['compose', '-p', PROJECT, ...ISOLATED_FILES, 'exec', '-T', 'reconcile-daily', 'sh', '-c', 'date -u +%F; ls -1 /reports']), 'ls /reports');
  const [date, ...files] = lines(out);
  return { date, files };
}
const reportText = (name) => ok(docker(['compose', '-p', PROJECT, ...ISOLATED_FILES, 'exec', '-T', 'reconcile-daily', 'cat', `/reports/${name}`]), `cat /reports/${name}`);

test('reconcile-daily writes a report and logs ok, raises an ALERT on an unbalanced transaction, and keeps looping', { timeout: FLOW_TIMEOUT_MS }, async (t) => {
  destroy(PROJECT, ENV); // a run that died before its cleanup: start from empty volumes
  let failed = false;
  try {
    compose(PROJECT, ['up', '-d', 'reconcile-daily'], ENV);
    const services = lines(compose(PROJECT, ['ps', '-a', '--format', '{{.Service}}'], ENV)).sort();
    assert.deepEqual(services, ['mongo', 'reconcile-daily', 'secrets-init']);
    const id = containerOf('reconcile-daily');

    // An ALERT before the first ok is possible (an election just after mongo turns healthy), so none is asserted absent.
    const [first] = await waitForLines(id, /^reconcile ok \{/);
    const clean = JSON.parse(first.slice('reconcile ok '.length));
    t.diagnostic(redact(first).slice(0, 600));
    assert.equal(clean.ok, true);
    assert.deepEqual(clean.problems, []);

    const before = reports();
    t.diagnostic(`container date ${before.date}; /reports: ${before.files.join(', ')}`);
    const named = before.files.filter((name) => REPORT.test(name));
    assert.deepEqual(named, [`reconcile-${before.date}.json`], `the reports are ${JSON.stringify(before.files)}`);
    const report = JSON.parse(reportText(named[0]).trim());
    assert.equal(report.ok, true);
    assert.deepEqual(report.problems, []);

    const startedAt = inspect(id, '{{.State.StartedAt}}');
    const txId = `o102-unbalanced-${crypto.randomBytes(4).toString('hex')}`;
    assert.deepEqual(post(txId, 5), { acknowledged: true });
    const alert = new RegExp(`^ALERT reconcile_failed status=1 .*transaction ${txId} sums to 5`);
    const [raised] = await waitForLines(id, alert);
    t.diagnostic(redact(raised).slice(0, 600));
    const failure = jsonIn(raised);
    assert.equal(failure.ok, false);
    assert.ok(failure.problems.includes(`transaction ${txId} sums to 5`), JSON.stringify(failure.problems));
    const failedReport = JSON.parse(reportText(`reconcile-${reports().date}.json`).trim());
    assert.equal(failedReport.ok, false, 'the report does not hold the failed run');
    assert.ok(failedReport.problems.includes(`transaction ${txId} sums to 5`), JSON.stringify(failedReport.problems));

    // The same container, never restarted, logs the next round: the loop survived the failure itself.
    await waitForLines(id, alert, 2);
    assert.equal(inspect(id, '{{.State.Running}} {{.RestartCount}} {{.State.StartedAt}}'), `true 0 ${startedAt}`);

    // And it recovers once the transaction balances.
    const oks = logOf(id).filter((line) => line.startsWith('reconcile ok ')).length;
    assert.deepEqual(post(txId, -5), { acknowledged: true });
    const recovered = (await waitForLines(id, /^reconcile ok \{/, oks + 1)).at(-1);
    assert.equal(JSON.parse(recovered.slice('reconcile ok '.length)).ok, true);
    assert.equal(inspect(id, '{{.State.Running}} {{.RestartCount}} {{.State.StartedAt}}'), `true 0 ${startedAt}`);

    const format = '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.RestartPolicy.Name}} {{.HostConfig.LogConfig.Type}} {{.State.OOMKilled}}';
    const [memory, cpus, restart, driver, oomKilled] = inspect(id, format).split(' ');
    const peak = docker(['exec', id, 'cat', '/sys/fs/cgroup/memory.peak']);
    t.diagnostic(`limits: memory ${memory}, NanoCpus ${cpus}, restart ${restart}, log ${driver}, OOMKilled ${oomKilled}; memory.peak ${peak.status === 0 ? peak.stdout.trim() : 'unreadable'}`);
    assert.ok(Number(memory) > 0 && Number(cpus) > 0, `memory ${memory}, NanoCpus ${cpus}`);
    assert.deepEqual([restart, driver, oomKilled], ['unless-stopped', 'json-file', 'false']);

    // What `docker inspect` shows of the running container carries no password and no URI with one.
    const shown = inspect(id, '{{json .Config.Entrypoint}} {{json .Config.Cmd}} {{json .Config.Env}}');
    assert.doesNotMatch(shown, /mongodb:\/\/[^\s'"/]*@/);
    assert.doesNotMatch(shown, /\/secrets\//);

    // A stop's TERM ends a long sleep at once: sh as PID 1 ignores it, or runs its trap only once a foreground sleep
    // ends, and Docker kills the container when the stop's timeout runs out. A five-second sleep would end first.
    const long = { RECONCILE_INTERVAL_SECONDS: '3600' };
    compose(PROJECT, ['up', '-d', '--no-deps', '--force-recreate', 'reconcile-daily'], long);
    const sleeper = compose(PROJECT, ['ps', '-q', 'reconcile-daily'], long).trim();
    assert.ok(sleeper && sleeper !== id, 'reconcile-daily was not recreated');
    assert.match(inspect(sleeper, '{{json .Config.Entrypoint}}'), /sleep 3600 /);
    await waitForLines(sleeper, /^reconcile ok \{/);
    const stopping = Date.now();
    compose(PROJECT, ['stop', '-t', '30', 'reconcile-daily'], long);
    const stopMs = Date.now() - stopping;
    const exit = inspect(sleeper, '{{.State.Running}} {{.State.ExitCode}}');
    t.diagnostic(`stop took ${stopMs} ms; running, exit code: ${exit}`);
    assert.equal(exit, 'false 0');
    assert.ok(stopMs < 15_000, `stop took ${stopMs} ms`);
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    if (failed) {
      try {
        t.diagnostic(`the project's logs: ${saveLogs(PROJECT, ENV)}`);
      } catch (saving) {
        t.diagnostic(`its logs could not be saved: ${saving.message.split('\n')[0]}`);
      }
    }
    destroy(PROJECT, ENV);
  }
});
