// Runs ui/rtl-check.cjs in the Playwright image, inside the proxy container's network namespace
// (the browser opens the proxy as http://localhost:8080, a secure origin; see rtl-check.cjs).
//   node ui/run-rtl-check.mjs [--inject out/rtl.candidate.css]      (from deploy/staging)
// Creates a fresh staff account (password generated here, held in memory, handed to the container
// through the environment — never on a command line or in a file), finds the «عقل» specialist, and
// exits with the check's status.
import crypto from 'node:crypto';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const STAGING = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const COMPOSE = path.join(STAGING, 'compose.yaml');
const BASE = 'http://127.0.0.1:3080';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';
const injectAt = process.argv.indexOf('--inject');
const inject = injectAt > 0 ? process.argv[injectAt + 1] : null;

async function api(route, { token, method = 'GET', body } = {}) {
  const res = await fetch(BASE + route, {
    method,
    headers: { 'User-Agent': UA, ...(body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, json: await res.json().catch(() => null) };
}

const suffix = crypto.randomBytes(4).toString('hex');
const staff = { name: 'RTL staff', username: `rtl_staff_${suffix}`, email: `rtl.staff.${suffix}@example.test`, password: crypto.randomBytes(12).toString('base64url') + 'aA1!' };
const registered = await api('/api/auth/register', { method: 'POST', body: { ...staff, confirm_password: staff.password } });
if (registered.status >= 300) throw new Error(`staff register: HTTP ${registered.status}`);
const query = Buffer.from(JSON.stringify({ op: 'promote', email: staff.email })).toString('base64');
execFileSync('docker', ['compose', '-f', COMPOSE, 'exec', '-T', '-e', `IQRAA_QUERY=${query}`, 'mongo', 'mongosh', 'LibreChat', '--quiet', '--file', '/scripts/query.js'], { encoding: 'utf8' });
const login = await api('/api/auth/login', { method: 'POST', body: { email: staff.email, password: staff.password } });
if (login.json?.user?.role !== 'ADMIN') throw new Error(`staff account is not ADMIN (HTTP ${login.status})`);
const agents = await api('/api/agents?requiredPermission=1', { token: login.json.token });
const agent = (agents.json?.data ?? []).find((a) => String(a.name).startsWith('عقل'));
if (!agent) throw new Error('the «عقل» specialist is not on this stack — run node scenarios.mjs once first');

const proxyId = execFileSync('docker', ['compose', '-f', COMPOSE, 'ps', '-q', 'proxy'], { encoding: 'utf8' }).trim();
if (!proxyId) throw new Error('the staging proxy is not running');

const env = { ...process.env, STAFF_EMAIL: staff.email, STAFF_PASSWORD: staff.password, AGENT_ID: agent.id, MSYS_NO_PATHCONV: '1' };
const args = [
  'run', '--rm', '--network', `container:${proxyId}`, '-v', `${STAGING}:/work`, '-v', 'iqraa-playwright-npm:/root/.npm', '-w', '/tmp',
  '-e', 'STAFF_EMAIL', '-e', 'STAFF_PASSWORD', '-e', 'AGENT_ID',
  ...(inject ? ['-e', `INJECT_CSS=/work/${inject.replace(/\\/g, '/')}`] : []),
  'mcr.microsoft.com/playwright:v1.64.0-noble',
  'sh', '-c', 'npm init -y >/dev/null && npm i --no-audit --no-fund playwright@1.64.0 && NODE_PATH=/tmp/node_modules node /work/ui/rtl-check.cjs',
];
const run = spawnSync('docker', args, { env, stdio: 'inherit' });
if (run.error) console.error(`could not start docker: ${run.error.message}`);
process.exit(run.status ?? 1);
