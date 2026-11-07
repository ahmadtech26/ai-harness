// Every image the Harness runs or builds from is pinned by digest (O-57), so a rebuild or a new host gets what was tested:
//   node --test deploy/pins.test.mjs
// It only reads files: the images of deploy/staging/compose*.yaml, FROM and COPY --from in every Dockerfile under
// deploy/ and tools/, and the images deploy/dev/platform.sh, tools/gates.sh and deploy/staging/ui/run-rtl-check.mjs run.
// Exempt: our own images (iqraa/, built here), throwaway test tags (hardening-test/), and a reference a variable
// supplies (${...} or $name), whose value is checked where it is written. Not scanned: docker-tests/, services/, and the
// build and run output in deploy/release/.build and deploy/staging/out.
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { isBuiltin } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const HARNESS = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKIPPED = new Set(['docker-tests', 'services', 'node_modules', '.git']);
// Build and run output, not the Harness's own: build-platform.sh exports the whole fork to deploy/release/.build/<sha>,
// upstream's floating Dockerfile included, and the staging driver writes deploy/staging/out.
const SKIPPED_PATHS = ['deploy/release/.build', 'deploy/staging/out'];

/** True when `ref` names an image by tag alone: not pinned by digest and not exempt. */
function floats(ref) {
  if (/^(iqraa|hardening-test)\//.test(ref) || ref.includes('$')) return false;
  return !/@sha256:[0-9a-f]{64}$/.test(ref);
}

const lines = (text) => text.split(/\r?\n/).map((body, i) => ({ line: i + 1, body }));
const unquote = (word) => word.replace(/^(['"])(.*)\1$/, '$2');

// compose: every `image:` value.
function composeImages(text) {
  return lines(text).flatMap(({ line, body }) => {
    const m = body.match(/^\s*image:\s*(\S+)/);
    return m ? [{ line, ref: unquote(m[1]) }] : [];
  });
}

// Dockerfile: FROM and COPY --from, less the names of earlier stages (FROM base AS source) and stage numbers.
function dockerfileImages(text) {
  const stages = new Set();
  const refs = [];
  for (const { line, body } of lines(text)) {
    const from = body.match(/^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?/i);
    const copy = body.match(/^\s*COPY\s.*?--from=(\S+)/i);
    const ref = from?.[1] ?? copy?.[1];
    if (ref && !stages.has(ref.toLowerCase()) && !/^\d+$/.test(ref) && ref !== 'scratch') refs.push({ line, ref });
    if (from?.[2]) stages.add(from[2].toLowerCase());
  }
  return refs;
}

// docker run options that take the next word as their value (the ones these scripts use, and their kin).
const VALUED = new Set(['-v', '--volume', '-e', '--env', '--env-file', '-w', '--workdir', '--name', '--network', '--net',
  '--entrypoint', '-p', '--publish', '--tmpfs', '--mount', '-u', '--user', '-l', '--label', '--platform', '-m', '--memory',
  '--cpus', '--add-host', '-h', '--hostname', '--pull', '--restart', '--shm-size', '--ulimit', '--log-opt', '--log-driver']);

// Shell words of one command line, quotes removed; enough for these scripts, not a shell parser.
const words = (body) => [...body.matchAll(/"([^"]*)"|'([^']*)'|(\S+)/g)].map((m) => m[1] ?? m[2] ?? m[3]);

// Shell: `image=` assignments and the image word of each `docker run`. Full-line comments are skipped and
// backslash-continued lines joined; an array expansion such as "${volumes[@]}" carries options.
function shellImages(text) {
  const commands = [];
  for (const { line, body } of lines(text)) {
    if (/^\s*#/.test(body)) continue;
    const last = commands.at(-1);
    if (last?.open) last.body += ` ${body}`;
    else commands.push({ line, body });
    commands.at(-1).open = /\\$/.test(body);
    commands.at(-1).body = commands.at(-1).body.replace(/\\$/, '');
  }
  const refs = [];
  for (const { line, body } of commands) {
    for (const m of body.matchAll(/(?:^|\s)image=("[^"]*"|'[^']*'|\S+)/g)) refs.push({ line, ref: unquote(m[1]) });
    for (const m of body.matchAll(/\bdocker\s+run\s+(.*)/g)) {
      const rest = words(m[1]);
      for (let i = 0; i < rest.length; i += 1) {
        const word = rest[i];
        if (/^\$\{\w+\[@\]\}$/.test(word)) continue;
        if (word.startsWith('-')) {
          if (VALUED.has(word)) i += 1;
          continue;
        }
        refs.push({ line, ref: word });
        break;
      }
    }
  }
  return refs;
}

const IMAGE = /^(?:[a-z0-9]+(?:[._-][a-z0-9]+)*(?::\d+)?\/)*[a-z0-9]+(?:[._-][a-z0-9]+)*(?::\w[\w.-]{0,127})?(?:@sha256:[0-9a-f]{64})?$/;

// JavaScript: each quoted literal shaped like an image with a tag or a digest, other than a node: module specifier.
function scriptImages(text) {
  return lines(text).flatMap(({ line, body }) => {
    if (/^\s*\/\//.test(body)) return [];
    return [...body.matchAll(/'([^'\n]*)'|"([^"\n]*)"/g)]
      .map((m) => m[1] ?? m[2])
      .filter((literal) => IMAGE.test(literal) && /[:@]/.test(literal) && !isBuiltin(literal))
      .map((ref) => ({ line, ref }));
  });
}

/** Harness-relative paths of the files named Dockerfile under `dir` of `root`, less the skipped folders. */
function dockerfiles(dir, root = HARNESS) {
  return readdirSync(path.join(root, dir), { recursive: true })
    .map((rel) => path.join(dir, rel).replaceAll('\\', '/'))
    .filter((rel) => path.basename(rel) === 'Dockerfile' && !rel.split('/').some((part) => SKIPPED.has(part)))
    .filter((rel) => !SKIPPED_PATHS.some((skipped) => rel.startsWith(`${skipped}/`)));
}

const composeFiles = readdirSync(path.join(HARNESS, 'deploy/staging'))
  .filter((name) => /^compose.*\.yaml$/.test(name))
  .map((name) => `deploy/staging/${name}`);

const SOURCES = [
  ...composeFiles.map((file) => ({ file, extract: composeImages })),
  ...[...dockerfiles('deploy'), ...dockerfiles('tools')].map((file) => ({ file, extract: dockerfileImages })),
  { file: 'deploy/dev/platform.sh', extract: shellImages },
  { file: 'tools/gates.sh', extract: shellImages },
  { file: 'deploy/staging/ui/run-rtl-check.mjs', extract: scriptImages },
];
const found = SOURCES.map(({ file, extract }) => ({ file, refs: extract(readFileSync(path.join(HARNESS, file), 'utf8')) }));

test('floats tells a tag from a digest', () => {
  assert.equal(floats('node:24-alpine@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53'), false);
  assert.equal(floats('node:24-alpine'), true);
});

// A scan that finds nothing would pass with every image floating. compose.summary.yaml only adds a mount.
test('every source scanned yields its images', () => {
  const empty = found.filter(({ file, refs }) => refs.length === 0 && file !== 'deploy/staging/compose.summary.yaml').map(({ file }) => file);
  assert.deepEqual(empty, []);
  for (const file of ['deploy/staging/compose.yaml', 'deploy/release/Dockerfile', 'tools/skills/Dockerfile']) {
    assert.ok(found.some((source) => source.file === file), `${file} was not scanned`);
  }
});

// The walk itself, on a tree of its own: the real build output is empty or absent on most checkouts, so a case
// against it would pass whether or not the walk skips it.
test('the Dockerfile walk skips build and run output', () => {
  const tree = mkdtempSync(path.join(os.tmpdir(), 'pins walk '));
  try {
    for (const dir of ['deploy/release', 'deploy/release/.build/abc1234', 'deploy/staging/out/abc1234', 'deploy/staging/proxy']) {
      mkdirSync(path.join(tree, dir), { recursive: true });
      writeFileSync(path.join(tree, dir, 'Dockerfile'), 'FROM node:24-alpine\n');
    }
    assert.deepEqual(dockerfiles('deploy', tree).sort(), ['deploy/release/Dockerfile', 'deploy/staging/proxy/Dockerfile']);
  } finally {
    rmSync(tree, { recursive: true, force: true });
  }
});

test('every image is pinned by digest', () => {
  const floating = found.flatMap(({ file, refs }) => refs.filter(({ ref }) => floats(ref)).map(({ line, ref }) => `${file}:${line} ${ref}`));
  assert.deepEqual(floating, []);
});
