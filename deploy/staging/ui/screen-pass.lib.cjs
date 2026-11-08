// The decisions of the screen pass (ui/screen-pass.cjs), kept out of the browser so they can be tested on the host:
//   node --test ui/screen-pass.test.mjs      (from deploy/staging)
// The browser only reports facts about each text node (its text, whether it sits in code, in the answer's model
// text, in the customer's own message ...); everything that decides what counts as English in the interface, whether
// the tier heading keeps its Arabic letters joined, and what each known open item shows now is here.
'use strict';

/**
 * Latin a customer may see (REQ-UI-001: proper names, model ids and code): the brand, model ids, the names printed on
 * keys (Ctrl+D, Shift+Enter, `ENTER`), the names of file formats (Markdown, LaTeX, JSON) and web addresses (a source
 * such as jordan-lawyer.com). Combinations go before single keys, so «Ctrl+D» leaves no «D» behind.
 */
// In a combination any key; alone, never «Delete», «Tab» or «Space», and the others only beside Arabic (BESIDE_ARABIC).
const KEY = '(?:Alt|ALT|Ctrl|CTRL|Control|Shift|SHIFT|Cmd|Command|Option|Enter|ENTER|Esc|Escape|Tab|Backspace|Delete|Space|F\\d{1,2})';
const LONE_KEY = '(?:Alt|ALT|Ctrl|CTRL|Shift|SHIFT|Cmd|Enter|ENTER|Esc|Backspace|F\\d{1,2})';
const ALLOWED = [
  /Iqraa LAW AI/g,
  /\b(?:mock-model|gpt-[\w.-]+|o\d(?:-[\w.-]+)?|claude-[\w.-]+|gemini-[\w.-]+)\b/gi,
  new RegExp(`(?:\\b|⌘\\s*\\+\\s*)${KEY}(?:\\s*\\+\\s*(?:${KEY}|[A-Za-z0-9/.,;]))+`, 'g'),
  /\b(?:markdown|LaTeX|JSON|CSV|PDF)\b|\(\.md\)/gi,
  /\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|jo)\b/gi,
];
/**
 * Allowed only in a text that has Arabic in it: a key's name alone («Enter للإرسال») and the apps a copy is pasted
 * into («مثل Teams وWord»). «Enter», «Shift» and «Word» are English words too, so a label that reads just one of them
 * is English in the interface.
 */
const ARABIC = /[؀-ۿ]/;
const BESIDE_ARABIC = [new RegExp(`\\b${LONE_KEY}\\b`, 'g'), /\b(?:Teams|Outlook|Word|Excel)\b/g];
/**
 * The staging mock's markers and this pass's own content: test content wherever it shows (a title, a toast, a live
 * region). Markdown eats the underscores in some places («MOCKOK», «TOOLRESULTSEEN»), so they are optional. The pass
 * also uploads «ملاحظة.txt», and its accounts are named «Staging <label>» (lib.mjs newAccount: «Staging pass»,
 * «Staging pass-staff»), which the user's turn reads out.
 */
const MOCK = [
  /\bARABIC_?DEMO\b/g,
  /\bTOOL_?ROUNDS:\d+/g,
  /\bSLOW_?STREAM:\d+/g,
  /\bMOCK_?(?:OK|TITLE|SUMMARY)\b/g,
  /\bSTREAMED_?PIECE\b/g,
  /\bTOOL_?RESULT_?SEEN\b/g,
  /ملاحظة\.txt/g,
  /\bStaging pass(?:-staff)?\b/g,
];
/** Inside the brand's own components (Wordmark, BrandFooter) only the brand's words are allowed. */
const BRAND_WORDS = /\b(?:Iqraa|LAW|AI)\b/g;

const hasLatin = (text) => /[A-Za-z]/.test(String(text ?? ''));

/** What remains of `text` once the allowed Latin and the mock's markers are taken out. */
function latinRemainder(text, extra = []) {
  let rest = String(text ?? '');
  const beside = ARABIC.test(rest) ? BESIDE_ARABIC : [];
  for (const pattern of [...ALLOWED, ...beside, ...MOCK, ...extra]) rest = rest.replace(pattern, ' ');
  return rest;
}

