// Phase 1 acceptance driver: scenarios 1, 4, 8, 9, 10, 11 (.hq/docs/audits/librechat-platform/I I.4)
// against the staging stack in this directory.
//
//   docker compose up -d --build && node scenarios.mjs
//
// Every run creates fresh accounts with throwaway passwords that exist only in memory and in the
// staging database; the staff account is promoted through mongosh. Evidence is judged from three
// sources: HTTP responses, the mock model's request log (out/llm-requests.jsonl — every provider call)
// and the ledger collections in MongoDB. Writes out/scenarios-report.json; exits 1 on any failure.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const COMPOSE = path.join(HERE, 'compose.yaml');
const OUT = path.join(HERE, 'out');
const LLM_LOG = path.join(OUT, 'llm-requests.jsonl');
const BASE = process.env.LIBRECHAT_URL ?? 'http://127.0.0.1:3080';
const RUN = crypto.randomBytes(3).toString('hex');
const PRICES = JSON.parse(fs.readFileSync(path.join(HERE, 'iqraa.json'), 'utf8')).prices;
const MODEL = 'mock-model';
const PLAN_ROLE = 'PLAN_PRO';
// LibreChat's agents router rejects non-browser user agents ("Illegal request").
const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';

const MARKERS = {
  pinned: 'منهج عمل لتحليل الوقائع',
  listed: 'STAGING_LISTED_MARKER',
  unlisted: 'STAGING_UNLISTED_MARKER',
};
const AUTHORING_TOOLS = ['create_file', 'edit_file', 'execute_code', 'bash_tool'];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const nonce = (label) => `${label}-${RUN}-${crypto.randomBytes(3).toString('hex')}`;

// ---------------------------------------------------------------- HTTP

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

