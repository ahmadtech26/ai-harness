// Screen pass of the customer interface: the screens and states listed in the sections below (not every one a customer
// can reach: see «Not opened»), in four runs (desktop 1440x900 and phone 390x844 with touch, each in the light and
// the dark theme), with a screenshot of each and a text census.
// Started by run-screen-pass.mjs inside mcr.microsoft.com/playwright, in the proxy container's network namespace, like
// rtl-check.cjs (the browser opens the proxy as http://localhost:8080, a secure origin, so sign-in posts carry
// Sec-Fetch-Site).
//
// One phone-only plan customer with an authenticator app (run-screen-pass.mjs makes it). Each run signs in on the
// fork's code screens with a fresh app code, after showing the sign-in states: the signed-out redirect, phone entry,
// the footer, code entry, backup-code entry and ONE wrong code (four per pass; ten lock the identifier for 15 minutes,
// README «Sign-in on staging»). It never presses «send code» (that spends the per-identifier code requests, and the
// browser cannot read the sink). The theme is the operating system's (the client's default «system»), set per run with
// the context's colorScheme; nothing in the customer's settings is changed except: a renamed and a pinned chat, a
// deleted chat, the composer's thinking choice (put back), «delete all chats» (twice per run, so the next run starts
// with an empty sidebar), an archived chat (taken back), a small text file uploaded and the interface language
// (English, then Arabic again; a step that stops in English drops the choice, so the run goes on in Arabic). Every
// run that signs in logs out at its end, a partial one (IQRAA_PASS_ONLY) too.
//
// Not opened (each needs its own state first): a fork carried out, an edited question saved and sent, a file sent with
// a question, the phone and email change flows past their first screen, the staff screens.
//
// The census of each screenshot lists the visible text nodes and the labels (placeholder, aria-label, title, alt,
// screen-reader text) that contain Latin letters, classified by screen-pass.lib.cjs (the brand, model ids, code, the
// model's answer text and the customer's own words are not interface text), and dir, lang and the computed direction of
// the main containers. Output in /pass (IQRAA_PASS_DIR on the host): shots/<viewport>-<theme>-<nn>-<slug>.png,
// census.json, screens.json, findings.json (this pass's findings; entries with "source": "review" are kept),
// known-items.json and arabic-texts.json. A step whose control is not found is recorded as not reached, with a
// screenshot, and the pass goes on; the exit status is 1 when any step was not reached.
//
// IQRAA_PASS_ONLY=desktop-light[,phone-dark][:landing,composer] runs only those runs and sections (sign-in and log
// out always).
const fs = require('fs');
const { chromium } = require('playwright');
const { nextAppStep, stepOf, totp } = require('/work/totp.cjs');
const lib = require('/work/ui/screen-pass.lib.cjs');

const BASE = 'http://localhost:8080';
const PASS = '/pass';
const SHOTS = `${PASS}/shots`;
const QUESTION = 'ARABIC_DEMO ما حكم العربون في القانون المدني الأردني؟';
const LAST_LINE = 'مراجعة محامٍ مختص'; // the demo answer's final line
const LIBRARY_QUESTION = 'TOOL_ROUNDS:3 ما شروط العربون في القانون المدني؟'; // the mock calls search_law three times
const SHORT_QUESTION = 'سؤال قصير سيُحذف';
const TYPED = 'ما حكم العربون إذا عدل المشتري؟';
const RENAMED = 'محادثة العربون المعاد تسميتها';
const { CUSTOMER_PHONE, CUSTOMER_APP_SECRET, CUSTOMER_APP_LAST_STEP, AUTHENTICATOR_LABEL = '', IQRAA_PASS_ONLY = '' } = process.env;
const LOCAL_PHONE = `0${CUSTOMER_PHONE.slice(4)}`; // +96279… typed the local way, 079…
let lastStep = Number(CUSTOMER_APP_LAST_STEP);

const VIEWPORTS = {
  desktop: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
  phone: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
};
const RUNS = ['desktop-light', 'desktop-dark', 'phone-light', 'phone-dark'];
// `more` runs after the clean-up's «delete all chats» and before log out, so the screens it adds never renumber the others.
const SECTIONS = ['landing', 'composer', 'answer', 'conversation', 'header', 'account', 'settings', 'routes', 'cleanup', 'more'];
const [onlyRuns, onlySections] = IQRAA_PASS_ONLY.split(':');
const runs = onlyRuns ? RUNS.filter((run) => onlyRuns.split(',').includes(run)) : RUNS;
const sections = onlySections ? SECTIONS.filter((s) => onlySections.split(',').includes(s)) : SECTIONS;

const entries = []; // census, one per screenshot
const screens = [];
const notReached = [];
const arabic = new Map(); // visible Arabic text -> how often, on how many screenshots, the first three of them
const apiFailures = new Map();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** A fresh app code; a code's 30 s step is accepted once, so a second sign-in waits for the next step. */
async function appCode() {
  const { step, waitMs } = nextAppStep(lastStep);
  if (waitMs > 0) await sleep(waitMs);
  lastStep = step;
  return totp(CUSTOMER_APP_SECRET, { step });
}

/** Six digits that are not the app code of this step or the next: the wrong code of the error state. */
function wrongCode() {
  const now = stepOf();
  const valid = new Set([now - 1, now, now + 1, now + 2].map((step) => totp(CUSTOMER_APP_SECRET, { step })));
  return ['000000', '111111', '222222', '333333'].find((code) => !valid.has(code));
}

// ------------------------------------------------------------------ the census, collected in the browser

/**
 * Runs in the page: the tier heading (SplitText). Its screen-reader copy is the text; the drawn units are its innermost
 * elements (the fork's WordFade: one per word; the stock SplitText: one per letter). `clipped` lists the units the
 * paragraph's overflow cuts off at this instant: a word rising into an overflow-hidden line loses its lower half, and
 * Arabic letters whose tails and dots sit below the line then read apart («عقل سرىع») although every word is whole.
 */
function headingFacts() {
  const shown = (el) => el.getClientRects().length > 0 && (!el.checkVisibility || el.checkVisibility({ opacityProperty: true, visibilityProperty: true }));
  const h = [...document.querySelectorAll('.split-parent')].find(shown);
  if (!h) return null;
  const leaves = [...h.querySelectorAll('*')].filter((el) => !el.closest('.sr-only') && el.childElementCount === 0 && el.textContent.trim());
  const style = getComputedStyle(h);
  const box = h.getBoundingClientRect();
  const clips = /hidden|clip/.test(`${style.overflow} ${style.overflowY}`);
  return {
    text: (h.querySelector(':scope > .sr-only')?.textContent ?? h.textContent).replace(/\s+/g, ' ').trim(),
    unitTexts: leaves.map((el) => el.textContent),
    letterSpacing: style.letterSpacing,
    unitDisplay: leaves[0] ? getComputedStyle(leaves[0]).display : '',
    opacities: leaves.slice(0, 6).map((el) => Number(getComputedStyle(el).opacity).toFixed(2)),
    transforms: leaves.slice(0, 6).map((el) => getComputedStyle(el).transform),
    clipped: clips
      ? leaves
          .filter((el) => {
            const r = el.getBoundingClientRect();
            return r.bottom > box.bottom + 0.5 || r.top < box.top - 0.5;
          })
          .map((el) => el.textContent)
      : [],
    font: style.fontFamily.split(',')[0],
    fontsReady: document.fonts?.status ?? '',
  };
}

