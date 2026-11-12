// Tests for the PROPOSED AQEL edition 1.4 (draft, for lawyer review; not live):  node --test content/aqel-v14.test.mjs
// They read the built edition (prompts/aqel-v1.4-librechat.md, written by prompts/build_aqel.py 1.4). 1.4 is 1.3 with
// whole lines added: these tests hold that, so a reviewer reads only the additions, and that the additions hand the
// model no article number, and name only search terms the Jordanian corpus holds.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const contentDir = path.dirname(fileURLToPath(import.meta.url));
const readEdition = (version) =>
  fs.readFileSync(path.join(contentDir, 'prompts', `aqel-v${version}-librechat.md`), 'utf8').replace(/\r\n/g, '\n');
const base = readEdition('1.3');
const edition = readEdition('1.4');
const companionAt = edition.indexOf('ENGLISH SYSTEM PROMPT');
const arabic = edition.slice(0, companionAt);
const english = edition.slice(companionAt);
const { laws } = JSON.parse(fs.readFileSync(path.join(contentDir, 'corpus', 'laws.json'), 'utf8'));
const isVersionLine = (line) => line.startsWith('SYSTEM PROMPT — VERSION ');

/** The lines of 1.4 that are not 1.3's, in order; fails unless 1.3's lines (less the version line) survive in order. */
function addedLines() {
  const old = base.split('\n').filter((line) => !isVersionLine(line));
  const added = [];
  let at = 0;
  for (const line of edition.split('\n').filter((l) => !isVersionLine(l))) {
    if (at < old.length && line === old[at]) at += 1;
    else added.push(line);
  }
  assert.equal(at, old.length, `1.3 line ${at + 1} is missing or changed in 1.4: ${old[at]?.slice(0, 80)}`);
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

test('1.4 carries its version and changes no line of 1.3', () => {
  assert.ok(edition.includes('SYSTEM PROMPT — VERSION 1.4 — '));
  assert.ok(!edition.includes('VERSION 1.3'));
  assert.ok(addedLines().length > 0);
});

test('1.4 adds the distilled checks after the ten stages, in both languages', () => {
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

// A search term the model is told to use must be the statute's own word, or search_law finds nothing for it.
test('every statutory term the distilled checks tell the model to search is in the Civil Code text', () => {
  const civil = lawText('civil-code');
  for (const term of ['إضرار', 'المباشر', 'المتسبب', 'التعدي', 'لا تسمع الدعوى', 'موقوف', 'غير لازم', 'فاسد']) {
    assert.ok(civil.includes(term), `${term} is not in the Civil Code text`);
  }
});
