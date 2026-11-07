// Tests for the ledger-versus-provider-export comparison, run on the host:  node --test provider-compare.test.mjs
// No provider is chosen, so the exports here are made up in the neutral column layout provider-compare.mjs reads.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { compareUsage, parseExportCsv } from './provider-compare.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MODEL = 'model-a';

/** One iqraa_usage_events document as mongoQuery returns it (dates as ISO text). */
const event = (createdAt, inputTokens, outputTokens, { model = MODEL, estimated = false, cacheReadTokens = 0, cacheWriteTokens = 0 } = {}) => ({
  key: `run-${createdAt}-${inputTokens}`,
  userId: 'user-1',
  amount: 1_000,
  estimated,
  model,
  createdAt,
  inputTokens,
  outputTokens,
  cacheReadTokens,
  cacheWriteTokens,
});
const csv = (...lines) => ['date,model,input_tokens,output_tokens', ...lines].join('\n');

test('matching totals are ok, summed per day and model, and an export without cache columns compares no cache', () => {
  const ledger = [
    event('2026-11-03T08:00:00.000Z', 600, 200, { cacheReadTokens: 50 }),
    event('2026-11-03T15:30:00.000Z', 400, 100),
    event('2026-11-03T09:00:00.000Z', 70, 30, { model: 'model-b' }),
  ];
  const provider = parseExportCsv(csv('2026-11-03,model-a,1000,300', '2026-11-03,model-b,40,10', '2026-11-03,model-b,30,20'));

  assert.deepEqual(compareUsage(ledger, provider), {
    ok: true,
    mismatches: [],
    missingAtProvider: [],
    missingInLedger: [],
    estimated: [],
    window: null,
  });
});

test('output tokens 2% off at a 1% tolerance is a mismatch naming the day, the model and the field', () => {
  const ledger = [event('2026-11-03T10:00:00.000Z', 5_000, 1_000)];
  const provider = parseExportCsv(csv('2026-11-03,model-a,5000,1020'));

  const result = compareUsage(ledger, provider, { tolerancePct: 1 });
  assert.equal(result.ok, false);
  assert.deepEqual(result.mismatches, [{ day: '2026-11-03', model: MODEL, field: 'output_tokens', ledger: 1_000, provider: 1_020 }]);
});

test('0.5% off passes at the default 1% tolerance', () => {
  const ledger = [event('2026-11-03T10:00:00.000Z', 5_000, 1_000)];
  const provider = parseExportCsv(csv('2026-11-03,model-a,5025,1005'));

  const result = compareUsage(ledger, provider);
  assert.equal(result.ok, true);
  assert.deepEqual(result.mismatches, []);
});

test('a day only in the export is missing in the ledger', () => {
  const ledger = [event('2026-11-03T10:00:00.000Z', 100, 50)];
  const provider = parseExportCsv(csv('2026-11-03,model-a,100,50', '2026-11-04,model-a,7,3'));

  const result = compareUsage(ledger, provider);
  assert.equal(result.ok, false);
  assert.deepEqual(result.missingInLedger, [{ day: '2026-11-04', model: MODEL, input_tokens: 7, output_tokens: 3 }]);
  assert.deepEqual(result.missingAtProvider, []);
  assert.deepEqual(result.mismatches, []);
});

test('a day only in the ledger is missing at the provider', () => {
  const ledger = [event('2026-11-03T10:00:00.000Z', 100, 50), event('2026-11-02T10:00:00.000Z', 9, 4, { cacheWriteTokens: 2 })];
  const provider = parseExportCsv(csv('2026-11-03,model-a,100,50'));

  const result = compareUsage(ledger, provider);
  assert.equal(result.ok, false);
  assert.deepEqual(result.missingAtProvider, [
    { day: '2026-11-02', model: MODEL, input_tokens: 9, output_tokens: 4, cache_read_tokens: 0, cache_write_tokens: 2 },
  ]);
  assert.deepEqual(result.missingInLedger, []);
});

test('an estimated row is left out of the sums and counted for its day and model', () => {
  const ledger = [
    event('2026-11-03T10:00:00.000Z', 100, 50),
    event('2026-11-03T11:00:00.000Z', 900, 900, { estimated: true }),
    event('2026-11-03T12:00:00.000Z', 0, 0, { estimated: true }),
  ];
  const provider = parseExportCsv(csv('2026-11-03,model-a,100,50'));

  const result = compareUsage(ledger, provider);
  assert.equal(result.ok, true);
  assert.deepEqual(result.mismatches, []);
  assert.deepEqual(result.estimated, [{ day: '2026-11-03', model: MODEL, count: 2 }]);
});

test('23:59 and 00:01 UTC land on two days, whatever offset or type the time comes in', () => {
  const ledger = [
    event('2026-11-03T23:59:00.000Z', 10, 1),
    event('2026-11-04T02:30:00+03:00', 20, 2), // 23:30 UTC on 3 November (Amman time is UTC+3)
    event(new Date('2026-11-04T00:01:00.000Z'), 300, 30),
    event({ $date: '2026-11-04T00:02:00.000Z' }, 4_000, 400),
  ];
  const provider = parseExportCsv(csv('2026-11-03,model-a,30,3', '2026-11-04,model-a,4300,430'));

  assert.deepEqual(compareUsage(ledger, provider), {
    ok: true,
    mismatches: [],
    missingAtProvider: [],
    missingInLedger: [],
    estimated: [],
    window: null,
  });
});

