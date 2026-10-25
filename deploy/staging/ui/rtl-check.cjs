// Arabic RTL acceptance check (REQ-RTL-001..004). Started by run-rtl-check.mjs inside
// mcr.microsoft.com/playwright, in the proxy container's network namespace. Signs in a fresh plan
// customer, asks the specialist the deterministic Arabic demo question, waits for the full answer and
// checks computed styles. INJECT_CSS=<file under /work> adds a candidate stylesheet to the live page first.
// Writes /work/out/rtl-check.json and screenshots; exits 1 on any failed check.
const fs = require('fs');
const crypto = require('crypto');
const { chromium } = require('playwright');

// The proxy, reached as localhost. Customers use HTTPS, where the browser labels each request with
// Sec-Fetch-Site and LibreChat's sign-in guard accepts same-origin posts. Chromium sends that header
// only to secure origins: localhost is one, http://proxy:8080 is not (sign-in would be refused).
const BASE = 'http://localhost:8080';
const OUT = '/work/out';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';
const QUESTION = 'ARABIC_DEMO ما حكم العربون في القانون المدني الأردني؟';
const ANSWER_ONLY = 'أصبح باتًا'; // in the demo answer, not in the question
const LAST_LINE = 'مراجعة محامٍ مختص'; // the demo answer's final line
const { STAFF_EMAIL, STAFF_PASSWORD, AGENT_ID, INJECT_CSS } = process.env;

