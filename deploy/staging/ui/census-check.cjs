// Census of the customer chat screen: which /api calls the stock client makes in a real session, whether the
// fork's allowlist refused any, and the accessibility checks of the starter gallery (WCAG 2.1 A: keyboard, focus
// visible, text fully readable; plus the RTL and mobile captures). Started by run-rtl-check.mjs --census inside
// mcr.microsoft.com/playwright, in the proxy container's network namespace.
//
// It signs a plan customer in (an app code) and walks every flow a customer has: the gallery by keyboard, a
// featured starter, title generation, regenerate, message edit, feedback, search, a file attach, resume after a
// reload, conversation rename, archive and delete, the archived-chats list, the settings tabs, a language change,
// and logout last. A flow whose control cannot be found FAILS (it is never skipped: a skipped flow is a route
// nobody measured). Every /api response after sign-in is recorded; the run fails on a 403 IQRAA_FORBIDDEN outside
// EXPECTED_DENIED, on any other non-2xx status (401, 5xx, TIER_*; only EXPECTED_NOT_SAVED_YET is accepted), and on
// any flow that did not run. Output: /work/out/census.json, and screenshots in /shots (the workspace
// `.hq/scratch/tiers-ui`). The selectors are read from the client source (client/src), and its interface here is
// Arabic with English where a locale key has no Arabic text, so they use a test id or a structure where one exists.
//
// Chat search is measured only as far as the stack allows: with SEARCH off (staging's compose.yaml) the flow proves
// the client shows no field; it runs a search only when /api/search/enable answers true.
const fs = require('fs');
const { chromium } = require('playwright');
const { nextAppStep, totp } = require('/work/totp.cjs');

const BASE = 'http://localhost:8080';
const OUT = '/work/out';
const SHOTS = '/shots';
const { CUSTOMER_PHONE, CUSTOMER_APP_SECRET, CUSTOMER_APP_LAST_STEP } = process.env;
const LOCAL_PHONE = `0${CUSTOMER_PHONE.slice(4)}`;

/** Routes the trimmed client still calls but the product closes (the controls are hidden; a 403 here is the design). */
const EXPECTED_DENIED = [
  /^GET \/api\/user\/settings\/favorites$/,
  /^POST \/api\/user\/settings\/favorites$/,
  /^GET \/api\/user\/settings\/favorites\/tools$/,
  /^GET \/api\/user\/settings\/skills\/active$/,
  /^GET \/api\/files\/speech\//,
  /^POST \/api\/files\/speech\//,
  // Features a customer does not have; the stock client asks anyway, and copes with the refusal.
  /^GET \/api\/agents\/tools\/calls$/, // code-interpreter results: no tier agent runs code
  /^GET \/api\/agents\/tools\/web_search\/auth$/, // web search is off (closed corpus)
  /^GET \/api\/endpoints\/token-config$/, // per-endpoint limits: it names the custom endpoints
  /^GET \/api\/keys$/, // user-provided API keys
  /^GET \/api\/mcp\/servers$/, // MCP servers
  /^GET \/api\/share\/link\//, // shared links
  /^GET \/api\/tags$/, // bookmarks
];
/**
 * 404s the stock client causes on a conversation it has named but the server has not saved yet: during a first turn
 * it polls these two routes with the new id. Stock code on both sides (no fork hook): the server answers
 * queuedTurnHttp.ts `CONVERSATION_NOT_FOUND` and view.ts `notFound`; the client expects both and does not retry
 * (queuedTurns.ts `retry: false`, Subagents/queries.ts stops on a 404). The subagents 404 has no code, only its error
 * text, which the recorder writes as NO_CODE_CONVERSATION_NOT_FOUND. Any other 404 on these routes still fails.
 */