test('a window leaves out the days outside it on both sides', () => {
  const ledger = [event('2026-11-02T10:00:00.000Z', 9, 4), event('2026-11-03T10:00:00.000Z', 100, 50)];
  const provider = parseExportCsv(csv('2026-11-03,model-a,100,50', '2026-11-05,model-a,1,1'));

  const result = compareUsage(ledger, provider, { from: '2026-11-03', to: '2026-11-04' });
  assert.equal(result.ok, true);
  assert.deepEqual(result.window, { from: '2026-11-03', to: '2026-11-04' });
  assert.deepEqual(result.missingAtProvider, []);
  assert.deepEqual(result.missingInLedger, []);
});

test('the cache columns are compared when the export has them', () => {
  const ledger = [event('2026-11-03T10:00:00.000Z', 100, 50, { cacheReadTokens: 400, cacheWriteTokens: 30 })];
  const provider = parseExportCsv(
    'date,model,input_tokens,output_tokens,cache_read_tokens,cache_write_tokens\n2026-11-03,model-a,100,50,400,60',
  );

  assert.deepEqual(compareUsage(ledger, provider).mismatches, [
    { day: '2026-11-03', model: MODEL, field: 'cache_write_tokens', ledger: 30, provider: 60 },
  ]);
});

test('a missing required column throws naming it', () => {
  assert.throws(() => parseExportCsv('date,model,input_tokens\n2026-11-03,model-a,1'), /output_tokens/);
  assert.throws(() => parseExportCsv('model,input_tokens,output_tokens\nmodel-a,1,2'), /"date"/);
});

test('CRLF line ends and a byte-order mark parse', () => {
  const text = '\uFEFFdate,model,input_tokens,output_tokens,cache_read_tokens\r\n2026-11-03,model-a,10,20,5\r\n\r\n';

  assert.deepEqual(parseExportCsv(text), [{ date: '2026-11-03', model: MODEL, inputTokens: 10, outputTokens: 20, cacheReadTokens: 5 }]);
});

test('it refuses a cell it cannot read rather than guess', () => {
  assert.throws(() => parseExportCsv(csv('2026-11-03,model-a,ten,20')), /line 2.*input_tokens/);
  assert.throws(() => parseExportCsv(csv('03/11/2026,model-a,10,20')), /line 2.*date/);
  assert.throws(() => parseExportCsv('"date","model","input_tokens","output_tokens"\n"2026-11-03","model-a","1","2"'), /quoted/);
});

test('the command prints one JSON line and exits 1 when not ok, honouring --tolerance-pct', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'provider-compare-'));
  try {
    const exportFile = path.join(dir, 'export.csv');
    const usageFile = path.join(dir, 'usage.json');
    fs.writeFileSync(exportFile, csv('2026-11-03,model-a,5000,1020'));
    fs.writeFileSync(usageFile, JSON.stringify([event('2026-11-03T10:00:00.000Z', 5_000, 1_000)]));
    const run = (...extra) =>
      spawnSync(process.execPath, [path.join(HERE, 'provider-compare.mjs'), '--export', exportFile, '--usage', usageFile, ...extra], {
        encoding: 'utf8',
      });

    const strict = run();
    assert.equal(strict.status, 1, strict.stderr);
    const lines = strict.stdout.trim().split('\n');
    assert.equal(lines.length, 1);
    const report = JSON.parse(lines[0]);
    assert.equal(report.ok, false);
    assert.equal(report.mismatches[0].field, 'output_tokens');
    assert.deepEqual(report.window, { from: '2026-11-03', to: '2026-11-03' });

    const loose = run('--tolerance-pct', '5');
    assert.equal(loose.status, 0, loose.stderr);
    assert.equal(JSON.parse(loose.stdout.trim()).ok, true);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('without --usage the command reads iqraa_usage_events through the lib.mjs beside it', () => {
  // A copy of the command next to a stand-in lib.mjs, so no docker and no staging data are touched.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'provider-compare-'));
  try {
    const seen = path.join(dir, 'query.json');
    const rows = [event('2026-11-03T10:00:00.000Z', 5_000, 1_000), event('2026-10-01T10:00:00.000Z', 1, 1)];
    fs.copyFileSync(path.join(HERE, 'provider-compare.mjs'), path.join(dir, 'provider-compare.mjs'));
    fs.writeFileSync(
      path.join(dir, 'lib.mjs'),
      `import fs from 'node:fs';\nexport function mongoQuery(query) {\n  fs.writeFileSync(${JSON.stringify(seen)}, JSON.stringify(query));\n  return ${JSON.stringify(rows)};\n}\n`,
    );
    const exportFile = path.join(dir, 'export.csv');
    fs.writeFileSync(exportFile, csv('2026-11-03,model-a,5000,1000'));

    const run = spawnSync(process.execPath, [path.join(dir, 'provider-compare.mjs'), '--export', exportFile], { encoding: 'utf8' });
    assert.equal(run.status, 0, run.stderr);
    assert.deepEqual(JSON.parse(fs.readFileSync(seen, 'utf8')), { op: 'find', collection: 'iqraa_usage_events' });
    const report = JSON.parse(run.stdout.trim());
    assert.equal(report.ok, true, 'the October event is outside the export and so outside the default window');
    assert.deepEqual(report.window, { from: '2026-11-03', to: '2026-11-03' });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
