// Unit checks for the staging TOTP helper (RFC 6238 / RFC 4226), run on the host: node --test totp.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { base32Decode, nextAppStep, stepOf, totp } from './totp.cjs';

// RFC 6238 appendix B: the SHA-1 key is the ASCII string "12345678901234567890", here in base32 (RFC 4648).
const RFC_KEY_BASE32 = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ';

test('it decodes a base32 secret to its bytes', () => {
  assert.deepEqual(base32Decode(RFC_KEY_BASE32), Buffer.from('12345678901234567890', 'ascii'));
  assert.deepEqual(base32Decode('mzxw6ytb oi======'), Buffer.from('foobar', 'ascii')); // RFC 4648 §10; case, spaces, padding ignored
});

test('it gives the RFC 6238 SHA-1 codes', () => {
  assert.equal(totp(RFC_KEY_BASE32, { at: 59_000, digits: 8 }), '94287082');
  assert.equal(totp(RFC_KEY_BASE32, { at: 59_000 }), '287082');
  assert.equal(totp(RFC_KEY_BASE32, { at: 1_111_111_109_000, digits: 8 }), '07081804');
  assert.equal(totp(RFC_KEY_BASE32, { at: 2_000_000_000_000, digits: 8 }), '69279037');
});

test('it computes a code for an explicit 30 s step', () => {
  assert.equal(stepOf(59_000), 1);
  assert.equal(stepOf(60_000), 2);
  assert.equal(totp(RFC_KEY_BASE32, { step: 1 }), '287082');
});

test('it picks the current step when it is newer than the last one used', () => {
  assert.deepEqual(nextAppStep(-1, 95_000), { step: 3, waitMs: 0 });
  assert.deepEqual(nextAppStep(2, 95_000), { step: 3, waitMs: 0 });
});

test('it waits for the next step (plus 1 s) when the current one was already used', () => {
  assert.deepEqual(nextAppStep(3, 95_000), { step: 4, waitMs: 26_000 });
  assert.deepEqual(nextAppStep(3, 119_999), { step: 4, waitMs: 1_001 });
});