async function waitForHealth(timeoutMs = 240_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BASE}/health`);
      if (res.ok) return;
    } catch {
      // not up yet
    }
    await sleep(2000);
  }
  throw new Error(`LibreChat did not become healthy at ${BASE}`);
}

/** Starts a turn and follows its event stream to the final event. */
async function chat({ token, agentId, text, conversationId = null, parentMessageId, manualSkills, timeoutMs = 90_000 }) {
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

function newAccount(label) {
  const suffix = `${RUN}${crypto.randomBytes(2).toString('hex')}`;
  return {
    name: `Staging ${label}`,
    username: `stg_${label.replace(/[^a-z0-9]/gi, '')}_${suffix}`,
    email: `stg.${label.replace(/[^a-z0-9]/gi, '')}.${suffix}@example.test`,
    password: crypto.randomBytes(12).toString('base64url') + 'aA1!',
  };
}

async function login(account) {
  const res = await api('/api/auth/login', { method: 'POST', body: { email: account.email, password: account.password } });
  if (!res.json?.token) throw new Error(`login ${account.username}: ${res.status} ${res.text.slice(0, 200)}`);
  const user = res.json.user;
  return { ...account, token: res.json.token, id: String(user.id ?? user._id), role: user.role };
}

async function registerAndLogin(account) {
  const reg = await api('/api/auth/register', { method: 'POST', body: { ...account, confirm_password: account.password } });
  if (reg.status >= 300) throw new Error(`register ${account.username}: ${reg.status} ${reg.text.slice(0, 200)}`);
  return login(account);
}

async function grant(staff, userId, amountAic, ref) {
  const res = await api(`/api/iqraa/admin/wallets/${userId}/grant`, { token: staff.token, method: 'POST', body: { amount: amountAic, ref } });
  if (res.status >= 300) throw new Error(`grant ${ref}: ${res.status} ${res.text.slice(0, 200)}`);
  return res.json;
}

async function customer(staff, label, { plan = true, credits = 0 } = {}) {
  let account = await registerAndLogin(newAccount(label));
  if (plan) {
    const member = await api(`/api/admin/roles/${PLAN_ROLE}/members`, { token: staff.token, method: 'POST', body: { userId: account.id } });
    if (member.status >= 300) throw new Error(`plan membership ${label}: ${member.status} ${member.text.slice(0, 200)}`);
    account = await login(account);
  }
  if (credits > 0) await grant(staff, account.id, credits, `staging-${RUN}-${label}`);
  return account;
}

const wallet = async (account) => (await api('/api/iqraa/wallet', { token: account.token })).json;

// ---------------------------------------------------------------- evidence: Mongo and the model log

function mongoQuery(query) {
  const encoded = Buffer.from(JSON.stringify(query), 'utf8').toString('base64');
  const out = execFileSync(
    'docker',
    ['compose', '-f', COMPOSE, 'exec', '-T', '-e', `IQRAA_QUERY=${encoded}`, 'mongo', 'mongosh', 'LibreChat', '--quiet', '--file', '/scripts/query.js'],
    { encoding: 'utf8' },
  );
  return JSON.parse(out.trim().split('\n').filter(Boolean).pop());
}

function reconcile() {
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

// Ledger rows are attributed by user (fresh accounts per scenario) and by order, never by comparing
// this machine's clock with timestamps written inside the containers.
const reservationsOf = (userId) =>
  mongoQuery({ op: 'find', collection: 'iqraa_reservations', filter: { userId }, sort: { createdAt: 1, _id: 1 } });
const usageEventsOf = (userId) =>
  mongoQuery({ op: 'find', collection: 'iqraa_usage_events', filter: { userId }, sort: { createdAt: 1, _id: 1 } });

function textOf(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) return content.map((p) => (typeof p === 'string' ? p : (p?.text ?? ''))).join('');
  return '';
}

function llmLog() {
  if (!fs.existsSync(LLM_LOG)) return [];
  return fs
    .readFileSync(LLM_LOG, 'utf8')
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

const TAG = new RegExp(`[A-Za-z0-9-]+-${RUN}-[0-9a-f]{6}`, 'g');

/**
 * The turn a request belongs to: the tag in its most recent tagged user message. LibreChat appends
 * skill bodies and step-budget notices as user messages after the user's own text, so the last user
 * message is not necessarily the user's.
 */
function turnTagOf(entry) {
  for (const message of [...(entry.messages ?? [])].reverse()) {
    if (message.role !== 'user') continue;
    const tags = textOf(message.content).match(TAG);
    if (tags) return tags[tags.length - 1];
  }
  return null;
}

/** Provider calls for a turn (title requests excluded; they are reported separately). */
const callsFor = (tag) => llmLog().filter((e) => e.decision && !e.title && turnTagOf(e) === tag);
const titleCallsFor = (tag) => llmLog().filter((e) => e.title && JSON.stringify(e.messages ?? []).includes(tag));
const flakyFor = (tag) => llmLog().filter((e) => e.event === 'flaky-500' && tag.includes(e.nonce));
const carries = (call, marker) => JSON.stringify(call.messages ?? []).includes(marker);
const costOf = (usage) => {
  const price = PRICES[MODEL];
  return Math.ceil(usage.prompt_tokens * price.input + usage.completion_tokens * price.output);
};

// ---------------------------------------------------------------- scenarios

const check = (ok, detail) => ({ ok: Boolean(ok), detail });
const verdict = (checks) => ({ pass: Object.values(checks).every((c) => c.ok), checks });
const countBy = (values) => values.reduce((acc, v) => ({ ...acc, [v]: (acc[v] ?? 0) + 1 }), {});
const answered = (t) => /MOCK_OK|TOOL_RESULT_SEEN/.test(t.result.text ?? '');
// A refused turn must reach the provider not at all: conversation-title requests count too.
const providerCalls = (t) => t.calls.length + t.titles.length;

/**
 * Titles run after the turn (`titleTiming: final`), so they can land after the turn's stream ends.
 * Waits until one appears (`expectOne`) or the window closes, and returns the title calls seen.
 */
async function titlesAfter(tag, { expectOne, windowMs }) {
  const deadline = Date.now() + windowMs;
  while (Date.now() < deadline) {
    if (expectOne && titleCallsFor(tag).length > 0) break;
    await sleep(500);
  }
  return titleCallsFor(tag);
}

async function turn(account, agentId, label, text, extra = {}) {
  const tag = nonce(label);
  // The tag directly follows the text, so "FLAKY_ONCE:" + tag forms the mock's flaky nonce.
  const result = await chat({ token: account.token, agentId, text: `${text}${text.endsWith(':') ? '' : ' '}${tag}`, ...extra });
  await sleep(1500);
  return { tag, result, calls: callsFor(tag), titles: titleCallsFor(tag) };
}

function summarizeTurn(t) {
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

async function scenario1(ctx) {
  const { c1, agentId } = ctx;
  const a = await turn(c1, agentId, 's1-plain', 'S1 probe');
  a.titles = await titlesAfter(a.tag, { expectOne: true, windowMs: 15_000 });
  const b = await turn(c1, agentId, 's1-listed', 'CALL_TOOL:skill:{"skillName":"staging-listed"}', {
    conversationId: a.result.conversationId,
    parentMessageId: a.result.responseId,
  });
  const c = await turn(c1, agentId, 's1-unlisted-model', 'CALL_TOOL:skill:{"skillName":"staging-unlisted"}');
  const d = await turn(c1, agentId, 's1-unlisted-manual', 'manual unlisted', { manualSkills: ['staging-unlisted'] });
  const e = await turn(c1, agentId, 's1-listed-manual', 'manual listed', { manualSkills: ['staging-listed'] });
  const turns = [a, b, c, d, e];
  const all = turns.flatMap((t) => t.calls);
  ctx.customerCalls.push(...all);
  const leaks = (t) => t.calls.some((call) => carries(call, MARKERS.unlisted));
  return {
    ...verdict({
      pinnedEveryCall: check(all.length > 0 && all.every((call) => carries(call, MARKERS.pinned)), `${all.filter((call) => carries(call, MARKERS.pinned)).length}/${all.length} provider calls carry S1`),
      pinnedAcrossTurns: check(a.calls.length >= 1 && b.calls.length >= 1 && b.result.conversationId === a.result.conversationId, `turn 1 calls=${a.calls.length}, turn 2 calls=${b.calls.length}, same conversation=${b.result.conversationId === a.result.conversationId}`),
      listedLoadsByModel: check(b.calls.length === 2 && carries(b.calls[1], MARKERS.listed), `calls=${b.calls.length}; reply: ${b.result.text?.slice(0, 120)}`),
      unlistedRefusedToModel: check(c.calls.length >= 1 && !leaks(c), `S3 reached model: ${leaks(c)}; reply: ${c.result.text?.slice(0, 160)}`),
      unlistedRefusedToManualInvocation: check(d.calls.length >= 1 && !leaks(d), `S3 reached model: ${leaks(d)}`),
      listedManualInvocationControl: check(e.calls.some((call) => carries(call, MARKERS.listed)), 'positive control: manually invoked S2 reaches the model'),
      answeredTurnStillTitled: check(answered(a) && a.titles.length === 1, `positive control for the title gate: ${a.titles.length} title call(s) for an answered first turn`),
    }),
    turns: turns.map(summarizeTurn),
  };
}

async function scenario4(ctx) {
  const { c1, staff, skillIds } = ctx;
  const probes = [];
  for (const name of ['jordanian-case-analysis', 'staging-listed', 'staging-unlisted']) {
    const read = await api(`/api/skills/${skillIds[name]}`, { token: c1.token });
    const files = await api(`/api/skills/${skillIds[name]}/files`, { token: c1.token });
    const leaked = Object.values(MARKERS).some((m) => read.text.includes(m) || files.text.includes(m));
    probes.push({ name, read: read.status, code: read.json?.code, files: files.status, leaked });
  }
  const staffRead = await api(`/api/skills/${skillIds['staging-listed']}`, { token: staff.token });
  const create = await api('/api/skills', { token: c1.token, method: 'POST', body: { name: `customer-skill-${RUN}`, description: 'x', body: 'y' } });
  const agent = await api(`/api/agents/${ctx.agentId}`, { token: staff.token });
  const advertised = [...new Set(ctx.customerCalls.flatMap((call) => call.tools ?? []))];
  return verdict({
    skillReadDenied: check(probes.every((p) => p.read === 403 && p.code === 'IQRAA_FORBIDDEN' && p.files === 403 && !p.leaked), JSON.stringify(probes)),
    staffReadControl: check(staffRead.status === 200 && staffRead.text.includes(MARKERS.listed), `staff GET skill: ${staffRead.status}`),
    skillCreateDenied: check(create.status === 403, `customer POST /api/skills: ${create.status}`),
    authoringDisabledOnSpecialist: check(agent.status === 200 && agent.json?.skill_authoring_enabled !== true, `status ${agent.status}, skill_authoring_enabled=${agent.json?.skill_authoring_enabled}`),
    noAuthoringToolOffered: check(advertised.length > 0 && !advertised.some((t) => AUTHORING_TOOLS.includes(t)), `tools offered to the model: ${advertised.join(', ')}`),
  });
}

async function scenario9(ctx) {
  const { c2, agentId } = ctx;
  const withUsage = await turn(c2, agentId, 's9-usage', 'usage probe');
  const withTool = await turn(c2, agentId, 's9-tool', 'CALL_TOOL:search_law:{"query":"العدول عن العقد"}');
  const noUsage = await turn(c2, agentId, 's9-nousage', 'NO_USAGE probe');
  // c2 is fresh and its turns run one after another, so its ledger rows split by each turn's call count.
  const [n1, n2] = [withUsage.calls.length, withTool.calls.length];
  const events = usageEventsOf(c2.id);
  const reservations = reservationsOf(c2.id);
  const e1 = events.slice(0, n1);
  const e2 = events.slice(n1, n1 + n2);
  const e3 = events.slice(n1 + n2);
  const r3 = reservations.slice(n1 + n2);
  const reported = (calls, events) => {
    const expected = calls.map((call) => `${call.usage.prompt_tokens}/${call.usage.completion_tokens}/${costOf(call.usage)}`).sort();
    const actual = events.map((e) => `${e.inputTokens}/${e.outputTokens}/${e.amount}`).sort();
    return { ok: JSON.stringify(expected) === JSON.stringify(actual), expected, actual };
  };
  const m1 = reported(withUsage.calls, e1);
  const m2 = reported(withTool.calls, e2);
  ctx.reservationSample = reservations[0]?.amount;
  const totalCalls = n1 + n2 + noUsage.calls.length;
  return {
    ...verdict({
      oneEventPerCall: check(n1 === 1 && n2 === 2 && events.length === totalCalls && reservations.length === totalCalls, `${events.length} usage events and ${reservations.length} reservations for ${totalCalls} provider calls (plain 1, tool turn ${n2}, no-usage ${noUsage.calls.length})`),
      providerUsageSettled: check(m1.ok && m2.ok && [...e1, ...e2].every((e) => e.estimated === false), `expected ${JSON.stringify([...m1.expected, ...m2.expected])} got ${JSON.stringify([...m1.actual, ...m2.actual])}`),
      legalSearchToolRan: check(withTool.calls.length === 2 && String(withTool.calls[0].decision?.name ?? '').startsWith('search_law') && /TOOL_RESULT_SEEN/.test(withTool.result.text ?? ''), withTool.result.text?.slice(0, 200)),
      missingUsageSettledAtEstimate: check(noUsage.calls.length === 1 && noUsage.calls[0].sentUsage === false && e3.length === 1 && e3[0].estimated === true && r3.length === 1 && e3[0].amount === r3[0].amount, `events=${e3.length} estimated=${e3[0]?.estimated} amount=${e3[0]?.amount} reserved=${r3[0]?.amount}`),
    }),
    turns: [withUsage, withTool, noUsage].map(summarizeTurn),
  };
}

async function scenario10(ctx) {
  const { staff, agentId } = ctx;
  const c = await customer(staff, 's10', { credits: 5 });
  const flaky = await turn(c, agentId, 's10-flaky', 'FLAKY_ONCE:');
  const failures = flakyFor(flaky.tag);
  const reservations = reservationsOf(c.id);
  const events = usageEventsOf(c.id);

  const ref = `staging-${RUN}-s10-dup`;
  const before = await wallet(c);
  await grant(staff, c.id, 1, ref);
  await grant(staff, c.id, 1, ref);
  const after = await wallet(c);

  const indexes = Object.fromEntries(
    ['iqraa_reservations', 'iqraa_usage_events', 'iqraa_postings'].map((collection) => [
      collection,
      mongoQuery({ op: 'indexes', collection }).filter((i) => i.unique).map((i) => Object.keys(i.key).join('+')),
    ]),
  );
  return {
    ...verdict({
      providerFailedOnceThenSucceeded: check(failures.length === 1 && flaky.calls.length === 1 && answered(flaky), `500s=${failures.length}, successful calls=${flaky.calls.length}, reply=${flaky.result.text?.slice(0, 120)}`),
      oneReservationOneSettlement: check(reservations.length === 1 && reservations[0].status === 'settled' && events.length === 1, `reservations=${JSON.stringify(reservations.map((r) => r.status))}, usage events=${events.length}`),
      duplicateGrantCreditedOnce: check(Math.abs(after.available - before.available - 1) < 1e-9, `available ${before.available} -> ${after.available} after the same grant ref twice`),
      idempotencyIndexes: check(indexes.iqraa_reservations.includes('key') && indexes.iqraa_usage_events.includes('key') && indexes.iqraa_postings.includes('txId+account'), JSON.stringify(indexes)),
    }),
    turns: [summarizeTurn(flaky)],
  };
}

async function scenario8(ctx) {
  const { staff, agentId } = ctx;
  const sample = ctx.reservationSample;
  if (!sample) return { pass: false, checks: { sample: check(false, 'no reservation sample from scenario 9') } };
  const limit = Math.floor(sample * 1.5);
  const c = await customer(staff, 's8', { credits: limit / 1_000_000 });
  const tags = Array.from({ length: 6 }, (_, i) => nonce(`s8-${i}`));
  const results = await Promise.all(tags.map((tag) => chat({ token: c.token, agentId, text: `parallel probe ${tag}` })));
  // Titles follow their turn; give a refused turn's would-be title time to show before counting.
  await sleep(6000);
  const turns = tags.map((tag, i) => ({ tag, result: results[i], calls: callsFor(tag), titles: titleCallsFor(tag) }));
  const succeeded = turns.filter(answered);
  const denied = turns.filter((t) => /IQRAA_INSUFFICIENT_CREDITS/.test(t.result.text ?? ''));
  const unresolved = turns.filter((t) => !answered(t) && !denied.includes(t));
  const reservations = reservationsOf(c.id);
  const settled = reservations.filter((r) => r.status === 'settled');
  // Peak of simultaneously held credit from reservation lifetimes (a close sorts before an open on ties).
  const edges = reservations.flatMap((r) => [
    { t: new Date(r.createdAt).getTime(), d: r.amount, o: 1 },
    ...(r.status === 'held' ? [] : [{ t: new Date(r.updatedAt).getTime(), d: -r.amount, o: 0 }]),
  ]);
  edges.sort((x, y) => x.t - y.t || x.o - y.o);
  let running = 0;
  let peak = 0;
  for (const edge of edges) {
    running += edge.d;
    peak = Math.max(peak, running);
  }
  const final = await wallet(c);
  const spent = settled.reduce((acc, r) => acc + r.actualAmount, 0);
  const answeredCalls = succeeded.reduce((acc, t) => acc + t.calls.length, 0);
  return {
    ...verdict({
      everyTurnAnsweredOrRefused: check(unresolved.length === 0, `unresolved turns: ${JSON.stringify(unresolved.map((t) => `${t.result.text?.slice(0, 80)} after ${t.result.elapsedMs} ms`))}`),
      boundExercised: check(succeeded.length >= 1 && denied.length >= 1, `${succeeded.length} answered, ${denied.length} refused for credits of ${turns.length} parallel chats; wallet ${limit} µAIC, one reservation ≈ ${sample} µAIC`),
      peakHoldWithinWallet: check(peak <= limit, `peak held ${peak} µAIC, wallet ${limit} µAIC`),
      noOverspend: check(final.available >= 0 && final.held === 0 && spent <= limit, `final available ${final.available} AIC, held ${final.held} AIC, spent ${spent} µAIC`),
      refusedTurnsNeverReachedProvider: check(denied.every((t) => providerCalls(t) === 0), `provider calls (titles included) on refused turns: [${denied.map(providerCalls).join(',')}]`),
      oneSettlementPerCall: check(settled.length === answeredCalls, `settled ${settled.length}, provider calls on answered turns ${answeredCalls}`),
    }),
    refusalText: denied[0]?.result.text?.slice(0, 200) ?? null,
  };
}

async function scenario11(ctx) {
  const { staff, agentId } = ctx;
  const broke = await customer(staff, 's11-nocredit', { credits: 0 });
  const noPlan = await customer(staff, 's11-noplan', { plan: false, credits: 5 });
  const noCredit = await turn(broke, agentId, 's11-nocredit', 'no credit probe');
  const noPlanTurn = await turn(noPlan, agentId, 's11-noplan', 'no plan probe');
  noCredit.titles = await titlesAfter(noCredit.tag, { expectOne: false, windowMs: 6_000 });
  noPlanTurn.titles = titleCallsFor(noPlanTurn.tag);
  const remote = [
    await api('/api/agents/v1/models', { token: broke.token }),
    await api('/api/agents/v1/chat/completions', { token: broke.token, method: 'POST', body: { model: agentId, messages: [{ role: 'user', content: 'x' }] } }),
  ].map((r) => ({ status: r.status, code: r.json?.code }));
  const creation = {
    agent: (await api('/api/agents', { token: broke.token, method: 'POST', body: { name: `customer agent ${RUN}`, provider: 'MockLLM', model: MODEL } })).status,
    prompt: (await api('/api/prompts', { token: broke.token, method: 'POST', body: { prompt: { prompt: 'x', type: 'text' }, group: { name: `customer prompt ${RUN}`, category: '' } } })).status,
    mcp: (await api('/api/mcp/servers', { token: broke.token, method: 'POST', body: { config: { type: 'streamable-http', url: 'http://example.test/mcp', title: 'x' } } })).status,
  };

  // Message rate limit (MESSAGE_USER_MAX=30 per minute): a burst from one more account without credits.
  const burster = await customer(staff, 's11-burst', { credits: 0 });
  // LibreChat denies a limited message with HTTP 200 and a `message_limit` error event, not 429.
  const burstTags = [];
  const outcomes = [];
  for (let i = 0; i < 36; i += 1) {
    const tag = nonce(`s11-burst-${i}`);
    burstTags.push(tag);
    const start = await api('/api/agents/chat/agents', {
      token: burster.token,
      method: 'POST',
      body: {
        text: `burst ${tag}`,
        sender: 'User',
        isCreatedByUser: true,
        parentMessageId: '00000000-0000-0000-0000-000000000000',
        conversationId: null,
        messageId: crypto.randomUUID(),
        endpoint: 'agents',
        agent_id: agentId,
      },
    });
    outcomes.push(start.text.includes('message_limit') ? 'limited' : `${start.status}${start.json?.streamId ? ' started' : ''}`);
  }
  await sleep(3000);
  const burstCalls = burstTags.reduce((acc, tag) => acc + callsFor(tag).length + titleCallsFor(tag).length, 0);
  const started = outcomes.filter((o) => o.endsWith('started')).length;
  return {
    ...verdict({
      noCreditRefusedBeforeProvider: check(providerCalls(noCredit) === 0 && !answered(noCredit), `provider calls ${noCredit.calls.length}, title calls ${noCredit.titles.length}; reply: ${noCredit.result.text?.slice(0, 200)}`),
      noPlanRefusedBeforeProvider: check(providerCalls(noPlanTurn) === 0 && !answered(noPlanTurn), `start ${noPlanTurn.result.startStatus}; provider calls ${noPlanTurn.calls.length}, title calls ${noPlanTurn.titles.length}; reply: ${noPlanTurn.result.text?.slice(0, 200)}`),
      remoteAgentsApiDenied: check(remote.every((r) => r.status === 403 && r.code === 'IQRAA_FORBIDDEN'), JSON.stringify(remote)),
      noCustomerCreation: check(Object.values(creation).every((status) => status === 403), JSON.stringify(creation)),
      messageRateLimited: check(outcomes.includes('limited') && started <= 30 && burstCalls === 0, `outcomes ${JSON.stringify(countBy(outcomes))} (limit 30/min); provider calls ${burstCalls}`),
    }),
  };
}

/** Plan item 9: the shell carries LibreChat's nonce policy and the proxy's narrow policy. */
async function proxyChecks() {
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

// ---------------------------------------------------------------- setup and run

async function setup() {
  await waitForHealth();
  const staffAccount = newAccount('staff');
  await registerAndLogin(staffAccount);
  mongoQuery({ op: 'promote', email: staffAccount.email });
  const staff = await login(staffAccount);
  if (staff.role !== 'ADMIN') throw new Error(`staff account is ${staff.role}, expected ADMIN`);

  const release = spawnSync(process.execPath, [path.join(ROOT, 'content', 'release.mjs'), path.join(ROOT, 'content', 'specialists', 'aqel.json')], {
    encoding: 'utf8',
    env: { ...process.env, LIBRECHAT_URL: BASE, IQRAA_STAFF_EMAIL: staff.email, IQRAA_STAFF_PASSWORD: staff.password, IQRAA_PROVIDER: 'MockLLM', IQRAA_MODEL: MODEL },
  });
  if (release.status !== 0) throw new Error(`release failed: ${release.stderr || release.stdout}`);
  const agentId = release.stdout.match(/\((agent_[^)]+)\)/)?.[1];
  if (!agentId) throw new Error(`no agent id in release output: ${release.stdout}`);

  const skills = await api('/api/skills', { token: staff.token });
  const list = Array.isArray(skills.json) ? skills.json : (skills.json?.skills ?? skills.json?.data ?? []);
  const skillIds = Object.fromEntries(list.map((s) => [s.name, String(s._id ?? s.id)]));
  for (const name of ['jordanian-case-analysis', 'staging-listed', 'staging-unlisted']) {
    if (!skillIds[name]) throw new Error(`deployment skill ${name} not found (have: ${Object.keys(skillIds).join(', ')})`);
  }
  // Staging only: list S2 next to the pinned S1 so scenario 1 can load a skill on demand.
  const patch = await api(`/api/agents/${agentId}`, {
    token: staff.token,
    method: 'PATCH',
    body: { skills: [skillIds['jordanian-case-analysis'], skillIds['staging-listed']] },
  });
  if (patch.status >= 300) throw new Error(`listing S2 on the specialist: ${patch.status} ${patch.text.slice(0, 200)}`);

  return {
    staff,
    agentId,
    skillIds,
    release: release.stdout.trim().split('\n'),
    c1: await customer(staff, 's1', { credits: 5 }),
    c2: await customer(staff, 's9', { credits: 5 }),
    customerCalls: [],
  };
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const ctx = await setup();
  const report = { run: RUN, base: BASE, startedAt: new Date().toISOString(), agentId: ctx.agentId, release: ctx.release, scenarios: {} };
  // 9 runs before 8 (8 sizes its wallet from a scenario 9 reservation); 11 last (its burst trips the rate limit).
  const order = [
    ['1', scenario1],
    ['4', scenario4],
    ['9', scenario9],
    ['10', scenario10],
    ['8', scenario8],
    ['11', scenario11],
  ];
  for (const [id, run] of order) {
    try {
      report.scenarios[id] = await run(ctx);
    } catch (error) {
      report.scenarios[id] = { pass: false, error: String(error.stack ?? error) };
    }
    const s = report.scenarios[id];
    console.log(`scenario ${id.padEnd(2)} ${s.pass ? 'PASS' : 'FAIL'}`);
    for (const [name, c] of Object.entries(s.checks ?? {})) console.log(`   ${c.ok ? 'ok  ' : 'FAIL'} ${name}: ${c.detail}`);
    if (s.error) console.log(`   error: ${s.error}`);
  }
  report.proxy = await proxyChecks();
  console.log(`proxy      ${report.proxy.pass ? 'PASS' : 'FAIL'}`);
  for (const [name, c] of Object.entries(report.proxy.checks)) console.log(`   ${c.ok ? 'ok  ' : 'FAIL'} ${name}: ${c.detail}`);
  report.reconciliation = reconcile();
  console.log(`reconciliation ${report.reconciliation.ok ? 'ok' : 'FAIL'} ${JSON.stringify(report.reconciliation)}`);
  report.finishedAt = new Date().toISOString();
  report.pass = Object.values(report.scenarios).every((s) => s.pass) && report.proxy.pass && report.reconciliation.ok;
  fs.writeFileSync(path.join(OUT, 'scenarios-report.json'), JSON.stringify(report, null, 2));
  console.log(report.pass ? 'ALL PASS' : 'FAILURES — see out/scenarios-report.json');
  process.exit(report.pass ? 0 : 1);
}

await main();
