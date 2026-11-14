# Verification records

**Draft, for lawyer review.** This page sets out the method of the verification pass (the owner's decision of
2026-11-14), the record format and how a law is re-run. Where it states a legal fact (what the Gazette holds, which
text is in force, the Majalla's status) it is a working statement for the lawyer to confirm, not a finding.

## What is where

| Path | What it holds |
|---|---|
| `content/corpus/verification/<law-slug>.jsonl` | One record per corpus article of that law: the result of comparing the article's stored text with the Official Gazette and with the Legislation and Opinion Bureau (ديوان التشريع والرأي), with dates and references. |
| `docs/verification/evidence/<law-slug>.jsonl` | The texts compared: one line per article and source, so the comparison can be re-run without reading the sources again. Texts only, never images or PDFs. |
| `docs/verification/lawyer-open-items.md` | The lawyer's list, one list per law. Every `differs` and `unverifiable` article goes on it. |
| `tools/verification/v1.py` | Normalisation `v1` (`v1()`, `compare()`), the same for all three texts. Its self-test runs with `uv run pytest -q` in `tools/skills`. |
| `tools/verification/dump_texts.py` | The stored texts, as `legal_search.ingest.prepare` on `recall-plan` returns them, with their `text_sha256`. |

A law without a file is simply unverified. The library shows an article as verified only when its law's file has a
`verified` record whose `text_sha256` matches the text being stored.

**Neither path is served to the model.** The skills, prompts, starters and specialist never read them. On `recall-plan`
the ingest of `services/legal-search` reads the records from `verification/` beside the registry (the
`/content/corpus` mount) to set each article's `verified_at` and its Gazette and Bureau reference columns; the three
tools print only the verification label and those references. The records' `notes` and `lawyer_item`, and the evidence
texts, are never formatted into a tool's output, and `docs/` is not mounted in the service at all.

## The method (owner, 2026-11-14)

Quoted from the owner's instructions, §1, with the record fields named.

- **The text compared** is the article's text as the ingest stores it (`articles.text`: on `recall-plan`,
  `legal_search.ingest.prepare` → `corpus.parse_law` with `content/corpus/corrections.json` applied), never the search
  `norm` (which folds hamza, ة/ه, ى/ي, drops punctuation and strips prefixes, so real differences would pass).
- An article is `verified` only when its text equals, after `v1`:
  1. **the Official Gazette:** the text in force today. An article never amended is checked against the original law's
     issue. Where the latest amending law replaced the article's whole text, that law's published text is the text in
     force (record earlier issues if known; you need not read them). Otherwise the original plus every amending law
     that touched it (law number and year, issue, date, page). **And**
  2. **the Bureau's consolidated text:** its legislation id, the article's text, and the version or as-of date the
     Bureau shows.
- **Gazette page images count:** read from the page image, record `method: "image"` with the issue, page, document id
  and the image's sha256. Any word you cannot read makes the article `unverifiable` (`reason: "gazette_image_unread"`).
  The Gazette text is transcribed blind (without looking at the corpus text) and then compared with `v1` by script. The
  owner's local session re-reads a sample of recorded pages before the library goes live.
- **Issues before 2005** (not online on the Gazette site): scans of the official Gazette issue itself held on
  archive.org count as the Gazette (identify each by issue number and page, record the archive.org identifier and
  file sha256). No other edition, print copy or consolidation site counts. Without such a scan the article is
  `unverifiable` (`reason: "gazette_offline"`), and the missing issues are listed. (As found on 2026-11-14: the Gazette
  site lists issues from 4632 on; archive.org held no scan of a Jordanian Gazette issue.)
- **Repealed articles** (corpus «ملغاة»): `verified` when the repealing law's Gazette text and the Bureau both show the
  repeal (`effect: "repealed"`); the wording is not compared.
- **«مكرر» articles:** the first Gazette text is the amending law that inserted it (`effect: "added"`). A «مكرر» text
  merged inside its parent makes the parent `differs`; it is not split here (splits go only through the O-42 marker
  split, after the lawyer's samples and the owner's go).