/** Runs in the page: raw facts only (screen-pass.lib.cjs decides). Self-contained: no closure reaches the page. */
function collect() {
  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
    return el.getClientRects().length > 0;
  };
  const srOnly = (el) => {
    if (el.closest('.sr-only')) return true;
    const r = el.getBoundingClientRect();
    return r.width <= 1 && r.height <= 1 && el.getClientRects().length > 0;
  };
  const testids = (el) => {
    const out = [];
    for (let cur = el; cur && out.length < 3; cur = cur.parentElement) {
      const id = cur.getAttribute?.('data-testid');
      if (id) out.push(id);
    }
    return out;
  };
  const inView = (el) => {
    const r = el.getBoundingClientRect();
    return r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
  };
  const facts = (el) => ({
    // A <pre> is code only in an answer's turn: the error page prints its English message in a bare one.
    inCodeElement: !!el.closest('code, kbd, samp'),
    inPre: !!el.closest('pre'),
    inAgentTurn: !!el.closest('[data-iqraa-answer], .agent-turn'),
    inBrand: !!el.closest('[data-testid="iqraa-wordmark"], [data-testid="iqraa-brand-footer"]'),
    inAnswerText: !!el.closest('.markdown, .prose') && !!el.closest('[data-iqraa-answer], .agent-turn'),
    // The message's own text, not the turn's controls, attachment chips or read-out heading.
    inUserMessage: !!el.closest('.user-turn [data-message-text]'),
    inToast: !!el.closest('.toast-root, [data-sonner-toast]'),
    inLanguageList: !!el.closest('[role="option"]') && /العربية/.test(el.closest('[role="listbox"]')?.textContent ?? '') && /English/.test(el.closest('[role="listbox"]')?.textContent ?? ''),
    inView: inView(el),
    tag: el.tagName.toLowerCase(),
    role: el.closest('[role]')?.getAttribute('role') ?? '',
    testids: testids(el),
  });
  const texts = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent.replace(/\s+/g, ' ').trim();
    const el = node.parentElement;
    if (!text || !el || el.closest('script, style, noscript, template')) continue;
    const sr = srOnly(el);
    if (!sr && !visible(el)) continue;
    texts.push({ text: text.slice(0, 300), kind: sr ? 'sr-only' : 'text', ...facts(el) });
  }
  const attributes = [];
  for (const el of document.querySelectorAll('[placeholder], [aria-label], [title], img[alt], [aria-description]')) {
    if (!visible(el) && !srOnly(el)) continue;
    for (const attr of ['placeholder', 'aria-label', 'title', 'alt', 'aria-description']) {
      const value = el.getAttribute(attr);
      if (value && value.trim()) attributes.push({ text: value.trim().slice(0, 300), attr, ...facts(el) });
    }
  }
  // Screen-reader text that is not a text node of its own: the composer's hint is one (packages/chat Hints.tsx).
  for (const el of document.querySelectorAll('.sr-only')) {
    const text = el.textContent.replace(/\s+/g, ' ').trim();
    if (text) attributes.push({ text: text.slice(0, 300), attr: 'sr-only', ...facts(el) });
  }
  const last = (selector) => {
    const all = [...document.querySelectorAll(selector)].filter(visible);
    return all[all.length - 1] ?? null;
  };
  const containers = [];
  const add = (name, el, expectRtl) => {
    if (!el) return;
    const s = getComputedStyle(el);
    containers.push({ name, dir: el.getAttribute('dir') ?? '', lang: el.getAttribute('lang') ?? '', direction: s.direction, textAlign: s.textAlign, expectRtl });
  };
  add('html', document.documentElement, true);
  add('body', document.body, true);
  add('#root', document.getElementById('root'), true);
  add('main', last('main, [role="main"]'), true);
  add('sidebar', last('nav'), true);
  add('chat header', document.querySelector('[data-testid="model-selector-button"]')?.closest('.absolute') ?? null, true);
  add('composer', last('[data-testid="composer-surface"]'), true);
  add('composer field', last('[data-testid="text-input"]'), false);
  add('answer', last('[data-iqraa-answer]'), true);
  add('answer strip', last('[data-iqraa-strip]'), true);
  add('pane', last('.iqraa-pane'), true);
  add('dialog', last('[role="dialog"], [role="alertdialog"]'), true);
  add('menu', last('[role="menu"]'), true);
  add('listbox', last('[role="listbox"]'), true);
  add('tab panel', last('[role="tabpanel"]'), true);
  add('sign-in form', last('form'), true);
  add('toast', last('.toast-root'), true);
  add('phone field', document.getElementById('iqraa-identifier'), false);
  // The tier heading (SplitText): its screen-reader copy is the text; the drawn units are its innermost elements
  // (the fork's WordFade: one per word inside an aria-hidden span; the stock SplitText: one per letter).
  const exportButton = document.getElementById('export-menu-button');
  const brand = document.querySelector('[data-testid="iqraa-brand-footer"]');
  const wordmark = document.querySelector('[data-testid="iqraa-wordmark"]');
  const palette = document.querySelector('[data-testid="composer-palette-button"]');
  const thinking =
    document.querySelector('[data-testid="composer-thinking-button"]') ??
    [...document.querySelectorAll('[data-testid="composer-surface"] button')].find((b) => /التفكير|thinking|effort|الجهد/i.test(b.getAttribute('aria-label') ?? ''));
  const hint = document.querySelector('[id^="composer-hint-"]');
  const field = document.querySelector('[data-testid="text-input"]');
  const probes = {
    exportButton:
      exportButton && visible(exportButton)
        ? { label: exportButton.getAttribute('aria-label') || exportButton.textContent.trim(), icon: ((exportButton.innerHTML.match(/lucide-[a-z0-9-]+/g) ?? []).filter((c) => c !== 'lucide-icon').join(' ')) }
        : null,
    brandFooter: brand ? { visible: visible(brand), text: brand.textContent.trim(), inView: inView(brand) } : null,
    wordmark: wordmark ? { visible: visible(wordmark), text: wordmark.textContent.replace(/\s+/g, ' ').trim(), alt: wordmark.querySelector('img')?.alt ?? '' } : null,
    palette: palette && visible(palette) ? palette.getAttribute('aria-label') || 'shown' : null,
    thinking: thinking && visible(thinking) ? thinking.getAttribute('aria-label') || thinking.textContent.trim() || 'shown' : null,
    hint: hint ? hint.textContent.trim() : null,
    placeholder: field?.getAttribute('placeholder') ?? null,
    fieldDir: field ? { dir: field.getAttribute('dir') ?? '', direction: getComputedStyle(field).direction } : null,
    links: [...document.querySelectorAll('a[href]')].filter(visible).map((a) => a.href).filter((href) => !href.startsWith(location.origin)).slice(0, 20),
    icons: [...document.querySelectorAll('link[rel~="icon"], link[rel="apple-touch-icon"], link[rel="manifest"]')].map((l) => `${l.rel} ${l.getAttribute('href')}`),
    dialogs: [...document.querySelectorAll('[role="dialog"], [role="alertdialog"]')]
      .filter(visible)
      .map((d) => (d.getAttribute('aria-label') || d.querySelector('h1, h2, h3, [id$="title"]')?.textContent || '').trim())
      .slice(0, 4),
    toast: [...document.querySelectorAll('.toast-root')].filter(visible).map((t) => t.textContent.trim()).slice(0, 3),
    // The Living Answer's record of library calls, as drawn: per call, its line and how many article chips it shows.
    records: [...document.querySelectorAll('[data-iqraa-record]')].filter(visible).map((r) => ({
      calls: [...r.querySelectorAll('[data-iqraa-rec="call"]')].map((c) => ({
        line: (c.querySelector('[data-iqraa-rec="line"]')?.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 160),
        chips: c.querySelectorAll('.iqraa-rec-chip').length,
      })),
      status: (r.querySelector('[data-iqraa-rec="status"]')?.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 160),
    })),
    // The answer strip as drawn: its controls in order (the note, the hollow tabs, the section index s0, s1 ...).
    strip: (() => {
      const strip = last('[data-iqraa-strip]');
      if (!strip) return null;
      return {
        items: [...strip.querySelectorAll('[data-iqraa-strip-key]')].map((b) => ({
          key: b.getAttribute('data-iqraa-strip-key'),
          label: (b.getAttribute('aria-label') || b.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80),
          current: b.getAttribute('aria-current') === 'location',
        })),
      };
    })(),
    // The section index follows the answer at the reading line, 30% of the height (useAnswerInView): which one it is.
    answerAtLine: (() => {
      const line = innerHeight * 0.3;
      const at = [...document.querySelectorAll('[data-iqraa-answer]')].find((a) => {
        const r = a.getBoundingClientRect();
        return r.top <= line && r.bottom > line;
      });
      if (!at) return null;
      const headings = [...at.querySelectorAll('.markdown h1, .markdown h2, .markdown h3, .markdown h4, .markdown h5, .markdown h6')];
      return { id: at.getAttribute('data-iqraa-answer'), headings: headings.map((h) => h.textContent.replace(/\s+/g, ' ').trim()).filter(Boolean) };
    })(),
    // Upstream's header control for background tools and subagents (it hides itself once no task is listed).
    backgroundTasks: (() => {
      const b = document.querySelector('[data-testid="header-background-tasks-button"]');
      return b && visible(b) ? b.getAttribute('aria-label') || 'shown' : null;
    })(),
    scrollWidth: document.documentElement.scrollWidth - innerWidth,
  };
  return {
    url: location.pathname + location.search,
    title: document.title,
    htmlDir: document.documentElement.dir,
    htmlLang: document.documentElement.lang,
    dark: document.documentElement.classList.contains('dark'),
    texts,
    attributes,
    containers,
    probes,
  };
}

// ------------------------------------------------------------------ captures and steps

/**
 * A screenshot, its census entry and its screens.json row. `extraProbes` adds facts the page cannot know; while
 * `ctx.english` is set (the customer chose the English interface) every capture says so.
 */
async function capture(ctx, slug, { screen, state, caption, fullPage = false, extraProbes }) {
  ctx.n += 1;
  const file = lib.shotName(ctx.view, ctx.theme, ctx.n, slug);
  let shotError = null;
  // The heading as it is drawn in the screenshot: read just before it, since the full census takes a moment.
  const headingAtShot = await ctx.page.evaluate(headingFacts).catch(() => null);
  try {
    await ctx.page.screenshot({ path: `${SHOTS}/${file}`, fullPage, timeout: 20000 });
  } catch (error) {
    shotError = String(error.message ?? error).split('\n')[0];
  }
  let raw;
  try {
    raw = await ctx.page.evaluate(collect);
    raw.heading = headingAtShot ?? (await ctx.page.evaluate(headingFacts).catch(() => null));
  } catch (error) {
    raw = { error: String(error.message ?? error).split('\n')[0], texts: [], attributes: [], containers: [], probes: {} };
  }
  const classify = (record) => ({ ...record, zone: lib.zoneOf(record), verdict: lib.classify(record) });
  const texts = raw.texts.map(classify);
  const attributes = raw.attributes.map(classify);
  // Arabic the customer meets, visible or read out (labels too): the review data for the drafts.
  for (const record of [...texts, ...attributes]) {
    if (record.verdict === 'no-latin' && /[؀-ۿ]/.test(record.text) && !record.inUserMessage && !record.inAnswerText) {
      const seen = arabic.get(record.text) ?? { shots: [], count: 0, files: new Set() };
      seen.count += 1;
      seen.files.add(file);
      if (seen.shots.length < 3 && !seen.shots.includes(file)) seen.shots.push(file);
      arabic.set(record.text, seen);
    }
  }
  const entry = {
    file,
    viewport: ctx.view,
    theme: ctx.theme,
    screen,
    state,
    url: raw.url,
    title: raw.title,
    htmlDir: raw.htmlDir,
    htmlLang: raw.htmlLang,
    dark: raw.dark,
    texts: texts.filter((r) => r.verdict !== 'no-latin'),
    attributes: attributes.filter((r) => r.verdict !== 'no-latin'),
    counts: { texts: texts.length, attributes: attributes.length, uiLatin: texts.filter((r) => r.verdict === 'ui').length },
    containers: raw.containers,
    heading: (() => {
      const h = raw.heading;
      return h ? { ...h, atShot: Boolean(headingAtShot), ...lib.headingJoin(h.text, h.unitTexts, h.letterSpacing, h.clipped) } : null;
    })(),
    probes: { ...raw.probes, ...(ctx.english ? { interfaceLanguage: 'en' } : {}), ...(extraProbes ?? {}) },
    ...(raw.error ? { collectError: raw.error } : {}),
    ...(shotError ? { shotError } : {}),
  };
  entries.push(entry);
  screens.push({ file, viewport: ctx.view, theme: ctx.theme, screen, state, caption, url: raw.url, ...(shotError ? { shotError } : {}) });
  return entry;
}

