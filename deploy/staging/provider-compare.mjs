// Compares the usage ledger (iqraa_usage_events) with a provider's usage export, per UTC day and model.
// Read-only, tokens only: the ledger counts money in µAIC and the provider's money units are unknown.
//
//   node provider-compare.mjs --export <csv> [--usage <json file>] [--tolerance-pct n] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
//
// The export is a CSV with a header row. Required columns: date (a UTC day, YYYY-MM-DD), model, input_tokens,
// output_tokens; optional: cache_read_tokens, cache_write_tokens; any other column is ignored. Header names are
// trimmed and read case-insensitively, a byte-order mark and CRLF line ends are taken, blank lines are skipped,
// and several rows for one day and model are summed. Cells are plain: a double quote anywhere throws, since no
// provider is chosen and no real export has ever been parsed. Mapping the chosen provider's export onto these
// columns, and its model names onto the ledger's, is left to that choice.
//
// --usage is a JSON array of iqraa_usage_events documents (createdAt as ISO text, epoch ms or {"$date": ...}).
// Without it the command reads every event from the STAGING stack's Mongo through lib.mjs's mongoQuery, imported
// only then so that importing this module has no side effects. That read goes through execFileSync's default
// 1 MB output buffer, so a large ledger needs an exported --usage file instead.
//
// Rules:
// - Days are UTC on both sides; the ledger's createdAt is converted, never sliced as text.
// - Rows with estimated: true carry no provider tokens. They are left out of the sums and counted per day and
//   model in `estimated`. A group whose ledger rows are all estimated still counts as in the ledger with zero
//   tokens: it mismatches whatever the provider billed for it, or is missing at the provider when the export has
//   nothing for it; the count beside it says why.
// - A field mismatches when |ledger - provider| / max(ledger, provider) x 100 > tolerancePct (default 1); two
//   zeros agree. The cache fields are compared only when the export has their columns.
// - compareUsage takes an optional window (from, to: UTC days, inclusive) and leaves out the days outside it on
//   both sides. The command defaults it to the export's first and last day, so ledger history the export does not
//   cover is not reported missing; --from and --to set it explicitly, and the window is printed.
//
// Prints one JSON line { ok, mismatches, missingAtProvider, missingInLedger, estimated, window }. Exits 0 when
// ok, 1 when not, and 2 when it cannot read its input.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const REQUIRED = ['date', 'model', 'input_tokens', 'output_tokens'];
const OPTIONAL = ['cache_read_tokens', 'cache_write_tokens'];
/** Export column and usage event field, in the order mismatches are reported. */
const FIELDS = [
  ['input_tokens', 'inputTokens'],
  ['output_tokens', 'outputTokens'],
  ['cache_read_tokens', 'cacheReadTokens'],
  ['cache_write_tokens', 'cacheWriteTokens'],
];
const NO_MODEL = '(no model)';
const USAGE =
  'usage: node provider-compare.mjs --export <csv> [--usage <json file>] [--tolerance-pct n] [--from YYYY-MM-DD] [--to YYYY-MM-DD]';

function isDay(text) {
  if (typeof text !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(text)) return false;
  const time = Date.parse(`${text}T00:00:00Z`);
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === text;
}

const modelOf = (model) => (typeof model === 'string' && model.trim() !== '' ? model.trim() : NO_MODEL);

