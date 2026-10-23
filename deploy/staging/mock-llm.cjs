// Staging mock model: an OpenAI-compatible chat-completions server for the Iqraa acceptance scenarios.
// Never contacts a real provider. Every request is logged to /out/llm-requests.jsonl.
//
// Behaviour (decided from the request):
//   - conversation-title request           -> "MOCK_TITLE" (directives below are ignored), logged title:true
//   - last message is a tool result        -> final text "TOOL_RESULT_SEEN: <first 300 chars>"
//   - last user text has CALL_TOOL:<name>:<json args>
//                                          -> one tool call to the advertised tool whose name contains <name>
//   - last user text has ARABIC_DEMO       -> a fixed Arabic legal answer (UI checks)
//   - otherwise                            -> "MOCK_OK: <first 60 chars of the user text>"
//   - FLAKY_ONCE:<nonce>                   -> the first request carrying <nonce> fails with HTTP 500
//   - NO_USAGE                             -> no usage chunk even when stream_options.include_usage is set
// Streaming responses end with a usage chunk when stream_options.include_usage is set.

const http = require('http');
const fs = require('fs');
const crypto = require('crypto');

const PORT = 8080;
const LOG = '/out/llm-requests.jsonl';
const flakySeen = new Set();

function log(entry) {
  fs.appendFileSync(LOG, JSON.stringify({ ts: new Date().toISOString(), ...entry }) + '\n');
}

function textOf(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) return content.map((p) => (typeof p === 'string' ? p : p?.text ?? '')).join('');
  return '';
}

// The current turn is everything after the last assistant message. LibreChat appends more than the
// user's text there: primed and loaded skill bodies and step-budget notices arrive as user messages,
// after tool results when a tool ran.
function currentTurn(messages) {
  const list = Array.isArray(messages) ? messages : [];
  const lastAssistant = list.map((m) => m.role).lastIndexOf('assistant');
  const turn = list.slice(lastAssistant + 1);
  return {
    toolRan: turn.some((m) => m.role === 'tool'),
    text: turn.filter((m) => m.role !== 'system').map((m) => textOf(m.content)).join('\n'),
    userText: turn.filter((m) => m.role === 'user').map((m) => textOf(m.content)).join('\n'),
  };
}

function decide(body) {
  const turn = currentTurn(body.messages);
  const tools = (body.tools ?? []).map((t) => t?.function?.name).filter(Boolean);
  if (turn.toolRan) {
    return { kind: 'text', text: `TOOL_RESULT_SEEN: ${turn.text.slice(0, 300)}` };
  }
  const userText = turn.userText;
  const match = userText.match(/CALL_TOOL:([A-Za-z0-9_.-]+):(\{.*\})/s);
  if (match) {
    const wanted = match[1];
    const name = tools.find((t) => t === wanted) ?? tools.find((t) => t.includes(wanted));
    if (name) return { kind: 'tool', name, args: match[2] };
    return { kind: 'text', text: `MOCK_NO_SUCH_TOOL: ${wanted} (advertised: ${tools.join(', ')})` };
  }
  if (userText.includes('ARABIC_DEMO')) {
    return {
      kind: 'text',
      text: [
        '## الخلاصة',
        'العربون في القانون المدني الأردني دليل على أن العقد أصبح باتًا، ما لم يُتفق على غير ذلك.',
        '',
        '## النصوص المطبقة',
        '> **المادة 107** من القانون المدني الأردني رقم 43 لسنة 1976: «نص تجريبي لأغراض الاختبار فقط».',
        '',
        '1. الوقائع: اتفق الطرفان بتاريخ 2026/10/23 على بيع عقار بثمن 150,000 دينار.',
        '2. المسألة القانونية: هل يجوز العدول عن العقد مقابل التخلي عن العربون؟',
        '3. التحليل: يُرجع إلى `shard-map.json` للتحقق من رقم المادة (Article 107).',
        '',
        'تنبيه: يتطلب الاستخدام المهني مراجعة محامٍ مختص.',
      ].join('\n'),
    };
  }
  return { kind: 'text', text: `MOCK_OK: ${userText.slice(0, 60)}` };
}

// LibreChat's title prompt asks for "a concise, 5-word-or-less title for the conversation".
function isTitleRequest(body) {
  const tools = body.tools ?? [];
  const all = (body.messages ?? []).map((m) => textOf(m.content)).join('\n');
  return tools.length === 0 && /title for the conversation/i.test(all);
}

