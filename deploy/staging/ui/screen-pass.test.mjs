// Unit checks for the screen pass's decisions (ui/screen-pass.lib.cjs), run on the host: node --test ui/screen-pass.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { autoFindings, classify, headingJoin, knownItems, mergeFindings, mergeKnown, recordDrift, sectionIndexDrift, shotName } from './screen-pass.lib.cjs';

test('English interface text is flagged, Arabic and the allowed Latin are not', () => {
  assert.equal(classify({ text: 'Search settings' }), 'ui');
  assert.equal(classify({ text: 'إعدادات البحث' }), 'no-latin');
  assert.equal(classify({ text: '+962 79 123 4567' }), 'no-latin');
  assert.equal(classify({ text: 'Iqraa LAW AI' }), 'allowlisted');
  assert.equal(classify({ text: 'النموذج: mock-model' }), 'allowlisted');
  // the placeholder email is not a phone number: it must show up
  assert.equal(classify({ text: '9627912345@phone.iqraa.invalid' }), 'ui');
});

test('the mock markers are allowed, the English around them is not', () => {
  assert.equal(classify({ text: 'MOCK_TITLE' }), 'allowlisted');
  assert.equal(classify({ text: 'Conversation «MOCK_TITLE» deleted' }), 'ui');
});

test('code, the answer text and the customer’s own words are content, not the interface', () => {
  assert.equal(classify({ text: 'shard-map.json', inCode: true }), 'content:code');
  assert.equal(classify({ text: '(Article 107)', inAnswerText: true }), 'content:answer');
  assert.equal(classify({ text: 'ARABIC_DEMO ما حكم', inUserMessage: true }), 'content:user');
  // code wins over the answer it sits in
  assert.equal(classify({ text: 'x', inCode: true, inAnswerText: true }), 'content:code');
});

test('a <pre> is code only in an answer’s turn: the error page’s bare <pre> is the interface', () => {
  assert.equal(classify({ text: 'An unexpected error occurred', inCodeElement: false, inPre: true, inAgentTurn: false }), 'ui');
  assert.equal(classify({ text: 'Error: No route matches URL', inPre: true }), 'ui');
  assert.equal(classify({ text: 'shard-map.json', inCodeElement: true }), 'content:code');
  assert.equal(classify({ text: 'ls -la', inPre: true, inAgentTurn: true }), 'content:code');
  // a census written before the pass reported these facts keeps its reading of inCode
  assert.equal(classify({ text: 'Error: No route matches URL', inCode: true }), 'content:code');
});

test('the language list may name languages in themselves; the same word elsewhere is English', () => {
  assert.equal(classify({ text: 'Deutsch', inLanguageList: true }), 'allowlisted');
  assert.equal(classify({ text: 'English' }), 'ui');
});

test('inside the brand components only the brand words pass', () => {
  assert.equal(classify({ text: 'Iqraa', inBrand: true }), 'allowlisted');
  assert.equal(classify({ text: 'LAW AI', inBrand: true }), 'allowlisted');
  assert.equal(classify({ text: 'Powered by LibreChat', inBrand: true }), 'ui');
});

test('a heading split into whole words is joined; one split into letters is not', () => {
  assert.equal(headingJoin('عقل سريع', ['عقل', 'سريع']).joined, true);
  assert.equal(headingJoin('عقل سريع', []).joined, true); // reduced motion: the text as one unit
  const letters = headingJoin('عقل سريع', ['ع', 'ق', 'ل', ' ', 'س', 'ر', 'ي', 'ع']);
  assert.equal(letters.joined, false);
  assert.deepEqual(letters.offending.slice(0, 3), ['ع', 'ق', 'ل']);
  // a run against the paragraph's direction stays one unit and still reads as whole words
  assert.equal(headingJoin('مساء الخير، John Smith', ['مساء', 'الخير،', 'John Smith']).joined, true);
  assert.equal(headingJoin('عقل سريع', ['عقل', 'سريع'], '2px').joined, false);
});

const entry = (screen, file, extra = {}) => ({ screen, state: '', file, viewport: 'desktop', texts: [], attributes: [], ...extra });

