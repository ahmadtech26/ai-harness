// Tests for build.sh, with docker, git and node stubbed first on PATH:  node --test deploy/release/build.test.mjs
// No case may reach the real tools: the file stops before any test unless bash resolves all three to the stubs.
// Each case runs a copy of build.sh in its own Harness-shaped tree whose tools/gates.sh is a stub too, so no gate
// really runs. The temp paths carry spaces on purpose, because the real checkouts do ("AI Harness").
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const source = (relative) => fileURLToPath(new URL(relative, import.meta.url)).replaceAll('\\', '/');
const script = source('./build.sh');
const realGates = source('../../tools/gates.sh');
const TAG = 'o56';
const PLATFORM = 'abc1234';
const HARNESS_SHA = 'def5678';
const PREFIX = 'stub-prefix';
const PRODUCTION_GATES = ['--release', 'checks', 'skills', 'plan', 'legal-search', 'eval', 'node', 'fork'];

const root = mkdtempSync(path.join(os.tmpdir(), 'build release ')).replaceAll('\\', '/');
after(() => rmSync(root, { recursive: true, force: true }));

// Each stub appends its argv to $STUB_LOG, one call per line, tab separated, then behaves as its case asks.
const log = (name) => `(IFS='\t'; printf '%s\\n' "${name}\t$*") >> "$STUB_LOG"`;
const stubs = {
  // A -C folder that does not exist fails as git does; the platform checkout ($STUB_PLATFORM_DIR) answers its own.
  git: `[ "$1" != -C ] || [ -d "$2" ] || { echo "fatal: cannot change to '$2'" >&2; exit 128; }
if [ "$1" = -C ] && [ "$(cd "$2" && pwd)" = "$(cd "\${STUB_PLATFORM_DIR:-/nonexistent}" 2>/dev/null && pwd)" ]; then
  case " $* " in
    *" status --porcelain "*) [ -z "\${STUB_PLATFORM_DIRTY:-}" ] || printf '%s\\n' "$STUB_PLATFORM_DIRTY"; exit 0 ;;
    *" rev-parse --short HEAD "*) printf '%s\\n' "$STUB_PLATFORM_SHA"; exit 0 ;;
  esac
fi
case " $* " in
  *" status --porcelain "*) [ -z "\${STUB_DIRTY:-}" ] || printf '%s\\n' "$STUB_DIRTY"; exit "\${STUB_GIT_EXIT:-0}" ;;
  *" rev-parse --short HEAD "*) printf '%s\\n' "$STUB_SHA" ;;
esac`,
  docker: `case "$1 $2" in
  "image inspect")
    case " $* " in
      *" --format "*) printf 'PATH=/usr/local/bin\\n'; [ -z "\${STUB_BUILD_COMMIT:-}" ] || printf 'BUILD_COMMIT=%s\\n' "$STUB_BUILD_COMMIT" ;;
    esac
    exit 0 ;;
esac
if [ "$1" = build ]; then exit "\${STUB_BUILD_EXIT:-0}"; fi`,
  node: '',
};
const stubDir = `${root}/stubs`;
mkdirSync(stubDir);
for (const [name, body] of Object.entries(stubs)) {
  writeFileSync(`${stubDir}/${name}`, `#!/bin/sh\n${log(name)}\n${body}\n`, { mode: 0o755 });
}
// The gates stub also keeps the image prefix and PLATFORM_DIR it was given, so a case can see that build.sh and the
// gates agree on them.
const gatesStub = `#!/bin/sh\n${log('gates.sh')}\nprintf '%s' "\${IQRAA_IMAGE_PREFIX-unset}" > "$STUB_GATES_PREFIX"\nprintf '%s' "\${PLATFORM_DIR-unset}" > "$STUB_GATES_PREFIX.platform"\nexit "\${STUB_GATES_EXIT:-0}"\n`;

const scrubbed = ['path', 'platform_dir', 'iqraa_image_prefix', 'iqraa_build_dir', 'iqraa_gates_project', 'msys_no_pathconv'];
const baseEnv = {
  ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !scrubbed.includes(key.toLowerCase()))),
  PATH: `${stubDir}${path.delimiter}${process.env.PATH}`,
};