/**
 * Code: a <code>, <kbd> or <samp> element, or a <pre> in an answer's turn. A bare <pre> elsewhere is the interface: the
 * error page prints upstream's English «An unexpected error occurred» in one. A census written before the pass
 * reported these facts has only `inCode` (any of them, a <pre> anywhere too) and keeps that reading.
 */
function inCode(record) {
  if (record.inCodeElement === undefined && record.inPre === undefined) return Boolean(record.inCode);
  return Boolean(record.inCodeElement || (record.inPre && record.inAgentTurn));
}

/**
 * Where a text node sits, from the facts the browser reported: code (inline or block), the brand's components, the
 * language list, the model's answer text, the customer's own message, or the interface itself. Content is not interface text: the
 * demo answer cites «(Article 107)» and `shard-map.json`, and the customer typed `ARABIC_DEMO`.
 */
function zoneOf(record) {
  if (inCode(record)) return 'code';
  if (record.inBrand) return 'brand';
  if (record.inLanguageList) return 'language';
  // The pane's «what the answer said here, in its words» quotes the model (NoTextView: iqraa-claim).
  if (record.inAnswerText || (record.testids ?? []).includes('iqraa-claim')) return 'answer';
  if (record.inUserMessage) return 'user';
  return 'ui';
}

/**
 * The census verdict for one record: 'no-latin' (nothing to say), 'allowlisted' (only the brand, a model id or a
 * mock marker), 'content:<zone>' (model text, the customer's own words, code) or 'ui' (English in the interface,
 * which REQ-UI-001 forbids).
 */
function classify(record) {
  if (!hasLatin(record.text)) return 'no-latin';
  const zone = zoneOf(record);
  if (zone === 'brand') return hasLatin(latinRemainder(record.text, [BRAND_WORDS])) ? 'ui' : 'allowlisted';
  // The language list names each language in itself («English», «Deutsch»): proper names, by convention.
  if (zone === 'language') return 'allowlisted';
  if (zone !== 'ui') return `content:${zone}`;
  // A key cap on its own («X», «/»): the key's name.
  if (/^[A-Za-z0-9]$/.test(String(record.text).trim())) return 'allowlisted';
  return hasLatin(latinRemainder(record.text)) ? 'ui' : 'allowlisted';
}

/** A census entry with every record's zone and verdict worked out again (after a change to the rules above). */
function reclassify(entry) {
  const again = (record) => ({ ...record, zone: zoneOf(record), verdict: classify(record) });
  return { ...entry, texts: (entry.texts ?? []).map(again), attributes: (entry.attributes ?? []).map(again) };
}

/**
 * Whether the animated tier heading keeps every word whole (O-35: the stock SplitText drew one inline-block per
 * letter, «عقل سرىع»). `units` are the texts of the heading's animated children in DOM order (none: one unit, the
 * whole text). Joined when the units, split at white space, give back exactly the heading's words, no letter
 * spacing is set, and no unit is `clipped` (cut by the line's overflow while it rises: whole words, letters apart on
 * screen). `offending` lists the units that are not whole words or are cut.
 */
function headingJoin(text, units, letterSpacing = 'normal', clipped = []) {
  const words = String(text ?? '').split(/\s+/).filter(Boolean);
  const parts = (units?.length ? units : [text]).map((unit) => String(unit ?? '').replace(/ /g, ' '));
  const unitWords = parts.flatMap((unit) => unit.split(/\s+/).filter(Boolean));
  const whole = new Set(words);
  const offending = parts.map((unit) => unit.trim()).filter((unit) => unit && unit.split(/\s+/).some((word) => !whole.has(word)));
  const spaced = !['normal', '0px', '0', ''].includes(String(letterSpacing ?? 'normal'));
  const cut = (clipped ?? []).map((unit) => String(unit).trim()).filter(Boolean);
  const joined = words.length > 0 && !spaced && !cut.length && unitWords.length === words.length && unitWords.every((word, i) => word === words[i]);
  return {
    joined,
    words: words.length,
    units: parts.length,
    offending: [...offending, ...cut.filter((unit) => !offending.includes(unit)).map((unit) => `${unit} (clipped)`)],
    letterSpacing: String(letterSpacing ?? 'normal'),
  };
}

/** The interface Latin of one census entry (visible text, or the attributes and screen-reader text). */
function uiLatin(entry, { attributes = false } = {}) {
  const list = attributes ? entry.attributes ?? [] : entry.texts ?? [];
  return list.filter((record) => record.verdict === 'ui');
}

