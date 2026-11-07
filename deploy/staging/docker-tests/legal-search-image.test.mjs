// ensureLegalSearch builds hardening-test/legal-search:isolated from services/legal-search on every call, so the docker
// tests boot the service as this tree has it, never a tag an older run left behind (one such tag predated O-57's change).
//   node --test deploy/staging/docker-tests/legal-search-image.test.mjs
// Points the tag at another local image first, the pinned node image the stack already runs, then calls
// ensureLegalSearch in the project hardening-o57ls; Docker's build cache makes the rebuild quick when nothing changed.
// It starts no container and leaves the tag on a fresh legal-search build. It moves a tag the other files here boot,
// so it runs only one file at a time, as tools/gates.sh's docker step runs them (--test-concurrency=1).
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { ensureLegalSearch, LEGAL_SEARCH_IMAGE } from './isolated.mjs';

const NODE_IMAGE = 'node:24-alpine@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53';

function docker(...args) {
  const run = spawnSync('docker', args, { encoding: 'utf8' });
  if (run.error) throw run.error;
  assert.equal(run.status, 0, `docker ${args.join(' ')} failed: ${run.stderr}`);
  return run.stdout.trim();
}

const idOf = (image) => docker('image', 'inspect', '--format', '{{.Id}}', image);

test('ensureLegalSearch rebuilds the isolated legal-search tag even when the tag exists', { timeout: 30 * 60_000 }, () => {
  docker('tag', NODE_IMAGE, LEGAL_SEARCH_IMAGE);
  assert.equal(idOf(LEGAL_SEARCH_IMAGE), idOf(NODE_IMAGE));

  ensureLegalSearch('hardening-o57ls');

  assert.notEqual(idOf(LEGAL_SEARCH_IMAGE), idOf(NODE_IMAGE), 'the stale tag was kept');
  assert.equal(docker('image', 'inspect', '--format', '{{json .Config.Cmd}}', LEGAL_SEARCH_IMAGE), '["legal-search"]');
});
