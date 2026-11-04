// Acceptance driver: scenarios 1, 2, 3, 4, 7, 8, 9, 10, 11, 13, auth (passwordless sign-in), guard (the library sweep guard),
// chatonly (the tiers, the closed API, the citation guard) and the library checks (P1–P3 results) against the staging stack in this directory.
//
//   docker compose up -d --build && node scenarios.mjs
//
// Every run creates fresh accounts by phone, with codes read from the staging sink (no passwords exist); the
// staff account is made with the staff bootstrap runner and signs in with an app code. Evidence is judged from three
// sources: HTTP responses, the mock model's request log (out/llm-requests.jsonl — every provider call)
// and the ledger collections in MongoDB. Writes out/scenarios-report.json; exits 1 on any failure.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import {
  HERE, ROOT, OUT, BASE, RUN, PRICES, MODEL, sleep, nonce,
  api, waitForHealth, chat, newAccount, newPhone, signUp, staffAccount, enableApp, appCode, requestCode, verifyCode,
  withSinkCode, newestSinkRow, sessionOf, AUTH, PLACEHOLDER_DOMAIN, grant, customer,
  wallet, mongoQuery, reconcile, compose, legalSearchHealthy, reservationsOf, usageEventsOf, callsFor,
  titleCallsFor, flakyFor, carries, costOf, check, verdict, countBy, answered,
  providerCalls, titlesAfter, turn, summarizeTurn, waitUntil, chatAndStop, proxyChecks,
  summaryCallsFor, mcpCalls, legalSearchAlerts, sweepFlagCounts, specFor,
} from './lib.mjs';
import { composeSpecialist } from '../../content/compose.mjs';
import { scenarioChatOnly } from './chatonly.mjs';

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
      // The tier gate keeps a whitelist of body fields, and a customer has no skill to invoke by hand (Decision 16).
      manualSkillsIgnoredForCustomer: check(!e.calls.some((call) => carries(call, MARKERS.listed)), 'a customer naming a listed skill by hand does not load it'),
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

/**
 * The library: court-fees (REQ-SKL-010) and corpus v1 (REQ-COR-002..005, 007). Expected citation text is
 * built from content/corpus/laws.json at run time, so the checks never assume a value the registry lacks.
 */
