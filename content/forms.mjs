// Checks the court and notary form templates:  node content/forms.mjs check [--release]
//
// Each template is content/forms/<region>/<id>.json (its fields and their rules) beside <id>.typ (its fixed text and
// layout), with a sample of dummy values in content/forms/samples/<region>/<id>.json (spec
// .hq/docs/specs/2026-11-17-court-forms-spec.md). The API validates a user's values with the same rules
// (valueProblems), so a value this file refuses never reaches the renderer. `--release` also demands `status:
// approved` with a named reviewer: only the owner sets it, after the lawyer's reading; drafts are for staff.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const FORMS_DIR = path.join(here, 'forms');
export const REGIONS = ['jo'];
export const KINDS = ['court-form'];
export const STATUSES = ['draft', 'approved'];
/** Parts of a printed form that always stay blank: the user never fills them. */
export const BLANK_PARTS = ['signature', 'court-box', 'notary', 'dates', 'seal'];
export const TYPES = ['text', 'paragraph', 'list', 'choice', 'national-number', 'phone', 'year', 'date', 'amount'];
const TEMPLATE_ID = /^[a-z]+(?:-[a-z]+)*$/;
const FIELD_ID = /^[a-z]+(?:_[a-z0-9]+)*$/;
/** The .typ helpers that take a field id (content/forms/lib/form.typ). */
const TYP_REFERENCE = /\b(?:val|fill|nn|para|items|chosen|has)\("([^"]*)"/g;
const DIGIT = '[0-9٠-٩]';
const VALUE_PATTERNS = {
  'national-number': new RegExp(`^${DIGIT}{10}$`),
  phone: new RegExp(`^\\+?${DIGIT}(?:[ -]?${DIGIT}){6,14}$`),
  year: new RegExp(`^${DIGIT}{4}$`),
  amount: new RegExp(`^${DIGIT}{1,9}(?:\\.${DIGIT}{1,3})?$`),
};
// Control characters other than the line break a paragraph may hold.
const CONTROL = /[\u0000-\u0009\u000B-\u001F\u007F]/;

const isCount = (value, max) => Number.isInteger(value) && value >= 1 && value <= max;

/** Problems with one field's definition, as readable lines. */
function fieldProblems(field, groupIds) {
  const out = [];
  const at = `field ${JSON.stringify(field?.id)}`;
  if (!FIELD_ID.test(field?.id ?? '')) out.push(`${at}: id must be snake_case`);
  if (typeof field?.label !== 'string' || !field.label.trim()) out.push(`${at}: no label`);
  if (!TYPES.includes(field?.type)) out.push(`${at}: unknown type ${JSON.stringify(field?.type)}`);
  if (typeof field?.required !== 'boolean') out.push(`${at}: required must be true or false`);
  if (field?.group !== undefined && !groupIds.has(field.group)) out.push(`${at}: unknown group ${field.group}`);
  if ((field?.type === 'text' || field?.type === 'paragraph') && !isCount(field.max, 2000)) {
    out.push(`${at}: max must be 1-2000`);
  }
  if (field?.type === 'list' && (!isCount(field.maxItems, 20) || !isCount(field.itemMax, 1000))) {
    out.push(`${at}: a list needs maxItems 1-20 and itemMax 1-1000`);
  }
  if (field?.type === 'choice') {
    const options = Array.isArray(field.options) ? field.options : [];
    if (options.length < 2 || new Set(options).size !== options.length || !options.every((o) => typeof o === 'string' && o.trim())) {
      out.push(`${at}: a choice needs two or more distinct options`);
    }
  }
  return out;
}

/** Problems with a template's JSON and its .typ, as readable lines; empty when it is valid. */
export function templateProblems(template, { region, fileId, typ, release = false }) {
  const out = [];
  if (template?.id !== fileId || !TEMPLATE_ID.test(fileId)) out.push(`id must be the file name in kebab-case`);
  if (template?.region !== region || !REGIONS.includes(region)) out.push(`region must be its folder, one of ${REGIONS}`);
  if (!KINDS.includes(template?.kind)) out.push(`kind must be one of ${KINDS}`);
  if (!Number.isInteger(template?.version) || template.version < 1) out.push('version must be a whole number from 1');
  if (!STATUSES.includes(template?.status)) out.push(`status must be one of ${STATUSES}`);
  if (release && (template?.status !== 'approved' || !String(template?.reviewedBy ?? '').trim())) {
    out.push('a release needs status approved and reviewedBy');
  }
  if (typeof template?.title !== 'string' || !template.title.trim()) out.push('no title');
  const groups = Array.isArray(template?.groups) ? template.groups : [];
  const groupIds = new Set(groups.map((g) => g?.id));
  if (groupIds.size !== groups.length || groups.some((g) => !FIELD_ID.test(g?.id ?? '') || !String(g?.label ?? '').trim())) {
    out.push('groups need distinct snake_case ids and labels');
  }
  const fields = Array.isArray(template?.fields) ? template.fields : [];
  if (!fields.length) out.push('no fields');
  const ids = fields.map((f) => f?.id);
  for (const id of ids.filter((id, i) => ids.indexOf(id) !== i)) out.push(`field ${JSON.stringify(id)} defined twice`);
  for (const field of fields) out.push(...fieldProblems(field, groupIds));
  const blank = Array.isArray(template?.blank) ? template.blank : null;
  if (!blank || blank.some((part) => !BLANK_PARTS.includes(part))) out.push(`blank must list parts from ${BLANK_PARTS}`);
  if (!Array.isArray(template?.reviewFlags) || template.reviewFlags.some((f) => typeof f !== 'string' || !f.trim())) {
    out.push('reviewFlags must be a list of texts');
  }
  if (typeof typ !== 'string') {
    out.push('no .typ beside the JSON');
  } else {
    const used = new Set([...typ.matchAll(TYP_REFERENCE)].map((m) => m[1]));
    for (const id of used) if (!ids.includes(id)) out.push(`the .typ uses ${JSON.stringify(id)}, which is not a field`);
    for (const id of ids) if (!used.has(id)) out.push(`field ${JSON.stringify(id)} is never printed by the .typ`);
  }
  return out;
}

