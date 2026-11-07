// Tests for tiers.mjs:  node --test content/tiers.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import { BEGIN, END, applyToIqraa, applyToYaml, setModel, specsBlock, usageProblems, validateTiers } from './tiers.mjs';

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

// A librechat.yaml with two custom endpoints; `mock` is the MockLLM entry's lines after its name.
const endpoints = (mock, name = "'MockLLM'") =>
  [
    'version: 1.3.18',
    'endpoints:',
    '  agents:',
    '    titleTiming: final',
    '  custom:',
    "    - name: 'Other'",
    "      baseURL: 'http://other/v1'",
    '      addParams:',
    '        streamUsage: true',
    `    - name: ${name}`,
    "      baseURL: 'http://mock-llm:8080/v1'",
    ...mock,
    "      modelDisplayLabel: 'Mock LLM'",
    'fileConfig:',
    '  serverFileSizeLimit: 5',
    '',
  ].join('\n');
const ASKS = ['      addParams:', '        # the provider reports usage only when asked', '        streamUsage: true'];
const NOT_ASKED = /provider MockLLM: its endpoint must set addParams\.streamUsage: true/;

test('accepts a tier endpoint that asks for usage, in block or flow style, quoted or not, with CRLF line ends', () => {
  assert.deepEqual(usageProblems(endpoints(ASKS), ['MockLLM']), []);
  assert.deepEqual(usageProblems(endpoints(['      addParams: { streamUsage: true }']), ['MockLLM']), []);
  assert.deepEqual(usageProblems(endpoints(ASKS, 'MockLLM'), ['MockLLM']), []);
  assert.deepEqual(usageProblems(endpoints(ASKS, '"MockLLM"').replace(/\n/g, '\r\n'), ['MockLLM', 'MockLLM']), []);
});

test('refuses a tier endpoint that does not ask for usage, though another endpoint does', () => {
  const cases = [
    [],
    ['      addParams:', '        streamUsage: false'],
    ['      addParams:', '        temperature: 0.2'],
    ['      headers:', '        streamUsage: true'],
    ['      addParams: { streamUsage: false }'],
  ];
  for (const mock of cases) {
    const problems = usageProblems(endpoints(mock), ['MockLLM', 'Other']);
    assert.equal(problems.length, 1, mock.join(' / '));
    assert.match(problems[0], NOT_ASKED);
  }
});

test('refuses a tier provider with no custom endpoint of its name, and leaves built-in endpoints alone', () => {
  assert.deepEqual(usageProblems(endpoints(ASKS), ['Ghost']), ['provider Ghost: librechat.yaml has no custom endpoint of that name']);
  assert.deepEqual(usageProblems(endpoints(ASKS), ['openAI', 'anthropic', 'azureOpenAI', 'google', 'bedrock']), []);
  assert.deepEqual(usageProblems('version: 1.3.18\n', ['MockLLM']), ['provider MockLLM: librechat.yaml has no custom endpoint of that name']);
});

test('apply refuses a librechat.yaml whose tier endpoint does not ask for usage, and writes neither file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tiers-apply-'));
  try {
    const yamlFile = path.join(dir, 'librechat.yaml');
    const iqraaFile = path.join(dir, 'iqraa.json');
    const resolvedFile = path.join(dir, 'resolved.json');
    const yaml = endpoints([]).replace('fileConfig:', `${BEGIN}\nmodelSpecs:\n  list: []\n${END}\nfileConfig:`);
    fs.writeFileSync(yamlFile, yaml);
    fs.writeFileSync(iqraaFile, '{}\n');
    fs.writeFileSync(resolvedFile, JSON.stringify(resolved));
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => key !== 'IQRAA_PROVIDER'));
    const apply = (file) =>
      spawnSync(process.execPath, [path.join(here, 'tiers.mjs'), 'apply', '--resolved', resolvedFile, '--yaml', file, '--iqraa', iqraaFile], { encoding: 'utf8', env });

    const refused = apply(yamlFile);

    assert.equal(refused.status, 1);
    assert.match(refused.stderr, NOT_ASKED);
    assert.equal(fs.readFileSync(yamlFile, 'utf8'), yaml);
    assert.equal(fs.readFileSync(iqraaFile, 'utf8'), '{}\n');

    fs.writeFileSync(yamlFile, endpoints(ASKS).replace('fileConfig:', `${BEGIN}\nmodelSpecs:\n  list: []\n${END}\nfileConfig:`));
    const accepted = apply(yamlFile);
    assert.equal(accepted.status, 0, accepted.stderr);
    assert.ok(fs.readFileSync(yamlFile, 'utf8').includes(`agent_id: agent_${ordered[0].key}`));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
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
