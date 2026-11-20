// Tests for the PROPOSED AQEL edition 1.5 (draft, for lawyer review; not live):  node --test content/aqel-v15.test.mjs
// They read the built edition (prompts/aqel-v1.5-librechat.md, written by prompts/build_aqel.py 1.5). 1.5 is 1.4 with
// the distilled checks for civil and commercial matters added as whole lines: these tests hold that, so a reviewer
// reads only the additions, and that the additions hand the model no article number, and name only search terms the
// Jordanian corpus holds.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { termProblem } from './search-terms.mjs';

const contentDir = path.dirname(fileURLToPath(import.meta.url));
const readEdition = (version) =>
  fs.readFileSync(path.join(contentDir, 'prompts', `aqel-v${version}-librechat.md`), 'utf8').replace(/\r\n/g, '\n');
const base = readEdition('1.4');
const edition = readEdition('1.5');
const companionAt = edition.indexOf('ENGLISH SYSTEM PROMPT');
const arabic = edition.slice(0, companionAt);
const english = edition.slice(companionAt);
const { laws } = JSON.parse(fs.readFileSync(path.join(contentDir, 'corpus', 'laws.json'), 'utf8'));
const isVersionLine = (line) => line.startsWith('SYSTEM PROMPT — VERSION ');

/** The lines of 1.5 that are not 1.4's, in order; fails unless 1.4's lines (less the version line) survive in order. */
function addedLines() {
  const old = base.split('\n').filter((line) => !isVersionLine(line));
  const added = [];
  let at = 0;
  for (const line of edition.split('\n').filter((l) => !isVersionLine(l))) {
    if (at < old.length && line === old[at]) at += 1;
    else added.push(line);
  }
  assert.equal(at, old.length, `1.4 line ${at + 1} is missing or changed in 1.5: ${old[at]?.slice(0, 80)}`);
  return added;
}

/** The whole text of a law in the corpus (its section files, or its single file), as the library tools read it. */
function lawText(slug) {
  const law = laws.find((entry) => entry.slug === slug);
  const folder = path.join(contentDir, '..', 'jordanian-law', 'references', 'القوانين-الأردنية', law.folder);
  const sections = path.join(folder, 'sections');
  const dir = fs.existsSync(sections) ? sections : folder;
  return fs
    .readdirSync(dir)
    .filter((name) => name.endsWith('.md') && !name.startsWith('_'))
    .map((name) => fs.readFileSync(path.join(dir, name), 'utf8'))
    .join('\n');
}

test('1.5 carries its version and changes no line of 1.4', () => {
  assert.ok(edition.includes('SYSTEM PROMPT — VERSION 1.5 — '));
  assert.ok(!edition.includes('VERSION 1.4'));
  assert.ok(addedLines().length > 0);
});

test('1.5 adds the distilled checks after the ten stages, in both languages', () => {
  const block = arabic.indexOf('\nضوابط تطبيق المراحل على المسائل المدنية والتجارية\n');
  assert.ok(block > arabic.indexOf('المرحلة 10 — العرض والإقناع'));
  assert.ok(block < arabic.indexOf('\nقواعد التفكير المتقدم\n'));
  const twin = english.indexOf('\nCIVIL AND COMMERCIAL MATTERS: CHECKS FOR THE STAGES\n');
  assert.ok(twin > english.indexOf('STAGE 10 — PRESENT A PERSUASIVE LEGAL PRODUCT'));
  assert.ok(twin < english.indexOf('\nADVANCED REASONING AND REVIEW\n'));
  const bullets = (text, from) => text.slice(from).split('\n').slice(2).findIndex((line) => !line.startsWith('- '));
  assert.equal(bullets(arabic, block), bullets(english, twin), 'the English twin has one bullet per Arabic bullet');
});

test('the added lines name no article number and pass only slugs the library has', () => {
  const added = addedLines().join('\n');
  assert.deepEqual(added.match(/[0-9٠-٩]+/g) ?? [], []);
  assert.ok(!/المادة\s+[0-9٠-٩]/.test(added));
  const slugs = laws.map((law) => law.slug);
  const passed = [...added.matchAll(/law="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(passed.filter((slug) => !slugs.includes(slug)), []);
});

const checksAr = arabic.slice(arabic.indexOf('\nضوابط تطبيق المراحل'), arabic.indexOf('\nقواعد التفكير المتقدم\n'));
const checksEn = english.slice(english.indexOf('\nCIVIL AND COMMERCIAL MATTERS'), english.indexOf('\nADVANCED REASONING AND REVIEW\n'));
/** What the checks quote that is not a search term: the stages they key to, and labels the model must not adopt. */
const STAGES = ['التكييف القانوني', 'تحليل عناصر القاعدة', 'الإثبات', 'المخاطر والبدائل', 'الاستراتيجية'];
const LABELS = ['قابل للإبطال', 'الخطأ', 'الإدراك'];
const TERMS = ['إضرار', 'المباشر', 'المتسبب', 'التعدي', 'عدم سماع الدعوى'];

// A search term the model is told to use must be the statute's own word, or search_law finds nothing for it; and a
// statutory noun phrase, never a proposition or an amount (owner, 2026-11-13, «Noun phrases only»).
test('every statutory term the distilled checks tell the model to search is in the Civil Code text, as a noun phrase', () => {
  const quoted = (text) => [...new Set([...text.matchAll(/«([^»]+)»/g)].map((m) => m[1]))].sort();
  assert.deepEqual(quoted(checksAr), [...STAGES, ...LABELS, ...TERMS].sort(), 'a new quoted term must be listed here');
  assert.deepEqual(quoted(checksEn), [...LABELS, ...TERMS].sort());
  const civil = lawText('civil-code');
  for (const term of [...TERMS, 'موقوف', 'غير لازم', 'فاسد']) {
    assert.ok(civil.includes(term), `${term} is not in the Civil Code text`);
    assert.equal(termProblem(term), null, `«${term}» is not a statutory noun phrase`);
  }
});

test('the checks open with the answer budget, in both languages', () => {
  const first = (text) => text.split('\n').find((line) => line.startsWith('- '));
  assert.ok(first(checksAr).startsWith('- طبّق هذه الضوابط على المسألة الحاسمة أولًا وضمن رصيد الإجابة'));
  assert.ok(first(checksEn).startsWith("- Apply these checks to the decisive issue first and within the answer's budget"));
});

// The owner, 2026-11-13 («Forbid in model text»): the checks name Egyptian law once, to forbid it in the answer.
test('the edition names Egyptian law only to forbid it, in both languages', () => {
  const lines = edition.split('\n').filter((line) => /مصري|مصرية|Egypt/.test(line));
  assert.equal(lines.length, 2, lines.map((line) => line.slice(0, 60)).join(' | '));
  assert.ok(lines[0].startsWith('- لا تذكر في الإجابة القانون المصري أو شروحه، ولا تقارن بهما.'));
  assert.ok(lines[1].startsWith('- Never mention Egyptian law or its commentary in the answer, nor compare with them.'));
  assert.ok(!/مصري|مصرية|Egypt/.test(base), '1.4 does not name it');
});

test('one term for discernment: the checks say «الإدراك», as the issue map does', () => {
  assert.ok(checksAr.includes('«الإدراك»') && !checksAr.includes('«التمييز»'));
});
