// The law names the citation guard recognises:  node content/grounding-laws.mjs write | check
//
// Builds content/corpus/grounding-laws.json from the registry (`corpus/laws.json`: slug, title as the library
// prints it in a citation heading, number and year) and the short names lawyers write (`corpus/law-aliases.json`).
// The fork loads the generated file at startup (`iqraa.json` grounding.lawsPath). Never edit it by hand: `check`
// fails when it differs from what `write` would produce, so a new law cannot ship without its names.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const LAWS_FILE = path.join(here, 'corpus', 'laws.json');
export const ALIASES_FILE = path.join(here, 'corpus', 'law-aliases.json');
export const OUTPUT_FILE = path.join(here, 'corpus', 'grounding-laws.json');

/** The generated document, or throws on an alias for an unknown law or one shared by two laws. */
export function buildGroundingLaws(lawsDoc, aliases) {
  const slugs = new Set(lawsDoc.laws.map((law) => law.slug));
  const owner = new Map();
  for (const [slug, names] of Object.entries(aliases)) {
    if (!slugs.has(slug)) throw new Error(`law-aliases.json names an unknown law: ${slug}`);
    for (const name of names) {
      if (owner.has(name)) throw new Error(`alias «${name}» belongs to ${owner.get(name)} and ${slug}`);
      owner.set(name, slug);
    }
  }
  const laws = lawsDoc.laws.map((law) => ({
    slug: law.slug,
    title: law.title,
    ...(aliases[law.slug]?.length ? { aliases: aliases[law.slug] } : {}),
    ...(law.number != null ? { number: law.number } : {}),
    ...(law.year != null ? { year: law.year } : {}),
  }));
  for (const law of laws) {
    if (owner.has(law.title) && owner.get(law.title) !== law.slug) throw new Error(`alias «${law.title}» is another law's title`);
  }
  return { version: 1, laws };
}

const render = (doc) => JSON.stringify(doc, null, 2) + '\n';
const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8'));

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const built = render(buildGroundingLaws(readJson(LAWS_FILE), readJson(ALIASES_FILE)));
  if (process.argv[2] === 'write') {
    fs.writeFileSync(OUTPUT_FILE, built);
    console.log(`wrote ${OUTPUT_FILE}`);
  } else if (process.argv[2] === 'check') {
    if (!fs.existsSync(OUTPUT_FILE) || fs.readFileSync(OUTPUT_FILE, 'utf8').replace(/\r\n/g, '\n') !== built) {
      console.error('grounding-laws.json is out of date: run node content/grounding-laws.mjs write');
      process.exit(1);
    }
    console.log('grounding-laws.json is up to date');
  } else {
    console.error('usage: grounding-laws.mjs write | check');
    process.exit(2);
  }
}
