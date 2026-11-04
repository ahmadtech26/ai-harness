// Tests for release.mjs, planning only (no network):  node --test content/release.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const contentDir = path.dirname(fileURLToPath(import.meta.url));
const run = (args, env = {}) =>
  spawnSync(process.execPath, [path.join(contentDir, 'release.mjs'), ...args], { encoding: 'utf8', env: { ...process.env, ...env } });
const prices = path.join(contentDir, '..', 'deploy', 'staging', 'iqraa.json');

const tiersDoc = JSON.parse(fs.readFileSync(path.join(contentDir, 'tiers.json'), 'utf8'));

test('--dry-run plans every tier with the library tools and four starters, and calls nothing', () => {
  const result = run(['--dry-run', '--prices', prices]);

  assert.equal(result.status, 0, result.stderr);
  const planned = JSON.parse(result.stdout);
  const byOrder = [...tiersDoc.tiers].sort((a, b) => a.order - b.order);
  assert.deepEqual(planned.map((tier) => tier.key), byOrder.map((tier) => tier.key));
  assert.deepEqual(planned.map((tier) => tier.plans), byOrder.map((tier) => tier.plans));
  assert.ok(planned.every((tier) => tier.tools.length === 3 && tier.starters === 4));
});

test('a live release refuses to run without a price book or without the file apply reads', () => {
  const env = { IQRAA_STAFF_TOKEN: 'x' };

  assert.match(run([], env).stderr, /needs --prices .* and --resolved/);
  assert.match(run(['--prices', prices], env).stderr, /needs --prices .* and --resolved/);
  assert.match(run(['--resolved', 'out.json'], env).stderr, /needs --prices .* and --resolved/);
});

test('refuses to release when the model has no price in the target price book', () => {
  const result = run(['--dry-run', '--prices', prices], { IQRAA_MODEL: 'vendor/unpriced' });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /IQRAA_MODEL vendor\/unpriced has no price/);
});

test('refuses a production release of a draft starters set', () => {
  const result = run(['--dry-run', '--release', '--prices', prices]);

  assert.equal(result.status, 1);
  assert.match(result.stderr, /production needs an approved set/);
});

test('without a dry run it needs a staff session', () => {
  const result = run(['--prices', prices, '--resolved', 'out.json'], { IQRAA_STAFF_TOKEN: '', IQRAA_STAFF_IDENTIFIER: '', IQRAA_STAFF_APP_CODE: '' });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /set IQRAA_STAFF_TOKEN/);
});