/**
 * A heading drawn apart on screen: not joined (letters split, spaced, or whole words cut by the line), and visible
 * enough to read (a unit at opacity 0.3 or more); a word still fully faded out shows nothing to misread.
 */
function drawnApart(heading) {
  if (!heading || heading.joined) return false;
  const opacities = (heading.opacities ?? []).map(Number).filter((n) => !Number.isNaN(n));
  return !opacities.length || Math.max(...opacities) >= 0.3;
}

const textMatch = (pattern, { attributes = false } = {}) => (entry) => {
  const hit = [...(entry.texts ?? []), ...(attributes ? entry.attributes ?? [] : [])].find((record) => pattern.test(String(record.text ?? '').trim()));
  return hit ? `«${String(hit.text).trim().slice(0, 80)}»${hit.attr ? ` (${hit.attr})` : ''}` : null;
};

/**
 * Every point of the known open items (OPEN-items.md O-35, O-37, O-38, N-08) with the screens that can show it and a
 * test on one census entry. `defect: 'present'` is still there when a reached screen matches; `defect: 'absent'`
 * is still there when no reached screen matches (the footer that should be on sign-in).
 */
const KNOWN_POINTS = [
  { item: 'O-35', point: 'Settings row «Search settings» in English', screens: /^settings$/, defect: 'present', test: textMatch(/Search settings/i) },
  { item: 'O-35', point: 'Settings «Data & Privacy» in English', screens: /^settings$/, states: /البيانات والخصوصية|Data/, defect: 'present', test: textMatch(/Data\s*(?:&|and)\s*Privacy/i) },
  { item: 'O-35', point: 'Settings row «Clock Format» in English', screens: /^settings$/, defect: 'present', test: textMatch(/Clock Format/i) },
  { item: 'O-35', point: 'Settings «Two-Factor Authentication» in English', screens: /^settings$/, states: /الحساب|Account/, defect: 'present', test: textMatch(/Two-Factor Authentication/i) },
  {
    item: 'O-35',
    point: 'An English toast (after deleting a conversation)',
    screens: /^conversation$/,
    states: /toast/,
    defect: 'present',
    test: (entry) => {
      const hit = (entry.texts ?? []).find((record) => record.inToast && record.verdict === 'ui');
      return hit ? `toast «${String(hit.text).trim().slice(0, 80)}»` : null;
    },
  },
  { item: 'O-35', point: 'The language row shows raw «ar»', screens: /^settings$/, defect: 'present', test: textMatch(/^ar$/) },
  { item: 'O-35', point: 'The chat direction row reads «ltr»', screens: /^settings$/, defect: 'present', test: textMatch(/^(?:ltr|rtl|auto)$/i) },
  {
    item: 'O-35',
    point: 'The animated tier heading draws Arabic letters apart («عقل سرىع»)',
    screens: /^landing$/,
    states: /heading/,
    defect: 'present',
    test: (entry) => (drawnApart(entry.heading) ? `units ${JSON.stringify(entry.heading.offending.slice(0, 6))} of «${entry.heading.text}», opacity ${entry.heading.opacities?.join('/') ?? '?'}` : null),
  },
  // The screens that can show a point: an answer that used the library, the sidebar with a pinned chat, the open
  // tier picker, so the shot a point cites is one where it could be seen.
  { item: 'O-35', point: '«Ran 3 actions» on an answer that used the library', screens: /^answer$/, states: /used the library|record of the library calls/, defect: 'present', test: textMatch(/\bRan \d+ actions?\b/i, { attributes: true }) },
  { item: 'O-35', point: '«legal-search ×3» on an answer that used the library', screens: /^answer$/, states: /used the library|record of the library calls/, defect: 'present', test: textMatch(/legal-search/i, { attributes: true }) },
  { item: 'O-35', point: 'Sidebar heading «Chats»', screens: /^sidebar$/, defect: 'present', test: textMatch(/^Chats$/) },
  { item: 'O-35', point: 'Sidebar heading «Pinned»', screens: /^sidebar$/, states: /pinned/, defect: 'present', test: textMatch(/^Pinned$/) },
  { item: 'O-35', point: 'Sidebar empty state «No chats yet»', screens: /^sidebar$/, defect: 'present', test: textMatch(/No chats\b.*\byet/i) },
  { item: 'O-35', point: 'Tier picker search «Search models»', screens: /^header$/, states: /tier picker/, defect: 'present', test: textMatch(/Search models/i, { attributes: true }) },
  { item: 'O-35', point: 'Account menu «Help»', screens: /^account$/, defect: 'present', test: textMatch(/^Help\b/i) },
  {
    item: 'O-35',
    point: 'The share-style Export/Share icon in the chat header',
    screens: /^header$/,
    states: /Export\/Share menu/,
    defect: 'present',
    // The header button itself may stay (it holds export); the defect is a share glyph or a share label while sharing is off.
    test: (entry) => {
      const button = entry.probes?.exportButton;
      if (!button || !(/share/i.test(button.icon ?? '') || /share|مشاركة/i.test(button.label ?? ''))) return null;
      return `#export-menu-button label «${button.label}», icon ${button.icon || 'unknown'}`;
    },
  },
  {
    item: 'O-37',
    point: 'The sign-in screen shows «Iqraa LAW AI»',
    screens: /^signin$/,
    defect: 'absent',
    test: (entry) => (entry.probes?.brandFooter?.visible && /Iqraa LAW AI/.test(entry.probes.brandFooter.text) ? `footer «${entry.probes.brandFooter.text}»` : null),
  },
  {
    item: 'O-38',
    point: 'Browser tab title «LibreChat»',
    screens: /./,
    defect: 'present',
    test: (entry) => (/librechat/i.test(entry.title ?? '') ? `document.title «${entry.title}»` : null),
    // In a chat the tab shows the chat's title, so «gone» says which titles the captures had.
    goneEvidence: (reached) => {
      const brand = reached.filter((entry) => entry.title === 'Iqraa LAW AI').length;
      return `no capture's title contains LibreChat (${brand} «Iqraa LAW AI», ${reached.length - brand} a chat's own title)`;
    },
  },
  { item: 'O-38', point: 'Sign-in logo alt text «LibreChat»', screens: /^(?:signin|signup)$/, defect: 'present', test: textMatch(/librechat/i, { attributes: true }) },
  {
    item: 'O-38',
    point: 'The Help menu opens librechat.ai',
    screens: /^account$/,
    defect: 'present',
    test: (entry) => {
      const link = (entry.probes?.links ?? []).find((href) => /librechat\.ai/i.test(href));
      return link ? `link ${link}` : null;
    },
  },
  {
    item: 'O-38',
    point: 'The name LibreChat in any visible text or attribute',
    screens: /./,
    defect: 'present',
    test: textMatch(/librechat/i, { attributes: true }),
  },
  {
    item: 'O-38',
    point: 'Installed-app manifest (name LibreChat, lang en)',
    screens: /./,
    defect: 'present',
    test: (entry) => {
      const m = entry.probes?.manifest;
      return m && (/librechat/i.test(`${m.name} ${m.short_name}`) || /^en/i.test(m.lang ?? '')) ? `manifest name «${m.name}», short_name «${m.short_name}», lang «${m.lang}»` : null;
    },
  },
  {
    item: 'O-38',
    point: 'Authenticator entry named LibreChat',
    screens: /./,
    defect: 'present',
    test: (entry) => (/librechat/i.test(entry.probes?.authenticatorLabel ?? '') ? `otpauth label «${entry.probes.authenticatorLabel}»` : null),
  },
  {
    item: 'N-08',
    point: 'The + palette in the composer',
    screens: /^composer$/,
    defect: 'present',
    test: (entry) => (entry.probes?.palette ? `composer-palette-button «${entry.probes.palette}»` : null),
  },
  {
    item: 'N-08',
    point: 'The effort / thinking control in the composer',
    screens: /^composer$/,
    defect: 'present',
    test: (entry) => (entry.probes?.thinking ? `«${entry.probes.thinking}»` : null),
  },
  {
    item: 'N-08',
    point: 'The hint line under the composer',
    screens: /^composer$/,
    defect: 'present',
    test: (entry) => (entry.probes?.hint ? `#composer-hint (screen-reader text) «${entry.probes.hint}»` : null),
  },
];

