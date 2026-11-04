// Tests for tiers.mjs:  node --test content/tiers.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { BEGIN, END, applyToIqraa, applyToYaml, setModel, specsBlock, validateTiers } from './tiers.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const tiers = JSON.parse(fs.readFileSync(path.join(here, 'tiers.json'), 'utf8'));
const roles = JSON.parse(fs.readFileSync(path.join(here, 'roles.json'), 'utf8'));
const prices = { 'mock-model': { input: 1, output: 1 } };
const clone = () => structuredClone(tiers);
const ordered = [...tiers.tiers].sort((a, b) => a.order - b.order);
const resolved = { tiers: tiers.tiers.map((tier) => ({ key: tier.key, spec: tier.spec, agentId: `agent_${tier.key}` })) };

test('the shipped tier table is valid against the plan roles and the staging price book', () => {
  assert.deepEqual(validateTiers(tiers, { roles, prices }), []);
});

test('rejects a plan that is not a role, a model with no price and a spec that does not match its key', () => {
  const doc = clone();
  doc.tiers[0].plans = ['PLAN_NOPE'];
  doc.tiers[1].model = 'vendor/unpriced';
  const expectedKey = doc.tiers[2].key;
  doc.tiers[2].spec = 'iqraa-other';

  const errors = validateTiers(doc, { roles, prices });

  assert.ok(errors.some((e) => e.includes('plan PLAN_NOPE is not a role')));
  assert.ok(errors.some((e) => e.includes('model vendor/unpriced has no price')));
  assert.ok(errors.some((e) => e.includes(`spec must be iqraa-${expectedKey}`)));
});

test('rejects a default tier that leaves a plan out, and a key or order used twice', () => {
  const doc = clone();
  const defaultTier = doc.tiers.find((tier) => tier.order === ordered[0].order);
  // A plan another tier lists, taken out of the default tier: the default no longer covers every plan.
  const shared = defaultTier.plans.find((plan) => doc.tiers.some((tier) => tier !== defaultTier && tier.plans.includes(plan)));
  defaultTier.plans = defaultTier.plans.filter((plan) => plan !== shared);
  const [first, second] = doc.tiers.filter((tier) => tier !== defaultTier);
  second.key = first.key;
  second.order = first.order;

  const errors = validateTiers(doc, { roles, prices });

  assert.ok(errors.some((e) => e.includes('must include every plan')));
  assert.ok(errors.some((e) => e.includes('key used twice')));
  assert.ok(errors.some((e) => e.includes('order used twice')));
});

test('writes one model spec per tier, in order, the first as the default, each with its private agent', () => {
  const block = specsBlock(tiers, resolved);

  assert.ok(block.startsWith(BEGIN) && block.trimEnd().endsWith(END));
  assert.deepEqual([...block.matchAll(/- name: (\S+)/g)].map((m) => m[1]), ordered.map((tier) => tier.spec));
  assert.deepEqual([...block.matchAll(/agent_id: (\S+)/g)].map((m) => m[1]), ordered.map((tier) => `agent_${tier.key}`));
  assert.equal(block.match(/default: true/g).length, 1);
  assert.ok(block.includes(`label: ${JSON.stringify(ordered[0].label)}`));
  assert.ok(ordered.every((tier) => !block.includes(tier.model)), 'the internal model never reaches librechat.yaml');
});

test('writes an empty list while no tier agent exists yet', () => {
  assert.ok(specsBlock(tiers, { tiers: [] }).includes('  list: []'));
});

const YAML = `version: 1.3.17\n${BEGIN}\nmodelSpecs:\n  list: []\n${END}\nbalance:\n  enabled: false\n`;

test('replaces only the marked region of librechat.yaml, and does the same again unchanged', () => {
  const once = applyToYaml(YAML, specsBlock(tiers, resolved));
  const twice = applyToYaml(once, specsBlock(tiers, resolved));

  assert.ok(once.startsWith('version: 1.3.17\n') && once.endsWith('balance:\n  enabled: false\n'));
  assert.ok(once.includes(`agent_id: agent_${ordered[1].key}`));
  assert.equal(twice, once);
});

test('refuses a librechat.yaml without the region, or with it twice', () => {
  assert.throws(() => applyToYaml('version: 1\n', 'x'), /exactly one BEGIN\/END/);
  assert.throws(() => applyToYaml(`${YAML}${YAML}`, 'x'), /exactly one BEGIN\/END/);
});

test('sets iqraa.json tiers from the table (spec and plans only) and keeps its other keys', () => {
  const next = applyToIqraa({ staffRoles: ['ADMIN'], prices }, tiers, resolved);

  const last = ordered.at(-1);
  assert.deepEqual(next.tiers.at(-1), { spec: last.spec, plans: last.plans });
  assert.deepEqual(next.staffRoles, ['ADMIN']);
  assert.ok(!JSON.stringify(next.tiers).includes('model'));
});

test('writes no tier to iqraa.json until every tier has an agent, so the fork can start and be released into', () => {
  assert.deepEqual(applyToIqraa({ prices }, tiers, { tiers: [] }).tiers, []);
  assert.deepEqual(applyToIqraa({ prices }, tiers, { tiers: [resolved.tiers[0]] }).tiers, []);
});

test('changes a tier model only with a reason and a price, and returns the audit row', () => {
  const { doc, row } = setModel(tiers, {
    key: 'advanced',
    provider: 'openrouter',
    model: 'mock-model',
    note: 'cheaper provider',
    actor: 'ibrahim',
    prices,
    now: new Date('2026-10-31T09:00:00Z'),
  });

  assert.deepEqual(doc.tiers.find((t) => t.key === 'advanced').provider, 'openrouter');
  assert.deepEqual(row, {
    ts: '2026-10-31T09:00:00.000Z',
    tier: 'advanced',
    actor: 'ibrahim',
    from: { provider: 'MockLLM', model: 'mock-model' },
    to: { provider: 'openrouter', model: 'mock-model' },
    note: 'cheaper provider',
  });
  assert.throws(() => setModel(tiers, { key: 'advanced', provider: 'p', model: 'mock-model', note: ' ', prices }), /--note is required/);
  assert.throws(() => setModel(tiers, { key: 'advanced', provider: 'p', model: 'unpriced', note: 'x', prices }), /has no price/);
  assert.throws(() => setModel(tiers, { key: 'ghost', provider: 'p', model: 'mock-model', note: 'x', prices }), /no tier ghost/);
});
