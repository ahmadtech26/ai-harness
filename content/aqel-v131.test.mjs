// Tests for AQEL edition 1.3.1 (owner, 2026-11-14):  node --test content/aqel-v131.test.mjs
// They read the built edition (prompts/aqel-v1.3.1-librechat.md, written by prompts/build_aqel.py 1.3.1) and the fast
// tier's suffix (prompts/aqel-v1.3.1-fast.md, written by the same build). 1.3.1 is 1.3 with five rules: search the right
// law, the memo matches the analysis, no guessed article numbers, honest gap wording, and the allowance read from the
// library's remaining-budget line instead of a fixed number. The tool texts it relies on are legal-search's, pinned
// here literally as aqel-edition.test.mjs pins the guard forms: they cannot be imported from this repository.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const contentDir = path.dirname(fileURLToPath(import.meta.url));
const readPrompt = (name) => fs.readFileSync(path.join(contentDir, 'prompts', name), 'utf8').replace(/\r\n/g, '\n');
const base = readPrompt('aqel-v1.3-librechat.md');
const edition = readPrompt('aqel-v1.3.1-librechat.md');
const companionAt = edition.indexOf('ENGLISH SYSTEM PROMPT');
const arabic = edition.slice(0, companionAt);
const english = edition.slice(companionAt);

/** legal-search tools.py BUDGET_LINE (plan S3; owner-approved 2026-11-14): the last line of every served reply. */
const BUDGET_LINE = 'النصوص المتبقية لهذه الإجابة: {left} من {per_answer}.';
const BUDGET_PREFIX = BUDGET_LINE.slice(0, BUDGET_LINE.indexOf(' {left}'));
/** legal-search tools.py CAP_DAILY (plan S2; owner-approved 2026-11-14): the refusal at the account's daily cap. */
const CAP_DAILY =
  'تم بلوغ الحد المسموح من النصوص لهذا اليوم في هذا الحساب. لا تستدعِ أدوات المكتبة بعد الآن في هذه الإجابة؛ ' +
  'أجب بما استُرجع وحده، واذكر للمستخدم بموضوعها النقاط التي بقيت دون نص مسترجع، وأن حد اليوم قد بلغ.';
const DAILY_WORDS = 'لهذا اليوم في هذا الحساب';

/** The v1.3 lines (1-based) 1.3.1 replaces; line 78 becomes two lines. */
const CHANGED = [2, 56, 66, 72, 78, 79, 133, 165, 190];

/**
 * The lines of `next` that are not `previous`'s, in order. Fails unless every line of `previous` but the `changed` ones
 * survives in order, and unless no changed line survives verbatim.
 */
function replacedLines(previous, next, changed) {
  const lines = previous.split('\n');
  const kept = lines.filter((_, i) => !changed.includes(i + 1));
  const added = [];
  let at = 0;
  for (const line of next.split('\n')) {
    if (at < kept.length && line === kept[at]) at += 1;
    else added.push(line);
  }
  assert.equal(at, kept.length, `unchanged line missing or changed: ${kept[at]?.slice(0, 80)}`);
  for (const number of changed) assert.ok(!next.split('\n').includes(lines[number - 1]), `v1.3 line ${number} is still there`);
  return added;
}

/** The whole line of `text` that starts with `prefix`; fails unless exactly one does. */
function lineStarting(text, prefix) {
  const lines = text.split('\n').filter((line) => line.startsWith(prefix));
  assert.equal(lines.length, 1, `one line starting ${prefix}`);
  return lines[0];
}

const budgetBullets = () => [
  lineStarting(arabic, '- لكل إجابة رصيد'),
  lineStarting(arabic, '- خطّط لعمليات البحث قبل أول استدعاء'),
  lineStarting(english, '- Each answer may receive'),
];

test('1.3.1 changes only the lines it names', () => {
  // Fails if the edition touches any other v1.3 line, or leaves one of the named lines as it was.
  const added = replacedLines(base, edition, CHANGED);

  assert.equal(added.length, CHANGED.length + 1, 'nine lines replaced, line 78 now two');
  assert.equal(added[0], 'SYSTEM PROMPT — VERSION 1.3.1 — 14 November 2026');
  assert.ok(!edition.includes('VERSION 1.3 —'));
});

