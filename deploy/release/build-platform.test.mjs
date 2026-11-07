// Tests for build-platform.sh, with git, docker and tar stubbed first on PATH:  node --test build-platform.test.mjs
// No case may reach the real tools: the file stops before any test unless bash resolves all three to the stubs.
// The temp paths carry spaces on purpose, because the real checkouts do ("AI Platform").
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(new URL('./build-platform.sh', import.meta.url)).replaceAll('\\', '/');
const SHA = 'abc1234';
const BRANCH = 'some-branch';
const PREFIX = 'stub-prefix';

const root = mkdtempSync(path.join(os.tmpdir(), 'build platform ')).replaceAll('\\', '/');
after(() => rmSync(root, { recursive: true, force: true }));

// Each stub appends its argv to $STUB_LOG, one call per line, tab separated, then behaves as its case asks.
const stubs = {
  git: `case " $* " in
  *" rev-parse --short HEAD "*) printf '%s\\n' "$STUB_SHA" ;;
  *" rev-parse --abbrev-ref HEAD "*) printf '%s\\n' "$STUB_BRANCH" ;;
  *" archive "*) printf 'tar-stream'; exit "\${STUB_ARCHIVE_EXIT:-0}" ;;
esac`,
  docker: `case "$1 $2" in
  "image inspect") case " $STUB_IMAGES " in *" $3 "*) exit 0 ;; *) exit 1 ;; esac ;;
  "image tag") exit "\${STUB_TAG_EXIT:-0}" ;;
esac
if [ "$1" = build ]; then echo 'stdout of the build'; echo 'stderr of the build' >&2; exit "\${STUB_BUILD_EXIT:-0}"; fi`,
  tar: 'cat > "$STUB_TAR_INPUT"',
};
const stubDir = `${root}/stubs`;
mkdirSync(stubDir);
for (const [name, body] of Object.entries(stubs)) {
  writeFileSync(`${stubDir}/${name}`, `#!/bin/sh\n(IFS='\t'; printf '%s\\n' "${name}\t$*") >> "$STUB_LOG"\n${body}\n`, { mode: 0o755 });
}

const scrubbed = ['path', 'platform_dir', 'iqraa_image_prefix', 'iqraa_build_dir'];
const baseEnv = {
  ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !scrubbed.includes(key.toLowerCase()))),
  PATH: `${stubDir}${path.delimiter}${process.env.PATH}`,
};

const resolved = spawnSync('bash', ['-c', 'command -v git; command -v docker; command -v tar'], { encoding: 'utf8', env: baseEnv });
assert.deepEqual(
  resolved.stdout.trim().split('\n').map((found) => found.split('/').slice(-2).join('/')),
  ['stubs/git', 'stubs/docker', 'stubs/tar'],
  `bash would reach a real tool, so no case may run: ${resolved.stdout}${resolved.stderr}`,
);

let caseNumber = 0;

// Runs the script in a fresh folder. defaults: true leaves its three settings unset and runs a copy from inside a Harness-shaped tree.
function runBuild(args = [], { images = '', env = {}, leftover = false, defaults = false } = {}) {
  caseNumber += 1;
  const work = `${root}/case ${caseNumber}`;
  mkdirSync(work);
  const log = `${work}/stub.log`;
  const tarInput = `${work}/tar-input`;
  const platform = `${work}/AI Platform`;
  const build = defaults ? `${work}/AI Harness/deploy/release/.build` : `${work}/build dir`;
  if (leftover) {
    mkdirSync(`${build}/${SHA}`, { recursive: true });
    writeFileSync(`${build}/${SHA}/leftover`, '');
  }
  let target = script;
  if (defaults) {
    target = `${work}/AI Harness/deploy/release/build-platform.sh`;
    mkdirSync(path.dirname(target), { recursive: true });
    copyFileSync(script, target);
  }
  const settings = defaults ? {} : { PLATFORM_DIR: platform, IQRAA_IMAGE_PREFIX: PREFIX, IQRAA_BUILD_DIR: build };
  const result = spawnSync('bash', [target, ...args], {
    encoding: 'utf8',
    env: { ...baseEnv, ...settings, STUB_LOG: log, STUB_TAR_INPUT: tarInput, STUB_SHA: SHA, STUB_BRANCH: BRANCH, STUB_IMAGES: images, ...env },
  });
  const calls = existsSync(log) ? readFileSync(log, 'utf8').trim().split('\n').map((line) => line.split('\t')) : [];
  const find = (tool, verb) => calls.findIndex((call) => call[0] === tool && call.includes(verb));
  return { ...result, calls, find, platform, build, dir: `${build}/${SHA}`, tarInput };
}

const image = (tag) => `${PREFIX}/platform:${tag}`;
const flagValues = (call, flag) => call.flatMap((arg, i) => (call[i - 1] === flag ? [arg] : []));
const dockerCalls = (run, ...verb) => run.calls.filter((call) => call[0] === 'docker' && verb.every((word, i) => call[i + 1] === word));