test('a known point is still there, gone, or not reached', () => {
  const points = [
    { item: 'O-35', point: 'Pinned', screens: /^sidebar$/, defect: 'present', test: (e) => (e.texts.some((r) => r.text === 'Pinned') ? 'Pinned' : null) },
    { item: 'O-37', point: 'footer', screens: /^signin$/, defect: 'absent', test: (e) => (e.probes?.footer ? 'shown' : null) },
    { item: 'O-38', point: 'help', screens: /^account$/, defect: 'present', test: () => 'x' },
  ];
  const entries = [
    entry('sidebar', 'a.png'),
    entry('sidebar', 'b.png', { texts: [{ text: 'Pinned' }] }),
    entry('signin', 'c.png', { probes: { footer: true } }),
  ];
  const [pinned, footer, help] = knownItems(entries, points);
  assert.equal(pinned.on_screen, 'still there');
  assert.equal(pinned.shot, 'b.png');
  assert.equal(footer.on_screen, 'gone'); // the footer shows, so the defect is gone
  assert.equal(help.on_screen, 'not reached');
  const [, footerMissing] = knownItems([entry('signin', 'd.png')], points);
  assert.equal(footerMissing.on_screen, 'still there');
});

test('findings group English per screen and name the open item', () => {
  const findings = autoFindings([
    entry('sidebar', 's1.png', { texts: [{ text: 'Pinned', verdict: 'ui' }, { text: 'MOCK_TITLE', verdict: 'allowlisted' }] }),
    entry('sidebar', 's2.png', { texts: [{ text: 'Pinned', verdict: 'ui' }, { text: 'Filter', verdict: 'ui' }] }),
  ]);
  const latin = findings.find((f) => f.id === 'latin-sidebar-text');
  assert.equal(latin.severity, 'major');
  assert.equal(latin.shot, 's1.png');
  assert.match(latin.evidence, /«Pinned» \(s1\.png\); «Filter» \(s2\.png\)/);
  assert.match(latin.item, /O-35/);
  assert.match(latin.item, /REQ-UI-001/);
  assert.ok(!/MOCK_TITLE/.test(latin.evidence));
});

test('a right-to-left page with a left-to-right main container is a finding; a phone field is not', () => {
  const findings = autoFindings([
    entry('settings', 'x.png', {
      htmlDir: 'rtl',
      containers: [
        { name: 'dialog', expectRtl: true, direction: 'ltr', dir: '', lang: '', textAlign: 'start' },
        { name: 'phone field', expectRtl: false, direction: 'ltr' },
      ],
    }),
  ]);
  assert.deepEqual(findings.map((f) => f.id), ['ltr-settings-dialog']);
});

test('a rerun replaces the pass’s findings and keeps the reviewed ones', () => {
  const merged = mergeFindings(
    [{ id: 'old', source: 'pass' }, { id: 'eye', source: 'review' }],
    [{ id: 'new', source: 'pass' }, { id: 'eye', source: 'pass' }],
  );
  assert.deepEqual(merged.map((f) => `${f.id}:${f.source}`), ['eye:review', 'new:pass']);
});

test('screenshot names follow <viewport>-<theme>-<nn>-<slug>.png', () => {
  assert.equal(shotName('phone', 'dark', 7, 'Sign-in: wrong code!'), 'phone-dark-07-sign-in-wrong-code.png');
  assert.equal(shotName('desktop', 'light', 112, 'x'), 'desktop-light-112-x.png');
});

test('the known points match the wording the screens show now', () => {
  const point = (name) => knownItems([
    entry('sidebar', 'e.png', { texts: [{ text: 'No chats outside your projects yet', verdict: 'ui' }] }),
    entry('settings', 's.png', { texts: [{ text: 'ar', verdict: 'ui' }], attributes: [{ text: 'Manage Backup Codes', attr: 'aria-label', verdict: 'ui' }] }),
  ]).find((k) => k.point.includes(name));
  assert.equal(point('No chats yet').on_screen, 'still there');
  assert.equal(point('raw «ar»').on_screen, 'still there');
  assert.equal(point('Clock Format').on_screen, 'gone');
});

test('key names, format names and web addresses are allowed; a feature name is not', () => {
  assert.equal(classify({ text: 'Enter للإرسال · Shift+Enter لسطر جديد' }), 'allowlisted');
  assert.equal(classify({ text: 'استخدم الأسهم، وCtrl+D للإضافة إلى المفضلة.' }), 'allowlisted');
  assert.equal(classify({ text: 'سيؤدي الضغط على مفتاح `ENTER` إلى الإرسال' }), 'allowlisted');
  assert.equal(classify({ text: 'markdown (.md)' }), 'allowlisted');
  assert.equal(classify({ text: 'تحليل LaTeX في الرسائل' }), 'allowlisted');
  assert.equal(classify({ text: 'jordan-lawyer.com' }), 'allowlisted');
  assert.equal(classify({ text: 'X' }), 'allowlisted'); // a key cap
  assert.equal(classify({ text: 'فتح إعدادات MCP' }), 'ui');
  assert.equal(classify({ text: 'Not Found' }), 'ui');
});