/** Parses a provider usage export into { date, model, inputTokens, outputTokens[, cacheReadTokens, cacheWriteTokens] }. */
export function parseExportCsv(text) {
  const lines = String(text).replace(/^\uFEFF/, '').split(/\r?\n/);
  let columns = null;
  const rows = [];
  lines.forEach((line, index) => {
    if (line.trim() === '') return;
    const number = index + 1;
    if (line.includes('"')) {
      throw new Error(`export line ${number} has a quoted cell; this reader takes plain comma-separated cells only`);
    }
    const cells = line.split(',').map((cell) => cell.trim());
    if (!columns) {
      const names = cells.map((cell) => cell.toLowerCase());
      for (const name of REQUIRED) if (!names.includes(name)) throw new Error(`the export is missing column "${name}"`);
      columns = new Map([...REQUIRED, ...OPTIONAL].filter((name) => names.includes(name)).map((name) => [name, names.indexOf(name)]));
      return;
    }
    const cell = (name) => cells[columns.get(name)] ?? '';
    const date = cell('date');
    if (!isDay(date)) throw new Error(`export line ${number}: date is "${date}", not a UTC day as YYYY-MM-DD`);
    const model = cell('model');
    if (model === '') throw new Error(`export line ${number}: model is empty`);
    const row = { date, model };
    for (const [column, field] of FIELDS) {
      if (!columns.has(column)) continue;
      const raw = cell(column);
      if (raw === '' && OPTIONAL.includes(column)) {
        row[field] = 0;
        continue;
      }
      if (!/^\d+$/.test(raw)) throw new Error(`export line ${number}: ${column} is "${raw}", not a whole number of tokens`);
      row[field] = Number(raw);
    }
    rows.push(row);
  });
  if (!columns) throw new Error('the export is empty: it has no header line');
  return rows;
}

function dayOf(createdAt, index) {
  let value = createdAt;
  if (value && typeof value === 'object' && !(value instanceof Date) && '$date' in value) value = value.$date;
  if (value && typeof value === 'object' && !(value instanceof Date) && '$numberLong' in value) value = Number(value.$numberLong);
  const time =
    value instanceof Date ? value.getTime() : typeof value === 'number' ? value : typeof value === 'string' ? Date.parse(value) : NaN;
  if (!Number.isFinite(time)) throw new Error(`usage row ${index + 1} has no readable createdAt`);
  return new Date(time).toISOString().slice(0, 10);
}

function tokensOf(row, field, index) {
  const value = row[field] ?? 0;
  const tokens =
    value && typeof value === 'object' ? Number(value.$numberLong ?? value.$numberInt ?? value.$numberDouble) : Number(value);
  if (!Number.isFinite(tokens) || tokens < 0) throw new Error(`usage row ${index + 1}: ${field} is not a token count`);
  return tokens;
}

function groupOf(groups, day, model) {
  const key = `${day}\u0000${model}`;
  if (!groups.has(key)) {
    groups.set(key, { day, model, sums: Object.fromEntries(FIELDS.map(([column]) => [column, 0])), absent: new Set(), estimated: 0 });
  }
  return groups.get(key);
}

function differs(ledger, provider, tolerancePct) {
  const base = Math.max(Math.abs(ledger), Math.abs(provider));
  return base > 0 && (Math.abs(ledger - provider) / base) * 100 > tolerancePct;
}

const byDayAndModel = (a, b) => (a.day === b.day ? (a.model < b.model ? -1 : a.model > b.model ? 1 : 0) : a.day < b.day ? -1 : 1);

/**
 * Compares usage events with parsed export rows, per UTC day and model.
 * @returns {{ ok: boolean, mismatches: {day, model, field, ledger, provider}[], missingAtProvider: object[],
 *   missingInLedger: object[], estimated: {day, model, count}[], window: {from, to} | null }}
 */
