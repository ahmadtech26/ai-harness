# The law corpus against official sources (2026-11-12)

**Draft, for lawyer review («مسودة، لمراجعة المحامي»). Nothing here is verified or approved, and no review status was changed.** This report gives a named reviewer the evidence to check the transcription of each law against the Official Gazette (handoff decisions D14/D15); it does not do that check for them. The texts that only the Gazette can settle are listed, with both readings, in the appendices.

Deliverables in this pull request:

- this report;
- [`2026-11-12-corpus-diff.jsonl`](2026-11-12-corpus-diff.jsonl): one line per article (4,749 lines): law, article, suffix, class, scope, corpus text, official text, source (LOB id, URL, retrieval time, SHA-256 of the payload) and Gazette page;
- [`2026-11-12-corpus-vs-official/`](2026-11-12-corpus-vs-official/): one appendix per law with every article that is not identical, both readings of each difference, and the full texts where an article is missing, extra, renumbered or not amended;
- seventeen commits of proposed fixes, one law per commit (section 7).

## 1. What was found

- **4,741 corpus articles of 21 laws were aligned with the Legislation and Opinion Bureau's (LOB) official consolidated text** (plus 8 LOB articles the corpus lacks). Before the fixes: 182 identical, 1,298 equal after normalisation, 3,043 with a substantive difference, 134 whose text predates an amendment, 59 renumbered, 8 missing and 25 extra. Most substantive differences are formatting (headings, paragraph numbers, a following article's title glued to the end of an article, spacing); the body differences (real differences of words) are listed one by one in the appendices.
- **The corpus is behind the law.** 134 article texts in 14 laws predate an amendment that LOB records, and 7 articles that amendments added are absent (six «مكرر» articles and civil-code 1287). Yet the registry names the latest amendment for these laws, and every library result prints it as «آخر تعديل» under the quoted text, so a customer is told the text is current when it is not.
- **The proposed fixes** bring 132 of those articles up to LOB's consolidated text, add the 7 missing ones, and remove 11 stray «نص المادة مكرر» lines (a web-page label inside article text). After them the comparison finds 2 articles not amended (two penal articles LOB gives no amending law for) and 290 identical articles.
- **The official sources disagree with each other in places.** LOB's consolidated Evidence Law keeps the replaced text of article 21 and shifts articles 21 to 74 by one; LOB's consolidated Companies Law omits most of «الباب الخامس مكرر» (23 of the corpus's articles 65–89 مكرر have no LOB counterpart), which law 4/2002 added; LOB gives a Gazette date that the Gazette's own issue page contradicts for four amending laws, and an impossible issue number (3082017) for another. The Gazette's own issue pages were used to settle dates and issues wherever they are online.
- **The Gazette text could not be read in this session**: the Gazette's document server shows guests page images only (text layer and PDF download refused), and issues before 2005 are not online. No OCR was used; every text decision that needs the Gazette is left to the named reviewer.

## 2. Sources, in order of authority, and how they were read

| Source | Host | What was read | How |
|---|---|---|---|
| Official Gazette (الجريدة الرسمية) | `pm.gov.jo`, `doc.pm.gov.jo` | the issue list (date of each issue) and each issue's contents page (title and document id of every item), for every issue from 2005 on that holds one of the laws or amending laws | headless Chromium on the official pages; the document viewer was opened for issue 5922 to see what it serves |
| Legislation and Opinion Bureau | `www.lob.gov.jo` | for each law: the record (number, year, Gazette issue, date, page), the consolidated articles, the list of amending laws, the per-article amendment list, the as-released version and every intermediate version; for each amending law: its record and text | the official page in headless Chromium, calling the page's own API methods (`GetLegislationDetails`, `GetlegislationModified`, `GetArticleModified`, `GetlegislationAsReleased`, `GetFinalLegislation`); the page encrypts and decrypts, the results were saved as data |
| Jordan Bar Association copy (convenience only, never proof) | `www.jba.org.jo` | «قانون اصول المحاكمات المدنية وتعديلاته» (PDF, 35 pages, printed from a web page on 2023-06-17) | text layer extracted with the extraction fixed (see below); used only as a third reading of civil-procedure differences |

Hosts were requested one at a time with evidence: `www.lob.gov.jo` (176 registry source URLs point to it), `www.jba.org.jo` (the PDF named in the task), `pm.gov.jo` (LOB's own site links to `pm.gov.jo/ar/Pages/NewsPaper` as the Gazette), `doc.pm.gov.jo` (the Gazette's issue pages link every item to it). No mirror or unofficial copy was used as proof.

**The Gazette's text.** The issue pages open each law in a DocuWare viewer as a guest. For issue 5922 (law 6/2024 amending civil procedure, document 59579, «عدد 5922.pdf», 2 pages) the viewer serves page images; the text layer (`TextshotPage`) answers 401 and the PDF download (`FileDownload`) answers 451 to the guest. So no Gazette text was compared, and no OCR was run. LOB marks one Gazette scan (investment fund) as attached; its file URL answers 404.

**The Bar Association PDF** (SHA-256 `6996af0ec4e37dcf0591f4750000d6902e91ad2ac2694cce23d388238b616478`) has a broken text layer of the usual kind: the lam-alef ligature is stored as a zero-width alef before the lam (so a naive extraction reads «لا» as «ال»), and each line's words are in visual order. The extraction was fixed (swap the zero-width alef back, reverse each line's words, NFKC), not the text; some initial alefs of «الا…» words are absent from the layer itself, so the copy is compared on a skeleton without alef and hamza forms.

## 3. Method

1. **Corpus side**: the articles exactly as the product parses them (`legal_search.corpus.parse_law` with `content/corpus/corrections.json` applied): text in a heading («### المادة N — …») included, «مكرر» labels as parsed.
2. **Official side**: LOB's consolidated articles, HTML turned into text. LOB embeds added articles in the text of the article before them («المادة (25 مكررة):-», «المادة (59) مكرر:-»); these were split out. Where an LOB article's text starts with its own label («المادة 21 -») that label's number was used (LOB's number field is wrong in one law). The court-fees corpus is the schedule «جدول رسوم المحاكم», which LOB carries inside the regulation's last article; it was split into its 52 items.
3. **Two levels**: (a) exact = Unicode NFC and whitespace; (b) normalised = also diacritics, tatweel, hamza seats, ى/ي, ة/ه, Arabic-Indic digits and punctuation. "Identical" means equal at (a).
4. **Classes** (as asked): identical | normalisation-only | substantive difference | amendment not applied | numbering or order differs | missing in corpus | extra in corpus. A substantive difference also gets a **scope** so a reviewer can tell kinds apart: `spacing-only` (only where spaces fall), `repeal-note` (both say the article is repealed, in other words), `formatting` (equal once heading lines and standalone paragraph numbers are set aside), `trailing-title` (the corpus article ends with the next article's title), `body` (the words differ).
5. **Amendment not applied**: the corpus text equals an earlier LOB version of the article, or is within three words of it and further from the final text, or lacks words that the text of an amending law LOB lists for that article contains. Each LOB version row is the text **before** its amending law (checked on civil-procedure 191, which law 6/2024 changed).
6. **Numbering or order differs**: the corpus text matches the LOB article one or two numbers away far better than the LOB article with the same number.
7. **Which version the corpus represents**: the LOB version (as released, each intermediate one, final) that most corpus articles equal at level (b); and the amending laws whose changes are missing (section 5, per law).
8. **Registry and amendment chain**: registry against the LOB record; LOB's amending laws against the Gazette's own issue pages (is the law listed in the issue LOB names, and on what date does the Gazette put that issue).

## 4. Counts by class, per law

**Before the proposed fixes** (the corpus as it is on `demo-fixes-2026-11-11`):

| Law | Corpus | LOB | identical | normalisation-only | substantive difference | amendment not applied | numbering or order differs | missing in corpus | extra in corpus |
|---|---|---|---|---|---|---|---|---|---|
| civil-procedure | 229 | 229 | 17 | 110 | 99 | 3 | 0 | 0 | 0 |
| civil-code | 1448 | 1449 | 104 | 645 | 699 | 0 | 0 | 1 | 0 |
| evidence | 74 | 75 | 1 | 3 | 17 | 1 | 52 | 1 | 0 |
| landlords-tenants | 22 | 22 | 0 | 1 | 19 | 2 | 0 | 0 | 0 |
| commerce | 480 | 480 | 0 | 0 | 480 | 0 | 0 | 0 | 0 |
| penal-code | 489 | 490 | 14 | 219 | 236 | 20 | 0 | 1 | 0 |
| maritime-commerce | 386 | 386 | 0 | 0 | 386 | 0 | 0 | 0 | 0 |
| companies | 314 | 292 | 0 | 0 | 239 | 51 | 0 | 0 | 24 |
| customs | 254 | 253 | 0 | 2 | 216 | 30 | 5 | 0 | 1 |
| income-tax | 82 | 82 | 0 | 1 | 80 | 1 | 0 | 0 | 0 |
| sales-tax | 77 | 78 | 0 | 0 | 73 | 3 | 1 | 1 | 0 |
| labour | 142 | 142 | 0 | 0 | 131 | 10 | 1 | 0 | 0 |
| investment-fund | 16 | 16 | 0 | 0 | 16 | 0 | 0 | 0 | 0 |
| execution | 119 | 121 | 0 | 3 | 116 | 0 | 0 | 2 | 0 |
| mediation | 14 | 14 | 0 | 11 | 3 | 0 | 0 | 0 | 0 |
| criminal-procedure | 372 | 374 | 41 | 213 | 109 | 9 | 0 | 2 | 0 |
| courts-formation | 23 | 23 | 3 | 13 | 6 | 1 | 0 | 0 | 0 |
| magistrates-courts | 22 | 22 | 1 | 11 | 10 | 0 | 0 | 0 | 0 |
| major-felonies-court | 16 | 16 | 1 | 10 | 4 | 1 | 0 | 0 | 0 |
| court-fees | 52 | 52 | 0 | 1 | 50 | 1 | 0 | 0 | 0 |
| bar-association | 110 | 110 | 0 | 55 | 54 | 1 | 0 | 0 | 0 |
| **all** | 4,741 | 4,726 | **182** | **1,298** | **3,043** | **134** | **59** | **8** | **25** |

Substantive differences and amendments not applied, by scope (before the fixes):

| Law | body | formatting | trailing-title | spacing-only | repeal-note |
|---|---|---|---|---|---|
| civil-procedure | 44 | 45 | 0 | 12 | 1 |
| civil-code | 214 | 443 | 0 | 15 | 27 |
| evidence | 7 | 10 | 0 | 1 | 0 |
| landlords-tenants | 11 | 0 | 10 | 0 | 0 |
| commerce | 345 | 0 | 131 | 0 | 4 |
| penal-code | 154 | 79 | 3 | 17 | 3 |
| maritime-commerce | 172 | 0 | 213 | 0 | 1 |
| companies | 167 | 0 | 121 | 0 | 2 |
| customs | 134 | 0 | 112 | 0 | 0 |
| income-tax | 37 | 0 | 44 | 0 | 0 |
| sales-tax | 28 | 0 | 48 | 0 | 0 |
| labour | 45 | 0 | 96 | 0 | 0 |
| investment-fund | 6 | 0 | 10 | 0 | 0 |
| execution | 26 | 0 | 88 | 0 | 2 |
| mediation | 2 | 1 | 0 | 0 | 0 |
| criminal-procedure | 72 | 40 | 1 | 4 | 1 |
| courts-formation | 6 | 0 | 0 | 1 | 0 |
| magistrates-courts | 5 | 5 | 0 | 0 | 0 |
| major-felonies-court | 4 | 0 | 0 | 1 | 0 |
| court-fees | 26 | 25 | 0 | 0 | 0 |
| bar-association | 30 | 24 | 0 | 1 | 0 |
| **all** | **1,535** | **672** | **877** | **52** | **41** |

**After the proposed fixes** (same comparison on this branch):

| Law | identical | normalisation-only | substantive difference | amendment not applied | numbering or order differs | missing in corpus | extra in corpus |
|---|---|---|---|---|---|---|---|
| civil-procedure | 19 | 111 | 99 | 0 | 0 | 0 | 0 |
| civil-code | 105 | 645 | 699 | 0 | 0 | 0 | 0 |
| evidence | 1 | 3 | 18 | 0 | 52 | 1 | 0 |
| landlords-tenants | 2 | 1 | 19 | 0 | 0 | 0 | 0 |
| commerce | 0 | 0 | 480 | 0 | 0 | 0 | 0 |
| penal-code | 21 | 223 | 244 | 2 | 0 | 0 | 0 |
| maritime-commerce | 0 | 0 | 386 | 0 | 0 | 0 | 0 |
| companies | 47 | 0 | 243 | 0 | 0 | 0 | 24 |
| customs | 20 | 2 | 226 | 0 | 5 | 0 | 1 |
| income-tax | 1 | 1 | 80 | 0 | 0 | 0 | 0 |
| sales-tax | 3 | 0 | 74 | 0 | 1 | 0 | 0 |
| labour | 9 | 0 | 132 | 0 | 1 | 0 | 0 |
| investment-fund | 0 | 0 | 16 | 0 | 0 | 0 | 0 |
| execution | 2 | 3 | 116 | 0 | 0 | 0 | 0 |
| mediation | 0 | 11 | 3 | 0 | 0 | 0 | 0 |
| criminal-procedure | 51 | 214 | 109 | 0 | 0 | 0 | 0 |
| courts-formation | 4 | 13 | 6 | 0 | 0 | 0 | 0 |
| magistrates-courts | 1 | 11 | 10 | 0 | 0 | 0 | 0 |
| major-felonies-court | 2 | 10 | 4 | 0 | 0 | 0 | 0 |
| court-fees | 1 | 1 | 50 | 0 | 0 | 0 | 0 |
| bar-association | 1 | 55 | 54 | 0 | 0 | 0 | 0 |
| **all** | **290** | **1,304** | **3,068** | **2** | **59** | **1** | **25** |

## 5. Per law: sources, amendment chain, version, registry, what the reviewer must confirm

### قانون أصول المحاكمات المدنية (`civil-procedure`)

- **LOB**: قانون أصول المحاكمات المدنية رقم 24 لسنة 1988, id 3420 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3420&LegislationType=2&isMod=false); retrieved 2026-11-12T20:06:22Z; SHA-256 of the record and articles `64bab8cfb9d984f8a9caf456d3dcbd77b9b7ee0b20ff5efb4b7e77cfa8f0a80f`, of the amending-law list `2df214e4961bab5de8634360076e2b11cab33a880b3b4a10aeb5ff5d52d0912b`, of the per-article amendment list `623d71595c95660d923ddeeed24b072314acacd00e4169f7cddcc8c623b3030d`. As released: LOB id 936; 8 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 3545, 1988-04-02, page 735. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 14/2001 | 904 | 4480 | 2001-03-18 | 1252 | not online | — |
| 26/2002 | 506 | 4547 | 2002-05-16 | 2066 | not online | — |
| 20/2005 | 912 | 4720 | 2005-09-15 | 3926 | 2005-09-15 | yes |
| 16/2006 | 911 | 4751 | 2006-03-16 | 752 | 2006-03-16 | yes |
| 31/2017 | 4235 | 5479 | 2017-08-30 | 5391 | 2017-08-30 | yes |
| 4/2019 | 4363 | 5557 | 2019-01-28 | 347 | 2019-01-28 | yes |
| 14/2023 | 4790 | 5859 | 2023-05-17 | 2480 | 2023-05-17 | yes |
| 6/2024 | 4873 | 5922 | 2024-04-16 | 1866 | 2024-04-16 | yes |

