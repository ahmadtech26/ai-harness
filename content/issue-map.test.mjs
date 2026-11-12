// Tests for the PROPOSED skill jordanian-civil-issue-map (draft, for lawyer review):  node --test content/issue-map.test.mjs
// Each line of its reference files is a method sentence from docs/distillation/2026-11-12-book-principles.md with the
// statutory terms to search. These tests hold the lines to the corpus: a term the model is told to search must be in
// the named law's text, a line may name no article number, and each line's catalogue entry must exist.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const contentDir = path.dirname(fileURLToPath(import.meta.url));
const skillDir = path.join(contentDir, 'skills', 'jordanian-civil-issue-map');
const refDir = path.join(skillDir, 'references');
const catalogue = fs.readFileSync(path.join(contentDir, '..', 'docs', 'distillation', '2026-11-12-book-principles.md'), 'utf8');
const { laws } = JSON.parse(fs.readFileSync(path.join(contentDir, 'corpus', 'laws.json'), 'utf8'));
const refFiles = fs.readdirSync(refDir).filter((name) => name.endsWith('.md'));
const LINE = /^- (?<text>.+?)(?: — البحث: law="(?<law>[a-z-]+)"، (?<terms>.+?))?\. <!-- (?<id>V[0-9A-Z]+-[0-9]+) -->$/;

/** Spelling the corpus and the search terms may differ in: short vowels, tatweel, hamza seats, final ى and ة. */
const normalise = (text) =>
  text
    .replace(/[ً-ْـ]/g, '')
    .replace(/[إأآ]/g, 'ا')
    .replace(/ى/g, 'ي')
    .replace(/ة/g, 'ه')
    .replace(/ؤ/g, 'و')
    .replace(/ئ/g, 'ي')
    .replace(/ء/g, '')
    .replace(/\s+/g, ' ');

const lawTexts = new Map();
/** A law's whole text as the library holds it (section files, headings included), normalised. */
function lawText(slug) {
  if (!lawTexts.has(slug)) {
    const law = laws.find((entry) => entry.slug === slug);
    const folder = path.join(contentDir, '..', 'jordanian-law', 'references', 'القوانين-الأردنية', law.folder);
    const sections = path.join(folder, 'sections');
    const dir = fs.existsSync(sections) ? sections : folder;
    const text = fs
      .readdirSync(dir)
      .filter((name) => name.endsWith('.md') && !name.startsWith('_'))
      .map((name) => fs.readFileSync(path.join(dir, name), 'utf8'))
      .join('\n');
    lawTexts.set(slug, normalise(text));
  }
  return lawTexts.get(slug);
}

const entries = refFiles.flatMap((file) =>
  fs
    .readFileSync(path.join(refDir, file), 'utf8')
    .split('\n')
    .filter((line) => line.startsWith('- '))
    .map((line) => ({ file, line, match: LINE.exec(line) })),
);

test('SKILL.md sends the model only to reference files that exist, and to all of them', () => {
  const skill = fs.readFileSync(path.join(skillDir, 'SKILL.md'), 'utf8');
  const named = [...skill.matchAll(/`references\/([a-z-]+\.md)`/g)].map((m) => m[1]);
  assert.deepEqual([...named].sort(), [...refFiles].sort());
});

test('every reference line is a method sentence with its catalogue id, and names no article number', () => {
  assert.ok(entries.length > 0);
  for (const { file, line, match } of entries) {
    assert.ok(match, `${file}: line not in the expected form: ${line.slice(0, 80)}`);
    assert.ok(!/[0-9٠-٩]/.test(match.groups.text), `${match.groups.id}: a digit in the method text`);
    assert.ok(!/(المادة|المواد)\s+[0-9٠-٩]/.test(line), `${match.groups.id}: an article number`);
    assert.ok(catalogue.includes(`#### ${match.groups.id} ·`), `${match.groups.id}: no catalogue entry`);
  }
  const ids = entries.map(({ match }) => match.groups.id);
  assert.equal(new Set(ids).size, ids.length, 'each catalogue entry appears once in the issue map');
});

// search_law matches the statute's words: a term that is not in the named law returns nothing for the model.
test('every search term is in the named law\'s text in the corpus', () => {
  const slugs = laws.map((law) => law.slug);
  for (const { match } of entries.filter(({ match }) => match?.groups.law)) {
    const { id, law, terms } = match.groups;
    assert.ok(slugs.includes(law), `${id}: unknown law ${law}`);
    for (const term of terms.split('، ').map((t) => t.replace(/^«|»$/g, ''))) {
      assert.ok(lawText(law).includes(normalise(term)), `${id}: «${term}» is not in ${law}`);
    }
  }
});