test('mock markers without their underscores are still the mock’s', () => {
  assert.equal(classify({ text: 'MOCKOK: سؤال قصير' }), 'allowlisted');
  assert.equal(classify({ text: 'TOOLRESULTSEEN: [1] القانون المدني' }), 'allowlisted');
});

test('the pane’s quote of the answer is the model’s text', () => {
  assert.equal(classify({ text: 'للتحقق من رقم المادة (Article 107).', testids: ['iqraa-claim', 'iqraa-no-text'] }), 'content:answer');
});

test('screen-reader text is reported with the labels, and every viewport that shows a string is named', () => {
  const findings = autoFindings([
    entry('sidebar', 'd.png', { viewport: 'desktop', texts: [{ text: 'New Chat', verdict: 'ui', kind: 'text' }, { text: 'Close', verdict: 'ui', kind: 'sr-only' }] }),
    entry('sidebar', 'p.png', { viewport: 'phone', texts: [{ text: 'New Chat', verdict: 'ui', kind: 'text' }] }),
  ]);
  const visible = findings.find((f) => f.id === 'latin-sidebar-text');
  const unseen = findings.find((f) => f.id === 'latin-sidebar-attribute');
  assert.ok(!/Close/.test(visible.evidence));
  assert.match(unseen.evidence, /Close/);
  assert.equal(visible.viewport, 'desktop, phone');
});

test('a key name alone passes only beside Arabic, and never «Delete» or «Tab»', () => {
  assert.equal(classify({ text: 'اضغط `CTRL + ENTER` / `⌘ + ENTER` لإرسال رسالتك.' }), 'allowlisted');
  assert.equal(classify({ text: 'لا تدعم Markdown، مثل Teams وOutlook وWord.' }), 'allowlisted');
  assert.equal(classify({ text: 'Delete' }), 'ui');
  assert.equal(classify({ text: 'Tab' }), 'ui');
});

test('a key or app name that is also an English word is allowed only beside Arabic', () => {
  assert.equal(classify({ text: 'Enter' }), 'ui');
  assert.equal(classify({ text: 'Word' }), 'ui');
  assert.equal(classify({ text: 'Enter للإرسال' }), 'allowlisted');
  assert.equal(classify({ text: 'مثل Teams وWord' }), 'allowlisted');
});

test('the file the pass uploads and the names of its accounts are its own content', () => {
  assert.equal(classify({ text: 'ملاحظة.txt' }), 'allowlisted');
  assert.equal(classify({ text: 'موجه 1: Staging passقبل ثانيتين', kind: 'sr-only' }), 'allowlisted');
  // upstream's alt text around the name is still English
  assert.equal(classify({ text: "Staging pass's avatar", attr: 'alt' }), 'ui');
});

test('the header button counts as the Export/Share defect only with a share glyph or label', () => {
  const exportPoint = (exportButton) =>
    knownItems([entry('header', 'h.png', { state: 'Export/Share menu open', probes: { exportButton } })]).find((k) => k.point.includes('Export/Share')).on_screen;
  assert.equal(exportPoint({ label: 'Export/Share', icon: 'lucide-share-2' }), 'still there');
  assert.equal(exportPoint({ label: 'خيارات المحادثة', icon: 'lucide-ellipsis' }), 'gone');
});

test('whole words cut by the line while they rise are drawn apart, so the heading is not joined', () => {
  const rising = headingJoin('عقل سريع', ['عقل', 'سريع'], 'normal', ['سريع']);
  assert.equal(rising.joined, false);
  assert.deepEqual(rising.offending, ['سريع (clipped)']);
  assert.equal(headingJoin('عقل سريع', ['عقل', 'سريع'], 'normal', []).joined, true);
});

test('a record that shows fewer articles once the chat is reopened is a finding; the same record is not', () => {
  const record = (chips, status) => ({ records: [{ calls: chips.map((n) => ({ line: 'بحث', chips: n })), status }] });
  const run = (later) => [
    entry('answer', 'live.png', { theme: 'light', state: 'the record of the library calls', probes: record([5, 0, 0], 'تقول المكتبة') }),
    entry('header', 'again.png', { theme: 'light', state: 'a chat open', probes: later }),
  ];
  const [drift] = recordDrift(run(record([1, 0, 0], '')));
  assert.equal(drift.severity, 'major');
  assert.equal(drift.shot, 'again.png');
  assert.match(drift.evidence, /call 1: 5 chip\(s\).*\| reopened .*call 1: 1 chip\(s\)/);
  assert.equal(recordDrift(run(record([5, 0, 0], 'تقول المكتبة'))).length, 0);
});