- **Version the corpus represents**: the versions most corpus articles equal: «before 6/2024 (LOB 3395)» and «final (LOB 3420)» (127 articles; all versions: before 14/2001 (LOB 936) 13, before 26/2002 (LOB 2467) 17, before 20/2005 (LOB 2468) 17, before 16/2006 (LOB 2469) 17, before 31/2017 (LOB 2470) 109, before 4/2019 (LOB 3251) 120, before 14/2023 (LOB 3253) 120, before 6/2024 (LOB 3395) 127, final (LOB 3420) 127). Amending laws with changes missing from the corpus (articles): 14/2001: 182, 193; 6/2024: 191.
- **Counts** before → after the fixes: identical 17→19, normalisation-only 110→111, substantive difference 99→99, amendment not applied 3→0. Appendix: [civil-procedure.md](2026-11-12-corpus-vs-official/civil-procedure.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): civil-procedure: …`): 3 replace, 1 remove-label.
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 3545, not online); each amending law's Gazette issue and page (2 of 8 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 44 articles whose words differ (appendix, scope `body`).

### القانون المدني الأردني (`civil-code`)

- **LOB**: القانون المدني رقم 43 لسنة 1976, id 536 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=536&LegislationType=2&isMod=false); retrieved 2026-11-12T20:05:14Z; SHA-256 of the record and articles `d5dea1ee52ed4d0aded29486310128e1ed221f56d6a55bf74d443d591a46a5c3`, of the amending-law list `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`, of the per-article amendment list `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`. As released: LOB id 536; 0 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 2645, 1976-08-01, page 2. The issue is not online on the Gazette's site.

- **Version the corpus represents**: the version most corpus articles equal: «final (LOB 536)» (749 articles; all versions: final (LOB 536) 749). No amendment LOB records is missing from the corpus text.
- **Counts** before → after the fixes: identical 104→105, normalisation-only 645→645, substantive difference 699→699, missing in corpus 1→0. Appendix: [civil-code.md](2026-11-12-corpus-vs-official/civil-code.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): civil-code: …`): 1 fill; registry: removed the gap for article 1287, whose text is now filled from LOB.
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 2645, not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 214 articles whose words differ (appendix, scope `body`).

### قانون البينات (`evidence`)

- **LOB**: قانون البينات رقم 30 لسنة 1952, id 3243 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3243&LegislationType=2&isMod=false); retrieved 2026-11-12T20:06:28Z; SHA-256 of the record and articles `30d67cdfb14dd9418ba7edc9184daa264239d52a0e7d4de45793a2992363f76f`, of the amending-law list `e4829170b9ec5a8a98de891cbbea4b627998c618a9c259a14c80d2e95436f312`, of the per-article amendment list `7ae94a3fe077f6e98074780ad9494a76a8866645c62a6589599bcd5a3a511c58`. As released: LOB id 385; 4 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 1108, 1952-05-17, page 200. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 24/1961 | 1155 | 1563 | 1952-05-17 | 944 | not online | — |
| 37/2001 | 460 | 4501 | 2001-08-16 | 3330 | not online | — |
| 16/2005 | 1154 | 4709 | 2005-06-01 | 2188 | 2005-06-01 | yes |
| 22/2017 | 4161 | 5474 | 2017-08-01 | 4604 | 2017-08-01 | yes |

- **Version the corpus represents**: the version most corpus articles equal: «before 22/2017 (LOB 1923)» (28 articles; all versions: before 24/1961 (LOB 385) 26, before 37/2001 (LOB 1921) 26, before 16/2005 (LOB 1922) 26, before 22/2017 (LOB 1923) 28, final (LOB 3243) 4). Amending laws with changes missing from the corpus (articles): 16/2005: 6.
- **Counts** before → after the fixes: identical 1→1, normalisation-only 3→3, substantive difference 17→18, amendment not applied 1→0, numbering or order differs 52→52, missing in corpus 1→1. Appendix: [evidence.md](2026-11-12-corpus-vs-official/evidence.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): evidence: …`): 1 replace.
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 1108, not online); each amending law's Gazette issue and page (2 of 4 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 7 articles whose words differ (appendix, scope `body`); LOB's numbering of articles 21–75 (section 6, item 9).

### قانون المالكين والمستأجرين (`landlords-tenants`)

- **LOB**: قانون المالكين والمستأجرين رقم 11 لسنة 1994, id 2803 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=2803&LegislationType=2&isMod=false); retrieved 2026-11-12T20:05:19Z; SHA-256 of the record and articles `b63c4494a9cd39da6b5055a37f6504c491c49249cd326ed0f33025c010fa3e3d`, of the amending-law list `31e81e77bebe218177d86966ed13ee466fb7b823ef85371791ecb3f054a28328`, of the per-article amendment list `591cd6b49c4e85aa8c24c41133b35dfabff730dc48f5b706126719b37a0f7b36`. As released: LOB id 1143; 4 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 3984, 1994-08-01, page 1656. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 30/2000 | 795 | 4453 | 2000-08-13 | 3415 | not online | — |
| 17/2009 | 94 | 4979 | 2009-09-01 | 4356 | 2009-09-01 | yes |
| 43/2010 | 792 | 5075 | 2010-12-30 | 7236 | 2010-12-30 | yes |
| 22/2011 | 791 | 5134 | 2011-12-31 | 5572 | 2011-12-31 | yes |

- **Version the corpus represents**: the version most corpus articles equal: «final (LOB 2803)» (1 articles; all versions: before 30/2000 (LOB 1143) 0, before 17/2009 (LOB 2800) 0, before 43/2010 (LOB 2801) 0, before 22/2011 (LOB 2802) 0, final (LOB 2803) 1). Amending laws with changes missing from the corpus (articles): 22/2011: 5, 7.
- **Counts** before → after the fixes: identical 0→2, normalisation-only 1→1, substantive difference 19→19, amendment not applied 2→0. Appendix: [landlords-tenants.md](2026-11-12-corpus-vs-official/landlords-tenants.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): landlords-tenants: …`): 2 replace.
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 3984, not online); each amending law's Gazette issue and page (1 of 4 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 11 articles whose words differ (appendix, scope `body`).