/** Problems with a user's values for a template, as readable lines; empty when they may be rendered. */
export function valueProblems(template, values) {
  if (values === null || typeof values !== 'object' || Array.isArray(values)) return ['values must be an object'];
  const out = [];
  const byId = new Map(template.fields.map((f) => [f.id, f]));
  for (const key of Object.keys(values)) if (!byId.has(key)) out.push(`unknown field ${JSON.stringify(key)}`);
  for (const field of template.fields) {
    const value = values[field.id];
    const empty = value === undefined || value === null || value === '' || (Array.isArray(value) && !value.length);
    if (empty) {
      if (field.required) out.push(`${field.id}: required`);
      continue;
    }
    if (field.type === 'list') {
      if (!Array.isArray(value) || value.length > field.maxItems) {
        out.push(`${field.id}: a list of at most ${field.maxItems}`);
      } else if (value.some((item) => typeof item !== 'string' || !item.trim() || item.length > field.itemMax || CONTROL.test(item) || item.includes('\n'))) {
        out.push(`${field.id}: each item one line of 1-${field.itemMax} characters`);
      }
      continue;
    }
    if (typeof value !== 'string') {
      out.push(`${field.id}: must be text`);
    } else if (CONTROL.test(value) || (field.type !== 'paragraph' && value.includes('\n'))) {
      out.push(`${field.id}: holds a character it may not`);
    } else if ((field.type === 'text' || field.type === 'paragraph') && value.length > field.max) {
      out.push(`${field.id}: at most ${field.max} characters`);
    } else if (field.type === 'choice' && !field.options.includes(value)) {
      out.push(`${field.id}: not one of its options`);
    } else if (field.type === 'date' && !isDate(value)) {
      out.push(`${field.id}: a date as YYYY-MM-DD`);
    } else if (VALUE_PATTERNS[field.type] && !VALUE_PATTERNS[field.type].test(value)) {
      out.push(`${field.id}: not a valid ${field.type}`);
    }
  }
  return out;
}

function isDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8'));
const readIf = (file) => (fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : undefined);

/** Every template under `dir`, checked with its .typ and its sample; problems as `<region>/<id>: <line>`. */
export function formsProblems(dir = FORMS_DIR, { release = false } = {}) {
  const out = [];
  let count = 0;
  for (const region of fs.readdirSync(dir).filter((name) => !['lib', 'samples'].includes(name))) {
    const regionDir = path.join(dir, region);
    if (!fs.statSync(regionDir).isDirectory()) continue;
    for (const name of fs.readdirSync(regionDir).filter((n) => n.endsWith('.json')).sort()) {
      const fileId = name.slice(0, -'.json'.length);
      const at = `${region}/${fileId}`;
      count += 1;
      let template;
      try {
        template = readJson(path.join(regionDir, name));
      } catch (error) {
        out.push(`${at}: not JSON (${error.message})`);
        continue;
      }
      const typ = readIf(path.join(regionDir, `${fileId}.typ`));
      const problems = templateProblems(template, { region, fileId, typ, release });
      out.push(...problems.map((p) => `${at}: ${p}`));
      if (problems.length) continue;
      const sample = path.join(dir, 'samples', region, name);
      if (!fs.existsSync(sample)) out.push(`${at}: no sample`);
      else out.push(...valueProblems(template, readJson(sample)).map((p) => `${at}: sample: ${p}`));
    }
  }
  if (!count) out.push('no templates');
  return out;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const [command, ...rest] = process.argv.slice(2);
  if (command !== 'check') {
    console.error('usage: node content/forms.mjs check [--release]');
    process.exit(2);
  }
  const problems = formsProblems(FORMS_DIR, { release: rest.includes('--release') });
  for (const line of problems) console.log(line);
  console.log(problems.length ? 'FORMS_INVALID' : 'FORMS_OK');
  process.exit(problems.length ? 1 : 0);
}
