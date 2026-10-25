// Acceptance driver: scenarios 1, 2, 3, 4, 7, 8, 9, 10, 11, 13 and the library checks (P1/P2 results)
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
import { spawnSync } from 'node:child_process';
import {
  ROOT, OUT, BASE, RUN, PRICES, MODEL, sleep, nonce,
  api, waitForHealth, chat, newAccount, login, registerAndLogin, grant, customer,
  wallet, mongoQuery, reconcile, compose, legalSearchHealthy, reservationsOf, usageEventsOf, callsFor,
  titleCallsFor, flakyFor, carries, costOf, check, verdict, countBy, answered,
  providerCalls, titlesAfter, turn, summarizeTurn, waitUntil, chatAndStop, proxyChecks,
  summaryCallsFor,
} from './lib.mjs';
import { composeSpecialist } from '../../content/compose.mjs';

const MARKERS = {
  pinned: 'منهج عمل لتحليل الوقائع',
  listed: 'STAGING_LISTED_MARKER',
  unlisted: 'STAGING_UNLISTED_MARKER',
};
const AUTHORING_TOOLS = ['create_file', 'edit_file', 'execute_code', 'bash_tool'];
const INSTRUCTIONS_MARKER = 'AQEL LEGAL ENGINE'; // in the specialist's instructions (AQEL prompt)

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

async function scenario2(ctx) {
  const { staff, agentId } = ctx;
  const c = await customer(staff, 's2', { credits: 5 });
  const file = 'skills/legal-document-review/references/review-checklist.md';
  const shipped = fs.readFileSync(path.join(ROOT, 'content', 'skills', 'legal-document-review', 'references', 'review-checklist.md'), 'utf8');
  const firstLine = shipped.replace(/\r\n/g, '\n').split('\n')[0];
  const lastLine = shipped.replace(/\r\n/g, '\n').trim().split('\n').pop();
  const t = await turn(c, agentId, 's2-read', `CALL_TOOL:read_file:{"path":"${file}"}`);
  const toolText = t.calls[1] ? JSON.stringify(t.calls[1].messages.filter((m) => m.role === 'tool')) : '';
  return {
    ...verdict({
      referenceReadFromRelease: check(t.calls.length === 2 && toolText.includes(firstLine) && toolText.includes(lastLine), `calls ${t.calls.length}; first line found ${toolText.includes(firstLine)}; last line found ${toolText.includes(lastLine)}`),
    }),
    turns: [summarizeTurn(t)],
  };
}

/** The library serves the court-fees schedule with its verification label (REQ-SKL-010). */
async function libraryChecks(ctx) {
  const c = await customer(ctx.staff, 'lib', { credits: 5 });
  const t = await turn(c, ctx.agentId, 'lib-fees', 'CALL_TOOL:get_article:{"number":1,"law":"court-fees"}');
  const toolText = t.calls[1] ? JSON.stringify(t.calls[1].messages.filter((m) => m.role === 'tool')) : '';
  return verdict({
    courtFeesArticle1: check(toolText.includes('جدول رسوم المحاكم') && toolText.includes('عن الدعوى أو الدعوى المتقابلة'), `tool result: ${toolText.slice(0, 160)}`),
    unverifiedLabel: check(toolText.includes('لم يُتحقق بعد'), 'result carries the unverified label'),
  });
}

