// Release drills on staging: rollback (scenario 14) and a removed skill (scenario 5).
//
//   node drills.mjs        (needs iqraa/release:drill-r1, drill-r2, drill-r3 — see README "Release drills";
//                           run node scenarios.mjs once first: it creates the PLAN_PRO role and «عقل»)
//
// Swaps LibreChat between release images, restores iqraa/release:staging at the end, and writes
// out/drills-report.json. Exits 1 on any failure.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import {
  BASE, COMPOSE, OUT, RUN, MODEL, PLAN_ROLE, api, chat, customer, login, mongoQuery, newAccount,
  registerAndLogin, sleep, nonce, llmLog, check, verdict,
} from './lib.mjs';

const RELEASES = { r1: 'iqraa/release:drill-r1', r2: 'iqraa/release:drill-r2', r3: 'iqraa/release:drill-r3', staging: 'iqraa/release:staging' };

async function useRelease(image) {
  execFileSync('docker', ['compose', '-f', COMPOSE, 'up', '-d', '--no-deps', 'librechat'], { env: { ...process.env, IQRAA_IMAGE: image }, stdio: 'ignore' });
  // nginx resolves `librechat` once at start; a recreated container may get a new address.
  execFileSync('docker', ['compose', '-f', COMPOSE, 'restart', 'proxy'], { stdio: 'ignore' });
  const wanted = execFileSync('docker', ['image', 'inspect', image, '--format', '{{.Id}}'], { encoding: 'utf8' }).trim();
  const deadline = Date.now() + 300_000;
  while (Date.now() < deadline) {
    const id = execFileSync('docker', ['compose', '-f', COMPOSE, 'ps', '-q', 'librechat'], { encoding: 'utf8' }).trim();
    const running = id ? execFileSync('docker', ['inspect', id, '--format', '{{.Image}}'], { encoding: 'utf8' }).trim() : '';
    let healthy = false;
    try {
      healthy = (await fetch(`${BASE}/readyz`)).ok; // ready, not just listening
    } catch {
      healthy = false;
    }
    if (running === wanted && healthy) return;
    await sleep(3000);
  }
  throw new Error(`LibreChat did not come up on ${image}`);
}

const callsTagged = (tag) => llmLog().filter((e) => e.decision && !e.title && !e.summary && JSON.stringify(e.messages ?? []).includes(tag));
const seen = (calls, marker) => calls.some((c) => JSON.stringify(c.messages ?? []).includes(marker));

const probes = [];

async function probe(account, agentId, label, text, extra = {}) {
  const tag = nonce(label);
  const startedAt = new Date().toISOString();
  const result = await chat({ token: account.token, agentId, text: `${text} ${tag}`, ...extra });
  await sleep(1500);
  const calls = callsTagged(tag);
  const entry = { label, tag, startedAt, startStatus: result.startStatus, calls: calls.length, reply: result.text?.slice(0, 200) ?? null, error: result.error ? JSON.stringify(result.error).slice(0, 300) : null };
  if (calls.length === 0) {
    // Keep LibreChat's log now: the next release swap replaces the container and its logs.
    entry.logFile = `drills-${tag}.log`;
    fs.writeFileSync(path.join(OUT, entry.logFile), execFileSync('docker', ['compose', '-f', COMPOSE, 'logs', '--since', '5m', 'librechat'], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }));
  }
  probes.push(entry);
  return { tag, result, calls };
}

/** The three routes to a listed skill: the model's skill tool, manual invocation, read_file. */
async function probeListed(account, agentId, label) {
  return {
    byTool: await probe(account, agentId, `${label}-tool`, 'CALL_TOOL:skill:{"skillName":"drill-listed"}'),
    byManual: await probe(account, agentId, `${label}-manual`, 'manual drill-listed', { manualSkills: ['drill-listed'] }),
    byFile: await probe(account, agentId, `${label}-file`, 'CALL_TOOL:read_file:{"path":"skills/drill-listed/SKILL.md"}'),
  };
}