- **Set aside and recorded in `notes`:** a section heading (باب/فصل/فرع …) or the next article's title glued to the end
  of an article, and a site's title after «المادة N —». A trailing part that cannot be identified as such a heading or
  title makes the record `differs` with `difference: "trailing-title"`. Every `differs` record carries `difference`
  (`formatting` | `trailing-title` | `body` | `repeal`) so the lawyer list can be grouped.
- **Disagreement, or a source that cannot be reached or read:** the article stays unverified. Both readings are
  recorded, the article goes on the lawyer list, and a fix is proposed only from a Gazette text that was read, in a
  separate one-law PR that changes only the amended passage and brings in nothing from the Bureau (the Gazette decides;
  the Bureau only helps find). Where only the Bureau differs, or the corpus is newer than the Bureau, the corpus text
  is kept and the record says `differs_from: "bureau"`.
- **Never mark anything verified that was not seen.** Article keys and ids do not change; any other missing or extra
  article is a Gazette-sourced law change in its own PR, with its record. Earlier agreement (the 2026-11-12 comparison,
  the third reading) does not count as verification.

### The Majalla rule

The Majalla (`majalla`, مجلة الأحكام العدلية, 1,851 articles) has no Jordanian Gazette publication and no Bureau record.
Each of its articles is recorded `unverifiable` with `reason: "no_official_source"`; no other edition is used (not
adaleh, not the Ottoman Düstur, not a print copy); its review stays `draft`; the law goes on the lawyer list as one
entry; and which text, if any, counts as official is the owner's decision. Any other text whose original was not
published in the Jordanian Official Gazette is treated the same way.

## Normalisation v1

`tools/verification/v1.py`, applied the same way to the stored text, the Gazette text and the Bureau text:

- Unicode NFC;
- tatweel (ـ) and the Arabic diacritics removed (U+0610–061A, U+064B–065F, U+0670, U+06D6–06DC, U+06DF–06E8,
  U+06EA–06ED);
- digit shapes unified (Arabic-Indic ٠–٩ and Extended Arabic-Indic ۰–۹ to 0–9);
- whitespace and line breaks collapsed to one space, the ends trimmed.

Nothing else: no letter folding (أ/إ/ا, ة/ه, ى/ي stay apart), no prefix stripping, punctuation kept and compared.
`compare(stored, other)` returns `(True, None)` when the two are equal after `v1`, `(False, "formatting")` when they
differ only in punctuation and the spacing around it (the punctuation set is `PUNCT` in the file), and
`(False, "body")` otherwise.

| Stored | Other | `compare` |
|---|---|---|
| `نص  النص` + line break | `نص النص` | equal |
| `المادة (٥)` | `المادة (5)` | equal |
| `التالية:-` | `التالية:` | `formatting` |
| `اذا` | `إذا` | `body` |
| `الهيئة` | `الهيئه` | `body` |

A change to these rules is a new normalisation (`v2`), and every record made under `v1` is re-run.

## The record

