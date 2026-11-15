// The everyday search vocabulary (draft, for lawyer review):  node --test content/search-vocabulary.test.mjs
// corpus/search-vocabulary.json maps everyday wordings («طرد العامل», «الكمبيالة») to the statutory noun phrase the mapped
// law uses («فصل العامل», «سند السحب»). legal-search adds the statutory phrase to a query that holds an everyday wording,
// once a server or an evaluation run installs the file (LEGAL_SEARCH_VOCABULARY, recall-plan vocabulary.py). It is never
// shown to the model. These tests hold the file to the library: every statutory phrase is a statutory noun phrase
// (search-terms.mjs; owner, 2026-11-13) found in the mapped law's text, and no wording names a source site.
// legal-search's test_vocabulary.py checks the same file against the ingested articles (each listed article holds it).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { normalise, termProblem } from './search-terms.mjs';

const contentDir = path.dirname(fileURLToPath(import.meta.url));
const raw = fs.readFileSync(path.join(contentDir, 'corpus', 'search-vocabulary.json'), 'utf8');
const vocabulary = JSON.parse(raw);
const { laws } = JSON.parse(fs.readFileSync(path.join(contentDir, 'corpus', 'laws.json'), 'utf8'));
const TOP_KEYS = ['entries', 'note', 'review', 'version'];
const ENTRY_KEYS = ['articles', 'everyday', 'id', 'law', 'statutory'];
// The source sites' names (owner, 2026-11-14 §3); the product's own names are not on it.
const SITE_NAMES = ['jordan-lawyer', 'aqel-lawfirm', 'adaleh', 'حماة الحق', 'حُماة الحق', 'محامي الأردن', 'محامي الاردن'];

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
    lawTexts.set(slug, ` ${normalise(text).replace(/[^\p{L}\p{N}]+/gu, ' ')} `);
  }
  return lawTexts.get(slug);
}

/** A phrase's words, normalised, with a leading «ال» dropped when three letters remain (the search's own stripping). */
const words = (phrase) => normalise(phrase).split(' ').map((word) => (word.startsWith('ال') && word.length > 4 ? word.slice(2) : word));

test('the file has the agreed shape and is a draft', () => {
  assert.deepEqual(Object.keys(vocabulary).sort(), TOP_KEYS);
  assert.equal(vocabulary.version, 1);
  assert.equal(vocabulary.review.status, 'draft');
  assert.ok(vocabulary.entries.length > 0);
  const ids = vocabulary.entries.map((entry) => entry.id);
  assert.deepEqual(ids, ids.map((_, i) => `v${String(i + 1).padStart(2, '0')}`));
  for (const entry of vocabulary.entries) {
    assert.deepEqual(Object.keys(entry).sort(), ENTRY_KEYS, entry.id);
    assert.ok(laws.some((law) => law.slug === entry.law), `${entry.id}: unknown law ${entry.law}`);
    assert.ok(Array.isArray(entry.everyday) && entry.everyday.length > 0, entry.id);
    assert.ok(entry.articles.length > 0 && entry.articles.every((n) => Number.isInteger(n) && n > 0), entry.id);
  }
});

test('every statutory phrase is a statutory noun phrase found in the mapped law', () => {
  for (const { id, statutory, law } of vocabulary.entries) {
    assert.equal(termProblem(statutory), null, `${id}: «${statutory}» ${termProblem(statutory)}`);
    assert.ok(lawText(law).includes(` ${normalise(statutory)} `), `${id}: «${statutory}» is not in ${law}`);
  }
});

test('every everyday wording differs from its statutory phrase and belongs to one entry', () => {
  const owner = new Map();
  for (const { id, everyday, statutory } of vocabulary.entries) {
    for (const wording of everyday) {
      const key = words(wording).join(' ');
      assert.notEqual(key, words(statutory).join(' '), `${id}: «${wording}» is the statutory phrase`);
      assert.ok(!owner.has(key), `${id}: «${wording}» is already in ${owner.get(key)}`);
      owner.set(key, id);
      // The search matches a wording's first word as a prefix: two letters would match unrelated words.
      assert.ok(words(wording)[0].length >= 3, `${id}: «${wording}» begins with a word under three letters`);
    }
  }
});

test('no wording or note names a source site', () => {
  for (const name of SITE_NAMES) assert.ok(!raw.includes(name), `the vocabulary names ${name}`);
  assert.ok(!/https?:\/\//.test(raw), 'the vocabulary holds a link');
});
