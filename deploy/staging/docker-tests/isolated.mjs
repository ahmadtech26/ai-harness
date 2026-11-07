// Helpers for tests that boot an isolated copy of the staging stack (compose.yaml plus compose.isolated.yaml) beside
// staging, and build release images under throwaway hardening-test/ tags. Nothing here writes an iqraa/ image,
// publishes port 3080 or touches the iqraa-staging project: compose() refuses any other project name, and checks the
// merged configuration before it first runs a project.
//   import { buildRelease, compose, destroy, waitReady } from './isolated.mjs';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const STAGING_DIR = path.resolve(HERE, '..');
export const RELEASE_DOCKERFILE = path.resolve(HERE, '..', '..', 'release', 'Dockerfile');
export const PLATFORM_IMAGE = 'iqraa/platform:phase1';
export const LEGAL_SEARCH_IMAGE = 'hardening-test/legal-search:isolated';
// What compose() runs as the LibreChat release unless the caller names one: never the shell's IQRAA_IMAGE.
export const DEFAULT_RELEASE = 'hardening-test/release:isolated';
const FILES = ['-f', 'compose.yaml', '-f', 'docker-tests/compose.isolated.yaml'];

function run(command, args, { cwd, env = process.env } = {}) {
  const result = spawnSync(command, args, { cwd, env, encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 });
  if (result.error) throw result.error;
  return result;
}

function stdoutOf(result, what) {
  if (result.status !== 0) {
    throw new Error(`${what} exited ${result.status}:\n${`${result.stderr}\n${result.stdout}`.trim().slice(-4000)}`);
  }
  return result.stdout;
}

const pathless = (env) => ({ ...process.env, MSYS_NO_PATHCONV: '1', ...env });

// A published port as compose config prints it: "3080", or a range such as "3075-3085".
function publishes3080(published) {
  const [low, high = low] = String(published ?? '').split('-').map(Number);
  return low <= 3080 && 3080 <= high;
}

const checked = new Set();