async function patchAgent(staff, agentId, body) {
  const res = await api(`/api/agents/${agentId}`, { token: staff.token, method: 'PATCH', body });
  if (res.status >= 300) throw new Error(`PATCH agent: ${res.status} ${res.text.slice(0, 200)}`);
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const report = { run: RUN, startedAt: new Date().toISOString(), steps: {} };
  try {
    await useRelease(RELEASES.r1);
    const staffAccount = newAccount('drillstaff');
    await registerAndLogin(staffAccount);
    mongoQuery({ op: 'promote', email: staffAccount.email });
    let staff = await login(staffAccount);
    const skills = await api('/api/skills', { token: staff.token });
    const list = Array.isArray(skills.json) ? skills.json : (skills.json?.skills ?? skills.json?.data ?? []);
    const ids = Object.fromEntries(list.map((s) => [s.name, String(s._id ?? s.id)]));
    for (const name of ['drill-pinned', 'drill-listed']) {
      if (!ids[name]) throw new Error(`drill skill ${name} is not in release r1 (have: ${Object.keys(ids).join(', ')})`);
    }
    const created = await api('/api/agents', {
      token: staff.token,
      method: 'POST',
      body: {
        name: `Drill specialist ${RUN}`,
        instructions: 'DRILL_INSTRUCTIONS_V1 — rollback drill specialist.',
        provider: 'MockLLM',
        model: MODEL,
        model_parameters: { streamUsage: true },
        skills: [ids['drill-pinned'], ids['drill-listed']],
        skills_enabled: true,
        skill_authoring_enabled: false,
      },
    });
    const agentId = created.json?.id;
    if (!agentId) throw new Error(`drill specialist not created: ${created.status} ${created.text.slice(0, 200)}`);
    const share = await api(`/api/permissions/agent/${created.json._id}`, {
      token: staff.token,
      method: 'PUT',
      body: { updated: [{ type: 'role', id: PLAN_ROLE, accessRoleId: 'agent_viewer' }], removed: [], public: false },
    });
    if (share.status >= 300) throw new Error(`sharing the drill specialist: ${share.status}`);
    const customerAccount = await customer(staff, 'drill', { credits: 5 });
    // Sessions last 15 minutes and each release swap takes minutes: log in again after every swap.
    const relogin = async () => {
      staff = await login(staffAccount);
      return login(customerAccount);
    };

    // Release r2 and specialist v2; positive controls for the scenario 5 probes.
    await useRelease(RELEASES.r2);
    let c = await relogin();
    await patchAgent(staff, agentId, { instructions: 'DRILL_INSTRUCTIONS_V2 — rollback drill specialist.' });
    const onR2 = await probe(c, agentId, 'drill-r2', 'r2 probe');
    const listedOnR2 = await probeListed(c, agentId, 'drill-r2-listed');
    report.steps.r2 = verdict({
      runsV2Skill: check(seen(onR2.calls, 'DRILL_SKILL_V2'), 'r2 pinned skill reached the model'),
      runsV2Instructions: check(seen(onR2.calls, 'DRILL_INSTRUCTIONS_V2'), 'v2 instructions reached the model'),
      listedReachableByTool: check(seen(listedOnR2.byTool.calls, 'DRILL_LISTED_MARKER'), 'control: the skill tool loads drill-listed on r2'),
      listedReachableByManual: check(seen(listedOnR2.byManual.calls, 'DRILL_LISTED_MARKER'), 'control: manual invocation loads drill-listed on r2'),
      listedReachableByFile: check(seen(listedOnR2.byFile.calls, 'DRILL_LISTED_MARKER'), 'control: read_file reads drill-listed on r2'),
    });

    // Scenario 14: roll back the image to r1 and revert the specialist to its v1 version.
    await useRelease(RELEASES.r1);
    c = await relogin();
    const versions = (await api(`/api/agents/${agentId}/versions`, { token: staff.token })).json;
    const versionList = Array.isArray(versions) ? versions : (versions?.versions ?? []);
    const v1Index = versionList.findIndex((v) => String(v.instructions ?? '').includes('DRILL_INSTRUCTIONS_V1'));
    const revert = await api(`/api/agents/${agentId}/revert`, { token: staff.token, method: 'POST', body: { version_index: v1Index } });
    const onR1 = await probe(c, agentId, 'drill-rollback', 'rollback probe');
    report.steps.scenario14 = verdict({
      revertAccepted: check(v1Index >= 0 && revert.status === 200, `v1 version index ${v1Index}; revert ${revert.status}`),
      runsV1Skill: check(seen(onR1.calls, 'DRILL_SKILL_V1') && !seen(onR1.calls, 'DRILL_SKILL_V2'), 'only the r1 pinned skill reached the model'),
      runsV1Instructions: check(seen(onR1.calls, 'DRILL_INSTRUCTIONS_V1') && !seen(onR1.calls, 'DRILL_INSTRUCTIONS_V2'), 'only the v1 instructions reached the model'),
    });
    report.steps.scenario14.probe = { startStatus: onR1.result.startStatus, calls: onR1.calls.length, reply: onR1.result.text?.slice(0, 300) ?? null };

    // Scenario 5: release r3 drops drill-listed; the specialist stops listing it.
    await useRelease(RELEASES.r3);
    c = await relogin();
    await patchAgent(staff, agentId, { skills: [ids['drill-pinned']] });
    const listedOnR3 = await probeListed(c, agentId, 'drill-s5');
    const all = [...listedOnR3.byTool.calls, ...listedOnR3.byManual.calls, ...listedOnR3.byFile.calls];
    report.steps.scenario5 = verdict({
      probesRan: check(listedOnR3.byTool.calls.length >= 1 && listedOnR3.byManual.calls.length >= 1 && listedOnR3.byFile.calls.length >= 1, `calls ${listedOnR3.byTool.calls.length}/${listedOnR3.byManual.calls.length}/${listedOnR3.byFile.calls.length}`),
      removedSkillNeverReachedModel: check(!seen(all, 'DRILL_LISTED_MARKER'), 'the removed skill marker reached no model call'),
    });
  } catch (error) {
    report.error = String(error.stack ?? error);
  } finally {
    await useRelease(RELEASES.staging).catch((error) => {
      report.restoreError = String(error);
    });
  }
  report.probes = probes;
  report.finishedAt = new Date().toISOString();
  report.pass = !report.error && !report.restoreError && Object.values(report.steps).length === 3 && Object.values(report.steps).every((s) => s.pass);
  fs.writeFileSync(path.join(OUT, 'drills-report.json'), JSON.stringify(report, null, 2));
  for (const [name, step] of Object.entries(report.steps)) {
    console.log(`${name.padEnd(11)} ${step.pass ? 'PASS' : 'FAIL'}`);
    for (const [k, c] of Object.entries(step.checks)) console.log(`   ${c.ok ? 'ok  ' : 'FAIL'} ${k}: ${c.detail}`);
  }
  if (report.error) console.log(`error: ${report.error}`);
  if (report.restoreError) console.log(`restore error: ${report.restoreError}`);
  console.log(report.pass ? 'DRILLS PASS' : 'DRILLS FAIL — see out/drills-report.json');
  process.exit(report.pass ? 0 : 1);
}

await main();