async function api(path, { token, method = 'GET', body } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: { 'User-Agent': UA, ...(body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, json: await res.json().catch(() => null) };
}

function ensure(response, what) {
  if (response.status >= 300) throw new Error(`${what} failed: HTTP ${response.status}`);
  return response;
}

async function makeCustomer() {
  const staff = ensure(await api('/api/auth/login', { method: 'POST', body: { email: STAFF_EMAIL, password: STAFF_PASSWORD } }), 'staff login');
  const suffix = crypto.randomBytes(4).toString('hex');
  const account = { name: 'عميل تجريبي', username: `rtl_${suffix}`, email: `rtl.${suffix}@example.test`, password: crypto.randomBytes(12).toString('base64url') + 'aA1!' };
  ensure(await api('/api/auth/register', { method: 'POST', body: { ...account, confirm_password: account.password } }), 'register');
  const login = ensure(await api('/api/auth/login', { method: 'POST', body: { email: account.email, password: account.password } }), 'customer login');
  const userId = login.json?.user?.id ?? login.json?.user?._id;
  ensure(await api('/api/admin/roles/PLAN_PRO/members', { token: staff.json.token, method: 'POST', body: { userId } }), 'plan membership');
  ensure(await api(`/api/iqraa/admin/wallets/${userId}/grant`, { token: staff.json.token, method: 'POST', body: { amount: 5, ref: `rtl-${suffix}` } }), 'credit grant');
  return account;
}

/** Signs in and asks the demo question; `cookieLang` null means a first visit without a cookie. */
async function askDemo(browser, account, { cookieLang, file }) {
  const context = await browser.newContext({ locale: 'en-US', viewport: { width: 1366, height: 900 } });
  if (cookieLang) await context.addCookies([{ name: 'lang', value: cookieLang, url: BASE }]);
  const page = await context.newPage();
  const loginResponses = [];
  page.on('response', async (r) => {
    if (!r.url().includes('/api/auth/login')) return;
    const h = await r.request().allHeaders();
    loginResponses.push(`${r.request().method()} ${r.url()} ${r.status()} (origin ${h.origin ?? 'absent'}, sec-fetch-site ${h['sec-fetch-site'] ?? 'absent'})`);
  });
  await page.goto(`${BASE}/login`);
  await page.locator('input[name="email"]').fill(account.email);
  await page.locator('input[name="password"]').fill(account.password);
  await page.locator('button[type="submit"]').first().click();
  try {
    await page.waitForURL(/\/c\//, { timeout: 30000 });
  } catch (error) {
    await page.screenshot({ path: `${OUT}/rtl-login-fail-${file}` });
    const alert = await page.locator('[role="alert"]').allTextContents().catch(() => []);
    throw new Error(`sign-in did not reach /c/ (at ${page.url()}; auth responses: ${loginResponses.join(', ') || 'none'}; alert: ${alert.join(' | ') || 'none'})`);
  }
  await page.goto(`${BASE}/c/new?agent_id=${encodeURIComponent(AGENT_ID)}`);
  const input = page.locator('#prompt-textarea, textarea').first();
  await input.waitFor({ timeout: 30000 });
  // After the app has settled (injecting during its client-side navigation fails).
  if (INJECT_CSS) await page.addStyleTag({ content: fs.readFileSync(INJECT_CSS, 'utf8') });
  await input.fill(QUESTION);
  await input.press('Enter');
  // The answer streams in pieces: wait for its last line and its inline code before measuring.
  await page.getByText(LAST_LINE).first().waitFor({ timeout: 90000 });
  await page.locator('.markdown li code').first().waitFor({ timeout: 30000 });
  await page.screenshot({ path: `${OUT}/${file}`, fullPage: false });
  const measured = await page.evaluate(({ answerOnly }) => {
    const css = (el, pseudo) => (el ? getComputedStyle(el, pseudo ?? null) : null);
    const messages = [...document.querySelectorAll('.text-message')];
    const answer = messages[messages.length - 1];
    const quote = answer?.querySelector('.markdown blockquote');
    const quoteP = quote?.querySelector('p');
    const list = answer?.querySelector('.markdown ol');
    const para = [...(answer?.querySelectorAll('.markdown p') ?? [])].find((p) => p.textContent.includes(answerOnly));
    const code = answer?.querySelector('.markdown li code');
    const user = [...document.querySelectorAll('.text-message *')].find((el) => el.childElementCount === 0 && el.textContent.includes('ما حكم العربون'));
    return {
      html: { dir: document.documentElement.dir, lang: document.documentElement.lang },
      quote: quote && { left: css(quote).borderLeftWidth, right: css(quote).borderRightWidth, before: css(quoteP, '::before')?.content, after: css(quoteP, '::after')?.content },
      list: list && { direction: css(list).direction, paddingLeft: css(list).paddingLeft, paddingRight: css(list).paddingRight },
      para: para && { hasAnswerOnly: para.textContent.includes(answerOnly), unicodeBidi: css(para).unicodeBidi, direction: css(para).direction },
      code: code && { text: code.textContent, unicodeBidi: css(code).unicodeBidi, direction: css(code).direction },
      user: user && { tag: user.tagName, className: String(user.className), text: user.textContent.slice(0, 40), unicodeBidi: css(user).unicodeBidi },
    };
  }, { answerOnly: ANSWER_ONLY });
  await context.close();
  return measured;
}

const px = (value) => Number.parseFloat(value ?? '0');
const noQuote = (content) => content === 'none' || content === 'normal' || content === '""';

(async () => {
  const report = { injected: INJECT_CSS ?? null, checks: {} };
  const browser = await chromium.launch();
  try {
    const account = await makeCustomer();
    const ar = await askDemo(browser, account, { cookieLang: null, file: 'rtl-ar.png' });
    const en = await askDemo(browser, account, { cookieLang: 'en-US', file: 'rtl-en.png' });
    report.measured = { ar, en };
    const check = (name, ok, detail) => (report.checks[name] = { ok: Boolean(ok), detail });
    check('htmlRtlByDefault', ar.html.dir === 'rtl' && ar.html.lang === 'ar', JSON.stringify(ar.html));
    check('blockquoteBarOnRight', ar.quote && px(ar.quote.right) > 0 && px(ar.quote.left) === 0, JSON.stringify(ar.quote));
    check('noCssQuoteMarks', ar.quote && noQuote(ar.quote.before) && noQuote(ar.quote.after), JSON.stringify(ar.quote));
    check('listOnRight', ar.list && ar.list.direction === 'rtl' && px(ar.list.paddingRight) > 0 && px(ar.list.paddingLeft) === 0, JSON.stringify(ar.list));
    check('blocksPlaintext', ar.para?.unicodeBidi === 'plaintext' && ar.user?.unicodeBidi === 'plaintext', JSON.stringify({ para: ar.para, user: ar.user }));
    check('inlineCodeIsolated', ar.code?.unicodeBidi === 'isolate' && ar.code?.direction === 'ltr', JSON.stringify(ar.code));
    check('englishUiLtr', en.html.dir === 'ltr' && en.para?.unicodeBidi === 'plaintext', JSON.stringify({ html: en.html, para: en.para }));
  } catch (error) {
    report.error = String(error.stack ?? error);
  } finally {
    await browser.close();
  }
  report.pass = !report.error && Object.values(report.checks).length === 7 && Object.values(report.checks).every((c) => c.ok);
  fs.writeFileSync(`${OUT}/rtl-check.json`, JSON.stringify(report, null, 2));
  for (const [name, c] of Object.entries(report.checks)) console.log(`${c.ok ? 'ok  ' : 'FAIL'} ${name}: ${c.detail}`);
  if (report.error) console.log(`error: ${report.error}`);
  console.log(report.pass ? 'RTL PASS' : 'RTL FAIL');
  process.exit(report.pass ? 0 : 1);
})();
