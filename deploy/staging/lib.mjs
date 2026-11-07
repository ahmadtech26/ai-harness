// Shared helpers for the staging drivers (scenarios.mjs, drills.mjs, ui/run-rtl-check.mjs): HTTP, chat,
// passwordless accounts (codes from the sink, app codes, the staff bootstrap runner), ledger and model-log
// evidence, check/verdict helpers, proxy checks.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { nextAppStep, totp } from './totp.cjs';

export const HERE = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(HERE, '..', '..');
export const COMPOSE = path.join(HERE, 'compose.yaml');
export const OUT = path.join(HERE, 'out');
export const LLM_LOG = path.join(OUT, 'llm-requests.jsonl');
export const BASE = process.env.LIBRECHAT_URL ?? 'http://127.0.0.1:3080';
export const RUN = crypto.randomBytes(3).toString('hex');
export const PRICES = JSON.parse(fs.readFileSync(path.join(HERE, 'iqraa.json'), 'utf8')).prices;
export const MODEL = 'mock-model';
export const PLAN_ROLE = 'PLAN_PRO';
// LibreChat's agents router rejects non-browser user agents ("Illegal request").
export const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';


export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
export const nonce = (label) => `${label}-${RUN}-${crypto.randomBytes(3).toString('hex')}`;

// ---------------------------------------------------------------- HTTP