export function compareUsage(usageRows, exportRows, { tolerancePct = 1, from, to } = {}) {
  if (typeof tolerancePct !== 'number' || !Number.isFinite(tolerancePct) || tolerancePct < 0) {
    throw new Error(`the tolerance must be a percentage of 0 or more, not ${tolerancePct}`);
  }
  for (const [name, day] of [['from', from], ['to', to]]) {
    if (day != null && !isDay(day)) throw new Error(`${name} must be a UTC day as YYYY-MM-DD, not ${day}`);
  }
  const inWindow = (day) => (from == null || day >= from) && (to == null || day <= to);

  const ledger = new Map();
  usageRows.forEach((row, index) => {
    const day = dayOf(row.createdAt, index);
    if (!inWindow(day)) return;
    const group = groupOf(ledger, day, modelOf(row.model));
    if (row.estimated === true) {
      group.estimated += 1;
      return;
    }
    for (const [column, field] of FIELDS) group.sums[column] += tokensOf(row, field, index);
  });

  const provider = new Map();
  exportRows.forEach((row, index) => {
    if (!isDay(row.date)) throw new Error(`export row ${index + 1} has no UTC day in date`);
    if (!inWindow(row.date)) return;
    const group = groupOf(provider, row.date, modelOf(row.model));
    for (const [column, field] of FIELDS) {
      if (typeof row[field] === 'number') group.sums[column] += row[field];
      else group.absent.add(column);
    }
  });
  const reported = (group) =>
    Object.fromEntries(FIELDS.filter(([column]) => !group.absent.has(column)).map(([column]) => [column, group.sums[column]]));

  const mismatches = [];
  const missingAtProvider = [];
  const missingInLedger = [];
  const estimated = [];
  for (const [key, ours] of ledger) {
    const { day, model } = ours;
    if (ours.estimated > 0) estimated.push({ day, model, count: ours.estimated });
    const theirs = provider.get(key);
    if (!theirs) {
      missingAtProvider.push({ day, model, ...ours.sums });
      continue;
    }
    for (const [column] of FIELDS) {
      if (theirs.absent.has(column)) continue;
      const [a, b] = [ours.sums[column], theirs.sums[column]];
      if (differs(a, b, tolerancePct)) mismatches.push({ day, model, field: column, ledger: a, provider: b });
    }
  }
  for (const [key, theirs] of provider) {
    if (!ledger.has(key)) missingInLedger.push({ day: theirs.day, model: theirs.model, ...reported(theirs) });
  }
  for (const list of [mismatches, missingAtProvider, missingInLedger, estimated]) list.sort(byDayAndModel);

  return {
    ok: mismatches.length === 0 && missingAtProvider.length === 0 && missingInLedger.length === 0,
    mismatches,
    missingAtProvider,
    missingInLedger,
    estimated,
    window: from == null && to == null ? null : { from: from ?? null, to: to ?? null },
  };
}

async function main(args) {
  const { values } = parseArgs({
    args,
    options: {
      export: { type: 'string' },
      usage: { type: 'string' },
      'tolerance-pct': { type: 'string' },
      from: { type: 'string' },
      to: { type: 'string' },
    },
  });
  if (!values.export) throw new Error(USAGE);
  const exportRows = parseExportCsv(fs.readFileSync(values.export, 'utf8'));
  const days = exportRows.map((row) => row.date).sort();
  const from = values.from ?? days[0];
  const to = values.to ?? days.at(-1);
  if (from == null || to == null) throw new Error('the export has no rows; give --from and --to to say which days it covers');
  const tolerancePct = values['tolerance-pct'] === undefined ? 1 : Number(values['tolerance-pct']);

  let usageRows;
  if (values.usage) {
    usageRows = JSON.parse(fs.readFileSync(values.usage, 'utf8'));
  } else {
    const { mongoQuery } = await import('./lib.mjs');
    usageRows = mongoQuery({ op: 'find', collection: 'iqraa_usage_events' });
  }
  if (!Array.isArray(usageRows)) throw new Error('the usage must be a JSON array of iqraa_usage_events documents');

  const report = compareUsage(usageRows, exportRows, { tolerancePct, from, to });
  process.stdout.write(`${JSON.stringify(report)}\n`);
  return report.ok ? 0 : 1;
}

function invokedDirectly() {
  if (!process.argv[1]) return false;
  const invoked = path.resolve(process.argv[1]);
  const self = fileURLToPath(import.meta.url);
  return process.platform === 'win32' ? invoked.toLowerCase() === self.toLowerCase() : invoked === self;
}

if (invokedDirectly()) {
  main(process.argv.slice(2)).then(
    (code) => {
      process.exitCode = code;
    },
    (error) => {
      process.stderr.write(`provider-compare: ${error.message}\n`);
      process.exitCode = 2;
    },
  );
}
