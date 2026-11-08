// Works the screen pass's report out again from its census, without a browser: after a change to the rules in
// ui/screen-pass.lib.cjs (what counts as English, the known points), or after adding reviewed findings.
//   node ui/screen-pass-report.mjs <pass folder>          (from deploy/staging; the folder run-screen-pass.mjs wrote)
// Rewrites census.json (each record's zone and verdict, the heading check), findings.json (this pass's findings again;
// entries marked "source": "review" are kept) and known-items.json (the same: points read by hand, marked
// "source": "review", are kept). Screenshots, screens.json and arabic-texts.json are not touched.
import fs from 'node:fs';
import path from 'node:path';
import lib from './screen-pass.lib.cjs';

const dir = process.argv[2];
if (!dir) throw new Error('usage: node ui/screen-pass-report.mjs <pass folder>');
const read = (name) => JSON.parse(fs.readFileSync(path.join(dir, name), 'utf8'));
const census = read('census.json');
census.entries = census.entries.map((entry) => {
  const again = lib.reclassify(entry);
  if (again.heading) again.heading = { ...again.heading, ...lib.headingJoin(again.heading.text, again.heading.unitTexts, again.heading.letterSpacing, again.heading.clipped) };
  return again;
});
census.reportedAt = new Date().toISOString();
const reached = census.entries.filter((entry) => entry.screen !== 'not-reached');
let previous = [];
try {
  previous = read('findings.json');
} catch {
  // no findings yet
}
const findings = lib.mergeFindings(previous, lib.autoFindings(reached));
let previousKnown = [];
try {
  previousKnown = read('known-items.json');
} catch {
  // no known items yet
}
const known = lib.mergeKnown(previousKnown, lib.knownItems(reached));
fs.writeFileSync(path.join(dir, 'census.json'), JSON.stringify(census, null, 1));
fs.writeFileSync(path.join(dir, 'findings.json'), JSON.stringify(findings, null, 1));
fs.writeFileSync(path.join(dir, 'known-items.json'), JSON.stringify(known, null, 1));
console.log(`${census.entries.length} entries; ${findings.length} findings (${findings.filter((f) => f.source === 'review').length} reviewed)`);
for (const k of known) console.log(`  ${k.item} ${k.on_screen.padEnd(11)} ${k.point}`);