/** One step of a run; a control that is not there is recorded as not reached, with a screenshot, never a crash. */
async function step(ctx, name, body) {
  try {
    await body();
    ctx.reached.push(name);
  } catch (error) {
    const message = String(error.message ?? error).split('\n')[0];
    notReached.push({ run: ctx.run, step: name, error: message });
    console.log(`  not reached: ${ctx.run} ${name}: ${message}`);
    await capture(ctx, `not-reached-${name}`, { screen: 'not-reached', state: name, caption: `The pass could not finish «${name}»: ${message}` }).catch(() => undefined);
    await ctx.page.keyboard.press('Escape').catch(() => undefined);
  }
}

const escape = async (ctx, times = 1) => {
  for (let i = 0; i < times; i += 1) {
    await ctx.page.keyboard.press('Escape').catch(() => undefined);
    await sleep(300);
  }
};
const visibleNow = (locator) => locator.first().isVisible().catch(() => false);

/** The first of several candidates to be visible within `timeout`. */
async function firstVisible(label, candidates, timeout = 10000) {
  try {
    return await Promise.any(
      candidates.map(async (candidate) => {
        const found = candidate.first();
        await found.waitFor({ state: 'visible', timeout });
        return found;
      }),
    );
  } catch {
    throw new Error(`no control found for: ${label}`);
  }
}

async function openSidebar(ctx) {
  const { page } = ctx;
  if (await visibleNow(page.getByTestId('close-sidebar-button'))) return;
  const opener = await firstVisible('open the sidebar', [page.getByTestId('header-open-sidebar-button'), page.getByTestId('open-sidebar-button')]);
  await opener.click();
  await page.getByTestId('close-sidebar-button').first().waitFor({ state: 'visible', timeout: 10000 });
  await sleep(600);
}

/** On a phone the sidebar covers the chat: close it before working in the chat. */
async function closeSidebarOnPhone(ctx) {
  if (!ctx.phone) return;
  const closer = ctx.page.getByTestId('close-sidebar-button').first();
  if (await closer.isVisible().catch(() => false)) {
    await closer.click().catch(() => undefined);
    await sleep(600);
  }
}

async function newChat(ctx) {
  await ctx.page.goto(`${BASE}/c/new`);
  const input = ctx.page.getByTestId('text-input').first();
  await input.waitFor({ timeout: 30000 });
  await sleep(800);
  return input;
}

/** An answer has finished when the last message offers regenerate again (HoverButtons hides it while submitting). */
async function answerFinished(ctx, timeout = 90000) {
  await ctx.page.getByTestId('regenerate-generation-button').first().waitFor({ state: 'attached', timeout }).catch(() => undefined);
  await sleep(1200);
}

/** The scrollable ancestor of an element (the message list, a settings panel). */
async function scrollerOf(locator) {
  return locator.evaluateHandle((el) => {
    for (let cur = el; cur; cur = cur.parentElement) {
      const s = getComputedStyle(cur);
      if (cur.scrollHeight > cur.clientHeight + 20 && /(auto|scroll)/.test(s.overflowY)) return cur;
    }
    return document.scrollingElement;
  });
}

/** Screenshots down a scrolling area, from where it is now, at most `max` more. */
async function captureScrolling(ctx, locator, slug, meta, max = 4) {
  const scroller = await scrollerOf(locator);
  for (let i = 1; i <= max; i += 1) {
    const moved = await scroller.evaluate((el) => {
      const before = el.scrollTop;
      el.scrollTop = before + el.clientHeight * 0.8;
      return el.scrollTop - before;
    });
    if (moved < 10) break;
    await sleep(400);
    await capture(ctx, `${slug}-scrolled-${i}`, { ...meta, state: `${meta.state}, scrolled ${i}` });
  }
}

async function closePane(ctx) {
  const pane = ctx.page.locator('.iqraa-pane').first();
  if (await pane.isVisible().catch(() => false)) {
    const close = pane.getByRole('button', { name: /إغلاق|close/i }).first();
    if (await close.isVisible().catch(() => false)) await close.click().catch(() => undefined);
    else await escape(ctx);
    await sleep(400);
  } else {
    await escape(ctx);
  }
}

/** The options inside the newest open popover, menu, listbox or radio group. */
const optionsNow = (page) => page.locator('[role="menuitemradio"]:visible, [role="radio"]:visible, [role="option"]:visible, [role="menuitemcheckbox"]:visible');

/** A label for a control: its aria-label, its text, its test id. */
const labelOf = (locator) =>
  locator.evaluate((el) => (el.getAttribute('aria-label') || el.textContent || el.getAttribute('title') || el.getAttribute('data-testid') || '').replace(/\s+/g, ' ').trim().slice(0, 80));

// ------------------------------------------------------------------ the sections