test('a missing rollback tag is made from phase1 before the build', () => {
  const run = runBuild(['--rollback-tag', 'before-x']);

  assert.equal(run.status, 0, run.stderr);
  assert.deepEqual(dockerCalls(run, 'image', 'tag'), [['docker', 'image', 'tag', image('phase1'), image('before-x')]]);
  assert.ok(run.find('docker', 'tag') < run.find('docker', 'build'), 'the tag must exist before the build moves phase1');
});

test('an existing rollback tag is never tagged again', () => {
  const run = runBuild(['--rollback-tag', 'before-x'], { images: image('before-x') });

  assert.equal(run.status, 0, run.stderr);
  assert.equal(dockerCalls(run, 'image', 'inspect')[0][3], image('before-x'));
  assert.deepEqual(dockerCalls(run, 'image', 'tag'), []);
  assert.equal(dockerCalls(run, 'build').length, 1);
});

test('no flag means no rollback tagging', () => {
  const run = runBuild();

  assert.equal(run.status, 0, run.stderr);
  assert.deepEqual(dockerCalls(run, 'image', 'tag'), []);
  assert.equal(dockerCalls(run, 'build').length, 1);
});

test('a rollback tag that cannot be made stops before the build', () => {
  const run = runBuild(['--rollback-tag', 'before-x'], { env: { STUB_TAG_EXIT: '1' } });

  assert.equal(dockerCalls(run, 'image', 'tag').length, 1);
  assert.notEqual(run.status, 0);
  assert.deepEqual(dockerCalls(run, 'build'), []);
});

test('the names the build itself moves cannot be the rollback tag', () => {
  for (const name of ['phase1', SHA]) {
    const run = runBuild(['--rollback-tag', name], { images: image(name) });

    assert.equal(run.status, 2, `--rollback-tag ${name} would let the build overwrite the rollback target`);
    assert.deepEqual(dockerCalls(run, 'build'), []);
  }
});

test('a non-empty build folder exits 1 with no export and no docker build', () => {
  const run = runBuild([], { leftover: true });

  assert.equal(run.status, 1, run.stderr);
  assert.equal(run.find('git', 'archive'), -1);
  assert.deepEqual(dockerCalls(run, 'build'), []);
});

test('a failing docker build exits with docker\'s status and keeps its output in the log', () => {
  const run = runBuild([], { env: { STUB_BUILD_EXIT: '7' } });

  assert.equal(dockerCalls(run, 'build').length, 1);
  assert.equal(run.status, 7);
  const log = readFileSync(`${run.build}/build-${SHA}.log`, 'utf8');
  assert.match(log, /stdout of the build/);
  assert.match(log, /stderr of the build/);
});

test('the build line has the target, both tags, the commit and the current branch', () => {
  const run = runBuild();

  assert.equal(run.status, 0, run.stderr);
  const [build] = dockerCalls(run, 'build');
  assert.deepEqual(flagValues(build, '--target'), ['api-build']);
  assert.deepEqual(flagValues(build, '-t'), [image(SHA), image('phase1')]);
  assert.deepEqual(flagValues(build, '--build-arg'), [`BUILD_COMMIT=${SHA}`, `BUILD_BRANCH=${BRANCH}`]);
  assert.deepEqual(flagValues(build, '-f'), [`${run.dir}/Dockerfile.multi`]);
  assert.equal(build.at(-1), run.dir);
});

test('the committed tree is exported with core.autocrlf off and piped into tar', () => {
  const run = runBuild();

  assert.equal(run.status, 0, run.stderr);
  assert.deepEqual(run.calls[run.find('git', 'archive')], ['git', '-C', run.platform, '-c', 'core.autocrlf=false', 'archive', '--format=tar', 'HEAD']);
  assert.deepEqual(run.calls[run.find('tar', '-x')], ['tar', '-x', '-C', run.dir]);
  assert.equal(readFileSync(run.tarInput, 'utf8'), 'tar-stream');
  assert.ok(run.find('git', 'archive') < run.find('docker', 'build'));
});

test('a failed export stops before the build, even though tar succeeds', () => {
  const run = runBuild([], { env: { STUB_ARCHIVE_EXIT: '5' } });

  assert.notEqual(run.find('git', 'archive'), -1);
  assert.notEqual(run.status, 0);
  assert.notEqual(run.status, 127);
  assert.deepEqual(dockerCalls(run, 'build'), []);
});

test('a bad argument exits 2 and touches nothing', () => {
  for (const args of [['--rollback-tag'], ['--rollback-tag', ''], ['--rollback-tag', '--other'], ['--other']]) {
    const run = runBuild(args);

    assert.equal(run.status, 2, `arguments: ${JSON.stringify(args)}`);
    assert.deepEqual(run.calls, []);
  }
});

test('the defaults are the sibling AI Platform, the iqraa images and deploy/release/.build', () => {
  const run = runBuild([], { defaults: true });

  assert.equal(run.status, 0, run.stderr);
  const [, , platform] = run.calls[run.find('git', 'archive')];
  assert.ok(platform.endsWith('/AI Harness/../AI Platform'), platform);
  assert.deepEqual(flagValues(dockerCalls(run, 'build')[0], '-t'), [`iqraa/platform:${SHA}`, 'iqraa/platform:phase1']);
  assert.ok(existsSync(`${run.build}/build-${SHA}.log`), 'the build log belongs in deploy/release/.build');
});
