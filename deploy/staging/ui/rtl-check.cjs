// Arabic RTL acceptance check (REQ-RTL-001..004), the account label (REQ-AUTH-011) and the sign-in footer
// (REQ-UI-002, O-37). Started by run-rtl-check.mjs inside mcr.microsoft.com/playwright, in the proxy container's
// network namespace. Reads «Iqraa LAW AI» in the sign-in screen's footer before typing, then signs a
// phone-only plan customer in on the fork's code screens (an app code, then a backup code), checks the account
// menu shows the phone and never the placeholder email, asks the specialist the deterministic Arabic demo
// question, waits for the full answer and checks computed styles. INJECT_CSS=<file under /work> adds a candidate
// stylesheet to the live page first. Writes /work/out/rtl-check.json and screenshots; exits 1 on any failed check.
const fs = require('fs');
const { chromium } = require('playwright');
const { nextAppStep, totp } = require('/work/totp.cjs');

// The proxy, reached as localhost. Customers use HTTPS, where the browser labels each request with
// Sec-Fetch-Site and LibreChat's sign-in guard accepts same-origin posts. Chromium sends that header
// only to secure origins: localhost is one, http://proxy:8080 is not (sign-in would be refused).
const BASE = 'http://localhost:8080';
const OUT = '/work/out';
const QUESTION = 'ARABIC_DEMO ما حكم العربون في القانون المدني الأردني؟';
const ANSWER_ONLY = 'أصبح باتًا'; // in the demo answer, not in the question
const LAST_LINE = 'مراجعة محامٍ مختص'; // the demo answer's final line
const BRAND_NAME = 'Iqraa LAW AI'; // the footer on every screen, sign-in included (REQ-UI-002)
const { CUSTOMER_PHONE, CUSTOMER_APP_SECRET, CUSTOMER_APP_LAST_STEP, CUSTOMER_BACKUP_CODE, INJECT_CSS } = process.env;
const LOCAL_PHONE = `0${CUSTOMER_PHONE.slice(4)}`; // +96279… typed the local way, 079…
let lastStep = Number(CUSTOMER_APP_LAST_STEP);

/** A fresh app code. LibreChat's confirm records no step, so waiting after it is harmless, not required. */
async function appCode() {
  const { step, waitMs } = nextAppStep(lastStep);
  if (waitMs > 0) await new Promise((resolve) => setTimeout(resolve, waitMs));
  lastStep = step;
  return totp(CUSTOMER_APP_SECRET, { step });
}

/** Western digits for a label that may print Arabic-Indic ones. */
const digitsOf = (text) => String(text).replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660)).replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0)).replace(/\D/g, '');

/**
 * Signs in on the code screens (plan contract test ids: phone, "use your authenticator app", then an app code or,
 * with `backup`, a backup code) and asks the demo question; `cookieLang` null means a first visit without a cookie.
 */
