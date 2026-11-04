// Tests for the mock model's FINAL_TEXT directive:  node --test mock-llm.test.mjs
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { Readable } from 'node:stream';
import { test } from 'node:test';

process.env.MOCK_LLM_LOG = '/dev/null';
const { decide, providerErrorFor, readBody } = createRequire(import.meta.url)('./mock-llm.cjs');

const tool = (name) => ({ type: 'function', function: { name } });
const ARTICLE = 'المادة 29 من القانون المدني الأردني تنص على كذا وكذا.';

test('answers with the FINAL_TEXT line when no tool was asked for', () => {
  const decision = decide({ messages: [{ role: 'user', content: `سؤال\nFINAL_TEXT:${ARTICLE}\nrun-tag` }], tools: [] });

  assert.deepEqual(decision, { kind: 'text', text: ARTICLE });
});

test('calls the tool first when CALL_TOOL is also present, and gives the FINAL_TEXT once it has run', () => {
  const content = `CALL_TOOL:get_article:{"number":107}\nFINAL_TEXT:${ARTICLE}`;
  const first = decide({ messages: [{ role: 'user', content }], tools: [tool('get_article_mcp_legal-search')] });
  const second = decide({
    messages: [
      { role: 'user', content },
      { role: 'assistant', content: null, tool_calls: [{ id: 'c1' }] },
      { role: 'tool', content: '[1] نص' },
    ],
    tools: [tool('get_article_mcp_legal-search')],
  });

  assert.equal(first.kind, 'tool');
  assert.deepEqual(second, { kind: 'text', text: ARTICLE });
});

test('streams the FINAL_TEXT a word at a time when SLOW_STREAM is also present, and the plain slow text as before', () => {
  const slow = decide({ messages: [{ role: 'user', content: `SLOW_STREAM:250 stop\nFINAL_TEXT:${ARTICLE}` }], tools: [] });
  const plain = decide({ messages: [{ role: 'user', content: 'SLOW_STREAM:100 stop' }], tools: [] });

  assert.deepEqual(slow, { kind: 'text', text: ARTICLE, slowMs: 250 });
  assert.equal(plain.slowMs, 100);
  assert.equal(plain.text.match(/\S+\s*/g).length, 40);
});

test('still answers the plain mock text without the directive', () => {
  assert.equal(decide({ messages: [{ role: 'user', content: 'hello' }], tools: [] }).text, 'MOCK_OK: hello');
});

test('keeps an Arabic word whole when the request body arrives split inside a letter', async () => {
  const body = Buffer.from('قانون');

  const text = await readBody(Readable.from([body.subarray(0, 1), body.subarray(1)]));

  assert.equal(text, 'قانون');
});

test('refuses a PROVIDER_ERROR turn with a 400 whose text names the model, and nothing else', () => {
  const refusal = providerErrorFor('سؤال PROVIDER_ERROR tag-1', 'mock-model');

  assert.equal(refusal.status, 400);
  assert.ok(refusal.body.error.message.includes('mock-model') && refusal.body.error.message.includes('MockLLM'));
  assert.equal(providerErrorFor('سؤال عادي', 'mock-model'), null);
});