async function signInStates(ctx) {
  const { page } = ctx;
  await step(ctx, 'signed-out-redirect', async () => {
    await page.goto(`${BASE}/c/new`);
    await page.waitForURL(/\/login/, { timeout: 30000 });
    await page.getByTestId('iqraa-identifier').waitFor({ timeout: 30000 });
    await sleep(800);
    const manifest = await page
      .evaluate(async () => {
        const link = document.querySelector('link[rel="manifest"]');
        if (!link) return null;
        const res = await fetch(link.href);
        if (!res.ok) return { status: res.status };
        const m = await res.json();
        return { href: link.getAttribute('href'), name: m.name, short_name: m.short_name, lang: m.lang, description: m.description };
      })
      .catch(() => null);
    const config = await page
      .evaluate(async () => {
        const res = await fetch('/api/config');
        if (!res.ok) return { status: res.status };
        const c = await res.json();
        return { appTitle: c.appTitle, customFooter: c.customFooter, helpAndFaqURL: c.helpAndFaqURL };
      })
      .catch(() => null);
    ctx.brandFacts = { manifest, config };
    await capture(ctx, 'signed-out-redirect', {
      screen: 'signin',
      state: 'signed-out redirect',
      caption: 'Opening /c/new without a session lands on the sign-in screen (phone entry).',
      extraProbes: { manifest, config, authenticatorLabel: AUTHENTICATOR_LABEL },
    });
  });
  await step(ctx, 'signin-states', async () => {
    await page.getByTestId('iqraa-identifier').fill(LOCAL_PHONE);
    await capture(ctx, 'signin-phone-filled', { screen: 'signin', state: 'phone entered', caption: 'Sign-in: the phone number typed (the local form 079…).' });
    const footer = page.getByTestId('iqraa-brand-footer').first();
    if (await footer.count()) await footer.scrollIntoViewIfNeeded().catch(() => undefined);
    else await page.mouse.wheel(0, 3000);
    await sleep(300);
    await capture(ctx, 'signin-footer', { screen: 'signin', state: 'footer area', caption: 'Sign-in: the bottom of the page, where REQ-UI-002 wants «Iqraa LAW AI».' });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.getByTestId('iqraa-use-app').click();
    await page.getByTestId('iqraa-code').waitFor({ timeout: 10000 });
    await sleep(300);
    await capture(ctx, 'signin-app-code', { screen: 'signin', state: 'authenticator code entry', caption: 'Sign-in: «use your authenticator app» chosen, the code field shown.' });
    await page.getByTestId('iqraa-use-backup').click();
    await sleep(300);
    await capture(ctx, 'signin-backup-code', { screen: 'signin', state: 'backup code entry', caption: 'Sign-in: the backup-code entry.' });
    await page.getByTestId('iqraa-use-app').click();
    await page.getByTestId('iqraa-code').fill(wrongCode());
    await page.getByTestId('iqraa-submit-code').click();
    await page.getByTestId('iqraa-auth-error').first().waitFor({ timeout: 15000 });
    await sleep(300);
    await capture(ctx, 'signin-wrong-code', { screen: 'signin', state: "a wrong code's error", caption: 'Sign-in: the error after a wrong authenticator code (one per run).' });
  });
  await step(ctx, 'signup-screen', async () => {
    await page.getByTestId('iqraa-to-signup').click();
    await page.waitForURL(/\/register/, { timeout: 15000 });
    await sleep(800);
    await capture(ctx, 'signup-screen', { screen: 'signup', state: 'sign-up form', caption: 'The sign-up screen a stranger reaches from the sign-in link (nothing submitted).' });
  });
  // The sign-in itself: without it the run has nothing more to show, so a failure ends the run.
  await page.goto(`${BASE}/login`);
  await page.getByTestId('iqraa-identifier').fill(LOCAL_PHONE);
  await page.getByTestId('iqraa-use-app').click();
  await page.getByTestId('iqraa-code').fill(await appCode());
  await page.getByTestId('iqraa-submit-code').click();
  await page.waitForURL(/\/c\//, { timeout: 30000 });
}

async function landingSection(ctx) {
  const { page } = ctx;
  await step(ctx, 'landing-heading', async () => {
    await page.goto(`${BASE}/c/new`);
    await page.locator('.split-parent').first().waitFor({ state: 'attached', timeout: 30000 });
    const start = Date.now();
    for (const [i, at] of [[1, 0], [2, 250], [3, 600], [4, 1500], [5, 3500]]) {
      const wait = at - (Date.now() - start);
      if (wait > 0) await sleep(wait);
      await capture(ctx, `landing-heading-frame-${i}`, {
        screen: 'landing',
        state: `tier heading, frame ${i} (+${Date.now() - start} ms)`,
        caption: `New chat for the customer's tier: the animated heading, frame ${i} of 5.`,
      });
    }
  });
  await step(ctx, 'sidebar-empty', async () => {
    await openSidebar(ctx);
    await sleep(1500);
    await capture(ctx, 'sidebar-empty', { screen: 'sidebar', state: 'empty, no chats yet', caption: 'The sidebar before the customer has any chat.' });
    await closeSidebarOnPhone(ctx);
  });
}

async function composerSection(ctx) {
  const { page } = ctx;
  await step(ctx, 'composer-states', async () => {
    const input = await newChat(ctx);
    await closeSidebarOnPhone(ctx);
    await input.evaluate((el) => el.blur());
    await capture(ctx, 'composer-idle', { screen: 'composer', state: 'idle', caption: 'The composer, idle (placeholder; the hint line is screen-reader text).' });
    await input.focus();
    await sleep(300);
    await capture(ctx, 'composer-focused', { screen: 'composer', state: 'focused', caption: 'The composer, focused.' });
    await input.fill(TYPED);
    await sleep(300);
    await capture(ctx, 'composer-with-text', { screen: 'composer', state: 'with text', caption: 'The composer with Arabic text typed (send enabled).' });
    await input.fill('');
  });
  await step(ctx, 'composer-controls', async () => {
    const surface = page.getByTestId('composer-surface').first();
    const controls = await surface.evaluate((root) =>
      [...root.querySelectorAll('button')]
        .filter((b) => b.getClientRects().length > 0 && !b.disabled && b.type !== 'submit')
        .map((b) => ({ testid: b.getAttribute('data-testid') ?? '', label: (b.getAttribute('aria-label') || b.textContent || '').trim().slice(0, 80) }))
        .filter((c) => !/إرسال|send|إيقاف|stop|توقف|ميكروفون|microphone|إملاء|dictat|إزالة|remove/i.test(c.label))
        .filter((c) => !/send-button|stop-button/.test(c.testid)),
    );
    if (!controls.length) throw new Error('the composer offers no control besides send');
    let i = 0;
    for (const control of controls) {
      i += 1;
      const button = control.testid ? surface.getByTestId(control.testid).first() : surface.locator(`button[aria-label="${control.label.replace(/"/g, '\\"')}"]`).first();
      const slug = `composer-control-${i}-${control.testid.replace(/^composer-/, '') || 'button'}`;
      await step(ctx, slug, async () => {
        await button.click();
        await sleep(600);
        await capture(ctx, slug, { screen: 'composer', state: `control «${control.label}» opened`, caption: `Composer control ${i} «${control.label}» (${control.testid || 'no test id'}) opened.` });
        if (control.testid === 'composer-palette-button') await paletteItems(ctx, button, i);
        else await controlOptions(ctx, button, slug, control.label);
        await escape(ctx);
      });
    }
  });
}

/** Every row of the + palette: highlighted, then chosen; what it opens is captured and closed, a chip it adds is removed. */
async function paletteItems(ctx, opener, i) {
  const { page } = ctx;
  const grid = page.locator('[role="grid"]:visible').last();
  await grid.waitFor({ timeout: 5000 });
  const rows = grid.locator('[role="row"]');
  const labels = (await rows.allInnerTexts()).map((t) => t.replace(/\s+/g, ' ').trim());
  const headers = await rows.evaluateAll((all) => all.map((r) => !!r.querySelector('[role="columnheader"]')));
  let k = 0;
  for (let r = 0; r < Math.min(labels.length, 16); r += 1) {
    if (headers[r]) continue;
    k += 1;
    const slug = `palette-item-${k}`;
    await step(ctx, slug, async () => {
      if (!(await visibleNow(page.locator('[role="grid"]')))) {
        await opener.click();
        await sleep(500);
      }
      const row = page.locator('[role="grid"]:visible').last().locator('[role="row"]').nth(r);
      await row.hover();
      await sleep(250);
      await capture(ctx, `${slug}-highlighted`, { screen: 'composer', state: `palette row «${labels[r]}» highlighted`, caption: `+ palette, row ${k} «${labels[r]}» under the pointer.` });
      const chooser = page.waitForEvent('filechooser', { timeout: 1500 }).then(() => true).catch(() => false);
      await row.locator('[role="gridcell"]').first().click();
      const picked = await chooser;
      await sleep(600);
      await capture(ctx, `${slug}-chosen`, {
        screen: 'composer',
        state: `palette row «${labels[r]}» chosen`,
        caption: `+ palette, row ${k} «${labels[r]}» chosen${picked ? ': it opened the system file picker (not filled)' : ''}.`,
      });
      await escape(ctx);
      // A row that turned a tool on leaves a chip: take it off again, so the next turns are the customer's plain turns.
      for (const chip of await page.locator('[data-testid^="composer-active-"]:visible').all()) {
        const remove = chip.getByRole('button', { name: /إزالة|remove|إلغاء التثبيت|unpin/i }).last();
        if (await remove.isVisible().catch(() => false)) await remove.click().catch(() => undefined);
      }
    });
  }
  await capture(ctx, `composer-control-${i}-palette-after`, { screen: 'composer', state: 'after the palette rows', caption: 'The composer after every palette row was tried and undone.' });
}

/** The options of a composer control (the thinking or effort choice): each chosen and captured, the first choice put back. */
async function controlOptions(ctx, opener, slug, label) {
  const { page } = ctx;
  const options = optionsNow(page);
  const count = Math.min(await options.count(), 8);
  if (!count) return;
  const names = [];
  for (let k = 0; k < count; k += 1) names.push(await labelOf(options.nth(k)));
  const checked = await options.evaluateAll((all) => all.findIndex((o) => o.getAttribute('aria-checked') === 'true' || o.getAttribute('aria-selected') === 'true'));
  for (let k = 0; k < count; k += 1) {
    if (!(await visibleNow(optionsNow(page)))) {
      await opener.click();
      await sleep(400);
    }
    await optionsNow(page).nth(k).click().catch(() => undefined);
    await sleep(500);
    await capture(ctx, `${slug}-option-${k + 1}`, { screen: 'composer', state: `«${label}» option «${names[k]}» chosen`, caption: `Composer control «${label}»: option ${k + 1} of ${count} «${names[k]}» chosen.` });
  }
  if (checked >= 0) {
    if (!(await visibleNow(optionsNow(page)))) {
      await opener.click();
      await sleep(400);
    }
    await optionsNow(page).nth(checked).click().catch(() => undefined);
    await sleep(300);
  }
}

async function answerSection(ctx) {
  const { page } = ctx;
  await step(ctx, 'answer-demo', async () => {
    const input = await newChat(ctx);
    await closeSidebarOnPhone(ctx);
    await input.fill(QUESTION);
    await capture(ctx, 'demo-question-typed', { screen: 'composer', state: 'the demo question typed', caption: 'The deterministic demo question in the composer, before sending.' });
    const start = Date.now();
    await input.press('Enter');
    // Always two frames, finished or not: a frame count that follows the stream's speed renumbers every later
    // screenshot from one pass to the next (2026-11-08: one frame instead of two moved desktop-light 23-89 by one).
    for (let k = 1; k <= 2; k += 1) {
      await capture(ctx, `demo-streaming-${k}`, { screen: 'answer', state: `while it streams, frame ${k} (+${Date.now() - start} ms)`, caption: `The demo question sent: frame ${k} while the answer arrives (it may have finished).` });
      await sleep(120);
    }
    await page.getByText(LAST_LINE).first().waitFor({ timeout: 90000 });
    await page.locator('.markdown li code').first().waitFor({ timeout: 30000 });
    await answerFinished(ctx);
    const answer = page.locator('[data-iqraa-answer]').last();
    await page.locator('.user-turn').last().scrollIntoViewIfNeeded();
    await capture(ctx, 'demo-answer', { screen: 'answer', state: 'the full Living Answer, from the top', caption: 'The demo answer finished, from the question down.' });
    await captureScrolling(ctx, answer, 'demo-answer', { screen: 'answer', state: 'the full Living Answer' });
  });
  await step(ctx, 'answer-citations', async () => {
    const cites = page.locator('[data-iqraa-answer] .iqraa-cite');
    const count = await cites.count();
    if (!count) {
      await capture(ctx, 'demo-no-citation-button', { screen: 'answer', state: 'no citation button', caption: 'The demo answer offers no citation button (.iqraa-cite) to open.' });
      return;
    }
    for (let k = 0; k < Math.min(count, 3); k += 1) {
      await cites.nth(k).scrollIntoViewIfNeeded();
      await cites.nth(k).click();
      await sleep(900);
      await capture(ctx, `demo-citation-${k + 1}`, { screen: 'answer', state: `citation ${k + 1} of ${count} opened`, caption: `The demo answer's citation ${k + 1} opened in the pane.` });
      await closePane(ctx);
    }
  });
  await step(ctx, 'answer-strip', async () => {
    const strip = page.locator('[data-iqraa-strip]').last();
    if (!(await strip.isVisible().catch(() => false))) {
      await capture(ctx, 'demo-no-strip', { screen: 'answer', state: 'no answer strip', caption: 'No answer strip ([data-iqraa-strip]) is shown under the answer.' });
      return;
    }
    await capture(ctx, 'demo-strip', { screen: 'answer', state: 'the answer strip', caption: 'The answer strip (note, gaps, sections) under the answer.' });
    const items = strip.locator('[data-iqraa-strip-key]');
    const count = Math.min(await items.count(), 6);
    for (let k = 0; k < count; k += 1) {
      const name = await labelOf(items.nth(k));
      await items.nth(k).click().catch(() => undefined);
      await sleep(800);
      await capture(ctx, `demo-strip-item-${k + 1}`, { screen: 'answer', state: `strip item «${name}» opened`, caption: `Answer strip item ${k + 1} «${name}» chosen.` });
      await closePane(ctx);
    }
  });
  await step(ctx, 'answer-actions', async () => {
    const turn = page.locator('.agent-turn').last();
    await turn.scrollIntoViewIfNeeded();
    await turn.hover();
    await sleep(400);
    await capture(ctx, 'demo-answer-actions', { screen: 'answer', state: "the answer's actions", caption: "The answer's action row (copy, feedback ...), pointer on the answer." });
    const menus = turn.locator('button[aria-haspopup]:visible:not(.iqraa-cite)');
    const count = Math.min(await menus.count(), 4);
    for (let k = 0; k < count; k += 1) {
      const name = await labelOf(menus.nth(k));
      await turn.hover();
      await menus.nth(k).click().catch(() => undefined);
      await sleep(500);
      await capture(ctx, `demo-answer-action-${k + 1}`, { screen: 'answer', state: `answer action «${name}» opened`, caption: `Answer action «${name}» opened.` });
      await escape(ctx);
    }
    // What sits under the answer (the fork's BelowAnswer): every button there besides citations, chips and the strip.
    const below = page.locator('[data-iqraa-answer]').last().locator('button:visible:not(.iqraa-cite):not(.iqraa-rec-chip):not([data-iqraa-strip-key])');
    const n = Math.min(await below.count(), 4);
    for (let k = 0; k < n; k += 1) {
      const name = await labelOf(below.nth(k));
      await below.nth(k).click().catch(() => undefined);
      await sleep(600);
      await capture(ctx, `demo-below-answer-${k + 1}`, { screen: 'answer', state: `under the answer: «${name}» opened`, caption: `Under the answer: «${name}» opened.` });
      await closePane(ctx);
    }
  });
  await step(ctx, 'answer-library', async () => {
    const input = page.getByTestId('text-input').first();
    await input.fill(LIBRARY_QUESTION);
    const start = Date.now();
    await input.press('Enter');
    for (let k = 1; k <= 3; k += 1) {
      await sleep(400);
      await capture(ctx, `library-live-${k}`, { screen: 'answer', state: `a library turn live, frame ${k} (+${Date.now() - start} ms)`, caption: `A turn that searches the library three times: frame ${k} while it runs.` });
    }
    await page.getByText(/TOOL_RESULT_SEEN/).first().waitFor({ timeout: 90000 });
    await answerFinished(ctx);
    const answer = page.locator('[data-iqraa-answer]').last();
    await answer.scrollIntoViewIfNeeded();
    await capture(ctx, 'library-answer', { screen: 'answer', state: 'an answer that used the library', caption: 'The answer after three library searches, with the record of the calls.' });
    const record = answer.locator('[data-iqraa-record]').first();
    if (await record.isVisible().catch(() => false)) {
      await record.scrollIntoViewIfNeeded();
      await capture(ctx, 'library-record', { screen: 'answer', state: 'the record of the library calls', caption: 'The record of the library calls (what was asked, what came back).' });
    }
    const group = page.getByTestId('tool-call-group').last();
    if (await group.isVisible().catch(() => false)) {
      await group.click().catch(() => undefined);
      await sleep(600);
      await capture(ctx, 'library-tool-group-opened', { screen: 'answer', state: 'the stock tool-call group opened', caption: "The stock tool-call group ('Ran N actions') opened." });
    }
    const chips = answer.locator('.iqraa-rec-chip');
    const count = Math.min(await chips.count(), 2);
    for (let k = 0; k < count; k += 1) {
      await chips.nth(k).scrollIntoViewIfNeeded();
      await chips.nth(k).click();
      await sleep(900);
      await capture(ctx, `library-source-${k + 1}`, { screen: 'answer', state: `source ${k + 1} opened`, caption: `A source the library returned, opened in the pane (${k + 1}).` });
      await closePane(ctx);
    }
  });
}

/** A sidebar row's menu: on a desktop the trigger shows once the pointer is on the row (ConvoActions). */
async function openRowMenu(ctx, row) {
  if (!ctx.phone) await row.hover();
  await sleep(250);
  const trigger = await firstVisible('conversation options', [row.getByTestId('convo-options-trigger'), row.locator('button[id^="conversation-menu-"]'), row.getByTestId('convo-options')], 5000);
  await trigger.click();
  await sleep(400);
}

async function conversationSection(ctx) {
  const { page } = ctx;
  const rows = page.getByTestId('convo-item');
  await step(ctx, 'conversation-short-chat', async () => {
    const input = await newChat(ctx);
    await closeSidebarOnPhone(ctx);
    await input.fill(SHORT_QUESTION);
    await input.press('Enter');
    await page.getByText(/MOCK_OK/).first().waitFor({ timeout: 90000 });
    await answerFinished(ctx);
    await sleep(2000); // the title
  });
  await step(ctx, 'sidebar-with-chats', async () => {
    await openSidebar(ctx);
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="convo-item"]').length >= 2, null, { timeout: 15000 });
    await sleep(800);
    await capture(ctx, 'sidebar-with-chats', { screen: 'sidebar', state: 'with chats', caption: 'The sidebar with the two chats of this run.' });
  });
  await step(ctx, 'sidebar-search', async () => {
    await openSidebar(ctx);
    const field = page.getByTestId('nav-search-input').first();
    if (!(await field.isVisible().catch(() => false))) {
      await capture(ctx, 'sidebar-no-search-field', { screen: 'sidebar', state: 'search: no field', caption: 'Chat search: the sidebar shows no search field (SEARCH is off on staging, compose.yaml).' });
      return;
    }
    await field.fill('العربون');
    await sleep(1200);
    await capture(ctx, 'sidebar-search', { screen: 'sidebar', state: 'search typed', caption: 'Chat search with «العربون» typed.' });
    await field.fill('');
  });
  await step(ctx, 'conversation-menu', async () => {
    await openSidebar(ctx);
    await openRowMenu(ctx, rows.first());
    await capture(ctx, 'conversation-menu', { screen: 'conversation', state: 'row menu open', caption: "A sidebar chat's menu (pin, rename, archive, delete)." });
    await escape(ctx);
  });
  await step(ctx, 'conversation-rename', async () => {
    await openSidebar(ctx);
    const row = rows.nth(1); // the demo chat; the short chat is the newest
    await openRowMenu(ctx, row);
    await (await firstVisible('rename', [page.getByRole('menuitem', { name: /إعادة تسمية|rename/i })])).click();
    const title = await firstVisible('the title field', [page.getByTestId('rename-form').locator('input'), rows.locator('input')]);
    await title.fill(RENAMED);
    await capture(ctx, 'conversation-rename-editing', { screen: 'conversation', state: 'renaming', caption: 'Renaming a chat: the title field with the new Arabic title.' });
    await title.press('Enter');
    await rows.filter({ hasText: RENAMED }).first().waitFor({ timeout: 15000 });
    await sleep(500);
    await capture(ctx, 'conversation-renamed', { screen: 'conversation', state: 'renamed', caption: 'The chat after the rename.' });
  });
  await step(ctx, 'conversation-pin', async () => {
    await openSidebar(ctx);
    await openRowMenu(ctx, rows.filter({ hasText: RENAMED }).first());
    await (await firstVisible('pin', [page.getByRole('menuitem', { name: /^(تثبيت|pin)$/i })])).click();
    await sleep(1500);
    await escape(ctx);
    await openSidebar(ctx);
    await capture(ctx, 'sidebar-pinned', { screen: 'sidebar', state: 'with a pinned chat', caption: 'The sidebar with the renamed chat pinned.' });
  });
  await step(ctx, 'conversation-delete', async () => {
    await openSidebar(ctx);
    const row = rows.filter({ hasNotText: RENAMED }).first();
    await openRowMenu(ctx, row);
    await (await firstVisible('delete', [page.getByRole('menuitem', { name: /حذف|delete/i })])).click();
    const dialog = await firstVisible('the delete dialog', [page.getByRole('dialog').filter({ has: page.getByRole('button', { name: /حذف|delete/i }) })]);
    await sleep(300);
    await capture(ctx, 'conversation-delete-dialog', { screen: 'conversation', state: 'delete confirm dialog', caption: 'Deleting a chat: the confirm dialog.' });
    await dialog.getByRole('button', { name: /حذف|delete/i }).last().click();
    const toast = await page.locator('.toast-root').first().waitFor({ state: 'visible', timeout: 8000 }).then(() => true).catch(() => false);
    await sleep(300);
    await capture(ctx, 'conversation-delete-toast', {
      screen: 'conversation',
      state: toast ? 'deleted, toast' : 'deleted, no toast within 8 s',
      caption: toast ? 'After the delete: the toast.' : 'After the delete: no toast appeared within 8 seconds.',
    });
  });
  await closeSidebarOnPhone(ctx);
}

