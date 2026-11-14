// Tests for the practice notes in the skills' reference files (draft, for lawyer review):  node --test content/practice-notes.test.mjs
// A practice note is a reference line, in any skill, that ends in «<!-- PN-NN مسودة، لمراجعة المحامي -->». It gives a
// step, a deadline's starting point, a document or a competent court in words, names in «المواد» the library articles
// that say it (law slug and article number, for get_article), and in «البحث» statutory noun phrases found in those
// articles, for search_law:
//   «- <note> — المواد: law="civil-procedure"، 171، 178؛ law="magistrates-courts"، 8 — البحث: law="civil-procedure"، «…». <!-- PN-14 مسودة، لمراجعة المحامي -->»
// The note itself states no period, amount or article number: the model takes those from the article it retrieves.
// Each note has an internal source record in docs/distillation/jordan-lawyer/sources.jsonl (the page it was distilled
// from, the page's sha256 and post date, distilled_on); that file is never served, and what the model reads of a skill
// names no copy site, its firm or its title, and links nowhere.
// Files are read with either line end: a Windows checkout gives CRLF, and a line that kept its \r would match nothing.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { normalise, termProblem } from './search-terms.mjs';

const contentDir = path.dirname(fileURLToPath(import.meta.url));
const repoDir = path.join(contentDir, '..');
const skillsDir = path.join(contentDir, 'skills');
const SOURCES = path.join(repoDir, 'docs', 'distillation', 'jordan-lawyer', 'sources.jsonl');
const MARK = 'مسودة، لمراجعة المحامي';
const readText = (file) => fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
const { laws } = JSON.parse(fs.readFileSync(path.join(contentDir, 'corpus', 'laws.json'), 'utf8'));
const NOTE = new RegExp(
  `^- (?<text>.+?) — المواد: (?<keys>law="[a-z-]+"، .+?) — البحث: (?<searches>law="[a-z-]+"، .+?)\\. <!-- (?<id>PN-[0-9]{2,3}) ${MARK} -->$`,
);
const PN_COMMENT = / <!-- PN-[0-9]+ [^>]*-->$/;
// Whole words (after normalise, less a leading و/ف/ب/ل/ال) that state a number, a fraction or a counted period.
const NUMBER_WORDS = new Set([
  'نصف', 'ثلث', 'ربع', 'خمس', 'سدس', 'عشر', 'اثنان', 'اثنين', 'ثلاث', 'ثلاثه', 'اربع', 'اربعه', 'خمسه', 'ست', 'سته', 'سبع',
  'سبعه', 'ثماني', 'ثمانيه', 'تسع', 'تسعه', 'عشره', 'عشرين', 'ثلاثين', 'اربعين', 'خمسين', 'ستين', 'سبعين', 'ثمانين', 'تسعين',
  'مايه', 'ميه', 'الف', 'الاف', 'سنتين', 'شهرين', 'يومين', 'اسبوعين',
]);

