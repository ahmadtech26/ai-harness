// Tests for the tier-aware chat helper of lib.mjs, with fetch stubbed:  node --test lib.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';

const calls = [];
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url: String(url), body: options.body ? JSON.parse(options.body) : undefined });
  if (String(url).endsWith('/api/config')) {
    return new Response(JSON.stringify({ modelSpecs: { list: [{ name: 'iqraa-fast', preset: { endpoint: 'agents', agent_id: 'agent_fast' } }] } }), { status: 200 });
  }
  return new Response(JSON.stringify({ error: 'stop here' }), { status: 400 }); // ends the turn at its start
};
const { chat, specFor } = await import('./lib.mjs');
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
