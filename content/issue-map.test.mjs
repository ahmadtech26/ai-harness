// Tests for the PROPOSED skill jordanian-civil-issue-map (draft, for lawyer review):  node --test content/issue-map.test.mjs
// Each line of its reference files is a method sentence from docs/distillation/2026-11-12-book-principles.md with the
// statutory terms to search. These tests hold the lines to the corpus: a term the model is told to search must be in
// the named law's text, a line may name no article number, and each line's catalogue entry must exist and propose the
// same sentence and terms. The same checks run on any other skill's reference line that ends in a catalogue id. A
// line names one search or more, each a law and its terms: «— البحث: law="civil-code"، «…»، «…»؛ law="evidence"، «…».»
// Every term is a statutory noun phrase (search-terms.mjs; owner, 2026-11-13).
// Files are read with either line end: a Windows checkout gives CRLF, and a line that kept its \r would match nothing.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { normalise, termProblem } from './search-terms.mjs';

const contentDir = path.dirname(fileURLToPath(import.meta.url));
const skillsDir = path.join(contentDir, 'skills');
const ISSUE_MAP = 'jordanian-civil-issue-map';
const skillDir = path.join(skillsDir, ISSUE_MAP);
const readText = (file) => fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
const catalogue = readText(path.join(contentDir, '..', 'docs', 'distillation', '2026-11-12-book-principles.md'));
const { laws } = JSON.parse(fs.readFileSync(path.join(contentDir, 'corpus', 'laws.json'), 'utf8'));
const LINE = /^- (?<text>.+?)(?: — البحث: (?<searches>law="[a-z-]+"، .+?))?\. <!-- (?<id>V[0-9A-Z]+-[0-9]+) -->$/;
const ID_COMMENT = / <!-- V[0-9A-Z]+-[0-9]+ -->$/;

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

/** «law="a"، «x»، «y»؛ law="b"، «z»» as [{ law, terms }]. */
const parseSearches = (searches) =>
  (searches ?? '').split('؛ ').filter(Boolean).map((part) => {
    const m = /^law="([a-z-]+)"، (.+)$/.exec(part);
    return { law: m?.[1], terms: (m?.[2] ?? '').split('، ').map((t) => t.replace(/^«|»$/g, '')) };
  });

