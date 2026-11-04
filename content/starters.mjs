// Checks the reviewed starter prompts:  node content/starters.mjs check [file] [--release]
//
// Mirrors the fork's startup check (`packages/api/src/iqraa/starters.ts`, which refuses to start on an invalid
// file): the same rules, run here at release time so a bad file never reaches an image. `--release` (production)
// also demands `status: approved` with a named reviewer; staging and drills accept `draft`.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const STARTERS_FILE = path.join(here, 'starters', 'starters.ar.json');
export const MIN_PER_AREA = 3;
export const FEATURED_COUNT = 4;
/** The same caps as the fork's `starters.ts`. */
export const MAX_AREAS = 12;
export const MAX_PER_AREA = 30;
export const MAX_FILE_BYTES = 200_000;
const ID = /^[a-z]+(?:-[a-z]+)*-\d{2}$/;

/** Problems with the starters file, as readable lines; empty when it is valid. */
export function validateStarters(doc, { release = false } = {}) {
  const errors = [];
  if (doc?.version !== 1 || doc?.locale !== 'ar') errors.push('version must be 1 and locale ar');
  if (!['draft', 'approved'].includes(doc?.status)) errors.push("status must be 'draft' or 'approved'");
  if (release && doc?.status !== 'approved') errors.push("status is 'draft': production needs an approved set");
  if (doc?.status === 'approved' && !doc.reviewed_by?.trim()) errors.push('an approved set needs reviewed_by');
  const ids = new Set();
  const keys = new Set();
  if ((doc?.areas ?? []).length > MAX_AREAS) errors.push(`more than ${MAX_AREAS} areas`);
  for (const area of doc?.areas ?? []) {
    if (!area.key || !area.title) errors.push(`an area needs a key and a title (${area.key ?? '?'})`);
    if (String(area.key ?? '').length > 40 || String(area.title ?? '').length > 60) {
      errors.push(`area ${area.key}: key up to 40 and title up to 60 characters`);
    }
    if (keys.has(area.key)) errors.push(`area key ${area.key} used twice`);
    keys.add(area.key);
    if ((area.prompts ?? []).length < MIN_PER_AREA) errors.push(`area ${area.key} has fewer than ${MIN_PER_AREA} prompts`);
    if ((area.prompts ?? []).length > MAX_PER_AREA) errors.push(`area ${area.key} has more than ${MAX_PER_AREA} prompts`);
    for (const prompt of area.prompts ?? []) {
      if (!ID.test(prompt.id ?? '')) errors.push(`prompt id ${prompt.id} must look like civil-01`);
      if (ids.has(prompt.id)) errors.push(`prompt id ${prompt.id} used twice`);
      ids.add(prompt.id);
      if (typeof prompt.text !== 'string' || prompt.text.trim().length < 10 || prompt.text.length > 400) {
        errors.push(`prompt ${prompt.id}: text must be 10 to 400 characters`);
      }
      if (!['send', 'fill'].includes(prompt.mode)) errors.push(`prompt ${prompt.id}: mode must be send or fill`);
    }
  }
  if (ids.size === 0) errors.push('no prompts');
  if (new Set(doc?.featured ?? []).size !== (doc?.featured ?? []).length) errors.push('featured lists a prompt id twice');
  if ((doc?.featured ?? []).length !== FEATURED_COUNT) errors.push(`featured must list exactly ${FEATURED_COUNT} prompt ids`);
  for (const id of doc?.featured ?? []) {
    if (!ids.has(id)) errors.push(`featured prompt ${id} does not exist`);
  }
  return errors;
}

/** The featured prompts' texts in order: what each tier agent shows as its starters. */
export function featuredTexts(doc) {
  const byId = new Map(doc.areas.flatMap((area) => area.prompts).map((prompt) => [prompt.id, prompt.text]));
  return doc.featured.map((id) => byId.get(id));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const file = args.find((arg, i) => i > 0 && !arg.startsWith('--')) ?? STARTERS_FILE;
  if (args[0] !== 'check') {
    console.error('usage: starters.mjs check [file] [--release]');
    process.exit(2);
  }
  const size = fs.statSync(file).size;
  const errors =
    size > MAX_FILE_BYTES
      ? [`${file}: larger than ${MAX_FILE_BYTES} bytes`]
      : validateStarters(JSON.parse(fs.readFileSync(file, 'utf8')), { release: args.includes('--release') });
  if (errors.length > 0) {
    console.error(errors.join('\n'));
    process.exit(1);
  }
  console.log(`starters ok: ${file}`);
}