### قانون التجارة (`commerce`)

- **LOB**: قانون التجارة رقم 12 لسنة 1966, id 1028 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=1028&LegislationType=2&isMod=false); retrieved 2026-11-12T20:05:34Z; SHA-256 of the record and articles `36ecb9499d1c87cd483b5b72a0590d0b4bd85d3ff049a6ac07ab9099be80f1bc`, of the amending-law list `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`, of the per-article amendment list `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`. As released: LOB id 1028; 0 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 1910, 1966-03-30, page 472. The issue is not online on the Gazette's site.

- **Version the corpus represents**: the version most corpus articles equal: «final (LOB 1028)» (0 articles; all versions: final (LOB 1028) 0). No amendment LOB records is missing from the corpus text.
- **Counts** before → after the fixes: substantive difference 480→480. Appendix: [commerce.md](2026-11-12-corpus-vs-official/commerce.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): commerce: …`): .
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 1910, not online); which reading is right for the 345 articles whose words differ (appendix, scope `body`).

### قانون العقوبات الأردني (`penal-code`)

- **LOB**: قانون العقوبات رقم 16 لسنة 1960, id 3435 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3435&LegislationType=2&isMod=false); retrieved 2026-11-12T20:05:27Z; SHA-256 of the record and articles `bfcbbe9245d6e1568a86846e8563e416539688b483b5acf0acc059740d052b05`, of the amending-law list `eafd9a00bf72b7169ffbe490380d2cd97811b9a59000eee1ec482cb23782cc3f`, of the per-article amendment list `d8e40e052b533e99e6855f3a5fdea40a0717145c6969e7d8d0363d045a07236c`. As released: LOB id 508; 28 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 1487, 1960-01-01, page 374. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 24/1962 | 1276 | 1627 | — | 810 | not online | — |
| 39/1963 | 1231 | 1727 | — | 1683 | not online | — |
| 40/1963 | 1232 | 1727 | — | 1684 | not online | — |
| 29/1965 | 1241 | 1859 | — | 1070 | not online | — |
| 42/1965 | 1375 | 1876 | — | 1606 | not online | — |
| 1/1966 | 1222 | 1895 | — | — | not online | — |
| 7/1966 | 1223 | 1902 | — | — | not online | — |
| 15/1971 | 1228 | 2291 | — | 556 | not online | — |
| 40/1971 | 1233 | 2305 | — | — | not online | — |
| 9/1988 | 1225 | 3533 | — | 361 | not online | — |
| 15/1991 | 1229 | 3775 | — | 1471 | not online | — |
| 11/1996 | 1226 | None | 1996-12-25 | 4329 | not online | — |
| 54/2001 | 439 | 4510 | 2001-10-08 | 4467 | not online | — |
| 86/2001 | 410 | 4524 | 2001-12-31 | 6026 | not online | — |
| 33/2002 | 438 | 4553 | 2002-07-01 | 2944 | not online | — |
| 45/2003 | 501 | 4600 | 2003-06-01 | 2639 | not online | — |
| 41/2006 | 1234 | 4785 | 2006-10-01 | 3745 | 2006-10-01 | yes |
| 11/2007 | 1227 | 4817 | 2007-04-01 | 1679 | 2007-04-01 | yes |
| 16/2007 | 1230 | 4821 | 2007-04-16 | 2219 | 2007-04-16 | yes |
| 49/2007 | 1235 | 4862 | 2007-11-15 | 6734 | 2007-11-15 | yes |
| 12/2010 | 1641 | 5034 | 2010-06-01 | 3000 | 2010-06-01 | yes |
| 8/2011 | 1224 | 5090 | 2011-05-02 | 1758 | 2011-05-02 | yes |
| 9/2014 | 567 | 5275 | 2014-03-16 | 1701 | 2014-03-16 | yes |
| 27/2017 | 4218 | 3082017 (LOB) → **5479** | 2017-08-30 | 5334 | 2017-08-30 | yes |
| 7/2018 | 4026 | 5499 | 2018-03-01 | 503 | 2018-02-01 **≠** | yes |
| 10/2022 | 4732 | 5796 | 2022-06-02 | 3591 | 2022-05-25 **≠** | yes |
| 12/2025 | 4966 | 5996 | 2025-06-16 | 3064 | 2025-06-16 | yes |

- **Version the corpus represents**: the version most corpus articles equal: «final (LOB 3435)» (233 articles; all versions: before 16/1960 (LOB 508) 123, before 24/1962 (LOB 2146) 123, before 39/1963 (LOB 2147) 123, before 40/1963 (LOB 2148) 123, before 29/1965 (LOB 2149) 123, before 42/1965 (LOB 2150) 124, before 1/1966 (LOB 2151) 124, before 7/1966 (LOB 2152) 124, before 15/1971 (LOB 2153) 124, before 40/1971 (LOB 2154) 124, before 9/1988 (LOB 2155) 124, before 15/1991 (LOB 2156) 124, before 11/1996 (LOB 2157) 124, before 54/2001 (LOB 2158) 123, before 86/2001 (LOB 2159) 123, before 33/2002 (LOB 2160) 123, before 45/2003 (LOB 2161) 123, before 41/2006 (LOB 2162) 123, before 11/2007 (LOB 2163) 123, before 16/2007 (LOB 2164) 123, before 49/2007 (LOB 2165) 124, before 12/2010 (LOB 2166) 123, before 8/2011 (LOB 2167) 123, before 9/2014 (LOB 2168) 146, before 27/2017 (LOB 2169) 176, before 7/2018 (LOB 3262) 224, before 10/2022 (LOB 3263) 224, before 12/2025 (LOB 3366) 231, final (LOB 3435) 233). Amending laws with changes missing from the corpus (articles): 27/2017: 25, 99, 185, 308 مكرر, 334 مكرر; 10/2022: 25, 177, 334 مكرر; 12/2025: 25, 72; 8/2011: 80, 102, 185, 228, 287, 300, 306, 308 مكرر, 334 مكرر, 407, 422; 29/1965: 126; 40/1971: 177; 49/2007: 185, 208; 9/2014: 185, 228, 300, 308 مكرر, 422, 475; 16/1960: 228.
- **Counts** before → after the fixes: identical 14→21, normalisation-only 219→223, substantive difference 236→244, amendment not applied 20→2, missing in corpus 1→0. Appendix: [penal-code.md](2026-11-12-corpus-vs-official/penal-code.md).
- **Registry** (`content/corpus/laws.json`) against LOB and the Gazette: gazette.date: registry 1960-05-01, LOB 1960-01-01.
- **Proposed fixes** (commit `fix(corpus): penal-code: …`): 18 replace, 2 skipped, 1 add, 7 remove-label; registry: 489 -> 490 articles (total 6,594).
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 1487, not online); each amending law's Gazette issue and page (16 of 27 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 154 articles whose words differ (appendix, scope `body`).

### قانون التجارة البحرية (`maritime-commerce`)

- **LOB**: قانون التجارة البحرية رقم 12 لسنة 1972, id 1840 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=1840&LegislationType=2&isMod=false); retrieved 2026-11-12T20:05:39Z; SHA-256 of the record and articles `b2cd11eb3a3c73b2f8bb89ffc0898fc45e109afd19b057f4ee63ff1b6ed18298`, of the amending-law list `b55a93d56680bd8a8cf1c6bdd8e0678a0302e1eed6da04499075553288f6bb47`, of the per-article amendment list `c7da1246d7bc69fe317a81408c9e6b3d017e53cbe592927f0160c9365264638b`. As released: LOB id 358; 2 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 2357, 1972-05-06, page 698. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 4/1978 | 1506 | 2758 | — | 219 | not online | — |
| 35/1983 | 1507 | 3194 | — | 1951 | not online | — |

- **Version the corpus represents**: the versions most corpus articles equal: «before 4/1978 (LOB 358)» and «before 35/1983 (LOB 1839)» and «final (LOB 1840)» (0 articles; all versions: before 4/1978 (LOB 358) 0, before 35/1983 (LOB 1839) 0, final (LOB 1840) 0). No amendment LOB records is missing from the corpus text.
- **Counts** before → after the fixes: substantive difference 386→386. Appendix: [maritime-commerce.md](2026-11-12-corpus-vs-official/maritime-commerce.md).
- **Registry** (`content/corpus/laws.json`) against LOB and the Gazette: amendment.gazette_issue: registry None, LOB 3194.
- **Proposed fixes** (commit `fix(corpus): maritime-commerce: …`): ; registry: added 3194 (p. 1951) for law 35/1983, per the LOB record of that law; the Gazette issue is not online, so a reviewer must confirm it.
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 2357, not online); each amending law's Gazette issue and page (2 of 2 not online); which reading is right for the 172 articles whose words differ (appendix, scope `body`).

### قانون الشركات (`companies`)

- **LOB**: قانون الشركات رقم 22 لسنة 1997, id 3410 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3410&LegislationType=2&isMod=false); retrieved 2026-11-12T20:05:45Z; SHA-256 of the record and articles `e46fd692953277e756524c488f82611f206502dae38f1e73a5985cfb43759a6b`, of the amending-law list `50a0b200742279808c72a13c251ff499b1e34b761d31719df22bac42ff6692bc`, of the per-article amendment list `66ae45a06f91989325b6ef6589ce23601abfd772d0eb1b5ee06b3e1c86de440e`. As released: LOB id 1070; 11 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 4204, 1997-05-15, page 2038. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 4/2002 | 786 | 4533 | 2002-02-17 | 373 | not online | — |
| 40/2002 | 788 | 4556 | 2002-07-16 | 3319 | not online | — |
| 74/2002 | 1193 | 4577 | 2002-12-23 | 6204 | not online | — |
| 17/2003 | 787 | 4589 | 2003-03-16 | 1201 | not online | — |
| 57/2006 | 1192 | 4790 | 2006-11-01 | 4271 | 2006-11-01 | yes |
| 35/2008 | 1190 | 4919 | 2008-07-23 | 3038 | 2008-07-23 | yes |
| 35/2010 | 1474 | 5059 | 2010-09-30 | 5567 | 2010-09-30 | yes |
| 34/2017 | 4247 | 5481 | 2017-09-17 | 5441 | not given | yes |
| 17/2021 | 4648 | 5724 | 2021-06-16 | 2375 | 2021-06-16 | yes |
| 19/2021 | 4682 | 5743 | 2021-09-16 | 3784 | 2021-09-16 | yes |
| 20/2023 | 4819 | 5874 | 2023-08-13 | 3627 | not given | yes |

- **Version the corpus represents**: the versions most corpus articles equal: «before 4/2002 (LOB 1070)» and «before 40/2002 (LOB 2701)» and «before 74/2002 (LOB 2702)» and «before 17/2003 (LOB 2703)» and «before 57/2006 (LOB 2704)» and «before 35/2008 (LOB 2705)» and «before 35/2010 (LOB 2706)» and «before 34/2017 (LOB 2707)» and «before 17/2021 (LOB 3250)» and «before 19/2021 (LOB 3347)» and «before 20/2023 (LOB 3353)» and «final (LOB 3410)» (0 articles; all versions: before 4/2002 (LOB 1070) 0, before 40/2002 (LOB 2701) 0, before 74/2002 (LOB 2702) 0, before 17/2003 (LOB 2703) 0, before 57/2006 (LOB 2704) 0, before 35/2008 (LOB 2705) 0, before 35/2010 (LOB 2706) 0, before 34/2017 (LOB 2707) 0, before 17/2021 (LOB 3250) 0, before 19/2021 (LOB 3347) 0, before 20/2023 (LOB 3353) 0, final (LOB 3410) 0). Amending laws with changes missing from the corpus (articles): 40/2002: 2, 34, 37, 59, 67, 73, 78, 87, 97, 98, 186, 200 …; 35/2010: 2, 28, 34, 37, 59, 78, 79, 80, 84, 85, 86, 87 …; 20/2023: 2, 5, 6, 7, 11, 13, 14, 28, 31, 32, 34, 37 …; 17/2003: 186; 34/2017: 186; 4/2002: 223.
- **Counts** before → after the fixes: identical 0→47, substantive difference 239→243, amendment not applied 51→0, extra in corpus 24→24. Appendix: [companies.md](2026-11-12-corpus-vs-official/companies.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): companies: …`): 51 replace.
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 4204, not online); each amending law's Gazette issue and page (4 of 11 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 167 articles whose words differ (appendix, scope `body`); the 23 «مكرر» articles of «الباب الخامس مكرر» (66–88 مكرر) that LOB's consolidated text lacks (section 6, item 10).