const EXPECTED_NOT_SAVED_YET = [
  { route: /^\/api\/agents\/chat\/queued-turns$/, code: 'CONVERSATION_NOT_FOUND' },
  { route: /^\/api\/convos\/[^/]+\/subagents$/, code: 'NO_CODE_CONVERSATION_NOT_FOUND' },
];
const TABS = 4; // CUSTOMER_TAB_IDS: general, chat, data, account
const RENAMED_TITLE = 'محادثة مُعاد تسميتها';

(async () => {
  const report = { checks: {}, calls: [], statuses: [] };
  const check = (name, ok, detail) => (report.checks[name] = { ok: Boolean(ok), detail });
  const browser = await chromium.launch();
  const context = await browser.newContext({ locale: 'ar-JO', viewport: { width: 1366, height: 900 } });
  const page = await context.newPage();
  const seen = new Map();
  const pending = [];
  let recording = false;
  // Recorded synchronously, so a refusal that arrives while a flow is ending is never lost; the body is read after.
  page.on('response', (response) => {
    const url = new URL(response.url());
    if (!recording || !url.pathname.startsWith('/api/')) return;
    const key = `${response.request().method()} ${url.pathname} ${response.status()}`;
    if (!seen.has(key)) seen.set(key, '');
    if (response.status() >= 300) {
      pending.push(
        response
          .text()
          .then((body) => {
            const code = /"code"\s*:\s*"([A-Z_]+)"/.exec(body)?.[1] ?? '';
            seen.set(key, code || (/"error"\s*:\s*"Conversation not found"/.test(body) ? 'NO_CODE_CONVERSATION_NOT_FOUND' : ''));
          })
          .catch(() => undefined),
      );
    }
  });

  /** Runs one flow; any thrown error (a control that is not there, a timeout) is a failed check, never a skip. */
  const flow = async (name, body) => {
    try {
      const detail = await body();
      check(name, true, detail ?? 'ran');
    } catch (error) {
      check(name, false, String(error.message ?? error).split('\n')[0]);
      await page.screenshot({ path: `${SHOTS}/fail-${name}.png` }).catch(() => undefined);
      await page.keyboard.press('Escape').catch(() => undefined);
    }
  };
  /**
   * The first of several candidate controls to appear. A page has just loaded when a flow asks (the React app
   * restarts on every goto), so this waits; a control that never appears is still a failed flow.
   */
  const control = async (label, candidates, timeout = 15000) => {
    try {
      return await Promise.any(
        candidates.map(async (candidate) => {
          const found = candidate.first();
          await found.waitFor({ state: 'attached', timeout });
          return found;
        }),
      );
    } catch {
      throw new Error(`no control found for: ${label}`);
    }
  };
  /** Waits for a call the action makes, set up before the action so a fast answer is not missed; 2xx only. */
  const answered = async (label, method, pattern, action, timeout = 30000) => {
    const [response] = await Promise.all([
      page.waitForResponse((r) => r.request().method() === method && pattern.test(r.url()), { timeout }),
      action(),
    ]);
    if (!response.ok()) throw new Error(`${label} answered ${response.status()}`);
    return response;
  };
  /** An answer has finished when the last message offers regenerate again (HoverButtons hides it while submitting). */
  const answerFinished = () => page.getByTestId('regenerate-generation-button').waitFor({ timeout: 90000 });
  /** The phone-width capture closes the sidebar and the client keeps it closed (useSidebarState), as for a customer. */
  const openSidebar = async () => {
    const opener = page.getByTestId('open-sidebar-button');
    await Promise.race([opener.first().waitFor({ timeout: 15000 }), page.getByTestId('close-sidebar-button').first().waitFor({ timeout: 15000 })]);
    if (await opener.count()) await opener.first().click();
    await page.getByTestId('close-sidebar-button').first().waitFor({ timeout: 15000 });
  };
  /** The settings dialog's root has no box of its own (every child is `fixed`), so its tab list is what shows it opened. */
  const openSettings = async () => {
    await page.getByTestId('nav-user').click();
    await page.getByTestId('nav-settings').click();
    const dialog = page.getByRole('dialog').first();
    await dialog.getByRole('tablist').waitFor({ timeout: 15000 });
    return dialog;
  };
  /** Reveal a sidebar row's menu: on a desktop it mounts a tick after the pointer arrives (ConvoActions.tsx). */
  const openRowMenu = async (row) => {
    await row.hover();
    await (await control('conversation options', [row.locator('button[id^="conversation-menu-"]')])).click();
  };
  const ring = (locator) =>
    locator.evaluate((el) => {
      const style = getComputedStyle(el);
      return style.boxShadow !== 'none' || (style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0);
    });

  try {
    const { step, waitMs } = nextAppStep(Number(CUSTOMER_APP_LAST_STEP));
    if (waitMs > 0) await new Promise((resolve) => setTimeout(resolve, waitMs));
    await page.goto(`${BASE}/login`);
    await page.getByTestId('iqraa-identifier').fill(LOCAL_PHONE);
    await page.getByTestId('iqraa-use-app').click();
    await page.getByTestId('iqraa-code').fill(totp(CUSTOMER_APP_SECRET, { step }));
    await page.getByTestId('iqraa-submit-code').click();
    await page.waitForURL(/\/c\//, { timeout: 30000 });
    recording = true;
    await page.goto(`${BASE}/c/new`);
    await page.getByTestId('iqraa-starters-more').waitFor({ timeout: 30000 });
    check('galleryShown', true, 'the starter gallery replaced the stock four');

    await flow('galleryKeyboard', async () => {
      const more = page.getByTestId('iqraa-starters-more');
      await more.focus();
      const moreRing = await ring(more);
      await page.keyboard.press('Enter');
      if ((await more.getAttribute('aria-expanded')) !== 'true') throw new Error('Enter on the toggle did not open the areas');
      await page.keyboard.press('Space');
      if ((await more.getAttribute('aria-expanded')) !== 'false') throw new Error('Space on the toggle did not close the areas');
      await page.keyboard.press('Enter');
      const areas = page.locator('[data-testid^="iqraa-starter-area-"]');
      if ((await areas.count()) < 2) throw new Error('fewer than two area buttons');
      const second = areas.nth(1);
      await second.focus();
      const areaRing = await ring(second);
      await page.keyboard.press('Space');
      if ((await second.getAttribute('aria-pressed')) !== 'true') throw new Error('Space on an area button did not press it');
      const first = areas.first();
      await first.focus();
      await page.keyboard.press('Enter');
      if ((await first.getAttribute('aria-pressed')) !== 'true') throw new Error('Enter on an area button did not press it');
      const chip = page.locator('[data-testid^="iqraa-starter-"]:not([data-testid*="area"]):not([data-testid*="more"])').first();
      await chip.focus();
      const chipRing = await ring(chip);
      // Tab reaches the chip from the toggle without a mouse.
      await more.focus();
      await page.keyboard.press('Tab');
      const reached = await page.evaluate(() => document.activeElement?.getAttribute('data-testid') ?? '');
      if (!moreRing || !areaRing || !chipRing) throw new Error(`no visible focus ring: toggle ${moreRing}, area ${areaRing}, chip ${chipRing}`);
      if (!/^iqraa-starter-/.test(reached)) throw new Error(`Tab from the toggle reached ${reached || 'nothing'}`);
      return 'toggle, area buttons and chips work with Enter, Space and Tab and show a focus ring';
    });

    await flow('galleryTextReadable', async () => {
      const clipped = await page.evaluate(() =>
        [...document.querySelectorAll('[data-testid^="iqraa-starter-"]')]
          .filter((el) => el.querySelector('span'))
          .filter((el) => {
            const span = el.querySelector('span');
            return span.scrollHeight > span.clientHeight + 1 || getComputedStyle(span).webkitLineClamp !== 'none';
          })
          .map((el) => el.getAttribute('data-testid')),
      );
      if (clipped.length) throw new Error(`clipped prompt text: ${clipped.join(', ')}`);
      return 'every visible prompt shows its whole text';
    });

    await flow('rtlAndMobileCaptures', async () => {
      fs.mkdirSync(SHOTS, { recursive: true });
      const dir = await page.evaluate(() => document.documentElement.dir);
      if (dir !== 'rtl') throw new Error(`the page is ${dir}, not rtl`);
      await page.screenshot({ path: `${SHOTS}/gallery-rtl-desktop.png` });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(500);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      await page.screenshot({ path: `${SHOTS}/gallery-rtl-mobile.png` });
      await page.setViewportSize({ width: 1366, height: 900 });
      if (overflow > 1) throw new Error(`the gallery overflows a 390 px screen by ${overflow} px`);
      return `captures in ${SHOTS}: gallery-rtl-desktop.png, gallery-rtl-mobile.png`;
    });

    let titleResponse;
    await flow('starterAnswered', async () => {
      // A featured prompt is also listed under its open area, so the same chip is on screen twice.
      const chip = page.getByTestId('iqraa-starter-civil-01').first();
      // The title can answer before the text shows, so the wait for it starts before the turn does.
      titleResponse = page.waitForResponse((r) => /\/api\/convos\/gen_title\//.test(r.url()) && r.status() === 200, { timeout: 120000 }).catch(() => null);
      await chip.focus();
      await page.keyboard.press('Enter');
      await page.getByText('MOCK_OK').first().waitFor({ timeout: 90000 });
      return 'a featured starter was sent from the keyboard and the mock answered';
    });

    await flow('titleGenerated', async () => {
      if (!(await titleResponse)) throw new Error('GET /api/convos/gen_title never answered 200');
      return 'GET /api/convos/gen_title answered 200';
    });

    await flow('feedback', async () => {
      // The thumbs carry only a `title`, and `com_ui_feedback_positive` has no Arabic text: it reads "Love this" here.
      const up = await control('feedback (thumbs up)', [page.getByRole('button', { name: /love this/i }), page.locator('.agent-turn button[aria-haspopup="menu"][aria-pressed]')]);
      await up.click();
      // The thumb only opens a list of reasons (Feedback.tsx); the rating is sent when one is chosen.
      const reason = await control('feedback reason', [page.locator('.popover-animate button[aria-pressed]')]);
      await answered('the feedback', 'PUT', /\/api\/messages\/[^/]+\/[^/]+\/feedback/, () => reason.click());
      await page.locator('.agent-turn button[aria-pressed="true"]').first().waitFor({ timeout: 15000 });
      return 'PUT .../feedback answered and the thumb shows as chosen';
    });

    await flow('regenerate', async () => {
      const regenerate = await control('regenerate', [page.getByTestId('regenerate-generation-button')]);
      await answered('the regenerated turn', 'POST', /\/api\/agents\/chat\//, () => regenerate.click(), 60000);
      await answerFinished();
      await page.getByText('MOCK_OK').first().waitFor({ timeout: 30000 });
      return 'the regenerated turn ran';
    });

    await flow('messageEdit', async () => {
      const user = page.locator('.user-turn').first();
      await user.hover();
      const edit = await control('edit message', [user.locator('button[id^="edit-"]')]);
      await edit.click();
      const box = page.getByTestId('message-text-editor');
      await box.fill('ما حكم العربون في القانون المدني؟ (معدلة)');
      // Cancel, save (no answer), then the one that resubmits; `com_ui_update_rerun` has no Arabic text either.
      const resubmit = await control('resubmit edit', [page.locator('section:has([data-testid="message-text-editor"]) footer button').last()]);
      await answered('the edited message', 'POST', /\/api\/agents\/chat\//, () => resubmit.click(), 60000);
      await answerFinished();
      await page.locator('.user-turn', { hasText: '(معدلة)' }).first().waitFor({ timeout: 30000 });
      await page.getByText('MOCK_OK').first().waitFor({ timeout: 30000 });
      return 'an edited message was resubmitted and answered';
    });

    await flow('resumeAfterReload', async () => {
      await page.goto(`${BASE}/c/new`);
      const input = page.locator('#prompt-textarea, textarea').first();
      await input.waitFor({ timeout: 30000 });
      await input.fill('SLOW_STREAM:300 resume census');
      await input.press('Enter');
      await page.getByText('STREAMED_PIECE').first().waitFor({ timeout: 60000 });
      // The address names the conversation a moment after the text starts: a reload on /c/new has nothing to resume.
      await page.waitForURL(/\/c\/(?!new)[^/]+$/, { timeout: 30000 });
      await page.reload();
      await page.getByText('STREAMED_PIECE').first().waitFor({ timeout: 60000 });
      await answerFinished();
      return 'the page reloaded mid-answer and the stream was picked up again';
    });

    await flow('searchChats', async () => {
      const [enable] = await Promise.all([
        page.waitForResponse((r) => new URL(r.url()).pathname === '/api/search/enable', { timeout: 30000 }),
        page.goto(`${BASE}/c/new`),
      ]);
      const enabled = (await enable.text()).trim();
      if (enable.status() !== 200 || !['true', 'false'].includes(enabled)) throw new Error(`/api/search/enable answered ${enable.status()} ${enabled}`);
      await openSidebar();
      await page.getByTestId('convo-item').first().waitFor({ timeout: 15000 });
      const field = page.getByTestId('nav-search-input');
      if (enabled === 'false') {
        // SEARCH is off on this stack (compose.yaml), so ConversationsSection renders no field: the absence is by design.
        if (await field.count()) throw new Error('search is off but the client shows the field');
        return 'search is OFF on this stack: /api/search/enable answered false and the client shows no field; a search itself was not run';
      }
      const search = await control('chat search', [field]);
      // The client searches through the chat list (ConversationsSection passes `search` to /api/convos).
      await answered('the search', 'GET', /\/api\/convos\?.*search=/, () => search.fill('العربون'));
      await search.fill('');
      return 'GET /api/convos?search= answered';
    });

    await flow('fileAttach', async () => {
      await page.goto(`${BASE}/c/new`);
      const input = page.locator('input[type="file"]').first();
      await input.waitFor({ state: 'attached', timeout: 30000 });
      await input.setInputFiles({ name: 'census-note.txt', mimeType: 'text/plain', buffer: Buffer.from('ملاحظات العقد: المادة الأولى.') });
      await page.waitForResponse((r) => r.request().method() === 'POST' && /\/api\/files(\?|$)/.test(r.url()), { timeout: 30000 });
      return 'POST /api/files answered';
    });

    await flow('noSpeechControls', async () => {
      await page.goto(`${BASE}/c/new`);
      await page.getByTestId('text-input').first().waitFor({ timeout: 30000 });
      // The server refuses speech, so neither the microphone nor the read-aloud button may be offered.
      if (await page.locator('#audio-recorder').count()) throw new Error('the composer shows a microphone');
      await openSidebar();
      await page.getByTestId('convo-item').first().click();
      await answerFinished();
      if (await page.getByRole('button', { name: /قراءة بصوت عالٍ|read aloud/i }).count()) throw new Error('a message offers read aloud');
      // The header's menu is shared with sharing: with shared links off it may only offer the export of the customer's own chat.
      await page.locator('#export-menu-button').click();
      const offered = (await page.getByRole('menuitem').allInnerTexts()).join(' | ');
      await page.screenshot({ path: `${SHOTS}/export-menu.png` });
      await page.keyboard.press('Escape');
      if (/share|مشاركة/i.test(offered)) throw new Error(`the header menu offers sharing: ${offered}`);
      return `no microphone in the composer, no read aloud on a message; the header menu offers: ${offered}`;
    });

    await flow('conversationRenameArchiveDelete', async () => {
      await openSidebar();
      const rows = page.getByTestId('convo-item');
      await control('a conversation in the sidebar', [rows]);
      // Projects and Pinned ask for what a customer is refused, and the client retries a refusal three times (about
      // 8 s) before their spinner and placeholder leave. One that never leaves fails here.
      await page.waitForFunction(() => !document.querySelector('[role="region"] .spinner, [role="region"] .animate-pulse'), null, { timeout: 30000 });
      const listed = await rows.count();
      await page.screenshot({ path: `${SHOTS}/sidebar-after-chat.png` });
      if (listed < 2) throw new Error(`the sidebar lists ${listed} conversation(s) after two chats`);

      await openRowMenu(rows.first());
      await page.screenshot({ path: `${SHOTS}/sidebar-conversation-menu.png` });
      // A customer cannot use projects: neither the section nor the menu row may offer them.
      if (await page.getByRole('menuitem', { name: /change project/i }).count()) throw new Error('the conversation menu offers Change project');
      if (await page.getByText('Projects', { exact: true }).count()) throw new Error('the sidebar shows Projects');
      if (seen.has('GET /api/projects')) throw new Error('the client still asks for projects');
      await (await control('rename', [page.getByRole('menuitem', { name: /إعادة تسمية|rename/i })])).click();
      const title = await control('new title', [rows.locator('input')]);
      await title.fill(RENAMED_TITLE);
      await answered('the rename', 'POST', /\/api\/convos\/update/, () => title.press('Enter'));
      const renamed = rows.filter({ hasText: RENAMED_TITLE }).first();
      await renamed.waitFor({ timeout: 15000 });

      await openRowMenu(renamed);
      const archive = await control('archive', [page.getByRole('menuitem', { name: /أرشفة|archive/i })]);
      await answered('the archive', 'POST', /\/api\/convos\/archive/, () => archive.click());
      await renamed.waitFor({ state: 'detached', timeout: 15000 });

      await openRowMenu(rows.first());
      await (await control('delete', [page.getByRole('menuitem', { name: /حذف|delete/i })])).click();
      const confirm = await control('confirm delete', [page.getByRole('dialog').getByRole('button', { name: /حذف|delete/i })]);
      await answered('the delete', 'DELETE', /\/api\/convos(\?|$)/, () => confirm.click());
      await page.waitForFunction((before) => document.querySelectorAll('[data-testid="convo-item"]').length < before, listed - 1, { timeout: 15000 });
      return `${listed} conversations listed; one renamed and archived, one deleted`;
    });

    await flow('settingsTabs', async () => {
      const dialog = await openSettings();
      const tabs = dialog.getByRole('tab');
      const count = await tabs.count();
      if (count !== TABS) throw new Error(`a customer sees ${count} settings tabs, not ${TABS}`);
      for (let index = 0; index < count; index += 1) {
        await tabs.nth(index).click();
        await page.waitForTimeout(300);
        await page.screenshot({ path: `${SHOTS}/settings-tab-${index + 1}.png` });
        if (await dialog.getByText(/ذاكرة التخزين المؤقت للنص المنطوق|TTS cache/i).count()) throw new Error('settings offers the speech cache row');
      }
      await page.screenshot({ path: `${SHOTS}/settings-end.png` });
      await page.keyboard.press('Escape');
      await dialog.getByRole('tablist').waitFor({ state: 'detached', timeout: 15000 });
      return `${count} tabs opened`;
    });

    await flow('archivedChatsAndLanguage', async () => {
      // Archived chats are in the account menu in this client (AccountSettings.tsx), not in the settings dialog.
      await page.getByTestId('nav-user').click();
      const archived = await control('archived chats', [page.getByRole('menuitem', { name: /المؤرشفة|archived/i })]);
      await answered('the archived list', 'GET', /\/api\/convos\?.*isArchived=true/, () => archived.click());
      await page.getByRole('dialog').getByText(RENAMED_TITLE).first().waitFor({ timeout: 15000 });
      await page.screenshot({ path: `${SHOTS}/archived-chats.png` });
      await page.keyboard.press('Escape');
      await page.getByRole('dialog').first().waitFor({ state: 'detached', timeout: 15000 });

      const dialog = await openSettings();
      await dialog.getByRole('tab', { name: /^(عام|general)$/i }).click();
      const language = () => control('language', [dialog.getByRole('combobox', { name: /اللغة|language/i })]);
      await (await language()).click();
      await (await control('the English option', [page.getByRole('option', { name: /English/ })])).click();
      await dialog.getByRole('tab', { name: /^general$/i }).waitFor({ timeout: 15000 });
      // At a person's pace: reopened in the same instant the labels change, the list still holds its last choice in its
      // search field (measured: at 0 ms always, from 100 ms never), which no customer can do.
      await page.waitForTimeout(500);
      await (await language()).click();
      await (await control('the Arabic option', [page.getByRole('option', { name: /العربية/ })])).click();
      await dialog.getByRole('tab', { name: /^عام$/ }).waitFor({ timeout: 15000 });
      const dir = await page.evaluate(() => document.documentElement.dir);
      if (dir !== 'rtl') throw new Error(`the page is ${dir} after changing back to Arabic`);
      await page.keyboard.press('Escape');
      await dialog.getByRole('tablist').waitFor({ state: 'detached', timeout: 15000 });
      return 'the archived list showed the archived chat and the language changed there and back';
    });

    await flow('logoutLast', async () => {
      await page.getByTestId('nav-user').click();
      await (await control('log out', [page.getByRole('menuitem', { name: /تسجيل الخروج|log ?out/i })])).click();
      await page.waitForURL(/\/login/, { timeout: 30000 });
      return 'POST /api/auth/logout, back on /login';
    });
    await page.waitForTimeout(1500);
  } catch (error) {
    report.error = String(error.stack ?? error);
  } finally {
    await browser.close();
  }
  await Promise.all(pending);
  report.calls = [...seen.entries()].map(([call, code]) => `${call}${code ? ` ${code}` : ''}`).sort();
  const parse = (call) => {
    const [method, route, status, code] = call.split(' ');
    return { call, method, route, status: Number(status), code: code ?? '' };
  };
  const parsed = report.calls.map(parse);
  const expected = (entry) =>
    (entry.code === 'IQRAA_FORBIDDEN' && EXPECTED_DENIED.some((rule) => rule.test(`${entry.method} ${entry.route}`))) ||
    (entry.method === 'GET' && entry.status === 404 && EXPECTED_NOT_SAVED_YET.some((rule) => rule.code === entry.code && rule.route.test(entry.route)));
  const refused = parsed.filter((entry) => entry.code === 'IQRAA_FORBIDDEN' && !expected(entry));
  const failed = parsed.filter((entry) => entry.status >= 400 && !expected(entry));
  check('noRouteTheClientNeedsIsRefused', refused.length === 0, refused.length ? refused.map((e) => e.call).join('; ') : `${parsed.length} distinct calls, none refused beyond the expected denials`);
  check('noUnexpectedFailureStatus', failed.length === 0, failed.length ? failed.map((e) => e.call).join('; ') : 'every other call answered 2xx or 3xx');
  report.pass = !report.error && Object.values(report.checks).every((c) => c.ok);
  fs.writeFileSync(`${OUT}/census.json`, JSON.stringify(report, null, 2));
  for (const call of report.calls) console.log(`  ${call}`);
  for (const [name, c] of Object.entries(report.checks)) console.log(`${c.ok ? 'ok  ' : 'FAIL'} ${name}: ${c.detail}`);
  if (report.error) console.log(`error: ${report.error}`);
  console.log(report.pass ? 'CENSUS PASS' : 'CENSUS FAIL');
  process.exit(report.pass ? 0 : 1);
})();