/**
 * What the screens show now for every known point: 'still there', 'gone', or 'not reached' (no census entry of a
 * screen that can show it). `shot` is the first screenshot showing it, else the first that could have.
 */
function knownItems(entries, points = KNOWN_POINTS) {
  const arabic = arabicInterface(entries);
  return points.map(({ item, point, screens, states, defect, test, goneEvidence }) => {
    const reached = arabic.filter((entry) => screens.test(entry.screen ?? '') && (!states || states.test(entry.state ?? '')));
    if (!reached.length) return { item, point, on_screen: 'not reached', shot: '', evidence: 'no screen of this kind was captured' };
    const hits = reached.map((entry) => ({ entry, evidence: test(entry) })).filter((hit) => hit.evidence);
    const there = defect === 'present' ? hits.length > 0 : hits.length === 0;
    const shown = hits[0]?.entry ?? reached[0];
    let evidence;
    if (hits.length) evidence = `${hits.length} of ${reached.length} captures: ${hits[0].evidence} (${hits[0].entry.file})`;
    else if (goneEvidence) evidence = goneEvidence(reached);
    else evidence = `none of ${reached.length} captures (${reached.slice(0, 3).map((e) => e.file).join(', ')}${reached.length > 3 ? ' ...' : ''})`;
    return { item, point, on_screen: there ? 'still there' : 'gone', shot: shown.file, evidence };
  });
}