### قانون الجمارك (`customs`)

- **LOB**: قانون الجمارك رقم 20 لسنة 1998, id 3473 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3473&LegislationType=2&isMod=false); retrieved 2026-11-12T20:05:52Z; SHA-256 of the record and articles `f8ef22bdabe537052d9a763659b7a24e8242d5b1fe8f4ffc005234957ee05fae`, of the amending-law list `8ca9c1653f50dfaa5d8f68f328fa4659aea62db465023f89a5fcc6efc2914730`, of the per-article amendment list `39ea0273d5c9d9203ea7f6b4bb8c1265ab59879291bdad5366a18aebfa9bca6a`. As released: LOB id 51; 8 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 4305, 1998-10-01, page 3935. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 10/1999 | 1161 | 4338 | 1999-08-24 | 1186 | not online | — |
| 16/2000 | 1162 | 4423 | 2000-04-02 | 1323 | not online | — |
| 27/2000 | 1163 | 4443 | 2000-07-02 | 2677 | not online | — |
| 23/2005 | 538 | 4732 | 2005-11-30 | 4980 | 2005-11-30 | yes |
| 24/2010 | 1473 | 5040 | 2010-07-01 | 3972 | 2010-07-01 | yes |
| 37/2010 | 1164 | 5062 | 2010-11-01 | 6179 | 2010-11-01 | yes |
| 33/2018 | 4339 | 5520 | 2018-06-14 | 3851 | 2018-06-14 | yes |
| 7/2025 | 5008 | 5991 | 2025-04-30 | 2251 | 2025-04-30 | yes |

- **Version the corpus represents**: the versions most corpus articles equal: «before 7/2025 (LOB 3267)» and «final (LOB 3473)» (2 articles; all versions: before 10/1999 (LOB 51) 0, before 16/2000 (LOB 1532) 0, before 27/2000 (LOB 1533) 0, before 23/2005 (LOB 1534) 0, before 24/2010 (LOB 1535) 0, before 37/2010 (LOB 1536) 0, before 33/2018 (LOB 1537) 0, before 7/2025 (LOB 3267) 2, final (LOB 3473) 2). Amending laws with changes missing from the corpus (articles): 7/2025: 2, 5, 20, 21, 31, 41, 64, 71, 84, 133, 148, 170 …; 33/2018: 14, 41, 168, 170, 188, 192, 202, 229; 16/2000: 32, 41, 161.
- **Counts** before → after the fixes: identical 0→20, normalisation-only 2→2, substantive difference 216→226, amendment not applied 30→0, numbering or order differs 5→5, extra in corpus 1→1. Appendix: [customs.md](2026-11-12-corpus-vs-official/customs.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): customs: …`): 30 replace.
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 4305, not online); each amending law's Gazette issue and page (3 of 8 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 134 articles whose words differ (appendix, scope `body`).

### قانون ضريبة الدخل (`income-tax`)

- **LOB**: قانون ضريبة الدخل
 رقم 34 لسنة 2014, id 3225 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3225&LegislationType=2&isMod=false); retrieved 2026-11-12T20:05:58Z; SHA-256 of the record and articles `a49f625015a652b42ee4d630e8e9c79ee8c61fb9779f2d7f5160b77430021940`, of the amending-law list `21ddf05e0b6283e01d57314449ab0f4c8971090ed653299c578ded78ebe41cd9`, of the per-article amendment list `b6245078ff2899e8832aa4286688dd80097242d703ab95ba6ffd672bcd2a0e32`. As released: LOB id 795; 1 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 5320, 2014-12-31, page 7390. The Gazette's own [issue page](https://pm.gov.jo/Ar/Pages/NewsPaperDetails/5320) dates the issue 2014-12-31 and lists «* قانون رقم (34) لسنة 2014 - قانون ضريبة الدخـل» (contents SHA-256 `645a987e98908312c6572ed547128a393c842786aca5a65d20e85e36cacfe7ec`).

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 38/2018 | 4285 | 5547 | 2018-12-02 | 7285 | 2018-12-02 | yes |

- **Version the corpus represents**: the versions most corpus articles equal: «before 38/2018 (LOB 795)» and «final (LOB 3225)» (1 articles; all versions: before 38/2018 (LOB 795) 1, final (LOB 3225) 1). Amending laws with changes missing from the corpus (articles): 38/2018: 34.
- **Counts** before → after the fixes: identical 0→1, normalisation-only 1→1, substantive difference 80→80, amendment not applied 1→0. Appendix: [income-tax.md](2026-11-12-corpus-vs-official/income-tax.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): income-tax: …`): 1 replace.
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 5320, online); each amending law's Gazette issue and page (0 of 1 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 37 articles whose words differ (appendix, scope `body`).

### قانون الضريبة العامة على المبيعات (`sales-tax`)

- **LOB**: قانون الضريبة العامة العامة على المبيعات رقم 6 لسنة 1994, id 3370 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3370&LegislationType=2&isMod=false); retrieved 2026-11-12T20:06:03Z; SHA-256 of the record and articles `546c4cfe8896066217e3ca89f22fecd1763c22289fc1dcc381a020834d403d0e`, of the amending-law list `9e3fba1ce7be3e1fe3d3fe331d02d2e7c7bbc9d35c1f245d015cd33d415159a9`, of the per-article amendment list `b6baaa01911bb84ff6898247e45c0d8161ebbe04cf452e947e87af617f9e21af`. As released: LOB id 575; 14 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 3970, 1994-05-31, page 1037. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 15/1995 | 29 | 4027 | 1995-10-01 | 2985 | not online | — |
| 24/1999 | 31 | 4364 | 1977-07-20 | 2583 | not online | — |
| 18/2000 | 30 | 4423 | 2000-04-02 | 1345 | not online | — |
| 36/2000 | 38 | 4457 | 2000-10-01 | 3942 | not online | — |
| 25/2002 | 495 | 4547 | 2002-05-16 | 2057 | not online | — |
| 23/2003 | 493 | 4592 | 2003-04-16 | 1680 | not online | — |
| 5/2004 | 28 | 4651 | 2004-04-01 | 1397 | not online | — |
| 32/2004 | 37 | 4672 | 2004-08-16 | 3980 | not online | — |
| 32/2008 | 427 | 4910 | 2008-06-01 | 2047 | 2008-06-01 | yes |
| 25/2009 | 32 | 4990 | 2009-10-15 | 5534 | 2009-10-15 | yes |
| 29/2009 | 153 | 5005 | 2009-12-30 | 7187 | 2009-12-30 | yes |
| 26/2012 | 550 | 5167 | 2012-07-18 | 3420 | 2012-07-18 | yes |
| 26/2013 | 557 | 5167 | 2012-07-18 | 3420 | 2012-07-18 | no |
| 15/2022 | 4746 | 5812 | 2022-09-01 | 6223 | 2022-09-01 | yes |

