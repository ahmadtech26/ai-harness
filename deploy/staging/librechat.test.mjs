// The staging librechat.yaml against the tier contract:  node --test deploy/staging/librechat.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { tierProviders, usageProblems } from '../../content/tiers.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const yaml = fs.readFileSync(path.join(here, 'librechat.yaml'), 'utf8');
const tiersDoc = JSON.parse(fs.readFileSync(path.join(here, '..', '..', 'content', 'tiers.json'), 'utf8'));

// LibreChat refuses `streamUsage` on a tier agent, so the endpoint each tier runs on must ask the provider for usage,
// or metering settles every staging turn at its full hold (drill break 7). The scenarios release on MockLLM.
test('the endpoint of every tier, and the MockLLM endpoint the scenarios release on, asks the provider for usage', () => {
  assert.deepEqual(usageProblems(yaml, [...tierProviders(tiersDoc, {}), 'MockLLM']), []);
});
