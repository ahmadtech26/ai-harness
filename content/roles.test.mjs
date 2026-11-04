// Tests for roles.json:  node --test content/roles.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const roles = JSON.parse(fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), 'roles.json'), 'utf8'));

// Every PermissionTypes member of librechat-data-provider (packages/data-provider/src/permissions.ts) with its
// permission names. The staging scenario `chatonly` checks the same on the running server, so a type an upgrade
// adds fails there; update this list with it.
const SCHEMA = {
  PROMPTS: ['USE', 'CREATE', 'SHARE', 'SHARE_PUBLIC'],
  BOOKMARKS: ['USE'],
  MEMORIES: ['USE', 'CREATE', 'UPDATE', 'READ', 'OPT_OUT'],
  AGENTS: ['USE', 'CREATE', 'SHARE', 'SHARE_PUBLIC'],
  MULTI_CONVO: ['USE'],
  TEMPORARY_CHAT: ['USE'],
  RUN_CODE: ['USE'],
  WEB_SEARCH: ['USE'],
  PEOPLE_PICKER: ['VIEW_USERS', 'VIEW_GROUPS', 'VIEW_ROLES'],
  MARKETPLACE: ['USE'],
  FILE_SEARCH: ['USE'],
  FILE_CITATIONS: ['USE'],
  MCP_SERVERS: ['USE', 'CREATE', 'SHARE', 'SHARE_PUBLIC', 'CONFIGURE_OBO'],
  REMOTE_AGENTS: ['USE', 'CREATE', 'SHARE', 'SHARE_PUBLIC'],
  SKILLS: ['USE', 'CREATE', 'SHARE', 'SHARE_PUBLIC'],
  SHARED_LINKS: ['CREATE', 'SHARE', 'SHARE_PUBLIC'],
  SCHEDULES: ['USE', 'CREATE'],
};
// The two permissions a customer needs: AGENTS.USE to chat with a tier, MCP_SERVERS.USE because LibreChat drops an
// agent's MCP tools (the legal library) for a role without it (ToolService `canUseMCP`).
const ALLOWED = ['AGENTS.USE', 'MCP_SERVERS.USE'];

test('the plan roles are all PLAN_ roles, and there are at least two so that tiers can differ by plan', () => {
  assert.ok(Object.keys(roles).length >= 2);
  assert.ok(Object.keys(roles).every((name) => /^PLAN_[A-Z]+$/.test(name)));
});

test('every plan role states every permission of every type explicitly, as a boolean', () => {
  for (const [name, role] of Object.entries(roles)) {
    assert.deepEqual(Object.keys(role.permissions).sort(), Object.keys(SCHEMA).sort(), name);
    for (const [type, names] of Object.entries(SCHEMA)) {
      assert.deepEqual(Object.keys(role.permissions[type]).sort(), [...names].sort(), `${name} ${type}`);
      assert.ok(Object.values(role.permissions[type]).every((value) => typeof value === 'boolean'), `${name} ${type}`);
    }
  }
});

test('a plan role grants chat with a tier and the library tools, and nothing else', () => {
  for (const [name, role] of Object.entries(roles)) {
    const granted = Object.entries(role.permissions).flatMap(([type, perms]) => Object.entries(perms).filter(([, on]) => on).map(([perm]) => `${type}.${perm}`));
    assert.deepEqual(granted.sort(), ALLOWED, name);
  }
});

test('the plan roles hold the same permissions: the plan decides the tiers, not the permissions', () => {
  const [first, ...others] = Object.values(roles);
  assert.ok(others.length >= 1);
  for (const role of others) assert.deepEqual(role.permissions, first.permissions);
});
