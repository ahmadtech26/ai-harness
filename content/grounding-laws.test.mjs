// Tests for grounding-laws.mjs:  node --test content/grounding-laws.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { test } from 'node:test';
import { ALIASES_FILE, LAWS_FILE, OUTPUT_FILE, buildGroundingLaws } from './grounding-laws.mjs';

const laws = JSON.parse(fs.readFileSync(LAWS_FILE, 'utf8'));
const aliases = JSON.parse(fs.readFileSync(ALIASES_FILE, 'utf8'));

test('lists every law of the registry with its title, number, year and short names', () => {
  const built = buildGroundingLaws(laws, aliases);
  const civil = built.laws.find((law) => law.slug === 'civil-code');

  assert.equal(built.laws.length, laws.laws.length);
  assert.deepEqual(civil, { slug: 'civil-code', title: 'القانون المدني الأردني', aliases: ['القانون المدني'], number: 43, year: 1976 });
  assert.deepEqual(built.laws.find((law) => law.slug === 'court-fees'), { slug: 'court-fees', title: 'جدول رسوم المحاكم' });
});

test('the checked-in file is what the registry and the aliases produce', () => {
  const onDisk = fs.readFileSync(OUTPUT_FILE, 'utf8').replace(/\r\n/g, '\n'); // a checkout with CRLF line endings is the same file

  assert.equal(onDisk, JSON.stringify(buildGroundingLaws(laws, aliases), null, 2) + '\n');
});

test('refuses an alias for an unknown law, an alias two laws share, and an alias that is another law title', () => {
  assert.throws(() => buildGroundingLaws(laws, { nope: ['x'] }), /unknown law: nope/);
  assert.throws(() => buildGroundingLaws(laws, { 'civil-code': ['س'], 'penal-code': ['س'] }), /belongs to civil-code and penal-code/);
  assert.throws(() => buildGroundingLaws(laws, { 'civil-code': ['قانون العمل'] }), /another law's title/);
});