- **Version the corpus represents**: the versions most corpus articles equal: «before 15/1995 (LOB 575)» and «before 24/1999 (LOB 2204)» and «before 18/2000 (LOB 2205)» and «before 36/2000 (LOB 2206)» and «before 25/2002 (LOB 2207)» and «before 23/2003 (LOB 2208)» and «before 5/2004 (LOB 2209)» and «before 32/2004 (LOB 2210)» and «before 32/2008 (LOB 2211)» and «before 25/2009 (LOB 2212)» and «before 29/2009 (LOB 2213)» and «before 26/2012 (LOB 2214)» and «before 26/2013 (LOB 2215)» and «before 15/2022 (LOB 2216)» and «final (LOB 3370)» (0 articles; all versions: before 15/1995 (LOB 575) 0, before 24/1999 (LOB 2204) 0, before 18/2000 (LOB 2205) 0, before 36/2000 (LOB 2206) 0, before 25/2002 (LOB 2207) 0, before 23/2003 (LOB 2208) 0, before 5/2004 (LOB 2209) 0, before 32/2004 (LOB 2210) 0, before 32/2008 (LOB 2211) 0, before 25/2009 (LOB 2212) 0, before 29/2009 (LOB 2213) 0, before 26/2012 (LOB 2214) 0, before 26/2013 (LOB 2215) 0, before 15/2022 (LOB 2216) 0, final (LOB 3370) 0). Amending laws with changes missing from the corpus (articles): 15/2022: 2; 36/2000: 9, 21.
- **Counts** before → after the fixes: identical 0→3, substantive difference 73→74, amendment not applied 3→0, numbering or order differs 1→1, missing in corpus 1→0. Appendix: [sales-tax.md](2026-11-12-corpus-vs-official/sales-tax.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): sales-tax: …`): 3 replace, 1 add; registry: 77 -> 78 articles (total 6,595).
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 3970, not online); each amending law's Gazette issue and page (8 of 14 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 28 articles whose words differ (appendix, scope `body`).

### قانون العمل (`labour`)

- **LOB**: قانون العمل رقم 8 لسنة 1996, id 3392 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3392&LegislationType=2&isMod=false); retrieved 2026-11-12T20:06:11Z; SHA-256 of the record and articles `f9edd7370d1669f038f93dd9b3ff780a28f5282e6905acdf726c35a0cf5e3173`, of the amending-law list `030698eecb338b7647a442709a49adb4300c475e12a91ba5fd2fa35d5efb32da`, of the per-article amendment list `8a1d2eca66e07582377f8988ecbc33ca1e519a3172c2ac4c78e216f5791ea295`. As released: LOB id 79; 13 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 4113, 1996-04-16, page 1173. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 12/1997 | 1128 | 4192 | — | 1182 | not online | — |
| 12/1998 | 1129 | 4304 | — | 3733 | not online | — |
| 11/1999 | 1126 | 4338 | 1999-04-01 | 1928 | not online | — |
| 56/2001 | 468 | 4511 | 2001-10-16 | 4483 | not online | — |
| 51/2002 | 435 | 4561 | 2002-08-28 | 4085 | not online | — |
| 60/2002 | 523 | 4567 | 2002-10-10 | 4915 | not online | — |
| 11/2004 | 1127 | 4658 | 2004-05-16 | 2368 | not online | — |
| 30/2006 | 1135 | 4759 | 2006-05-16 | 1715 | 2006-05-16 | yes |
| 12/2007 | 1130 | 4817 | 2007-04-01 | 1682 | 2007-04-01 | yes |
| 48/2008 | 1136 | 4924 | 2008-08-17 | 3487 | 2008-08-17 | yes |
| 26/2010 | 1131 | 5042 | 2010-07-15 | 4478 | not given | yes |
| 14/2019 | 4416 | 5573 | 2019-05-16 | 2878 | 2019-05-16 | yes |
| 10/2023 | 4785 | 5851 | 2023-04-16 | 1775 | 2023-04-16 | yes |

- **Version the corpus represents**: the versions most corpus articles equal: «before 12/1997 (LOB 79)» and «before 12/1998 (LOB 1584)» and «before 11/1999 (LOB 1585)» and «before 56/2001 (LOB 1586)» and «before 51/2002 (LOB 1587)» and «before 60/2002 (LOB 1588)» and «before 11/2004 (LOB 1589)» and «before 30/2006 (LOB 1590)» and «before 12/2007 (LOB 1591)» and «before 48/2008 (LOB 1592)» and «before 26/2010 (LOB 1593)» and «before 14/2019 (LOB 3259)» and «before 10/2023 (LOB 3260)» and «final (LOB 3392)» (0 articles; all versions: before 12/1997 (LOB 79) 0, before 12/1998 (LOB 1584) 0, before 11/1999 (LOB 1585) 0, before 56/2001 (LOB 1586) 0, before 51/2002 (LOB 1587) 0, before 60/2002 (LOB 1588) 0, before 11/2004 (LOB 1589) 0, before 30/2006 (LOB 1590) 0, before 12/2007 (LOB 1591) 0, before 48/2008 (LOB 1592) 0, before 26/2010 (LOB 1593) 0, before 14/2019 (LOB 3259) 0, before 10/2023 (LOB 3260) 0, final (LOB 3392) 0). Amending laws with changes missing from the corpus (articles): 11/2004: 10, 118, 137; 14/2019: 10; 10/2023: 10, 11, 12, 29, 30, 46, 69, 139; 48/2008: 29.
- **Counts** before → after the fixes: identical 0→9, substantive difference 131→132, amendment not applied 10→0, numbering or order differs 1→1. Appendix: [labour.md](2026-11-12-corpus-vs-official/labour.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): labour: …`): 10 replace.
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 4113, not online); each amending law's Gazette issue and page (7 of 13 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 45 articles whose words differ (appendix, scope `body`).

### قانون صندوق الاستثمار الأردني (`investment-fund`)

- **LOB**: قانــون صنـــدوق الاستثمـار الأردنـي رقم 16 لسنة 2016, id 3135 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3135&LegislationType=2&isMod=false); retrieved 2026-11-12T20:06:16Z; SHA-256 of the record and articles `dafbeca3822edaf9626843e31d7140cd662005c0112f538d11566da59a3b19ca`, of the amending-law list `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`, of the per-article amendment list `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`. As released: LOB id 3135; 0 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 5399, 2016-05-26, page 2913. The Gazette's own [issue page](https://pm.gov.jo/Ar/Pages/NewsPaperDetails/5399) dates the issue 2016-05-26 and lists «* قانون رقــــم (16) لسنــة 2016 - قانــون صنـــدوق الاستثمـار الأردنـي» (contents SHA-256 `41782ef8c54e3ed1848a0c0dea2de918d62bc0b1857459730427a683f8d793e0`).

- **Version the corpus represents**: the version most corpus articles equal: «final (LOB 3135)» (0 articles; all versions: final (LOB 3135) 0). No amendment LOB records is missing from the corpus text.
- **Counts** before → after the fixes: substantive difference 16→16. Appendix: [investment-fund.md](2026-11-12-corpus-vs-official/investment-fund.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): investment-fund: …`): .
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 5399, online); which reading is right for the 6 articles whose words differ (appendix, scope `body`).

### قانون التنفيذ (`execution`)

- **LOB**: قانون التنفيذ رقم 25 لسنة 2007, id 3365 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3365&LegislationType=2&isMod=false); retrieved 2026-11-12T20:06:33Z; SHA-256 of the record and articles `3a5f7a34ca887c638a9e1982409a8efa4a162dee956fd10730e31a135cc98a4a`, of the amending-law list `39a8047dd8ad3675dfabbc624ab190aab208545958f239f30caf9aeb9d025667`, of the per-article amendment list `ac31128e67404f34778ce0e050f3adce5ab8bf6293f73c6d19effbaf5c2b6cf7`. As released: LOB id 1297; 3 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 4821, 2007-04-16, page 2262. The Gazette's own [issue page](https://pm.gov.jo/Ar/Pages/NewsPaperDetails/4821) dates the issue 2007-04-16 and lists «* قانون رقم (25) لسنة 2007 - قانون التنفيذ» (contents SHA-256 `e207f2c4e5adfa71830d4b9a16fb562d9144cd57a2124b3665f236ef3aa6b118`).

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 29/2017 | 4223 | 5479 | 2017-08-30 | 5369 | 2017-08-30 | yes |
| 3/2019 | 4405 | 5557 | 2019-01-28 | 345 | 2019-01-28 | yes |
| 9/2022 | 4731 | 5796 | 2022-05-25 | 3583 | 2022-05-25 | yes |

- **Version the corpus represents**: the version most corpus articles equal: «final (LOB 3365)» (3 articles; all versions: before 29/2017 (LOB 1297) 0, before 3/2019 (LOB 3233) 2, before 9/2022 (LOB 3254) 2, final (LOB 3365) 3). No amendment LOB records is missing from the corpus text.
- **Counts** before → after the fixes: identical 0→2, normalisation-only 3→3, substantive difference 116→116, missing in corpus 2→0. Appendix: [execution.md](2026-11-12-corpus-vs-official/execution.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): execution: …`): 2 add; registry: 119 -> 121 articles (total 6,597).
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 4821, online); each amending law's Gazette issue and page (0 of 3 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 26 articles whose words differ (appendix, scope `body`).

### قانون الوساطة لتسوية النزاعات المدنية (`mediation`)

- **LOB**: قانون الوساطة لتسوية النزاعات المدنية رقم 12 لسنة 2006, id 3245 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3245&LegislationType=2&isMod=false); retrieved 2026-11-12T20:06:39Z; SHA-256 of the record and articles `78378f1d454219088d21b9c065d5434a0c3524754ba0d791a2acb37d9f58c002`, of the amending-law list `46469119d9045fa40f187d3c7dc7d22776734398ba2c08e58b6e55e41debc809`, of the per-article amendment list `b4d1f86370eef7471be50ac4ca7d199285ac04940ebf6a5920814a2950a7d580`. As released: LOB id 1252; 1 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 4751, 2006-03-16, page 738. The Gazette's own [issue page](https://pm.gov.jo/Ar/Pages/NewsPaperDetails/4751) dates the issue 2006-03-16 and lists «* قانون رقم (12) لسنة 2006 قانون الوساطة لتسوية النزاعات المدنية» (contents SHA-256 `503b0c8eb683446f6f7ff370f12a19223eb95d92364e1998911b66cd1565833f`).

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 25/2017 | 4163 | 5474 | 2017-08-01 | 4622 | 2017-08-01 | yes |

