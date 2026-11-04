// Tests for the pure parts of scenario chatonly:  node --test chatonly.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { BLOCKED_MESSAGE, DENIED_ROUTES, OPEN_ROUTES, PLAIN_CHAT_VARIANTS, findIdentityFields, findLeaks, framesOf, stopProbeText } from './chatonly.mjs';
import { createRequire } from 'node:module';

process.env.MOCK_LLM_LOG = '/dev/null';
const { decide } = createRequire(import.meta.url)('./mock-llm.cjs');

test('names the places a customer can read that hold the internal model', () => {
  const texts = { agent: '{"model":"iqraa"}', convo: '{"model":"mock-model"}', messages: '[{"model":"عقل سريع"}]' };

  assert.deepEqual(findLeaks(texts, ['mock-model', 'MockLLM']), ['convo']);
  assert.deepEqual(findLeaks({ agent: 'x' }, ['mock-model']), []);
});

test('names every key that holds the model or the provider, at any depth, and spares a message its own model', () => {
  const frames = framesOf(['event: message\ndata: {"event":"on_token_usage","data":{"model":"m","provider":"openAI","input_tokens":1}}', ': ping', 'data: not json']);

  assert.deepEqual(findIdentityFields(frames), ['$[0].data.model', '$[0].data.provider']);
  assert.deepEqual(findIdentityFields({ responseMessage: { messageId: 'm1', model: 'عقل سريع', metadata: { contextUsage: { provider: 'x' } } } }), ['$.responseMessage.metadata.contextUsage.provider']);
  assert.deepEqual(findIdentityFields({ conversationId: 'c1', model: 'agent_x', text: 'model provider' }), []);
});

test('lists each denied and open route once, all under /api', () => {
  const keys = [...DENIED_ROUTES, ...OPEN_ROUTES].map(([method, route]) => `${method} ${route}`);

  assert.equal(new Set(keys).size, keys.length);
  assert.ok(keys.every((key) => key.split(' ')[1].startsWith('/api/')));
  assert.ok(DENIED_ROUTES.length >= 25 && OPEN_ROUTES.length >= 8);
  assert.ok(keys.includes('GET /api/user/settings/favorites') && keys.includes('GET /api/files/speech/config/get'));
});

test('keeps the blocked-answer text the fork replaces an answer with', () => {
  assert.ok(BLOCKED_MESSAGE.startsWith('تعذّر عرض هذه الإجابة') && BLOCKED_MESSAGE.includes('المكتبة القانونية'));
});

test('probes the plain model chat on every spelling the review found: trailing slash, other endpoint, active, case, query', () => {
  const routes = PLAIN_CHAT_VARIANTS.map(([method, route]) => `${method} ${route}`);

  assert.equal(new Set(routes).size, routes.length);
  assert.ok(PLAIN_CHAT_VARIANTS.every(([method]) => method === 'POST'));
  assert.ok(routes.some((route) => route.endsWith('/chat/')) && routes.some((route) => route.includes('/active')));
  assert.ok(routes.some((route) => route.includes('?')) && routes.some((route) => route.startsWith('POST /API/')));
});

test('the stop probe makes the mock stream an ungrounded citation first, then slow filler the driver can stop on', () => {
  const decision = decide({ messages: [{ role: 'user', content: stopProbeText('tag-1') }], tools: [] });

  assert.equal(decision.kind, 'text');
  assert.equal(decision.slowMs, 250);
  assert.ok(decision.text.startsWith('نصت المادة 29 من القانون المدني المصري'));
  assert.equal(decision.text.match(/STREAMED_PIECE/g).length, 40);
  assert.ok(decision.text.match(/\S+\s*/g).findIndex((word) => word.startsWith('STREAMED_PIECE')) < 15);
});