/**
 * The known-items file after a pass: the pass's points, then the points read by hand that no census shows (the email
 * subject, the page's description ...), kept as `"source": "review"` entries the way findings.json keeps reviewed
 * findings. A reviewed point the pass now covers itself (same item and point) gives way to the pass's own.
 */
function mergeKnown(previous, fresh) {
  const ids = new Set(fresh.map((k) => `${k.item}|${k.point}`));
  const kept = (Array.isArray(previous) ? previous : []).filter((k) => k && k.source === 'review' && !ids.has(`${k.item}|${k.point}`));
  return [...fresh, ...kept];
}

/**
 * The captures of the Arabic interface. A state that switches the interface to English on purpose (the language
 * setting) marks its captures `probes.interfaceLanguage: 'en'`: English there is the customer's choice, not a gap.
 */
function arabicInterface(entries) {
  return entries.filter((entry) => entry.probes?.interfaceLanguage !== 'en');
}

/** The known point a Latin string belongs to, so a finding names its open item; REQ-UI-001 otherwise. */
function itemOf(text) {
  const t = String(text ?? '').trim();
  for (const p of KNOWN_POINTS) {
    if (p.item !== 'O-35' && p.item !== 'O-38') continue;
    try {
      if (p.test({ texts: [{ text: t }], attributes: [] })) return p.item;
    } catch {
      // a point that reads probes, not text
    }
  }
  return /librechat/i.test(t) ? 'O-38' : 'REQ-UI-001';
}

/** The record of a library answer: the last record on screen that lists calls, or null. */
const lastRecord = (entry) => [...(entry?.probes?.records ?? [])].reverse().find((record) => record.calls?.length) ?? null;
const recordText = (record) => record.calls.map((call, i) => `call ${i + 1}: ${call.chips} chip(s), «${call.line}»`).join('; ') + (record.status ? `; status «${record.status}»` : '');

/**
 * The record of the library calls must say the same thing live and when the chat is opened again: per run, the record
 * captured right after the library answer against the record of the same chat reopened from the sidebar (the header
 * screens). A call that shows a different number of article chips, or a status line that comes or goes, is a finding.
 */
function recordDrift(entries) {
  const out = [];
  const runs = [...new Set(entries.map((entry) => `${entry.viewport}-${entry.theme}`))];
  for (const run of runs) {
    const mine = entries.filter((entry) => `${entry.viewport}-${entry.theme}` === run);
    const live = mine.find((entry) => entry.screen === 'answer' && /record of the library calls/.test(entry.state ?? '') && lastRecord(entry));
    const later = mine.find((entry) => entry.screen === 'header' && lastRecord(entry));
    if (!live || !later) continue;
    const a = lastRecord(live);
    const b = lastRecord(later);
    const changed = a.calls.length !== b.calls.length || a.calls.some((call, i) => call.chips !== b.calls[i]?.chips) || Boolean(a.status) !== Boolean(b.status);
    if (!changed) continue;
    out.push({
      id: `record-changes-after-reopen-${run}`,
      screen: 'answer',
      issue: 'The record of the library calls says something else once the chat is opened again',
      severity: 'major',
      shot: later.file,
      evidence: `live (${live.file}): ${recordText(a)} | reopened (${later.file}): ${recordText(b)}`,
      item: 'Living Answer (record of library calls)',
      viewport: live.viewport,
      source: 'pass',
    });
  }
  return out;
}

