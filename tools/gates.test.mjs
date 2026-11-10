// Tests for gates.sh, with docker and node stubbed first on PATH:  node --test tools/gates.test.mjs
// No case may reach the real tools: the file stops before any test unless bash resolves both to the stubs.
// Each case runs a copy of gates.sh in its own Harness-shaped tree, so the result does not depend on which folders and
// test files the checkout has today. The temp paths carry spaces on purpose, because the real checkouts do ("AI Harness").
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const source = (relative) => fileURLToPath(new URL(relative, import.meta.url));
const STEPS = ['checks', 'skills', 'plan', 'legal-search', 'eval', 'node', 'docker', 'fork'];
const PLAN_IMAGE = 'python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704';
const SEARCH = 'docker compose -p release-gates-tests -f services/legal-search/compose.test.yaml';
const EVAL = 'docker compose -p release-gates-eval -f services/legal-search/compose.test.yaml -f deploy/release/compose.eval.yaml';

const root = mkdtempSync(path.join(os.tmpdir(), 'gates test ')).replaceAll('\\', '/');
after(() => rmSync(root, { recursive: true, force: true }));

// Each stub appends one line per call, tab separated: the tool, the two settings gates.sh answers for, then argv.
// A call whose argv contains $STUB_FAIL exits $STUB_EXIT (default 1); every other call exits 0. The AI Platform's
// tools/dev.sh, which a case may give PLATFORM_DIR, is the same stub.
const stub = (tool) => `#!/bin/sh
(IFS='\t'; printf '%s\\n' "${tool}\t\${MSYS_NO_PATHCONV:-}\t\${IQRAA_EVAL_OUT:-}\t$*") >> "$STUB_LOG"
if [ -n "\${STUB_FAIL:-}" ]; then
  case " $* " in *"$STUB_FAIL"*) exit "\${STUB_EXIT:-1}" ;; esac
fi
`;
const stubDir = `${root}/stubs`;
mkdirSync(stubDir);
for (const tool of ['docker', 'node']) writeFileSync(`${stubDir}/${tool}`, stub(tool), { mode: 0o755 });

const scrubbed = ['path', 'platform_dir', 'iqraa_image_prefix', 'iqraa_gates_project', 'iqraa_eval_out', 'msys_no_pathconv', 'tmpdir', 'stub_fail', 'stub_exit'];
const baseEnv = {
  ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !scrubbed.includes(key.toLowerCase()))),
  PATH: `${stubDir}${path.delimiter}${process.env.PATH}`,
};

const resolved = spawnSync('bash', ['-c', 'command -v docker; command -v node'], { encoding: 'utf8', env: baseEnv });
assert.deepEqual(
  resolved.stdout.trim().split('\n').map((found) => found.split('/').slice(-2).join('/')),
  ['stubs/docker', 'stubs/node'],
  `bash would reach a real tool, so no case may run: ${resolved.stdout}${resolved.stderr}`,
);

const TREE = {
  content: ['a.test.mjs'],
  'deploy/dev': [],
  'deploy/release': [],
  'deploy/staging': ['b.test.mjs'],
  'deploy/staging/docker-tests': ['d.test.mjs'],
  'services/legal-search': [],
  tools: ['c.test.mjs'],
  'tools/plan': [],
  'tools/skills': [],
};

// The mount source gates.sh must produce for a folder: its Windows form under Git Bash, itself elsewhere.
const win = (dir) => spawnSync('bash', ['-c', 'pwd -W 2>/dev/null || pwd'], { cwd: dir, encoding: 'utf8', env: baseEnv }).stdout.trim();

let caseNumber = 0;

