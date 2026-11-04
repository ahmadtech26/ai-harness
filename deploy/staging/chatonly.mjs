// Scenario `chatonly`: the chat-only product (spec-chat-only-tiers-closed-corpus) against the staging stack.
//
//   SCENARIOS=chatonly node scenarios.mjs      (run twice: once with iqraa.json grounding.mode "shadow", once "block")
//
// (a) a customer reaches the model only through a named tier, and nothing the client sends changes the run;
// (b) every route outside the allowlist answers 403, the plan roles hold no permission but AGENTS.USE and
//     MCP_SERVERS.USE, and the routes the client needs stay open; (c) the internal model is not readable, also
//     when the provider refuses a turn in words that name it (the customer reads the fork's notice);
// (d) the citation guard logs an ungrounded answer (shadow) or replaces it (block), and lets a grounded one be,
//     also for an answer the customer stops halfway (the stop route saves it, not the chat controller);
// (e) a plan without the tier is refused, and a plan lost mid-conversation leaves the chat readable;
// (f) uploads obey the type and size limits, whatever `endpoint` the form names; (g) the starters and the footer.
// Evidence: HTTP answers, the mock model's request log, and `iqraa_guard_events`. Check (c) reads the agent route,
// the model list, the endpoint list, the whole SSE stream, the final event, the chat status and the resume frame while
// a turn runs, a fork, the conversation and its title and the stored messages, for a finished turn and for a refused
// one; it does not read the ledger, response headers or server logs (Residual risk).
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { HERE, BASE, MODEL, UA, api, carries, chatAndStop, check, callsFor, chat, customer, llmLog, mongoQuery, nonce, sleep, specFor, turn, verdict, waitUntil } from './lib.mjs';

/** The fixed Arabic text of a blocked answer: keep equal to BLOCKED_MESSAGE in answer-guard.ts. */
export const BLOCKED_MESSAGE =
  'تعذّر عرض هذه الإجابة لأنها تضمّنت استشهادًا بنص قانوني لم يُسترجع من المكتبة القانونية. يمكنك إعادة صياغة السؤال أو تحديد القانون والمادة ليبحث عقل في المكتبة.';
/** The fixed Arabic notice of a tier turn that failed: keep equal to FAILURE_NOTICE in answer-guard.ts. */
export const FAILURE_NOTICE = 'تعذّر إكمال الإجابة الآن. حاول مرة أخرى بعد قليل.';
const NOT_IN_PLAN = 'هذه الفئة غير متاحة في باقتك الحالية، ابدأ محادثة جديدة بفئة متاحة';
/** The three legal-search tools a tier agent must send the provider (with nothing else): `<tool>_mcp_legal-search`. */
const LIBRARY_TOOLS = ['search_law_mcp_legal-search', 'get_article_mcp_legal-search', 'get_memorandum_mcp_legal-search'];
/** What the real client shows in the footer; the shell page only says whether to show it, so read it from /api/config. */
const FOOTER = 'Iqraa LAW AI';
/** What the pinned skills add: `read_file` opens only those skills' files while the code environment is off (the startup lint). */
const SKILL_TOOLS = ['skill', 'read_file'];

/**
 * The prompt of the stop probe: the mock streams the FINAL_TEXT a word at a time (SLOW_STREAM, 250 ms), and its first
 * words cite another country's article, so a Stop pressed after a few filler words lands after the citation.
 */
export const stopProbeText = (tag) => `SLOW_STREAM:250 stop probe ${tag}\nFINAL_TEXT:نصت المادة 29 من القانون المدني المصري على كذا وكذا. ${'STREAMED_PIECE '.repeat(40)}`;