/** The header's buttons that open something (menus, the tier picker), each opened and captured. */
async function headerSection(ctx) {
  const { page } = ctx;
  await step(ctx, 'header-open-chat', async () => {
    await openSidebar(ctx);
    // Pinned, the chat may sit in the pinned section under another test id.
    const chat = await firstVisible('the renamed chat', [page.getByTestId('convo-item').filter({ hasText: RENAMED }), page.getByTestId('pinned-convo').filter({ hasText: RENAMED }), page.getByText(RENAMED, { exact: true })]);
    await chat.click();
    await sleep(600);
    await closeSidebarOnPhone(ctx);
    await page.locator('[data-iqraa-answer]').first().waitFor({ timeout: 30000 });
    await sleep(800);
    await capture(ctx, 'header-chat', { screen: 'header', state: 'a chat open', caption: 'A chat opened from the sidebar: the header with its controls.' });
  });
  await step(ctx, 'header-tier-picker', async () => {
    await page.getByTestId('model-selector-button').first().click();
    await sleep(700);
    await capture(ctx, 'header-tier-picker', { screen: 'header', state: 'tier picker open', caption: 'The tier picker (model selector) opened.' });
    await escape(ctx);
  });
  await step(ctx, 'header-export', async () => {
    let button = page.locator('#export-menu-button').first();
    if (!(await button.isVisible().catch(() => false))) {
      const overflow = page.getByTestId('header-overflow-menu').first();
      if (!(await overflow.isVisible().catch(() => false))) throw new Error('no Export/Share button and no overflow menu');
      await overflow.click();
      await sleep(500);
      await capture(ctx, 'header-overflow-menu', { screen: 'header', state: 'overflow menu open', caption: "The header's overflow menu opened." });
      button = page.getByRole('menuitem', { name: /تصدير|export/i }).first();
    } else {
      await button.click();
      await sleep(500);
      await capture(ctx, 'header-export-menu', { screen: 'header', state: 'Export/Share menu open', caption: 'The Export/Share header menu opened.' });
      button = page.getByRole('menuitem', { name: /تصدير|export/i }).first();
    }
    await button.click();
    await page.getByRole('dialog').first().waitFor({ timeout: 10000 });
    await sleep(500);
    await capture(ctx, 'header-export-dialog', { screen: 'header', state: 'export dialog', caption: 'The export dialog (nothing exported).' });
    await escape(ctx);
  });
  await step(ctx, 'header-other-buttons', async () => {
    const header = page.getByTestId('model-selector-button').first().locator('xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " absolute ")][1]');
    const buttons = await header.evaluate((root) =>
      [...root.querySelectorAll('button[aria-haspopup], button[aria-expanded]')]
        .filter((b) => b.getClientRects().length > 0)
        .map((b) => ({ id: b.id, testid: b.getAttribute('data-testid') ?? '', label: (b.getAttribute('aria-label') || b.textContent || '').trim().slice(0, 80) }))
        .filter((b) => b.id !== 'export-menu-button' && b.testid !== 'model-selector-button'),
    );
    let k = 0;
    for (const b of buttons) {
      k += 1;
      const target = b.testid ? page.getByTestId(b.testid).first() : b.id ? page.locator(`[id="${b.id}"]`).first() : header.locator(`button[aria-label="${b.label.replace(/"/g, '\\"')}"]`).first();
      await target.click().catch(() => undefined);
      await sleep(500);
      await capture(ctx, `header-button-${k}`, { screen: 'header', state: `header control «${b.label}» opened`, caption: `Header control «${b.label}» (${b.testid || b.id || 'no id'}) opened.` });
      await escape(ctx);
    }
  });
}