const resolved = spawnSync('bash', ['-c', 'command -v git; command -v docker; command -v node'], { encoding: 'utf8', env: baseEnv });
assert.deepEqual(
  resolved.stdout.trim().split('\n').map((found) => found.split('/').slice(-2).join('/')),
  ['stubs/git', 'stubs/docker', 'stubs/node'],
  `bash would reach a real tool, so no case may run: ${resolved.stdout}${resolved.stderr}`,
);

let caseNumber = 0;

// Runs a copy of build.sh in a fresh Harness-shaped tree. defaults: true leaves IQRAA_IMAGE_PREFIX and IQRAA_BUILD_DIR unset.
function runBuild(args, { env = {}, defaults = false } = {}) {
  caseNumber += 1;
  const work = `${root}/case ${caseNumber}`;
  const harness = `${work}/AI Harness`;
  const target = `${harness}/deploy/release/build.sh`;
  mkdirSync(path.dirname(target), { recursive: true });
  copyFileSync(script, target);
  mkdirSync(`${harness}/tools`);
  writeFileSync(`${harness}/tools/gates.sh`, gatesStub, { mode: 0o755 });
  mkdirSync(`${harness}/content/skills`, { recursive: true });
  const platformDir = `${work}/AI Platform`;
  mkdirSync(platformDir);
  const extras = [`${work}/extra one`, `${work}/extra two`];
  for (const extra of extras) mkdirSync(extra);
  const stubLog = `${work}/stub.log`;
  const gatesPrefix = `${work}/gates-prefix`;
  const buildDir = defaults ? `${harness}/deploy/release/.build` : `${work}/build dir`;
  const settings = defaults ? {} : { IQRAA_IMAGE_PREFIX: PREFIX, IQRAA_BUILD_DIR: buildDir, PLATFORM_DIR: platformDir };
  const argv = args.map((arg) => (arg === '<extra 1>' ? extras[0] : arg === '<extra 2>' ? extras[1] : arg));
  const result = spawnSync('bash', [target, ...argv], {
    encoding: 'utf8',
    env: {
      ...baseEnv, ...settings,
      STUB_LOG: stubLog, STUB_GATES_PREFIX: gatesPrefix, STUB_SHA: HARNESS_SHA, STUB_BUILD_COMMIT: PLATFORM,
      STUB_PLATFORM_DIR: platformDir, STUB_PLATFORM_SHA: PLATFORM, ...env,
    },
  });
  const calls = existsSync(stubLog) ? readFileSync(stubLog, 'utf8').trim().split('\n').map((line) => line.split('\t')) : [];
  const stages = existsSync(buildDir) ? readdirSync(buildDir) : [];
  const gatesSawPrefix = existsSync(gatesPrefix) ? readFileSync(gatesPrefix, 'utf8') : null;
  const gatesSawPlatform = existsSync(`${gatesPrefix}.platform`) ? readFileSync(`${gatesPrefix}.platform`, 'utf8') : null;
  return { ...result, calls, harness, platformDir, buildDir, stages, gatesSawPrefix, gatesSawPlatform };
}

const flagValues = (call, flag) => call.flatMap((arg, i) => (call[i - 1] === flag ? [arg] : []));
const callsOf = (run, tool) => run.calls.filter((call) => call[0] === tool);
const dockerCalls = (run, ...verb) => callsOf(run, 'docker').filter((call) => verb.every((word, i) => call[i + 1] === word));
const skillStage = (run) => dockerCalls(run, 'run').filter((call) => call.includes('skill-stage'));
const indexOf = (run, predicate) => run.calls.findIndex(predicate);
const draft = [TAG, PLATFORM, '--allow-draft'];
const production = [TAG, PLATFORM, '--production'];

function assertRefused(args, reason) {
  const run = runBuild(args);
  assert.equal(run.status, 2, `${reason}: ${JSON.stringify(args)}\n${run.stdout}${run.stderr}`);
  assert.deepEqual(run.calls, [], `${reason}: nothing may run`);
}