async function askDemo(browser, { cookieLang, file, backup }) {
  const context = await browser.newContext({ locale: 'en-US', viewport: { width: 1366, height: 900 } });
  if (cookieLang) await context.addCookies([{ name: 'lang', value: cookieLang, url: BASE }]);
  const page = await context.newPage();
  const loginResponses = [];
  page.on('response', async (r) => {
    if (!r.url().includes('/api/iqraa/auth/')) return;
    const h = await r.request().allHeaders();
    loginResponses.push(`${r.request().method()} ${r.url()} ${r.status()} (origin ${h.origin ?? 'absent'}, sec-fetch-site ${h['sec-fetch-site'] ?? 'absent'})`);
  });
  await page.goto(`${BASE}/login`);
  // The sign-in footer (REQ-UI-002, O-37), read before anything is typed. Before sign-in /api/config sends no
  // customFooter, so the name is the fork's own text (hook C16-footer), outside upstream's footer landmark.
  await page.getByTestId('iqraa-identifier').waitFor({ timeout: 30000 });
  await page.getByTestId('iqraa-brand-footer').waitFor({ timeout: 15000 }).catch(() => {});
  const signIn = await page.evaluate(() => {
    const footers = [...document.querySelectorAll('[data-testid="iqraa-brand-footer"]')];
    const el = footers[0];
    const r = el?.getBoundingClientRect();
    const cs = el && getComputedStyle(el);
    return {
      count: footers.length,
      text: el?.textContent ?? null,
      shown: Boolean(r && r.width > 0 && r.height > 0 && cs.visibility === 'visible' && cs.display !== 'none' && Number(cs.opacity) > 0),
      inViewport: Boolean(r && r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth),
      inLandmark: Boolean(el?.closest('[role="contentinfo"]')),
      landmarks: document.querySelectorAll('[role="contentinfo"]').length,
    };
  });
  await page.screenshot({ path: `${OUT}/signin-${file}` });
  await page.getByTestId('iqraa-identifier').fill(LOCAL_PHONE);
  await page.getByTestId('iqraa-use-app').click();
  if (backup) await page.getByTestId('iqraa-use-backup').click();
  await page.getByTestId('iqraa-code').fill(backup ? CUSTOMER_BACKUP_CODE : await appCode());
  await page.getByTestId('iqraa-submit-code').click();
  try {
    await page.waitForURL(/\/c\//, { timeout: 30000 });
  } catch (error) {
    await page.screenshot({ path: `${OUT}/rtl-login-fail-${file}` });
    const alert = await page.locator('[data-testid="iqraa-auth-error"], [role="alert"]').allTextContents().catch(() => []);
    throw new Error(`sign-in did not reach /c/ (at ${page.url()}; auth responses: ${loginResponses.join(', ') || 'none'}; alert: ${alert.join(' | ') || 'none'})`);
  }
  // The default tier (model spec): a landing link naming an agent would send no tier, and the fork's gate refuses that.
  await page.goto(`${BASE}/c/new`);
  const input = page.locator('#prompt-textarea, textarea').first();
  await input.waitFor({ timeout: 30000 });
  // The account menu label (fork AccountLabel): the phone, never the placeholder email.
  await page.getByTestId('nav-user').click();
  // The label shows the fallback until GET /me answers: wait for the phone's digits, then read it.
  await page.waitForFunction(
    () => /[0-9٠-٩۰-۹]{7}/.test(document.querySelector('[data-testid="iqraa-account-label"]')?.textContent ?? ''),
    null,
    { timeout: 15000 },
  );
  const label = (await page.getByTestId('iqraa-account-label').textContent()) ?? '';
  const placeholderOnPage = (await page.locator('body').innerText()).includes('phone.iqraa.invalid');
  await page.keyboard.press('Escape');
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
    // Each message's text sits in upstream's Container, marked data-message-text (it was .text-message before
    // LibreChat f4154b649); a customer's answer is wrapped whole in the fork's [data-iqraa-answer] (IqraaAnswer).
    const answers = [...document.querySelectorAll('[data-iqraa-answer]')];
    const messages = [...document.querySelectorAll('[data-message-text]')];
    const answer = answers[answers.length - 1] ?? messages[messages.length - 1];
    const quote = answer?.querySelector('.markdown blockquote');
    const quoteP = quote?.querySelector('p');
    const list = answer?.querySelector('.markdown ol');
    const para = [...(answer?.querySelectorAll('.markdown p') ?? [])].find((p) => p.textContent.includes(answerOnly));
    const code = answer?.querySelector('.markdown li code');
    // The question's own text, inside the customer's last turn (packages/chat MessageRow marks it .user-turn).
    const turns = [...document.querySelectorAll('.user-turn')];
    const userTurn = turns[turns.length - 1];
    const user = [...(userTurn?.querySelectorAll('[data-message-text] *') ?? [])].find((el) => el.childElementCount === 0 && el.textContent.includes('ما حكم العربون'));
    return {
      answerSource: answers.length ? 'data-iqraa-answer' : messages.length ? 'data-message-text' : 'none',
      answerCount: answers.length,
      html: { dir: document.documentElement.dir, lang: document.documentElement.lang },
      quote: quote && { left: css(quote).borderLeftWidth, right: css(quote).borderRightWidth, before: css(quoteP, '::before')?.content, after: css(quoteP, '::after')?.content },
      list: list && { direction: css(list).direction, paddingLeft: css(list).paddingLeft, paddingRight: css(list).paddingRight },
      para: para && { hasAnswerOnly: para.textContent.includes(answerOnly), unicodeBidi: css(para).unicodeBidi, direction: css(para).direction },
      code: code && { text: code.textContent, unicodeBidi: css(code).unicodeBidi, direction: css(code).direction },
      user: user && { tag: user.tagName, className: String(user.className), text: user.textContent.slice(0, 40), unicodeBidi: css(user).unicodeBidi },
    };
  }, { answerOnly: ANSWER_ONLY });
  await context.close();
  return { ...measured, signIn, account: { label, placeholderOnPage } };
}