// dev: true makes PLATFORM_DIR an AI Platform after the split, with a tools/dev.sh, in place of a LibreChat checkout.
function runGates(args = [], { env = {}, fail, exitCode, without = [], dev = false } = {}) {
  caseNumber += 1;
  const work = `${root}/case ${caseNumber}`;
  const tree = `${work}/AI Harness`;
  const platform = `${work}/AI Platform`;
  const log = `${work}/stub.log`;
  for (const [folder, files] of Object.entries(TREE)) {
    if (without.includes(folder)) continue;
    mkdirSync(`${tree}/${folder}`, { recursive: true });
    for (const file of files) writeFileSync(`${tree}/${folder}/${file}`, '');
  }
  mkdirSync(platform);
  if (dev) {
    mkdirSync(`${platform}/tools`);
    writeFileSync(`${platform}/tools/dev.sh`, stub('dev.sh'));
  }
  mkdirSync(`${work}/tmp`);
  copyFileSync(source('../deploy/dev/platform.sh'), `${tree}/deploy/dev/platform.sh`);
  if (existsSync(source('./gates.sh'))) copyFileSync(source('./gates.sh'), `${tree}/tools/gates.sh`);

  const result = spawnSync('bash', [`${tree}/tools/gates.sh`, ...args], {
    encoding: 'utf8',
    env: {
      ...baseEnv,
      PLATFORM_DIR: platform,
      TMPDIR: `${work}/tmp`,
      STUB_LOG: log,
      ...(fail ? { STUB_FAIL: fail } : {}),
      ...(exitCode ? { STUB_EXIT: String(exitCode) } : {}),
      ...env,
    },
  });
  const calls = existsSync(log)
    ? readFileSync(log, 'utf8').trim().split('\n').map((line) => {
        const [tool, pathconv, evalOut, ...argv] = line.split('\t');
        return { tool, pathconv, evalOut, argv, text: [tool, ...argv].join(' ') };
      })
    : [];
  const marks = result.stdout.split('\n').filter((line) => /^(==|PASS|FAIL) /.test(line));
  return { ...result, calls, marks, tree, platform, shown: `${result.stdout}${result.stderr}` };
}

// The fork commands reach docker through platform.sh, whose own flags are not this script's business.
const label = (call) => (call.argv.includes('-lc') ? `platform.sh ${call.argv.at(-1)}` : call.text);

test('with no step named, every gate runs in order, each command as the release needs it', () => {
  const run = runGates();

  assert.equal(run.status, 0, run.shown);
  assert.deepEqual(run.marks, STEPS.flatMap((step) => [`== ${step}`, `PASS ${step}`]));
  const tools = win(`${run.tree}/tools`);
  const whole = win(run.tree);
  assert.deepEqual(run.calls.map(label), [
    'docker build -q -t iqraa/skill-tools tools/skills',
    `docker run --rm -v ${whole}:/w:ro iqraa/skill-tools skill-ci --content /w/content`,
    `docker run --rm -v ${whole}:/w:ro iqraa/skill-tools corpus-ci --content /w/content --corpus /w/jordanian-law/references/القوانين-الأردنية`,
    'node content/tiers.mjs check',
    'node content/starters.mjs check content/starters/starters.ar.json',
    'node content/grounding-laws.mjs check',
    'docker build -q --target test -t iqraa/skill-tools-test tools/skills',
    'docker run --rm iqraa/skill-tools-test pytest -q',
    `docker run --rm -v ${win(`${run.tree}/tools/plan`)}:/p:ro -w /p ${PLAN_IMAGE} python -B -m unittest test_plan_tools`,
    `${SEARCH} run --rm --build tests`,
    `${SEARCH} down -v`,
    `${EVAL} run --rm --build eval check`,
    `${EVAL} run --rm --build eval run --label release --reset`,
    `${EVAL} run --rm --entrypoint python -v ${tools}:/tools:ro -v ${win(`${run.tree}/deploy/release`)}:/baseline:ro eval /tools/release_eval.py check --report /evidence/eval-release.json --baseline /baseline/eval-baseline.json`,
    `${EVAL} run --rm --entrypoint python -v ${tools}:/tools:ro -w /tools eval -B -m unittest test_release_eval test_recall_compare`,
    `${EVAL} down -v`,
    'node --test content/a.test.mjs deploy/staging/b.test.mjs tools/c.test.mjs',
    // One stack-booting file at a time: run together they exhaust Docker's network address pools.
    'node --test --test-concurrency=1 deploy/staging/docker-tests/d.test.mjs',
    'platform.sh cd packages/api && npx jest src/iqraa && npx tsc --noEmit',
    'platform.sh cd client && npx jest src/iqraa',
  ]);
});

test('named steps run alone, in the order given', () => {
  const run = runGates(['plan', 'skills']);

  assert.equal(run.status, 0, run.shown);
  assert.deepEqual(run.marks, ['== plan', 'PASS plan', '== skills', 'PASS skills']);
  assert.equal(run.calls.length, 3);
});

test('the first failing step stops the run with FAIL and exit 1, whatever code the command exited with', () => {
  const run = runGates([], { fail: '--target test', exitCode: 7 });

  assert.equal(run.status, 1, run.shown);
  assert.deepEqual(run.marks, ['== checks', 'PASS checks', '== skills', 'FAIL skills']);
  assert.equal(run.calls.at(-1).text, 'docker build -q --target test -t iqraa/skill-tools-test tools/skills');
});