/** The section index the strip shows: the labels of its section controls (keys s0, s1 ...), in order. */
const sectionLabels = (entry) => (entry?.probes?.strip?.items ?? []).filter((item) => /^s\d+$/.test(item.key)).map((item) => item.label);

/**
 * The strip's section index must come back when a chat is opened again. The index follows the answer at the reading
 * line (useAnswerInView), so the pass compares one answer in both states: per run, the capture made with the demo
 * answer's first heading at the reading line right after it streamed (state «section index, live») against the same
 * after the chat was opened again from the sidebar (state «section index, reopened»). Different labels, or none
 * after reopening, is a finding; so is an answer missing from the reading line in either capture, since then the
 * two say nothing about the index.
 */
function sectionIndexDrift(entries) {
  const out = [];
  const runs = [...new Set(entries.map((entry) => `${entry.viewport}-${entry.theme}`))];
  for (const run of runs) {
    const mine = entries.filter((entry) => `${entry.viewport}-${entry.theme}` === run);
    const live = mine.find((entry) => /section index, live/.test(entry.state ?? ''));
    const later = mine.find((entry) => /section index, reopened/.test(entry.state ?? ''));
    if (!live || !later) continue;
    const a = sectionLabels(live);
    const b = sectionLabels(later);
    const same = a.length === b.length && a.every((label, i) => label === b[i]);
    const inView = Boolean(live.probes?.answerAtLine && later.probes?.answerAtLine);
    if (same && inView && a.length > 0) continue;
    const where = (entry) => (entry.probes?.answerAtLine ? `answer ${entry.probes.answerAtLine.id} at the line, headings ${JSON.stringify(entry.probes.answerAtLine.headings)}` : 'no answer at the reading line');
    out.push({
      id: `section-index-after-reopen-${run}`,
      screen: 'answer',
      issue: inView ? 'The strip shows another section index once the chat is opened again' : 'The section-index comparison had no answer at the reading line',
      severity: inView ? 'major' : 'minor',
      shot: later.file,
      evidence: `live (${live.file}): ${JSON.stringify(a)}, ${where(live)} | reopened (${later.file}): ${JSON.stringify(b)}, ${where(later)}`,
      item: 'Living Answer (strip section index)',
      viewport: live.viewport,
      source: 'pass',
    });
  }
  return out;
}

/**
 * The pass's own findings from the census: English interface text per screen (visible text major, attributes and
 * screen-reader text minor), the name LibreChat, a heading drawn letter by letter, a main container laid out left to
 * right on a right-to-left page, and the sign-in screen without the brand footer.
 */