async function scenario3(ctx) {
  const { staff, agentId } = ctx;
  // The agents library summarises only the messages pruned out of the context window, so nothing is
  // summarised until a conversation overflows it. The mock model's window is unknown (large), so give
  // the specialist a small one for this run; the next normal run re-releases it from aqel.json.
  const contextWindow = Number(process.env.S3_MAX_CONTEXT_TOKENS ?? 9000);
  const spec = JSON.parse(fs.readFileSync(path.join(ROOT, 'content', 'specialists', 'aqel.json'), 'utf8'));
  const body = { model_parameters: { ...spec.model_parameters, maxContextTokens: contextWindow } };
  const narrowed = await api(`/api/agents/${agentId}`, { token: staff.token, method: 'PATCH', body });
  if (narrowed.status >= 300) throw new Error(`setting the context window: ${narrowed.status} ${narrowed.text.slice(0, 200)}`);
  const c = await customer(staff, 's3', { credits: 20 });
  const turns = [];
  let conversationId = null;
  let parentMessageId;
  const next = async (label, text) => {
    const t = await turn(c, agentId, label, text, conversationId ? { conversationId, parentMessageId } : {});
    conversationId = t.result.conversationId ?? conversationId;
    parentMessageId = t.result.responseId ?? parentMessageId;
    turns.push(t);
    return t;
  };
  for (let i = 0; i < 6; i += 1) {
    await next(`s3-long-${i}`, `long turn ${i}: ${'العقد شريعة المتعاقدين، ولا يجوز نقضه ولا تعديله إلا باتفاق الطرفين. '.repeat(30)}`);
  }
  const research = await next('s3-tools', 'TOOL_ROUNDS:5 research turn');
  await next('s3-after', 'after summary probe');
  const calls = turns.flatMap((t) => t.calls);
  const summaries = summaryCallsFor(turns.map((t) => t.tag));
  const firstSummaryAt = summaries.length ? Date.parse(summaries[0].ts) : Infinity;
  const afterSummary = calls.filter((call) => Date.parse(call.ts) > firstSummaryAt);
  // The release folds the pinned method into the instructions: it rides in the system prompt, once.
  const inSystemOnce = (call) => {
    const all = JSON.stringify(call.messages ?? []);
    const system = JSON.stringify((call.messages ?? []).filter((m) => m.role === 'system'));
    return system.includes(MARKERS.pinned) && all.split(MARKERS.pinned).length === 2;
  };
  return {
    ...verdict({
      summarySeen: check(summaries.length >= 1, `${summaries.length} summarisation request(s) in this conversation`),
      // A regular agent call carries the specialist's instructions (AQEL); a summarisation call does not
      // (both advertise tools). If LibreChat ever fed the summary prompt into a regular call, the mock
      // would misfile it as a summary — this catches that.
      summaryRequestsAreSummaries: check(summaries.every((e) => !JSON.stringify(e.messages ?? []).includes(INSTRUCTIONS_MARKER)), `summary requests carrying the AQEL instructions: ${summaries.filter((e) => JSON.stringify(e.messages ?? []).includes(INSTRUCTIONS_MARKER)).length}/${summaries.length}`),
      pinnedEveryCall: check(calls.length > 0 && calls.every((call) => carries(call, MARKERS.pinned)), `${calls.filter((call) => carries(call, MARKERS.pinned)).length}/${calls.length} model calls carry S1`),
      pinnedInSystemPromptOnce: check(calls.length > 0 && calls.every(inSystemOnce), `${calls.filter(inSystemOnce).length}/${calls.length} model calls carry S1 once, in the system prompt`),
      pinnedAfterSummary: check(afterSummary.length > 0 && afterSummary.every((call) => carries(call, MARKERS.pinned)), `${afterSummary.length} model calls after the first summary, all carrying S1: ${afterSummary.every((call) => carries(call, MARKERS.pinned))}`),
      toolRoundTurnCompleted: check(research.calls.length >= 6 && /TOOL_RESULT_SEEN/.test(research.result.text ?? ''), `${research.calls.length} model calls in the tool-round turn; reply ${research.result.text?.slice(0, 60)}`),
      pinnedThroughToolRounds: check(research.calls.length > 0 && research.calls.every((call) => carries(call, MARKERS.pinned)), `${research.calls.filter((call) => carries(call, MARKERS.pinned)).length}/${research.calls.length} tool-round calls carry S1`),
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
  // The release folds the pinned method into the specialist's instructions: customers must not read them.
  const instructionReads = [];
  for (const route of [`/api/agents/${ctx.agentId}`, `/api/agents/${ctx.agentId}/expanded`, `/api/agents/${ctx.agentId}/versions`, '/api/agents?requiredPermission=1']) {
    const res = await api(route, { token: c1.token });
    instructionReads.push({ route, status: res.status, leaked: res.text.includes(MARKERS.pinned) || res.text.includes(INSTRUCTIONS_MARKER) });
  }
  const editOnly = instructionReads.filter((p) => /\/(expanded|versions)$/.test(p.route));
  // The full record (EDIT) — the view route never returns instructions or skill_authoring_enabled.
  const agent = await api(`/api/agents/${ctx.agentId}/expanded`, { token: staff.token });
  const advertised = [...new Set(ctx.customerCalls.flatMap((call) => call.tools ?? []))];
  return verdict({
    skillReadDenied: check(probes.every((p) => p.read === 403 && p.code === 'IQRAA_FORBIDDEN' && p.files === 403 && !p.leaked), JSON.stringify(probes)),
    staffReadControl: check(staffRead.status === 200 && staffRead.text.includes(MARKERS.listed), `staff GET skill: ${staffRead.status}`),
    skillCreateDenied: check(create.status === 403, `customer POST /api/skills: ${create.status}`),
    instructionsHiddenFromCustomers: check(instructionReads.every((p) => !p.leaked) && editOnly.every((p) => p.status === 403), JSON.stringify(instructionReads)),
    staffInstructionsControl: check(agent.status === 200 && agent.text.includes(MARKERS.pinned) && agent.text.includes(INSTRUCTIONS_MARKER), `positive control: staff GET expanded ${agent.status}; method and AQEL markers in the instructions`),
    authoringDisabledOnSpecialist: check(agent.status === 200 && agent.json?.skill_authoring_enabled === false, `status ${agent.status}, skill_authoring_enabled=${agent.json?.skill_authoring_enabled}`),
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

async function scenario13(ctx) {
  const { staff, agentId } = ctx;
  const c = await customer(staff, 's13', { credits: 5 });
  const tag = nonce('s13-stop');
  const stopped = await chatAndStop({ token: c.token, agentId, text: `SLOW_STREAM:250 stop probe ${tag}`, marker: 'STREAMED_PIECE', stopAfter: 3 });
  // The 5 s window runs from the moment Stop was pressed, not from when the stream closed.
  const remainingMs = stopped.stopPressedAt ? Math.max(0, stopped.stopPressedAt + 5_000 - Date.now()) : 0;
  const settledInTime = await waitUntil(() => {
    const rows = reservationsOf(c.id);
    return rows.length > 0 && rows.every((r) => r.status !== 'held');
  }, remainingMs);
  const clearedAfterMs = stopped.stopPressedAt ? Date.now() - stopped.stopPressedAt : null;
  await sleep(1500);
  const calls = callsFor(tag);
  const reservations = reservationsOf(c.id);
  const events = usageEventsOf(c.id);
  const hold = reservations[0]?.amount ?? 0;
  // The mock logs the request's max_tokens; without it the prompt-only bound cannot be computed.
  const maxTokens = calls[0]?.maxTokens ?? null;
  const promptOnly = maxTokens === null ? null : hold - maxTokens * PRICES[MODEL].output;
  const charged = reservations[0]?.actualAmount ?? null;
  return {
    ...verdict({
      runStopped: check(stopped.abortStatus === 200 && stopped.piecesBeforeStop >= 3 && stopped.ended === true, `abort ${stopped.abortStatus} after ${stopped.piecesBeforeStop} streamed pieces; stream ended ${stopped.ended}`),
      oneCallOneSettlement: check(calls.length === 1 && reservations.length === 1 && reservations[0].status === 'settled' && events.length === 1, `calls ${calls.length}, reservations ${JSON.stringify(reservations.map((r) => r.status))}, usage events ${events.length}`),
      noOpenHoldWithin5s: check(settledInTime, `no held reservation ${clearedAfterMs} ms after Stop was pressed (limit 5000)`),
      chargedForStreamedOutput: check(promptOnly !== null && charged !== null && charged > promptOnly && charged < hold && events[0]?.estimated === true, `charged ${charged} µAIC; prompt-only ${promptOnly}; hold ${hold}; max_tokens ${maxTokens}; estimated ${events[0]?.estimated}`),
    }),
    // Kept in the report for diagnosis when a check fails.
    reservations: reservations.map(({ key, status, amount, actualAmount, estimated }) => ({ key, status, amount, actualAmount, estimated })),
    usageEvents: events.map(({ key, amount, estimated, inputTokens, outputTokens }) => ({ key, amount, estimated, inputTokens, outputTokens })),
  };
}

async function scenario7(ctx) {
  const { staff, agentId } = ctx;
  const settledPerCall = (account, calls) => {
    const reservations = reservationsOf(account.id);
    const events = usageEventsOf(account.id);
    return {
      ok: calls === 2 && reservations.length === 2 && reservations.every((r) => r.status === 'settled') && events.length === 2,
      detail: `calls ${calls}, reservations ${JSON.stringify(reservations.map((r) => r.status))}, usage events ${events.length}`,
    };
  };

  // (a) The tool call fails on its input (I.4 "tool returns an error"): the error comes back to the
  //     model as the tool result. Whether LibreChat's schema check or legal-search rejects it, the
  //     model must see an error and the run must continue.
  const ca = await customer(staff, 's7-input', { credits: 5 });
  const invalid = await turn(ca, agentId, 's7-input', 'CALL_TOOL:get_article:{"number":"not-a-number"}');
  const a = settledPerCall(ca, invalid.calls.length);

  // (b) legal-search goes away between the model's tool call and the tool run.
  const cb = await customer(staff, 's7-down', { credits: 5 });
  const tag = nonce('s7-down');
  let firstCallSeen = false;
  let result = { text: null, error: 'not run' };
  let healthyAgain = false;
  try {
    const pending = chat({ token: cb.token, agentId, text: `DELAY_MS:8000 CALL_TOOL:search_law:{"query":"العربون"} ${tag}`, timeoutMs: 150_000 }).catch((error) => ({ text: null, error: String(error) }));
    firstCallSeen = await waitUntil(() => callsFor(tag).length >= 1, 30_000);
    compose(['stop', 'legal-search']);
    result = await pending;
  } finally {
    // Always bring legal-search back, even when the steps above throw: later runs need it.
    compose(['up', '-d', '--no-deps', 'legal-search']);
    healthyAgain = await waitUntil(legalSearchHealthy, 60_000);
  }
  await sleep(1500);
  const down = { tag, result, calls: callsFor(tag), titles: titleCallsFor(tag) };
  const b = settledPerCall(cb, down.calls.length);

  // (c) LibreChat's MCP connection recovered: a normal search works again.
  const cc = await customer(staff, 's7-after', { credits: 5 });
  const after = await turn(cc, agentId, 's7-after', 'CALL_TOOL:search_law:{"query":"العربون"}');
  const toolResultText = (t) => (t.calls[1] ? JSON.stringify(t.calls[1].messages.filter((m) => m.role === 'tool')) : '');

  return {
    ...verdict({
      invalidInputReturnedToModel: check(invalid.calls.length === 2 && /TOOL_RESULT_SEEN/.test(invalid.result.text ?? '') && /error/i.test(toolResultText(invalid)), `reply: ${invalid.result.text?.slice(0, 160)}`),
      invalidInputSettledPerCall: check(a.ok, a.detail),
      unreachableToolReturnedToModel: check(firstCallSeen && down.calls.length === 2 && /TOOL_RESULT_SEEN/.test(result.text ?? '') && /error|fail/i.test(toolResultText(down)), `first call seen ${firstCallSeen}; reply: ${result.text?.slice(0, 160)}; error ${result.error ?? 'none'}`),
      unreachableToolSettledPerCall: check(b.ok, b.detail),
      legalSearchBackAfterTest: check(healthyAgain && after.calls.length === 2 && /المادة/.test(toolResultText(after)) && !/error|fail/i.test(toolResultText(after)), `healthy ${healthyAgain}; follow-up search reply: ${after.result.text?.slice(0, 120)}`),
    }),
    turns: [invalid, down, after].map(summarizeTurn),
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
  // Staging only: the skills the release listed (pinned ones live in the instructions) plus S2, so
  // scenario 1 can load a test skill on demand.
  const spec = JSON.parse(fs.readFileSync(path.join(ROOT, 'content', 'specialists', 'aqel.json'), 'utf8'));
  for (const name of [...spec.skills, 'staging-listed', 'staging-unlisted']) {
    if (!skillIds[name]) throw new Error(`deployment skill ${name} not found (have: ${Object.keys(skillIds).join(', ')})`);
  }
  const { skills: listedSkills } = composeSpecialist({
    spec,
    instructions: '',
    skills: Object.fromEntries(spec.skills.map((name) => [name, fs.readFileSync(path.join(ROOT, 'content', 'skills', name, 'SKILL.md'), 'utf8')])),
  });
  const patch = await api(`/api/agents/${agentId}`, {
    token: staff.token,
    method: 'PATCH',
    body: { skills: [...listedSkills, 'staging-listed'].map((name) => skillIds[name]), skills_enabled: true },
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
    ['2', scenario2],
    ['4', scenario4],
    ['9', scenario9],
    ['10', scenario10],
    ['8', scenario8],
    ['13', scenario13],
    ['7', scenario7],
    ['11', scenario11],
  ];
  // SCENARIOS=3 (or "1,2") runs only those; scenario 3 needs the summarisation config (README "Scenario 3").
  const optional = { 3: scenario3 };
  const selected = process.env.SCENARIOS?.split(',').map((s) => s.trim()).filter(Boolean);
  const plan = selected
    ? selected.map((id) => [id, optional[id] ?? order.find(([known]) => known === id)?.[1]]).filter(([, run]) => run)
    : order;
  for (const [id, run] of plan) {
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
  report.library = await libraryChecks(ctx);
  console.log(`library    ${report.library.pass ? 'PASS' : 'FAIL'}`);
  for (const [name, c] of Object.entries(report.library.checks)) console.log(`   ${c.ok ? 'ok  ' : 'FAIL'} ${name}: ${c.detail}`);
  report.proxy = await proxyChecks();
  console.log(`proxy      ${report.proxy.pass ? 'PASS' : 'FAIL'}`);
  for (const [name, c] of Object.entries(report.proxy.checks)) console.log(`   ${c.ok ? 'ok  ' : 'FAIL'} ${name}: ${c.detail}`);
  report.reconciliation = reconcile();
  console.log(`reconciliation ${report.reconciliation.ok ? 'ok' : 'FAIL'} ${JSON.stringify(report.reconciliation)}`);
  report.finishedAt = new Date().toISOString();
  report.pass = Object.values(report.scenarios).every((s) => s.pass) && report.library.pass && report.proxy.pass && report.reconciliation.ok;
  fs.writeFileSync(path.join(OUT, 'scenarios-report.json'), JSON.stringify(report, null, 2));
  console.log(report.pass ? 'ALL PASS' : 'FAILURES — see out/scenarios-report.json');
  process.exit(report.pass ? 0 : 1);
}

await main();