async function openAccountMenu(ctx) {
  const { page } = ctx;
  await openSidebar(ctx);
  await page.getByTestId('nav-user').first().click();
  await page
    .waitForFunction(() => /[0-9٠-٩۰-۹]{7}/.test(document.querySelector('[data-testid="iqraa-account-label"]')?.textContent ?? ''), null, { timeout: 15000 })
    .catch(() => undefined);
  await sleep(400);
}

async function accountSection(ctx) {
  const { page } = ctx;
  let items = [];
  await step(ctx, 'account-menu', async () => {
    await openAccountMenu(ctx);
    items = (await page.getByRole('menuitem').allInnerTexts()).map((t) => t.replace(/\s+/g, ' ').trim());
    await capture(ctx, 'account-menu', { screen: 'account', state: 'account menu open', caption: `The account menu: ${items.join(' | ')}.` });
    await escape(ctx);
  });
  await step(ctx, 'account-archived', async () => {
    await openAccountMenu(ctx);
    await (await firstVisible('archived chats', [page.getByRole('menuitem', { name: /المؤرشفة|archived/i })])).click();
    await page.getByRole('dialog').first().waitFor({ timeout: 10000 });
    await sleep(800);
    await capture(ctx, 'account-archived-chats', { screen: 'account', state: 'archived chats dialog', caption: 'Archived chats (from the account menu).' });
    await escape(ctx);
  });
  // The rest of the menu, except settings (below), log out (last) and links that leave the site (read, not followed).
  const skip = /الإعدادات|settings|تسجيل الخروج|log ?out|المؤرشفة|archived/i;
  let k = 0;
  for (const item of items.filter((name) => name && !skip.test(name))) {
    k += 1;
    await step(ctx, `account-item-${k}`, async () => {
      await openAccountMenu(ctx);
      const entry = page.getByRole('menuitem', { name: item }).first();
      const href = await entry.evaluate((el) => el.closest('a')?.href ?? el.querySelector('a')?.href ?? '').catch(() => '');
      if (href && !href.startsWith(BASE)) {
        await capture(ctx, `account-item-${k}-link`, { screen: 'account', state: `menu item «${item}» is a link`, caption: `Account menu item «${item}» links to ${href} (not followed).`, extraProbes: { links: [href] } });
        await escape(ctx);
        return;
      }
      const popup = ctx.context.waitForEvent('page', { timeout: 1500 }).catch(() => null);
      await entry.click();
      const opened = await popup;
      if (opened) {
        const url = opened.url();
        await opened.close().catch(() => undefined);
        await capture(ctx, `account-item-${k}-opened-tab`, { screen: 'account', state: `menu item «${item}» opened a tab`, caption: `Account menu item «${item}» opened a new tab at ${url} (closed).`, extraProbes: { links: [url] } });
        return;
      }
      await sleep(700);
      await capture(ctx, `account-item-${k}`, { screen: 'account', state: `menu item «${item}» opened`, caption: `Account menu item «${item}» opened.` });
      // A submenu (Help: keyboard shortcuts ...): each of its items opened too.
      const subs = (await page.getByRole('menuitem').allInnerTexts()).map((t) => t.replace(/\s+/g, ' ').trim()).filter((name) => name && !items.includes(name));
      let j = 0;
      for (const sub of subs.slice(0, 4)) {
        j += 1;
        if (!(await visibleNow(page.getByRole('menuitem', { name: sub })))) {
          await escape(ctx, 2);
          await openAccountMenu(ctx);
          await page.getByRole('menuitem', { name: item }).first().click();
          await sleep(500);
        }
        const target = page.getByRole('menuitem', { name: sub }).first();
        const href = await target.evaluate((el) => el.closest('a')?.href ?? '').catch(() => '');
        if (href && !href.startsWith(BASE)) {
          await capture(ctx, `account-item-${k}-sub-${j}-link`, { screen: 'account', state: `submenu item «${sub}» is a link`, caption: `«${item}» › «${sub}» links to ${href} (not followed).`, extraProbes: { links: [href] } });
          continue;
        }
        const tab = ctx.context.waitForEvent('page', { timeout: 1500 }).catch(() => null);
        await target.click();
        const other = await tab;
        if (other) {
          const url = other.url();
          await other.close().catch(() => undefined);
          await capture(ctx, `account-item-${k}-sub-${j}-tab`, { screen: 'account', state: `submenu item «${sub}» opened a tab`, caption: `«${item}» › «${sub}» opened a new tab at ${url} (closed).`, extraProbes: { links: [url] } });
          continue;
        }
        await sleep(700);
        await capture(ctx, `account-item-${k}-sub-${j}`, { screen: 'account', state: `submenu item «${sub}» opened`, caption: `«${item}» › «${sub}» opened.` });
        await escape(ctx, 2);
      }
      await escape(ctx);
    });
  }
}

async function openSettings(ctx) {
  const { page } = ctx;
  await openAccountMenu(ctx);
  await page.getByTestId('nav-settings').first().click();
  const dialog = page.getByRole('dialog').first();
  await dialog.getByRole('tablist').waitFor({ timeout: 15000 });
  await sleep(500);
  return dialog;
}

/** Every settings tab and every row: each tab captured (scrolled on a phone), each control that opens something opened. */
async function settingsSection(ctx) {
  const { page } = ctx;
  let tabNames = [];
  await step(ctx, 'settings-open', async () => {
    const dialog = await openSettings(ctx);
    tabNames = (await dialog.getByRole('tab').allInnerTexts()).map((t) => t.replace(/\s+/g, ' ').trim());
  });
  for (let t = 0; t < tabNames.length; t += 1) {
    const tabSlug = `settings-tab-${t + 1}`;
    // The tab list shows on a desktop beside the rows; on a phone only before a tab is chosen (Settings/Dialog.tsx),
    // so a phone goes back through the account menu for every tab and row.
    const openTab = async () => {
      if (!(await visibleNow(page.locator('[role="tablist"]')))) {
        await escape(ctx, 2);
        await openSettings(ctx);
      }
      await page.locator('[role="tab"]:visible').nth(t).click({ timeout: 5000 });
      await sleep(500);
      return page.getByRole('dialog').first();
    };
    await step(ctx, tabSlug, async () => {
      const dialog = await openTab();
      await capture(ctx, tabSlug, { screen: 'settings', state: `tab «${tabNames[t]}»`, caption: `Settings, tab ${t + 1} «${tabNames[t]}».` });
      const panel = dialog.getByRole('tabpanel').first();
      await captureScrolling(ctx, panel.locator('*').first(), tabSlug, { screen: 'settings', state: `tab «${tabNames[t]}»` }, 3);
      await panel.evaluate((el) => {
        for (let cur = el; cur; cur = cur.parentElement) cur.scrollTop = 0;
      });
    });
    let controls = [];
    await step(ctx, `${tabSlug}-rows`, async () => {
      const dialog = await openTab();
      // `index` counts every match, hidden ones included, as the locator's nth() below does.
      controls = await dialog.getByRole('tabpanel').first().evaluate((root) =>
        [...root.querySelectorAll('button, [role="combobox"]')]
          .map((el, index) => ({ el, index }))
          .filter(({ el }) => el.getClientRects().length > 0 && !el.disabled && el.getAttribute('aria-disabled') !== 'true')
          .filter(({ el }) => el.getAttribute('role') !== 'switch' && !el.hasAttribute('aria-checked'))
          .map(({ el, index }) => ({ index, testid: el.getAttribute('data-testid') ?? '', label: (el.getAttribute('aria-label') || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80) })),
      );
    });
    // Never: change the UI scale, send an email code, regenerate backup codes or delete the account.
    const unsafe = /ui-scale|iqraa-email-send|iqraa-email-verify|regenerate|إعادة إنشاء|delete-account|حذف الحساب/i;
    let k = 0;
    for (const control of controls.filter((c) => !unsafe.test(`${c.testid} ${c.label}`))) {
      k += 1;
      await step(ctx, `${tabSlug}-control-${k}`, async () => {
        const dialog = await openTab();
        const all = dialog.getByRole('tabpanel').first().locator('button, [role="combobox"]');
        const target = all.nth(control.index);
        await target.scrollIntoViewIfNeeded();
        await target.click();
        await sleep(700);
        await capture(ctx, `${tabSlug}-control-${k}`, { screen: 'settings', state: `tab «${tabNames[t]}», «${control.label}» opened`, caption: `Settings «${tabNames[t]}»: «${control.label}» opened (nothing chosen or confirmed).` });
        await escape(ctx);
      });
    }
  }
  await escape(ctx, 2);
}

async function routesSection(ctx) {
  const { page } = ctx;
  await step(ctx, 'unknown-routes', async () => {
    await page.goto(`${BASE}/c/00000000-0000-4000-8000-000000000000`);
    await sleep(3000);
    await capture(ctx, 'route-unknown-conversation', { screen: 'route', state: 'a conversation that does not exist', caption: '/c/<an id no conversation has>.' });
    await page.goto(`${BASE}/nothing-here`);
    await sleep(3000);
    await capture(ctx, 'route-unknown-path', { screen: 'route', state: 'an unknown path', caption: '/nothing-here.' });
  });
}

/** «Delete all chats» from the Data tab (its confirm dialog is a screen too), so the next run starts empty. */
async function cleanupSection(ctx) {
  const { page } = ctx;
  await step(ctx, 'clear-all-chats', async () => {
    await newChat(ctx); // after the unknown routes: back where the sidebar is
    const dialog = await openSettings(ctx);
    await dialog.getByRole('tab', { name: /البيانات|data/i }).first().click();
    await sleep(500);
    const row = page.locator('div:has(> #clear-all-chats-label)').first();
    await row.getByRole('button').first().click();
    const confirm = await firstVisible('the clear-chats dialog', [page.getByRole('dialog').filter({ hasNot: page.getByRole('tablist') })]);
    await sleep(300);
    await capture(ctx, 'settings-clear-chats-dialog', { screen: 'settings', state: 'delete all chats, confirm', caption: 'Settings, Data: «delete all chats» asks for confirmation.' });
    await confirm.getByRole('button', { name: /حذف|delete/i }).last().click();
    await page.locator('.toast-root').first().waitFor({ state: 'visible', timeout: 8000 }).catch(() => undefined);
    await sleep(300);
    await capture(ctx, 'settings-chats-deleted', { screen: 'settings', state: 'all chats deleted, toast', caption: 'All chats deleted: the toast.' });
    await escape(ctx, 2);
  });
}