export async function api(route, { token, method = 'GET', body, cookie } = {}) {
  const res = await fetch(BASE + route, {
    method,
    headers: {
      'User-Agent': UA,
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(cookie ? { Cookie: cookie } : {}),
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
  return { status: res.status, json, text, cookies: res.headers.getSetCookie() };
}

/** The value of cookie `name` among a response's Set-Cookie headers (null when absent). */
export const cookieValue = (setCookies, name) =>
  (setCookies ?? []).map((c) => c.split(';')[0]).find((c) => c.startsWith(`${name}=`))?.slice(name.length + 1) ?? null;

export async function waitForHealth(timeoutMs = 240_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      // /readyz, not /health: /health answers as soon as the server listens, before MCP and agent
      // startup finish, and a chat sent in that window can end without a model call.
      const res = await fetch(`${BASE}/readyz`);
      if (res.ok) return;
    } catch {
      // not up yet
    }
    await sleep(2000);
  }
  throw new Error(`LibreChat did not become healthy at ${BASE}`);
}

const specNames = new Map();

/**
 * The model spec (tier) whose private agent is `agentId`, from the startup config the client reads. A customer's
 * chat turn must name one (the fork's tier gate); staff chats may too, harmlessly. Null for an agent that is no tier.
 */
export async function specFor(token, agentId) {
  if (!specNames.has(agentId)) {
    const config = await api('/api/config', { token });
    const spec = (config.json?.modelSpecs?.list ?? []).find((entry) => entry.preset?.agent_id === agentId);
    specNames.set(agentId, spec?.name ?? null);
  }
  return specNames.get(agentId);
}

/** Starts a turn and follows its event stream to the final event. */
export async function chat({ token, agentId, text, conversationId = null, parentMessageId, manualSkills, timeoutMs = 90_000, spec }) {
  const messageId = crypto.randomUUID();
  const specName = spec ?? (await specFor(token, agentId));
  const body = {
    text,
    sender: 'User',
    clientTimestamp: new Date().toISOString(),
    isCreatedByUser: true,
    parentMessageId: parentMessageId ?? '00000000-0000-0000-0000-000000000000',
    conversationId,
    messageId,
    error: false,
    endpoint: 'agents',
    agent_id: agentId,
    ...(specName ? { spec: specName } : {}),
    isTemporary: false,
    isRegenerate: false,
    isContinued: false,
    ...(manualSkills ? { manualSkills } : {}),
  };
  const startedAt = Date.now();
  const start = await api('/api/agents/chat/agents', { token, method: 'POST', body });
  // `stream` keeps every SSE block, so a check can read all the customer's stream, not only the final event.
  const result = { startStatus: start.status, startedAt, elapsedMs: null, final: null, error: null, text: null, conversationId: null, responseId: null, stream: [] };
  const streamId = start.json?.streamId ?? start.json?.conversationId;
  if (start.status >= 300 || !streamId) {
    result.error = start.json ?? start.text.slice(0, 300);
    result.text = typeof result.error === 'string' ? result.error : JSON.stringify(result.error);
    return result;
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}/api/agents/chat/stream/${encodeURIComponent(streamId)}`, {
      headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream', 'User-Agent': UA },
      signal: controller.signal,
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        result.stream.push(block);
        const dataLines = block.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim());
        if (!dataLines.length) continue;
        let data;
        try {
          data = JSON.parse(dataLines.join('\n'));
        } catch {
          data = dataLines.join('\n');
        }
        const eventLine = block.split('\n').find((l) => l.startsWith('event:'));
        if (eventLine?.slice(6).trim() === 'error' || data?.error) result.error = data;
        if (data?.final) {
          result.final = data;
          controller.abort();
        }
      }
    }
  } catch (error) {
    if (error.name !== 'AbortError') result.error = String(error);
  } finally {
    clearTimeout(timer);
  }
  result.elapsedMs = Date.now() - startedAt;
  const message = result.final?.responseMessage;
  result.conversationId = result.final?.conversation?.conversationId ?? start.json?.conversationId ?? null;
  result.responseId = message?.messageId ?? null;
  result.text =
    (typeof message?.text === 'string' && message.text) ||
    (message?.content ?? [])
      .map((p) => p?.text ?? (typeof p?.[p?.type] === 'string' ? p[p.type] : (p?.[p?.type]?.text ?? '')))
      .join('') ||
    (typeof result.error === 'string' ? result.error : JSON.stringify(result.error ?? ''));
  return result;
}

// ---------------------------------------------------------------- accounts (passwordless: codes from the sink)

export const AUTH = '/api/iqraa/auth';
export const PLACEHOLDER_DOMAIN = '@phone.iqraa.invalid';

/** A Jordanian mobile number (+96279 and 7 digits) no account holds yet: staging data outlives runs. */
export function newPhone() {
  for (let draw = 0; draw < 5; draw += 1) {
    const phone = `+96279${crypto.randomInt(0, 10_000_000).toString().padStart(7, '0')}`;
    if (mongoQuery({ op: 'find', collection: 'iqraa_identities', filter: { phone }, limit: 1 }).length === 0) return phone;
  }
  throw new Error('no free staging phone number in 5 draws');
}

export const newAccount = (label) => ({ label, name: `Staging ${label}`, phone: newPhone() });

/** The newest iqraa_auth_sink row (to, channel, purpose, code, createdAt) for `to` and `purpose`, or null. */
export const newestSinkRow = (to, purpose) =>
  mongoQuery({ op: 'find', collection: 'iqraa_auth_sink', filter: { to, purpose }, sort: { createdAt: -1, _id: -1 }, limit: 1 })[0] ?? null;

/**
 * Runs `send` (a code request) and returns its result with the sink row it produced for `to`. The row is told
 * apart from older ones by its _id, never by clocks: a sign-in answer does not wait for delivery. Assumes mongosh
 * serialises an ObjectId `_id` as its hex string in `JSON.stringify` (bson's `toJSON`), so `!==` compares strings;
 * Chunk 8's first `SCENARIOS=auth` run is its first observation.
 */
export async function withSinkCode(to, purpose, send, timeoutMs = 20_000) {
  const before = newestSinkRow(to, purpose)?._id ?? null;
  const sent = await send();
  if (sent?.status !== undefined && sent.status !== 200) throw new Error(`${purpose} code request for ${to}: ${sent.status} ${sent.text.slice(0, 200)}`);
  let row = null;
  const arrived = await waitUntil(() => {
    row = newestSinkRow(to, purpose);
    return row !== null && row._id !== before;
  }, timeoutMs);
  if (!arrived) throw new Error(`no ${purpose} code reached the sink for ${to} within ${timeoutMs} ms`);
  return { sent, row, code: row.code };
}

/** The session fields of a 200 `{ token, user }` answer (the shape LoginController answers), else throws. */
export function sessionOf(res, what) {
  if (res.status !== 200 || !res.json?.token) throw new Error(`${what}: ${res.status} ${res.text.slice(0, 200)}`);
  const { user } = res.json;
  return { token: res.json.token, id: String(user.id ?? user._id), role: user.role, email: user.email, refreshToken: cookieValue(res.cookies, 'refreshToken') };
}

export const requestCode = (identifier, purpose) => api(`${AUTH}/request-code`, { method: 'POST', body: { identifier, purpose } });
export const verifyCode = (identifier, method, code) => api(`${AUTH}/verify-code`, { method: 'POST', body: { identifier, method, code } });

/** Sign-up by phone (REQ-AUTH-001): a WhatsApp code from the sink, then the account with the account's name. */
export async function signUp(account) {
  const { code } = await withSinkCode(account.phone, 'signup', () => requestCode(account.phone, 'signup'));
  const res = await api(`${AUTH}/signup`, { method: 'POST', body: { phone: account.phone, code, name: account.name } });
  return { ...account, ...sessionOf(res, `sign-up ${account.label}`) };
}

/** Sign-in by WhatsApp code (REQ-AUTH-002). Every call is a new code request, counted in iqraa.json auth.limits. */
export async function login(account) {
  const { code } = await withSinkCode(account.phone, 'signin', () => requestCode(account.phone, 'signin'));
  return { ...account, ...sessionOf(await verifyCode(account.phone, 'code', code), `sign-in ${account.label}`) };
}

/** The base32 secret of an otpauth:// URL. */
export function secretOf(otpauthUrl) {
  const secret = new URL(otpauthUrl).searchParams.get('secret');
  if (!secret) throw new Error('no secret in the otpauth URL');
  return secret;
}

/** A fresh app code for `account.app` ({ secret, backupCodes, lastStep }); waits for a new 30 s step when needed. */
export async function appCode(account) {
  const { step, waitMs } = nextAppStep(account.app.lastStep);
  if (waitMs > 0) await sleep(waitMs);
  account.app.lastStep = step;
  return totp(account.app.secret, { step });
}

/** Sign-in with phone plus an app code, or plus `backupCode` (REQ-AUTH-004/005). */
export async function loginWithApp(account, { backupCode } = {}) {
  const res = backupCode
    ? await verifyCode(account.phone, 'backup', backupCode)
    : await verifyCode(account.phone, 'app', await appCode(account));
  return { ...account, ...sessionOf(res, `app sign-in ${account.label}`) };
}

/**
 * Sets up the authenticator app through LibreChat's own routes (spec «Spec review» item 5): enable, then confirm
 * one app code. LibreChat's confirm records no step (only the fork's own sign-ins and the runner's promote do), so
 * the wait for a new step before the next app code is harmless, not required.
 */
export async function enableApp(account) {
  const enabled = await api('/api/auth/2fa/enable', { token: account.token, method: 'POST', body: {} });
  if (enabled.status !== 200 || !enabled.json?.otpauthUrl) throw new Error(`2fa enable ${account.label}: ${enabled.status} ${enabled.text.slice(0, 200)}`);
  const app = { secret: secretOf(enabled.json.otpauthUrl), backupCodes: enabled.json.backupCodes, lastStep: -1, otpauthUrl: enabled.json.otpauthUrl };
  const confirmed = await api('/api/auth/2fa/confirm', { token: account.token, method: 'POST', body: { token: await appCode({ app }) } });
  if (confirmed.status !== 200) throw new Error(`2fa confirm ${account.label}: ${confirmed.status} ${confirmed.text.slice(0, 200)}`);
  return { ...account, app };
}

// The runner reads its secrets inside the LibreChat container (the entrypoint's exports do not reach an exec
// session), MONGO_URI among them since O-34 took it out of the environment; only the command and its arguments cross
// the host command line.
export const RUNNER =
  'export IQRAA_AUTH_SECRET=$(cat /secrets/iqraa_auth) CREDS_KEY=$(cat /secrets/creds_key) CREDS_IV=$(cat /secrets/creds_iv)' +
  ' MONGO_URI=$(cat /secrets/mongo_uri) && exec node /app/config/iqraa-bootstrap-staff.js "$@"';
const lastJsonLine = (text) => {
  for (const line of String(text ?? '').trim().split('\n').reverse()) {
    try {
      const value = JSON.parse(line);
      if (value && typeof value === 'object') return value;
    } catch {
      // config/connect.js prints colored progress lines first
    }
  }
  return null;
};

/** Runs one staff bootstrap command (plan contract: request | enrol | promote); returns its JSON line. */
export function bootstrapRunner(args) {
  const run = spawnSync('docker', ['compose', '-f', COMPOSE, 'exec', '-T', 'librechat', 'sh', '-c', RUNNER, 'iqraa-bootstrap-staff', ...args], { encoding: 'utf8' });
  if (run.status !== 0) {
    const failure = lastJsonLine(run.stderr);
    throw new Error(`bootstrap ${args[0]}: exit ${run.status ?? run.error?.message}: ${failure ? `${failure.error} ${failure.message}` : String(run.stderr ?? '').slice(-300)}`);
  }
  const out = lastJsonLine(run.stdout);
  if (!out) throw new Error(`bootstrap ${args[0]}: no JSON line on stdout`);
  return out;
}

/**
 * A staff account made the way an operator makes one (Decision 13): `request` (a sign-up code to the sink),
 * `enrol` (the otpauth URL and backup codes), `promote` with an app code (the guarded role assignment), then a
 * sign-in with phone plus app code. The returned account carries its app for later sign-ins.
 */
export async function staffAccount(label) {
  const account = newAccount(label);
  const { code } = await withSinkCode(account.phone, 'signup', async () => bootstrapRunner(['request', '--phone', account.phone]));
  const enrolled = bootstrapRunner(['enrol', '--phone', account.phone, '--name', account.name, '--code', code]);
  account.app = { secret: secretOf(enrolled.otpauthUrl), backupCodes: enrolled.backupCodes, lastStep: -1 };
  const promoted = bootstrapRunner(['promote', '--phone', account.phone, '--app-code', await appCode(account)]);
  const staff = await loginWithApp(account);
  if (promoted.role !== 'ADMIN' || staff.role !== 'ADMIN' || String(promoted.userId) !== staff.id) {
    throw new Error(`staff ${label}: promoted ${JSON.stringify(promoted)}, signed in as ${staff.id} (${staff.role})`);
  }
  return staff;
}

export async function grant(staff, userId, amountAic, ref) {
  const res = await api(`/api/iqraa/admin/wallets/${userId}/grant`, { token: staff.token, method: 'POST', body: { amount: amountAic, ref } });
  if (res.status >= 300) throw new Error(`grant ${ref}: ${res.status} ${res.text.slice(0, 200)}`);
  return res.json;
}

export async function customer(staff, label, { plan = true, credits = 0, role = PLAN_ROLE } = {}) {
  let account = await signUp(newAccount(label));
  if (plan) {
    const member = await api(`/api/admin/roles/${role}/members`, { token: staff.token, method: 'POST', body: { userId: account.id } });
    if (member.status >= 300) throw new Error(`plan membership ${label}: ${member.status} ${member.text.slice(0, 200)}`);
    account = await login(account); // a new code request: counted in iqraa.json auth.limits
  }
  if (credits > 0) await grant(staff, account.id, credits, `staging-${RUN}-${label}`);
  return account;
}

export const wallet = async (account) => (await api('/api/iqraa/wallet', { token: account.token })).json;

// ---------------------------------------------------------------- evidence: Mongo and the model log

export function mongoQuery(query) {
  const encoded = Buffer.from(JSON.stringify(query), 'utf8').toString('base64');
  const out = execFileSync(
    'docker',
    ['compose', '-f', COMPOSE, 'exec', '-T', '-e', `IQRAA_QUERY=${encoded}`, 'mongo', 'mongosh', 'LibreChat', '--quiet', '--file', '/scripts/query.js'],
    { encoding: 'utf8' },
  );
  return JSON.parse(out.trim().split('\n').filter(Boolean).pop());
}

export function reconcile() {
  try {
    const out = execFileSync(
      'docker',
      ['compose', '-f', COMPOSE, 'exec', '-T', 'mongo', 'mongosh', 'LibreChat', '--quiet', '--file', '/scripts/reconcile.js'],
      { encoding: 'utf8' },
    );
    return JSON.parse(out.trim().split('\n').filter(Boolean).pop());
  } catch (error) {
    const out = String(error.stdout ?? '').trim().split('\n').filter(Boolean).pop();
    return out ? JSON.parse(out) : { ok: false, problems: [String(error.message)] };
  }
}

/** Runs `docker compose <args>` against the staging stack. */
export function compose(args) {
  return execFileSync('docker', ['compose', '-f', COMPOSE, ...args], { encoding: 'utf8' });
}

export function legalSearchHealthy() {
  try {
    execFileSync(
      'docker',
      ['compose', '-f', COMPOSE, 'exec', '-T', 'mock-llm', 'node', '-e', "fetch('http://legal-search:8000/health').then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"],
      { stdio: 'ignore' },
    );
    return true;
  } catch {
    return false;
  }
}

const MCP_CALLS = path.join(HERE, 'scripts', 'mcp-calls.py');

/**
 * MCP tool calls as `user` (X-Iqraa-User), made from inside the legal-search container, which is not
 * published to the host; the script reads the shared secret there. Returns each call's tool text, in order.
 */
export function mcpCalls(user, calls) {
  const plan = Buffer.from(JSON.stringify({ user, calls }), 'utf8').toString('base64');
  const out = execFileSync('docker', ['compose', '-f', COMPOSE, 'exec', '-T', 'legal-search', 'python3', '-I', '-', plan], {
    encoding: 'utf8',
    input: fs.readFileSync(MCP_CALLS, 'utf8'),
    maxBuffer: 64 * 1024 * 1024,
  });
  return JSON.parse(out.trim().split('\n').filter(Boolean).pop()).results;
}

/**
 * legal-search's sweep alert lines for `userId` (spec C.5): one JSON object per line on the container's
 * stderr, so both streams of `compose logs` are read. Callers order them by `log_id`, never by time.
 */
export function legalSearchAlerts(userId) {
  const logs = spawnSync('docker', ['compose', '-f', COMPOSE, 'logs', '--no-log-prefix', '--since', '2h', 'legal-search'], {
    encoding: 'utf8',
    maxBuffer: 512 * 1024 * 1024,
  });
  return `${logs.stdout ?? ''}\n${logs.stderr ?? ''}`
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('{') && line.includes('"sweep_'))
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return null;
      }
    })
    .filter((entry) => entry?.user_id === userId);
}

/** Open sweep flags by level, from the fork's staff `flags` route (the reconciliation line, spec C.5). */
export async function sweepFlagCounts(staff) {
  const res = await api('/api/iqraa/admin/library/flags', { token: staff.token });
  if (res.status !== 200 || !Array.isArray(res.json?.flags)) throw new Error(`staff flags route: ${res.status} ${res.text.slice(0, 200)}`);
  const count = (level) => res.json.flags.filter((flag) => flag.level === level).length;
  return { suspected: count('suspected'), proven: count('proven') };
}

// Ledger rows are attributed by user (fresh accounts per scenario) and by order, never by comparing
// this machine's clock with timestamps written inside the containers.
export const reservationsOf = (userId) =>
  mongoQuery({ op: 'find', collection: 'iqraa_reservations', filter: { userId }, sort: { createdAt: 1, _id: 1 } });
export const usageEventsOf = (userId) =>
  mongoQuery({ op: 'find', collection: 'iqraa_usage_events', filter: { userId }, sort: { createdAt: 1, _id: 1 } });

export function textOf(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) return content.map((p) => (typeof p === 'string' ? p : (p?.text ?? ''))).join('');
  return '';
}

export function llmLog() {
  if (!fs.existsSync(LLM_LOG)) return [];
  return fs
    .readFileSync(LLM_LOG, 'utf8')
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

export const TAG = new RegExp(`[A-Za-z0-9-]+-${RUN}-[0-9a-f]{6}`, 'g');

/**
 * The turn a request belongs to: the tag in its most recent tagged user message. LibreChat appends
 * skill bodies and step-budget notices as user messages after the user's own text, so the last user
 * message is not necessarily the user's.
 */
export function turnTagOf(entry) {
  for (const message of [...(entry.messages ?? [])].reverse()) {
    if (message.role !== 'user') continue;
    const tags = textOf(message.content).match(TAG);
    if (tags) return tags[tags.length - 1];
  }
  return null;
}

/** Provider calls for a turn (title requests excluded; they are reported separately). */
export const callsFor = (tag) => llmLog().filter((e) => e.decision && !e.title && !e.summary && turnTagOf(e) === tag);
/** Summarisation requests whose content includes any of the given turn tags. */
export const summaryCallsFor = (tags) => llmLog().filter((e) => e.summary && tags.some((tag) => JSON.stringify(e.messages ?? []).includes(tag)));
export const titleCallsFor = (tag) => llmLog().filter((e) => e.title && JSON.stringify(e.messages ?? []).includes(tag));
export const flakyFor = (tag) => llmLog().filter((e) => e.event === 'flaky-500' && tag.includes(e.nonce));
export const carries = (call, marker) => JSON.stringify(call.messages ?? []).includes(marker);
export const costOf = (usage) => {
  const price = PRICES[MODEL];
  return Math.ceil(usage.prompt_tokens * price.input + usage.completion_tokens * price.output);
};

// ---------------------------------------------------------------- scenarios

export const check = (ok, detail) => ({ ok: Boolean(ok), detail });
export const verdict = (checks) => ({ pass: Object.values(checks).every((c) => c.ok), checks });
export const countBy = (values) => values.reduce((acc, v) => ({ ...acc, [v]: (acc[v] ?? 0) + 1 }), {});
export const answered = (t) => /MOCK_OK|TOOL_RESULT_SEEN/.test(t.result.text ?? '');
// A refused turn must reach the provider not at all: conversation-title requests count too.
export const providerCalls = (t) => t.calls.length + t.titles.length;

/**
 * Titles run after the turn (`titleTiming: final`), so they can land after the turn's stream ends.
 * Waits until one appears (`expectOne`) or the window closes, and returns the title calls seen.
 */
export async function titlesAfter(tag, { expectOne, windowMs }) {
  const deadline = Date.now() + windowMs;
  while (Date.now() < deadline) {
    if (expectOne && titleCallsFor(tag).length > 0) break;
    await sleep(500);
  }
  return titleCallsFor(tag);
}

export async function turn(account, agentId, label, text, extra = {}) {
  const tag = nonce(label);
  // The tag directly follows the text, so "FLAKY_ONCE:" + tag forms the mock's flaky nonce.
  const result = await chat({ token: account.token, agentId, text: `${text}${text.endsWith(':') ? '' : ' '}${tag}`, ...extra });
  await sleep(1500);
  return { tag, result, calls: callsFor(tag), titles: titleCallsFor(tag) };
}

export function summarizeTurn(t) {
  return {
    tag: t.tag,
    startStatus: t.result.startStatus,
    reply: t.result.text?.slice(0, 200) ?? null,
    // Diagnostics only (two clocks): turn duration and the wait before the first provider call.
    elapsedMs: t.result.elapsedMs,
    firstCallAfterMs: t.calls[0] ? Date.parse(t.calls[0].ts) - t.result.startedAt : null,
    calls: t.calls.map((c) => ({ decision: c.decision?.kind, tool: c.decision?.name, sentUsage: c.sentUsage, usage: c.usage, tools: c.tools })),
    titleCalls: t.titles.length,
  };
}

/** Polls `predicate` (sync or async) every 250 ms until it is truthy or `timeoutMs` passes. */
export async function waitUntil(predicate, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return true;
    await sleep(250);
  }
  return false;
}

/**
 * Starts a turn and presses Stop (POST /api/agents/chat/abort) once `stopAfter` SSE blocks carrying
 * `marker` have arrived, then follows the stream to its end.
 */
export async function chatAndStop({ token, agentId, text, marker, stopAfter, timeoutMs = 90_000 }) {
  const specName = await specFor(token, agentId);
  const body = {
    text,
    sender: 'User',
    clientTimestamp: new Date().toISOString(),
    isCreatedByUser: true,
    parentMessageId: '00000000-0000-0000-0000-000000000000',
    conversationId: null,
    messageId: crypto.randomUUID(),
    error: false,
    endpoint: 'agents',
    agent_id: agentId,
    ...(specName ? { spec: specName } : {}),
    isTemporary: false,
    isRegenerate: false,
    isContinued: false,
  };
  const start = await api('/api/agents/chat/agents', { token, method: 'POST', body });
  const streamId = start.json?.streamId ?? start.json?.conversationId;
  const result = { startStatus: start.status, piecesBeforeStop: 0, abortStatus: null, stopPressedAt: null, ended: false, error: null };
  if (!streamId) return result;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}/api/agents/chat/stream/${encodeURIComponent(streamId)}`, {
      headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream', 'User-Agent': UA },
      signal: controller.signal,
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        if (result.abortStatus === null && block.includes(marker)) {
          result.piecesBeforeStop += 1;
          if (result.piecesBeforeStop >= stopAfter) {
            result.stopPressedAt = Date.now();
            const abort = await api('/api/agents/chat/abort', { token, method: 'POST', body: { streamId } });
            result.abortStatus = abort.status;
          }
        }
        const dataLines = block.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim());
        let data = null;
        try {
          data = dataLines.length ? JSON.parse(dataLines.join('\n')) : null;
        } catch {
          data = null;
        }
        if (data?.final) {
          result.ended = true;
          result.final = data;
          controller.abort();
        }
      }
    }
  } catch (error) {
    if (error.name !== 'AbortError') result.error = String(error);
  } finally {
    clearTimeout(timer);
  }
  return result;
}