const px = (value) => Number.parseFloat(value ?? '0');
const noQuote = (content) => content === 'none' || content === 'normal' || content === '""';

(async () => {
  const report = { injected: INJECT_CSS ?? null, checks: {} };
  const browser = await chromium.launch();
  try {
    const ar = await askDemo(browser, { cookieLang: null, file: 'rtl-ar.png', backup: false });
    const en = await askDemo(browser, { cookieLang: 'en-US', file: 'rtl-en.png', backup: true });
    report.measured = { ar, en };
    const check = (name, ok, detail) => (report.checks[name] = { ok: Boolean(ok), detail });
    // The checks below measure the fork's answer: the upstream message fallback would measure another element.
    check('answerFound', ar.answerSource === 'data-iqraa-answer', JSON.stringify({ source: ar.answerSource, count: ar.answerCount }));
    check('htmlRtlByDefault', ar.html.dir === 'rtl' && ar.html.lang === 'ar', JSON.stringify(ar.html));
    check('blockquoteBarOnRight', ar.quote && px(ar.quote.right) > 0 && px(ar.quote.left) === 0, JSON.stringify(ar.quote));
    check('noCssQuoteMarks', ar.quote && noQuote(ar.quote.before) && noQuote(ar.quote.after), JSON.stringify(ar.quote));
    check('listOnRight', ar.list && ar.list.direction === 'rtl' && px(ar.list.paddingRight) > 0 && px(ar.list.paddingLeft) === 0, JSON.stringify(ar.list));
    check('blocksPlaintext', ar.para?.unicodeBidi === 'plaintext' && ar.user?.unicodeBidi === 'plaintext', JSON.stringify({ para: ar.para, user: ar.user }));
    check('inlineCodeIsolated', ar.code?.unicodeBidi === 'isolate' && ar.code?.direction === 'ltr', JSON.stringify(ar.code));
    check('englishUiLtr', en.html.dir === 'ltr' && en.para?.unicodeBidi === 'plaintext', JSON.stringify({ html: en.html, para: en.para }));
    check('accountLabelIsThePhone', [ar, en].every((m) => digitsOf(m.account.label).endsWith(CUSTOMER_PHONE.slice(-9)) && !m.account.label.includes('phone.iqraa.invalid') && !m.account.placeholderOnPage), JSON.stringify([ar.account, en.account]));
    // A FAIL here on a stack that otherwise passes means its image predates the fork's hook C16-footer.
    check('signInShowsName', [ar, en].every((m) => m.signIn.count === 1 && m.signIn.text === BRAND_NAME && m.signIn.shown && m.signIn.inViewport && !m.signIn.inLandmark && m.signIn.landmarks <= 1), JSON.stringify([ar.signIn, en.signIn]));
  } catch (error) {
    report.error = String(error.stack ?? error);
  } finally {
    await browser.close();
  }
  report.pass = !report.error && Object.values(report.checks).length === 10 && Object.values(report.checks).every((c) => c.ok);
  fs.writeFileSync(`${OUT}/rtl-check.json`, JSON.stringify(report, null, 2));
  for (const [name, c] of Object.entries(report.checks)) console.log(`${c.ok ? 'ok  ' : 'FAIL'} ${name}: ${c.detail}`);
  if (report.error) console.log(`error: ${report.error}`);
  console.log(report.pass ? 'RTL PASS' : 'RTL FAIL');
  process.exit(report.pass ? 0 : 1);
})();
