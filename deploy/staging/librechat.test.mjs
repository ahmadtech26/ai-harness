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

// The fork starts only with exactly these four library headers (AI Platform-next packages/api/src/iqraa/config.ts
// LIBRARY_REQUEST_HEADERS, hook M1): any other set is the fault «other requestHeaders». X-Iqraa-Tier carries the tier
// spec legal-search grants the allowance by (plan F3), so this yaml and the fork image ship in one recreate.
const LIBRARY_REQUEST_HEADERS = {
  'X-Iqraa-User': '{{LIBRECHAT_USER_ID}}',
  'X-Iqraa-Message': '{{LIBRECHAT_BODY_MESSAGEID}}',
  'X-Iqraa-Conversation': '{{LIBRECHAT_BODY_CONVERSATIONID}}',
  'X-Iqraa-Tier': '{{LIBRECHAT_BODY_IQRAATIER}}',
};

/** The legal-search MCP server's requestHeaders, as [header, value] in file order (values unquoted). */
function libraryRequestHeaders(text) {
  const lines = text.split(/\r?\n/);
  const server = lines.indexOf('  legal-search:', lines.indexOf('mcpServers:'));
  const start = lines.indexOf('    requestHeaders:', server);
  assert.ok(server > 0 && start > server, 'librechat.yaml has mcpServers.legal-search.requestHeaders');
  const headers = [];
  for (const line of lines.slice(start + 1)) {
    const pair = /^      ([A-Za-z0-9-]+):\s*(.*)$/.exec(line);
    if (!pair) break;
    headers.push([pair[1], pair[2].replace(/^(['"])(.*)\1$/, '$2')]);
  }
  return headers;
}

test('librechat.yaml pins the four library request headers', () => {
  // Fails if a header is missing, extra or has another value: the fork would refuse to start, or the tier would not
  // reach legal-search and every answer would get the lowest allowance.
  assert.deepEqual(libraryRequestHeaders(yaml), Object.entries(LIBRARY_REQUEST_HEADERS));
});
