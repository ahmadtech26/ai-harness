// Tests for the PROPOSED skill jordanian-civil-issue-map (draft, for lawyer review):  node --test content/issue-map.test.mjs
// Each line of its reference files is a method sentence from docs/distillation/2026-11-12-book-principles.md with the
// statutory terms to search. These tests hold the lines to the corpus: a term the model is told to search must be in
// the named law's text, a line may name no article number, and each line's catalogue entry must exist and propose the
// same sentence and terms. The same checks run on any other skill's reference line that ends in a catalogue id.
// Files are read with either line end: a Windows checkout gives CRLF, and a line that kept its \r would match nothing.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const contentDir = path.dirname(fileURLToPath(import.meta.url));
const skillsDir = path.join(contentDir, 'skills');
const ISSUE_MAP = 'jordanian-civil-issue-map';
const skillDir = path.join(skillsDir, ISSUE_MAP);
const readText = (file) => fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
const catalogue = readText(path.join(contentDir, '..', 'docs', 'distillation', '2026-11-12-book-principles.md'));
const { laws } = JSON.parse(fs.readFileSync(path.join(contentDir, 'corpus', 'laws.json'), 'utf8'));
const LINE = /^- (?<text>.+?)(?: — البحث: law="(?<law>[a-z-]+)"، (?<terms>.+?))?\. <!-- (?<id>V[0-9A-Z]+-[0-9]+) -->$/;
const ID_COMMENT = / <!-- V[0-9A-Z]+-[0-9]+ -->$/;

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

/** The entry lines of a reference file: in the issue map every bullet, elsewhere a bullet that ends in an id comment. */
function entryLines(text, skill) {
  return text
    .replace(/\r\n/g, '\n')
    .split('\n')
    .filter((line) => line.startsWith('- ') && (skill === ISSUE_MAP || ID_COMMENT.test(line)));
}

const referenceFiles = fs
  .readdirSync(skillsDir, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .flatMap(({ name: skill }) => {
    const dir = path.join(skillsDir, skill, 'references');
    if (!fs.existsSync(dir)) return [];
    return fs
      .readdirSync(dir)
      .filter((name) => name.endsWith('.md'))
      .map((name) => ({ skill, name, file: `${skill}/references/${name}`, text: readText(path.join(dir, name)) }));
  });
const entries = referenceFiles.flatMap(({ skill, file, text }) =>
  entryLines(text, skill).map((line) => ({ skill, file, line, match: LINE.exec(line) })),
);
const issueMapEntries = entries.filter(({ skill }) => skill === ISSUE_MAP);

/** Each catalogue entry's proposed sentence and search, by id. */
const proposals = new Map(
  catalogue
    .split(/\n(?=#### )/)
    .map((block) => {
      const id = /^#### (V[0-9A-Z]+-[0-9]+) ·/.exec(block)?.[1];
      const sentence = /^- \*\*صياغة منهجية مقترحة:\*\* (.+)$/m.exec(block)?.[1];
      const search = /^- \*\*ما يُبحث عنه في المكتبة:\*\* `search_law` law="([a-z-]+)": (.+)$/m.exec(block);
      return [id, { sentence, law: search?.[1], terms: search?.[2] }];
    })
    .filter(([id]) => id),
);

test('reads a reference file the same with CRLF or LF line ends', () => {
  const { skill, text } = referenceFiles.find((ref) => ref.skill === ISSUE_MAP);
  assert.ok(entryLines(text, skill).length > 0);
  assert.deepEqual(entryLines(text.replace(/\n/g, '\r\n'), skill), entryLines(text, skill));
});

test('SKILL.md sends the model only to reference files that exist, and to all of them', () => {
  const skill = readText(path.join(skillDir, 'SKILL.md'));
  const named = [...skill.matchAll(/`references\/([a-z-]+\.md)`/g)].map((m) => m[1]);
  const files = referenceFiles.filter((ref) => ref.skill === ISSUE_MAP).map((ref) => ref.name);
  assert.deepEqual([...named].sort(), [...files].sort());
});

test('every reference line is a method sentence with its catalogue id, and names no article number', () => {
  assert.equal(issueMapEntries.length, proposals.size, 'the issue map carries every catalogue entry');
  for (const { file, line, match } of entries) {
    assert.ok(match, `${file}: line not in the expected form: ${line.slice(0, 80)}`);
    assert.ok(!/[0-9٠-٩]/.test(match.groups.text), `${match.groups.id}: a digit in the method text`);
    assert.ok(!/(المادة|المواد)\s+[0-9٠-٩]/.test(line), `${match.groups.id}: an article number`);
    assert.ok(proposals.has(match.groups.id), `${match.groups.id}: no catalogue entry`);
  }
  const ids = issueMapEntries.map(({ match }) => match.groups.id);
  assert.equal(new Set(ids).size, ids.length, 'each catalogue entry appears once in the issue map');
});

// The lawyer reviews the catalogue; the model reads the skill. They must say the same thing.
test('every reference line is the sentence and search its catalogue entry proposes', () => {
  for (const { match } of entries) {
    const { id, text, law, terms } = match.groups;
    const proposal = proposals.get(id);
    // The catalogue ends the sentence with a full stop; the skill line puts its search before the stop.
    assert.ok([text, `${text}.`].includes(proposal.sentence), `${id}: the sentence differs from the catalogue's «صياغة منهجية مقترحة»`);
    assert.equal(proposal.law, law, `${id}: the law differs from the catalogue's «ما يُبحث عنه»`);
    assert.equal(proposal.terms, terms, `${id}: the terms differ from the catalogue's «ما يُبحث عنه»`);
  }
});

// search_law matches the statute's words: a term that is not in the named law returns nothing for the model.
test('every search term is in the named law\'s text in the corpus', () => {
  const slugs = laws.map((law) => law.slug);
  let checked = 0;
  for (const { match } of entries.filter(({ match }) => match?.groups.law)) {
    const { id, law, terms } = match.groups;
    assert.ok(slugs.includes(law), `${id}: unknown law ${law}`);
    for (const term of terms.split('، ').map((t) => t.replace(/^«|»$/g, ''))) {
      assert.ok(lawText(law).includes(normalise(term)), `${id}: «${term}» is not in ${law}`);
      checked += 1;
    }
  }
  assert.ok(checked > 0, 'no search term was checked: are the lines read?');
  assert.equal(entries.filter(({ match }) => match?.groups.law).length, entries.length, 'every line names its search');
});
