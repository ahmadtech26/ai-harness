// Plans one private agent per customer tier, and lints it: the closed corpus starts here (REQ-CORPUS-001/003).
//
// Pure planning, no network: `release.mjs` sends what this returns. Every tier agent is the AQEL specialist
// (`specialists/aqel.json`: instructions, the three library tools, the pinned and listed skills) with the tier's
// name, description, internal model and the four featured starters. The lint refuses an agent that carries any
// other tool, an unknown model parameter, or instructions without the corpus rule, so a tier can never be
// released with a web search, code execution or another MCP server.
//
// Usage reporting is not the agent's: LibreChat (since v0.8.9-rc1) refuses `streamUsage` on an agent and drops a
// stored one at run time, and a custom endpoint streams no usage unless the run's parameters ask for it. The tier
// endpoint asks instead (`addParams: { streamUsage: true }` in librechat.yaml), which `tiers.mjs` checks; without
// it every tier turn is charged its full hold.
import fs from 'node:fs';
import path from 'node:path';
import { composeSpecialist } from './compose.mjs';
import { featuredTexts } from './starters.mjs';

/** The three legal-search tools as LibreChat names an MCP tool: `<tool>_mcp_<server>`. */
export const LIBRARY_TOOLS = ['search_law_mcp_legal-search', 'get_article_mcp_legal-search', 'get_memorandum_mcp_legal-search'];
/**
 * Model parameters a tier agent may set; anything else (a provider-side search switch, the responses API) is refused.
 * LibreChat checks every agent write against its own list for the endpoint (`packages/api/src/agents/inference.ts`,
 * the openai profile a custom endpoint gets) and refuses the release on any other key: re-check these on an upgrade.
 */
export const ALLOWED_PARAMETERS = ['max_tokens', 'temperature', 'top_p'];
/** Why a tier agent may not carry `streamUsage`: LibreChat refuses it on an agent, so the endpoint asks for usage. */
export const USAGE_ON_AGENT =
  'model parameter streamUsage is not allowed: LibreChat refuses it on an agent, so the tier endpoint sets addParams.streamUsage: true';
/** Each tier agent's `category` marks it as that tier's (the key survives a rename of the label). */
export const TIER_CATEGORY_PREFIX = 'iqraa-tier-';
/** Agents of earlier releases that customers must no longer reach: the old single agent of the first release. */
const LEGACY_NAMES = ['عقل — المستشار القانوني'];

/** The listed agent that is this tier's: by category, else (an agent of an earlier release) by exact name. */
export function findTierAgent(existingAgents, body) {
  return existingAgents.find((agent) => agent.category === body.category) ?? existingAgents.find((agent) => agent.name === body.name);
}

/** Agents to take away from every plan role: a removed tier's agent and the legacy agents, never a current one. */
export function retiredAgents(existingAgents, keptIds) {
  return existingAgents.filter(
    (agent) =>
      !keptIds.has(agent.id) &&
      ((agent.category ?? '').startsWith(TIER_CATEGORY_PREFIX) || LEGACY_NAMES.includes(agent.name)),
  );
}

/** A phrase of the AQEL instructions (`prompts/aqel-v1.2-librechat.md`) the release requires. */
export const CORPUS_MARKER = 'AQEL LEGAL ENGINE';

/** Problems with a planned tier agent body, as readable lines; empty when it is closed to the library only. */
export function lintAgentBody(body) {
  const errors = [];
  const tools = body.tools ?? [];
  for (const tool of tools.filter((name) => !LIBRARY_TOOLS.includes(name))) errors.push(`tool ${tool} is not a library tool`);
  for (const tool of LIBRARY_TOOLS.filter((name) => !tools.includes(name))) errors.push(`library tool ${tool} is missing`);
  for (const key of Object.keys(body.model_parameters ?? {})) {
    if (key === 'streamUsage') errors.push(USAGE_ON_AGENT);
    else if (!ALLOWED_PARAMETERS.includes(key)) errors.push(`model parameter ${key} is not allowed`);
  }
  if (!String(body.instructions ?? '').includes(CORPUS_MARKER)) errors.push(`instructions lack the AQEL text (${CORPUS_MARKER})`);
  if (body.skill_authoring_enabled !== false) errors.push('skill_authoring_enabled must be false');
  if (!Array.isArray(body.conversation_starters) || body.conversation_starters.length !== 4) errors.push('conversation_starters must be the four featured prompts');
  return errors;
}

/**
 * @param {{ tiersDoc: object, contentDir: string, startersDoc: object, env?: Record<string, string | undefined> }} input
 * @returns {{ tier: object, plans: string[], body: object }[]}  each body lists skills by name (release maps them to ids)
 */
export function planTierAgents({ tiersDoc, contentDir, startersDoc, env = process.env }) {
  const specFile = path.join(contentDir, tiersDoc.specialist);
  const spec = JSON.parse(fs.readFileSync(specFile, 'utf8'));
  if (!Array.isArray(spec.skills) || spec.skills.length === 0) {
    throw new Error(`${specFile}: list the skills explicitly (an empty list gives the specialist every skill)`);
  }
  const composed = composeSpecialist({
    spec,
    instructions: fs.readFileSync(path.resolve(path.dirname(specFile), spec.instructionsFile), 'utf8'),
    skills: Object.fromEntries(
      spec.skills.map((name) => {
        const skillFile = path.join(contentDir, 'skills', name, 'SKILL.md');
        return [name, fs.existsSync(skillFile) ? fs.readFileSync(skillFile, 'utf8') : undefined];
      }),
    ),
  });
  const starters = featuredTexts(startersDoc);
  return [...tiersDoc.tiers]
    .sort((a, b) => a.order - b.order)
    .map((tier) => {
      const body = {
        name: tier.label,
        description: tier.description,
        instructions: composed.instructions,
        provider: env.IQRAA_PROVIDER ?? tier.provider,
        model: env.IQRAA_MODEL ?? tier.model,
        model_parameters: spec.model_parameters,
        tools: spec.tools,
        skills: composed.skills,
        skills_enabled: composed.skills_enabled,
        skill_authoring_enabled: spec.skill_authoring_enabled,
        recursion_limit: spec.recursion_limit,
        category: `${TIER_CATEGORY_PREFIX}${tier.key}`,
        conversation_starters: starters,
      };
      const problems = lintAgentBody(body);
      if (problems.length > 0) throw new Error(`tier ${tier.key}: ${problems.join('; ')}`);
      return { tier, plans: tier.plans, body, pinned: composed.pinned };
    });
}