function refuseUnsafe(project, env) {
  const config = JSON.parse(
    stdoutOf(run('docker', ['compose', '-p', project, ...FILES, 'config', '--format', 'json'], { cwd: STAGING_DIR, env }), 'docker compose config'),
  );
  const problems = [];
  if (config.name !== project) problems.push(`the project resolves to "${config.name}"`);
  for (const [name, service] of Object.entries(config.services ?? {})) {
    if (/(^|\/)iqraa\//.test(String(service.image ?? ''))) problems.push(`${name} uses ${service.image}`);
    for (const port of service.ports ?? []) {
      if (publishes3080(port.published)) problems.push(`${name} publishes ${port.published}`);
    }
  }
  if (problems.length > 0) throw new Error(`refusing compose project ${project}: ${problems.join('; ')}`);
}

/**
 * Runs `docker compose -p <project> -f compose.yaml -f docker-tests/compose.isolated.yaml <args>` in deploy/staging and
 * returns its stdout; throws on a non-zero exit. env: IQRAA_IMAGE (default DEFAULT_RELEASE) and IQRAA_ISOLATED_PORT
 * (default 3186). Refuses a project not named hardening-*, and, the first time a project runs with an image and port,
 * a merged configuration with an iqraa/ image or a published 3080.
 */
export function compose(project, args, env = {}) {
  if (typeof project !== 'string' || !/^hardening-[a-z0-9][a-z0-9_-]*$/.test(project)) {
    throw new Error(`refusing compose project "${project}": isolated projects are named hardening-*`);
  }
  const full = pathless({ IQRAA_IMAGE: DEFAULT_RELEASE, ...env });
  // compose.yaml interpolates only IQRAA_IMAGE and the overlay only IQRAA_ISOLATED_PORT.
  const key = JSON.stringify([project, full.IQRAA_IMAGE, full.IQRAA_ISOLATED_PORT ?? '']);
  if (!checked.has(key)) {
    refuseUnsafe(project, full);
    checked.add(key);
  }
  return stdoutOf(run('docker', ['compose', '-p', project, ...FILES, ...args], { cwd: STAGING_DIR, env: full }), `docker compose ${args.join(' ')}`);
}

/** The commit the current platform image was built from (its BUILD_COMMIT), which is also its iqraa/platform:<sha> tag. */
export function platformCommit() {
  const env = JSON.parse(stdoutOf(run('docker', ['image', 'inspect', '--format', '{{json .Config.Env}}', PLATFORM_IMAGE]), `docker image inspect ${PLATFORM_IMAGE}`));
  const commit = (env ?? []).find((entry) => entry.startsWith('BUILD_COMMIT='))?.slice('BUILD_COMMIT='.length);
  if (!commit) throw new Error(`${PLATFORM_IMAGE} has no BUILD_COMMIT`);
  return commit;
}

/**
 * Builds deploy/release/Dockerfile on iqraa/platform:<BUILD_COMMIT of iqraa/platform:phase1> as hardening-test/release:<tag>,
 * from a temporary context holding only skills/RELEASE.json. Reads the base image and writes nothing under iqraa/.
 */
export function buildRelease(tag) {
  if (!/^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$/.test(tag)) throw new Error(`not a docker tag: ${tag}`);
  const platform = platformCommit();
  // A FROM that is not local would be pulled from a registry: build only on the local base.
  stdoutOf(run('docker', ['image', 'inspect', '--format', '{{.Id}}', `iqraa/platform:${platform}`]), `docker image inspect iqraa/platform:${platform}`);
  const image = `hardening-test/release:${tag}`;
  const context = mkdtempSync(path.join(os.tmpdir(), 'hardening-release-'));
  try {
    mkdirSync(path.join(context, 'skills'));
    writeFileSync(path.join(context, 'skills', 'RELEASE.json'), `${JSON.stringify({ tag, platform, skills: [] }, null, 2)}\n`);
    stdoutOf(
      run('docker', ['build', '-q', '-f', RELEASE_DOCKERFILE, '--build-arg', `PLATFORM=${platform}`, '-t', image, context], { env: pathless() }),
      `docker build ${image}`,
    );
  } finally {
    rmSync(context, { recursive: true, force: true });
  }
  return image;
}

/**
 * Builds hardening-test/legal-search:isolated from services/legal-search on every call, never trusting a tag an earlier
 * run left (it would boot the service as it was then). Docker's build cache keeps an unchanged tree quick.
 */
export function ensureLegalSearch(project, env = {}) {
  compose(project, ['build', 'legal-search'], env);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Polls http://127.0.0.1:<port>/readyz until it answers 200 (the proxy answers 502 until LibreChat listens). */
export async function waitReady(port, timeoutMs = 600_000) {
  const deadline = Date.now() + timeoutMs;
  let last = 'no answer';
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/readyz`, { signal: AbortSignal.timeout(10_000) });
      await res.text();
      if (res.status === 200) return;
      last = `HTTP ${res.status}`;
    } catch (error) {
      last = error.cause?.code ?? error.message;
    }
    await sleep(3000);
  }
  throw new Error(`/readyz on 127.0.0.1:${port} was not 200 within ${timeoutMs} ms (last: ${last})`);
}

/** Writes the project's `ps -a` and every service's log to a file in the temp folder (before destroy), returns its path. */
export function saveLogs(project, env = {}) {
  const file = path.join(os.tmpdir(), `${project}-${new Date().toISOString().replace(/[:.]/g, '-')}.log`);
  writeFileSync(file, `${compose(project, ['ps', '-a'], env)}\n${compose(project, ['logs', '--no-color', '--timestamps'], env)}`);
  return file;
}

/** Removes the project's containers, network and volumes. */
export function destroy(project, env = {}) {
  return compose(project, ['down', '-v', '--remove-orphans'], env);
}