test('a failure inside a step stops that step at once, though its last command would pass', () => {
  const built = runGates(['checks'], { fail: 'build -q -t iqraa/skill-tools ' });
  assert.equal(built.status, 1, built.shown);
  assert.deepEqual(built.marks, ['== checks', 'FAIL checks']);
  assert.equal(built.calls.length, 1);

  const tiers = runGates(['checks'], { fail: 'content/tiers.mjs' });
  assert.equal(tiers.status, 1, tiers.shown);
  assert.deepEqual(tiers.marks, ['== checks', 'FAIL checks']);
  assert.equal(tiers.calls.at(-1).text, 'node content/tiers.mjs check');
});

test('--release reaches skill-ci, corpus-ci and the starters check and nothing else; without it nothing has it', () => {
  const held = (run) =>
    run.calls
      .filter((call) => call.argv.includes('--release'))
      .map((call) => call.argv.find((arg) => ['skill-ci', 'corpus-ci', 'content/starters.mjs'].includes(arg)));

  const release = runGates(['--release']);
  assert.equal(release.status, 0, release.shown);
  assert.deepEqual(held(release), ['skill-ci', 'corpus-ci', 'content/starters.mjs']);

  const plain = runGates();
  assert.equal(plain.status, 0, plain.shown);
  assert.deepEqual(held(plain), []);
});

test('IQRAA_IMAGE_PREFIX and IQRAA_GATES_PROJECT reach every image name and compose project', () => {
  const run = runGates(['checks', 'skills', 'legal-search', 'eval'], {
    env: { IQRAA_IMAGE_PREFIX: 'stub-prefix', IQRAA_GATES_PROJECT: 'stub-project' },
  });

  assert.equal(run.status, 0, run.shown);
  const texts = run.calls.map((call) => call.text);
  assert.doesNotMatch(texts.join('\n'), /iqraa\/|release-gates/);
  assert.ok(texts.includes('docker build -q -t stub-prefix/skill-tools tools/skills'));
  assert.ok(texts.includes('docker build -q --target test -t stub-prefix/skill-tools-test tools/skills'));
  assert.ok(texts.includes('docker run --rm stub-prefix/skill-tools-test pytest -q'));
  assert.equal(texts.filter((text) => text.includes(' stub-prefix/skill-tools skill-ci ') || text.includes(' stub-prefix/skill-tools corpus-ci ')).length, 2);
  assert.equal(texts.filter((text) => text.startsWith('docker compose -p stub-project-tests ')).length, 2);
  assert.equal(texts.filter((text) => text.startsWith('docker compose -p stub-project-eval ')).length, 5);
});

test('legal-search tears its project down after a failed run', () => {
  const run = runGates(['legal-search', 'node'], { fail: 'run --rm --build tests' });

  assert.equal(run.status, 1, run.shown);
  assert.deepEqual(run.marks, ['== legal-search', 'FAIL legal-search']);
  assert.deepEqual(run.calls.map((call) => call.text), [`${SEARCH} run --rm --build tests`, `${SEARCH} down -v`]);
});

test('eval tears its project down after any of its four runs fails, and the runs after the failure do not happen', () => {
  ['eval check', '--reset', 'release_eval.py', 'test_release_eval'].forEach((failing, index) => {
    const run = runGates(['eval', 'node'], { fail: failing });

    assert.equal(run.status, 1, run.shown);
    assert.deepEqual(run.marks, ['== eval', 'FAIL eval']);
    assert.equal(run.calls.length, index + 2, failing);
    assert.ok(run.calls.at(-2).text.includes(failing), failing);
    assert.equal(run.calls.at(-1).text, `${EVAL} down -v`);
  });
});

test('a teardown that fails fails the step, because it leaves a database behind', () => {
  for (const step of ['legal-search', 'eval']) {
    const run = runGates([step, 'node'], { fail: ' down -v' });

    assert.equal(run.status, 1, run.shown);
    assert.deepEqual(run.marks, [`== ${step}`, `FAIL ${step}`]);
  }
});

test('every eval call passes the overlay after the test stack, and the legal-search calls do not pass it', () => {
  const run = runGates(['legal-search', 'eval']);

  assert.equal(run.status, 0, run.shown);
  const composed = run.calls.map((call) => call.text);
  assert.equal(composed.length, 7);
  assert.equal(composed.filter((text) => text.startsWith(`${EVAL} `)).length, 5);
  assert.equal(composed.filter((text) => text.startsWith(`${SEARCH} `)).length, 2);
});