export async function proxyChecks() {
  const res = await fetch(`${BASE}/`, { headers: { 'User-Agent': UA } });
  const html = await res.text();
  // fetch joins repeated headers with ", ".
  const csp = res.headers.get('content-security-policy') ?? '';
  const nonce = csp.match(/'nonce-([^']+)'/)?.[1];
  const chosen = await fetch(`${BASE}/`, { headers: { 'User-Agent': UA, Cookie: 'lang=en-US' } });
  await chosen.arrayBuffer();
  const defaultCookie = res.headers.getSetCookie().find((c) => c.startsWith('lang=')) ?? '';
  const chosenCookie = chosen.headers.getSetCookie().find((c) => c.startsWith('lang=')) ?? '';
  return verdict({
    arabicByDefault: check(defaultCookie.startsWith('lang=ar;') && chosenCookie === '', `no cookie → "${defaultCookie}"; lang=en-US → "${chosenCookie || 'none'}"`),
    shellServed: check(res.status === 200 && html.includes('<script'), `GET / ${res.status}`),
    librechatNoncePolicy: check(Boolean(nonce) && html.includes(`nonce="${nonce}"`), `nonce in header and shell: ${Boolean(nonce) && html.includes(`nonce="${nonce}"`)}`),
    proxyNarrowPolicy: check(csp.includes("img-src 'self' data: blob:;") && csp.includes("connect-src 'self';") && csp.includes("frame-ancestors 'none'"), csp),
  });
}