const referenceFiles = fs
  .readdirSync(skillsDir, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .flatMap(({ name: skill }) => {
    const dir = path.join(skillsDir, skill, 'references');
    if (!fs.existsSync(dir)) return [];
    return fs
      .readdirSync(dir)
      .filter((name) => name.endsWith('.md'))
      .map((name) => ({ skill, name, file: `skills/${skill}/references/${name}`, text: readText(path.join(dir, name)) }));
  });
const notes = referenceFiles.flatMap(({ skill, file, text }) =>
  text.split('\n').filter((line) => line.startsWith('- ') && PN_COMMENT.test(line)).map((line) => ({ skill, file, line, match: NOTE.exec(line) })),
);
// The tests after the first read the notes that are in form; the first reports any that is not.
const parsed = notes.filter(({ match }) => match);

/** «law="a"، x، y؛ law="b"، z» as [{ law, items }]. */
const parseParts = (value) =>
  value.split('؛ ').map((part) => {
    const m = /^law="([a-z-]+)"، (.+)$/.exec(part);
    return { law: m?.[1], items: (m?.[2] ?? '').split('، ') };
  });

const lawArticles = new Map();
/** A law's articles as the section files hold them: «N» or «N مكرر» → the article's text. Some headings carry text after
 * «المادة N —» (in the court-fees schedule, the whole item); the library stores it with the article, so it counts. */
function articles(slug) {
  if (!lawArticles.has(slug)) {
    const law = laws.find((entry) => entry.slug === slug);
    const folder = path.join(repoDir, 'jordanian-law', 'references', 'القوانين-الأردنية', law.folder);
    const sections = path.join(folder, 'sections');
    const dir = fs.existsSync(sections) ? sections : folder;
    const found = new Map();
    for (const name of fs.readdirSync(dir).filter((n) => n.endsWith('.md') && !n.startsWith('_')).sort()) {
      let key = null;
      let body = [];
      const close = () => key && !found.has(key) && found.set(key, body.join('\n'));
      for (const line of readText(path.join(dir, name)).split('\n')) {
        if (/^#{1,6}\s/.test(line)) {
          close();
          const m = /^###\s+المادة\s+(\d+)(\s+مكرر)?(?=\s|$)(?:\s+—\s+(.*))?/.exec(line);
          key = m ? `${m[1]}${m[2] ? ' مكرر' : ''}` : null;
          body = m?.[3] ? [m[3]] : [];
        } else if (key) body.push(line);
      }
      close();
    }
    lawArticles.set(slug, found);
  }
  return lawArticles.get(slug);
}

test('there are practice notes, and every one is in the expected form with a unique id', () => {
  assert.ok(notes.length > 0, 'no practice note was read');
  for (const { file, line, match } of notes) assert.ok(match, `${file}: line not in the expected form: ${line.slice(0, 80)}`);
  const ids = notes.map(({ match }) => match.groups.id);
  assert.equal(new Set(ids).size, ids.length, 'each practice note id appears once');
});

test('a note states no period, amount or article number of its own', () => {
  for (const { match } of parsed) {
    const { id, text } = match.groups;
    assert.ok(!/[0-9٠-٩%]/.test(text), `${id}: a digit in the note`);
    assert.ok(!/(^|\s)(ال|ب|و)?(مادة|المادة|البند)(\s|$)/.test(text), `${id}: the note names an article; put it in «المواد»`);
    const words = normalise(text).split(' ').map((word) => word.replace(/[^ء-ي]/g, ''));
    const numbers = words.filter((word) => NUMBER_WORDS.has(word) || NUMBER_WORDS.has(word.replace(/^(?:وال|فال|بال|لل|ال|و|ف|ب|ل)/, '')));
    assert.deepEqual(numbers, [], `${id}: a number word in the note`);
  }
});

// get_article takes the law and the number; a key that is not in the corpus returns nothing for the model.
test('every article a note names is in the corpus, and every search term is in the articles it names for that law', () => {
  const slugs = laws.map((law) => law.slug);
  let checked = 0;
  for (const { match } of parsed) {
    const { id, keys, searches } = match.groups;
    const named = new Map();
    for (const { law, items } of parseParts(keys)) {
      assert.ok(slugs.includes(law), `${id}: unknown law ${law}`);
      assert.ok(!named.has(law), `${id}: ${law} named twice in «المواد»`);
      for (const key of items) {
        assert.match(key, /^\d+( مكرر)?$/, `${id}: «${key}» is not an article number`);
        assert.ok(articles(law).has(key), `${id}: ${law} ${key} is not in the corpus`);
      }
      named.set(law, items);
    }
    for (const { law, items } of parseParts(searches)) {
      assert.ok(named.has(law), `${id}: a search in ${law}, which «المواد» does not name`);
      for (const term of items.map((t) => t.replace(/^«|»$/g, ''))) {
        const inArticle = named.get(law).some((key) => normalise(articles(law).get(key)).includes(normalise(term)));
        assert.ok(inArticle, `${id}: «${term}» is not in ${law} ${named.get(law).join(', ')}`);
        checked += 1;
      }
    }
  }
  assert.ok(checked > 0, 'no search term was checked');
});

// The owner, 2026-11-13 («Noun phrases only»).
test('every search term is a statutory noun phrase', () => {
  const problems = parsed.flatMap(({ match }) =>
    parseParts(match.groups.searches).flatMap(({ items }) =>
      items.map((t) => t.replace(/^«|»$/g, '')).map((term) => [term, termProblem(term)]).filter(([, p]) => p).map(([term, p]) => `${match.groups.id}: «${term}»: ${p}`),
    ),
  );
  assert.deepEqual(problems, []);
});

// read_file takes the path from the skills folder (skills/<skill>/references/<file>.md); a bare references/… is not found.
test('every skill with reference files names each of them in SKILL.md by its full path, and names no other', () => {
  for (const skill of new Set(referenceFiles.map((ref) => ref.skill))) {
    const text = readText(path.join(skillsDir, skill, 'SKILL.md'));
    const pattern = new RegExp(`\`skills/${skill}/references/([a-z0-9-]+\\.md)\``, 'g');
    const named = [...new Set([...text.matchAll(pattern)].map((m) => m[1]))].sort();
    assert.deepEqual(named, referenceFiles.filter((ref) => ref.skill === skill).map((ref) => ref.name).sort(), skill);
    assert.ok(!/`references\//.test(text), `${skill}: a bare references/ path`);
  }
});

test('every practice note has a source record, and every record names a note, its file and an unchanged page', () => {
  // The file is shared with the other distillation outputs (eval set, Cassation leads, search vocabulary), whose
  // records carry an «output» field; the practice notes' records have none.
  const records = readText(SOURCES).split('\n').filter(Boolean).map((line) => JSON.parse(line)).filter((record) => !('output' in record));
  const byId = new Map(parsed.map(({ file, skill, match }) => [match.groups.id, { file, skill }]));
  const fields = ['item', 'skill', 'file', 'page', 'sha256', 'post_date', 'distilled_on', 'review'];
  const pairs = new Set();
  for (const record of records) {
    assert.deepEqual(Object.keys(record), fields, `${record.item}: the record's fields`);
    const note = byId.get(record.item);
    assert.ok(note, `${record.item}: no practice note with this id`);
    assert.equal(record.file, note.file, `${record.item}: the record names another file`);
    assert.equal(record.skill, note.skill, `${record.item}: the record names another skill`);
    assert.equal(record.review, MARK);
    assert.match(record.distilled_on, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(record.page.startsWith('jordanian-law/references/docs/markdown/'), `${record.item}: ${record.page}`);
    const page = fs.readFileSync(path.join(repoDir, record.page));
    assert.equal(crypto.createHash('sha256').update(page).digest('hex'), record.sha256, `${record.item}: ${record.page} changed`);
    assert.equal(/^date: "(\d{4}-\d{2}-\d{2})"$/m.exec(page.toString('utf8'))?.[1], record.post_date, `${record.item}: post date`);
    const pair = `${record.item} ${record.page}`;
    assert.ok(!pairs.has(pair), `${pair}: recorded twice`);
    pairs.add(pair);
  }
  assert.deepEqual([...byId.keys()].filter((id) => !records.some((r) => r.item === id)), [], 'notes without a source record');
});

// The owner, 2026-11-14: model-facing text never names the site, its firm or its title, and has no links to it; and no
// Egyptian law (2026-11-13). Statutory text is not served from these files, so a plain search is enough here.
test('what the model reads of a skill with practice notes names no copy site and links nowhere, and no note names Egyptian law', () => {
  const COPY_SITE = /jordan-lawyer|حماة الحق|حُماة الحق|محامي الأردن|محامي الاردن|https?:\/\/|www\./i;
  for (const skill of new Set(notes.map((n) => n.skill))) {
    const served = [{ file: `${skill}/SKILL.md`, text: readText(path.join(skillsDir, skill, 'SKILL.md')) }, ...referenceFiles.filter((ref) => ref.skill === skill)];
    for (const { file, text } of served) assert.ok(!COPY_SITE.test(text), `${file}: ${COPY_SITE.exec(text)?.[0]}`);
  }
  for (const { match } of parsed) assert.ok(!/مصري|مصرية|Egypt/i.test(match.input), `${match.groups.id}: Egyptian law`);
});
