// Tests for tier-agents.mjs:  node --test content/tier-agents.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { featuredTexts } from './starters.mjs';
import { LIBRARY_TOOLS, TIER_CATEGORY_PREFIX, USAGE_ON_AGENT, findTierAgent, lintAgentBody, planTierAgents, retiredAgents } from './tier-agents.mjs';

const contentDir = path.dirname(fileURLToPath(import.meta.url));
const tiersDoc = JSON.parse(fs.readFileSync(path.join(contentDir, 'tiers.json'), 'utf8'));
const startersDoc = JSON.parse(fs.readFileSync(path.join(contentDir, 'starters', 'starters.ar.json'), 'utf8'));
const plan = (env = {}) => planTierAgents({ tiersDoc, contentDir, startersDoc, env });

const byOrder = () => [...tiersDoc.tiers].sort((a, b) => a.order - b.order);

test('plans one agent per tier in tier order, named by its label, with the AQEL instructions and the library tools only', () => {
  const planned = plan();

  assert.deepEqual(planned.map((entry) => entry.body.name), byOrder().map((tier) => tier.label));
  for (const { body } of planned) {
    assert.deepEqual(body.tools, LIBRARY_TOOLS);
    assert.ok(body.instructions.includes('AQEL LEGAL ENGINE'));
    assert.equal(body.skill_authoring_enabled, false);
  }
  assert.deepEqual(planned.map((entry) => entry.plans), byOrder().map((tier) => tier.plans));
});

test('marks each agent with its tier key in the category, which survives a rename of the label', () => {
  assert.deepEqual(plan().map((entry) => entry.body.category), byOrder().map((tier) => `${TIER_CATEGORY_PREFIX}${tier.key}`));
});

test('finds a tier agent by its category before its name, and retires only agents of removed tiers and the legacy agent', () => {
  const [fast, advanced] = plan().map((entry) => entry.body);
  const listed = [
    { id: 'a1', name: 'اسم قديم', category: fast.category },
    { id: 'a2', name: advanced.name, category: 'general' },
    { id: 'a3', name: 'عقل قديم', category: `${TIER_CATEGORY_PREFIX}removed` },
    { id: 'a4', name: 'عقل — المستشار القانوني', category: 'general' },
    { id: 'a5', name: 'وكيل آخر', category: 'general' },
  ];

  assert.equal(findTierAgent(listed, fast).id, 'a1');
  assert.equal(findTierAgent(listed, advanced).id, 'a2');
  assert.deepEqual(retiredAgents(listed, new Set(['a1', 'a2'])).map((agent) => agent.id), ['a3', 'a4']);
});

test('gives each agent the four featured starters and the tier model, which the environment may override', () => {
  const [fast] = plan();
  const [overridden] = plan({ IQRAA_PROVIDER: 'MockLLM', IQRAA_MODEL: 'other-model' });

  const first = byOrder()[0];
  assert.deepEqual(fast.body.conversation_starters, featuredTexts(startersDoc));
  assert.equal(fast.body.conversation_starters.length, 4);
  assert.deepEqual([fast.body.provider, fast.body.model], [first.provider, first.model]);
  assert.equal(overridden.body.model, 'other-model');
});

// A tier's instructionsSuffix goes after the composed text, pinned skill included, so every tier shares the composed
// text as its prefix (and its prompt cache). Edition 1.3.1 gives every tier one (plan Amendment 3, owner 2026-11-14):
// its own allowance, and for fast also its limits.
const strip = (keys) => ({
  ...tiersDoc,
  tiers: tiersDoc.tiers.map(({ instructionsSuffix, ...tier }) => (keys.includes(tier.key) ? tier : { ...tier, instructionsSuffix })),
});
const withoutSuffixes = strip(tiersDoc.tiers.map((tier) => tier.key));
const composedText = () => planTierAgents({ tiersDoc: withoutSuffixes, contentDir, startersDoc, env: {} })[0].body.instructions;
const textOf = (key) => plan().find((entry) => entry.tier.key === key).body.instructions;
/** build_aqel.py ALLOWANCE_AR's line, pinned literally as check_instructions.mjs reads it: the tier's own allowance. */
const ALLOWANCE_LINE = /^- رصيد كل إجابة: (\d+) من نصوص المكتبة في مجموعها\.$/gm;
const statedAllowances = (text) => [...text.matchAll(ALLOWANCE_LINE)].map((match) => Number(match[1]));

