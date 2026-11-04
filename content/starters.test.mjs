// Tests for starters.mjs:  node --test content/starters.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { test } from 'node:test';
import { FEATURED_COUNT, MAX_AREAS, MAX_PER_AREA, MIN_PER_AREA, STARTERS_FILE, featuredTexts, validateStarters } from './starters.mjs';

const shipped = JSON.parse(fs.readFileSync(STARTERS_FILE, 'utf8'));
const clone = () => structuredClone(shipped);

test('the shipped set is valid as a draft and holds enough prompts to cover areas and the four featured', () => {
  assert.deepEqual(validateStarters(shipped), []);
  assert.ok(shipped.areas.length >= 3);
  assert.ok(shipped.areas.every((area) => area.prompts.length >= MIN_PER_AREA));
  assert.equal(shipped.featured.length, FEATURED_COUNT);
});

test('a draft is refused for production until it is approved with a named reviewer', () => {
  assert.ok(validateStarters(shipped, { release: true }).some((e) => e.includes('production needs an approved set')));

  const approved = { ...clone(), status: 'approved' };
  assert.ok(validateStarters(approved, { release: true }).some((e) => e.includes('reviewed_by')));
  assert.deepEqual(validateStarters({ ...approved, reviewed_by: 'المحامي المراجع' }, { release: true }), []);
});

/** A valid document built here, so the rule tests do not depend on what the owner ships. */
function synth() {
  const names = ['civil', 'criminal', 'labour', 'commercial', 'family'];
  const areas = names.map((key) => ({
    key,
    title: key,
    prompts: [1, 2, 3].map((n) => ({ id: `${key}-0${n}`, text: `سؤال تجريبي رقم ${n} في مجال ${key}`, mode: 'send' })),
  }));
  return { version: 1, locale: 'ar', status: 'draft', featured: names.slice(0, 4).map((key) => `${key}-01`), areas };
}

test('rejects a repeated id, a thin area, a short text, a bad mode and an unknown featured id', () => {
  const doc = synth();
  const [first, second, third, fourth] = doc.areas;
  second.prompts[0].id = first.prompts[0].id;
  third.prompts.length = MIN_PER_AREA - 1;
  fourth.prompts[0].text = 'قصير';
  doc.areas[4].prompts[0].mode = 'auto';
  doc.featured[0] = 'ghost-09';

  const errors = validateStarters(doc);

  assert.ok(errors.some((e) => e.includes(`${first.prompts[0].id} used twice`)));
  assert.ok(errors.some((e) => e.includes(`area ${third.key} has fewer than`)));
  assert.ok(errors.some((e) => e.includes(`${fourth.prompts[0].id}: text must be`)));
  assert.ok(errors.some((e) => e.includes(`${doc.areas[4].prompts[0].id}: mode must be`)));
  assert.ok(errors.some((e) => e.includes('featured prompt ghost-09 does not exist')));
});

test('rejects a featured id listed twice and the caps on areas, prompts and title length', () => {
  const dup = synth();
  dup.featured[1] = dup.featured[0];
  assert.ok(validateStarters(dup).some((e) => e.includes('featured lists a prompt id twice')));

  const wide = synth();
  wide.areas = Array.from({ length: MAX_AREAS + 1 }, (_, i) => ({ ...structuredClone(wide.areas[0]), key: `area${i}` }));
  assert.ok(validateStarters(wide).some((e) => e.includes(`more than ${MAX_AREAS} areas`)));

  const long = synth();
  long.areas[0].prompts = Array.from({ length: MAX_PER_AREA + 1 }, (_, i) => ({ ...long.areas[0].prompts[0], id: `civil-${String(i).padStart(2, '0')}` }));
  assert.ok(validateStarters(long).some((e) => e.includes(`more than ${MAX_PER_AREA} prompts`)));

  const titled = synth();
  titled.areas[0].title = 'ع'.repeat(61);
  assert.ok(validateStarters(titled).some((e) => e.includes('title up to 60')));
});

test('lists the four featured texts in order, for the tier agents', () => {
  const texts = featuredTexts(shipped);

  assert.equal(texts.length, 4);
    assert.ok(texts.every((text) => typeof text === 'string'));
});
