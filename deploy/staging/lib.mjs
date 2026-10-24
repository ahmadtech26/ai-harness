// Shared helpers for the staging drivers (scenarios.mjs, drills.mjs): HTTP, chat, accounts,
// ledger and model-log evidence, check/verdict helpers, proxy checks.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

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

export async function api(route, { token, method = 'GET', body } = {}) {
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

/** Starts a turn and follows its event stream to the final event. */
export async function chat({ token, agentId, text, conversationId = null, parentMessageId, manualSkills, timeoutMs = 90_000 }) {
  const messageId = crypto.randomUUID();
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
    isTemporary: false,
    isRegenerate: false,
    isContinued: false,
    ...(manualSkills ? { manualSkills } : {}),
  };
  const startedAt = Date.now();
  const start = await api('/api/agents/chat/agents', { token, method: 'POST', body });
  const result = { startStatus: start.status, startedAt, elapsedMs: null, final: null, error: null, text: null, conversationId: null, responseId: null };
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

// ---------------------------------------------------------------- accounts

export function newAccount(label) {
  const suffix = `${RUN}${crypto.randomBytes(2).toString('hex')}`;
  return {
    name: `Staging ${label}`,
    username: `stg_${label.replace(/[^a-z0-9]/gi, '')}_${suffix}`,
    email: `stg.${label.replace(/[^a-z0-9]/gi, '')}.${suffix}@example.test`,
    password: crypto.randomBytes(12).toString('base64url') + 'aA1!',
  };
}

export async function login(account) {
  const res = await api('/api/auth/login', { method: 'POST', body: { email: account.email, password: account.password } });
  if (!res.json?.token) throw new Error(`login ${account.username}: ${res.status} ${res.text.slice(0, 200)}`);
  const user = res.json.user;
  return { ...account, token: res.json.token, id: String(user.id ?? user._id), role: user.role };
}

export async function registerAndLogin(account) {
  const reg = await api('/api/auth/register', { method: 'POST', body: { ...account, confirm_password: account.password } });
  if (reg.status >= 300) throw new Error(`register ${account.username}: ${reg.status} ${reg.text.slice(0, 200)}`);
  return login(account);
}

export async function grant(staff, userId, amountAic, ref) {
  const res = await api(`/api/iqraa/admin/wallets/${userId}/grant`, { token: staff.token, method: 'POST', body: { amount: amountAic, ref } });
  if (res.status >= 300) throw new Error(`grant ${ref}: ${res.status} ${res.text.slice(0, 200)}`);
  return res.json;
}

export async function customer(staff, label, { plan = true, credits = 0 } = {}) {
  let account = await registerAndLogin(newAccount(label));
  if (plan) {
    const member = await api(`/api/admin/roles/${PLAN_ROLE}/members`, { token: staff.token, method: 'POST', body: { userId: account.id } });
    if (member.status >= 300) throw new Error(`plan membership ${label}: ${member.status} ${member.text.slice(0, 200)}`);
    account = await login(account);
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
  return verdict({
    shellServed: check(res.status === 200 && html.includes('<script'), `GET / ${res.status}`),
    librechatNoncePolicy: check(Boolean(nonce) && html.includes(`nonce="${nonce}"`), `nonce in header and shell: ${Boolean(nonce) && html.includes(`nonce="${nonce}"`)}`),
    proxyNarrowPolicy: check(csp.includes("img-src 'self' data: blob:;") && csp.includes("connect-src 'self';") && csp.includes("frame-ancestors 'none'"), csp),
  });
}