/** «Delete all chats» again, without screenshots: the chats the `more` section made. */
async function clearChatsQuietly(ctx) {
  const { page } = ctx;
  await step(ctx, 'clear-more-chats', async () => {
    await newChat(ctx);
    const dialog = await openSettings(ctx);
    await dialog.getByRole('tab', { name: /البيانات|data/i }).first().click();
    await sleep(500);
    const row = page.locator('div:has(> #clear-all-chats-label)').first();
    await row.getByRole('button').first().click();
    const confirm = await firstVisible('the clear-chats dialog', [page.getByRole('dialog').filter({ hasNot: page.getByRole('tablist') })]);
    await confirm.getByRole('button', { name: /حذف|delete/i }).last().click();
    await page.locator('.toast-root').first().waitFor({ state: 'visible', timeout: 8000 }).catch(() => undefined);
    await escape(ctx, 2);
  });
}

/** Puts the last answer's first heading a little above the reading line (30% of the height), so that answer crosses it. */
async function headingAtLine(ctx) {
  const heading = ctx.page.locator('[data-iqraa-answer]').last().locator('.markdown h1, .markdown h2, .markdown h3, .markdown h4').first();
  await heading.waitFor({ timeout: 15000 });
  await heading.evaluate((el) => {
    let scroller = el.parentElement;
    while (scroller && !(scroller.scrollHeight > scroller.clientHeight + 20 && /(auto|scroll)/.test(getComputedStyle(scroller).overflowY))) scroller = scroller.parentElement;
    (scroller ?? document.scrollingElement).scrollTop += el.getBoundingClientRect().top - innerHeight * 0.25;
  });
  await sleep(900);
}

/** A tier in the open tier picker, by its name. */
const tierOption = (page, name) =>
  firstVisible(`the tier «${name}»`, [page.getByRole('option', { name }), page.getByRole('menuitem', { name }), page.getByRole('menuitemradio', { name })]);

/**
 * Screens a customer reaches that the sections above never open (added after the review of 2026-11-08): the question
 * builder and the starter gallery, a starter card sent, the second tier, the strip's section index of one answer live
 * and after its chat is opened again, editing one's own question, copy and fork from the answer's actions, a
 * regenerated answer, archiving a chat and taking it back, the error page's details, an upload, and the English
 * interface. It runs after «delete all chats» and deletes its own chats again.
 */
async function moreSection(ctx) {
  const { page } = ctx;
  const rows = page.getByTestId('convo-item');
  await step(ctx, 'more-builder', async () => {
    await newChat(ctx);
    await closeSidebarOnPhone(ctx);
    await (await firstVisible('the question builder button', [page.getByTestId('iqraa-builder-open')])).click();
    await page.getByTestId('iqraa-builder').first().waitFor({ state: 'visible', timeout: 10000 });
    await sleep(500);
    await capture(ctx, 'more-builder-open', { screen: 'landing', state: 'question builder open', caption: 'New chat: «ابن سؤالك خطوة خطوة» (the question builder) opened.' });
    const choice = page.getByTestId('iqraa-builder').locator('button[aria-pressed]').first();
    if (await choice.isVisible().catch(() => false)) {
      await choice.click();
      await sleep(500);
      await capture(ctx, 'more-builder-choice', { screen: 'landing', state: 'question builder, first choice made', caption: 'The question builder after its first choice.' });
    }
    await page.getByTestId('iqraa-builder-open').first().click();
    await sleep(300);
  });
  await step(ctx, 'more-gallery', async () => {
    await (await firstVisible('more questions', [page.getByTestId('iqraa-starters-more')])).click();
    await sleep(600);
    await capture(ctx, 'more-gallery', { screen: 'landing', state: 'starter gallery open', caption: '«المزيد من الأسئلة» (the starter gallery) opened.' });
    const areas = page.locator('[data-testid^="iqraa-starter-area-"]');
    if ((await areas.count()) > 1) {
      await areas.nth(1).click();
      await sleep(500);
      await capture(ctx, 'more-gallery-area-2', { screen: 'landing', state: 'starter gallery, second area', caption: 'The starter gallery with its second area chosen.' });
    }
  });
  await step(ctx, 'more-starter-card', async () => {
    const card = page.locator('button[data-testid^="iqraa-starter-"]:not([data-testid^="iqraa-starter-area-"])').first();
    const text = await labelOf(card);
    await card.click();
    await page.locator('[data-iqraa-answer]').first().waitFor({ timeout: 60000 });
    await answerFinished(ctx, 60000);
    await capture(ctx, 'more-starter-answer', { screen: 'answer', state: 'a starter card sent', caption: `A starter card «${text}» sent, and its answer.` });
  });
  await step(ctx, 'more-second-tier', async () => {
    const input = await newChat(ctx);
    await closeSidebarOnPhone(ctx);
    await page.getByTestId('model-selector-button').first().click();
    await sleep(600);
    await (await tierOption(page, /عقل متقدم/)).click();
    await sleep(1200);
    await capture(ctx, 'more-second-tier-landing', { screen: 'landing', state: 'second tier chosen', caption: 'New chat on the second tier «عقل متقدم».' });
    await input.fill(SHORT_QUESTION);
    await input.press('Enter');
    await answerFinished(ctx, 60000);
    await capture(ctx, 'more-second-tier-answer', { screen: 'answer', state: 'second tier, a question sent', caption: 'A question sent on the second tier: its answer, or the refusal a plan without it gets.' });
    // Back to the first tier on a new chat, so the rest of the run asks it as before.
    await newChat(ctx);
    await closeSidebarOnPhone(ctx);
    await page.getByTestId('model-selector-button').first().click();
    await sleep(600);
    await (await tierOption(page, /عقل سريع/)).click();
    await sleep(600);
  });
  await step(ctx, 'more-index-live', async () => {
    const input = await newChat(ctx);
    await closeSidebarOnPhone(ctx);
    await input.fill(QUESTION);
    await input.press('Enter');
    await page.getByText(LAST_LINE).first().waitFor({ timeout: 90000 });
    await answerFinished(ctx);
    await headingAtLine(ctx);
    await capture(ctx, 'more-index-live', { screen: 'answer', state: 'section index, live: the demo answer at the reading line', caption: "Right after the demo answer streamed, its first heading at the reading line: the strip's section index." });
  });
  await step(ctx, 'more-index-reopened', async () => {
    await page.goto(`${BASE}/c/new`);
    await page.getByTestId('text-input').first().waitFor({ timeout: 30000 });
    await openSidebar(ctx);
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="convo-item"]').length >= 1, null, { timeout: 15000 });
    await rows.first().click();
    await closeSidebarOnPhone(ctx);
    await page.locator('[data-iqraa-answer]').first().waitFor({ timeout: 30000 });
    await sleep(1200);
    await headingAtLine(ctx);
    await capture(ctx, 'more-index-reopened', { screen: 'answer', state: 'section index, reopened: the demo answer at the reading line', caption: 'The same chat opened again from the sidebar, the same heading at the reading line: the section index again.' });
  });
  await step(ctx, 'more-edit-question', async () => {
    const turn = page.locator('.user-turn').last();
    await turn.scrollIntoViewIfNeeded();
    await turn.hover();
    await sleep(300);
    await (await firstVisible('edit the question', [turn.getByRole('button', { name: /^(تعديل|edit)$/i }), turn.locator('button[title="تعديل"]')])).click();
    await sleep(600);
    await capture(ctx, 'more-edit-question', { screen: 'answer', state: "editing one's own question", caption: 'The pencil under the question: the question open for editing (nothing saved).' });
    await (await firstVisible('cancel the edit', [page.getByRole('button', { name: /^(إلغاء|cancel)$/i })])).click();
    await sleep(400);
  });
  await step(ctx, 'more-copy', async () => {
    const turn = page.locator('.agent-turn').last();
    await turn.scrollIntoViewIfNeeded();
    await turn.hover();
    await (await firstVisible('copy the answer', [page.getByTestId('copy-response-button').last()])).click();
    await sleep(500);
    await capture(ctx, 'more-copied', { screen: 'answer', state: 'answer copied', caption: "The answer's copy button pressed: what it shows after copying." });
  });
  await step(ctx, 'more-fork', async () => {
    const turn = page.locator('.agent-turn').last();
    await turn.hover();
    // packages/chat Fork.tsx: the trigger's label is com_ui_fork_open_menu («فتح قائمة التفريع»).
    await (await firstVisible('fork', [turn.getByRole('button', { name: /قائمة التفريع|fork menu/i })])).click();
    await sleep(600);
    await capture(ctx, 'more-fork-options', { screen: 'answer', state: 'fork options open', caption: "The answer's fork button: its options (nothing forked)." });
    await escape(ctx);
  });
  await step(ctx, 'more-regenerate', async () => {
    await page.locator('.agent-turn').last().hover();
    await page.getByTestId('regenerate-generation-button').first().click();
    await sleep(1500);
    await page.getByText(LAST_LINE).last().waitFor({ timeout: 90000 });
    await answerFinished(ctx);
    await page.locator('.agent-turn').last().scrollIntoViewIfNeeded();
    await capture(ctx, 'more-regenerated', { screen: 'answer', state: 'a regenerated answer', caption: 'The demo answer regenerated: the new answer and its sibling switch.' });
  });
  await step(ctx, 'more-archive', async () => {
    await openSidebar(ctx);
    await openRowMenu(ctx, rows.first());
    await (await firstVisible('archive', [page.getByRole('menuitem', { name: /^(أرشفة|archive)$/i })])).click();
    await page.locator('.toast-root').first().waitFor({ state: 'visible', timeout: 8000 }).catch(() => undefined);
    await sleep(300);
    await capture(ctx, 'more-archived', { screen: 'conversation', state: 'archived', caption: 'A chat archived from its menu.' });
    await escape(ctx);
    await openAccountMenu(ctx);
    await (await firstVisible('archived chats', [page.getByRole('menuitem', { name: /المؤرشفة|archived/i })])).click();
    const dialog = page.getByRole('dialog').first();
    await dialog.waitFor({ timeout: 10000 });
    await sleep(1000);
    await capture(ctx, 'more-archived-list', { screen: 'account', state: 'archived chats dialog with a chat', caption: 'Archived chats, with the chat just archived.' });
    // ArchivedChatsTable.tsx: the row's button is labelled com_ui_unarchive_conversation («إلغاء أرشفة المحادثة»).
    await (await firstVisible('unarchive', [dialog.getByRole('button', { name: /إلغاء أرشفة|إلغاء الأرشفة|unarchive/i })])).click();
    await sleep(1000);
    await capture(ctx, 'more-unarchived', { screen: 'account', state: 'chat taken out of the archive', caption: 'The chat taken back out of the archive.' });
    await escape(ctx, 2);
  });
  await step(ctx, 'more-error-details', async () => {
    await page.goto(`${BASE}/nothing-here`);
    await sleep(2500);
    const summaries = page.locator('details > summary');
    const n = await summaries.count();
    if (!n) throw new Error('the error page has no details to open');
    for (let k = 0; k < n; k += 1) await summaries.nth(k).click().catch(() => undefined);
    await sleep(500);
    await capture(ctx, 'more-error-details', { screen: 'route', state: 'error page, details opened', caption: 'The error page with every «details» part opened («تفاصيل إضافية» among them).', fullPage: true });
  });
  await step(ctx, 'more-upload', async () => {
    await newChat(ctx);
    await closeSidebarOnPhone(ctx);
    await page.getByTestId('composer-palette-button').first().click();
    const grid = page.locator('[role="grid"]:visible').last();
    await grid.waitFor({ timeout: 5000 });
    const chooser = page.waitForEvent('filechooser', { timeout: 10000 });
    await grid.locator('[role="row"]').filter({ hasText: 'من جهازك' }).locator('[role="gridcell"]').first().click();
    await (await chooser).setFiles({ name: 'ملاحظة.txt', mimeType: 'text/plain', buffer: Buffer.from('نص تجريبي من فحص الشاشات.\n', 'utf8') });
    await sleep(3000);
    await capture(ctx, 'more-upload', { screen: 'composer', state: 'a file attached', caption: 'A small text file chosen from the device and uploaded (nothing sent).' });
  });
  await step(ctx, 'more-english', async () => {
    // The language row is on the first tab. On a phone the tab list shows alone until a tab is chosen
    // (Settings/Dialog.tsx), so choose it; on a desktop it is already chosen and choosing it again changes nothing.
    const openGeneral = async () => {
      const opened = await openSettings(ctx);
      await page.locator('[role="tab"]:visible').first().click({ timeout: 5000 });
      await sleep(500);
      return opened;
    };
    const dialog = await openGeneral();
    await (await firstVisible('the language setting', [dialog.getByRole('combobox').filter({ hasText: 'العربية' }), dialog.getByRole('button').filter({ hasText: /^العربية$/ })])).click();
    await sleep(500);
    await (await firstVisible('English', [page.getByRole('option', { name: /^English$/ })])).click();
    ctx.english = true;
    await sleep(1500);
    await capture(ctx, 'more-english-settings', { screen: 'settings', state: 'English interface chosen', caption: 'Settings after choosing English: the interface in English.' });
    await escape(ctx, 2);
    await page.goto(`${BASE}/c/new`);
    await page.getByTestId('text-input').first().waitFor({ timeout: 30000 });
    await sleep(1500);
    await capture(ctx, 'more-english-new-chat', { screen: 'landing', state: 'English interface, new chat', caption: 'A new chat in the English interface.' });
    const again = await openGeneral();
    await (await firstVisible('the language setting', [again.getByRole('combobox').filter({ hasText: 'English' }), again.getByRole('button').filter({ hasText: /^English$/ })])).click();
    await sleep(500);
    await (await firstVisible('العربية', [page.getByRole('option', { name: /العربية/ })])).click();
    ctx.english = false;
    await sleep(1500);
    await capture(ctx, 'more-arabic-again', { screen: 'settings', state: 'Arabic interface chosen again', caption: 'Settings after choosing العربية again.' });
    await escape(ctx, 2);
  });
  if (ctx.english) await arabicAgain(ctx);
  await clearChatsQuietly(ctx);
}

