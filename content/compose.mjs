// Composes a specialist for release: pinned (always-apply) skills become part of its instructions;
// on-demand skills stay listed.
//
// Why: LibreChat primes an always-apply skill as a separate meta message, and its summariser does not
// carry such messages past a mid-run summary — the method silently drops out of the rest of the turn
// (scenario 3, P2-results). Instructions survive every summary, cache as part of the stable prompt
// prefix, and show the customer no skill pill. Decision: option A, 2026-10-25.

/** Splits a SKILL.md into its frontmatter flags and its body (text after the closing `---`). */
export function parseSkill(text) {
  const normalised = text.replace(/\r\n/g, '\n');
  const end = normalised.indexOf('\n---\n', 3);
  if (!normalised.startsWith('---\n') || end === -1) {
    throw new Error('SKILL.md has no closed frontmatter block');
  }
  const frontmatter = normalised.slice(4, end);
  return {
    alwaysApply: /^always-apply:\s*true\s*$/m.test(frontmatter),
    body: normalised.slice(end + 5).trim(),
  };
}

/**
 * @param {{ spec: { skills: string[], skills_enabled?: boolean }, instructions: string, skills: Record<string, string> }} input
 *   `skills` maps each listed skill name to its SKILL.md text.
 * @returns {{ instructions: string, skills: string[], skills_enabled: boolean, pinned: string[] }}
 */
export function composeSpecialist({ spec, instructions, skills }) {
  const pinned = [];
  const listed = [];
  const bodies = [];
  for (const name of spec.skills) {
    if (skills[name] == null) {
      throw new Error(`skill ${name} has no SKILL.md`);
    }
    const parsed = parseSkill(skills[name]);
    if (parsed.alwaysApply) {
      pinned.push(name);
      bodies.push(parsed.body);
    } else {
      listed.push(name);
    }
  }
  const composed = bodies.length ? `${instructions.trimEnd()}\n\n${bodies.join('\n\n')}\n` : instructions;
  return {
    instructions: composed,
    skills: listed,
    // An empty list with skills enabled would give the specialist every skill, so turn skills off.
    skills_enabled: listed.length > 0 ? spec.skills_enabled !== false : false,
    pinned,
  };
}
