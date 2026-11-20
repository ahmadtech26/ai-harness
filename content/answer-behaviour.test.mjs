// Tests for the answer-behaviour set:  node --test content/answer-behaviour.test.mjs
// content/eval/answer-behaviour-v1.jsonl: a header line, then one item per line (README «answer-behaviour-v1»).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const lines = fs.readFileSync(path.join(here, 'eval', 'answer-behaviour-v1.jsonl'), 'utf8').split('\n').filter((l) => l.trim());
const [header, ...items] = lines.map((line) => JSON.parse(line));
const LAWS = new Set(JSON.parse(fs.readFileSync(path.join(here, 'corpus', 'laws.json'), 'utf8')).laws.map((l) => l.slug));
const ARABIC = /[؀-ۿ]/;

test('the header names the set, its review state, the automatic fails and an eight-line rubric', () => {
  assert.equal(header.set, 'answer-behaviour-v1');
  assert.ok(['draft', 'approved'].includes(header.review?.status));
  assert.ok(header.automatic_fails.length >= 4);
  assert.equal(header.rubric.length, 8);
});

test('every item has a unique id, an Arabic question, a tier, library laws, and what is required and what fails', () => {
  const ids = items.map((item) => item.id);

  assert.equal(new Set(ids).size, ids.length);
  for (const item of items) {
    assert.match(item.id, /^behaviour-\d{2}$/);
    assert.match(item.question, ARABIC, item.id);
    assert.ok(['fast', 'advanced', 'expert'].includes(item.tier), item.id);
    assert.ok(item.laws.length > 0 && item.laws.every((law) => LAWS.has(law)), `${item.id}: ${item.laws}`);
    assert.match(item.required, ARABIC, item.id);
    assert.ok(item.fails.length > 0 && item.fails.every((fail) => ARABIC.test(fail)), item.id);
    assert.ok(item.source?.trim(), item.id);
  }
});