test('a tier without a suffix gets the composed text unchanged', () => {
  // Fails if a suffix leaks into a tier that has none, or the composed text is altered for every tier.
  const planned = planTierAgents({ tiersDoc: strip(['expert']), contentDir, startersDoc, env: {} });
  const unsuffixed = planned.filter((entry) => !entry.tier.instructionsSuffix);

  assert.deepEqual(unsuffixed.map((entry) => entry.tier.key), ['expert']);
  for (const { body } of unsuffixed) assert.equal(body.instructions, composedText());
});

test("every tier's text is the composed text, a blank line and its own suffix", () => {
  // Fails if a tier has no suffix, a suffix is dropped, placed before the pinned skill, joined without one blank line,
  // or given to another tier.
  const composed = composedText();

  assert.ok(composed.endsWith('\n') && !composed.endsWith('\n\n'));
  for (const tier of tiersDoc.tiers) {
    assert.ok(tier.instructionsSuffix, `${tier.key} has a suffix`);
    const suffix = fs.readFileSync(path.join(contentDir, tier.instructionsSuffix), 'utf8').replace(/\r\n/g, '\n');
    assert.equal(textOf(tier.key), `${composed}\n${suffix}`, tier.key);
  }
  assert.equal(new Set(tiersDoc.tiers.map((tier) => tier.instructionsSuffix)).size, tiersDoc.tiers.length);
  for (const { body } of plan()) assert.deepEqual(lintAgentBody(body), []);
});

// The allowance each tier's text states must be legal-search's guard_settings value for that tier (per_answer,
// per_answer_advanced, per_answer_expert: 8, 11, 16, set by L3's PUT); check_instructions.mjs --allowance compares
// the live pair. Each tier is tested on its own, so one wrong number names its tier.
test('the fast tier states its allowance of 8 texts, once', () => {
  assert.deepEqual(statedAllowances(textOf('fast')), [8]);
});

test('the advanced tier states its allowance of 11 texts, once', () => {
  assert.deepEqual(statedAllowances(textOf('advanced')), [11]);
});

test('the expert tier states its allowance of 16 texts, once', () => {
  assert.deepEqual(statedAllowances(textOf('expert')), [16]);
});

test('lists no pinned skill among the listed ones, since pinned bodies live in the instructions', () => {
  const [fast] = plan();

  for (const name of fast.pinned) assert.ok(!fast.body.skills.includes(name));
});

const good = () => structuredClone(plan()[0].body);

test('the lint accepts the planned agent', () => {
  assert.deepEqual(lintAgentBody(good()), []);
});

test('the lint refuses web search, code execution, another MCP server and a missing library tool', () => {
  const body = good();
  body.tools = [...LIBRARY_TOOLS.slice(1), 'web_search', 'execute_code', 'x_mcp_browser'];

  const errors = lintAgentBody(body);

  assert.deepEqual(errors, [
    'tool web_search is not a library tool',
    'tool execute_code is not a library tool',
    'tool x_mcp_browser is not a library tool',
    'library tool search_law_mcp_legal-search is missing',
  ]);
});

test('the lint refuses a provider-side search switch, instructions without the corpus rule and authoring', () => {
  const body = good();
  body.model_parameters = { web_search: true, useResponsesApi: true };
  body.instructions = 'be helpful';
  body.skill_authoring_enabled = true;

  const errors = lintAgentBody(body);

  assert.ok(errors.includes('model parameter web_search is not allowed'));
  assert.ok(errors.includes('model parameter useResponsesApi is not allowed'));
  assert.ok(errors.some((e) => e.includes('instructions lack the AQEL text')));
  assert.ok(errors.includes('skill_authoring_enabled must be false'));
});

// LibreChat (since v0.8.9-rc1) refuses `streamUsage` in an agent's model_parameters, so a release carrying it fails
// with a 400, and a stored one is dropped at run time. Usage is the tier endpoint's job (addParams, see tiers.mjs).
test('the planned agents carry no usage flag of their own', () => {
  for (const { body } of plan()) assert.equal(Object.hasOwn(body.model_parameters ?? {}, 'streamUsage'), false);
});

test('the lint refuses streamUsage on an agent, true or false, and names the endpoint setting that replaces it', () => {
  for (const value of [true, false]) {
    const body = good();
    body.model_parameters = { ...body.model_parameters, streamUsage: value };

    assert.deepEqual(lintAgentBody(body), [USAGE_ON_AGENT]);
    assert.ok(USAGE_ON_AGENT.includes('addParams.streamUsage: true'));
  }
});
