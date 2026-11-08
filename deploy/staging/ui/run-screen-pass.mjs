// Runs ui/screen-pass.cjs in the Playwright image, inside the proxy container's network namespace, as
// run-rtl-check.mjs runs rtl-check.cjs (the browser opens the proxy as http://localhost:8080, a secure origin).
//   node ui/run-screen-pass.mjs                                      (from deploy/staging, Git Bash: MSYS_NO_PATHCONV=1)
//   IQRAA_PASS_DIR=<folder>    where the pass writes (default out/screen-pass, git-ignored run output)
//   IQRAA_PASS_ONLY=desktop-light[,phone-dark][:landing,composer]    some runs and sections only (sign-in always)
// Makes one staff account with the bootstrap runner and one phone-only plan customer with credits (lib.mjs, codes
// from the sink), and sets up the customer's authenticator app through LibreChat's own routes; the browser signs in
// with app codes it computes in the container (totp.cjs). The app secret reaches the container through the
// environment, never a command line or a file. Makes one staff (ADMIN) account and one plan customer with a 30-credit
// grant per pass (recorded in <folder>/accounts.json: labels, phones, ids, no secret); beyond those, it changes only
// that customer's own data.
// Before the pass it removes the screenshots of the runs it is about to make from <folder>/shots, nothing else, and
// the pass rewrites census.json, screens.json, known-items.json and arabic-texts.json from the runs it makes (a partial
// run therefore leaves only its own; give it its own folder); findings.json and known-items.json keep the entries
// marked "source": "review". The exit status is the pass's: 1 when any step was not reached.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { COMPOSE, customer, enableApp, staffAccount } from '../lib.mjs';

const STAGING = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PASS = path.resolve(process.env.IQRAA_PASS_DIR ?? path.join(STAGING, 'out', 'screen-pass'));
const SHOTS = path.join(PASS, 'shots');
const ONLY = process.env.IQRAA_PASS_ONLY ?? '';
const RUNS = ONLY ? ONLY.split(':')[0].split(',') : ['desktop-light', 'desktop-dark', 'phone-light', 'phone-dark'];

const proxyId = execFileSync('docker', ['compose', '-f', COMPOSE, 'ps', '-q', 'proxy'], { encoding: 'utf8' }).trim();
if (!proxyId) throw new Error('the staging proxy is not running');

fs.mkdirSync(SHOTS, { recursive: true });
for (const file of fs.readdirSync(SHOTS)) {
  if (file.endsWith('.png') && RUNS.some((run) => file.startsWith(`${run}-`))) fs.rmSync(path.join(SHOTS, file));
}

const staff = await staffAccount('pass-staff');
const client = await enableApp(await customer(staff, 'pass', { credits: 30 }));
// The accounts this pass left on staging, so they can be found again; no secret, app code or backup code.
fs.writeFileSync(
  path.join(PASS, 'accounts.json'),
  JSON.stringify(
    {
      at: new Date().toISOString(),
      staff: { label: staff.label, name: staff.name, phone: staff.phone, id: staff.id, role: staff.role },
      customer: { label: client.label, name: client.name, phone: client.phone, id: client.id, credits: 30 },
    },
    null,
    1,
  ),
);
// The authenticator entry's name (O-38), without the secret: otpauth://totp/<label>?secret=…&issuer=…
const otpauth = new URL(client.app.otpauthUrl);
const authenticatorLabel = `${decodeURIComponent(otpauth.pathname.replace(/^\/+/, ''))} (issuer ${otpauth.searchParams.get('issuer') ?? 'none'})`;

const env = {
  ...process.env,
  CUSTOMER_PHONE: client.phone,
  CUSTOMER_APP_SECRET: client.app.secret,
  CUSTOMER_APP_LAST_STEP: String(client.app.lastStep),
  AUTHENTICATOR_LABEL: authenticatorLabel,
  IQRAA_PASS_ONLY: ONLY,
  MSYS_NO_PATHCONV: '1',
};
const passed = ['CUSTOMER_PHONE', 'CUSTOMER_APP_SECRET', 'CUSTOMER_APP_LAST_STEP', 'AUTHENTICATOR_LABEL', 'IQRAA_PASS_ONLY'];
const args = [
  'run', '--rm', '--network', `container:${proxyId}`, '-v', `${STAGING}:/work`, '-v', `${PASS}:/pass`, '-v', 'iqraa-playwright-npm:/root/.npm', '-w', '/tmp',
  ...passed.flatMap((name) => ['-e', name]),
  'mcr.microsoft.com/playwright:v1.64.0-noble@sha256:06a9939e57531807f8d5fd76ce44b53165ffb7d7501d87ab10e285c20b1e971f',
  'sh', '-c', 'npm init -y >/dev/null && npm i --no-audit --no-fund playwright@1.64.0 >/dev/null && NODE_PATH=/tmp/node_modules node /work/ui/screen-pass.cjs',
];
console.log(`screen pass: customer ${client.phone.slice(0, 6)}…, runs ${RUNS.join(', ')}, output ${PASS}`);
const run = spawnSync('docker', args, { env, stdio: 'inherit' });
if (run.error) console.error(`could not start docker: ${run.error.message}`);
process.exit(run.status ?? 1);
