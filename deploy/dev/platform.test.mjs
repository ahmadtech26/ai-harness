// Tests for platform.sh, with docker stubbed first on PATH and a logging tools/dev.sh:  node --test deploy/dev/platform.test.mjs
// No case may reach the real docker: the file stops before any test unless bash resolves it to the stub.
// The temp paths carry spaces on purpose, because the real checkouts do ("AI Platform").
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(new URL('./platform.sh', import.meta.url)).replaceAll('\\', '/');
const COMMAND = 'cd packages/api && npx jest src/iqraa';

const root = mkdtempSync(path.join(os.tmpdir(), 'dev platform ')).replaceAll('\\', '/');
after(() => rmSync(root, { recursive: true, force: true }));

// The stub and the dev script each append their argv to $STUB_LOG, one call per line, tab separated, then exit with
// the status their case asks for: the dev script's assemble STUB_ASSEMBLE_EXIT, its run STUB_DEV_EXIT.
const logArgs = (name) => `(IFS='\t'; printf '%s\\n' "${name}\t$*") >> "$STUB_LOG"`;
const stubDir = `${root}/stubs`;
mkdirSync(stubDir);
writeFileSync(`${stubDir}/docker`, `#!/bin/sh\n${logArgs('docker')}\nexit "\${STUB_DOCKER_EXIT:-0}"\n`, { mode: 0o755 });
const devScript = `${logArgs('dev.sh')}
[ "$1" = assemble ] && exit "\${STUB_ASSEMBLE_EXIT:-0}"
exit "\${STUB_DEV_EXIT:-0}"
`;

const baseEnv = {
  ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !['path', 'platform_dir'].includes(key.toLowerCase()))),
  PATH: `${stubDir}${path.delimiter}${process.env.PATH}`,
};

const resolved = spawnSync('bash', ['-c', 'command -v docker'], { encoding: 'utf8', env: baseEnv });
assert.equal(
  resolved.stdout.trim().split('/').slice(-2).join('/'),
  'stubs/docker',
  `bash would reach the real docker, so no case may run: ${resolved.stdout}${resolved.stderr}`,
);

// The mount source platform.sh must give docker for a folder: its Windows form under Git Bash, itself elsewhere.
const win = (dir) => spawnSync('bash', ['-c', 'pwd -W 2>/dev/null || pwd'], { cwd: dir, encoding: 'utf8', env: baseEnv }).stdout.trim();

let caseNumber = 0;

// Runs platform.sh in a fresh folder. dev: true gives the AI Platform checkout a tools/dev.sh; defaults: true leaves
// PLATFORM_DIR unset and runs a copy from inside a Harness-shaped tree, beside the AI Platform.
function runPlatform(args, { dev = false, defaults = false, env = {} } = {}) {
  caseNumber += 1;
  const work = `${root}/case ${caseNumber}`;
  const platform = `${work}/AI Platform`;
  const log = `${work}/stub.log`;
  mkdirSync(platform, { recursive: true });
  if (dev) {
    mkdirSync(`${platform}/tools`);
    writeFileSync(`${platform}/tools/dev.sh`, devScript);
  }
  let target = script;
  if (defaults) {
    target = `${work}/AI Harness/deploy/dev/platform.sh`;
    mkdirSync(path.dirname(target), { recursive: true });
    copyFileSync(script, target);
  }
  const result = spawnSync('bash', [target, ...args], {
    encoding: 'utf8',
    env: { ...baseEnv, ...(defaults ? {} : { PLATFORM_DIR: platform }), STUB_LOG: log, ...env },
  });
  const calls = existsSync(log) ? readFileSync(log, 'utf8').trim().split('\n').map((line) => line.split('\t')) : [];
  return { ...result, calls, platform, shown: `${result.stdout}${result.stderr}` };
}

// The assemble first: the gate must test the tree as the checkout has it now, not as it was last assembled.
test('a checkout with tools/dev.sh is assembled, then gets the command through its run, and docker is never called here', () => {
  const run = runPlatform([COMMAND], { dev: true });

  assert.equal(run.status, 0, run.shown);
  assert.deepEqual(run.calls, [['dev.sh', 'assemble'], ['dev.sh', 'run', COMMAND]]);
});

test('the words of the command reach tools/dev.sh run as one command, and its status is platform.sh\'s', () => {
  const run = runPlatform(['cd client &&', 'npx jest src/iqraa'], { dev: true, env: { STUB_DEV_EXIT: '3' } });

  assert.equal(run.status, 3, run.shown);
  assert.deepEqual(run.calls, [['dev.sh', 'assemble'], ['dev.sh', 'run', 'cd client && npx jest src/iqraa']]);
});

test('a failing assemble is platform.sh\'s status, and the command does not run on the tree it left', () => {
  const run = runPlatform([COMMAND], { dev: true, env: { STUB_ASSEMBLE_EXIT: '5' } });

  assert.equal(run.status, 5, run.shown);
  assert.deepEqual(run.calls, [['dev.sh', 'assemble']]);
});

test('a LibreChat checkout runs the command in the dev container on the checkout itself, as before', () => {
  const run = runPlatform([COMMAND], { env: { STUB_DOCKER_EXIT: '4' } });

  assert.equal(run.status, 4, run.shown);
  assert.equal(run.calls.length, 1);
  const [call] = run.calls;
  assert.deepEqual(call.slice(0, 6), ['docker', 'run', '--rm', '-i', '-v', `${win(run.platform)}:/work`]);
  assert.ok(call.includes('iqraa-nm-root:/work/./node_modules'), call.join(' '));
  assert.ok(call.includes('iqraa-nm-packages-api:/work/packages/api/node_modules'), call.join(' '));
  assert.ok(call.at(-4).startsWith('node:24-bookworm@sha256:'), call.at(-4));
  assert.deepEqual(call.slice(-3), ['bash', '-lc', COMMAND]);
});

test('PLATFORM_DIR defaults to the sibling AI Platform, whose tools/dev.sh then gets the command', () => {
  const run = runPlatform([COMMAND], { dev: true, defaults: true });

  assert.equal(run.status, 0, run.shown);
  assert.deepEqual(run.calls, [['dev.sh', 'assemble'], ['dev.sh', 'run', COMMAND]]);
});