- **Version the corpus represents**: the version most corpus articles equal: «final (LOB 3245)» (11 articles; all versions: before 25/2017 (LOB 1252) 10, final (LOB 3245) 11). No amendment LOB records is missing from the corpus text.
- **Counts** before → after the fixes: normalisation-only 11→11, substantive difference 3→3. Appendix: [mediation.md](2026-11-12-corpus-vs-official/mediation.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): mediation: …`): .
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 4751, online); each amending law's Gazette issue and page (0 of 1 not online); which reading is right for the 2 articles whose words differ (appendix, scope `body`).

### قانون أصول المحاكمات الجزائية (`criminal-procedure`)

- **LOB**: قانون اصول  المحاكمات الجزائية رقم 9 لسنة 1961, id 3252 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3252&LegislationType=2&isMod=false); retrieved 2026-11-12T20:06:45Z; SHA-256 of the record and articles `d4b7946049851bc6fc2c63832ced6012127101c8d9cda27b4f3a2d560f0c1a2d`, of the amending-law list `f3ecf17212151d87d20868e2e4c745b4f34e4c96f1fbc2205bae8abedaacacba`, of the per-article amendment list `af112d7dc88145efd1c6f45117ad7382cf677d89ed14dc84f4bc045e0ece71c8`. As released: LOB id 168; 10 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 1539, 1961-01-01, page 311. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 75/1966 | 967 | 1948 | — | 1824 | not online | — |
| 39/1968 | 966 | 2089 | — | 640 | not online | — |
| 26/1970 | 964 | 2268 | — | — | not online | — |
| 16/1991 | 961 | 3775 | 1991-08-05 | 1472 | not online | — |
| 16/2001 | 962 | 4480 | 2001-03-18 | 1294 | not online | — |
| 76/2003 | 968 | 4606 | 2003-06-16 | 3329 | not online | — |
| 15/2006 | 960 | 4751 | 2006-03-16 | 747 | 2006-03-16 | yes |
| 19/2009 | 963 | 4979 | 2009-09-01 | 4366 | 2009-09-01 | yes |
| 11/2010 | 1246 | 5034 | 2010-06-01 | 2998 | 2010-06-01 | yes |
| 32/2017 | 4236 | 5479 | 2017-08-30 | 5412 | 2017-08-30 | yes |

- **Version the corpus represents**: the version most corpus articles equal: «final (LOB 3252)» (254 articles; all versions: before 75/1966 (LOB 168) 189, before 39/1968 (LOB 1721) 189, before 26/1970 (LOB 1722) 189, before 16/1991 (LOB 1723) 189, before 16/2001 (LOB 1724) 189, before 76/2003 (LOB 1725) 197, before 15/2006 (LOB 1726) 197, before 19/2009 (LOB 1727) 200, before 11/2010 (LOB 1728) 201, before 32/2017 (LOB 1729) 201, final (LOB 3252) 254). Amending laws with changes missing from the corpus (articles): 16/2001: 14; 11/2010: 14, 136, 237, 288; 32/2017: 14, 68, 338, 341; 16/1991: 364, 365.
- **Counts** before → after the fixes: identical 41→51, normalisation-only 213→214, substantive difference 109→109, amendment not applied 9→0, missing in corpus 2→0. Appendix: [criminal-procedure.md](2026-11-12-corpus-vs-official/criminal-procedure.md).
- **Registry** (`content/corpus/laws.json`) against LOB and the Gazette: gazette.date: registry None, LOB 1961-01-01.
- **Proposed fixes** (commit `fix(corpus): criminal-procedure: …`): 9 replace, 2 add, 3 remove-label; registry: 372 -> 374 articles (total 6,599).
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 1539, not online); each amending law's Gazette issue and page (6 of 10 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 72 articles whose words differ (appendix, scope `body`).

### قانون تشكيل المحاكم النظامية (`courts-formation`)

- **LOB**: قانون تشكيل المحاكم النظامية رقم 17 لسنة 2001, id 3235 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3235&LegislationType=2&isMod=false); retrieved 2026-11-12T20:06:50Z; SHA-256 of the record and articles `e8050f001e5bf70f26864a8a670b1b6505c2bf46671fbf69aada3f09ed7dfa3b`, of the amending-law list `486dccc1c17b3a476e71e8b998d28b43e6f2c51011a9f75dd007bbd01e7309b6`, of the per-article amendment list `6781e5bfe22a0a0172d0ba806cd0945f645bbe98cda76152fc7d969226b611a4`. As released: LOB id 267; 6 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 4480, 2001-03-18, page 1308. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 68/2002 | 546 | 4572 | 2002-11-17 | 5513 | not online | — |
| 31/2008 | 928 | 4910 | 2008-11-01 | 2041 | 2008-06-01 **≠** | yes |
| 11/2010 | 1106 | 5034 | 2010-06-01 | 2983 | 2010-06-01 | yes |
| 2/2014 | 564 | 5268 | 2014-02-02 | 594 | not given | yes |
| 30/2017 | 4234 | 5479 | 2017-08-30 | 5383 | 2017-08-30 | yes |
| 12/2019 | 4362 | 5572 | 2019-08-28 | 2436 | 2019-05-01 **≠** | yes |

- **Version the corpus represents**: the version most corpus articles equal: «final (LOB 3235)» (16 articles; all versions: before 68/2002 (LOB 267) 3, before 31/2008 (LOB 1748) 3, before 11/2010 (LOB 1749) 3, before 2/2014 (LOB 1750) 3, before 30/2017 (LOB 1751) 4, before 12/2019 (LOB 3234) 13, final (LOB 3235) 16). Amending laws with changes missing from the corpus (articles): 12/2019: 15.
- **Counts** before → after the fixes: identical 3→4, normalisation-only 13→13, substantive difference 6→6, amendment not applied 1→0. Appendix: [courts-formation.md](2026-11-12-corpus-vs-official/courts-formation.md).
- **Registry** (`content/corpus/laws.json`) against LOB and the Gazette: amendment.gazette_date: registry None, LOB 2019-08-28, Gazette 2019-05-01.
- **Proposed fixes** (commit `fix(corpus): courts-formation: …`): 1 replace; registry: added 2019-05-01, the date the Official Gazette gives issue 5572, which lists law 12/2019 (LOB gives 2019-08-28 for that issue, which the Gazette contradicts).
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 4480, not online); each amending law's Gazette issue and page (1 of 6 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 6 articles whose words differ (appendix, scope `body`).

### قانون محاكم الصلح (`magistrates-courts`)

- **LOB**: قانون محاكم الصلح رقم 23 لسنة 2017, id 3179 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3179&LegislationType=2&isMod=false); retrieved 2026-11-12T20:06:56Z; SHA-256 of the record and articles `90fce519cea522f54fcfc2f69532476e7be975e5d8a07cae6f63b87bc9598cdb`, of the amending-law list `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`, of the per-article amendment list `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`. As released: LOB id 3179; 0 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 5474, 2017-08-01, page 4608. The Gazette's own [issue page](https://pm.gov.jo/Ar/Pages/NewsPaperDetails/5474) dates the issue 2017-08-01 and lists «* قانون رقم (23) لسنة 2017 - قانون محاكم الصلــــــــــــــح» (contents SHA-256 `090fd7e997c54eeed91b116ae7ff4f3ebcee4196966d678bdcdef673cd384f1e`).

- **Version the corpus represents**: the version most corpus articles equal: «final (LOB 3179)» (12 articles; all versions: final (LOB 3179) 12). No amendment LOB records is missing from the corpus text.
- **Counts** before → after the fixes: identical 1→1, normalisation-only 11→11, substantive difference 10→10. Appendix: [magistrates-courts.md](2026-11-12-corpus-vs-official/magistrates-courts.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): magistrates-courts: …`): .
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 5474, online); which reading is right for the 5 articles whose words differ (appendix, scope `body`).

### قانون محكمة الجنايات الكبرى (`major-felonies-court`)

- **LOB**: قانون محكمة الجنايات الكبرى رقم 19 لسنة 1986, id 3244 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3244&LegislationType=2&isMod=false); retrieved 2026-11-12T20:07:02Z; SHA-256 of the record and articles `93e13d07eb0a954398eac7bf13a2384e4bb5693258228bcfb35f203e74c306a8`, of the amending-law list `5378d02fd72b179d838d0af6d0376db756a366149fbc184abc7340e500aade89`, of the per-article amendment list `38b2200fa5c97c5e8f5a0976159306659aec165ab8290f0561ab9d0d3dd6cd84`. As released: LOB id 648; 2 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 3380, 1986-03-16, page 457. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 13/2010 | 491 | 5034 | 2010-06-01 | 3046 | 2010-06-01 | yes |
| 24/2017 | 4162 | 5474 | 2017-08-01 | 4620 | 2017-08-01 | yes |

- **Version the corpus represents**: the versions most corpus articles equal: «before 13/2010 (LOB 648)» and «before 24/2017 (LOB 2232)» (12 articles; all versions: before 13/2010 (LOB 648) 12, before 24/2017 (LOB 2232) 12, final (LOB 3244) 11). Amending laws with changes missing from the corpus (articles): 13/2010: 4; 24/2017: 4.
- **Counts** before → after the fixes: identical 1→2, normalisation-only 10→10, substantive difference 4→4, amendment not applied 1→0. Appendix: [major-felonies-court.md](2026-11-12-corpus-vs-official/major-felonies-court.md).
- **Registry**: number, year, Gazette issue and date, and the latest amendment agree with LOB.
- **Proposed fixes** (commit `fix(corpus): major-felonies-court: …`): 1 replace.
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 3380, not online); each amending law's Gazette issue and page (0 of 2 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 4 articles whose words differ (appendix, scope `body`).

### جدول رسوم المحاكم (`court-fees`)

- **LOB**: نظام رسوم المحاكم / صادر بمقتضى المادة (20) من قانون تشكيل المحاكم النظامية رقم (17) لسنة 2001 رقم 43 لسنة 2005, id 5081 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=5081&LegislationType=3&isMod=false); retrieved 2026-11-12T20:07:07Z; SHA-256 of the record and articles `2a7b7d1d0185b2e564efedeecbc9581ffa5087f593c63b5932074055db8b77b8`, of the amending-law list `c4989803a702f8aaad587735e1662b84b4ef71970449d8ca0774ac75534f230e`, of the per-article amendment list `c1551ccb9eebdaae138b976a0fbf4292408286bd6f82ed327b218a26e439b82d`. As released: LOB id 2635; 1 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 4711, 2005-06-16, page 2468. The Gazette's own [issue page](https://pm.gov.jo/Ar/Pages/NewsPaperDetails/4711) dates the issue 2005-06-16 and lists «* نظام رقم 43 لسنة 2005 - نظام رسوم المحاكم» (contents SHA-256 `4adce6b84a1a431a737e8f27d3be96a1477cda0342fece0f85c10d4065cbb430`).

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 108/2008 | 1820 | 4935 | 2008-11-02 | 5073 | 2008-11-02 | yes |

- **Version the corpus represents**: the version most corpus articles equal: «final (LOB 5081)» (1 articles; all versions: before 108/2008 (LOB 2635) 0, final (LOB 5081) 1). Amending laws with changes missing from the corpus (articles): 108/2008: 16.
- **Counts** before → after the fixes: identical 0→1, normalisation-only 1→1, substantive difference 50→50, amendment not applied 1→0. Appendix: [court-fees.md](2026-11-12-corpus-vs-official/court-fees.md).
- **Registry** (`content/corpus/laws.json`) against LOB and the Gazette: number: registry None, LOB 43; year: registry None, LOB 2005; gazette.issue: registry None, LOB 4711; gazette.date: registry None, LOB 2005-06-16, Gazette 2005-06-16; amendment.law: registry None, LOB 108; amendment.year: registry None, LOB 2008; amendment.gazette_issue: registry None, LOB 4935; amendment.gazette_date: registry None, LOB 2008-11-02, Gazette 2008-11-02.
- **Proposed fixes** (commit `fix(corpus): court-fees: …`): 1 replace; registry: regulation 43/2005, Gazette 4711 of 2005-06-16 (p. 2468 per LOB); amended by regulation 108/2008, Gazette 4935 of 2008-11-02 (p. 5073 per LOB).
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 4711, online); each amending law's Gazette issue and page (0 of 1 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 26 articles whose words differ (appendix, scope `body`).

### قانون نقابة المحامين النظاميين (`bar-association`)

- **LOB**: قانون نقابة المحامين النظاميين رقم 11 لسنة 1972, id 3258 — [record](https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=3258&LegislationType=2&isMod=false); retrieved 2026-11-12T20:07:12Z; SHA-256 of the record and articles `3f52e3bb5eed50e3b0e70e774d27c8e3d40873c4ddc33b5abafdb67dad95d53c`, of the amending-law list `68950a1ec2bb3a8292a5111d808b97874f440f79bd21ceccd9b53c0c959bdd1d`, of the per-article amendment list `180b7bd24356bc269f9be573bb7678139d787d7e213b3a61101a6b520d81c18b`. As released: LOB id 359; 5 intermediate versions read.
- **Gazette of the law (per LOB)**: issue 2357, 1972-01-01, page 666. The issue is not online on the Gazette's site.