test('no mode exits 2: production is never the mere absence of a flag', () => {
  assertRefused([TAG, PLATFORM], 'no mode');
  assertRefused([TAG, PLATFORM, '--extra', '<extra 1>'], 'no mode');
});

test('both modes exit 2, in either order', () => {
  assertRefused([TAG, PLATFORM, '--allow-draft', '--production'], 'both modes');
  assertRefused([TAG, PLATFORM, '--production', '--allow-draft'], 'both modes');
});

test('--extra with --production exits 2, wherever it stands', () => {
  assertRefused([...production, '--extra', '<extra 1>'], 'extra in production');
  assertRefused([TAG, PLATFORM, '--extra', '<extra 1>', '--production'], 'extra in production');
});

test('other bad arguments exit 2 and touch nothing', () => {
  assertRefused([...draft, '--record'], '--record is gone, implied by --production');
  assertRefused([...draft, '--extra'], '--extra needs a folder');
  assertRefused([...draft, '--other'], 'unknown argument');
  assertRefused([TAG], 'too few arguments');
  assertRefused(['../x', PLATFORM, '--allow-draft'], 'the tag names a folder and an image');
  assertRefused([TAG, '', '--allow-draft'], 'the platform sha names an image');
});

test('the draft path runs the checks gate, calls no git, records nothing and labels nothing', () => {
  const run = runBuild(draft);

  assert.equal(run.status, 0, run.stdout + run.stderr);
  assert.deepEqual(callsOf(run, 'gates.sh'), [['gates.sh', 'checks']]);
  assert.deepEqual(callsOf(run, 'git'), []);
  assert.deepEqual(callsOf(run, 'node'), [], 'the node checks belong to the gates');
  assert.ok(run.calls.every((call) => !call.includes('--record')), 'a draft must not record a release');
  const [build] = dockerCalls(run, 'build');
  assert.deepEqual(flagValues(build, '--label'), []);
  assert.ok(indexOf(run, (call) => call[0] === 'gates.sh') < indexOf(run, (call) => call.includes('skill-stage')));
});

test('a dirty or unreadable Harness stops production before any docker call, naming the rule', () => {
  const dirty = runBuild(production, { env: { STUB_DIRTY: ' M content/tiers.json' } });

  assert.equal(dirty.status, 1, dirty.stdout + dirty.stderr);
  assert.deepEqual(callsOf(dirty, 'docker'), []);
  assert.deepEqual(callsOf(dirty, 'gates.sh'), []);
  assert.match(dirty.stderr, /commit/i);
  assert.match(dirty.stderr, /content\/tiers\.json/);

  const unreadable = runBuild(production, { env: { STUB_GIT_EXIT: '128' } });
  assert.equal(unreadable.status, 1, 'a git that fails is not a clean tree');
  assert.deepEqual(callsOf(unreadable, 'docker'), []);
});

test('a platform image whose BUILD_COMMIT is not the sha stops production before the gates', () => {
  for (const commit of ['other99', '']) {
    const run = runBuild(production, { env: { STUB_BUILD_COMMIT: commit } });

    assert.equal(run.status, 1, `BUILD_COMMIT=${commit}: ${run.stdout}${run.stderr}`);
    const [inspect] = dockerCalls(run, 'image', 'inspect');
    assert.equal(inspect.at(-1), `${PREFIX}/platform:${PLATFORM}`);
    assert.deepEqual(callsOf(run, 'gates.sh'), []);
    assert.deepEqual(dockerCalls(run, 'build'), []);
    assert.match(run.stderr, /BUILD_COMMIT/);
  }
});

// The fork step mounts the AI Platform working tree, so production gates only the commit the image was built from.
const samePlace = (a, b) => spawnSync('bash', ['-c', '[ "$(cd "$1" && pwd)" = "$(cd "$2" && pwd)" ]', '-', a, b]).status === 0;
const platformGit = (run) => callsOf(run, 'git').filter((call) => call[1] === '-C' && samePlace(call[2], run.platformDir));