function autoFindings(all) {
  const entries = arabicInterface(all);
  const findings = [];
  const groups = new Map();
  for (const entry of entries) {
    // Screen-reader text (a .sr-only text node) is not seen: it goes with the labels, not with the visible text.
    const visible = uiLatin(entry).filter((record) => record.kind !== 'sr-only');
    const unseen = [...uiLatin(entry).filter((record) => record.kind === 'sr-only'), ...uiLatin(entry, { attributes: true })];
    for (const [kind, records] of [['text', visible], ['attribute', unseen]]) {
      for (const record of records) {
        const key = `${entry.screen}|${kind}`;
        if (!groups.has(key)) groups.set(key, { entry, kind, strings: new Map() });
        const text = String(record.text).trim().slice(0, 80);
        const group = groups.get(key);
        if (!group.strings.has(text)) group.strings.set(text, { entry, record, viewports: new Set() });
        group.strings.get(text).viewports.add(entry.viewport);
      }
    }
  }
  for (const [key, group] of groups) {
    const [screen] = key.split('|');
    const strings = [...group.strings.entries()];
    const items = [...new Set(strings.map(([text]) => itemOf(text)))];
    findings.push({
      id: `latin-${screen}-${group.kind}`,
      screen,
      issue: group.kind === 'text' ? `English text shown on the ${screen} screens (REQ-UI-001)` : `English in labels, tooltips or screen-reader text on the ${screen} screens (REQ-UI-001)`,
      severity: group.kind === 'text' ? 'major' : 'minor',
      shot: strings[0][1].entry.file,
      evidence: strings
        .slice(0, 25)
        .map(([text, { entry, record }]) => `«${text}»${record.attr ? ` [${record.attr}]` : ''} (${entry.file})`)
        .join('; ') + (strings.length > 25 ? `; and ${strings.length - 25} more (census.json)` : ''),
      item: items.join(', '),
      viewport: [...new Set(strings.flatMap(([, { viewports }]) => [...viewports]))].sort().join(', '),
      source: 'pass',
    });
  }
  const split = entries.find((entry) => drawnApart(entry.heading));
  if (split) {
    findings.push({
      id: 'heading-letters-apart',
      screen: split.screen,
      issue: 'The animated tier heading draws Arabic letters apart',
      severity: 'major',
      shot: split.file,
      evidence: `«${split.heading.text}» units ${JSON.stringify(split.heading.offending.slice(0, 8))}, letter-spacing ${split.heading.letterSpacing}`,
      item: 'O-35',
      viewport: [...new Set(entries.filter((entry) => drawnApart(entry.heading)).map((entry) => entry.viewport))].sort().join(', '),
      source: 'pass',
    });
  }
  const ltr = new Map();
  for (const entry of entries) {
    if (entry.htmlDir !== 'rtl') continue;
    for (const c of entry.containers ?? []) {
      if (c.expectRtl && c.direction === 'ltr') {
        const key = `${entry.screen}|${c.name}`;
        if (!ltr.has(key)) ltr.set(key, { entry, c });
      }
    }
  }
  for (const [key, { entry, c }] of ltr) {
    findings.push({
      id: `ltr-${key.replace('|', '-')}`,
      screen: entry.screen,
      issue: `${c.name} is laid out left to right on the right-to-left page`,
      severity: 'major',
      shot: entry.file,
      evidence: `${c.name}: dir=${c.dir || '(none)'} lang=${c.lang || '(none)'} computed direction ${c.direction}, text-align ${c.textAlign} (${entry.file})`,
      item: 'REQ-RTL-001',
      viewport: entry.viewport,
      source: 'pass',
    });
  }
  for (const drift of recordDrift(entries)) findings.push(drift);
  for (const drift of sectionIndexDrift(entries)) findings.push(drift);
  const signin = entries.filter((entry) => entry.screen === 'signin');
  if (signin.length && signin.every((entry) => !(entry.probes?.brandFooter?.visible && /Iqraa LAW AI/.test(entry.probes.brandFooter.text)))) {
    findings.push({
      id: 'signin-no-brand-footer',
      screen: 'signin',
      issue: 'The sign-in screen does not show «Iqraa LAW AI»',
      severity: 'major',
      shot: signin[0].file,
      evidence: `iqraa-brand-footer ${JSON.stringify(signin[0].probes?.brandFooter ?? null)}`,
      item: 'O-37',
      viewport: [...new Set(signin.map((e) => e.viewport))].join(', '),
      source: 'pass',
    });
  }
  return findings;
}

/** The findings file after a pass: this pass's own findings replace the last pass's; reviewed ones are kept. */
function mergeFindings(previous, fresh) {
  const kept = (Array.isArray(previous) ? previous : []).filter((finding) => finding && finding.source === 'review');
  const ids = new Set(kept.map((finding) => finding.id));
  return [...kept, ...fresh.filter((finding) => !ids.has(finding.id))];
}

/** The screenshot name: <viewport>-<theme>-<nn>-<slug>.png, the slug lower-case ASCII words joined by dashes. */
function shotName(viewport, theme, n, slug) {
  const clean = String(slug).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'screen';
  return `${viewport}-${theme}-${String(n).padStart(2, '0')}-${clean}.png`;
}

module.exports = { ALLOWED, MOCK, KNOWN_POINTS, arabicInterface, autoFindings, classify, hasLatin, headingJoin, itemOf, knownItems, latinRemainder, mergeFindings, mergeKnown, drawnApart, reclassify, recordDrift, sectionIndexDrift, shotName, zoneOf };