test('a known point cites a screen of the state that can show it, not the first screen of its kind', () => {
  const library = (k) => knownItems(k).find((p) => p.point.includes('Ran 3 actions'));
  const entries = [entry('answer', '22-demo.png', { state: 'while it streams, frame 1' }), entry('answer', '35-live.png', { state: 'a library turn live, frame 1' }), entry('answer', '39-record.png', { state: 'the record of the library calls' })];
  assert.equal(library(entries).shot, '39-record.png');
  assert.equal(library(entries.slice(0, 1)).on_screen, 'not reached');
});

test('the tab title point says which titles the captures had when LibreChat is gone', () => {
  const title = knownItems([entry('landing', 'a.png', { title: 'Iqraa LAW AI' }), entry('answer', 'b.png', { title: 'محادثة' })]).find((k) => k.point.includes('tab title'));
  assert.equal(title.on_screen, 'gone');
  assert.equal(title.evidence, "no capture's title contains LibreChat (1 «Iqraa LAW AI», 1 a chat's own title)");
});

test('a rerun keeps the known points read by hand, unless the pass now covers the same point', () => {
  const fresh = [{ item: 'O-38', point: 'Favicon', on_screen: 'gone' }];
  const merged = mergeKnown(
    [{ item: 'O-38', point: 'Email code subject', source: 'review' }, { item: 'O-38', point: 'Favicon', source: 'review', on_screen: 'still there' }, { item: 'O-35', point: 'old pass point' }],
    fresh,
  );
  assert.deepEqual(merged.map((k) => `${k.point}|${k.source ?? 'pass'}`), ['Favicon|pass', 'Email code subject|review']);
});

test('captures of the English interface the customer chose are not English-in-the-interface findings', () => {
  const english = entry('settings', 'en.png', { probes: { interfaceLanguage: 'en' }, texts: [{ text: 'General', verdict: 'ui' }] });
  const arabic = entry('settings', 'ar.png', { texts: [{ text: 'General', verdict: 'ui' }] });
  assert.equal(autoFindings([english]).some((f) => f.id.startsWith('latin-')), false);
  assert.equal(autoFindings([arabic]).some((f) => f.id === 'latin-settings-text'), true);
});

test('the section index must show the same answer’s sections after the chat is reopened', () => {
  const strip = (labels) => ({ strip: { items: [{ key: 'note', label: 'ملاحظة البحث' }, ...labels.map((label, i) => ({ key: `s${i}`, label }))] } });
  const atLine = (headings) => ({ answerAtLine: { id: 'm1', headings } });
  const run = (live, reopened) => [
    entry('answer', 'live.png', { theme: 'light', state: 'section index, live', probes: live }),
    entry('answer', 'again.png', { theme: 'light', state: 'section index, reopened', probes: reopened }),
  ];
  const both = ['الخلاصة', 'النصوص المطبقة'];
  assert.equal(sectionIndexDrift(run({ ...strip(both), ...atLine(both) }, { ...strip(both), ...atLine(both) })).length, 0);
  const [lost] = sectionIndexDrift(run({ ...strip(both), ...atLine(both) }, { ...strip([]), ...atLine(both) }));
  assert.equal(lost.severity, 'major');
  assert.equal(lost.shot, 'again.png');
  const [blind] = sectionIndexDrift(run({ ...strip(both), ...atLine(both) }, strip(both)));
  assert.equal(blind.severity, 'minor');
});

test('a cut heading counts only once it can be seen', () => {
  const cut = { joined: false, offending: ['سريع (clipped)'], text: 'عقل سريع' };
  const findings = autoFindings([
    entry('landing', 'f1.png', { heading: { ...cut, opacities: ['0.00', '0.00'] } }),
    entry('landing', 'f2.png', { heading: { ...cut, opacities: ['0.93', '0.88'] } }),
  ]);
  assert.equal(findings.find((f) => f.id === 'heading-letters-apart').shot, 'f2.png');
  const only = (opacities) => autoFindings([entry('landing', 'x.png', { heading: { ...cut, opacities } })]).some((f) => f.id === 'heading-letters-apart');
  assert.equal(only(['0.00', '0.10']), false);
});
