// The everyday search vocabulary (draft, for lawyer review):  node --test content/search-vocabulary.test.mjs
// corpus/search-vocabulary.json maps everyday wordings («طرد العامل», «الكمبيالة») to the statutory noun phrase the mapped
// law uses («فصل العامل», «سند السحب»), for legal-search to add the statutory phrase to a query that holds an everyday
// wording once the server reads the file (#34, on hold). It is never shown to the model. These tests hold the file to the library: every statutory phrase is a statutory noun phrase
// (search-terms.mjs; owner, 2026-11-13) found in the mapped law's text, and no wording names a source site.
// Each listed article holds its phrase by the rule the file's note states; the per-article test below is that rule's
// definition (bodyTokens and holds).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { namedSites } from './copy-sites.mjs';
import { normalise, termProblem } from './search-terms.mjs';

const contentDir = path.dirname(fileURLToPath(import.meta.url));
const raw = fs.readFileSync(path.join(contentDir, 'corpus', 'search-vocabulary.json'), 'utf8');
const vocabulary = JSON.parse(raw);
const { laws } = JSON.parse(fs.readFileSync(path.join(contentDir, 'corpus', 'laws.json'), 'utf8'));
const TOP_KEYS = ['entries', 'note', 'review', 'version'];
const ENTRY_KEYS = ['articles', 'everyday', 'id', 'law', 'statutory'];

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

