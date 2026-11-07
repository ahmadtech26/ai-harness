// No file a rebuild elsewhere reads may name this machine (O-59): no drive path, no user folder, no .hq/scratch.
//   node --test deploy/no-machine-paths.test.mjs
// It only reads files: the text files under deploy/, tools/ and services/, and README.md. Not scanned:
// deploy/release/.build and deploy/staging/out (build and run output), deploy/staging/docker-tests/fixtures,
// node_modules, __pycache__, .venv, .git, symbolic links, binary files (a NUL byte), any .env file (never read), and this
// file, which has to spell the paths it looks for. Not a needle: .hq/ itself, which the READMEs cite for the audit and
// plan documents; so the eval's .hq/docs evidence mount in services/legal-search/compose.test.yaml is not caught here.
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const HARNESS = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SELF = path.relative(HARNESS, fileURLToPath(import.meta.url)).replaceAll('\\', '/');

// Matched as written: case-sensitive substrings, not patterns.
const NEEDLES = ['/d/Iqraa', 'D:\\', 'D:/', 'C:/Users', 'C:\\Users', '.hq/scratch'];

/** Each machine path `text` names, as { line, needle }, one per needle on a line; [] when there is none. */
export function findMachinePaths(text) {
  return text.split(/\r?\n/).flatMap((body, i) => NEEDLES.filter((needle) => body.includes(needle)).map((needle) => ({ line: i + 1, needle })));
}

// The folders .gitignore keeps out: a local .venv's pyvenv.cfg names the user folder, and would fail the scan.
const SKIPPED_DIRS = new Set(['node_modules', '__pycache__', '.venv', '.git']);
const SKIPPED_PATHS = new Set(['deploy/release/.build', 'deploy/staging/out', 'deploy/staging/docker-tests/fixtures']);
const isEnv = (name) => name.startsWith('.env') || name.endsWith('.env');

/** Harness-relative paths of the files under `dir`, less the skipped folders, links, .env files and this file. */
function walk(dir) {
  return readdirSync(path.join(HARNESS, dir), { withFileTypes: true }).flatMap((entry) => {
    const rel = `${dir}/${entry.name}`;
    if (entry.isDirectory()) return SKIPPED_DIRS.has(entry.name) || SKIPPED_PATHS.has(rel) ? [] : walk(rel);
    return entry.isFile() && rel !== SELF && !isEnv(entry.name) ? [rel] : [];
  });
}

const scanned = [...walk('deploy'), ...walk('tools'), ...walk('services'), 'README.md']
  .map((file) => ({ file, bytes: readFileSync(path.join(HARNESS, file)) }))
  .filter(({ bytes }) => !bytes.includes(0));

test('findMachinePaths catches each machine path and passes a clean text', () => {
  const dirty = [
    'bash "/d/Iqraa Law/AI Harness/tools/gates.sh"',
    'cd D:\\Iqraa Law',
    'out=D:/Iqraa Law/out',
    'cache C:/Users/someone/.cache',
    'home C:\\Users\\someone',
    'log to .hq/scratch/run.log',
  ].join('\n');
  assert.deepEqual(
    findMachinePaths(dirty).map(({ line, needle }) => `${line} ${needle}`),
    ['1 /d/Iqraa', '2 D:\\', '3 D:/', '4 C:/Users', '5 C:\\Users', '6 .hq/scratch'],
  );
  const clean = 'cd "$(dirname "$0")/.."\nnode --test deploy/*.test.mjs\nimage: hardening-test/release:isolated';
  assert.deepEqual(findMachinePaths(clean), []);
});

// A walk that finds nothing, or wanders into build output, would pass or fail for the wrong reason.
test('the scan reads the Harness files and skips the excluded ones', () => {
  const files = scanned.map(({ file }) => file);
  for (const file of ['README.md', 'tools/gates.sh', 'deploy/release/build.sh', 'deploy/staging/compose.yaml', 'deploy/dev/platform.sh',
    'services/legal-search/compose.test.yaml']) {
    assert.ok(files.includes(file), `${file} was not scanned`);
  }
  const excluded = files.filter((file) => file === SELF || [...SKIPPED_PATHS].some((dir) => file.startsWith(`${dir}/`)));
  assert.deepEqual(excluded, []);
});

test('no scanned file names a machine path', () => {
  const found = scanned.flatMap(({ file, bytes }) =>
    findMachinePaths(bytes.toString('utf8')).map(({ line, needle }) => `${file}:${line} ${needle}`),
  );
  assert.deepEqual(found, []);
});
