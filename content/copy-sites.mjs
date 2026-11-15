// The one list of copy-site names, content/corpus/copy-sites.json (owner, 2026-11-14 «Hide all copy sites»; Qistas added
// 2026-11-15, «Helper source only»), for the content tests. skill-ci (tools/skills, copy_sites.py) and the legal-search
// tests read the same file; no test keeps a list of its own.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const LIST = path.join(path.dirname(fileURLToPath(import.meta.url)), 'corpus', 'copy-sites.json');
const MARKS = /[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۨ-ۭـ]/g; // diacritics, tatweel
const DOMAIN = /^[a-z0-9-]+(?:\.[a-z0-9-]+)+$/i;

const fold = (text) => text.normalize('NFC').replace(MARKS, '').toLowerCase();

/** The list's names; a domain also stands for its first label («jordan-lawyer.com» and «jordan-lawyer»). */
export const copySiteNames = () => {
  const { names } = JSON.parse(fs.readFileSync(LIST, 'utf8'));
  return [...new Set(names.flatMap((name) => (DOMAIN.test(name) ? [name, name.split('.')[0]] : [name])))];
};

/** The listed names `text` holds, ignoring case, tatweel and diacritics (a plain substring match: stricter than
 * skill-ci's, which lets a statutory «المحامي الأردني» pass). */
export const namedSites = (text, names = copySiteNames()) => names.filter((name) => fold(text).includes(fold(name)));
