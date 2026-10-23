// Release Iqraa specialists and plan roles into a LibreChat instance (idempotent).
//
//   LIBRECHAT_URL=http://localhost:3080 IQRAA_STAFF_EMAIL=... IQRAA_STAFF_PASSWORD=... \
//     node content/release.mjs content/specialists/aqel.json
//
// Optional IQRAA_PROVIDER / IQRAA_MODEL override the model per environment (e.g. a mock on staging).
// Credentials come only from the environment. Exits non-zero on any failed step.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = process.env.LIBRECHAT_URL ?? 'http://localhost:3080';
// LibreChat's agents router rejects non-browser user agents.
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';
const here = path.dirname(fileURLToPath(import.meta.url));

function fail(message) {
  console.error(`release failed: ${message}`);
  process.exit(1);
}

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

async function login() {
  const { IQRAA_STAFF_EMAIL: email, IQRAA_STAFF_PASSWORD: password } = process.env;
  if (!email || !password) fail('IQRAA_STAFF_EMAIL and IQRAA_STAFF_PASSWORD are required');
  const res = await api('/api/auth/login', { method: 'POST', body: { email, password } });
  if (!res.json?.token) fail(`login returned ${res.status}`);
  if (res.json.user?.role !== 'ADMIN') fail('the release account must be staff (ADMIN)');
  return res.json.token;
}

async function ensureRoles(token) {
  const roles = JSON.parse(fs.readFileSync(path.join(here, 'roles.json'), 'utf8'));
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

async function releaseSpecialist(token, file) {
  const spec = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (spec.model_parameters?.streamUsage !== true) {
    fail(`${file}: model_parameters.streamUsage must be true (usage is undercounted otherwise)`);
  }
  if (!Array.isArray(spec.skills) || spec.skills.length === 0) {
    fail(`${file}: list the skills explicitly (an empty list gives the specialist every skill)`);
  }
  const provider = process.env.IQRAA_PROVIDER ?? spec.provider;
  const model = process.env.IQRAA_MODEL ?? spec.model;
  if (!provider || !model) {
    fail(`${file}: no model chosen — set provider/model in the file or IQRAA_PROVIDER/IQRAA_MODEL`);
  }
  const instructions = fs.readFileSync(path.resolve(path.dirname(file), spec.instructionsFile), 'utf8');
  const body = {
    name: spec.name,
    description: spec.description,
    instructions,
    provider,
    model,
    model_parameters: spec.model_parameters,
    tools: spec.tools,
    skills: await skillIds(token, spec.skills),
    skills_enabled: spec.skills_enabled,
    skill_authoring_enabled: spec.skill_authoring_enabled,
    recursion_limit: spec.recursion_limit,
    category: spec.category,
  };

  const list = await api('/api/agents?requiredPermission=2', { token });
  const existing = (list.json?.data ?? []).find((agent) => agent.name === spec.name);
  const saved = existing
    ? await api(`/api/agents/${existing.id}`, { token, method: 'PATCH', body })
    : await api('/api/agents', { token, method: 'POST', body });
  if (saved.status >= 300 || !saved.json?._id) fail(`agent ${spec.name}: ${saved.status} ${saved.text.slice(0, 200)}`);

  const share = await api(`/api/permissions/agent/${saved.json._id}`, {
    token,
    method: 'PUT',
    body: {
      updated: spec.shareWithRoles.map((role) => ({ type: 'role', id: role, accessRoleId: 'agent_viewer' })),
      removed: [],
      public: false,
    },
  });
  if (share.status >= 300) fail(`sharing ${spec.name}: ${share.status} ${share.text.slice(0, 200)}`);
  console.log(`specialist ${spec.name}: ${existing ? 'updated' : 'created'} (${saved.json.id}), shared with ${spec.shareWithRoles.join(', ')}`);
  return saved.json.id;
}

const files = process.argv.slice(2);
if (files.length === 0) fail('pass one or more specialist JSON files');
const token = await login();
await ensureRoles(token);
for (const file of files) {
  await releaseSpecialist(token, path.resolve(file));
}