// legal-search's normalize.tokens (services/legal-search/src/legal_search/normalize.py on recall-plan), ported: fold
// diacritics, tatweel, letter variants and digits, split on non-word characters, strip one clitic prefix (longest first)
// where a three-letter stem remains. Keep it in step with that file.
const FOLD = { 'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ى': 'ي', 'ة': 'ه', 'ؤ': 'و', 'ئ': 'ي' };
const PREFIXES = ['وال', 'بال', 'كال', 'فال', 'لل', 'ال', 'و', 'ف', 'ب', 'ك', 'ل'];
const stem = (word) => {
  const prefix = PREFIXES.find((p) => word.startsWith(p) && word.length - p.length >= 3);
  return prefix ? word.slice(prefix.length) : word;
};
export const tokens = (text) =>
  text
    .replace(/[\u064B-\u0652\u0670\u0640]/g, '')
    .replace(/[أإآٱىةؤئ]/g, (c) => FOLD[c])
    .replace(/[٠-٩]/g, (d) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)))
    .replace(/[^\p{L}\p{N}_\s]/gu, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .map(stem);

const SENTENCE = /[.:؛،؟!]/;
const shortCaption = (paragraph) => paragraph.split(/\s+/).length <= 12 && !SENTENCE.test(paragraph);
/** The headings left at the end of a stored text, by law and article: §1 of the stored-text defects list. */
function leftoverTails() {
  const doc = fs.readFileSync(path.join(contentDir, '..', 'docs', 'verification', '2026-11-14-stored-text-defects.md'), 'utf8');
  const section = doc.replace(/\r\n/g, '\n').split('\n## 1.')[1].split('\n## 2.')[0];
  const slugs = new Set(laws.map((law) => law.slug));
  const tails = new Map();
  for (const bullet of section.split(/\n(?=- )/).map((b) => b.replace(/\n\s*/g, ' '))) {
    let law = /^- \*\*([a-z-]+)/.exec(bullet)?.[1];
    for (const m of bullet.matchAll(/(?:\b([a-z]+(?:-[a-z]+)*) )?(\d+):? «([^»]+)»/g)) {
      if (m[1] && slugs.has(m[1])) law = m[1];
      if (law && slugs.has(law) && !tails.has(`${law} ${m[2]}`)) tails.set(`${law} ${m[2]}`, m[3]);
    }
  }
  return tails;
}
/** A law's articles as its section files hold them, plain numbers only: number → the article's own text. */
function sectionArticles(slug) {
  const law = laws.find((entry) => entry.slug === slug);
  const folder = path.join(contentDir, '..', 'jordanian-law', 'references', 'القوانين-الأردنية', law.folder);
  const sections = path.join(folder, 'sections');
  const dir = fs.existsSync(sections) ? sections : folder;
  const found = new Map();
  for (const name of fs.readdirSync(dir).filter((n) => n.endsWith('.md') && !n.startsWith('_')).sort()) {
    let key = null;
    let body = [];
    const close = () => key !== null && !found.has(key) && found.set(key, body.join('\n'));
    for (const line of fs.readFileSync(path.join(dir, name), 'utf8').replace(/\r\n/g, '\n').split('\n')) {
      if (/^#{1,6}\s/.test(line)) {
        close();
        const m = /^###\s+المادة\s+(\d+)(\s+مكرر)?(?=\s|$)(?:\s+—\s+(.*))?/.exec(line);
        key = m && !m[2] ? Number(m[1]) : null;
        body = m?.[3] ? [m[3]] : [];
      } else if (key !== null && line.trim() !== '---') body.push(line); // «---» separates articles in a shard
    }
    close();
  }
  return found;
}
/** How near the end a heading §1 records may start: its own length plus this many tokens (a glued heading after it). */
const NEAR_END = 20;
/** The tokens of an article's own text (as the section files hold it, before the ingest's strip) without its leftover
 * captions, cut in this order:
 *  1. a leading caption: a first paragraph of at most 12 words with none of the marks . : ؛ ، ؟ !;
 *  2. the heading §1 of the stored-text defects list records at the article's end: from where its tokens start, if that
 *     is within its own length plus NEAR_END tokens of the end, to the end (`found` is called when it is found);
 *  3. otherwise the next article's heading glued to the end, which the ingest strips: a last paragraph of the same kind
 *     as 1, or else, after the last of the marks . : ؛ ؟ !, a run of the same kind. */
function bodyTokens(text, tail, found = () => {}) {
  let paragraphs = text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  if (paragraphs.length > 1 && shortCaption(paragraphs[0])) paragraphs = paragraphs.slice(1);
  const words = tokens(paragraphs.join('\n\n'));
  const tailWords = tail ? tokens(tail.replace(/^#+\s*/, '')) : [];
  if (tailWords.length) {
    for (let start = words.length - tailWords.length; start >= Math.max(0, words.length - tailWords.length - NEAR_END); start -= 1) {
      if (tailWords.every((word, j) => words[start + j] === word)) {
        found();
        return words.slice(0, start);
      }
    }
  }
  if (paragraphs.length > 1 && shortCaption(paragraphs.at(-1))) return tokens(paragraphs.slice(0, -1).join('\n\n'));
  const joined = paragraphs.join('\n\n');
  const end = Math.max(...[...joined.matchAll(/[.:؛؟!]/g)].map((m) => m.index), -1);
  const after = joined.slice(end + 1).trim();
  return end >= 0 && after && shortCaption(after) ? tokens(joined.slice(0, end + 1)) : words;
}
const holds = (words, phrase) =>
  words.some((_, i) => phrase.length > 0 && phrase.every((word, j) => words[i + j] === word));

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

// The owner, 2026-11-15: a listed article holds the phrase in its own text, not only in a heading left at its end or a
// caption, and not only in a longer word («الإخبارات» does not hold «الإخبار»).
test('every listed article holds its statutory phrase by the note\'s rule', () => {
  assert.match(vocabulary.note, /search-vocabulary\.test\.mjs/);
  const tails = leftoverTails();
  assert.ok(tails.size > 0, 'no heading read from §1 of the stored-text defects list');
  const problems = [];
  for (const { id, statutory, law, articles } of vocabulary.entries) {
    assert.ok(articles.length <= 5, `${id}: more than five articles`);
    const texts = sectionArticles(law);
    const phrase = tokens(statutory);
    for (const number of articles) {
      if (!texts.has(number)) problems.push(`${id}: ${law} ${number} is not a plain-numbered article`);
      else if (!holds(bodyTokens(texts.get(number), tails.get(`${law} ${number}`)), phrase)) problems.push(`${id}: ${law} ${number}`);
    }
  }
  assert.deepEqual(problems, []);
});

test('every heading §1 of the defects list records for a mapped law is found near its article\'s end and cut', () => {
  const tails = leftoverTails();
  const mapped = new Set(vocabulary.entries.map((entry) => entry.law));
  const missed = [];
  let checked = 0;
  for (const [key, tail] of tails) {
    const [law, number] = key.split(' ');
    if (!mapped.has(law)) continue;
    const text = sectionArticles(law).get(Number(number));
    let found = false;
    if (text !== undefined) bodyTokens(text, tail, () => { found = true; });
    if (!found) missed.push(`${key} «${tail}»`);
    checked += 1;
  }
  assert.ok(checked > 0, 'no §1 heading of a mapped law');
  assert.deepEqual(missed, []);
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
  // The names are the one copy-site list's (content/corpus/copy-sites.json; owner, 2026-11-14 §3).
  assert.deepEqual(namedSites(raw), [], 'the vocabulary names a copy site');
  assert.ok(!/https?:\/\//.test(raw), 'the vocabulary holds a link');
});