function usageFor(body, outputText) {
  const promptTokens = Math.max(1, Math.ceil(JSON.stringify(body.messages ?? []).length / 4));
  const completionTokens = Math.max(1, Math.ceil(outputText.length / 4));
  return { prompt_tokens: promptTokens, completion_tokens: completionTokens, total_tokens: promptTokens + completionTokens };
}

function sse(res, obj) {
  res.write(`data: ${JSON.stringify(obj)}\n\n`);
}

const server = http.createServer((req, res) => {
  let raw = '';
  req.on('data', (c) => (raw += c));
  req.on('end', () => {
    if (req.method === 'GET' && req.url.startsWith('/v1/models')) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ object: 'list', data: [{ id: 'mock-model', object: 'model' }] }));
      return;
    }
    if (req.method !== 'POST' || !req.url.startsWith('/v1/chat/completions')) {
      res.writeHead(404);
      res.end();
      return;
    }
    let body = {};
    try {
      body = JSON.parse(raw || '{}');
    } catch {
      res.writeHead(400);
      res.end('bad json');
      return;
    }
    const title = isTitleRequest(body);
    const lastUserText = currentTurn(body.messages).userText;
    // Scenario 10: the first request carrying FLAKY_ONCE:<nonce> fails, so the provider client retries
    // within the same model call; metering must still charge exactly once. Keyed on the nonce so the
    // later title request for the same conversation is not failed as well.
    const flaky = title ? null : lastUserText.match(/FLAKY_ONCE:([A-Za-z0-9-]+)/);
    if (flaky && !flakySeen.has(flaky[1])) {
      flakySeen.add(flaky[1]);
      log({ event: 'flaky-500', nonce: flaky[1] });
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: { message: 'transient upstream error', type: 'server_error' } }));
      return;
    }
    const decision = title ? { kind: 'text', text: 'MOCK_TITLE' } : decide(body);
    const outputText = decision.kind === 'text' ? decision.text : decision.args;
    const usage = usageFor(body, outputText);
    const sendUsage = !!body.stream_options?.include_usage && !(!title && lastUserText.includes('NO_USAGE'));
    log({
      title,
      sentUsage: body.stream ? sendUsage : true,
      stream: !!body.stream,
      includeUsage: !!body.stream_options?.include_usage,
      model: body.model,
      maxTokens: body.max_tokens ?? body.max_completion_tokens ?? null,
      tools: (body.tools ?? []).map((t) => t?.function?.name),
      decision,
      usage,
      messages: body.messages,
    });
    const id = 'chatcmpl-' + crypto.randomUUID();
    const created = Math.floor(Date.now() / 1000);
    const base = { id, object: 'chat.completion.chunk', created, model: body.model };

    if (!body.stream) {
      const message =
        decision.kind === 'text'
          ? { role: 'assistant', content: decision.text }
          : {
              role: 'assistant',
              content: null,
              tool_calls: [{ id: 'call_' + crypto.randomUUID().slice(0, 8), type: 'function', function: { name: decision.name, arguments: decision.args } }],
            };
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          id,
          object: 'chat.completion',
          created,
          model: body.model,
          choices: [{ index: 0, message, finish_reason: decision.kind === 'text' ? 'stop' : 'tool_calls' }],
          usage,
        }),
      );
      return;
    }

    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
    sse(res, { ...base, choices: [{ index: 0, delta: { role: 'assistant', content: '' }, finish_reason: null }] });
    if (decision.kind === 'text') {
      for (const piece of decision.text.match(/.{1,20}/gs) ?? ['']) {
        sse(res, { ...base, choices: [{ index: 0, delta: { content: piece }, finish_reason: null }] });
      }
      sse(res, { ...base, choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] });
    } else {
      const callId = 'call_' + crypto.randomUUID().slice(0, 8);
      sse(res, {
        ...base,
        choices: [{ index: 0, delta: { tool_calls: [{ index: 0, id: callId, type: 'function', function: { name: decision.name, arguments: decision.args } }] }, finish_reason: null }],
      });
      sse(res, { ...base, choices: [{ index: 0, delta: {}, finish_reason: 'tool_calls' }] });
    }
    if (sendUsage) {
      sse(res, { ...base, choices: [], usage });
    }
    res.write('data: [DONE]\n\n');
    res.end();
  });
});

server.listen(PORT, '0.0.0.0', () => log({ event: 'mock-llm listening', port: PORT }));