test('eval gets one new folder for its evidence, in the form docker reads, and no other step sees it', () => {
  const run = runGates();

  assert.equal(run.status, 0, run.shown);
  const isEval = (call) => call.text.startsWith(`${EVAL} `);
  const folders = new Set(run.calls.filter(isEval).map((call) => call.evalOut));
  assert.equal(folders.size, 1);
  const [folder] = folders;
  assert.ok(statSync(folder).isDirectory(), folder);
  assert.deepEqual(run.calls.filter((call) => !isEval(call) && call.evalOut !== ''), []);

  const stale = runGates(['legal-search', 'eval'], { env: { IQRAA_EVAL_OUT: 'stale-folder' } });
  assert.equal(stale.status, 0, stale.shown);
  assert.ok(stale.calls.filter(isEval).every((call) => call.evalOut !== 'stale-folder' && statSync(call.evalOut).isDirectory()));
  assert.deepEqual(stale.calls.filter((call) => !isEval(call)).map((call) => call.evalOut), ['', '']);
});

test('MSYS_NO_PATHCONV is on every docker call that carries a container path and never on a docker build', () => {
  const run = runGates();

  assert.equal(run.status, 0, run.shown);
  for (const call of run.calls.filter(({ tool }) => tool === 'docker')) {
    if (call.argv[0] === 'build') assert.equal(call.pathconv, '', call.text);
    if (call.argv[0] === 'run' || call.argv.includes('-v')) assert.equal(call.pathconv, '1', call.text);
  }
});

test('fork mounts PLATFORM_DIR, and a failing api run skips the client run', () => {
  const run = runGates(['fork'], { fail: 'cd packages/api' });

  assert.equal(run.status, 1, run.shown);
  assert.deepEqual(run.marks, ['== fork', 'FAIL fork']);
  assert.equal(run.calls.length, 1);
  assert.ok(run.calls[0].argv.includes(`${win(run.platform)}:/work`), run.calls[0].text);
});

// The release reads as gated on the checked-out commit, so each fork run must follow an assemble of that checkout:
// a run on the tree last assembled would test whatever overlay and pin that was.
test('fork on an AI Platform with tools/dev.sh assembles the tree before each of its runs', () => {
  const run = runGates(['fork'], { dev: true });

  assert.equal(run.status, 0, run.shown);
  assert.deepEqual(run.marks, ['== fork', 'PASS fork']);
  const texts = run.calls.map((call) => call.text);
  assert.deepEqual(texts, [
    'dev.sh assemble',
    'dev.sh run cd packages/api && npx jest src/iqraa && npx tsc --noEmit',
    'dev.sh assemble',
    'dev.sh run cd client && npx jest src/iqraa',
  ]);
  assert.ok(texts.indexOf('dev.sh assemble') < texts.findIndex((text) => text.includes('npx jest')));
});

test('a failing assemble fails fork before any of its suites runs', () => {
  const run = runGates(['fork'], { dev: true, fail: 'assemble', exitCode: 3 });

  assert.equal(run.status, 1, run.shown);
  assert.deepEqual(run.marks, ['== fork', 'FAIL fork']);
  assert.deepEqual(run.calls.map((call) => call.text), ['dev.sh assemble']);
});

test('a folder a step must mount being absent fails the step, without a call that mounts an empty path', () => {
  const run = runGates(['plan'], { without: ['tools/plan'] });

  assert.equal(run.status, 1, run.shown);
  assert.deepEqual(run.marks, ['== plan', 'FAIL plan']);
  assert.deepEqual(run.calls, []);
});

test('a test step with no test files fails, without the bare node --test that would run whatever it discovers', () => {
  const run = runGates(['docker'], { without: ['deploy/staging/docker-tests'] });

  assert.equal(run.status, 1, run.shown);
  assert.deepEqual(run.marks, ['== docker', 'FAIL docker']);
  assert.deepEqual(run.calls, []);
});

// --list too: deploy/release/build.test.mjs asks `gates.sh --list <build.sh's steps>` whether every step is known.
test('an unknown step exits 2 before anything runs, though a known step or --list comes first', () => {
  for (const args of [['checks', 'nope'], ['--nope'], ['--list', 'nope']]) {
    const run = runGates(args);

    assert.equal(run.status, 2, run.shown);
    assert.deepEqual(run.marks, []);
    assert.deepEqual(run.calls, []);
  }
});

test('--list prints the steps in order and runs nothing', () => {
  const run = runGates(['--list']);

  assert.equal(run.status, 0, run.shown);
  assert.deepEqual(run.stdout.trim().split('\n'), STEPS);
  assert.deepEqual(run.calls, []);
});