test('a platform checkout at another commit, with changes, or unreadable stops production before any docker call', () => {
  const moved = runBuild(production, { env: { STUB_PLATFORM_SHA: 'other99' } });
  assert.equal(moved.status, 1, moved.stdout + moved.stderr);
  assert.match(moved.stderr, /other99/);
  assert.match(moved.stderr, new RegExp(PLATFORM));

  const edited = runBuild(production, { env: { STUB_PLATFORM_DIRTY: ' M packages/api/src/iqraa/hooks.py' } });
  assert.equal(edited.status, 1, edited.stdout + edited.stderr);
  assert.match(edited.stderr, /packages\/api\/src\/iqraa\/hooks\.py/);

  const missing = runBuild(production, { env: { PLATFORM_DIR: `${root}/no such checkout` } });
  assert.equal(missing.status, 1, 'a checkout git cannot read is not a clean one');

  for (const run of [moved, edited, missing]) {
    assert.deepEqual(callsOf(run, 'docker'), [], run.stderr);
    assert.deepEqual(callsOf(run, 'gates.sh'), [], run.stderr);
  }
});

test('production checks the checkout PLATFORM_DIR names, or the sibling AI Platform, and the fork gate gets that one', () => {
  const named = runBuild(production);
  assert.equal(named.status, 0, named.stdout + named.stderr);
  assert.deepEqual(platformGit(named).map((call) => call.slice(3).join(' ')).sort(), ['rev-parse --short HEAD', 'status --porcelain']);
  assert.ok(samePlace(named.gatesSawPlatform, named.platformDir), `the gates saw PLATFORM_DIR=${named.gatesSawPlatform}`);
  const lastPlatform = Math.max(...platformGit(named).map((call) => named.calls.indexOf(call)));
  assert.ok(lastPlatform < indexOf(named, (call) => call[0] === 'docker'), JSON.stringify(named.calls));

  const sibling = runBuild(production, { defaults: true });
  assert.equal(sibling.status, 0, sibling.stdout + sibling.stderr);
  assert.equal(platformGit(sibling).length, 2, JSON.stringify(sibling.calls));
  assert.ok(samePlace(sibling.gatesSawPlatform, sibling.platformDir), `the gates saw PLATFORM_DIR=${sibling.gatesSawPlatform}`);
});

test('a clean production run checks the tree, gates with --release, stages with --record, then builds with the label', () => {
  const run = runBuild(production);

  assert.equal(run.status, 0, run.stdout + run.stderr);
  assert.deepEqual(callsOf(run, 'gates.sh'), [['gates.sh', ...PRODUCTION_GATES]]);
  const [stage] = skillStage(run);
  assert.deepEqual(flagValues(stage, '--record'), ['/record/RELEASED.json']);
  assert.ok(flagValues(stage, '-v').some((mount) => mount.endsWith('/content/skills:/record')), stage.join(' '));
  const [build] = dockerCalls(run, 'build');
  assert.deepEqual(flagValues(build, '--label'), [`org.iqraa.harness-commit=${HARNESS_SHA}`]);

  const status = indexOf(run, (call) => call[0] === 'git' && call.includes('status'));
  const inspect = indexOf(run, (call) => call[0] === 'docker' && call[1] === 'image');
  const gates = indexOf(run, (call) => call[0] === 'gates.sh');
  const staged = indexOf(run, (call) => call.includes('skill-stage'));
  const built = indexOf(run, (call) => call[0] === 'docker' && call[1] === 'build');
  assert.equal(status, 0, 'the clean-tree check comes before anything else');
  assert.ok(status < inspect && inspect < gates && gates < staged && staged < built, JSON.stringify(run.calls));
});

test('a failing gate exits non-zero with no staging and no docker build', () => {
  for (const args of [draft, production]) {
    const run = runBuild(args, { env: { STUB_GATES_EXIT: '1' } });

    assert.equal(callsOf(run, 'gates.sh').length, 1, args.join(' '));
    assert.notEqual(run.status, 0, args.join(' '));
    assert.deepEqual(skillStage(run), []);
    assert.deepEqual(dockerCalls(run, 'build'), []);
  }
});

