// The staging proxy config in a real nginx, in front of a server that answers with the Host it was sent (O-156).
// LibreChat's same-origin guard compares Origin with that Host, so a port the proxy drops refuses sign-in on a
// non-default port. Needs docker, so only the gates runner's docker step runs it, not the plain node glob:
//   node --test deploy/staging/docker-tests/host-header.test.mjs
// It creates only the hardening-o156 network and containers, removes them at the end, and never publishes 3080.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import http from 'node:http';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const NETWORK = 'hardening-o156';
const ECHO = `${NETWORK}-echo`;
const PROXY = `${NETWORK}-proxy`;
const NODE_IMAGE = 'node:24-alpine@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53';
const NGINX_IMAGE = 'nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10';
const CONF = fileURLToPath(new URL('../proxy/default.conf', import.meta.url));
const ECHO_SERVER = "require('http').createServer((req, res) => res.end(req.headers.host ?? '')).listen(3080)";

const docker = (...args) => spawnSync('docker', args, { encoding: 'utf8', env: { ...process.env, MSYS_NO_PATHCONV: '1' } });

function must(...args) {
  const run = docker(...args);
  if (run.error) throw run.error;
  assert.equal(run.status, 0, `docker ${args.join(' ')} failed: ${run.stderr}`);
  return run.stdout.trim();
}

// A setup that failed part way leaves only some of the three, so a missing one is not an error here.
function removeAll() {
  docker('rm', '-f', ECHO, PROXY);
  docker('network', 'rm', NETWORK);
}

const get = (port) =>
  new Promise((resolve, reject) => {
    const req = http.get({ host: '127.0.0.1', port, path: '/', agent: false }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => (body += chunk));
      res.on('end', () => resolve({ status: res.statusCode, body }));
    });
    req.on('error', reject);
    req.setTimeout(5000, () => req.destroy(new Error('no answer in 5 s')));
  });

// Any 2xx means nginx and the echo server both answer; refused, reset or 502 means one is still starting.
async function waitForProxy(port) {
  const deadline = Date.now() + 60_000;
  let last = 'no attempt';
  while (Date.now() < deadline) {
    try {
      const answer = await get(port);
      if (answer.status >= 200 && answer.status < 300) return answer;
      last = `status ${answer.status}`;
    } catch (error) {
      last = error.message;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  const logs = docker('logs', PROXY);
  assert.fail(`the proxy did not answer 2xx in 60 s (${last}); nginx logs:\n${logs.stdout}${logs.stderr}`);
}

test('the proxy forwards the Host the client sent, port included', async () => {
  removeAll();
  try {
    must('network', 'create', NETWORK);
    // nginx resolves librechat when it loads the config, so the alias must exist before the proxy starts.
    must('run', '-d', '--name', ECHO, '--network', NETWORK, '--network-alias', 'librechat', NODE_IMAGE, 'node', '-e', ECHO_SERVER);
    must('run', '-d', '--name', PROXY, '--network', NETWORK, '-p', '127.0.0.1::8080', '-v', `${CONF}:/etc/nginx/conf.d/default.conf:ro`, NGINX_IMAGE);
    const port = Number(must('port', PROXY, '8080/tcp').split('\n')[0].split(':').pop());
    assert.ok(port > 0, `docker port gave no port for ${PROXY}`);

    const answer = await waitForProxy(port);

    assert.equal(answer.body, `127.0.0.1:${port}`);
  } finally {
    removeAll();
  }
});
