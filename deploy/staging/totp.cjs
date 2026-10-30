// RFC 6238 TOTP (HMAC-SHA-1, 30 s steps, 6 digits by default) for the staging driver: lib.mjs imports it on
// the host and ui/rtl-check.cjs requires it inside the Playwright container, so both compute the same codes
// LibreChat's twoFactorService does. CommonJS so both can load it.
const crypto = require('node:crypto');

const BASE32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
const STEP_MS = 30_000;

/** RFC 4648 base32 to bytes; case, spaces and `=` padding are ignored. */
function base32Decode(text) {
  let bits = 0;
  let value = 0;
  const bytes = [];
  for (const char of String(text).toUpperCase().replace(/[\s=]/g, '')) {
    const index = BASE32.indexOf(char);
    if (index < 0) throw new Error(`not a base32 character: ${char}`);
    value = (value << 5) | index;
    bits += 5;
    if (bits >= 8) {
      bytes.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return Buffer.from(bytes);
}

/** The 30 s step a moment (ms since the epoch) falls in. */
const stepOf = (at = Date.now()) => Math.floor(at / STEP_MS);

/** The code for `step` (default: the step of `at`, default now). */
function totp(secret, { at = Date.now(), step = stepOf(at), digits = 6 } = {}) {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const mac = crypto.createHmac('sha1', base32Decode(secret)).update(counter).digest();
  const offset = mac[mac.length - 1] & 0xf;
  const binary = mac.readUInt32BE(offset) & 0x7fffffff;
  return String(binary % 10 ** digits).padStart(digits, '0');
}

/**
 * The step for the next app code and how long to wait for it. The fork accepts an app code's step once and
 * refuses any step at or below the last one it accepted (plan Decision 6), so when the current step was already
 * used (a sign-in or the runner's promote; LibreChat's confirm records no step, so waiting after it only costs
 * time) wait for the next one, plus 1 s for clock skew.
 */
function nextAppStep(lastStep, now = Date.now()) {
  const current = stepOf(now);
  if (current > lastStep) return { step: current, waitMs: 0 };
  return { step: lastStep + 1, waitMs: (lastStep + 1) * STEP_MS - now + 1_000 };
}

module.exports = { base32Decode, nextAppStep, stepOf, totp, STEP_MS };
