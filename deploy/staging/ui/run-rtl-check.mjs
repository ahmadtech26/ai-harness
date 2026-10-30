// Runs ui/rtl-check.cjs in the Playwright image, inside the proxy container's network namespace
// (the browser opens the proxy as http://localhost:8080, a secure origin; see rtl-check.cjs).
//   node ui/run-rtl-check.mjs [--inject out/rtl.candidate.css]      (from deploy/staging)
// Makes a staff account with the bootstrap runner and a phone-only plan customer with credits (lib.mjs, codes
// from the sink), and sets up the customer's authenticator app through LibreChat's own routes. The browser signs
// the customer in on the fork's code screens with an app code (computed in the container by totp.cjs) and once
// more with a backup code. The app secret and the backup code reach the container through the environment,
// never a command line or a file. Finds the «عقل» specialist and exits with the check's status.
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { COMPOSE, api, customer, enableApp, staffAccount } from '../lib.mjs';

const STAGING = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const injectAt = process.argv.indexOf('--inject');
const inject = injectAt > 0 ? process.argv[injectAt + 1] : null;

const staff = await staffAccount('rtl-staff');
const agents = await api('/api/agents?requiredPermission=1', { token: staff.token });
const agent = (agents.json?.data ?? []).find((a) => String(a.name).startsWith('عقل'));
if (!agent) throw new Error('the «عقل» specialist is not on this stack — run node scenarios.mjs once first');
const client = await enableApp(await customer(staff, 'rtl', { credits: 5 }));

const proxyId = execFileSync('docker', ['compose', '-f', COMPOSE, 'ps', '-q', 'proxy'], { encoding: 'utf8' }).trim();
if (!proxyId) throw new Error('the staging proxy is not running');

const env = {
  ...process.env,
  CUSTOMER_PHONE: client.phone,
  CUSTOMER_APP_SECRET: client.app.secret,
  CUSTOMER_APP_LAST_STEP: String(client.app.lastStep),
  CUSTOMER_BACKUP_CODE: client.app.backupCodes[0],
  AGENT_ID: agent.id,
  MSYS_NO_PATHCONV: '1',
};
const passed = ['CUSTOMER_PHONE', 'CUSTOMER_APP_SECRET', 'CUSTOMER_APP_LAST_STEP', 'CUSTOMER_BACKUP_CODE', 'AGENT_ID'];
const args = [
  'run', '--rm', '--network', `container:${proxyId}`, '-v', `${STAGING}:/work`, '-v', 'iqraa-playwright-npm:/root/.npm', '-w', '/tmp',
  ...passed.flatMap((name) => ['-e', name]),
  ...(inject ? ['-e', `INJECT_CSS=/work/${inject.replace(/\\/g, '/')}`] : []),
  'mcr.microsoft.com/playwright:v1.64.0-noble',
  'sh', '-c', 'npm init -y >/dev/null && npm i --no-audit --no-fund playwright@1.64.0 && NODE_PATH=/tmp/node_modules node /work/ui/rtl-check.cjs',
];
const run = spawnSync('docker', args, { env, stdio: 'inherit' });
if (run.error) console.error(`could not start docker: ${run.error.message}`);
process.exit(run.status ?? 1);
