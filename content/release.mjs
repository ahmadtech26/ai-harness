// Release the plan roles and the customer tiers into a LibreChat instance (idempotent).
//
//   LIBRECHAT_URL=http://localhost:3080 IQRAA_STAFF_IDENTIFIER=+9627... IQRAA_STAFF_APP_CODE=<app code> \
//     node content/release.mjs --prices iqraa.json --resolved out/tiers-resolved.json [--tiers content/tiers.json] [--release]
//     (or IQRAA_STAFF_TOKEN=<staff session token>; --dry-run plans and lints without any network call)
//
// A live release needs `--prices` (the target's price book: an unpriced model is refused, because metering would
// refuse every turn) and `--resolved` (the file `tiers.mjs apply` reads: a release without an apply leaves the
// yaml pointing at old agents). Run `node content/tiers.mjs apply --resolved ...` and recreate librechat next.
// Each agent is found by its `category` (`iqraa-tier-<key>`), so a tier keeps its agent when its label changes; an
// agent of a tier that left tiers.json, and the legacy single agent of an earlier release, are unshared from every
// plan role (never deleted). `--release` also demands approved starters: production refuses to start on a draft.
//
// One private agent per tier (`content/tiers.json`): the AQEL specialist with the library tools only, the tier's
// internal model and the four featured starters, shared with the tier's plan roles and unshared from the others.
// The resolved file ({ tiers: [{ key, spec, agentId }] }) feeds `node content/tiers.mjs apply`, which writes the
// matching modelSpecs into librechat.yaml. Optional IQRAA_PROVIDER / IQRAA_MODEL override every tier's model
// (staging runs all tiers on a mock). Credentials come only from the environment. Exits non-zero on any failed step.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { findTierAgent, planTierAgents, retiredAgents } from './tier-agents.mjs';
import { validateTiers } from './tiers.mjs';
import { validateStarters } from './starters.mjs';

const BASE = process.env.LIBRECHAT_URL ?? 'http://localhost:3080';
// LibreChat's agents router rejects non-browser user agents.
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';
const here = path.dirname(fileURLToPath(import.meta.url));

function fail(message) {
  console.error(`release failed: ${message}`);
  process.exit(1);
}

const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8'));
const args = process.argv.slice(2);
const flag = (name) => {
  const at = args.indexOf(name);
  return at === -1 ? undefined : args[at + 1];
};

