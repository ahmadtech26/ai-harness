// Runs ui/rtl-check.cjs in the Playwright image, inside the proxy container's network namespace
// (the browser opens the proxy as http://localhost:8080, a secure origin; see rtl-check.cjs).
//   node ui/run-rtl-check.mjs [--inject out/rtl.candidate.css]      (from deploy/staging)
//   node ui/run-rtl-check.mjs --census                              the API census of the customer chat screen
// Makes a staff account with the bootstrap runner and a phone-only plan customer with credits (lib.mjs, codes
// from the sink), and sets up the customer's authenticator app through LibreChat's own routes. The browser signs
// the customer in on the fork's code screens with an app code (computed in the container by totp.cjs) and once
// more with a backup code. The app secret and the backup code reach the container through the environment,
// never a command line or a file. The browser opens the new-chat screen on its default tier; the check exits with its status.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { COMPOSE, customer, enableApp, staffAccount } from '../lib.mjs';

const STAGING = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// Screenshots of the census (the gallery in RTL, desktop and mobile) go to out/shots in the stack folder by default
// (out/ is git-ignored run output); IQRAA_SHOTS_DIR puts them anywhere else.
const SHOTS = process.env.IQRAA_SHOTS_DIR ?? path.join(STAGING, 'out', 'shots');
fs.mkdirSync(SHOTS, { recursive: true });
const injectAt = process.argv.indexOf('--inject');
const inject = injectAt > 0 ? process.argv[injectAt + 1] : null;
const script = process.argv.includes('--census') ? 'census-check.cjs' : 'rtl-check.cjs';

const staff = await staffAccount('rtl-staff');
const client = await enableApp(await customer(staff, 'rtl', { credits: 5 }));

const proxyId = execFileSync('docker', ['compose', '-f', COMPOSE, 'ps', '-q', 'proxy'], { encoding: 'utf8' }).trim();
if (!proxyId) throw new Error('the staging proxy is not running');

const env = {
  ...process.env,
  CUSTOMER_PHONE: client.phone,
  CUSTOMER_APP_SECRET: client.app.secret,
  CUSTOMER_APP_LAST_STEP: String(client.app.lastStep),
  CUSTOMER_BACKUP_CODE: client.app.backupCodes[0],
  MSYS_NO_PATHCONV: '1',
};
const passed = ['CUSTOMER_PHONE', 'CUSTOMER_APP_SECRET', 'CUSTOMER_APP_LAST_STEP', 'CUSTOMER_BACKUP_CODE'];
const args = [
  'run', '--rm', '--network', `container:${proxyId}`, '-v', `${STAGING}:/work`, '-v', `${SHOTS}:/shots`, '-v', 'iqraa-playwright-npm:/root/.npm', '-w', '/tmp',
  ...passed.flatMap((name) => ['-e', name]),
  ...(inject ? ['-e', `INJECT_CSS=/work/${inject.replace(/\\/g, '/')}`] : []),
  'mcr.microsoft.com/playwright:v1.64.0-noble@sha256:06a9939e57531807f8d5fd76ce44b53165ffb7d7501d87ab10e285c20b1e971f',
  'sh', '-c', 'npm init -y >/dev/null && npm i --no-audit --no-fund playwright@1.64.0 && NODE_PATH=/tmp/node_modules node /work/ui/' + script,
];
const run = spawnSync('docker', args, { env, stdio: 'inherit' });
if (run.error) console.error(`could not start docker: ${run.error.message}`);
process.exit(run.status ?? 1);
