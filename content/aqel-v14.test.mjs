// Tests for the PROPOSED AQEL edition 1.4 (not live; goes live only after its bench):  node --test content/aqel-v14.test.mjs
// They read the built edition (prompts/aqel-v1.4-librechat.md, written by prompts/build_aqel.py 1.4). 1.4 is 1.3 with
// the D10 reasoning sequence and nothing else (owner, 2026-11-13: D10 ships on its own, ahead of the legal checks of
// 1.5). These tests hold that 1.4 only adds whole lines to 1.3, that the additions are the D10 block in both languages,
// and that they hand the model no article number.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const contentDir = path.dirname(fileURLToPath(import.meta.url));
const readEdition = (version) =>
  fs.readFileSync(path.join(contentDir, 'prompts', `aqel-v${version}-librechat.md`), 'utf8').replace(/\r\n/g, '\n');
const base = readEdition('1.3');
const edition = readEdition('1.4');
const companionAt = edition.indexOf('ENGLISH SYSTEM PROMPT');
const arabic = edition.slice(0, companionAt);
const english = edition.slice(companionAt);
const isVersionLine = (line) => line.startsWith('SYSTEM PROMPT — VERSION ');
const readJson = (...parts) => JSON.parse(fs.readFileSync(path.join(contentDir, ...parts), 'utf8'));

/** The lines of `next` that are not `previous`'s, in order; fails unless `previous`'s lines (less the version line) survive in order. */
function addedLines(previous, next) {
  const old = previous.split('\n').filter((line) => !isVersionLine(line));
  const added = [];
  let at = 0;
  for (const line of next.split('\n').filter((l) => !isVersionLine(l))) {
    if (at < old.length && line === old[at]) at += 1;
    else added.push(line);
  }
  assert.equal(at, old.length, `line ${at + 1} is missing or changed: ${old[at]?.slice(0, 80)}`);
  return added;
}

test('1.4 carries its version and changes no line of 1.3', () => {
  assert.ok(edition.includes('SYSTEM PROMPT — VERSION 1.4 — '));
  assert.ok(!edition.includes('VERSION 1.3'));
  assert.ok(addedLines(base, edition).length > 0);
});

test('1.4 adds the D10 reasoning sequence and nothing else', () => {
  const added = addedLines(base, edition).filter((line) => line !== '');
  assert.equal(added[0], 'تسلسل التفكير');
  assert.equal(added.length, 4, 'the Arabic heading and two bullets, and the English bullet');
  assert.ok(added[1].startsWith('- رتّب تفكيرك الداخلي') && added[2].startsWith('- قبل أول استدعاء'));
  assert.ok(added[3].startsWith('- Reasoning sequence:'));
  assert.ok(!edition.includes('ضوابط تطبيق المراحل') && !edition.includes('CIVIL AND COMMERCIAL MATTERS'), 'the distilled checks wait for 1.5');
});

test('the added lines name no article number and pass no slug', () => {
  const added = addedLines(base, edition).join('\n');
  assert.deepEqual(added.match(/[0-9٠-٩]+/g) ?? [], []);
  assert.ok(!/المادة\s+[0-9٠-٩]/.test(added));
  assert.ok(!/law="/.test(added));
});

// D10 (handoff 2026-11-12, section 5).
test('1.4 adds the D10 reasoning sequence after the reasoning-language block, in both languages', () => {
  const headings = '«الفهم»، «المسائل»، «خطة البحث»، «الجلب»، «التحقق من الاستشهادات»، «الجواب»';
  const reasoning = arabic.indexOf('لغة التفكير\n- فكّر بالعربية وحدها');
  const sequence = arabic.indexOf('تسلسل التفكير\n');
  assert.ok(reasoning > 0 && sequence > reasoning && sequence < arabic.indexOf('\nاستخدام المكتبة القانونية\n'));
  assert.ok(arabic.includes(headings));
  assert.ok(arabic.includes('«خطة البحث:»') && arabic.includes('«تعديل الخطة:»'));
  assert.ok(english.includes('- Reasoning sequence:') && english.includes('«تعديل الخطة:»'));
  assert.ok(english.indexOf('- Reasoning language:') < english.indexOf('- Reasoning sequence:'));
});

// The owner, 2026-11-13 («Arabic names, no limit»): the visible plan shows the customer neither a slug nor a tool
// argument, so 1.3's rules against both stand unchanged.
const PLAN_LINES = [
  '«- بحث: <اسم التشريع بالعربية> | <مصطلح النص التشريعي>»',
  '«- جلب: <اسم التشريع بالعربية> | <موضوع المادة>»',
];

test('the visible plan names a law by its Arabic name and carries no slug and no limit, in both languages', () => {
  for (const line of PLAN_LINES) {
    assert.ok(arabic.includes(line), `Arabic: ${line}`);
    assert.ok(english.includes(line), `English: ${line}`);
  }
  assert.ok(!edition.includes('رمز التشريع>'));
  assert.ok(!/limit=</.test(edition), 'no limit= in the plan grammar');
  const plan = addedLines(base, edition).join('\n');
  assert.ok(!/limit=|law=/.test(plan), 'the D10 lines show no tool argument');
  assert.ok(arabic.includes('ولا تذكر هذه الرموز للمستخدم'));
});

// The plan-followed check reads the law from the plan line by name: each name the edition gives the model for a law
// must map back to its slug through the registry title or corpus/law-aliases.json, or the check cannot follow it.
test('every law name the edition gives the model maps to its slug for the plan-followed check', () => {
  const { laws } = readJson('corpus', 'laws.json');
  const aliases = readJson('corpus', 'law-aliases.json');
  const library = arabic.split('\n').find((line) => line.startsWith('- التشريعات المحمّلة في المكتبة ورموزها:'));
  const named = [...library.matchAll(/(?:: |، )([^()،:]+?) \(([a-z-]+)\)/g)].map((m) => ({ name: m[1].trim(), slug: m[2] }));
  assert.deepEqual(named.map(({ slug }) => slug).sort(), laws.map(({ slug }) => slug).sort(), 'the edition names every law of the registry');
  const toSlug = new Map(laws.flatMap(({ slug, title }) => [[title, slug], ...(aliases[slug] ?? []).map((alias) => [alias, slug])]));
  assert.deepEqual(named.filter(({ name, slug }) => toSlug.get(name) !== slug), []);
});
