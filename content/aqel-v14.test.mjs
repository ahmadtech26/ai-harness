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

test('the visible plan names a law by its name, never by the slug 1.3 keeps from the user', () => {
  assert.ok(!edition.includes('رمز التشريع>'));
  assert.ok(arabic.includes('«- بحث: <اسم التشريع> | limit=<عدد> | <مصطلح النص التشريعي>»'));
  assert.ok(arabic.includes('ولا تذكر هذه الرموز للمستخدم'));
});
