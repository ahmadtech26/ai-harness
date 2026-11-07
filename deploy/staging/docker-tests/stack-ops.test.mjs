// O-46, O-68, O-69 on a real Docker: LibreChat's health check turns healthy through /readyz, what LibreChat writes to
// uploads, images and logs survives a container recreate (the documented way to apply a configuration change), and
// Docker runs every long-running service with its memory and CPU limit, restart policy and log rotation.
//   node --test deploy/staging/docker-tests/stack-ops.test.mjs
// Builds hardening-test/release:o68, boots it in the isolated project hardening-o68 on 127.0.0.1:3098 (staging keeps
// 3080, nonroot.test.mjs 3186) and removes that project, volumes included, afterwards.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { before, test } from 'node:test';
import { buildRelease, compose, destroy, ensureLegalSearch, saveLogs } from './isolated.mjs';

const PROJECT = 'hardening-o68';
const PORT = '3098';
const FOLDERS = ['/app/uploads', '/app/client/public/images', '/app/api/logs'];
const LONG_RUNNING = ['mongo', 'postgres', 'legal-search', 'mock-llm', 'librechat', 'proxy'];
// The ingest loads every law first, on a spinning disk; LibreChat then has its 300 s start period.
const BOOT_BUDGET_MS = 15 * 60_000;
const RECREATE_BUDGET_MS = 6 * 60_000;

let env;

before(() => {
  env = { IQRAA_IMAGE: buildRelease('o68'), IQRAA_ISOLATED_PORT: PORT };
});

function inspect(id, format) {
  const result = spawnSync('docker', ['inspect', '--format', format, id], { encoding: 'utf8' });
  if (result.error) throw result.error;
  return result.status === 0 ? result.stdout.trim() : null;
}

const containerOf = (service, all = false) => {
  const id = compose(PROJECT, ['ps', ...(all ? ['-a'] : []), '-q', service], env).trim();
  assert.ok(id, `no ${service} container`);
  return id;
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Polls the container's health until it is healthy or the budget ends; returns the last status seen. */
async function healthOf(id, budgetMs) {
  const deadline = Date.now() + budgetMs;
  let status = null;
  while (Date.now() < deadline) {
    status = inspect(id, '{{if .State.Health}}{{.State.Health.Status}}{{else}}no health check{{end}}');
    if (status === 'healthy') return status;
    await sleep(3000);
  }
  return status;
}

test('LibreChat turns healthy through /readyz, keeps its data folders across a recreate, and runs within its limits', { timeout: 40 * 60_000 }, async () => {
  // Another stack answering on the port would serve this one's requests.
  const busy = await fetch(`http://127.0.0.1:${PORT}/`, { signal: AbortSignal.timeout(3000) }).then(() => true, () => false);
  assert.equal(busy, false, `something already answers on 127.0.0.1:${PORT}`);
  destroy(PROJECT, env); // a run that died before its cleanup: start from empty volumes
  try {
    ensureLegalSearch(PROJECT, env);
    // Not `up --wait`: secrets-init and legal-search-ingest exit once done. The proxy waits for a healthy LibreChat.
    compose(PROJECT, ['up', '-d', 'proxy'], env);
    const first = containerOf('librechat');
    assert.equal(await healthOf(first, BOOT_BUDGET_MS), 'healthy');
    assert.match(inspect(first, '{{json .Config.Healthcheck.Test}}') ?? '', /\/readyz"/);

    // As the image's own user, which is what LibreChat writes as.
    const mark = `o68-${process.pid}-${Date.now()}`;
    const uid = compose(PROJECT, ['exec', '-T', 'librechat', 'id', '-u'], env).trim();
    compose(PROJECT, ['exec', '-T', 'librechat', 'sh', '-c', FOLDERS.map((d) => `echo ${mark} > ${d}/.o68-probe`).join(' && ')], env);

    compose(PROJECT, ['up', '-d', '--no-deps', '--force-recreate', 'librechat'], env);
    const second = containerOf('librechat');
    assert.notEqual(second, first, 'librechat was not recreated');
    const kept = compose(PROJECT, ['exec', '-T', 'librechat', 'sh', '-c', FOLDERS.map((d) => `cat ${d}/.o68-probe`).join(' && ')], env);
    assert.deepEqual(kept.trim().split('\n'), FOLDERS.map(() => mark), `probes written as uid ${uid} did not survive the recreate`);
    assert.equal(await healthOf(second, RECREATE_BUDGET_MS), 'healthy');

    const format = '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.RestartPolicy.Name}} {{.HostConfig.LogConfig.Type}} {{index .HostConfig.LogConfig.Config "max-size"}} {{.State.OOMKilled}}';
    const running = Object.fromEntries(LONG_RUNNING.map((service) => [service, inspect(containerOf(service), format)?.split(' ')]));
    for (const [service, [memory, cpus, restart, driver, maxSize, oomKilled]] of Object.entries(running)) {
      assert.ok(Number(memory) > 0, `${service}: .HostConfig.Memory is ${memory}`);
      assert.ok(Number(cpus) > 0, `${service}: .HostConfig.NanoCpus is ${cpus}`);
      assert.deepEqual([restart, driver, maxSize, oomKilled], ['unless-stopped', 'json-file', '20m', 'false'], service);
    }
    const ingest = inspect(containerOf('legal-search-ingest', true), '{{.HostConfig.Memory}} {{.State.ExitCode}} {{.State.OOMKilled}}');
    assert.match(ingest ?? '', /^[1-9]\d* 0 false$/, `legal-search-ingest: memory, exit code, OOM killed = ${ingest}`);
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