/** Routes a customer must not reach: [method, path, body]. Each answers 403 IQRAA_FORBIDDEN. */
export const DENIED_ROUTES = [
  ['GET', '/api/presets'],
  ['POST', '/api/presets', { title: 'x', endpoint: 'agents' }],
  ['GET', '/api/projects'],
  ['GET', '/api/keys?name=agents'],
  ['PUT', '/api/user/plugins', { pluginKey: 'x', action: 'install' }],
  ['GET', '/api/prompts/groups'],
  ['GET', '/api/mcp/servers'],
  ['GET', '/api/mcp/tools'],
  ['GET', '/api/skills'],
  ['GET', '/api/agents/categories'],
  ['POST', '/api/agents', { name: 'mine', provider: 'MockLLM', model: MODEL }],
  ['GET', '/api/agents/tools'],
  ['GET', '/api/memories'],
  ['POST', '/api/share/abc'],
  ['GET', '/api/tags'],
  ['GET', '/api/schedules'],
  ['GET', '/api/api-keys'],
  ['GET', '/api/traces/abc'],
  ['GET', '/api/insights'],
  ['POST', '/api/convos/import'],
  ['POST', '/api/agents/chat/steer', { conversationId: 'x', text: 'x' }],
  ['POST', '/api/agents/chat/queued-turns', { conversationId: 'x', text: 'x' }],
  ['POST', '/api/agents/chat/resume', {}],
  ['GET', '/api/files/agent/agent_x'],
  ['GET', '/api/permissions/search-principals?q=a'],
  ['GET', '/api/admin/roles'],
  ['GET', '/api/iqraa/admin/library/flags'],
  ['GET', '/api/user/settings/favorites'],
  ['POST', '/api/user/settings/favorites', { favorites: [] }],
  ['GET', '/api/files/speech/config/get'],
  ['POST', '/api/agents/chat/active', { endpoint: 'MockLLM', model: MODEL, text: 'x' }],
];

/**
 * Other spellings of the plain model chat of the incident: [method, path]. Each must answer 403 and never reach the
 * model (a trailing slash, another endpoint, `active`, an upper-case path, a query).
 */
export const PLAIN_CHAT_VARIANTS = [
  ['POST', '/api/agents/chat/'],
  ['POST', '/api/agents/chat/MockLLM'],
  ['POST', '/api/agents/chat/agents/'],
  ['POST', '/api/agents/chat/active'],
  ['POST', '/api/agents/chat/stream'],
  ['POST', '/api/agents/chat/openAI?x=1'],
  ['POST', '/API/AGENTS/CHAT/MockLLM'],
];

/** Routes the stock chat screen needs: a customer must not get 403 here. */
export const OPEN_ROUTES = [
  ['GET', '/api/config'],
  ['GET', '/api/user'],
  ['GET', '/api/convos'],
  ['GET', '/api/agents'],
  ['GET', '/api/endpoints'],
  ['GET', '/api/banner'],
  ['GET', '/api/iqraa/starters'],
  ['GET', '/api/iqraa/wallet'],
];

/** The labels whose text contains any needle: how the model-hiding check reads what a customer can read. */
export function findLeaks(texts, needles) {
  return Object.entries(texts)
    .filter(([, text]) => needles.some((needle) => String(text).includes(needle)))
    .map(([label]) => label);
}

/** The paths of keys that name the model behind a tier. A message's or conversation's own `model` holds the tier name. */
export function findIdentityFields(value, path = '$') {
  if (Array.isArray(value)) return value.flatMap((entry, index) => findIdentityFields(entry, `${path}[${index}]`));
  if (!value || typeof value !== 'object') return [];
  const ownModel = 'messageId' in value || 'conversationId' in value;
  return Object.entries(value).flatMap(([key, entry]) => [
    ...(key === 'provider' || (key === 'model' && !ownModel) ? [`${path}.${key}`] : []),
    ...findIdentityFields(entry, `${path}.${key}`),
  ]);
}

/** The JSON of each `data:` line of a stream's blocks, skipping any that is not JSON. */
export function framesOf(blocks) {
  return blocks.flatMap((block) =>
    block.split('\n').filter((line) => line.startsWith('data:')).flatMap((line) => {
      try {
        return [JSON.parse(line.slice(5))];
      } catch {
        return [];
      }
    }),
  );
}

const baseBody = (text, spec, extra = {}) => ({
  text,
  sender: 'User',
  clientTimestamp: new Date().toISOString(),
  isCreatedByUser: true,
  parentMessageId: '00000000-0000-0000-0000-000000000000',
  conversationId: null,
  messageId: crypto.randomUUID(),
  error: false,
  endpoint: 'agents',
  ...(spec ? { spec } : {}),
  isTemporary: false,
  ...extra,
});

