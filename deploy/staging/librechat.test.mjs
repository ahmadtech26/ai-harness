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

// A top-level block of this plain two-space YAML, as { key: value } of its own keys, values unquoted (nested keys skipped).
function topLevelBlock(text, name) {
  const lines = text.split(/\r?\n/);
  const start = lines.indexOf(`${name}:`);
  assert.notEqual(start, -1, `librechat.yaml has no top-level ${name}:`);
  const block = {};
  for (const line of lines.slice(start + 1)) {
    if (line.trim() === '' || line.trimStart().startsWith('#')) continue;
    if (!line.startsWith(' ')) break;
    const pair = /^  ([A-Za-z0-9_]+):\s*(.*)$/.exec(line);
    if (pair) block[pair[1]] = pair[2].replace(/^(['"])(.*)\1$/, '$2');
  }
  return block;
}

// LibreChat shows the context gauge, and the Compact button beside it, unless the interface turns it off (default true).
test('the interface turns the context gauge and its Compact button off, for everyone (O-90, O-115)', () => {
  assert.equal(topLevelBlock(yaml, 'interface').contextUsage, 'false');
});

// LibreChat shows the composer's thinking and effort pill, and the Parameters side panel, only when interface.parameters is
// true (Thinking.tsx, useSideNavLinks.ts). Model specs default it to false, but an explicit true turns both back on for
// everyone, and the fork's start-up checks do not refuse it; the owner chose to keep them hidden (2026-11-08).
test('the interface keeps the thinking and effort pill and the Parameters panel off, for everyone', () => {
  assert.equal(topLevelBlock(yaml, 'interface').parameters, 'false');
});