test('the budget bullets hold no digit but 5, no 3+3+2 and no limit=3, and name «النصوص المتبقية لهذه الإجابة:»', () => {
  // Fails if a fixed allowance survives (the allowance is per tier now) or the model is not sent to the budget line.
  const bullets = budgetBullets();

  assert.deepEqual(bullets.flatMap((line) => line.match(/[0-9٠-٩]+/g) ?? []).filter((digits) => digits !== '5'), []);
  assert.ok(bullets.every((line) => !line.includes('3+3+2') && !line.includes('limit=3')));
  assert.equal(BUDGET_PREFIX, 'النصوص المتبقية لهذه الإجابة:');
  assert.ok(bullets[0].includes(`«${BUDGET_PREFIX} …»`));
  assert.ok(bullets[2].includes(`«${BUDGET_PREFIX} …»`));
  assert.ok(!edition.includes('لا يتجاوز 8') && !edition.includes('at most 8'));
});

test('«ولا توزّع البحث» and «كلما عُرف التشريع» are gone', () => {
  // Fails if the old line-78 phrases survive: they told the model to pass law whenever it knew one law.
  assert.ok(!edition.includes('لا توزّع البحث'));
  assert.ok(!edition.includes('كلما عُرف التشريع'));
});

test('the right-law, no-guess, memo and gap rules appear in both languages', () => {
  // Fails if any of the four rules is missing from either language.
  const rules = [
    ['right law', 'ولا تحصر البحث في تشريع واحد إلا إذا كانت المسألة كلها فيه', 'restrict a search to one law only when the whole issue lies in it'],
    ['no guess', 'أما رقم تتذكره أو تخمّنه فلا تستدعِ به get_article', 'never call get_article with a number recalled from memory or guessed'],
    ['memo', 'فطابق كل سبب فيها بالنص المقتبس الذي يستند إليه', 'When the answer includes a memo or draft, check each of its reasons'],
    ['gap', 'ولا تنسب النقص إلى المكتبة', 'do not blame the library for the gap'],
  ];
  for (const [rule, ar, en] of rules) {
    assert.ok(arabic.includes(ar), `${rule}: Arabic`);
    assert.ok(english.includes(en), `${rule}: English`);
  }
});

test('the fast suffix has no digit and names tiers.json\'s expert label «عقل خبير»', () => {
  // Fails if the fast tier is told a number (its allowance comes from the budget line) or is sent to a tier label that
  // tiers.json does not give the expert tier.
  const suffix = readPrompt('aqel-v1.3.1-fast.md');
  const { tiers } = JSON.parse(fs.readFileSync(path.join(contentDir, 'tiers.json'), 'utf8'));
  const label = (key) => tiers.find((tier) => tier.key === key).label;

  assert.deepEqual(suffix.match(/[0-9٠-٩]+/g) ?? [], []);
  assert.ok(suffix.includes(`«${label('expert')}»`));
  assert.ok(suffix.startsWith(`حدود «${label('fast')}»\n`));
});

test('the daily sentence matches CAP_DAILY\'s «لهذا اليوم في هذا الحساب»', () => {
  // Fails if the at-limit bullet still tells the model to infer the daily cap from timing, or its words drift from the
  // refusal text the tool sends at the daily cap.
  const atLimit = lineStarting(arabic, '- إذا أعادت الأداة أنه تم بلوغ الحد المسموح');

  assert.ok(CAP_DAILY.includes(DAILY_WORDS));
  assert.ok(atLimit.includes(`وإذا ذكرت الرسالة أن الحد بلغ ${DAILY_WORDS}، فلا يفيد تقسيم السؤال`));
  assert.ok(!edition.includes('الرسالة نفسها') && !edition.includes('The same message marks'));
  assert.ok(budgetBullets()[2].includes('the limit has been reached for today for this account'));
});