| Amending law | LOB id | Gazette issue (LOB) | Date (LOB) | Page (LOB) | Gazette's own date | Listed in that issue |
|---|---|---|---|---|---|---|
| 32/1973 | 1034 | 2429 | — | 1234 | not online | — |
| 53/1976 | 1094 | 2655 | — | 2306 | not online | — |
| 51/1985 | 1035 | 3340 | — | 1327 | not online | — |
| 25/2014 | 577 | 5294 | 2014-07-16 | 4306 | 2014-07-16 | yes |
| 6/2019 | 4406 | 5561 | 2019-02-17 | 566 | 2019-02-17 | yes |

- **Version the corpus represents**: the versions most corpus articles equal: «before 6/2019 (LOB 1844)» and «final (LOB 3258)» (55 articles; all versions: before 32/1973 (LOB 359) 32, before 53/1976 (LOB 1841) 32, before 51/1985 (LOB 1842) 33, before 25/2014 (LOB 1843) 35, before 6/2019 (LOB 1844) 55, final (LOB 3258) 55). Amending laws with changes missing from the corpus (articles): 25/2014: 61.
- **Counts** before → after the fixes: identical 0→1, normalisation-only 55→55, substantive difference 54→54, amendment not applied 1→0. Appendix: [bar-association.md](2026-11-12-corpus-vs-official/bar-association.md).
- **Registry** (`content/corpus/laws.json`) against LOB and the Gazette: gazette.date: registry 1972-05-06, LOB 1972-01-01.
- **Proposed fixes** (commit `fix(corpus): bar-association: …`): 1 replace.
- **A named reviewer must confirm**: the Gazette issue, date and page of the law itself (issue 2357, not online); each amending law's Gazette issue and page (3 of 5 not online); each replaced or added article against the Gazette text of the law that made it; which reading is right for the 30 articles whose words differ (appendix, scope `body`).

### مجلة الأحكام العدلية (`majalla`)

- Not checked: LOB holds no record of the Majalla (a title search finds nothing), and its Ottoman-era publication is not in the Gazette's online archive. Its registry entry cites LOB only for the note on the Civil Code's precedence. A named reviewer must choose an official text before the Majalla can be checked.

## 6. The ten most serious differences

1. **Two articles added to the Criminal Procedure Law in 2017 are absent**
   Law 32/2017 (Gazette issue 5479, p. 5412, issue dated 2017-08-30) added the suspect's right to see the investigation file before questioning, under pain of nullity (63 مكرر), and the stay of a case pending another criminal case (140 مكرر). Added by the proposed fix.
   - criminal-procedure المادة 63 مكرر: absent from the corpus; LOB: «1- للمشتكى عليه أو محاميه الحق في ان يطلب خطيا قبل بدء الاستجواب الاطلاع على جميع أعمال التحقيق، ما عدا أقوال الشهود، تحت طائلة بطلان الاستجواب في حال رفض طلبه.  2- في الجنايات التي يبلغ  الحد الأدنى لعقوبتها عشر سنوات فأكثر، يتعين حضور محام مع المشتكى عليه في…»
   - criminal-procedure المادة 140 مكرر: absent from the corpus; LOB: «1- اذا كان الحكم في الدعوى يتوقف على نتيجة الفصل في دعوى جزائية أخرى جاز للمحكمة وبقرار مسبب وقف الأولى حتى يتم الفصل في الثانية.  2- اذا كان الحكم في الدعوى الجزائية يتوقف على الفصل في مسألة من مسائل الأحوال الشخصية جاز للمحكمة وبقرار مسبب أن توقف الدعوى وتحد…»

2. **Two articles added to the Execution Law in 2022 are absent**
   Law 9/2022 (issue 5796, p. 3583, 2022-05-25) added the lapse of an execution file left a year without a step (21 مكرر) and a transitional rule on imprisonment for debt (117 مكرر). Added by the proposed fix.
   - execution المادة 21 مكرر: absent from the corpus; LOB: «أ-  تترك حكما معاملة التنفيذ إذا انقضى عليها سنة ولم يتقدم المحكوم له أو الدائن أو ورثة أي منهما بطلب أي إجراء من إجراءات تنفيذها ويتخذ الرئيس قراراً بإلغاء الحبس أو منع السفر.  ب- يثابر على التنفيذ باستدعاء يقدم من أحد أطراف الدعوى التنفيذية ويتم تبليغ الطرف …»
   - execution المادة 117 مكرر: absent from the corpus; LOB: «تسري أحكام هذا القانون المعدل على المحكوم عليهم الذين صدرت بحقهم قرارات حبس تنفيذي قبل نفاذه وعلى رؤساء التنفيذ المباشرة بتطبيقه على القضايا قيد التنفيذ وإلغاء قرارات الحبس الصادرة قبل نفاذ أحكامه.…»

3. **Civil Procedure 191 lacks the 2024 widening of appeal to the Court of Cassation**
   The corpus has the 2024 wording except «غير القابلة للتقدير أو»: appeals in claims that cannot be valued. Law 6/2024, issue 5922, p. 1866, 2024-04-16. Replaced by the proposed fix.
   - civil-procedure المادة 191 : المدونة: …عن محاكم الاستيناف في الدعاوي «—» التي تزيد قيمتها علي عشرين… / LOB: …عن محاكم الاستيناف في الدعاوي «غير القابله للتقدير او» التي تزيد قيمتها علي عشرين…

4. **Penal Code: one added article absent and 18 articles older than their amendments**
   Amendments of 2011 to 2025 are missing (e.g. 27/2017 in issue 5479, which LOB records as «3082017»; 12/2025, issue 5996). Two more articles (409, 462) equal an earlier LOB version but LOB names no amending law, so they are left for the reviewer.
   - penal-code المادة 467 مكرر: absent from the corpus; LOB: «1- يعاقب بالحبس مدة لا تقل عن ثلاثة اشهر ولا تزيد على سنة كل من احدث شغبا او حرض على الكراهية بأي وسيلة كانت في المؤسسات التعليمية او المنشآت الرياضية او أي مكان آخر امتد اليه هذا الشغب.  2- تكون العقوبة مدة لا تقل عن ثلاثة اشهر ولا تزيد على ثلاث سنوات اذا اقت…»
   - penal-code المادة 308 مكرر: المدونة: … «مع مراعاه احكام الماده من هذا القانون» لا يجوز استعمال الاسباب المخففه… / LOB: … «—» لا يجوز استعمال الاسباب المخففه…
   - penal-code المادة 308 مكرر: المدونة: …الجريمه ذكرا كان او انثي «—» وكان الجاني قد اكمل الثامنه… / LOB: …الجريمه ذكرا كان او انثي «او كان ذا اعاقه» وكان الجاني قد اكمل الثامنه…
   - penal-code المادة 99 : المدونة: …الاعدام بالاشغال الموبده او بالاشغال «—» من خمس عشره سنه الي… / LOB: …الاعدام بالاشغال الموبده او بالاشغال «الموقته» من خمس عشره سنه الي…
   - penal-code المادة 99 : المدونة: …بالاشغال الموبده او بالاشغال من «خمس عشره سنه» الي خمس وعشرين سنه بدلا… / LOB: …بالاشغال الموبده او بالاشغال من «عشر سنين» الي خمس وعشرين سنه بدلا…

5. **Companies Law: 51 articles older than their amendments, up to 20/2023**
   E.g. the jurisdiction of the Administrative Court and the electronic publication of registrations, law 20/2023, issue 5874, p. 3627.
   - companies المادة 5 : المدونة: …من قراره الطعن فيه لدي «محكمه العدل العليا» خلال ثلاثين يوما من الاعلان… / LOB: …من قراره الطعن فيه لدي «المحكمه الاداريه» خلال ثلاثين يوما من الاعلان…
   - companies المادة 5 : المدونة: …في احدي الصحف اليوميه المحليه «انواع الشركات» … / LOB: …في احدي الصحف اليوميه المحليه «—» …
   - companies المادة 6 : المدونة: …شركه التضامن شركه التوصيه البسيطه «—» الشركه ذات المسووليه المحدوده شركه… / LOB: …شركه التضامن شركه التوصيه البسيطه «الشركات ذات المسووليهالمحدوده شركه راس المال المغامر» الشركه ذات المسووليه المحدوده شركه…
   - companies المادة 6 : المدونة: …اداره الاجتماعات من داخل المملكه «—» يصدر الوزير التعليمات اللازمه لتنفيذ… / LOB: …اداره الاجتماعات من داخل المملكه «علي المراقب ان يعلن علي الموقع الالكتروني للدايره عن تسجيل اي شركه وعن اي» يصدر الوزير التعليمات اللازمه لتنفيذ…

6. **Customs Law: 30 articles older than 33/2018 and 7/2025**
   E.g. the definition of post-clearance audit added by law 7/2025, issue 5991, p. 2251.
   - customs المادة 2 : المدونة: …بقرار ينشر في الجريده الرسميه «سريان هذا القانون» … / LOB: …بقرار ينشر في الجريده الرسميه «التدقيق اللاحق الاجراات التي تتخذها الدايره بعد الافراج عن البضاعه للتحقق من المخزون او» …

7. **Labour Law: 10 articles older than 10/2023**
   Law 10/2023, issue 5851, p. 1775: rules on non-Jordanian workers and on cumulative penalties.
   - labour المادة 12 : المدونة: …صرفها وفقا للتشريعات ذات العلاقه «—» في حال عدم التزام اصحاب… / LOB: …صرفها وفقا للتشريعات ذات العلاقه «يحدد بموجب نظام خاص مقدار الرسوم والمبالغ المشار اليها في الفقره من هذه الماده» في حال عدم التزام اصحاب…
   - labour المادة 12 : المدونة: …وزير التنميه الاجتماعيه لهذه الغايه «يعفي ابنا الاردنيات المتزوجات من غير الاردنيين المقيمون في المملكه من الحصول علي تصاريح» تعتبر مخالفه لاحكام هذا القانون… / LOB: …وزير التنميه الاجتماعيه لهذه الغايه «—» تعتبر مخالفه لاحكام هذا القانون…
   - labour المادة 11 : المدونة: …لا يجوز لغير مديريات التشغيل «العامه ومكاتب التشغيل الخاصه المرخصه القيام باعمال الوساطه لتشغيل» او تسهيل تشغيل العمال في… / LOB: …لا يجوز لغير مديريات التشغيل «في الوزاره والمكاتب والجهات والشركات المنصوص عليها في الفقرتين منها تشغيل» او تسهيل تشغيل العمال في…
   - labour المادة 11 : المدونة: …اي محل يستعمل لهذه الغايه «ومصادره موجوداته المتعلقه بغرض التشغيل استخدام العمال غير الاردنيين» … / LOB: …اي محل يستعمل لهذه الغايه «وتجمع العقوبات المحكوم بها اذا تعددت المخالفات» …