/**
 * After a language step that stopped in the English interface: drop the choice (the client keeps it in the lang cookie
 * and localStorage only, Nav/Settings controls.tsx and store/language.ts) and reload, so the proxy's default lang=ar
 * applies again and the rest of the run, sign-in after log out included, is the Arabic interface.
 */
async function arabicAgain(ctx) {
  const { page } = ctx;
  await page
    .evaluate(() => {
      localStorage.removeItem('lang');
      document.cookie = 'lang=; Max-Age=0; path=/';
    })
    .catch(() => undefined);
  await page.reload().catch(() => undefined);
  await sleep(1500);
  ctx.english = false;
}

/** Log out from the account menu, and /c/new sends the signed-out browser to sign-in again. */
async function logoutSection(ctx) {
  const { page } = ctx;
  await step(ctx, 'logout', async () => {
    await openAccountMenu(ctx);
    await (await firstVisible('log out', [page.getByRole('menuitem', { name: /تسجيل الخروج|log ?out/i })])).click();
    await page.waitForURL(/\/login/, { timeout: 30000 });
    await sleep(800);
    await capture(ctx, 'signed-out-after-logout', { screen: 'signin', state: 'after log out', caption: 'After log out: back on sign-in.' });
    await page.goto(`${BASE}/c/new`);
    await page.waitForURL(/\/login/, { timeout: 30000 });
    await sleep(800);
    await capture(ctx, 'signed-out-redirect-after-logout', { screen: 'signin', state: 'signed-out redirect after log out', caption: 'After log out, /c/new redirects to sign-in again.' });
  });
}

// ------------------------------------------------------------------ the pass

function writeOutputs() {
  let previous = [];
  try {
    previous = JSON.parse(fs.readFileSync(`${PASS}/findings.json`, 'utf8'));
  } catch {
    // first pass
  }
  const findings = lib.mergeFindings(previous, lib.autoFindings(entries.filter((e) => e.screen !== 'not-reached')));
  let previousKnown = [];
  try {
    previousKnown = JSON.parse(fs.readFileSync(`${PASS}/known-items.json`, 'utf8'));
  } catch {
    // first pass
  }
  const known = lib.mergeKnown(previousKnown, lib.knownItems(entries.filter((e) => e.screen !== 'not-reached')));
  const meta = { generatedAt: new Date().toISOString(), base: BASE, runs, sections, notReached, apiFailures: [...apiFailures.entries()].map(([call, n]) => `${call} ×${n}`) };
  fs.writeFileSync(`${PASS}/census.json`, JSON.stringify({ ...meta, entries }, null, 1));
  fs.writeFileSync(`${PASS}/screens.json`, JSON.stringify(screens, null, 1));
  fs.writeFileSync(`${PASS}/findings.json`, JSON.stringify(findings, null, 1));
  fs.writeFileSync(`${PASS}/known-items.json`, JSON.stringify(known, null, 1));
  // count: how often the text was met (twice on one screenshot counts twice); screens: on how many screenshots.
  const texts = [...arabic.entries()].map(([text, seen]) => ({ text, count: seen.count, screens: seen.files.size, shots: seen.shots })).sort((a, b) => b.count - a.count);
  fs.writeFileSync(`${PASS}/arabic-texts.json`, JSON.stringify(texts, null, 1));
  return { findings, known };
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch();
  const started = Date.now();
  try {
    for (const run of runs) {
      const [view, theme] = run.split('-');
      console.log(`run ${run}`);
      const context = await browser.newContext({ ...VIEWPORTS[view], colorScheme: theme, locale: 'ar-JO', timezoneId: 'Asia/Amman' });
      const page = await context.newPage();
      page.setDefaultTimeout(15000);
      page.on('response', (response) => {
        const url = new URL(response.url());
        if (url.pathname.startsWith('/api/') && response.status() >= 400) {
          const key = `${run} ${response.request().method()} ${url.pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/g, ':id')} ${response.status()}`;
          apiFailures.set(key, (apiFailures.get(key) ?? 0) + 1);
        }
      });
      const ctx = { run, view, theme, phone: view === 'phone', context, page, n: 0, reached: [], english: false };
      try {
        await signInStates(ctx);
        const themed = await page.evaluate(() => document.documentElement.classList.contains('dark'));
        if (themed !== (theme === 'dark')) notReached.push({ run, step: 'theme', error: `the page is ${themed ? 'dark' : 'light'}, not ${theme}` });
        if (sections.includes('landing')) await landingSection(ctx);
        if (sections.includes('composer')) await composerSection(ctx);
        if (sections.includes('answer')) await answerSection(ctx);
        if (sections.includes('conversation')) await conversationSection(ctx);
        if (sections.includes('header')) await headerSection(ctx);
        if (sections.includes('account')) await accountSection(ctx);
        if (sections.includes('settings')) await settingsSection(ctx);
        if (sections.includes('routes')) await routesSection(ctx);
        if (sections.includes('cleanup')) await cleanupSection(ctx);
        if (sections.includes('more')) await moreSection(ctx);
        await logoutSection(ctx); // every run, a partial one too: no session is left signed in on staging
      } catch (error) {
        const message = String(error.message ?? error).split('\n')[0];
        notReached.push({ run, step: 'sign-in', error: message });
        console.log(`  run ${run} stopped: ${message}`);
        await capture(ctx, 'not-reached-sign-in', { screen: 'not-reached', state: 'sign-in', caption: `The run stopped at sign-in: ${message}` }).catch(() => undefined);
      }
      console.log(`  ${ctx.n} captures, ${ctx.reached.length} steps reached`);
      await context.close();
      writeOutputs();
    }
  } finally {
    await browser.close();
  }
  const { findings, known } = writeOutputs();
  console.log(`${entries.length} screenshots in ${Math.round((Date.now() - started) / 1000)} s; ${findings.length} findings; ${notReached.length} steps not reached`);
  for (const k of known) console.log(`  ${k.item} ${k.on_screen.padEnd(11)} ${k.point}`);
  for (const miss of notReached) console.log(`  NOT REACHED ${miss.run} ${miss.step}: ${miss.error}`);
  process.exit(notReached.length ? 1 : 0);
})();