const start = (token, body) => api('/api/agents/chat/agents', { token, method: 'POST', body });

/** Reads the first frame of the resume stream: the state a reconnecting client is handed. */
async function resumeFrame(token, streamId) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const res = await fetch(`${BASE}/api/agents/chat/stream/${encodeURIComponent(streamId)}?resume=true`, {
      headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream', 'User-Agent': UA },
      signal: controller.signal,
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return buffer;
      buffer += decoder.decode(value, { stream: true });
      if (buffer.includes('"sync"') && buffer.includes('\n\n')) return buffer;
    }
  } catch {
    return '';
  } finally {
    clearTimeout(timer);
    controller.abort();
  }
}

/**
 * What a customer can read while a turn runs: after the library call its first usage record is stored, and the mock
 * then streams slowly, so the status route and a reconnect both hand out the job's state. The turn is stopped after.
 */
async function midTurnReads(token) {
  const text = `CALL_TOOL:get_article:{"number":107} SLOW_STREAM:250 ${nonce('co-midturn')}\nFINAL_TEXT:${'STREAMED_PIECE '.repeat(60)}`;
  const started = await start(token, baseBody(text, 'iqraa-fast'));
  const streamId = started.json?.streamId ?? started.json?.conversationId;
  const subscriber = new AbortController();
  // The job runs for a subscriber, so one stays attached while the routes are read.
  const attached = fetch(`${BASE}/api/agents/chat/stream/${encodeURIComponent(streamId)}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream', 'User-Agent': UA },
    signal: subscriber.signal,
  }).then((res) => res.text()).catch(() => '');
  let status = null;
  const usageSeen = await waitUntil(async () => {
    status = (await api(`/api/agents/chat/status/${encodeURIComponent(streamId)}`, { token })).json;
    return (status?.resumeState?.collectedUsage?.length ?? 0) > 0;
  }, 45_000);
  const resume = await resumeFrame(token, streamId);
  await api('/api/agents/chat/abort', { token, method: 'POST', body: { streamId } });
  subscriber.abort();
  await attached;
  return { status, resume, usageSeen };
}
const code = (res) => `${res.status} ${res.json?.code ?? ''}`.trim();

/** A message attachment (`message_file`), as the chat box sends it; `endpoint` is the form's own field, which the client chooses. */
async function upload(token, name, type, bytes, endpoint = 'agents') {
  const form = new FormData();
  form.append('endpoint', endpoint);
  form.append('file_id', crypto.randomUUID());
  form.append('message_file', 'true');
  form.append('tool_resource', 'context');
  form.append('file', new Blob([bytes], { type }), name);
  const res = await fetch(`${BASE}/api/files`, { method: 'POST', headers: { 'User-Agent': UA, Authorization: `Bearer ${token}` }, body: form });
  const text = await res.text();
  let message = '';
  try {
    message = String(JSON.parse(text)?.message ?? '');
  } catch {
    message = '';
  }
  return { status: res.status, text: text.slice(0, 200), message };
}

export async function scenarioChatOnly(ctx) {
  const { staff, agentId, c1: pro } = ctx;
  const mode = JSON.parse(fs.readFileSync(path.join(HERE, 'iqraa.json'), 'utf8')).grounding.mode;
  const basic = await customer(staff, 'co-basic', { credits: 5, role: 'PLAN_BASIC' });
  const firm = await customer(staff, 'co-firm', { credits: 5, role: 'PLAN_FIRM' });
  const FAST = 'iqraa-fast';

  // (a) only named tiers, and nothing the client sends changes the run
  const plainTag = nonce('co-plain');
  const plain = await start(pro.token, baseBody(`plain ${plainTag}`, undefined, { endpoint: 'MockLLM', model: MODEL }));
  const variants = [];
  const variantTags = [];
  for (const [method, route] of PLAIN_CHAT_VARIANTS) {
    const tag = nonce('co-variant');
    variantTags.push(tag);
    const res = await api(route, { token: pro.token, method, body: baseBody(`variant ${tag}`, undefined, { endpoint: 'MockLLM', model: MODEL }) });
    variants.push({ route: `${method} ${route}`, said: code(res) });
  }
  // A valid tier spec posted to another endpoint segment: the route itself is closed, whatever the body says.
  const mockEndpoint = await api('/api/agents/chat/MockLLM', { token: pro.token, method: 'POST', body: baseBody(`mock endpoint ${nonce('co-me')}`, FAST, { endpoint: 'MockLLM', model: MODEL }) });
  const nonTierSpec = await start(pro.token, baseBody(`invented spec ${nonce('co-ns')}`, 'invented-spec', { endpoint: 'MockLLM', model: MODEL }));
  const forgedTag = nonce('co-forged');
  const forged = await chat({
    token: pro.token,
    agentId,
    spec: FAST,
    text: `forged ${forgedTag}`,
  });
  const attackTag = nonce('co-attack');
  const attackStart = await start(
    pro.token,
    baseBody(`attack ${attackTag}`, FAST, {
      agent_id: 'ephemeral',
      ephemeralAgent: { web_search: true, execute_code: true, file_search: true, mcp: ['browser'] },
      promptPrefix: 'LEAKED_PREFIX_MARKER',
      model: 'attacker-model',
      addedConvo: { endpoint: 'MockLLM', model: 'attacker-model' },
    }),
  );
  await waitUntil(() => callsFor(attackTag).length >= 1, 30_000);
  const attackCalls = callsFor(attackTag);
  const attackTools = [...new Set(attackCalls.flatMap((call) => call.tools ?? []))];
  // After a wait, the plain chats of (a) must still have made no model call at all.
  await sleep(2000);
  const plainCalls = [plainTag, ...variantTags].flatMap((tag) => callsFor(tag));

  // (b) denied routes, the plan role matrix, and the routes the client needs
  const denied = [];
  for (const [method, route, body] of DENIED_ROUTES) {
    const res = await api(route, { token: pro.token, method, body });
    denied.push({ route: `${method} ${route}`, said: code(res) });
  }
  const closed = denied.filter((entry) => entry.said !== '403 IQRAA_FORBIDDEN');
  const open = [];
  for (const [method, route] of OPEN_ROUTES) {
    const res = await api(route, { token: pro.token, method });
    open.push({ route: `${method} ${route}`, status: res.status });
  }
  const role = await api('/api/admin/roles/PLAN_PRO', { token: staff.token });
  const granted = Object.entries(role.json?.role?.permissions ?? {}).flatMap(([type, perms]) =>
    Object.entries(perms ?? {}).filter(([, on]) => on === true).map(([name]) => `${type}.${name}`),
  );

  // (c) the model is not readable
  const spec = await specFor(pro.token, agentId);
  const answered = await turn(pro, agentId, 'co-model', 'CALL_TOOL:get_article:{"number":107}');
  const agentJson = (await api(`/api/agents/${agentId}`, { token: pro.token })).json;
  const modelList = (await api('/api/models', { token: pro.token })).json;
  const convoId = answered.result.conversationId;
  const texts = {
    agent: JSON.stringify(agentJson),
    models: JSON.stringify(modelList),
    final: JSON.stringify(answered.result.final ?? ''),
    stream: (answered.result.stream ?? []).join('\n'),
    convo: JSON.stringify((await api(`/api/convos/${convoId}`, { token: pro.token })).json ?? ''), // includes the title
    messages: JSON.stringify((await api(`/api/messages/${convoId}`, { token: pro.token })).json ?? ''),
  };
  const midTurn = await midTurnReads(pro.token);
  const endpointList = (await api('/api/endpoints', { token: pro.token })).json ?? {};
  const forked = await api('/api/convos/fork', { token: pro.token, method: 'POST', body: { conversationId: convoId, messageId: answered.result.responseId, option: 'directPath' } });
  texts.status = JSON.stringify(midTurn.status ?? '');
  texts.resume = midTurn.resume;
  texts.endpoints = JSON.stringify(endpointList);
  texts.fork = JSON.stringify(forked.json ?? '');
  const leaks = findLeaks(texts, [MODEL, 'MockLLM']);
  // A custom endpoint's provider reads `openAI`, so the name search alone would miss it: the keys are checked too.
  const identity = findIdentityFields({
    stream: framesOf(answered.result.stream ?? []),
    final: answered.result.final ?? null,
    status: midTurn.status ?? null,
    resume: framesOf(midTurn.resume.split('\n\n')),
    fork: forked.json ?? null,
  });

  // (c, failed) the provider refuses the turn in words that name the model (the mock's PROVIDER_ERROR): the customer
  // reads the fork's notice in the stream or the final event, and nothing they can read holds the model or those words.
  const failed = await turn(pro, agentId, 'co-failed', 'PROVIDER_ERROR probe');
  const failedConvo = failed.result.conversationId;
  const failedShown = {
    stream: (failed.result.stream ?? []).join('\n'),
    final: JSON.stringify(failed.result.final ?? ''),
    error: JSON.stringify(failed.result.error ?? ''),
  };
  const failedTexts = {
    ...failedShown,
    convo: failedConvo ? JSON.stringify((await api(`/api/convos/${failedConvo}`, { token: pro.token })).json ?? '') : '',
    messages: failedConvo ? JSON.stringify((await api(`/api/messages/${failedConvo}`, { token: pro.token })).json ?? '') : '',
  };
  const failedLeaks = findLeaks(failedTexts, [MODEL, 'MockLLM', 'quota exceeded']);
  const failedReachedProvider = llmLog().some((entry) => entry.event === 'provider-error' && JSON.stringify(entry.messages ?? []).includes(failed.tag));

  // (d) the citation guard
  const event = async (messageId) => (mongoQuery({ op: 'find', collection: 'iqraa_guard_events', filter: { messageId }, limit: 1 })[0]);
  const bad = await turn(pro, agentId, 'co-bad', 'FINAL_TEXT:نصت المادة 29 من القانون المدني المصري على كذا وكذا.');
  const badEvent = await event(bad.result.responseId);
  const good = await turn(pro, agentId, 'co-good', 'CALL_TOOL:get_article:{"number":107} FINAL_TEXT:تنص المادة 107 من القانون المدني الأردني على أن العربون دليل على العدول.');
  const goodEvent = await event(good.result.responseId);
  const follow = await turn(pro, agentId, 'co-follow', 'FINAL_TEXT:وكما سبق، المادة 107 من القانون المدني الأردني.', {
    conversationId: good.result.conversationId,
    parentMessageId: good.result.responseId,
  });
  const followEvent = await event(follow.result.responseId);
  // The user's own message carries the ungrounded text too (the mock echoes FINAL_TEXT from it): read only the
  // stored response of this turn, and the conversation title, never the whole message list.
  const storedMessages = (await api(`/api/messages/${bad.result.conversationId}`, { token: pro.token })).json;
  const storedResponse = (Array.isArray(storedMessages) ? storedMessages : (storedMessages?.messages ?? [])).find((message) => message.messageId === bad.result.responseId);
  const badConvo = (await api(`/api/convos/${bad.result.conversationId}`, { token: pro.token })).json;
  const storedBadText = JSON.stringify({ response: storedResponse ?? null, title: badConvo?.title ?? '' });

  // (d, stopped) the customer presses Stop after the citation was streamed: the stop route saves and publishes the
  // partial answer, and the guard must have judged it (block: the saved row and the final event hold the fixed text).
  const stopTag = nonce('co-stop');
  const stopped = await chatAndStop({ token: pro.token, agentId, text: stopProbeText(stopTag), marker: 'STREAMED_PIECE', stopAfter: 5 });
  const stoppedId = stopped.final?.responseMessage?.messageId;
  const stoppedEvent = stoppedId ? await event(stoppedId) : undefined;
  const stoppedConvo = stopped.final?.responseMessage?.conversationId ?? stopped.final?.conversation?.conversationId;
  const stoppedMessages = stoppedConvo ? (await api(`/api/messages/${stoppedConvo}`, { token: pro.token })).json : undefined;
  const storedStopped = (Array.isArray(stoppedMessages) ? stoppedMessages : (stoppedMessages?.messages ?? [])).find((message) => message.messageId === stoppedId);
  const storedStoppedText = JSON.stringify(storedStopped ?? null);
  const finalStoppedText = JSON.stringify(stopped.final?.responseMessage ?? null);

  // (e) plans
  const wrongTier = await start(pro.token, baseBody(`expert ${nonce('co-e1')}`, 'iqraa-expert'));
  const basicAdvanced = await start(basic.token, baseBody(`advanced ${nonce('co-e2')}`, 'iqraa-advanced'));
  const basicFast = await turn(basic, agentId, 'co-basic-fast', 'basic plan probe');
  const firmExpert = await chat({ token: firm.token, agentId, spec: 'iqraa-expert', text: `firm ${nonce('co-e3')}` });
  const advancedChat = await chat({ token: firm.token, agentId, spec: 'iqraa-advanced', text: `advanced ${nonce('co-e4')}` });
  const lost = await api(`/api/admin/roles/PLAN_BASIC/members`, { token: staff.token, method: 'POST', body: { userId: firm.id } });
  const afterLoss = await start(
    firm.token,
    baseBody(`after plan loss ${nonce('co-e5')}`, 'iqraa-advanced', {
      conversationId: advancedChat.conversationId,
      parentMessageId: advancedChat.responseId,
    }),
  );
  // The tier the plan still holds does not reopen the conversation: it stays read-only (D3).
  const afterLossOtherTier = await start(
    firm.token,
    baseBody(`other tier after plan loss ${nonce('co-e6')}`, FAST, {
      conversationId: advancedChat.conversationId,
      parentMessageId: advancedChat.responseId,
    }),
  );
  const readable = await api(`/api/messages/${advancedChat.conversationId}`, { token: firm.token });

  // (f) uploads: context only, with limits (PDF, Word and plain text up to 5 MB)
  const wrongType = await upload(pro.token, 'program.exe', 'application/x-msdownload', new Uint8Array(10));
  const tooBig = await upload(pro.token, 'big.txt', 'text/plain', new Uint8Array(6 * 1024 * 1024).fill(97));
  const fine = await upload(pro.token, 'note.txt', 'text/plain', new TextEncoder().encode('ملاحظات العقد: المادة الأولى.'));
  // The type and size limits are looked up by the form's own `endpoint` field: the client chooses it, so the same
  // limits must hold for another value (fileConfig.endpoints.default mirrors them).
  const wrongTypeOther = await upload(pro.token, 'program.exe', 'application/x-msdownload', new Uint8Array(10), 'openAI');
  const tooBigOther = await upload(pro.token, 'big.txt', 'text/plain', new Uint8Array(6 * 1024 * 1024).fill(97), 'openAI');
  // LibreChat's built-in file config has its own entry for `anthropic` (10 files, images included): the yaml spells it out.
  const wrongTypeAnthropic = await upload(pro.token, 'program.exe', 'application/x-msdownload', new Uint8Array(10), 'anthropic');
  const tooBigAnthropic = await upload(pro.token, 'big.txt', 'text/plain', new Uint8Array(6 * 1024 * 1024).fill(97), 'anthropic');

  // (g) starters and footer
  const starters = await api('/api/iqraa/starters', { token: pro.token });
  const staffStarters = await api('/api/iqraa/starters', { token: staff.token });
  const prompts = (starters.json?.areas ?? []).flatMap((area) => area.prompts ?? []);
  // The count is the shipped file's, so editing the prompts does not break the scenario.
  const shippedPrompts = JSON.parse(fs.readFileSync(path.join(HERE, '..', '..', 'content', 'starters', 'starters.ar.json'), 'utf8')).areas.flatMap((area) => area.prompts).length;
  // The shell page holds only a flag; the client prints the footer from /api/config.
  const config = (await api('/api/config', { token: pro.token })).json;

  const blockedExpected = mode === 'block';
  return {
    ...verdict({
      plainChatRefused: check(
        plain.status === 403 && plain.json?.code === 'IQRAA_TIER_REQUIRED' && nonTierSpec.status === 403 && nonTierSpec.json?.code === 'IQRAA_TIER_REQUIRED' &&
          mockEndpoint.status === 403 && mockEndpoint.json?.code === 'IQRAA_FORBIDDEN' && plainCalls.length === 0,
        `plain model chat: ${code(plain)}; non-tier spec: ${code(nonTierSpec)}; MockLLM endpoint: ${code(mockEndpoint)}; model calls for any plain chat: ${plainCalls.length}`,
      ),
      plainChatVariantsRefused: check(variants.every((entry) => entry.said.startsWith('403')), JSON.stringify(variants.filter((entry) => !entry.said.startsWith('403')))),
      tierChatRuns: check(forged.startStatus === 200 && /MOCK_OK/.test(forged.text ?? ''), `start ${forged.startStatus}; reply ${forged.text?.slice(0, 60)}`),
      clientFieldsIgnored: check(
        attackStart.status === 200 && attackCalls.length >= 1 && LIBRARY_TOOLS.every((tool) => attackTools.includes(tool)) &&
          attackTools.every((tool) => LIBRARY_TOOLS.includes(tool) || SKILL_TOOLS.includes(tool)) &&
          attackCalls.every((call) => call.model === MODEL && !carries(call, 'LEAKED_PREFIX_MARKER')),
        `start ${attackStart.status}; calls ${attackCalls.length}; tools ${JSON.stringify(attackTools)}; models ${JSON.stringify([...new Set(attackCalls.map((c) => c.model))])}`,
      ),
      deniedRoutes: check(closed.length === 0, closed.length === 0 ? `${denied.length} routes: 403 IQRAA_FORBIDDEN` : JSON.stringify(closed)),
      openRoutes: check(open.every((entry) => entry.status !== 403), JSON.stringify(open.filter((entry) => entry.status === 403))),
      planRoleMatrix: check(role.status === 200 && JSON.stringify(granted.sort()) === JSON.stringify(['AGENTS.USE', 'MCP_SERVERS.USE']), `granted: ${JSON.stringify(granted)}`),
      modelHiddenInAgentRoutes: check(agentJson?.model === 'iqraa' && agentJson?.provider === 'iqraa' && JSON.stringify(modelList) === '{}' && JSON.stringify(Object.keys(endpointList)) === '["agents"]', `agent ${agentJson?.provider}/${agentJson?.model}; models ${JSON.stringify(modelList)}; endpoints ${JSON.stringify(Object.keys(endpointList))}`),
      modelHiddenInConversation: check(
        leaks.length === 0 && identity.length === 0 && spec === FAST,
        `spec ${spec}; texts holding the model name: ${JSON.stringify(leaks)}; keys naming it: ${JSON.stringify(identity.slice(0, 8))}`,
      ),
      modelProbesRan: check(midTurn.usageSeen && forked.status < 300, `status read with usage: ${midTurn.usageSeen}; fork ${forked.status}`),
      responseStampedWithTier: check(answered.result.final?.responseMessage?.model === 'عقل سريع', `responseMessage.model: ${answered.result.final?.responseMessage?.model}`),
      providerErrorHidden: check(
        failed.result.startStatus === 200 && failedReachedProvider && failedLeaks.length === 0 && Object.values(failedShown).some((text) => text.includes(FAILURE_NOTICE)),
        `start ${failed.result.startStatus}; the mock refused the turn: ${failedReachedProvider}; texts holding the model or the provider's words: ${JSON.stringify(failedLeaks)}; notice shown: ${Object.entries(failedShown).filter(([, text]) => text.includes(FAILURE_NOTICE)).map(([label]) => label).join(',')}; conversation ${failedConvo}`,
      ),
      ungroundedAnswerLogged: check(
        badEvent?.verdict === 'ungrounded' && badEvent.classes?.includes('G-1') && badEvent.mode === mode && badEvent.blocked === blockedExpected,
        `event ${JSON.stringify(badEvent && { verdict: badEvent.verdict, classes: badEvent.classes, mode: badEvent.mode, blocked: badEvent.blocked })}; configured mode ${mode}`,
      ),
      ungroundedAnswerShown: check(
        blockedExpected
          ? bad.result.text === BLOCKED_MESSAGE && Boolean(storedResponse) && !storedBadText.includes('المصري')
          : Boolean(storedResponse) && bad.result.text?.includes('المصري'),
        `mode ${mode}; answer: ${bad.result.text?.slice(0, 80)}; stored response found: ${Boolean(storedResponse)}`,
      ),
      groundedAnswerKept: check(goodEvent?.verdict === 'grounded' && good.result.text?.includes('المادة 107'), `event ${goodEvent?.verdict}; answer: ${good.result.text?.slice(0, 60)}`),
      earlierTurnCounts: check(followEvent?.verdict === 'grounded' && follow.result.text?.includes('المادة 107'), `follow-up event ${followEvent?.verdict}`),
      stoppedAnswerJudged: check(
        stopped.abortStatus === 200 && stopped.ended === true && Boolean(storedStopped) && stoppedEvent?.verdict === 'ungrounded' && stoppedEvent.mode === mode &&
          stoppedEvent.blocked === blockedExpected && storedStopped.model === 'عقل سريع' &&
          (blockedExpected
            ? storedStoppedText.includes(BLOCKED_MESSAGE) && !storedStoppedText.includes('المصري') && finalStoppedText.includes(BLOCKED_MESSAGE) && !finalStoppedText.includes('المصري')
            : storedStoppedText.includes('المصري')),
        `abort ${stopped.abortStatus}, ended ${stopped.ended}; stored row found ${Boolean(storedStopped)}, model ${storedStopped?.model}; event ${JSON.stringify(stoppedEvent && { verdict: stoppedEvent.verdict, blocked: stoppedEvent.blocked })}; mode ${mode}; stored text has the foreign article: ${storedStoppedText.includes('المصري')}; final event has it: ${finalStoppedText.includes('المصري')}`,
      ),
      tierOutsidePlanRefused: check(
        wrongTier.status === 403 && wrongTier.json?.code === 'IQRAA_TIER_NOT_IN_PLAN' && wrongTier.json?.message === NOT_IN_PLAN &&
          basicAdvanced.status === 403 && basicAdvanced.json?.code === 'IQRAA_TIER_NOT_IN_PLAN',
        `pro->expert ${code(wrongTier)}; basic->advanced ${code(basicAdvanced)}`,
      ),
      tiersInPlanRun: check(/MOCK_OK/.test(basicFast.result.text ?? '') && /MOCK_OK/.test(firmExpert.text ?? '') && /MOCK_OK/.test(advancedChat.text ?? ''), `basic fast ${basicFast.result.text?.slice(0, 30)}; firm expert ${firmExpert.text?.slice(0, 30)}`),
      planLossReadOnly: check(lost.status < 300 && afterLoss.status === 403 && afterLoss.json?.code === 'IQRAA_TIER_NOT_IN_PLAN' && afterLossOtherTier.status === 403 && afterLossOtherTier.json?.code === 'IQRAA_TIER_NOT_IN_PLAN' && readable.status === 200, `role change ${lost.status}; send ${code(afterLoss)}; send on another tier ${code(afterLossOtherTier)}; read ${readable.status}`),
      uploadLimits: check(
        // The size limit is multer's: stock LibreChat answers it 500 «File too large», and its client refuses first.
        wrongType.status >= 400 && wrongType.status < 500 && wrongType.message !== '' && tooBig.status >= 400 && fine.status < 400,
        `exe ${wrongType.status} «${wrongType.message}»; 6 MB ${tooBig.status} «${tooBig.message}»; small text ${fine.status} ${fine.text.slice(0, 80)}`,
      ),
      uploadLimitsHoldForAnotherEndpoint: check(
        [wrongTypeOther, wrongTypeAnthropic].every((res) => res.status >= 400 && res.status < 500) && [tooBigOther, tooBigAnthropic].every((res) => res.status >= 400),
        `endpoint openAI: exe ${wrongTypeOther.status} «${wrongTypeOther.message}»; 6 MB ${tooBigOther.status} «${tooBigOther.message}»; endpoint anthropic: exe ${wrongTypeAnthropic.status}; 6 MB ${tooBigAnthropic.status}`,
      ),
      startersServed: check(starters.status === 200 && prompts.length === shippedPrompts && starters.json?.reviewed_by === undefined && starters.json?.staff === false && staffStarters.json?.staff === true, `${prompts.length} prompts; staff flag customer ${starters.json?.staff}, staff ${staffStarters.json?.staff}`),
      footerIsOurs: check(config?.customFooter === FOOTER, `/api/config customFooter: ${JSON.stringify(config?.customFooter)}`),
    }),
  };
}