/** Each catalogue entry's proposed sentence and search, by id. */
const proposals = new Map(
  catalogue
    .split(/\n(?=#### )/)
    .map((block) => {
      const id = /^#### (V[0-9A-Z]+-[0-9]+) ·/.exec(block)?.[1];
      const sentence = /^- \*\*صياغة منهجية مقترحة:\*\* (.+)$/m.exec(block)?.[1];
      const search = /^- \*\*ما يُبحث عنه في المكتبة:\*\* (.+)$/m.exec(block)?.[1] ?? '';
      const searches = search.split('؛ ').map((part) => {
        const m = /^`search_law` law="([a-z-]+)": (.+)$/.exec(part);
        return { law: m?.[1], terms: (m?.[2] ?? '').split('، ').map((t) => t.replace(/^«|»$/g, '')) };
      });
      return [id, { sentence, searches }];
    })
    .filter(([id]) => id),
);

test('reads a reference file the same with CRLF or LF line ends', () => {
  const { skill, text } = referenceFiles.find((ref) => ref.skill === ISSUE_MAP);
  assert.ok(entryLines(text, skill).length > 0);
  assert.deepEqual(entryLines(text.replace(/\n/g, '\r\n'), skill), entryLines(text, skill));
});

// read_file takes the path from the skills folder (skills/<skill>/references/<file>.md); a bare references/… is not found.
test('SKILL.md sends the model only to reference files that exist, and to all of them, by their full path', () => {
  const skill = readText(path.join(skillDir, 'SKILL.md'));
  const named = [...skill.matchAll(/`skills\/jordanian-civil-issue-map\/references\/([a-z-]+\.md)`/g)].map((m) => m[1]);
  const files = referenceFiles.filter((ref) => ref.skill === ISSUE_MAP).map((ref) => ref.name);
  assert.deepEqual([...named].sort(), [...files].sort());
  assert.ok(!/`references\//.test(skill), 'a bare references/ path');
});

// The owner, 2026-11-13 («Forbid in model text»): what the model reads of the skill (the SKILL.md body and the
// reference files, comments included) names Egyptian law once, in the rule that forbids it, and never the source book.
// The provenance stays in the SKILL.md frontmatter (metadata.review.note).
test('the skill names Egyptian law only to forbid it, and names no source book where the model reads it', () => {
  const skill = readText(path.join(skillDir, 'SKILL.md'));
  const body = skill.slice(skill.indexOf('\n---\n', 3) + 5);
  const served = [{ file: 'SKILL.md', text: body }, ...referenceFiles.filter((ref) => ref.skill === ISSUE_MAP).map(({ name, text }) => ({ file: name, text }))];
  const egyptian = served.flatMap(({ file, text }) => text.split('\n').filter((line) => /مصري|مصرية|Egypt/i.test(line)).map((line) => `${file}: ${line}`));
  assert.deepEqual(egyptian, ['SKILL.md: - لا تذكر في الإجابة القانون المصري أو شروحه، ولا تقارن بهما.']);
  const source = served.flatMap(({ file, text }) => (/السنهوري|Sanhuri|الوسيط في شرح|al-Wasit|«الوسيط»/.test(text) ? [file] : []));
  assert.deepEqual(source, []);
  assert.ok(/Sanhuri/.test(skill.slice(0, skill.indexOf('\n---\n', 3))), 'the provenance is in the frontmatter');
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
    const { id, text, searches } = match.groups;
    const proposal = proposals.get(id);
    // The catalogue ends the sentence with a full stop; the skill line puts its search before the stop.
    assert.ok([text, `${text}.`].includes(proposal.sentence), `${id}: the sentence differs from the catalogue's «صياغة منهجية مقترحة»`);
    assert.deepEqual(parseSearches(searches), proposal.searches, `${id}: the search differs from the catalogue's «ما يُبحث عنه»`);
  }
});

// search_law matches the statute's words: a term that is not in the named law returns nothing for the model.
test('every search term is in the named law\'s text in the corpus', () => {
  const slugs = laws.map((law) => law.slug);
  let checked = 0;
  for (const { match } of entries.filter(({ match }) => match?.groups.searches)) {
    const { id, searches } = match.groups;
    for (const { law, terms } of parseSearches(searches)) {
      assert.ok(slugs.includes(law), `${id}: unknown law ${law}`);
      for (const term of terms) {
        assert.ok(lawText(law).includes(normalise(term)), `${id}: «${term}» is not in ${law}`);
        checked += 1;
      }
    }
  }
  assert.ok(checked > 0, 'no search term was checked: are the lines read?');
  assert.equal(entries.filter(({ match }) => match?.groups.searches).length, entries.length, 'every line names its search');
});

// The owner, 2026-11-13 («Noun phrases only»): the words of the statute that name the issue, never a proposition the
// model could repeat as a rule, and never an amount.
test('every search term is a statutory noun phrase', () => {
  const problems = entries.flatMap(({ match }) =>
    parseSearches(match?.groups.searches).flatMap(({ terms }) =>
      terms.map((term) => [term, termProblem(term)]).filter(([, problem]) => problem).map(([term, problem]) => `${match.groups.id}: «${term}»: ${problem}`),
    ),
  );
  assert.deepEqual(problems, []);
});

test('the noun-phrase rule rejects propositions and amounts, and keeps noun phrases', () => {
  const rejected = [
    'الرهن لا يتجزا', 'لا يسال أحد عن فعل غيره', 'لا ينعقد الرهن التاميني الا بتسجيله', 'الاضطرار لا يبطل حق الغير',
    'يفسر الشك في مصلحة المدين', 'لا ينقضي الحق بمرور الزمان', 'يعزل وكيله متى أراد', 'ثلث التركة', 'لا تسمع الدعوى',
    'هلك المبيع قبل التسليم', 'فيشترط التعدي', 'ما فاته من كسب', 'إذا تعدد الكفلاء', 'ولو غير مميز', 'وتتم بالقبض',
  ];
  const kept = [
    'تعدد الكفلاء', 'يد عدل', 'يسار المحال عليه', 'عدم سماع الدعوى', 'التعهد بنقل ملكية عقار', 'بالتسجيل',
    'غير مسجل في دائرة التسجيل', 'فعل نافع للغير دون أمره', 'وضامنه الاحتياطي', 'الثمن المسمى',
  ];
  assert.deepEqual(rejected.filter((term) => !termProblem(term)), []);
  assert.deepEqual(kept.filter((term) => termProblem(term)), []);
});
