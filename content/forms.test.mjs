// Tests for the form templates and their checker:  node --test content/forms.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { FORMS_DIR, formsProblems, templateProblems, valueProblems } from './forms.mjs';

const TEMPLATE = {
  id: 'demo-form',
  region: 'jo',
  kind: 'court-form',
  version: 1,
  status: 'draft',
  title: 'نموذج تجريبي',
  groups: [{ id: 'party', label: 'الطرف' }],
  fields: [
    { id: 'name', group: 'party', label: 'الاسم', type: 'text', required: true, max: 10 },
    { id: 'national_no', group: 'party', label: 'الرقم الوطني', type: 'national-number', required: false },
    { id: 'facts', label: 'الوقائع', type: 'paragraph', required: false, max: 50 },
    { id: 'reasons', label: 'الأسباب', type: 'list', required: false, maxItems: 2, itemMax: 20 },
    { id: 'kind', label: 'النوع', type: 'choice', required: false, options: ['فاقد', 'تالف'] },
    { id: 'on', label: 'التاريخ', type: 'date', required: false },
  ],
  blank: ['signature'],
  reviewFlags: [],
};
const TYP = '#fill("name") #nn("national_no") #para("facts") #items("reasons") #chosen("kind", "فاقد") #fill("on")';
const check = (template, typ = TYP, options = {}) =>
  templateProblems(template, { region: 'jo', fileId: 'demo-form', typ, ...options });

test('every template in content/forms is valid, with a .typ that prints each field and a valid sample', () => {
  assert.deepEqual(formsProblems(FORMS_DIR), []);
});

test('a .typ that prints a field the JSON does not define is refused', () => {
  assert.deepEqual(check(TEMPLATE, `${TYP} #fill("nam")`), ['the .typ uses "nam", which is not a field']);
});

test('a field the .typ never prints is refused', () => {
  assert.deepEqual(check(TEMPLATE, TYP.replace('#fill("on")', '')), ['field "on" is never printed by the .typ']);
});

test('a text field without a length limit is refused', () => {
  const fields = TEMPLATE.fields.map((f) => (f.id === 'name' ? { ...f, max: undefined } : f));

  assert.deepEqual(check({ ...TEMPLATE, fields }), ['field "name": max must be 1-2000']);
});

test('a release accepts only an approved template with a named reviewer', () => {
  assert.deepEqual(check(TEMPLATE, TYP, { release: true }), ['a release needs status approved and reviewedBy']);
  assert.deepEqual(check({ ...TEMPLATE, status: 'approved', reviewedBy: 'owner, 2026-12-01' }, TYP, { release: true }), []);
});

test('valid values pass, with Arabic-Indic digits in the national number', () => {
  const values = { name: 'فلان', national_no: '٩٨٧١٢٣٤٥٦٧', facts: 'سطر\nسطر', reasons: ['أ'], kind: 'تالف', on: '2026-02-28' };

  assert.deepEqual(valueProblems(TEMPLATE, values), []);
});

test('values are refused when required, too long, unknown or malformed', () => {
  const problems = valueProblems(TEMPLATE, {
    national_no: '987123456',
    facts: 'س'.repeat(51),
    reasons: ['أ', 'ب', 'ج'],
    kind: 'مفقود',
    on: '2026-02-30',
    extra: 'x',
  });

  assert.deepEqual(problems, [
    'unknown field "extra"',
    'name: required',
    'national_no: not a valid national-number',
    'facts: at most 50 characters',
    'reasons: a list of at most 2',
    'kind: not one of its options',
    'on: a date as YYYY-MM-DD',
  ]);
});

test('a line break is refused outside a paragraph, and inside a list item', () => {
  const problems = valueProblems(TEMPLATE, { name: 'فلان\nعلان', reasons: ['أ\nب'] });

  assert.deepEqual(problems, ['name: holds a character it may not', 'reasons: each item one line of 1-20 characters']);
});

test('a template without its sample is reported', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'forms-'));
  fs.mkdirSync(path.join(dir, 'jo'));
  fs.writeFileSync(path.join(dir, 'jo', 'demo-form.json'), JSON.stringify(TEMPLATE));
  fs.writeFileSync(path.join(dir, 'jo', 'demo-form.typ'), TYP);

  assert.deepEqual(formsProblems(dir), ['jo/demo-form: no sample']);
});
