// O-40: the release image runs as node (uid 1000), writes where LibreChat writes and nowhere in its code or skills.
//   node --test deploy/staging/docker-tests/nonroot.test.mjs
// Builds hardening-test/release:o40 from deploy/release/Dockerfile, probes it, then boots it in the isolated project
// hardening-o40 on 127.0.0.1:3186 (staging keeps 3080, the client previews 3091-3097 and stack-ops 3098) and removes
// that project, volumes included, afterwards.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { before, test } from 'node:test';
import { buildRelease, compose, destroy, ensureLegalSearch, saveLogs, waitReady } from './isolated.mjs';

const PROJECT = 'hardening-o40';
const PORT = '3186';
// multer and Files/Local (api/config/paths.js uploads, imageOutput), winston (api/logs under the cwd /app/api), and
// the image's 1777 /app/data.
const WRITABLE = ['/app/uploads', '/app/api/logs', '/app/client/public/images', '/app/data'];
const READ_ONLY = ['/app/skill', '/app/api/server'];
const BOOT_BUDGET_MS = 10 * 60_000; // the ingest loads every law first, on a spinning disk

let image;
let probesPassed = false;

before(() => {
  image = buildRelease('o40');
});

let probes = 0;

function probe(script) {
  // A fresh name each time: `run --rm` can return before the daemon has removed the previous container.
  probes += 1;
  const name = `hardening-o40-probe-${process.pid}-${probes}`;
  const result = spawnSync('docker', ['run', '--rm', '--name', name, '--entrypoint', 'sh', image, '-c', script], {
    encoding: 'utf8',
    env: { ...process.env, MSYS_NO_PATHCONV: '1' },
  });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, `probe failed: ${result.stderr}`);
  return result.stdout;
}

// The harness itself: `ps` would be harmless if a refusal ever let it through.
test('compose refuses a project, image or port that could reach staging', () => {
  assert.throws(() => compose('iqraa-staging', ['ps']), /isolated projects are named hardening-/);
  assert.throws(() => compose(PROJECT, ['ps'], { IQRAA_IMAGE: 'iqraa/release:staging' }), /librechat uses iqraa\/release:staging/);
  assert.throws(() => compose(PROJECT, ['ps'], { IQRAA_IMAGE: image, IQRAA_ISOLATED_PORT: '3080' }), /proxy publishes 3080/);
});

// Run from the main tree, a writable bind would write into staging's own folders: mock-llm's ./out holds the
// llm-requests.jsonl that scenarios.mjs reconciles against.
test('the isolated stack mounts no host folder writable', () => {
  const config = JSON.parse(compose(PROJECT, ['config', '--format', 'json'], { IQRAA_IMAGE: image }));
  const writable = Object.entries(config.services).flatMap(([name, service]) =>
    (service.volumes ?? []).filter((v) => v.type === 'bind' && !v.read_only).map((v) => `${name}: ${v.source} -> ${v.target}`),
  );
  assert.deepEqual(writable, []);
});

test('the release image runs as node and can write only to the data folders', () => {
  assert.equal(probe('id -u').trim(), '1000');
  const dirs = [...WRITABLE, ...READ_ONLY];
  const out = probe(`for d in ${dirs.join(' ')}; do if touch "$d/.o40-probe" 2>/dev/null; then echo "$d writable"; else echo "$d denied"; fi; done`);
  assert.deepEqual(
    out.trim().split('\n'),
    [...WRITABLE.map((d) => `${d} writable`), ...READ_ONLY.map((d) => `${d} denied`)],
  );
  probesPassed = true;
});

test('the release boots as node in an isolated stack, with no permission error', { timeout: 40 * 60_000 }, async (t) => {
  if (!probesPassed) {
    t.skip('the image probes failed, so a boot would only repeat them');
    return;
  }
  const env = { IQRAA_IMAGE: image, IQRAA_ISOLATED_PORT: PORT };
  // Another stack answering on the port would pass /readyz for this one.
  const busy = await fetch(`http://127.0.0.1:${PORT}/`, { signal: AbortSignal.timeout(3000) }).then(() => true, () => false);
  assert.equal(busy, false, `something already answers on 127.0.0.1:${PORT}`);
  destroy(PROJECT, env); // a run that died before its cleanup: start from empty volumes
  try {
    ensureLegalSearch(PROJECT, env);
    const started = Date.now();
    // Not `up --wait`: secrets-init and legal-search-ingest exit once done.
    compose(PROJECT, ['up', '-d', 'proxy'], env);
    await waitReady(PORT, Math.max(0, BOOT_BUDGET_MS - (Date.now() - started)));

    assert.equal(compose(PROJECT, ['exec', '-T', 'librechat', 'id', '-u'], env).trim(), '1000');
    const denied = compose(PROJECT, ['logs', '--no-color', 'librechat'], env)
      .split('\n')
      .filter((line) => /EACCES|EPERM/.test(line));
    assert.deepEqual(denied, [], 'LibreChat logged a permission error');
    const logFiles = compose(PROJECT, ['exec', '-T', 'librechat', 'find', '/app/api/logs', '-mindepth', '1', '-type', 'f'], env);
    assert.notEqual(logFiles.trim(), '', 'LibreChat wrote no file under /app/api/logs');
  } catch (error) {
    try {
      error.message += `\n(the stack's logs: ${saveLogs(PROJECT, env)})`;
    } catch (saving) {
      error.message += `\n(its logs could not be saved: ${saving.message.split('\n')[0]})`;
    }
    throw error;
  } finally {
    destroy(PROJECT, env);
  }
});