One JSON object per line, one line per corpus article of the law, in the order of the stored texts
(`dump_texts.py`'s order). Every key below is present (only `norm_sha256` may be left out); an unknown value is `null`.
corpus-ci rejects any other key.

| Key | Value |
|---|---|
| `law_slug` | the law's registry slug; the same as the file name |
| `number` | the article number (int) |
| `suffix` | the suffix as stored (`""`, `"مكرر"`, `"مكرر ثانياً"` …) |
| `text_sha256` | sha256 of the article's stored text, UTF-8, exactly as `legal_search.ingest.prepare` returns it: **the binding key** |
| `norm_sha256` | optional, information only: sha256 of the text after `v1` |
| `result` | `verified` \| `differs` \| `unverifiable` |
| `reason` | `gazette_offline` \| `gazette_image_unread` \| `bureau_unreachable` \| `no_official_source` \| `sources_disagree` \| `null` |
| `differs_from` | `gazette` \| `bureau` \| `both` \| `null` |
| `difference` | `formatting` \| `trailing-title` \| `body` \| `repeal` \| `null` |
| `checked_on` | YYYY-MM-DD |
| `normalisation` | `v1` |
| `gazette` | `null`, or `{method, original, amendments, text_sha256, checked_on}` (below) |
| `bureau` | `null`, or `{legislation_id, url, as_of, text_sha256, checked_on}` (below) |
| `notes` | text or `null`: what was set aside (a trailing heading, a site title), both readings where sources disagree, a fix PR |
| `lawyer_item` | the article's entry in `docs/verification/lawyer-open-items.md`, as text, or `null` |

`gazette`:

| Key | Value |
|---|---|
| `method` | `text` \| `image` \| `null` |
| `original` | `null`, or `{issue, date, page, document_id, url, file_sha256}`: the original law's publication |
| `amendments` | a list (may be empty) of `{law, year, issue, date, page, effect, document_id, url, file_sha256}`, one per amending law that touched the article; `effect` is `amended` (a passage changed) \| `replaced` (the whole text) \| `added` \| `repealed` \| `renumbered` |
| `text_sha256` | sha256 of the Gazette text as read (the evidence line's `text_sha256`) |
| `checked_on` | YYYY-MM-DD |

In `original` and each amendment, `issue`, `page` and `document_id` are an int or a non-empty string (a page range such
as `"1866-1867"` is a string), `date` is YYYY-MM-DD, `url` is an http(s) URL (for a pre-2005 scan, the archive.org
item), `file_sha256` is the sha256 of the page image or file read, and `law` and `year` are ints. Any of them may be
`null` when unknown; `effect` may not.

`bureau`: `legislation_id` (int or string), `url`, `as_of` (YYYY-MM-DD: the version or as-of date the Bureau shows),
`text_sha256` (of the Bureau's article text as read), `checked_on`.

What the result requires (corpus-ci checks these):

- `verified`: `reason`, `differs_from` and `difference` are `null`; both source blocks are filled: `gazette` has
  `method`, `text_sha256`, `checked_on` and at least one reference (`original` or an amendment) with `issue`, `date`,
  `page` and `document_id` or `url`, and with `method: "image"` that reference's `file_sha256`; `bureau` has all five
  keys.
- `differs`: `differs_from` and `difference` are set.
- `unverifiable`: `reason` is set.

The shape of a record (placeholders, not data):

```json
{"law_slug": "<slug>", "number": 1, "suffix": "", "text_sha256": "<64 hex>", "result": "verified", "reason": null,
 "differs_from": null, "difference": null, "checked_on": "<YYYY-MM-DD>", "normalisation": "v1",
 "gazette": {"method": "image", "original": {"issue": 0, "date": "<YYYY-MM-DD>", "page": 0, "document_id": 0,
   "url": null, "file_sha256": "<64 hex>"}, "amendments": [], "text_sha256": "<64 hex>", "checked_on": "<YYYY-MM-DD>"},
 "bureau": {"legislation_id": 0, "url": "<https URL>", "as_of": "<YYYY-MM-DD>", "text_sha256": "<64 hex>",
   "checked_on": "<YYYY-MM-DD>"},
 "notes": null, "lawyer_item": null}
```

## Evidence files

`docs/verification/evidence/<law-slug>.jsonl`, one line per article and source:

```json
{"law_slug": "<slug>", "number": 1, "suffix": "", "source": "gazette", "text": "<the text read>",
 "text_sha256": "<64 hex>", "url": null, "document_id": 0, "issue": 0, "page": 0, "image_sha256": "<64 hex>",
 "accessed_on": "<YYYY-MM-DD>"}
```

`source` is `gazette` or `bureau`; a Gazette line read from a page image carries `image_sha256`, a Bureau line `url`
and `null` for the Gazette fields. The text is the transcription or the Bureau's article text as read, before `v1`, so
`compare()` can be run on it again. Gazette images and PDFs are never committed; their sha256 identifies them.

## How to re-run a law

1. **The stored texts.** Take a checkout of `recall-plan` (the copy of `services/legal-search` that runs live; this
   branch's own `services/legal-search` is older and is not used), then from this repository's root:

   ```bash
   git worktree add --detach ../rp origin/recall-plan
   uv run --project ../rp/services/legal-search \
     python tools/verification/dump_texts.py --root . --out <dir> --law <law-slug>
   ```

   Each line holds `law_slug`, `number`, `suffix`, `text`, `text_sha256`, `shard` and `folder`. The script imports
   `legal_search` and has no parser of its own; it prints the folder it imported `legal_search` from. On the tree of
   2026-11-14 it gives 6,592 articles in 22 laws.
2. **The Bureau.** Open the legislation's public page,
   `https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=<id>&LegislationType=2&isMod=false`, in a
   browser and call the page's own API method `GetLegislationDetails` from it (the page encrypts and decrypts; only
   its results are read). It returns the legislation (number, year, Gazette issue, date and page) and its articles
   (`Article_Number`, `Article`). Record the id, the page URL, the as-of date and the article's text.
3. **The Gazette.** The Gazette site lists the documents of an issue at
   `https://pm.gov.jo/Ar/Pages/NewsPaperDetails/<issue>`; each document opens in the official viewer, which serves its
   pages as images. Save each page image outside the repository, record its sha256, the issue, page and document id,
   and transcribe the article blind. Issues not online there need an archive.org scan of the issue itself, or the
   article is `unverifiable` (`gazette_offline`).
4. **Compare** the stored text with each source text by script with `v1.compare`, after setting aside a trailing
   heading or title (and saying so in `notes`).
5. **Write** the law's file with a record for every article, in stored-text order, the evidence lines, and the lawyer
   list entries for every `differs` and `unverifiable` article.
6. **Check:** `corpus-ci` (below) for the schema, and on `recall-plan` the hash check
   (`legal-search-ingest --check-verification`) for the binding of every `verified` record to the current text.

Access rule: never bypass a WAF, a bot check, a captcha, a login or a 401/451 refusal. A source that refuses is
recorded as unreachable (`bureau_unreachable`, or `gazette_offline`), not worked around.

## What makes a record stale

The binding key is `text_sha256`. When an article's stored text changes (a corpus edit, an entry in
`corrections.json`, a change of the parser on `recall-plan`), its record no longer matches it:

- the server's `legal-search-ingest --check-verification` fails on a `verified` record whose `text_sha256` differs
  from the article's current text;
- the ingest stores that article unverified: `verified_at` and the reference columns are set to NULL, including where
  an earlier run had set them.

A Gazette-sourced fix PR therefore updates the records of the articles it changes in the same PR: the new
`text_sha256`, `result: "unverifiable"`, `notes: "fixed in <PR>; to re-verify"`; they are re-verified afterwards.

Two things the hash cannot see: an amending law published after `checked_on` (the law is re-run when one is
published), and a change of normalisation (a new name, and every record re-run).

## The checks

- **corpus-ci** (`tools/skills`, schema only): every file names a registry law; each line is a record of the schema
  above (no unknown keys, the enums, valid dates, what the result requires); and the law has exactly one record per
  corpus article and none for an article that does not exist. corpus-ci does not run the legal-search parser: it reads
  the article headings of the law's `sections/*.md` (`### المادة N`, with «مكرر» and one more word as the suffix;
  no article text), applies the corrections that change a key (`relabel`, `split`) and drops the registry's
  `known_gaps`. On the tree of 2026-11-14 these keys equal the 6,592 keys `ingest.prepare` returns; the exact binding
  to the text is the server's hash check.
- **The hash check** lives with the parser, on `recall-plan` (`legal-search-ingest --check-verification`).

## Law approval

A law is approved only when its publication data in `laws.json` (the original's Gazette issue and date, the last
amendment's law, year, issue and date) are checked against the Gazette **and** every article of the law is
`verified`. Its `review` then becomes `{status: "approved", approved_by: "verification pass (cloud agent), <PR>",
approved_on: <date>, basis: "content/corpus/verification/<law-slug>.jsonl"}`. A law with `known_gaps` is not complete.