async function api(route, { token, method = 'GET', body } = {}) {
  const res = await fetch(BASE + route, {
    method,
    headers: {
      'User-Agent': UA,
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = null;
  }
  return { status: res.status, json, text };
}

// No passwords (spec-passwordless-login REQ-AUTH-006): a staff session token from the caller (the staging driver
// holds one), or a staff phone or email plus a current authenticator-app code, accepted once.
async function login() {
  const { IQRAA_STAFF_TOKEN: given, IQRAA_STAFF_IDENTIFIER: identifier, IQRAA_STAFF_APP_CODE: code } = process.env;
  let token = given;
  if (!token) {
    if (!identifier || !code) fail('set IQRAA_STAFF_TOKEN, or IQRAA_STAFF_IDENTIFIER and IQRAA_STAFF_APP_CODE');
    const res = await api('/api/iqraa/auth/verify-code', { method: 'POST', body: { identifier, method: 'app', code } });
    if (!res.json?.token) fail(`sign-in returned ${res.status} ${res.json?.code ?? ''}`);
    token = res.json.token;
  }
  const me = await api('/api/user', { token });
  if (me.status !== 200) fail(`the staff session was refused (${me.status})`);
  if (me.json?.role !== 'ADMIN') fail('the release account must be staff (ADMIN)');
  return token;
}

async function ensureRoles(token, roles) {
  for (const [name, role] of Object.entries(roles)) {
    const existing = await api(`/api/admin/roles/${encodeURIComponent(name)}`, { token });
    const res =
      existing.status === 404
        ? await api('/api/admin/roles', { token, method: 'POST', body: { name, ...role } })
        : await api(`/api/admin/roles/${encodeURIComponent(name)}/permissions`, {
            token,
            method: 'PATCH',
            body: { permissions: role.permissions },
          });
    if (res.status >= 300) fail(`role ${name}: ${res.status} ${res.text.slice(0, 200)}`);
    console.log(`role ${name}: ${existing.status === 404 ? 'created' : 'updated'}`);
  }
}

async function skillIds(token, names) {
  const res = await api('/api/skills', { token });
  const list = Array.isArray(res.json) ? res.json : (res.json?.skills ?? res.json?.data ?? []);
  const byName = new Map(list.map((skill) => [skill.name, skill._id ?? skill.id]));
  return names.map((name) => byName.get(name) ?? fail(`skill ${name} is not deployed on this instance`));
}

async function retire(token, agent, allPlans) {
  const res = await api(`/api/permissions/agent/${agent._id ?? agent.id}`, {
    token,
    method: 'PUT',
    body: { updated: [], removed: allPlans.map((role) => ({ type: 'role', id: role })), public: false },
  });
  if (res.status >= 300) fail(`unsharing ${agent.name}: ${res.status} ${res.text.slice(0, 200)}`);
  console.log(`retired ${agent.name} (${agent.id}): unshared from every plan role`);
}

async function releaseTier(token, planned, allPlans, existingAgents) {
  const { tier, plans, body } = planned;
  const listed = findTierAgent(existingAgents, body);
  // The list omits provider and model; the agent itself (the release account holds EDIT) has them.
  const existing = listed ? { ...listed, ...((await api(`/api/agents/${listed.id}`, { token })).json ?? {}) } : undefined;
  const saved = existing
    ? await api(`/api/agents/${existing.id}`, { token, method: 'PATCH', body: { ...body, skills: await skillIds(token, body.skills) } })
    : await api('/api/agents', { token, method: 'POST', body: { ...body, skills: await skillIds(token, body.skills) } });
  if (saved.status >= 300 || !saved.json?._id) fail(`tier ${tier.key}: ${saved.status} ${saved.text.slice(0, 200)}`);

  // Plans are the ACL: share with the tier's plan roles, and take the agent away from every other plan role.
  const share = await api(`/api/permissions/agent/${saved.json._id}`, {
    token,
    method: 'PUT',
    body: {
      updated: plans.map((role) => ({ type: 'role', id: role, accessRoleId: 'agent_viewer' })),
      removed: allPlans.filter((role) => !plans.includes(role)).map((role) => ({ type: 'role', id: role })),
      public: false,
    },
  });
  if (share.status >= 300) fail(`sharing tier ${tier.key}: ${share.status} ${share.text.slice(0, 200)}`);

  console.log(`tier ${tier.key} ${tier.label}: ${existing ? 'updated' : 'created'} (${saved.json.id}), plans ${plans.join(', ')}`);
  if (existing && (existing.provider !== body.provider || existing.model !== body.model)) {
    console.log(`  model changed: ${existing.provider}/${existing.model} -> ${body.provider}/${body.model}`);
  }
  console.log(`  in instructions: ${planned.pinned.join(', ') || 'none'}; listed skills: ${body.skills.join(', ') || 'none'}`);
  return { key: tier.key, spec: tier.spec, agentId: saved.json.id };
}

const roles = readJson(path.join(here, 'roles.json'));
const tiersDoc = readJson(flag('--tiers') ?? path.join(here, 'tiers.json'));
const startersDoc = readJson(path.join(here, 'starters', 'starters.ar.json'));
const pricesFile = flag('--prices');
const prices = pricesFile ? readJson(pricesFile).prices : undefined;
if (!args.includes('--dry-run') && (!pricesFile || !flag('--resolved'))) {
  fail('a live release needs --prices <the target price book> and --resolved <file> (then run tiers.mjs apply)');
}
const problems = [
  ...validateTiers(tiersDoc, { roles, prices: process.env.IQRAA_MODEL ? undefined : prices }),
  ...(prices && process.env.IQRAA_MODEL && !(process.env.IQRAA_MODEL in prices) ? [`IQRAA_MODEL ${process.env.IQRAA_MODEL} has no price`] : []),
  ...validateStarters(startersDoc, { release: args.includes('--release') }),
];
if (problems.length > 0) fail(problems.join('\n  '));

let planned;
try {
  planned = planTierAgents({ tiersDoc, contentDir: here, startersDoc });
} catch (error) {
  fail(error.message);
}

if (args.includes('--dry-run')) {
  console.log(
    JSON.stringify(
      planned.map(({ tier, plans, body }) => ({
        key: tier.key,
        name: body.name,
        provider: body.provider,
        model: body.model,
        plans,
        tools: body.tools,
        starters: body.conversation_starters.length,
      })),
      null,
      2,
    ),
  );
  process.exit(0);
}

const token = await login();
await ensureRoles(token, roles);
const list = await api('/api/agents?requiredPermission=2', { token });
const existingAgents = list.json?.data ?? [];
const resolved = { tiers: [] };
for (const entry of planned) {
  resolved.tiers.push(await releaseTier(token, entry, Object.keys(roles), existingAgents));
}
const keptIds = new Set(resolved.tiers.map((entry) => entry.agentId));
for (const agent of retiredAgents(existingAgents, keptIds)) await retire(token, agent, Object.keys(roles));
const out = flag('--resolved');
fs.writeFileSync(out, JSON.stringify(resolved, null, 2) + '\n');
console.log(`next: node content/tiers.mjs apply --resolved ${out} --yaml <librechat.yaml> --iqraa <iqraa.json>, then recreate librechat`);