async function libraryChecks(ctx) {
  const c = await customer(ctx.staff, 'lib', { credits: 30 });
  const laws = JSON.parse(fs.readFileSync(path.join(ROOT, 'content', 'corpus', 'laws.json'), 'utf8')).laws;
  const law = (slug) => laws.find((l) => l.slug === slug);
  const toolText = (t) => (t.calls[1] ? JSON.stringify(t.calls[1].messages.filter((m) => m.role === 'tool')) : '');
  const heading = (l, label) => `${l.title}${l.number != null ? ` رقم ${l.number}` : ''}${l.year != null ? ` لسنة ${l.year}` : ''} — ${label}`;
  // When the tool did not run (no second model call), say so with the model's reply, so the failure is readable.
  const ask = async (label, call) => {
    const t = await turn(c, ctx.agentId, label, `CALL_TOOL:${call}`);
    return toolText(t) || `NO_TOOL_RESULT (calls ${t.calls.length}) reply: ${t.result.text ?? ''}`;
  };

  const fees = await ask('lib-fees', 'get_article:{"number":1,"law":"court-fees"}');
  const penal = await ask('lib-penal', 'get_article:{"number":153,"suffix":"مكرر","law":"penal-code"}');
  const majalla = await ask('lib-majalla', 'get_article:{"number":1,"law":"majalla"}');
  const memoOwn = await ask('lib-memo-own', 'get_memorandum:{"article":107}');
  const memoRange = await ask('lib-memo-range', 'get_memorandum:{"article":214}');
  const memoNone = await ask('lib-memo-none', 'get_memorandum:{"article":1}');
  const filtered = await ask('lib-filter', 'search_law:{"query":"الحبس","law":"penal-code"}');
  const procedure = await ask('lib-procedure', 'get_article:{"number":1,"law":"civil-procedure"}');
  const penalHeading = heading(law('penal-code'), 'المادة 153 مكرر');
  const resultLaws = [...filtered.matchAll(/\[\d+\] (.+?) (?:رقم \d+ )?(?:لسنة \d+ )?— المادة/g)].map((m) => m[1]);
  return verdict({
    courtFeesArticle1: check(fees.includes('جدول رسوم المحاكم') && fees.includes('عن الدعوى أو الدعوى المتقابلة'), `tool result: ${fees.slice(0, 160)}`),
    unverifiedLabel: check(fees.includes('لم يُتحقق بعد'), 'result carries the unverified label'),
    penalCitationLine: check(penal.includes(penalHeading) && penal.includes('على الرغم مما ورد في أي قانون آخر'), `expected «${penalHeading}»; tool result: ${penal.slice(0, 220)}`),
    publicationDataLabel: check(law('penal-code').review.status === 'approved' || penal.includes('بيانات النشر لم يُتحقق منها بعد'), 'unapproved registry metadata is labelled'),
    majallaNote: check(majalla.includes('مجلة الأحكام العدلية') && majalla.includes(law('majalla').note), `tool result: ${majalla.slice(0, 160)}`),
    // Links come from the memorandum's own headings: 107's own note is 74 (العربون); note 166 explains 214–238;
    // article 1 (the short title) has no note.
    memorandumOwnNote: check(memoOwn.includes('العربون') && memoOwn.includes('تشرح المادة 107'), `tool result: ${memoOwn.slice(0, 220)}`),
    memorandumRange: check(memoRange.includes('تشرح المواد 214–238'), `tool result: ${memoRange.slice(0, 220)}`),
    memorandumNone: check(memoNone.includes('لا توجد ملاحظات في المذكرة الإيضاحية مرتبطة بالمادة 1 من القانون المدني الأردني.'), `tool result: ${memoNone.slice(0, 220)}`),
    lawFilter: check(resultLaws.length > 0 && resultLaws.every((t) => t === law('penal-code').title), `result laws: ${JSON.stringify(resultLaws)}`),
    civilProcedureArticle: check(procedure.includes(heading(law('civil-procedure'), 'المادة 1')) && procedure.includes('يسمى هذا القانون قانون أصول المحاكمات المدنية'), `tool result: ${procedure.slice(0, 200)}`),
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
  // Peak of simultaneously held credit, from the ledger's own postings: the rows' timestamps are stamped before a
  // transaction commits, so two holds that never coexisted can appear to overlap by milliseconds.
  const heldPostings = mongoQuery({ op: 'find', collection: 'iqraa_postings', filter: { account: `user:${c.id}:held` }, sort: { _id: 1 } });
  let running = 0;
  let peak = 0;
  for (const posting of heldPostings) {
    running += posting.amount;
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
  const burstSpec = await specFor(burster.token, agentId);
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
        spec: burstSpec,
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


// ---------------------------------------------------------------- library sweep guard (Phase 3, spec C)

const LIBRARY_SUSPENDED = 'تم إيقاف الوصول إلى المكتبة القانونية لهذا الحساب مؤقتًا. يُرجى التواصل مع الدعم.';
const LIBRARY_CAP_REACHED = 'تم بلوغ الحد المسموح من النصوص لهذه الإجابة أو لهذا اليوم. يُرجى الاعتماد على ما سبق استرجاعه.';
const GUARD_LAW = 'penal-code';
const GUARD_STAFF_ROUTES = [
  ['GET', '/api/iqraa/admin/library/flags'],
  ['POST', '/api/iqraa/admin/library/flags/:userId/clear'],
  ['GET', '/api/iqraa/admin/library/guard-settings'],
  ['PUT', '/api/iqraa/admin/library/guard-settings'],
  ['GET', '/api/iqraa/admin/library/guard-settings/history'],
  ['POST', '/api/iqraa/admin/library/guard-settings/simulate'],
  ['GET', '/api/iqraa/admin/library/telemetry'],
  ['POST', '/api/iqraa/admin/accounts/:userId/suspend'],
  ['POST', '/api/iqraa/admin/accounts/:userId/unsuspend'],
];

/**
 * The sweep guard end to end (spec C.7, REQ-GRD-001..009). A customer's account walks get_article over
 * articles 1–40 of one law through legal-search's MCP endpoint, under the customer's own user id (what
 * LibreChat sends as X-Iqraa-User): suspected at article 12 (refused: 11 served > throttle cap 10), proven
 * at 24 (the 12th sequential attempt after the flag), suspended after. Then: the alert lines in log order,
 * the evidence in the staff list, LibreChat's own get_article refused, a staff clear restoring access, a
 * control user doing topic research left unflagged, a settings change applied within 30 s and recorded
 * (then put back), simulate changing nothing, customers denied all nine staff routes, and staff account
 * suspension refusing chat before any provider call until it is lifted.
 */
async function scenarioGuard(ctx) {
  const { staff, agentId } = ctx;
  const library = (route, options = {}) => api(`/api/iqraa/admin/library${route}`, { token: staff.token, ...options });
  const refused = (text) => text === LIBRARY_CAP_REACHED || text === LIBRARY_SUSPENDED;
  const servedArticle = (text, number) => new RegExp(`— المادة ${number}(?!\\d)`).test(text ?? '');
  const article = (number) => ({ tool: 'get_article', arguments: { number, law: GUARD_LAW } });
  const toolText = (t) => (t.calls[1] ? JSON.stringify(t.calls[1].messages.filter((m) => m.role === 'tool')) : '');

  // 1. The scripted sweep, and the evidence staff see.
  const sweeper = await customer(staff, 'guard-sweep', { credits: 5 });
  const walk = mcpCalls(sweeper.id, Array.from({ length: 40 }, (_, i) => article(i + 1)));
  const flag = ((await library('/flags')).json?.flags ?? []).find((f) => f.user_id === sweeper.id);

  // 2. LibreChat's own get_article for the proven user; then the alert lines.
  const viaChat = await turn(sweeper, agentId, 'guard-chat', `CALL_TOOL:get_article:{"number":41,"law":"${GUARD_LAW}"}`);
  // sweep_refused: articles 25–40 and the chat call (the escalating call 24 raises sweep_flag_escalated only).
  await waitUntil(() => legalSearchAlerts(sweeper.id).filter((a) => a.event === 'sweep_refused').length >= 17, 15_000);
  // Emission order (the log's own line order) and attribution order (log id) must agree.
  const emitted = legalSearchAlerts(sweeper.id);
  const alerts = [...emitted].sort((a, b) => a.log_id - b.log_id);
  const changes = alerts.filter((a) => a.event !== 'sweep_refused');
  const emittedChanges = emitted.filter((a) => a.event !== 'sweep_refused').map((a) => a.event);
  const refusalAlerts = alerts.length - changes.length;

  // 3. Staff clear: the watermark moves, the next get_article is served and no flag reopens.
  const cleared = await library(`/flags/${encodeURIComponent(sweeper.id)}/clear`, { method: 'POST', body: { reason: `staging guard ${RUN}` } });
  const [afterClear] = mcpCalls(sweeper.id, [article(42)]);
  const reopened = ((await library('/flags')).json?.flags ?? []).some((f) => f.user_id === sweeper.id);

  // 4. The control: topic research across five laws (searches and scattered reads), under the thresholds.
  const control = `guard-control-${RUN}`;
  const topics = [['civil-code', 'العقد'], ['commerce', 'الكمبيالة'], ['companies', 'الشركة'], ['labour', 'العامل'], ['civil-procedure', 'الدعوى']];
  const reads = [['civil-code', 87], ['civil-code', 88], ['civil-code', 246], ['commerce', 40], ['commerce', 90], ['companies', 5], ['companies', 120], ['labour', 22], ['labour', 23], ['labour', 70], ['civil-procedure', 3], ['civil-procedure', 110]];
  const research = mcpCalls(control, [
    ...topics.flatMap(([law, query]) => [{ tool: 'search_law', arguments: { query, law } }, { tool: 'search_law', arguments: { query: `${query} التعويض`, law } }]),
    ...reads.map(([law, number]) => ({ tool: 'get_article', arguments: { number, law } })),
  ]);
  const everyFlag = (await library('/flags?status=all')).json?.flags ?? [];

  // 5. A settings change applies within 30 s and is in the history; then it is put back — always, even
  // when a step in between throws, so a failed run never leaves staging on the changed value.
  const SEEDED_MAX = 5; // legal-search's first-start default (LEGAL_SEARCH_MAX_RESULTS unset on staging)
  const previousMax = (await library('/guard-settings')).json?.settings?.max_results;
  const targetMax = previousMax === 2 ? 3 : 2;
  const probe = `guard-settings-${RUN}`;
  let put = null;
  let applied = false;
  let appliedMs = null;
  let shown = null;
  let latest = null;
  let restored = null;
  try {
    put = await library('/guard-settings', { method: 'PUT', body: { settings: { max_results: targetMax }, reason: `staging guard ${RUN}: settings apply` } });
    const putAt = Date.now();
    applied = await waitUntil(() => {
      const [text] = mcpCalls(probe, [{ tool: 'search_law', arguments: { query: 'العقد', law: 'civil-code' } }]);
      shown = (text.match(/^\[\d+\]/gm) ?? []).length;
      return shown === targetMax;
    }, 30_000);
    appliedMs = Date.now() - putAt;
    latest = ((await library('/guard-settings/history')).json?.history ?? [])[0];
  } finally {
    restored = await library('/guard-settings', { method: 'PUT', body: { settings: { max_results: previousMax ?? SEEDED_MAX }, reason: `staging guard ${RUN}: restore` } });
  }

  // 6. Simulate: candidate settings in, the users who would be flagged out, nothing changed.
  const flagsBefore = (await library('/flags?status=all')).text;
  const settingsBefore = (await library('/guard-settings')).text;
  const simulated = await library('/guard-settings/simulate', { method: 'POST', body: { settings: { suspected_run: 10 }, days: 1 } });
  const flagsAfter = (await library('/flags?status=all')).text;
  const settingsAfter = (await library('/guard-settings')).text;
  const wouldFlag = simulated.json?.would_flag ?? [];
  const telemetry = await library('/telemetry?days=1');

  // 7. A customer gets 403 on every staff route.
  const outsider = await customer(staff, 'guard-customer', { credits: 0 });
  const denied = [];
  for (const [method, route] of GUARD_STAFF_ROUTES) {
    const res = await api(route.replace(':userId', sweeper.id), { token: outsider.token, method, body: method === 'GET' ? undefined : { reason: 'x' } });
    denied.push({ route: `${method} ${route}`, status: res.status, code: res.json?.code });
  }
  const allDenied = denied.length === 9 && denied.every((d) => d.status === 403 && d.code === 'IQRAA_FORBIDDEN');

  // 8. Staff account suspension: refused before any provider call; unsuspend restores chat.
  const member = await customer(staff, 'guard-account', { credits: 5 });
  const suspend = await api(`/api/iqraa/admin/accounts/${member.id}/suspend`, { token: staff.token, method: 'POST', body: { reason: `staging guard ${RUN}` } });
  const blocked = await turn(member, agentId, 'guard-suspended', 'suspended probe');
  blocked.titles = await titlesAfter(blocked.tag, { expectOne: false, windowMs: 6_000 });
  const unsuspend = await api(`/api/iqraa/admin/accounts/${member.id}/unsuspend`, { token: staff.token, method: 'POST', body: {} });
  const back = await turn(member, agentId, 'guard-unsuspended', 'unsuspended probe');

  const opened = flag?.evidence?.opened?.[0] ?? {};
  const escalated = flag?.evidence?.escalated?.[0] ?? {};
  const sweeperWould = wouldFlag.find((u) => u.user_id === sweeper.id);
  return {
    ...verdict({
      suspectedAt12: check(walk.slice(0, 11).every((text, i) => servedArticle(text, i + 1)) && walk[11] === LIBRARY_CAP_REACHED, `articles 1–11 served ${walk.slice(0, 11).filter((text, i) => servedArticle(text, i + 1)).length}/11; article 12: ${walk[11]?.slice(0, 80)}`),
      provenAt24: check(walk.slice(12, 23).every((text) => text === LIBRARY_CAP_REACHED) && walk.slice(23).every((text) => text === LIBRARY_SUSPENDED), `13–23 throttled ${walk.slice(12, 23).filter((text) => text === LIBRARY_CAP_REACHED).length}/11; 24–40 suspended ${walk.slice(23).filter((text) => text === LIBRARY_SUSPENDED).length}/17`),
      alertsInOrder: check(alerts.every((a) => a.level === 'error') && JSON.stringify(changes.map((a) => [a.event, a.flag_level])) === JSON.stringify([['sweep_flag_opened', 'suspected'], ['sweep_flag_escalated', 'proven']]) && JSON.stringify(emittedChanges) === JSON.stringify(['sweep_flag_opened', 'sweep_flag_escalated']) && refusalAlerts === 17, `changes ${JSON.stringify(changes.map((a) => `${a.event}@${a.log_id}`))}; emitted ${JSON.stringify(emittedChanges)}; sweep_refused ${refusalAlerts} (exactly 17: articles 25–40 plus the chat call; more means duplicated alert lines)`),
      staffSeeEvidence: check(flag?.level === 'proven' && opened.kind === 'run' && opened.law === GUARD_LAW && opened.first === 1 && opened.last === 12 && escalated.first === 13 && escalated.last === 24 && escalated.after_flag === true, `flag ${JSON.stringify({ level: flag?.level, opened, escalated }).slice(0, 300)}`),
      refusedThroughLibreChat: check(viaChat.calls.length === 2 && toolText(viaChat).includes(LIBRARY_SUSPENDED), `calls ${viaChat.calls.length}; tool result: ${toolText(viaChat).slice(0, 200)}`),
      clearRestoresAccess: check(cleared.status === 200 && cleared.json?.flag?.cleared_by === staff.id && Boolean(cleared.json?.flag?.cleared_at) && servedArticle(afterClear, 42) && !reopened, `clear ${cleared.status} by ${cleared.json?.flag?.cleared_by} at ${cleared.json?.flag?.cleared_at}; next get_article: ${afterClear?.split('\n')[0]}; flag reopened ${reopened}`),
      controlNotFlagged: check(research.every((text) => !refused(text) && !text.startsWith('ERROR')) && !everyFlag.some((f) => f.user_id === control), `${research.filter((text) => !refused(text)).length}/${research.length} control calls served; flagged ${everyFlag.some((f) => f.user_id === control)}`),
      settingsApplyWithin30s: check(previousMax === SEEDED_MAX && put.status === 200 && applied && appliedMs <= 30_000, `max_results before the run ${previousMax} (seeded ${SEEDED_MAX}; anything else is drift left by an earlier run); PUT ${put.status}; ${previousMax} → ${targetMax}; the next search shows ${shown} result(s) after ${appliedMs} ms`),
      settingsHistory: check(latest?.changed_by === staff.id && latest?.reason?.includes(RUN) && latest?.previous?.max_results === previousMax && latest?.settings?.max_results === targetMax && Boolean(latest?.changed_at) && restored.status === 200, `latest ${JSON.stringify(latest ? { by: latest.changed_by, at: latest.changed_at, reason: latest.reason, from: latest.previous?.max_results, to: latest.settings?.max_results } : null)}; put back ${restored.status}`),
      simulateChangesNothing: check(simulated.status === 200 && sweeperWould?.level === 'proven' && !wouldFlag.some((u) => u.user_id === control) && flagsAfter === flagsBefore && settingsAfter === settingsBefore, `simulate ${simulated.status}: ${wouldFlag.length} user(s) would be flagged, the sweeper ${sweeperWould?.level}; flags unchanged ${flagsAfter === flagsBefore}; settings unchanged ${settingsAfter === settingsBefore}`),
      telemetryReport: check(telemetry.status === 200 && telemetry.json?.window_days === 1 && telemetry.json?.users >= 3, `telemetry ${telemetry.status}: users ${telemetry.json?.users}, user-days ${telemetry.json?.user_days}, longest run p99 ${telemetry.json?.longest_run?.p99} max ${telemetry.json?.longest_run?.max}`),
      customerDenied: check(allDenied, allDenied ? 'all 9 staff routes: 403 IQRAA_FORBIDDEN' : JSON.stringify(denied)),
      accountSuspendedBeforeProvider: check(suspend.status === 200 && providerCalls(blocked) === 0 && !answered(blocked) && (blocked.result.text ?? '').includes('IQRAA_ACCOUNT_SUSPENDED'), `suspend ${suspend.status}; provider calls ${blocked.calls.length}, title calls ${blocked.titles.length}; reply: ${blocked.result.text?.slice(0, 200)}`),
      unsuspendRestoresChat: check(unsuspend.status === 200 && answered(back) && back.calls.length >= 1, `unsuspend ${unsuspend.status}; provider calls ${back.calls.length}; reply: ${back.result.text?.slice(0, 120)}`),
    }),
    turns: [viaChat, blocked, back].map(summarizeTurn),
  };
}

// ---------------------------------------------------------------- passwordless sign-in (spec-passwordless-login)

const PASSWORD_ROUTES = [
  ['/api/auth/login', { email: 'nobody@example.test', password: 'not-a-password' }],
  ['/api/auth/register', { name: 'x', username: 'nobody', email: 'nobody@example.test', password: 'not-a-password', confirm_password: 'not-a-password' }],
  ['/api/auth/requestPasswordReset', { email: 'nobody@example.test' }],
  ['/api/auth/resetPassword', { userId: '000000000000000000000000', token: 'x', password: 'not-a-password', confirm_password: 'not-a-password' }],
  ['/api/auth/2fa/verify-temp', { tempToken: 'x', token: '000000' }],
  ['/api/admin/login/local', { email: 'nobody@example.test', password: 'not-a-password' }],
];
const sameUser = (res, id) => res.status === 200 && String(res.json?.user?.id ?? res.json?.user?._id) === id;
const said = (res) => `${res.status} ${res.json?.code ?? ''}`.trim();

/**
 * Every staging acceptance line of the spec on the code flow (sink): sign-up by phone (the same phone again is
 * the same account), WhatsApp-code sign-in typed in the local form, refresh with the code sign-in's cookie, the
 * ADMIN role refused to an account without the app and given to one with it (hook L5, both sides), app set-up through LibreChat with the phone as
 * the authenticator label, app sign-in, the same app code refused again, a backup code, email added and bound
 * after its code, email-code sign-in; staff refused with a delivered code and accepted with the app code, staff
 * unable to turn the app off; every password route closed; byte-identical sign-in answers for known, staff and
 * unknown identifiers with nothing sent to the unknown ones; audit rows without a code.
 */
async function scenarioAuth(ctx) {
  const { staff } = ctx;

  // 1. Sign-up by phone; the same phone again signs into the same account (spec item 14).
  const first = await signUp(newAccount('auth'));
  const meAfterSignUp = await api(`${AUTH}/me`, { token: first.token });
  const again = await withSinkCode(first.phone, 'signup', () => requestCode(first.phone, 'signup'));
  const repeat = await api(`${AUTH}/signup`, { method: 'POST', body: { phone: first.phone, code: again.code, name: first.name } });

  // 2. WhatsApp-code sign-in, typed in the local form (079…); the sink row is under the E.164 number.
  const local = `0${first.phone.slice(4)}`;
  const signin = await withSinkCode(first.phone, 'signin', () => requestCode(local, 'signin'));
  const byCode = await verifyCode(local, 'code', signin.code);
  let a = { ...first, ...sessionOf(byCode, 'auth: code sign-in') };

  // 3. Sessions stay LibreChat's: the refresh cookie of a code sign-in gives a new token.
  const refreshed = await api('/api/auth/refresh', { method: 'POST', cookie: `refreshToken=${a.refreshToken}` });

  // 4. Hook L5: staff cannot give ADMIN to an account without the app (before it has one).
  const toAdmin = await api('/api/admin/roles/ADMIN/members', { token: staff.token, method: 'POST', body: { userId: a.id } });

  // 5. App set-up through LibreChat (enable + confirm) while the account is on its placeholder email: the
  // authenticator label is the phone (Decision 12). Then app sign-in, the same code again, a backup code.
  a = await enableApp(a);
  const label = decodeURIComponent(new URL(a.app.otpauthUrl).pathname);
  const used = await appCode(a); // the step after the confirm's: the wait is harmless (confirm records no step)
  const byApp = await verifyCode(a.phone, 'app', used);
  const replay = await verifyCode(a.phone, 'app', used);
  const backup = a.app.backupCodes[0];
  const byBackup = await verifyCode(a.phone, 'backup', backup);

  // 5b. Hook L5, the other side: staff can give ADMIN to an account that has the app. A throwaway account takes it
  // (`a` must stay a customer for the code sign-ins below) and goes back to USER at once, so no stray admin stays.
  const b = await enableApp(await signUp(newAccount('auth-admin')));
  const toAdminWithApp = await api('/api/admin/roles/ADMIN/members', { token: staff.token, method: 'POST', body: { userId: b.id } });
  const fromAdmin = await api(`/api/admin/roles/ADMIN/members/${b.id}`, { token: staff.token, method: 'DELETE' });

  // 6. Add an email: bound only after its code; then sign in by email code (the app does not stop it, item 2).
  const email = `stg.auth.${RUN}${crypto.randomBytes(2).toString('hex')}@example.test`;
  const added = await withSinkCode(email, 'email_add', () => api(`${AUTH}/email/add`, { token: a.token, method: 'POST', body: { email } }));
  const meBefore = await api(`${AUTH}/me`, { token: a.token });
  const bound = await api(`${AUTH}/email/verify`, { token: a.token, method: 'POST', body: { email, code: added.code } });
  const meAfter = await api(`${AUTH}/me`, { token: a.token });
  const emailSignin = await withSinkCode(email, 'signin', () => requestCode(email, 'signin'));
  const byEmail = await verifyCode(email, 'code', emailSignin.code);

  // 7. Staff: a delivered code is issued, then refused (Decision 7); the app code is accepted; the app stays on.
  // The disable body is empty, so a missing guard answers 400 instead of turning staff 2FA off mid-run.
  const staffSignin = await withSinkCode(staff.phone, 'signin', () => requestCode(staff.phone, 'signin'));
  const staffByCode = await verifyCode(staff.phone, 'code', staffSignin.code);
  const staffByApp = await verifyCode(staff.phone, 'app', await appCode(staff));
  const disable = await api('/api/auth/2fa/disable', { token: staff.token, method: 'POST', body: {} });

  // 8. No enumeration (REQ-AUTH-008): unknown identifiers get the same bytes, and nothing reaches the sink.
  const unknownPhone = newPhone();
  const unknownEmail = `stg.nobody.${RUN}${crypto.randomBytes(2).toString('hex')}@example.test`;
  const unknowns = [await requestCode(unknownPhone, 'signin'), await requestCode(unknownEmail, 'signin')];
  await sleep(3_000); // a sign-in answer does not wait for delivery: give a stray row time to land
  const stray = [unknownPhone, unknownEmail].filter((to) => newestSinkRow(to, 'signin') !== null);
  const answers = [signin.sent, staffSignin.sent, emailSignin.sent, ...unknowns];
  const distinct = new Set(answers.map((res) => `${res.status} ${res.text}`));

  // 9. Every password route answers 403 IQRAA_PASSWORDS_OFF (REQ-AUTH-006, Decision 2).
  const closed = [];
  for (const [route, body] of PASSWORD_ROUTES) closed.push({ route, said: said(await api(route, { method: 'POST', body })) });

  // 10. Audit rows (REQ-AUTH-010): this account's rows exist and no row carries a code it used.
  const codes = [
    ...mongoQuery({ op: 'find', collection: 'iqraa_auth_sink', filter: { to: { $in: [a.phone, email, staff.phone] } } }).map((row) => row.code),
    used,
    backup,
  ];
  const events = mongoQuery({ op: 'find', collection: 'iqraa_auth_events', filter: {}, sort: { at: -1 }, limit: 300 });
  const own = events.filter((row) => String(row.userId) === a.id);
  const leaking = events.filter((row) => codes.some((code) => new RegExp(`(?<![0-9A-Za-z])${code}(?![0-9A-Za-z])`).test(JSON.stringify(row))));

  const national = first.phone.slice(-9);
  return verdict({
    signUpByPhone: check(first.role === 'USER' && first.email === `${first.id}${PLACEHOLDER_DOMAIN}` && meAfterSignUp.json?.phone === first.phone && meAfterSignUp.json?.email === null && meAfterSignUp.json?.twoFactorEnabled === false, `role ${first.role}; email ${first.email}; me ${meAfterSignUp.text.slice(0, 120)}`),
    samePhoneSameAccount: check(again.sent.status === 200 && sameUser(repeat, first.id), `second sign-up ${said(repeat)}, user ${repeat.json?.user?.id ?? repeat.json?.user?._id} (first ${first.id})`),
    signInByWhatsAppCode: check(sameUser(byCode, first.id) && signin.row.channel === 'whatsapp' && signin.row.to === first.phone, `typed ${local}; sink row to ${signin.row.to} by ${signin.row.channel}; verify ${said(byCode)}`),
    refreshFromCodeSignIn: check(Boolean(a.refreshToken) && refreshed.status === 200 && Boolean(refreshed.json?.token) && sameUser(refreshed, first.id), `refresh cookie ${a.refreshToken ? 'set' : 'missing'}; refresh ${refreshed.status}`),
    staffRoleNeedsApp: check(toAdmin.status === 403 && toAdmin.json?.code === 'IQRAA_STAFF_NEEDS_APP', `POST /api/admin/roles/ADMIN/members: ${said(toAdmin)}`),
    staffRoleWithApp: check(toAdminWithApp.status === 200 && toAdminWithApp.json?.success === true && fromAdmin.status === 200, `POST /api/admin/roles/ADMIN/members for an account with the app: ${said(toAdminWithApp)}; role taken back (DELETE …/members/<id>): ${said(fromAdmin)}`),
    appLabelIsThePhone: check(!label.includes('phone.iqraa.invalid') && label.replace(/\D/g, '').endsWith(national), `authenticator label ${label}`),
    appSignIn: check(sameUser(byApp, first.id), `app code: ${said(byApp)}`),
    appCodeAcceptedOnce: check(replay.status === 401 && replay.json?.code === 'IQRAA_AUTH_INVALID_CODE', `same app code again: ${said(replay)}`),
    backupCodeSignIn: check(sameUser(byBackup, first.id), `backup code: ${said(byBackup)}`),
    emailBoundAfterCode: check(added.row.channel === 'email' && meBefore.json?.email === null && bound.status === 200 && bound.json?.email === email && meAfter.json?.email === email, `sink by ${added.row.channel}; before verify ${meBefore.json?.email}; verify ${said(bound)}; after ${meAfter.json?.email}`),
    emailCodeSignIn: check(sameUser(byEmail, first.id) && byEmail.json?.user?.email === email, `email code: ${said(byEmail)}, user email ${byEmail.json?.user?.email}`),
    staffDeliveredCodeRefused: check(staffByCode.status === 403 && staffByCode.json?.code === 'IQRAA_AUTH_APP_REQUIRED', `staff WhatsApp code: ${said(staffByCode)}`),
    staffAppCodeAccepted: check(sameUser(staffByApp, staff.id) && staffByApp.json?.user?.role === 'ADMIN', `staff app code: ${said(staffByApp)}, role ${staffByApp.json?.user?.role}`),
    staffCannotTurnAppOff: check(disable.status === 403 && disable.json?.code === 'IQRAA_STAFF_APP_REQUIRED', `POST /api/auth/2fa/disable as staff: ${said(disable)}`),
    passwordRoutesClosed: check(closed.every((c) => c.said === '403 IQRAA_PASSWORDS_OFF'), JSON.stringify(closed)),
    signInAnswerIdentical: check(distinct.size === 1 && answers[0].status === 200, `${distinct.size} distinct answer(s) for known phone, staff phone, known email, unknown phone, unknown email: ${[...distinct][0]?.slice(0, 160)}`),
    unknownGetsNothing: check(stray.length === 0, `sink rows for unknown identifiers: ${stray.length}`),
    auditWithoutCodes: check(own.length >= 4 && leaking.length === 0, `${own.length} audit rows for the account; rows carrying a used code: ${leaking.length} (of ${events.length} read, ${codes.length} codes)`),
  });
}

// ---------------------------------------------------------------- setup and run

async function setup() {
  await waitForHealth();
  // The staff bootstrap runner (request, sink code, enrol, app code, promote), then phone plus app code.
  const staff = await staffAccount('staff');

  // The tiers: release the three tier agents onto the mock model, then make sure librechat.yaml and iqraa.json
  // carry their ids. Agent ids are generated, so the first run on a stack (or after its volumes are reset) rewrites
  // both files and recreates LibreChat once; later runs find them unchanged.
  const resolvedFile = path.join(OUT, 'tiers-resolved.json');
  const release = spawnSync(
    process.execPath,
    [path.join(ROOT, 'content', 'release.mjs'), '--resolved', resolvedFile, '--prices', path.join(HERE, 'iqraa.json')],
    { encoding: 'utf8', env: { ...process.env, LIBRECHAT_URL: BASE, IQRAA_STAFF_TOKEN: staff.token, IQRAA_PROVIDER: 'MockLLM', IQRAA_MODEL: MODEL } },
  );
  if (release.status !== 0) throw new Error(`release failed: ${release.stderr || release.stdout}`);
  const agentId = release.stdout.match(/^tier fast .*\((agent_[^)]+)\)/m)?.[1];
  if (!agentId) throw new Error(`no fast tier agent id in release output: ${release.stdout}`);
  const applied = spawnSync(
    process.execPath,
    [path.join(ROOT, 'content', 'tiers.mjs'), 'apply', '--resolved', resolvedFile, '--yaml', path.join(HERE, 'librechat.yaml'), '--iqraa', path.join(HERE, 'iqraa.json')],
    { encoding: 'utf8' },
  );
  if (applied.status !== 0) throw new Error(`tiers apply failed: ${applied.stderr || applied.stdout}`);
  if (applied.stdout.startsWith('changed')) {
    // A container recreate, never a restart: a bind-mounted file is read at start, and a restart can reuse old state.
    compose(['up', '-d', '--no-deps', '--force-recreate', 'librechat']);
    compose(['restart', 'proxy']); // nginx resolves `librechat` once, at its start
    await waitForHealth();
  }

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
  // 9 runs before 8 (8 sizes its wallet from a scenario 9 reservation); 11 last (its burst trips the rate limit);
  // auth after 7, by when the staff app step setup used has passed (no wait for a fresh one).
  const order = [
    ['1', scenario1],
    ['2', scenario2],
    ['4', scenario4],
    ['9', scenario9],
    ['10', scenario10],
    ['8', scenario8],
    ['13', scenario13],
    ['7', scenario7],
    ['auth', scenarioAuth],
    ['guard', scenarioGuard],
    ['chatonly', scenarioChatOnly],
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
  // reconcile.js reads MongoDB only; the open sweep flags come from the fork's staff route (spec C.5).
  try {
    const flags = await sweepFlagCounts(ctx.staff);
    report.reconciliation.sweepFlags = flags;
    report.reconciliation.sweepFlagsLine = `open sweep flags: suspected ${flags.suspected}, proven ${flags.proven}`;
  } catch (error) {
    report.reconciliation.ok = false;
    report.reconciliation.problems = [...(report.reconciliation.problems ?? []), `open sweep flags: ${error.message}`];
  }
  console.log(`reconciliation ${report.reconciliation.ok ? 'ok' : 'FAIL'} ${JSON.stringify(report.reconciliation)}`);
  if (report.reconciliation.sweepFlagsLine) console.log(report.reconciliation.sweepFlagsLine);
  report.finishedAt = new Date().toISOString();
  report.pass = Object.values(report.scenarios).every((s) => s.pass) && report.library.pass && report.proxy.pass && report.reconciliation.ok;
  fs.writeFileSync(path.join(OUT, 'scenarios-report.json'), JSON.stringify(report, null, 2));
  console.log(report.pass ? 'ALL PASS' : 'FAILURES — see out/scenarios-report.json');
  process.exit(report.pass ? 0 : 1);
}

await main();