test('the prefix names every image and the platform repository the Dockerfile builds on', () => {
  const run = runBuild(draft);

  assert.equal(run.status, 0, run.stdout + run.stderr);
  assert.equal(dockerCalls(run, 'image', 'inspect')[0].at(-1), `${PREFIX}/platform:${PLATFORM}`);
  assert.ok(skillStage(run)[0].includes(`${PREFIX}/skill-tools`));
  assert.equal(run.gatesSawPrefix, PREFIX);
  const [build] = dockerCalls(run, 'build');
  assert.deepEqual(flagValues(build, '-t'), [`${PREFIX}/release:${TAG}`]);
  assert.deepEqual(flagValues(build, '--build-arg'), [`PLATFORM=${PLATFORM}`, `PLATFORM_REPO=${PREFIX}/platform`]);
  assert.ok(flagValues(build, '-f')[0].endsWith('/deploy/release/Dockerfile'));
  assert.ok(run.calls.every((call) => call.every((arg) => !arg.includes('iqraa/'))), 'no image may keep the iqraa/ name');
});

test('the stage is <tag>-<timestamp> under IQRAA_BUILD_DIR, and no argv names .hq', () => {
  const runs = [runBuild(draft), runBuild(production)];

  for (const run of runs) {
    assert.equal(run.status, 0, run.stdout + run.stderr);
    assert.equal(run.stages.length, 1, `one stage folder in ${run.buildDir}: ${run.stages}`);
    const [name] = run.stages;
    assert.match(name, new RegExp(`^${TAG}-\\d{14}$`));
    assert.ok(flagValues(skillStage(run)[0], '-v').some((mount) => mount.endsWith(`/${name}:/out`)));
    assert.ok(dockerCalls(run, 'build')[0].at(-1).endsWith(`/${name}`), 'the stage is the build context');
    for (const call of run.calls) assert.ok(call.every((arg) => !arg.includes('.hq')), call.join(' '));
  }
});

test('the defaults are the iqraa images and deploy/release/.build', () => {
  const run = runBuild(draft, { defaults: true });

  assert.equal(run.status, 0, run.stdout + run.stderr);
  assert.equal(dockerCalls(run, 'image', 'inspect')[0].at(-1), `iqraa/platform:${PLATFORM}`);
  assert.equal(run.gatesSawPrefix, 'iqraa', 'the gates build the skill-tools image that skill-stage then runs');
  assert.ok(skillStage(run)[0].includes('iqraa/skill-tools'));
  const [build] = dockerCalls(run, 'build');
  assert.deepEqual(flagValues(build, '-t'), [`iqraa/release:${TAG}`]);
  assert.deepEqual(flagValues(build, '--build-arg'), [`PLATFORM=${PLATFORM}`, 'PLATFORM_REPO=iqraa/platform']);
  assert.equal(run.stages.length, 1, `the stage belongs in deploy/release/.build: ${run.stages}`);
});

test('extra skill folders are mounted read-only and passed to skill-stage in order', () => {
  const run = runBuild([...draft, '--extra', '<extra 1>', '--extra', '<extra 2>']);

  assert.equal(run.status, 0, run.stdout + run.stderr);
  const [stage] = skillStage(run);
  assert.deepEqual(flagValues(stage, '--extra'), ['/extra/0', '/extra/1']);
  const mounts = flagValues(stage, '-v');
  assert.ok(mounts.some((mount) => mount.endsWith('/extra one:/extra/0:ro')), mounts.join(' | '));
  assert.ok(mounts.some((mount) => mount.endsWith('/extra two:/extra/1:ro')), mounts.join(' | '));
});

test('every gate step build.sh asks for is one the real tools/gates.sh accepts', () => {
  const asked = [runBuild(draft), runBuild(production)].map((run) => callsOf(run, 'gates.sh')[0].slice(1));

  for (const args of asked) {
    // --list parses every argument first, so an unknown step or option exits 2 here, and nothing runs.
    const listed = spawnSync('bash', [realGates, '--list', ...args], { encoding: 'utf8', env: baseEnv });
    assert.equal(listed.status, 0, `tools/gates.sh refuses ${args.join(' ')}: ${listed.stderr}`);
  }
});
