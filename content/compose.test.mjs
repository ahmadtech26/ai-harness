// Tests for compose.mjs:  node --test content/compose.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { composeSpecialist } from './compose.mjs';

const skill = (name, { alwaysApply = false, body = `# ${name}\n\nbody of ${name}\n` } = {}) =>
  `---\nname: ${name}\ndescription: A skill used in compose tests, long enough.\n${alwaysApply ? 'always-apply: true\n' : ''}metadata:\n  version: "1.0.0"\n---\n\n${body}`;

const SPEC = { skills: ['method', 'review', 'fees'], skills_enabled: true };
const SKILLS = {
  method: skill('method', { alwaysApply: true, body: '# Method\n\nPINNED_METHOD_TEXT\n' }),
  review: skill('review'),
  fees: skill('fees'),
};

test('appends pinned skill bodies to the instructions and leaves them off the skill list', () => {
  const result = composeSpecialist({ spec: SPEC, instructions: 'AQEL INSTRUCTIONS\n', skills: SKILLS });

  assert.equal(result.instructions, 'AQEL INSTRUCTIONS\n\n# Method\n\nPINNED_METHOD_TEXT\n');
  assert.deepEqual(result.pinned, ['method']);
  assert.ok(!result.skills.includes('method'));
});

test('keeps on-demand skills listed in their order', () => {
  const result = composeSpecialist({ spec: SPEC, instructions: 'I', skills: SKILLS });

  assert.deepEqual(result.skills, ['review', 'fees']);
  assert.equal(result.skills_enabled, true);
});

test('turns skills off when every listed skill is pinned', () => {
  const result = composeSpecialist({ spec: { skills: ['method'], skills_enabled: true }, instructions: 'I', skills: SKILLS });

  assert.deepEqual(result.skills, []);
  assert.equal(result.skills_enabled, false);
});

test('rejects a listed skill that has no SKILL.md', () => {
  assert.throws(
    () => composeSpecialist({ spec: { skills: ['missing'], skills_enabled: true }, instructions: 'I', skills: SKILLS }),
    /skill missing has no SKILL\.md/,
  );
});