8. **Every library result says the text is current when it is not.**
   `citation.details` prints «آخر تعديل: القانون المعدِّل رقم X لسنة Y (الجريدة الرسمية: …)» from the registry under each quoted article. For the laws in items 1–7 the registry names an amendment the corpus text did not contain. The proposed fixes close the gap for the articles found; the variant readings in the appendices still need the reviewer.

9. **LOB's consolidated Evidence Law is out of step by one article from article 21**
   Law 22/2017 (issue 5474, p. 4604) replaced article 21 with «للخصم أن يطلب ضمن قائمة بيناته…»; LOB's consolidated text keeps the old article 21 and files the new text as 22, so every later LOB article is one number off (52 articles; LOB has 75, the corpus 74). The corpus numbering follows the amending law; no fix is proposed. LOB should be told.
   - evidence المادة 21: corpus «للخصم أن يطلب ضمن قائمة بيناته إلزام خصمه بتقديم أسناد أو أوراق منتجة في الدعوى تكون تحت يده على أن يبين في القائمة ما ي…» = LOB article 22; LOB article 21: «الفصل الرابع  في طلب الزام الخصم بتقديم الاسناد والاوراق الموجودة تحت يده  يجوز للخصم أن يطلب الزام خصمه بتقديم الاسناد …»
   - evidence المادة 22: corpus «إذا أثبت الطالب طلبه أو أقر الخصم بان السند أو الورقة في حوزته أو سكت قررت المحكمة لزوم تقديم السند أو الورقة في الحال أ…» = LOB article 23; LOB article 22: «للخصم ان يطلب ضمن قائمة بيناته إلزام خصمه بتقديم أسناد او أوراق منتجة في الدعوى تكون تحت يده على ان يبين في القائمة ما ي…»

10. **LOB's consolidated Companies Law lacks a whole chapter.**
   Law 4/2002 (issue 4533, p. 373, per LOB) added «الباب الخامس مكرر — الشركات المساهمة الخاصة»; LOB's consolidated text refers to its articles («المادة (82 مكرر)», «(273 مكرر)») but does not contain them. The corpus has 23 of them that LOB lacks entirely (66 مكرر to 88 مكرر, shown as "extra in corpus"; 65 مكرر and 89 مكرر have partial LOB counterparts); they cannot be checked against LOB, and 2002 issues are not online.

## 7. Proposed fixes (one commit per law)

Each replaced or added article takes **LOB's consolidated text** (its chapter headings dropped, its hard line wraps rejoined, nothing else changed) and cites the amending law's Gazette issue and page from LOB, with the Gazette's own issue date where the issue is online. These are corrections from the second source in authority; the Gazette check is the reviewer's. Commits that add articles also update `law-directory.md` (the counts ingest checks) and the total pinned in `services/legal-search/tests/test_prepare.py`. No change to `content/corpus/corrections.json` was needed: every fix is a text change, and that file is for re-labelling or splitting parsed articles.

| Law | Replaced | Added | Filled | Labels removed | Not changed | Registry |
|---|---|---|---|---|---|---|
| civil-procedure | 3 | 0 | 0 | 1 | 0 | — |
| civil-code | 0 | 0 | 1 | 0 | 0 | known_gaps |
| evidence | 1 | 0 | 0 | 0 | 0 | — |
| landlords-tenants | 2 | 0 | 0 | 0 | 0 | — |
| penal-code | 18 | 1 | 0 | 7 | 2 | law-directory.md: قانون-العقوبات-الأردني |
| maritime-commerce | 0 | 0 | 0 | 0 | 0 | amendment.gazette_issue |
| companies | 51 | 0 | 0 | 0 | 0 | — |
| customs | 30 | 0 | 0 | 0 | 0 | — |
| income-tax | 1 | 0 | 0 | 0 | 0 | — |
| sales-tax | 3 | 1 | 0 | 0 | 0 | law-directory.md: قانون-الضريبة-العامة-على-المبيعات |
| labour | 10 | 0 | 0 | 0 | 0 | — |
| execution | 0 | 2 | 0 | 0 | 0 | law-directory.md: قانون-التنفيذ |
| criminal-procedure | 9 | 2 | 0 | 3 | 0 | law-directory.md: قانون-أصول-المحاكمات-الجزائية |
| courts-formation | 1 | 0 | 0 | 0 | 0 | amendment.gazette_date |
| major-felonies-court | 1 | 0 | 0 | 0 | 0 | — |
| court-fees | 1 | 0 | 0 | 0 | 0 | note, gazette, amendment |
| bar-association | 1 | 0 | 0 | 0 | 0 | — |

Totals: 132 replaced, 6 added, 1 filled, 11 labels removed, 2 not changed for want of a citable amending law.

## 8. Registry metadata

- **court-fees** had no number, year, Gazette or amendment. LOB identifies the corpus as the schedule of «نظام رسوم المحاكم» رقم (43) لسنة 2005 (Gazette 4711, 2005-06-16, p. 2468; listed on the Gazette's issue page), amended by regulation 108/2008 (issue 4935, 2008-11-02, p. 5073). The fix adds these as a note, `gazette` and `amendment` (not as `number`/`year`, which would print «جدول رسوم المحاكم رقم 43 لسنة 2005», a number the schedule does not have).
- **courts-formation**: the amendment's Gazette date was missing. The Gazette dates issue 5572, which lists law 12/2019, 2019-05-01; LOB says 2019-08-28. The fix adds 2019-05-01 from the Gazette page.
- **maritime-commerce**: the amendment's Gazette issue was missing; LOB gives 3194 (p. 1951) for law 35/1983. Added from LOB; the issue is not online.
- **civil-code**: the known gap for article 1287 is removed with the text filled from LOB.
- **penal-code** (registry 1960-05-01), **criminal-procedure** (no date), **bar-association** (registry 1972-05-06): LOB gives 1 January of the year, which looks like a year-only placeholder (bar-association's issue 2357 is dated 1972-05-06 in LOB's maritime-commerce record). Not changed: only the Gazette, not online for these years, can settle them.
- **LOB errors the Gazette's own pages expose** (no registry value depends on them): penal 7/2018 (LOB 2018-03-01, Gazette 2018-02-01), penal 10/2022 (LOB 2022-06-02, Gazette 2022-05-25), courts-formation 31/2008 (LOB 2008-11-01, Gazette 2008-06-01), penal 27/2017 (LOB issue «3082017», Gazette issue 5479 lists it), sales-tax 26/2013 (LOB repeats 26/2012's issue 5167, which does not list it).

## 9. What could not be verified, and why

| What | Why |
|---|---|
| The Gazette **text** of every law and amendment | no text layer: the Gazette's document server gives guests page images only (`TextshotPage` 401, `FileDownload` 451); OCR was not used |
| The original Gazette issue of 15 laws (all before 2005) and their early amendments | Gazette issue not found online (the online archive starts between issues 4600 and 4709) |
| The Majalla | no official text found: not on LOB, not in the online Gazette |
| LOB's attached Gazette scan of the investment-fund law | the file URL (`/f/<id>`) answers 404 |
| Dates of the penal, criminal-procedure and bar-association laws | LOB gives a 1 January placeholder; Gazette issue not online |
| Gazette data of 22 amending laws without a date and 4 without a page in LOB | LOB leaves them empty; Gazette issue not online |
| Which reading is right where corpus and LOB differ in words (scope `body`) | needs the Gazette text; LOB has its own typos (e.g. civil-procedure 5 «يحب», 214 «العش») and the Bar Association copy sides with the corpus in 29 of 65 civil-procedure differences, with LOB in 10 |
| Two penal articles (409, 462) equal to an earlier LOB version | LOB names no amending law for them, so no Gazette issue to cite; not changed |

Amending laws whose Gazette issue is not online (the reviewer needs the printed Gazette or the Gazette's archive for them): bar-association 32/1973 (issue 2429); bar-association 53/1976 (issue 2655); bar-association 51/1985 (issue 3340); civil-procedure 14/2001 (issue 4480); civil-procedure 26/2002 (issue 4547); companies 4/2002 (issue 4533); companies 40/2002 (issue 4556); companies 74/2002 (issue 4577); companies 17/2003 (issue 4589); courts-formation 68/2002 (issue 4572); criminal-procedure 75/1966 (issue 1948); criminal-procedure 39/1968 (issue 2089); criminal-procedure 26/1970 (issue 2268); criminal-procedure 16/1991 (issue 3775); criminal-procedure 16/2001 (issue 4480); criminal-procedure 76/2003 (issue 4606); customs 10/1999 (issue 4338); customs 16/2000 (issue 4423); customs 27/2000 (issue 4443); evidence 24/1961 (issue 1563); evidence 37/2001 (issue 4501); labour 12/1997 (issue 4192); labour 12/1998 (issue 4304); labour 11/1999 (issue 4338); labour 56/2001 (issue 4511); labour 51/2002 (issue 4561); labour 60/2002 (issue 4567); labour 11/2004 (issue 4658); landlords-tenants 30/2000 (issue 4453); maritime-commerce 4/1978 (issue 2758); maritime-commerce 35/1983 (issue 3194); penal-code 11/1996 (issue None); penal-code 16/1960 (issue None); penal-code 24/1962 (issue 1627); penal-code 40/1963 (issue 1727); penal-code 39/1963 (issue 1727); penal-code 29/1965 (issue 1859); penal-code 42/1965 (issue 1876); penal-code 1/1966 (issue 1895); penal-code 7/1966 (issue 1902); penal-code 15/1971 (issue 2291); penal-code 40/1971 (issue 2305); penal-code 9/1988 (issue 3533); penal-code 15/1991 (issue 3775); penal-code 54/2001 (issue 4510); penal-code 86/2001 (issue 4524); penal-code 33/2002 (issue 4553); penal-code 45/2003 (issue 4600); sales-tax 15/1995 (issue 4027); sales-tax 24/1999 (issue 4364); sales-tax 18/2000 (issue 4423); sales-tax 36/2000 (issue 4457); sales-tax 25/2002 (issue 4547); sales-tax 23/2003 (issue 4592); sales-tax 5/2004 (issue 4651); sales-tax 32/2004 (issue 4672).

## 10. Other observations for the owner

- **Corpus structure** (no fix proposed; formatting, but the product quotes it): in commerce, maritime-commerce, companies, customs, income-tax, sales-tax, labour, investment-fund, execution and landlords-tenants each article is one line and ends with the **next** article's title (scope `trailing-title`, 1,000+ articles); in civil-code and others, chapter headings sit in a different article than LOB puts them; many articles drop paragraph numbers («1.», «أ-»), which matters when an answer cites «الفقرة (2)».
- **Derived index files** (`article-index.json`, `shard-map.json`, `statistics.json`, `topic-index.json`) were not rebuilt; no product code reads them, but they no longer match the shards for the added articles.
- **Third reading for civil procedure**: the Bar Association copy agrees with the corpus on 29 differences, with LOB on 10, with both on 5 and with neither on 19 (per article in the appendix).

