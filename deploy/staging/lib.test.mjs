// Tests for the tier-aware chat helper of lib.mjs, with fetch stubbed:  node --test lib.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { test } from 'node:test';

const calls = [];
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url: String(url), body: options.body ? JSON.parse(options.body) : undefined });
  if (String(url).endsWith('/api/config')) {
    return new Response(JSON.stringify({ modelSpecs: { list: [{ name: 'iqraa-fast', preset: { endpoint: 'agents', agent_id: 'agent_fast' } }] } }), { status: 200 });
  }
  return new Response(JSON.stringify({ error: 'stop here' }), { status: 400 }); // ends the turn at its start
};
const { chat, specFor, COMPOSE } = await import('./lib.mjs');
const started = () => calls.filter((call) => call.url.endsWith('/api/agents/chat/agents')).at(-1).body;

test('names the tier of a tier agent, from the startup config the client reads', async () => {
  assert.equal(await specFor('token', 'agent_fast'), 'iqraa-fast');
  assert.equal(await specFor('token', 'agent_unlisted'), null);
});

test('a turn on a tier agent carries the tier as its spec, beside the agent id', async () => {
  await chat({ token: 'token', agentId: 'agent_fast', text: 'سؤال' });

  assert.equal(started().spec, 'iqraa-fast');
  assert.equal(started().agent_id, 'agent_fast');
  assert.equal(started().endpoint, 'agents');
});

test('a turn on an agent that is no tier sends no spec, and an explicit spec wins', async () => {
  await chat({ token: 'token', agentId: 'agent_unlisted', text: 'سؤال' });
  assert.equal('spec' in started(), false);

  await chat({ token: 'token', agentId: 'agent_unlisted', text: 'سؤال', spec: 'iqraa-expert' });
  assert.equal(started().spec, 'iqraa-expert');
});

// The librechat service's environment block, read line by line: the compose is plain two-space YAML.
function librechatEnvironment(file) {
  const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/);
  const indent = (line) => line.length - line.trimStart().length;
  const service = lines.findIndex((line) => line === '  librechat:');
  assert.notEqual(service, -1, 'compose has no librechat service');
  const env = {};
  let inside = false;
  for (const line of lines.slice(service + 1)) {
    const text = line.trim();
    if (text === '' || text.startsWith('#')) continue;
    if (indent(line) <= 2) break;
    if (indent(line) === 4) {
      inside = text === 'environment:';
      continue;
    }
    const pair = inside && indent(line) === 6 ? /^([A-Z0-9_]+):\s*(.*)$/.exec(text) : null;
    if (pair) env[pair[1]] = pair[2].replace(/^(['"])(.*)\1$/, '$2');
  }
  return env;
}

test('staging turns Langfuse tracing off, or the fork refuses to start it (R2 n=31)', () => {
  assert.equal(librechatEnvironment(COMPOSE).LANGFUSE_TRACING_ENABLED, 'false');
});

test('staging enforces LibreChat script policy, or the fork refuses to start it (R1 n=31)', () => {
  const env = librechatEnvironment(COMPOSE);

  assert.equal(env.CSP_ENABLED, 'true');
  assert.equal(env.CSP_REPORT_ONLY, 'false');
  assert.notEqual((env.SECURITY_HEADERS ?? '').toLowerCase(), 'false');
});
