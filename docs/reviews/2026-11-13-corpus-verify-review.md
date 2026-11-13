> Copied from the local main session's records on 2026-11-13 for cloud agents. Paths under `.hq/` or `D:/Iqraa Law/` point to local evidence that is not in this repository; the findings themselves are complete here.

# Review of the corpus verification branch (LOB and Official Gazette), 2026-11-13

- **Branch:** `ahmadtech26/ai-harness` `verify/corpus-gazette-2026-11`, head `d267007`, base `49ad460`
  (`demo-fixes-2026-11-11`, the corpus the live demo library was ingested from). Reviewed read-only from the worktrees
  `D:/Iqraa Law/AI Harness-verify` (head) and `D:/Iqraa Law/AI Harness-demo` (base; its HEAD file names `49ad460`).
- **Written by:** a cloud agent. It compared the 22-law corpus (`jordanian-law/references/القوانين-الأردنية/`, registry
  `content/corpus/laws.json`) with the Legislation and Opinion Bureau (LOB, lob.gov.jo) and the Official Gazette
  (pm.gov.jo), and committed per-law text changes, registry metadata, one test change
  (`services/legal-search/tests/test_prepare.py`), the report `docs/verification/2026-11-12-corpus-vs-official.md` with
  per-law appendices, and `docs/verification/2026-11-12-corpus-diff.jsonl`.
- **Reviews merged here (six lenses):** companies; customs and penal code; labour, criminal procedure, civil procedure
  and execution; the ten smaller laws (sales tax, landlords-tenants, civil code, evidence, income tax, major felonies,
  courts formation, court fees, bar association, maritime); technical impact (ingest, retrieval, replay); method. None
  ran git, touched a container or the live database, or edited a worktree. Their notes and scripts are listed in the
  appendix. This synthesis re-checked 21 of the key findings directly in both trees and the jsonl (marked "re-checked").
- **Standing rule:** law text never changes without the owner's word, and the lawyer reviews legal content (D16, D17).
  Each changed article must be the official current text, in force, correctly numbered, free of OCR, diacritic or typing
  damage, and no article may be silently removed.
- **Status of everything below:** findings and proposals. The owner decides. Nothing here is applied.

Abbreviations: **V** = `D:/Iqraa Law/AI Harness-verify/jordanian-law/references/القوانين-الأردنية/`; **Bt** = the same
path under `AI Harness-demo`; **J** = `docs/verification/2026-11-12-corpus-diff.jsonl` in the verify tree (each row holds
the corpus text, the LOB text the branch captured, and LOB's amendment data); **S** =
`D:/Iqraa Law/.hq/scratch/corpus-verify-review/`.

## Bottom line

**Do not merge or ingest the corpus commits.** None of the 150 changed or added articles could be checked against an
independently fetched official text: LOB's data API answered HTTP 403 behind a WAF and needs encrypted requests, its
web page is an empty application shell to WebFetch, the browser tool is blocked for lob.gov.jo, and a scripted retry
was refused as bot-check circumvention. The Gazette serves guests page images only, and issues before 2005 are not
online. So **0 of 150 are verified**. The only comparison possible for most articles was with the LOB text the branch
itself recorded, and equality with the branch's own capture is not verification.

Where other evidence could be reached, it found real damage:

1. **Five regressions to older law,** where the corpus was newer than LOB's consolidated text and the branch overwrote
   it: landlords-tenants 5 and 7 (back to 22/2011; Gazette issue 5253 lists the in-force 14/2013), labour 137 (back to
   the pre-2019 text; the Constitutional Court quotes the 14/2019 wording), penal code 99 and 306 (back to text that
   27/2017 replaced). Customs 161 is a probable sixth.
2. **Operative text deleted:** customs 168 (the article was replaced by the amending law's instructions, «أولا: بإلغاء
   كلمة…»; paragraphs (أ)1-3 and (ب)1-3 are gone), companies 248 (its opening «تتمتع الشركة الأجنبية غير العاملة بما
   يلي» is gone), sales tax 21 (its lead-in «(أ) يعفى من الضريبة» is gone).
3. **Meaning changed outside the amended words:** customs 199(ع) now says the opposite («في غير الأماكن» became «في
   الأماكن»), customs 192 «التهريب» became «التهرب».
4. **Six duplicated «مكرر» articles:** penal 467, criminal procedure 63 and 140, execution 21 and 117, sales tax 4. Each
   new row repeats text still inside its parent article, and at three of them the marker that FR Task 4.1 would split at
   was deleted.
5. **A LOB web link written into the law:** customs 14 now ends with a `GetAttachment` URL, which also becomes customs
   15's search heading.
6. **Typing damage imported:** 70 of the 150 are shown wrong or visibly damaged. LOB typing damage alone (typos over
   correct base wording, glued words, stray «0» and «?») touches about 40 articles; LOB sub-chapter headings are glued
   into 10 article bodies; invisible characters (NBSP, ZWNJ, tatweel) arrive in 75 more.
7. **Amendments missed:** companies 88, 192, 217, 218 and 279 still carry pre-2023 text, and 24 companies «مكرر»
   articles were never compared because the splitter missed LOB's «المادة (N): مكرر» labels.

The cause is the method, not copying errors: whole-article replacement with LOB's consolidated text, plus an amendment
detector that treats LOB as the ceiling and fires on spelling variants, on headings, and on words an amending law
quotes in order to delete them. The detection half is sound and reproduces exactly; the report, the jsonl and the
appendices are useful evidence once their false claims are corrected (section 4).

On the next ingest from the main checkout, merging this branch would rewrite 143 rows and add 7 in the live library.
That ingest would also drop 96 search headings, and no rollback restores the library (section 3).

**Verdicts (section 1):** reject 4 laws' changes (landlords-tenants, execution, courts formation, court fees text);
fix first for 10; adopt after lawyer sign-off for 2 (civil code 1287, major felonies 4) plus the maritime registry
value. Five laws have no change. No law qualifies for "adopt now".

## 1. Verdict per law

**The three counts, applied the same way to every law:**

- **Verified:** equals an official text fetched independently in this review (LOB live, the Gazette, or another
  government source). **0 of 150.** Income tax 34 is the only article compared with an official non-LOB text (the
  government portal's consolidated law); three of its four paragraphs match, one carries a stray word, so it counts as
  "differ".
- **Differ:** shown wrong by evidence. That covers: contradicted by an official or independent source (Gazette issue
  listings, the Constitutional Court, WIPO's consolidation, the Bar Association copy, the government portal);
  different from the branch's own recorded LOB text by lost text; or visibly damaged by the branch (lost, duplicated or
  reversed text, a URL, glued headings, glued words, LOB typos over correct base wording, stray characters).
  Invisible characters (NBSP, ZWNJ, tatweel) and hamza-less spelling are not counted per article; they are a
  cross-cutting fix (error A43) and an owner decision (section 6, decision 3).
- **Unverified:** none of the above. Most of these equal the branch's capture of LOB, which is not verification.

**Reconciling the numbers the owner has seen.** The brief and the report speak of 134 "amendment not applied" rows and
132 articles brought up to date. Two rows were left unfixed (penal 409 and 462). The technical lens counts 143 rows with
changed text and 7 added. The method lens counts 132 replaced, 7 added and 11 rows that only lose the web label «نص
المادة مكرر»: 132 + 11 = 143, and 143 + 7 = **150**. The 11 label-only rows are penal 153, 308, 334, 345, 348, 405
and 467, criminal procedure 63, 140 and 242, and civil procedure 222. Eight are benign. Three are not (criminal procedure
63 and 140, penal 467), because those markers delimit «مكرر» text merged into the parent article (error rows A12, A20,
A21). The 7 additions are civil code 1287 (an empty article filled) and six «مكرر» rows.

**Cross-cutting rules that apply to every law below:**

- **«مكرر» rows:** every added «مكرر» row (penal 467, criminal procedure 63 and 140, execution 21 and 117, sales tax 4)
  is rejected as built. Redo only through FR Task 4.1's marker split (O-42), which cuts at the marker and never alters
  the text, after the lawyer's samples and the owner's go. Restore the three deleted markers first.
- **Passage-only edits:** where an amendment is confirmed, change only the amended passage; keep the base wording
  elsewhere unless the Gazette shows it is wrong.
- **Artifact pass:** strip NBSP, ZWNJ, tatweel and doubled tanween; never copy LOB headings, captions, attachment notes or
  URLs into article text.

| # | Law (slug) | Verdict | Changed | Verified | Differ | Unverified | What must happen |
|---|---|---|---|---|---|---|---|
| 1 | companies | **Fix first** | 51 replaced | 0 | 17 | 34 | Restore 248's opening sentence; restore the dropped Part V / V-bis headings; reject the LOB typos and glued words in 5, 6, 7, 11, 14, 59, 94, 97, 98, 135, 226, 254, 266, 283; bring 88, 192, 217, 218, 279 up to 20/2023 or say why not; compare the 24 «مكرر» articles after fixing the splitter; then the lawyer checks every article against Gazette 5874 (20/2023) and 4556 (40/2002, offline). |
| 2 | customs | **Fix first** | 30 replaced | 0 | 12 | 18 | Restore base 168 and 14; hold 161 until the texts of 37/2010 and 16/2000 are read; in 2, 192, 199, 206, 245 keep only the amended passage; fix glued words in 20, 21, 31, 64; then the lawyer (7/2025 Gazette 5991, 33/2018 Gazette 5520). |
| 3 | penal-code | **Fix first** | 18 replaced, 7 label-only, 1 added | 0 | 14 | 12 | Restore base 99 and 306; reject 467 مكرر as built and restore 467's marker; strip LOB sub-headings from 25, 72, 80, 185, 228, 287; revert the no-amendment cosmetic replacements (102, 300, 422); fix 126's citation and 475's date; then the lawyer against 27/2017 (Gazette 5479). |
| 4 | labour | **Fix first** | 10 replaced | 0 | 5 | 5 | Restore base 137 (the 14/2019 text); fix LOB typos in 10, 29, 46, 69; then the lawyer checks the 10/2023 set (10, 11, 12, 29, 30, 46, 69, 139) against Gazette 5851. LOB's labour consolidation is stale in places (98, 99, 107-109, 116, 137). |
| 5 | criminal-procedure | **Fix first** | 9 replaced, 3 label-only, 2 added | 0 | 10 | 4 | Reject 63 مكرر and 140 مكرر as built and restore their markers; remove the glued headings from 68, 338, 341, 364 (68 and 341 then have no change left); fix typos in 14, 364, 365; then the lawyer. 242 is clean. |
| 6 | civil-procedure | **Fix first** | 3 replaced, 1 label-only | 0 | 2 | 2 | Restore base 182 and 193 until the Gazette texts of 31/2017 and 14/2023 are read (the report's own Bar Association reading agrees with base); 191 (6/2024) and 222 (clean) go to the lawyer. |
| 7 | sales-tax | **Fix first** | 3 replaced, 1 added | 0 | 3 | 1 | Restore base 21; in 2 keep only the corrected «توريد السلعة» definition, with the added definitions under أ and «الاقرار الضريبي» spelt right; reject 4 مكرر as built (article 4 already holds it); the lawyer settles which law added «لأغراض شخصية أو» to 9. |
| 8 | landlords-tenants | **Reject** | 2 replaced | 0 | 2 | 0 | Both changes restore superseded 22/2011 text over the in-force 14/2013 text. Keep base. Separately, the registry's "latest amendment 22/2011" is stale (error B4). |
| 9 | execution | **Reject** | 2 added | 0 | 2 | 0 | Both «مكرر» rows duplicate text still inline in 21 and 117. Redo through FR Task 4.1, with the amending law recorded. |
| 10 | civil-code | **Adopt after lawyer sign-off** | 1 filled (1287) | 0 | 0 | 1 | Lawyer checks 1287 against Gazette 2645 (1976, offline). Keep `known_gaps` until then; update the two full-law files in the same change. |
| 11 | evidence | **Fix first** (small) | 1 replaced | 0 | 0 | 1 | Take only the «إثباتهما» → «إثبات ما» correction, keep the base hamza spelling, drop the 16/2005 attribution; then the lawyer. |
| 12 | income-tax | **Fix first** (small) | 1 replaced | 0 | 1 | 0 | Remove the stray «أو» in 34(ج) and the tatweel; the rest matches the government portal's 38/2018 text. Then the lawyer. |
| 13 | major-felonies-court | **Adopt after lawyer sign-off** | 1 replaced | 0 | 0 | 1 | Lawyer confirms against Gazette 5474 that 24/2017 put paragraph ج into article 4 (it reads like the amending law's own transitional article). |
| 14 | courts-formation | **Reject** (text); registry date: adopt after lawyer sign-off | 1 replaced | 0 | 0 | 1 | 15 changes only «ألا» to «أن لا» and hamzas; the base already had the 12/2019 text. The registry date 2019-05-01 for issue 5572 is right on the Gazette's numbering. |
| 15 | court-fees | **Reject** (text); registry: fix first | 1 replaced | 0 | 1 | 0 | 16 has no amendment content and imports «المهاياة» and a trailing «0». The registry values are sourced, but the footer would call regulation 108/2008 «القانون المعدِّل» (error C2). |
| 16 | bar-association | **Fix first** (small) | 1 replaced | 0 | 1 | 0 | Keep base and correct only «المتفرغة» to «المتفرعة»; the lawyer checks whether 25/2014 (Gazette 5294) changed 61. |
| 17 | maritime-commerce | **Adopt after lawyer sign-off** (registry only) | 0 | – | – | – | The new `gazette_issue` 3194 for 35/1983 comes from LOB only (issue not online). The report's "no amendment missing" is an empty result: 0 of 386 articles match any LOB version, so the rule could not fire. |
| 18 | commerce | No change on the branch | 0 | – | – | – | "No amendment missing" is an empty result (0 of 480 articles match any LOB version). LOB's amendment list for it is empty (`sha256("[]")`), taken as "no amendments" without a cross-check. Not a clean bill. |
| 19 | investment-fund | No change on the branch | 0 | – | – | – | Same empty-result caveat as commerce. |
| 20 | magistrates-courts | No change on the branch | 0 | – | – | – | LOB's amendment list is empty (`sha256("[]")`), taken as "no amendments" without a cross-check. |
| 21 | mediation | No change on the branch | 0 | – | – | – | Nothing to adopt. |
| 22 | majalla | No change on the branch | 0 | – | – | – | Nothing to adopt. |
| | **Total** | | **150** | **0** | **70** | **80** | |

## 2. Errors found

**Counting rule.** One row is one kind of defect in one law; a row may cover several articles. Questions for the lawyer
(2E) and things that passed (2F) are not counted. **63 errors:** 43 text defects introduced by the branch (2A), 4
amendments missed or left stale (2B), 7 registry, derived-file, test and retrieval defects (2C), 9 errors in the
report and method (2D). Severity: C critical, H high, M medium, L low.

### 2A. Text defects introduced by the branch (43)

| # | Sev | Law | Article | What | Evidence |
|---|---|---|---|---|---|
| A1 | C | customs | 168 | The consolidated article was replaced by the amending law's instructions (33/2018): «أولا: بإلغاء كلمة (العقوبات) الواردة في مطلع الفقرة (أ) منها… ثانيا: بإلغاء عبارة (لا تزيد عن ستة أشهر)… ثالثا… رابعا…». Paragraph (أ) items 1-3 (التنبيه، الإنذار، الوقف عن العمل) and paragraph (ب) items 1-3 are gone. The base already had all four 2018 changes applied. In effect an article removed. | V`قانون-الجمارك/sections/04-المواد-165-198.md`; re-checked: base 1,185 characters opening «أ. للمدير ان يفرض على المخلص الجمركي احدى الجزاءات المسلكية», head 856 characters opening «أولا: بإلغاء كلمة». J line 3309 (official_text is the amending instructions; triggered by «ثانيا بالغا عباره لا تزيد»). S`customs-penal/customs_compare.txt`. |
| A2 | H | customs | 14 (and 15's heading) | A LOB caption and encrypted attachment link were written into the statute: «قرار مجلس الوزراء بالموافقة على تخفيض رسوم الجمركية https://lob.gov.jo/OPSHandler/OPS_Auth.asmx/GetAttachment?FileName=U2FsdGVkX19F5D8wgLCYHjNQe4Cb%2BsHUlhG6X6JBDIo%3D&IsThumb=false». No 33/2018 wording was applied; the 21 extra words caused the "amendment not applied" class. Under `headings.extract` it also becomes customs 15's keyword heading. | Re-checked: `GetAttachment` occurs only in V`قانون-الجمارك/sections/00-المواد-1-29.md`, never in Bt. J line 3155. S`technical-impact/parse-recall-src.json` (15's heading). |
| A3 | H | customs | 161 | Probable regression. The base fees (2 per mille, minimum 50, maximum 500 JD; 50 JD per transit or re-export declaration; 30 JD per export; 7 JD per passenger) became lower amounts (minimum 10, maximum 250; 20; 15; 3). The branch cites 16/2000 although LOB lists 37/2010 as a later amender, the same pattern as the confirmed penal 306 regression. Grammar error imported: «الذين» → «اللذين». Not confirmed: Gazette 4423 (16/2000) is offline. | V`قانون-الجمارك/sections/03-المواد-128-164.md`; J line 3302 (by_law 16/2000; LOB lists 16/2000, 37/2010). |
| A4 | H | customs | 199 | Changes outside the 7/2025 amendment (which concerns (ص)): (ع) «أو تفريغها في غير الأماكن المخصصة لذلك» became «في الاماكن المخصصة لذلك», reversing the offence; (ب) «البيان المخالف الذي» lost «المخالف»; (و) «تعهدات» became «تعهدت». | Re-checked in V`قانون-الجمارك/sections/05-المواد-199-231.md` (base «تفريغها في غير الاماكن المخصصة لذلك», head «تفريغها في الاماكن المخصصة لذلك»). J line 3340. |
| A5 | H | customs | 192 | Besides the 33/2018 change («المدعي العام» → «مدعي عام الجمارك»), (أ)1 «جرم التهريب المشهود» became «جرم التهرب المشهود»: evasion instead of smuggling, outside the amended phrase. | Re-checked in V`قانون-الجمارك/sections/04-المواد-165-198.md`. J line 3333. |
| A6 | M | customs | 2 | Paragraph rejoining merged separate definitions into one run («المدير : مدير عام الدائرة التعريفة - التعريفة الجمركية : … الحرم الجمركي : …»); the new 7/2025 definition «التدقيق اللاحق» is glued to the end of «الطرق المعينة». LOB has them on separate lines. Served to demo guests. | V`قانون-الجمارك/sections/00-المواد-1-29.md`; J line 3143. |
| A7 | M | customs | 245 | Apart from the 7/2025 changes, «قانون تحصيل الأموال العامة» became «قانون تحصيل الأموال الأميرية» and «المتوجبة» became «المفروضة», neither covered by the amendment's wording (probably stale LOB text); glued «الااذا». | V`قانون-الجمارك/sections/06-المواد-232-254.md`; J line 3386. |
| A8 | M | customs | 206 | The opening clause is written twice («…بما يلي:- يعاقب على التهريب… بما يلي :-»). | J line 3347; S`customs-penal/customs_compare.txt`. |
| A9 | L | customs | 20, 21, 31, 64 | Glued or stray words from LOB: «أوالتي» (20), «أيهما أعلى و وفق» (21), «أوالكترونيا» (31), «أوأكثر» (64). | S`customs-penal/customs_compare.txt`; S`technical-impact/changed-articles.md`. |
| A10 | H | penal-code | 99 | Paragraph 1 was put back to the pre-2017 range «بالأشغال المؤقتة من عشر سنين الى عشرين سنة». The base (current) reads «من خمس عشرة سنة إلى خمس وعشرين سنة». The unofficial copy of 27/2017 says «ثانيا: بإلغاء عبارة (المؤقتة من عشر سنين إلى عشرين سنة)… والاستعاضة عنها بعبارة (من خمس عشرة سنة إلى خمس وعشرين سنة)». The detector's "missing words" «عشر سنين» are the words 27/2017 quotes in order to delete them. LOB's own consolidation looks stale. | Re-checked: base «خمس عشرة سنة» ×3 and «عشر سنين» ×0; head «عشر سنين» ×1. V`قانون-العقوبات-الأردني/sections/01-المواد-49-119.md`; J line 1573. Bar Association PDF https://www.jba.org.jo/ebv4.0/root_storage/ar/eb_list_page/تعديلات_قانون_العقوبات_2017.pdf (SHA-256 56841acf…a642167; unofficial). |
| A11 | H | penal-code | 306 | The 2017 sexual-harassment text («يعاقب بالحبس مدة لا تقل عن ستة أشهر… 2- شخص ذكر كان أو أنثى أكمل الثامنة عشرة… دون رضا») was replaced by the 2011 text («من عرض على شخص لم يكمل الثامنة عشرة… أو على أنثى مهما بلغ عمرها… بالحبس مدة لا تتجاوز ستة أشهر أو بغرامة»). The minimum becomes a maximum and adults of either sex lose protection. The branch cites 8/2011 although LOB lists 27/2017 later. | Re-checked: base «لا تقل عن ستة أشهر»; head «لا تتجاوز ستة أشهر», «أنثى مهما». V`…/sections/05-المواد-273-325.md`; J line 1781; JBA PDF above; Gazette 5479 lists 27/2017. |
| A12 | H | penal-code | 467 / 467 مكرر | The marker «نص المادة مكرر» was removed from 467 but the riot/hate paragraphs («1- يعاقب بالحبس مدة لا تقل عن ثلاثة اشهر… كل من احدث شغبا…») were left inside 467, then added again as a new 467 مكرر. The text appears twice and 467 answers with another article's provision. The report's "absent from the corpus" is wrong: the text was present, merged. The new row cites the 1960 law (Gazette 1487); the unofficial copy shows 27/2017 (Gazette 5479) added it. | Re-checked: «احدث شغبا» ×1 in base, ×2 in head; head headings «### المادة 467 — إقلاق الراحة» and «### المادة 467 مكرر» in V`…/sections/09-المواد-444-476.md`. J lines 1951, 1961. |
| A13 | M | penal-code | 25 | Article 25 now ends with «5- بدائل العقوبات السالبة للحرية:-», which is 25 مكرر's heading, the very trailing-title defect the report criticises. The amendments LOB lists for 25 (27/2017, 10/2022, 12/2025) belong to 25 مكرر, which already matched LOB. | V`…/sections/00-المواد-1-48.md`; J line 1496. |
| A14 | M | penal-code | 72, 80, 185, 228, 287 | LOB's numbered sub-chapter headings were glued into article text, against the report's §7 ("headings dropped, nothing else changed"): 72 «(2) اجتماع العقوبات», 80 «(2) المحرض والمتدخل», 185 «(1) مقاومة الموظفين», 228 «(2) فرار مراكز الاصلاح والتأهيل» (title still «فرار السجناء»), 287 «3- الجرائم المتعلقة بالقُصّر والعُجّز .». In 72 item (أ) is merged into item 1 and a stray «فللمحكمة: .» was imported; 72 still carries «(النص بعد تعديل 2022)» over text presented as post-12/2025. | V sections 01, 03, 04, 05 of the penal code; S`customs-penal/penal_compare.txt`; S`method/edits.txt`. |
| A15 | M | penal-code | 126 | The repealed text was replaced by LOB's repeal note «الغيت بمقتضى المادة (17) من قانون حماية اسرار وئائق الدولة رقم (50) لسنة 1971…», but the citation is 29/1965 (issue 1859), not the repealing 50/1971 (issue 2315). Typo «وئائق» for «وثائق». | V`…/sections/02-المواد-120-153.md`; J line 1600. |
| A16 | M | penal-code | 475 | In the list of repealed laws, Palestine Gazette No. 652's date changed from 14/12/1936 to 12/12/1936 and «التشريع» to «التشاريع», on LOB's reading, cited to 9/2014, which changes nothing visible here. Glued «1944المنشور», «1380من». | V`…/sections/09-المواد-444-476.md`; J line 1959; S`method/artifacts.py` output. |
| A17 | L | penal-code | 80, 185, 287, 407, 422 | Imported typos and glued or split words: «مختبأ» → «مخبأ» (80), «إ ذا» (185), «امرأة» → «إمرأة» (287), «أشهرالى» (407), «والاعاده» → «و الاعاده» (422). Hamza also dropped across 80, 185, 208, 228, 407, 422. | S`customs-penal/penal_compare.txt`; S`method/edits.txt`. |
| A18 | H | labour | 137 | Back to the pre-2019 text. The base (the 14/2019 text: أ wage claims; ب procedure; ج appeal within 10 days, decided within 30; د/1 fee exemption; د/2 no exemption after repeated renewal) was replaced by LOB's 2004-era consolidation ending «د- تستمر محكمة البداية بالنظر في الدعاوى العمالية المنظورة أمامها قبل نفاذ هذا القانون», 11/2004's transitional clause. LOB's amendment list for 137 names only 11/2004, so LOB missed 14/2019. Doubled tanween «وجاهياًً», «يوماًً». | Re-checked: base 1,916 characters with «تجديد الدعوى»; head 690 characters with «تستمر محكمة البداية» and «وجاهياًً». V`قانون-العمل/sections/03-المواد-118-142.md`. Constitutional Court, session 2021-08-17: «وتنص الفقرة (ج) من المادة (137) من قانون العمل المعدل بالقانون رقم 14 لسنة 2019» (https://www.cco.gov.jo/Ar/NewsDetails/المحكمة_الدستورية_ترد_الطعن_بعدم_دستورية_الفقرة__ج__من_المادة_137_بقانون_العمل). WIPO Lex JO089 consolidation to 14/2019 (https://www.wipo.int/wipolex/ar/legislation/details/20568, PDF SHA-256 fe85fada…afbe588) equals the base word for word. |
| A19 | L | labour | 10, 29, 46, 69 | LOB typing damage over correct base text: 10 a stray «)» after «وخارجها.»; 29 «بغرامه»; 46 «الأ في الحالات» for the base's correct «إلا»; 69 «آمنه». | V`قانون-العمل/sections/00-…` and `01-…`; S`law-text-labour-crimproc-civproc-exec/changes.json`. |
| A20 | H | criminal-procedure | 63 / 63 مكرر | The marker «نص المادة مكرر» was deleted, the right-to-counsel paragraphs 1-5 stayed inside 63, and a separate 63 مكرر repeats them. 63 now reads as one continuous article. No amending law is recorded for 63 مكرر (page field = Gazette 1539, 1961; probably 32/2017). | Re-checked: head 63 contains «قبل بدء الاستجواب الاطلاع» and no marker; base had the marker. V`قانون-أصول-المحاكمات-الجزائية/sections/01-المواد-44-113.md` lines 139 and 152. |
| A21 | H | criminal-procedure | 140 / 140 مكرر | Same defect: the stay-of-proceedings paragraphs stay unlabeled inside 140 (court competence) and are repeated as 140 مكرر, with no amending law recorded. Served to demo guests; replay call 1342 «أسباب وقف الدعوى» now ranks [140 مكرر, 140, 256]. | Re-checked: head 140 contains «يتوقف على نتيجة الفصل في دعوى جزائية», marker gone. V`…/sections/03-المواد-136-165.md` lines 61 and 72. |
| A22 | M | criminal-procedure | 68, 338, 341, 364 | LOB sub-chapter headings glued into article bodies: 68 «2- سماع الشهود على المدعي العام ان يدعو…» (opens as if paragraph 2), 338 «1- سقوط الدعوى بالتقادم» then «1- تسقط…», 341 «2- سقوط العقوبة بالتقادم» before paragraph 1, 364 «3- اعادة الاعتبار». For 68 and 341 the heading is the only change: the detector took heading words for amendment words. | V`…/sections/01-…` and `08-المواد-331-370.md`; J notes for 68, 338, 341, 364. |
| A23 | M | criminal-procedure | 364, 365 | LOB typos and wording changes beside two real repairs (364 «وإذاحكم»; 365 «الطلأبكم» → «الطلب مع», paragraph numbers restored): 364 «الخيانه», «بحقة», «بالغرامه», «استعيض عنها» → «عنه», «اصدرت حكمها» → «حكما» (base and the full-law file read «حكمها»); 365 «يتقدم المدعي العام الطلب» (ungrammatical; base «يقدم»), «تجديدة» ×2, «لاتزيد», «مايلي», «لايتولى». | V`…/sections/08-المواد-331-370.md`; S`law-text-labour-crimproc-civproc-exec/changes.json`. |
| A24 | L | criminal-procedure | 14 | The «بدائية» → «بداية» change brought in «دائرةاختصاصه» (glued) over the base's correct «دائرة اختصاصه». | V`…/sections/00-المواد-1-43.md`. |
| A25 | H | civil-procedure | 182 | «محاكم الصلح ومحاكم» inserted into paragraph 2 («في الأحكام الصادرة عن محاكم الصلح ومحاكم البداية… التي تزيد قيمتها على ثلاثين الف دينار»), which changes which judgments the Court of Appeal hears in full. Credited to 14/2001, the earliest of four amenders (14/2001, 16/2006, 31/2017, 14/2023). The report's own Bar Association reading (2023) agrees with the base, and magistrates' judgments over 30,000 JD look inconsistent with that court's jurisdiction. | V`قانون-أصول-المحاكمات-المدنية/sections/05-المواد-169-224.md`; `docs/verification/2026-11-12-corpus-vs-official/civil-procedure.md` §المادة 182 («third reading… → corpus»). |
| A26 | M | civil-procedure | 193 | «مطبوعة وبصورة» inserted into item 5, credited to 14/2001 although 16/2006 and 31/2017 amended the article later; the Bar Association reading agrees with the base, and the opening line already says «مطبوعة». | Same file; civil-procedure.md §المادة 193. |
| A27 | H | execution | 21 / 21 مكرر | Base 21 already ended «المادة(21 مكررة):- أ- تترك حكما معاملة التنفيذ… ب- يثابر على التنفيذ…». The branch added 21 مكرر without trimming 21, so the text is there twice and 21 still embeds another article's label. Once FR 4.1's inline-heading rule lands, the ingest would create a second «21 مكرر» and stop on "duplicate article". The heading «حبس المدين» moves from 22 to 21 مكرر. No amending law recorded (29/2017, 3/2019 or 9/2022?). | Re-checked: head 21 still contains «تترك حكما معاملة التنفيذ»; separate 21 مكرر heading. V`قانون-التنفيذ/sections/00-المواد-1-53.md` lines 112 and 117. |
| A28 | H | execution | 117 / 117 مكرر | Same: 117 still holds «المادة (117 مكررة):- تسري أحكام هذا القانون المعدل على المحكوم عليهم…» and the trailing title «الغاءات»; 117 مكرر repeats it and takes «الغاءات» as its heading. It is a transitional clause of an amending law (9/2022, Gazette 5796 per the report); its law and whether it still has effect are not recorded. | Re-checked: head 117 contains «تسري أحكام هذا القانون المعدل». V`قانون-التنفيذ/sections/01-المواد-54-119.md` lines 327-332. |
| A29 | C | sales-tax | 21 | The operative lead-in «(أ) يعفى من الضريبة:-» was deleted, so the list no longer says the items are exempt, and paragraph ب still refers to «البنود (2) و (3) و (4) من الفقرة (أ)», which no longer exists. The branch's own recorded LOB text has the lead-in; the "heading dropped" step removed operative text. The fix was triggered by a false positive (base «غيرالاردنيين»). The trailing title «السلع الخاضعة للضريبة بنسبة صفر» is now nowhere in the corpus. | Re-checked: base opens «أ. يعفى من الضريبة: 1. مشتريات ومستوردات جلالة الملك»; head opens «(1) مشتريات ومستوردات جلالة الملك», «يعفى من الضريبة» ×0. V`قانون-الضريبة-العامة-على-المبيعات/sections/00-المواد-1-22.md`. |
| A30 | H | sales-tax | 2 | Partly a real fix (the wrong «توريد السلعة» definition replaced, attributed to 15/2022). But the definitions amendments added (الاقرار الضريبي، المدقق، هيئة الاعتراض، المحكمة، التعليمات التنفيذية…) now follow paragraph ب and read as part of it; the base and a 2018 consolidated copy have them under أ. LOB typo «الاقرار الضريبيى» replaces the correct base form. | V same file, article 2 from line 17; J row sales-tax 2 (by_law 15/2022, Gazette 5812). Unofficial: https://jordan-lawyer.com/2018/12/19/قانون-الضريبة-العامة-على-المبيعات-لسن/. |
| A31 | H | sales-tax | 4 / 4 مكرر | Article 4 still contains the whole bis text inline («…هـ- يعد توريداً للخدمات كل توريد لا يعتبر توريداً للسلع. المادة 4 مكرر: أ- يعتبر توريد السلع قد تم داخل المنطقة الضريبية…»), and the branch added it again as «### المادة 4 مكرر». The heading «تحديد مسميات السلع» moves from 5 to 4 مكرر. The ten-laws lens missed this; the technical lens found it and this synthesis confirmed it. | Re-checked: article 4 is 3,207 characters in both trees and contains «المادة 4 مكرر: أ- يعتبر توريد السلع قد تم داخل»; head adds «### المادة 4 مكرر» after it. V`قانون-الضريبة-العامة-على-المبيعات/sections/00-المواد-1-22.md`. |
| A32 | C | landlords-tenants | 5 | The in-force 5(أ) text (Law 14/2013: rent increase set by Cabinet regulation, review «كل خمس سنوات», ten-year deferral for cases decided under 22/2011) was replaced by the superseded 22/2011 text (court reassesses rent to «أجر المثل»). The base text itself names «القانون رقم (22) لسنة 2011», so it must postdate that law. Also imported: «0» as a full stop ×4, «خمسة عشرة يوما», «يسمح» for «سمح». | Re-checked: base has «كل خمس سنوات» and «مجلس الوزراء» ×2; head has neither and «أجر المثل» ×2. V`قانون-المالكين-والمستأجرين/sections/00-المواد-1-22.md`. Gazette https://pm.gov.jo/Ar/Pages/NewsPaperDetails/5253 lists «قانون رقم (14) لسنة 2013 - قانون معدل لقانون المالكين والمستأجرين». Unofficial text: https://www.mohamah.net/law/?p=49438 (Gazette 5253, p. 5047, 2013-11-17). |
| A33 | C | landlords-tenants | 7 | Article 7 as replaced by 14/2013 (open-ended continuation for the tenant's family, heirs and widow; divorced wife with custody after «طلاق تعسفي») was swapped back to the 22/2011 limits (3 years family, 6 years heirs, 3 years divorced wife). A substantive loss of rights. Also «أ?-» with a literal question mark and «31/8/2000 0». | Re-checked: head «لمدة ثلاث سنوات» ×2 and «أ?-»; base «طلاق تعسفي». Same file. mohamah.net page above contains the base phrases and not «لمدة ثلاث سنوات». |
| A34 | H | companies | 248 | The operative opening «تتمتع الشركة الأجنبية غير العاملة بما يلي:-» was removed; the head opens at «أ- الاعفاء من رسوم التسجيل…», so the exemptions no longer say who gets them. Both the base and the recorded LOB text have the sentence; it was stripped like a heading line. | Re-checked: base opens «تتمتع الشركة الاجنبية غير العاملة بما يلي»; head opens «أ- الاعفاء من رسوم التسجيل». V`قانون-الشركات/sections/08-المواد-228-264.md`; S`companies/cmp-head-vs-recorded-lob.txt`. |
| A35 | M | companies | 14, 97, 98, 226, 254, 283 | LOB typos replaced correct base wording in passages no amendment touched: 14 «التغير» (base التغيير), 97 «ذوي الخبرة الاختصاص» (base والاختصاص), 98 «المشار الها» (base اليها), 226 «اتخاذه قرار الاندماج» (base اتخاذ), 254 «قراراها» (base قرارها), 283 «ولموظفي الدائرة المفوضون» (base المفوضين). | S`companies/small-replacements.txt` (SPELL rows). |
| A36 | M | companies | 5, 6, 7, 11, 94, 135 | Missing-space defects copied from LOB: «اوالغش» (5), «المسؤوليةالمحدودة» (6), «دولةاخرى» (7), «اوالحجر», «مايلي» (11), «حالةرفض» (94), «المؤسسةالرسمية», «شخصيةاعتبارية» and a stray «0» (135). A search for «المسؤولية المحدودة» or «شخصية اعتبارية» no longer matches these articles. | S`companies/small-replacements.txt` (GLUED rows), `damage-scan.txt`. |
| A37 | L | companies | 59, 266 | 266 «عن ( (75 %) من رأسمالها» (doubled, unbalanced parenthesis; base «(75%)»); 59 opens «أ--». | S`companies/damage-scan.txt`, `ends.txt`. |
| A38 | L | companies | 32, 77, 89, 266, 283 | Structural headings dropped: «الفصل الثالث انقضاء شركة التضامن وتصفيتها» (32), «الباب الخامس / شركة رأس المال المغامر» (77), «الباب الخامس مكرر الشركات المساهمة الخاصة» (89), «الفصل الثالث التصفية الاجبارية» (266), «احكام ختامية» (283). The corpus now has no Part V or Part V-bis heading. With 248, these are why 4 of the 51 do not equal the recorded LOB text. | S`companies/cmp-head-vs-recorded-lob.txt`; grep of head sections for «الباب الخامس مكرر»: 0 hits (base 1). |
| A39 | L | companies | 30, 76; all 51 | Each article ends with the next article's caption. 76 still ends «شركة التوصيه بالاسهم», which now introduces the venture-capital article 77; 30 ends «افلاس الشريك المتضامن», which now introduces an insolvency-law provision. The 51 changed articles lost their trailing captions, so 51 following articles lost their search heading. | S`companies/ends.txt`, `stale-markers.txt`. |
| A40 | M | income-tax | 34 | A genuine 38/2018 update with one imported LOB error: paragraph ج reads «أيا من الوقائع  أو التي فصلت فيها المحكمة»; the stray «أو» is not in the government's consolidated text, and the base had it right. Tatweel «مقتضــى». | Re-checked: head «أيا من الوقائع  أو التي فصلت»; base «أيا من الوقائع التي فصلت». Official non-LOB: https://portal.jordan.gov.jo/OD/files/7011.pdf (footnote: amended by 38/2018, Gazette 5547, 2/12/2018); S`law-text-b/dl-portal/7011.txt`. Gazette 5547 lists 38/2018. |
| A41 | L | court-fees | 16 | No amendment content: «على ألا» → «على أن لا», the correct «المهايأة» → LOB's misspelt «المهاياة», and «مائتي دينار 0», a trailing «0» that can be read as a number in a fee rule. Fees unchanged. | `docs/verification/2026-11-12-corpus-vs-official/court-fees.md` §المادة 16; V`جدول-رسوم-المحاكم/sections/`. |
| A42 | L | bar-association | 61 | The only change: the base typo «المتفرغة» replaced by LOB's «المتفرعه» (ه for ة; correct «المتفرعة»), plus hamza stripping. No 25/2014 content appears, although the detector credited 25/2014. | bar-association.md §المادة 61; J by_law 25/2014, Gazette 5294. |
| A43 | L | all changed laws | 75 articles and more | Invisible and decorative characters imported: 504 NBSP across 75 articles; ZWNJ in companies 31, 80, 83, 84, 85, 89 and sales tax 4 مكرر («أ‌-»); tatweel in companies 40, 77, 81, 82, 186, 226, 266, 284, income tax 34, labour 12, sales tax 2 and 9. `legal_search/normalize.py` folds tatweel and NBSP, but not ZWNJ, and users see the raw text when it is quoted. The base had none. | S`technical-impact/damage.py` output; S`companies/damage-scan.txt`; `services/legal-search/src/legal_search/normalize.py` line 9. |

### 2B. Amendments missed or left stale (4)

| # | Sev | Law | Article | What | Evidence |
|---|---|---|---|---|---|
| B1 | H | companies | 88 | 20/2023 missed inside the chapter the branch rewrote. Articles 77-87 and 89 now hold the venture-capital-company text; 88 still holds the abolished «تنقضي شركة التوصية بالاسهم وتصفى…». LOB's current 88 is the compulsory liquidation of the venture-capital company (similarity 0.042). The report classed it "substantive difference", so no fix was proposed. | J row companies 88 (last_amended_by 20/2023, Gazette 5874, p. 3627); S`companies/missed-candidates.txt`. |
| B2 | H | companies | 192, 217, 218, 279 | LOB lists 20/2023 as the last amender of each and its text no longer names «شركة التوصية بالأسهم»; the branch left them, so they still name the abolished company form (218 also «المحدود» for «المحدودة»). The report's "amendment not applied 51 → 0" hides them, and the registry footer says «آخر تعديل» 20/2023 for the whole law. | S`companies/stale-markers.txt`; J last_amended_by 20/2023 for all four; head `07-المواد-191-227.md`, `09-المواد-265-289.md`. |
| B3 | H | companies | 65 مكرر-88 مكرر (24 articles) | Never compared. The report says LOB lacks «الباب الخامس مكرر»; that is false. LOB's row for 65 مكرر (27,720 characters, against 842 in the corpus) holds 66-88 مكرر under labels «المادة (N): مكرر», which the splitter does not recognise, so rows 66-88 مكرر were classed "extra in corpus". LOB lists 20/2023 as the last amender of 13 of them, 34/2017 of 2 and 19/2021 of 1, so amendments are probably missing. 69 مكرر still names «محكمة العدل العليا» twice, where the branch elsewhere put «المحكمة الإدارية». **Correction to the companies lens**, which concluded the text must come from the Gazette: it is probably recoverable from J's 65 مكرر row once the splitter handles that label. | Re-checked: J companies 65 مكرر official_text contains 22 «المادة (N): مكرر» labels (66-69, 71-88; 70 is formatted differently); "extra in corpus" مكرر rows by LOB last amender: 20/2023 ×13, 35/2010 ×7, 34/2017 ×2, 19/2021 ×1. |
| B4 | H | landlords-tenants | registry | `amendment` says 22/2011 (Gazette 5134). That was already wrong before the branch, which keeps it; LOB's chain for record 2803 (30/2000, 17/2009, 43/2010, 22/2011) lacks 14/2013, so the report's "registry agrees with LOB" is agreement on a stale value. Every result for this law prints «آخر تعديل: 22 لسنة 2011». 14/2013 may have changed articles beyond 5 and 7. | `content/corpus/laws.json` (same in both trees); Gazette 5253 lists 14/2013. |

### 2C. Registry, derived files, tests and retrieval (7)

| # | Sev | Law | Item | What | Evidence |
|---|---|---|---|---|---|
| C1 | M | civil-code | 1287, `known_gaps` | 1287 was filled from LOB and its `known_gaps` entry removed, although the gap's own reason says the text "is to come from the Official Gazette (Phase 4 verification)". Removing it erases the only signal that the text is unverified. Both full-law files still print «(نص المادة غير متوفر)». The memorandum (draft art. 1278) states the rule for «صاحب الحق المجرد», where the filled text says «أحد الشركاء». The report also calls 1287 an article "that amendments added"; LOB lists no Civil Code amendments. | Bt `content/corpus/laws.json` known_gaps reason; V`القانون-المدني-الأردني/sections/12-المواد-1223-1320.md` line 483; `القانون-المدني-الأردني.md` line 8267, `…-مع-المذكرة.md` line 14812; `memorandum_civil_law.json`. |
| C2 | M | court-fees | registry `amendment` | The schedule is part of regulation 43/2005, amended by regulation 108/2008. `amendment.law` = 108, and `citation.py` prints «آخر تعديل: القانون المعدِّل رقم 108 لسنة 2008», calling a نظام معدل a قانون under every court-fees result. This footer is new (base had no amendment). The values themselves are sourced (LOB 5081/1820, Gazette 4711 and 4935) and pass corpus-ci; the fix is the wording path, not the values. | `content/corpus/laws.json` court-fees; `services/legal-search/src/legal_search/citation.py:39-48`. |
| C3 | M | 7 laws | derived files | Only the shards and `law-directory.md` were updated. `statistics.json` still says 6,593 total and old per-law counts; `article-index.json` lacks the six new «مكرر» rows; `shard-map.json` keeps old counts (the jordanian-law skill's "start here" lookup). The full-law copies of civil code (2 files), criminal procedure, civil procedure, courts formation, major felonies and court fees still hold the old text. Ingest reads only `sections/`, so skill readers and the ingest see different corpora. | S`technical-impact/NOTES.md` item 5; `jordanian-law/SKILL.md:39,84`. |
| C4 | L | penal-code | `_metadata.json`, shard 09 | After 467 مكرر was added, `law-directory.md` says 490 but `_metadata.json` keeps `expected_total_articles` 489, and shard 09's front matter says `article_count` 33 while it has 34 headings. | V`قانون-العقوبات-الأردني/sections/_metadata.json`, `09-المواد-444-476.md`. |
| C5 | H | companies, customs, labour, sales-tax, landlords-tenants, execution, income-tax, penal-code | search headings | The live keyword engine (T-B2, heading_weight 1.0) takes each article's heading from the title glued to the end of the previous article. LOB's text drops those titles: non-empty headings fall from 2,161 to 2,068 (96 lost, 22 changed, 0 gained). That is the clean-up the recall ingest says must never run before headings are stored separately (review 2026-11-11 (f)). Inserted «مكرر» rows steal the next heading («حبس المدين» execution 22 → 21 مكرر; «الغاءات» 118 → 117 مكرر; «تحديد مسميات السلع» sales tax 5 → 4 مكرر). RUNBOOK S3's `2161\|6592\|22` check would fail. execution-01 «حبس المدين في الالتزامات التعاقدية» drops from rank 1 to rank 3 (MRR 1.0 → 0.333; the lens summary's "rank 5" is corrected here from its own output file); customs-01 r@5 0.5 → 0. | `AI Harness-recall/services/legal-search/src/legal_search/ingest.py` (upsert comment), `headings.py`; S`technical-impact/parse-recall-src.json`, `eval-base-law.json`, `eval-head-law.json` (re-checked for execution-01 and customs-01). |
| C6 | M | all | provenance | Each article's source never reaches the product. Shard front matter still says `source: aqel-lawfirm.com/…` (or jordan-lawyer.com) above articles that now come from LOB, and `citation.py` prints «المصدر: {found.source}». So the library would cite LOB-derived text to a third-party site. | `citation.py:49`; e.g. V`قانون-التنفيذ/sections/00-المواد-1-53.md` front matter above the new 21 مكرر. |
| C7 | L | n/a | `test_prepare.py:85` | The only test change re-pins the real-corpus total from 6592 to 6599. No assertion is loosened, but the new number pins the six duplicated «مكرر» rows into the expected count. The recall worktree (`AI Harness-recall/services/legal-search/tests/test_prepare.py:85`) still pins 6592 and will fail or conflict on rebase. | `diff --strip-trailing-cr`: one line changed. |

### 2D. Errors in the report and the method (9)

| # | Sev | Item | What | Evidence |
|---|---|---|---|---|
| D1 | H | "amendment not applied" false positives | Rule 5 ("the corpus lacks words of the amending law") fires on spelling variants (ألا/أن لا in courts formation 15 and court fees 16; «إثباتهما» = «إثبات ما» in evidence 6; «غيرالاردنيين» in sales tax 21; «المتفرغة» in bar 61), on LOB headings (penal 80, 228, 287; criminal procedure 68, 338, 341), and on words an amending law quotes in order to delete them (penal 99). 11 of 132 replacements change no word of law text; 11 more change only 1-2 words, several typo-level (labour 118; criminal procedure 14, 136, 237, 288). The headline "134 stale / 132 brought up to date" is overstated by at least 11, and "134 texts in 14 laws" is about 12 laws: courts formation and court fees have no real stale article. Each such fix cites an amending law that did not produce the difference. | `courts-formation.md:60-64`, `court-fees.md:180-184`, `evidence.md` §6, `bar-association.md` §61, `penal-code.md:1080-1084, 1331-1335`; S`method/edits.txt`, `realchg.py` output; J basis: 82 rows rest on "lacks words", 27 of them on matches of 2 tokens or fewer. |
| D2 | H | LOB treated as the ceiling | The detector never asks whether the corpus text postdates LOB's last recorded amendment. Result: the regressions in landlords-tenants 5 and 7, labour 137, penal 99 and 306, and probably customs 161. A cheap predictor the redo should run: flag every row whose cited `by_law` is earlier than the latest law in LOB's own list for that article (penal 80, 208, 287, 306, 407; customs 161). | J notes "LOB lists amendments of this article by: …" against `page.by_law`; error rows A3, A10, A11, A18, A32, A33. |
| D3 | H | whole-article replacement | Each fix takes LOB's wording throughout the article, not only the amended passage, so LOB variants and typos come with it (error rows A4-A9, A14-A17, A19, A23, A24, A35-A37, A40-A43). The report's §7 claim "its chapter headings dropped … nothing else changed" is contradicted by the glued headings (A13, A14, A22) and the deleted operative lead-ins (A29, A34). 31 of 132 replacements do not equal LOB's text, 8 of them not even after normalising. The report itself documents LOB typos (§9, «يحب», «العش»; the Bar Association copy sides with the corpus 29 times, with LOB 10 times), yet replaces whole articles with LOB text. | S`method/trace.jsonl`; S`method/artifacts.py`. |
| D4 | M | hamza folding hides corpus damage | Comparison level (b) folds hamza seats, so spurious-hamza typos in the corpus are classed "normalisation-only" or "formatting", and the appendices show differences only after folding. About 38 such typos in about 29 civil code articles («المقأول» ×23 in 783-804, «تتنأولها» 2, «جأهلا» 298, «تعأرضت» 368, «عأدلة» 1050, «وجدأولها» 1293); civil code 802's «بدا» (appeared) against «بدأ» (began), a meaning change, is labelled normalisation-only. This weakens the report's "182 identical / 1,298 normalisation-only" framing. These are real fixes the corpus needs, through the lawyer. | S`method/hidden.py` output; J civil-code row 2 («تتنأولها», scope "formatting"); `civil-code.md` lines 351, 358, 360, 533. |
| D5 | M | "in force" not established | "In force" means LOB's GetFinalLegislation. Gazette contents pages were read only for issues LOB names, so an amending law LOB has not consolidated (as 14/2013 for landlords-tenants and 14/2019 for labour 137) goes unnoticed. No commencement (نفاذ) clause was read. Empty LOB amendment lists were taken as "no amendments": the list hash for civil code, commerce, investment fund and magistrates courts is `4f53cda1…1202b945`, the SHA-256 of the two-byte string `[]`. "No amendment LOB records is missing" for commerce, maritime and investment fund is an empty result (0 articles match any LOB version), and "version the corpus represents" is printed for 7 laws with a best match of 0 articles. | Report §2 table; report lines 204, 261, 286, 308, 352, 379, 390; `printf '[]' \| sha256sum`. |
| D6 | M | not reproducible | Raw LOB payloads, Gazette pages and the comparison scripts are not committed, so the SHA-256 values cannot be checked. Saved evidence for "Gazette's own date / listed in that issue" exists for 6 issue pages (4711, 4751, 4821, 5320, 5399, 5474); about 50 amending-law rows rest on unrecorded checks. Amending-law attribution is mechanical (penal 126, 228, 25: rows A13, A15). | Report NewsPaperDetails links; the diff adds no scripts or raw data. |
| D7 | M | report says "draft", branch commits text | The report says "Draft … Nothing here is verified or approved", yet the branch commits 150 article-text changes across 16 laws, the registry, `law-directory.md` (6,593 → 6,599) and the pinned test count. Merging would put unreviewed law text into the corpus that staging ingests, against D16/D17 and RUNBOOK P5's purpose. | S`method/tree-diff-raw.txt`. |
| D8 | L | report statistics | Companies LOB count 292 in §4 vs 290 in J (total 4,726 vs 4,724); §10 says "1,000+" trailing-title articles, the scope table gives 877; §9 says 22 undated amending laws, the tables have 21; the §9 offline list has 56 entries vs 55 in the tables (it includes the Penal Code itself, "16/1960: 228"); §10's Bar Association counts sum to 63, not 65; companies 89's note lists 35/2010 and 20/2023 twice each. | S`method/stats.py` output. |
| D9 | L | unexplained differences | Seven "numbering or order differs" rows and two "extra" rows have neither a fix nor an explanation: customs 227 (no LOB counterpart; LOB 227/228 and 249/250 repeat each other; corpus 250-253 = LOB 249-252, corpus 254 extra); sales tax 77 (similarity 0.0, "matches LOB article 76"); labour 142 (0.333). Two impossible LOB dates are missing from §8 (sales tax 24/1999 dated 1977-07-20; evidence 24/1961 dated 1952-05-17). §6 item 9 asserts 22/2017 replaced evidence 21 and LOB misnumbers 52 articles, without quoting 22/2017. Report lines 207, 393, 425, 480 name commits for laws with no change (commerce, investment fund, mediation, magistrates courts). | J rows; report lines 582-585. |

### 2E. For the lawyer to confirm (not errors; not counted)

These are not shown wrong, but nothing here is verified. The lawyer checks each against the Gazette text of the
amending law and its commencement clause.

- **companies:** 20/2023 (Gazette 5874; the 2023-08-13 date rests on LOB alone) and its commencement; 40/2002 (Gazette
  4556, offline; a temporary law made while no parliament sat) for 67, 73, 97, 248; the largest rewrites, which remove
  whole regimes: 2 (definitions of «البورصة» and «متعهد التغطية» dropped), 7 (about 142 words, including free-zones
  registration and «ولا تخضع لاحكام الافلاس والصلح الواقي»), 31 (bankruptcy rules replaced by the Insolvency Law regime),
  151 (internal regulations and the minister's 30-day approval), 285 («فيجوز للمراقب» became «فعلى المراقب»); 6 (the
  company-type list was reordered: item 4 is now «شركة رأس المال المغامر», so citations by item number move); 89 (LOB
  names 35/2010 and 20/2023 twice each); 265 (corpus «الوكيل العام», LOB still the pre-2017 «المحامي المدني»: LOB is not
  always current).
- **customs:** 16/2000 (Gazette 4423, offline) and 37/2010 (Gazette 5062) for 32 and 161; effective dates of 7/2025
  (Gazette 5991, 2025-04-30) and 33/2018 (Gazette 5520, 2018-06-14); which numbering is official for 227 and 250-254.
- **penal-code:** commencement of 27/2017 (Gazette 5479); 177 (equals LOB only); 185, 208, 308 مكرر, 334 مكرر, 407 and
  the 467 مكرر text (consistent with the unofficial Bar Association copy of 27/2017); whether 7/2018 changed 208, 10/2022
  changed 334 مكرر and 12/2025 changed 72 (no wording change is visible); 10/2022's date (Gazette's own 2022-05-25 against
  LOB's 2022-06-02); 475 against the 1960 Gazette (issue 1487, offline); 126 repealed by 50/1971 (issue 2315).
- **labour:** the 10/2023 set (10, 11, 12, 29, 30, 46, 69, 139) against Gazette 5851 (2023-04-16) and its effective
  date; 69 especially (the women's-work limits replaced by «يحظر أي تمييز على أساس الجنس…»); whether 10/2023 also
  touched 137; 118's spelling («وموجداتها», as in base and WIPO, against «وموجوداتها»); LOB's text for 98, 99, 107-109
  and 116 differs almost completely from the corpus, and WIPO agrees with the corpus for 107 and 116.
- **criminal-procedure:** the amending law that inserted 63 مكرر and 140 مكرر (probably 32/2017); whether 32/2017
  changed 68, 338, 341; what 16/2001, 11/2010 and 32/2017 changed in 14, 136, 237, 288; 364 and 365 against 16/1991
  (Gazette 3775, offline).
- **civil-procedure:** 182 and 193 against 31/2017 and 14/2023; 191 against 6/2024 (Gazette 5922, 2024-04-16).
- **execution:** the law that inserted 21 مكرر (29/2017, 3/2019 or 9/2022); 117 مكرر's law (9/2022, Gazette 5796),
  when the debtor-imprisonment provisions took effect, and whether the transitional clause is spent.
- **sales-tax:** which law added «لأغراض شخصية أو» to 9 (the branch says 36/2000; a 2018 consolidated copy lacks it,
  which points to 15/2022); 4 مكرر's text and effective date (15/2022, Gazette 5812, 2022-09-01).
- **landlords-tenants:** the 14/2013 text of 5 and 7, any amendment after 2013, and which other articles 14/2013 changed.
- **major-felonies-court:** 4(ج) in Gazette 5474 (24/2017, 2017-08-01).
- **civil-code:** 1287 against Gazette 2645 (1976, offline).
- **evidence:** whether 22/2017 (Gazette 5474, page images online) replaced article 21 and shifts 21-75.
- **bar-association:** whether 25/2014 (Gazette 5294, 2014-07-16) changed 61.
- **court-fees:** amendments to نظام رسوم المحاكم after 2008.
- **maritime-commerce:** 35/1983 in issue 3194 (LOB only).

### 2F. What passed (not counted)

- No article was removed or renumbered in any of the 22 laws. Parsed totals go 6,592 → 6,599, exactly the 7 additions;
  the 4 new criminal procedure and execution headings parse and sit after their parents. No shard moved; article order
  is kept.
- The registry keeps its 22 slugs in the same order. corpus-ci passes in staging mode on both trees; release mode shows
  the same 23 review problems as base. `node content/grounding-laws.mjs check` reports up to date. The memorandum is
  unchanged (766 notes, 1,447 links). The AQEL prompts, skills, specialists and starters cite no changed article.
- The detection half reproduces: J's corpus side equals the base tree's parse for all 4,741 compared articles; the class
  totals (182 / 1,298 / 3,043 / 134 / 59 / 8 / 25) and scope totals reproduce.
- Clean label removals: penal 153, 308, 334, 345, 348, 405; criminal procedure 242; civil procedure 222.
- The courts formation registry date (2019-05-01 for issue 5572) is right: issue 5561 is dated 2019-02-17 and 5573
  2019-05-16 on the Gazette, so LOB's 2019-08-28 is impossible.
- Gazette issue pages read live list the amending laws they should: 5253 (14/2013), 5812 (15/2022), 5134 (22/2011),
  5572 (12/2019), 5547 (38/2018), 5474 (24/2017), 5851 (10/2023); the report's tables give 5479 (27/2017), 5520
  (33/2018), 5991 (7/2025), 5796 (10/2022), 5996 (12/2025).
- Income tax 34 paragraphs أ, ب and د match the government portal's consolidated 38/2018 text word for word.
- Several substantive updates agree with the unofficial Bar Association copy of 27/2017 (penal 185, 208, 308 مكرر,
  334 مكرر, 407), and the customs 7/2025 additions (5(ج), 20(ب), 84 post-clearance audit, 247 five-year limitation) are
  consistent with LOB. Real repairs exist inside some damaged rows (sales tax 2's «توريد السلعة», evidence 6, criminal
  procedure 338's restored subject and 365's «الطلب مع»).

## 3. Technical impact and the safe adoption route

### 3.1 What the next ingest from main would do

The technical lens validated its offline harness on the base tree first. It reproduced RUNBOOK P5's live digest
`6592|9d944ab570c4565c166b517c9a06289a`, S3's 2,161 headings, the recorded T-B2 retrieval scores (recall@5 0.7229, MRR
0.5498) and 49 of 49 recorded replay lists. Its head numbers therefore show what an ingest of this branch would write:

- **Library:** 6,599 articles, key-order digest `6599|00a941da8c1b50bc3e56af379538dc11`. 143 rows rewritten, 7 added,
  0 removed.
- **Headings:** 2,161 → 2,068 (96 lost, 22 changed, 0 gained); RUNBOOK S3's `2161|6592|22` would fail.
- **Retrieval (80-item set, law filter):** recall@5 0.7229 → 0.7354, recall@10 0.8083 → 0.8250, MRR 0.5498 → 0.5488.
  Ten items have an expected article whose text or heading changes. Retrieval already returns both copies of a
  duplicated «مكرر» text (criminal-procedure-04's top two are 63 and 63 مكرر).
- **Replay:** 11 of 49 demo calls change their served list (calls 751, 1318, 1319, 1322, 1326, 1328, 1339, 1341, 1342,
  1343, 1360), including outside the edited laws, because BM25 statistics shift. No owner-accepted decisive article
  changes served state; the only decisive key whose text changes is penal 334 (loss of the «نص المادة مكرر» line).
  Articles actually served to demo guests whose text changes: companies 5, criminal procedure 140 and 338, customs 2,
  evidence 6.

**Why the main checkout matters.** Staging's ingest mounts the main checkout's corpus
(`deploy/staging/compose.yaml:238-239`: `'../../jordanian-law/references/القوانين-الأردنية:/corpus:ro'` and
`'../../content/corpus:/content/corpus:ro'`, re-checked). Any ingest from main after a merge (RUNBOOK S2, the D6/Rust
switch S2, FR Task 4.1, the PSL ingest) upserts every article's text (`ON CONFLICT … DO UPDATE SET … text =
EXCLUDED.text`) and prunes keys the corpus lacks. No rollback restores the live library, because a phase1 ingest writes
the same corpus. P5 and S3 would stop the runbook steps (first line `6599|00a941da…` instead of `6592|9d944ab…`), and
roadmap R6 ("one corpus change at a time") and FR 4.1's own runbook would collide with this branch. Every pinned value
goes stale: the rust-engine plan's P5/S7 pins, the replay table header ("6592 articles, headings 2161"), the recall test
pin.

**A runbook defect to fix independently.** P5b's raw-byte folder hash depends on line endings. The main checkout's
corpus folder already hashes `3defb49a…` against RUNBOOK's expected `1029ae71…`, although its text digest is still the
live `6592|9d944ab…` (the demo and verify worktrees are CRLF in all files; main is mixed). So P5b would stop S2 today
even without this branch. Replace it with the key-order text digest computed offline from the tree
(S`technical-impact/parse_compare.py`).

### 3.2 The hard rule

**Nothing from this branch may reach the MAIN checkout's corpus (`AI Harness/jordanian-law/references/القوانين-الأردنية/`
or `AI Harness/content/corpus/`) or the live library until the owner has given his word and the lawyer has signed off
on that law's articles.** Each adoption is recorded P5-style (count and key-order digest before and after, heading
count) and followed by the parity and replay re-runs below. A merge to main is itself the risk, since the next ingest
from main for any reason would carry it.

### 3.3 Safe route, in order

1. **The corpus commits do not merge.** Close the branch as committed, or revert its corpus, registry, `law-directory.md`
   and `test_prepare.py` changes before anything else from it lands.
2. **Docs-only PR (optional).** The report, J and the per-law appendices may land under `docs/verification/` as draft
   evidence, after the false claims are corrected: Part V-bis "missing" (B3), §7 "nothing else changed" (D3), the
   134/132 headline (D1), the statistics (D8), "no amendment missing" for laws with 0 matches (D5), and 467 مكرر "absent
   from the corpus" (A12).
3. **Registry-only PR**, touching only the `laws` table: maritime commerce `gazette_issue` 3194; courts formation
   `gazette_date` 2019-05-01; court fees only after the footer wording handles a regulation (C2). Civil code's `known_gaps`
   stays until the Gazette 2645 check. Show the lawyer the footer changes before the ingest that carries them.
4. **One PR per law**, each carrying:
   - the article list, with LOB and Gazette evidence per article (raw payload saved, retrieval time, SHA-256);
   - passage-only edits: only the amended passage changes, base wording kept elsewhere;
   - the artifact pass (A43) and no URLs, captions or attachment notes;
   - glued trailing titles kept, or moved into stored headings first, so the recall ingest's rule holds (C5);
   - «مكرر» handled only through FR Task 4.1's marker split, never by adding LOB rows beside merged text;
   - a per-article provenance field (C6);
   - the `law-directory.md` row and regenerated derived files: `statistics.json`, `article-index.json`, `shard-map.json`,
     the full-law copies, penal `_metadata.json` and shard front-matter counts (C3, C4);
   - the lawyer's sign-off (D16/D17) and the owner's word, recorded in the PR.
5. **Staging ingest under roadmap R6**, one corpus change at a time, each with a P5-style record:
   - before: compute the key-order text digest (count and md5 of md5(text) in key order) and the heading count offline
     from the tree with `parse_compare.py`, and write them into the change record;
   - after S3: the library's digest must equal the offline one; update S3's heading expectation and the rust-engine
     P5/S7 pins to the new digest;
   - do not rely on P5b's raw-byte hash (section 3.1).
6. **After each ingest, re-run:** `live_parity`; the replay table (`replay-rows.jsonl`) and its header; the retrieval
   evaluation set `retrieval-v1` (consider accepting 63 مكرر and 21 مكرر as answers once split); both `test_prepare.py`
   pins (main and the recall worktree). Tell the rust-engine and telemetry plans that their parity basis changed.

### 3.4 For the main agent (git, which the reviewers could not run)

- `git diff --stat 49ad460 d267007`: confirm that `content/prompts/aqel-v1.2-librechat.md`,
  `content/prompts/aqel-v1.3-librechat.md`, `content/aqel-edition.test.mjs` and
  `docs/handoff/2026-11-12-state-for-cloud-agents.md` are not in the range. In the worktrees they differ only by CRLF
  (`diff --strip-trailing-cr` is empty), which would otherwise change the pinned composed-prompt SHA-256.
- `git log --oneline 49ad460..d267007`: check the report's §5 claim of commits for commerce, investment fund, mediation
  and magistrates courts, which have no change in the tree.

## 4. The method: strengths and gaps

**Strengths.**

- The detection half is careful and reproduces exactly: J's corpus side equals the base parse for all 4,741 articles,
  and the per-law class and scope counts in §4 reproduce.
- It recorded LOB's per-article amendment chains, the payload SHA-256 and retrieval times, so the review could replay
  its reasoning row by row.
- It read Gazette issue pages for the laws LOB names and caught LOB's own date errors (courts formation 2019-08-28 for
  issue 5572), and it used a third reading (the Bar Association copy) and reported where it disagreed.
- It found real problems the corpus has: the wrong «توريد السلعة» definition, OCR damage in criminal procedure 365, the
  missing space in evidence 6, the trailing-title pattern, the stray «نص المادة مكرر» labels, the customs numbering
  mismatch.
- It removed nothing silently and renumbered nothing.

**Gaps.**

1. **Fixes replace whole articles** with LOB's consolidated text instead of the amended passage, importing LOB's typos,
   variants, headings and a URL (D3).
2. **LOB is treated as the ceiling.** There is no check for a corpus newer than LOB's consolidation, which produced the
   five regressions (D2).
3. **The amendment detector fires on noise:** spelling variants (ألا/أن لا), headings, missing spaces, and words an
   amending law quotes to delete (D1).
4. **The «مكرر» splitter misses LOB's «المادة (N): مكرر» labels** (B3), and the "missing in corpus" class does not look
   inside the parent article for merged text (A12, A20, A21, A27, A28, A31).
5. **Hamza folding hides real corpus typos** from the reviewer (D4).
6. **"In force" is never established independently:** no commencement clause read, empty amendment lists taken as
   "none", Gazette contents read only for issues LOB names (D5).
7. **No artifact pass** for NBSP, ZWNJ, tatweel, stray «0» and «?» (A43).
8. **No provenance** reaches the product (C6), and **nothing is reproducible** without the raw payloads and scripts (D6).
9. **The process contradicts itself:** a "draft, nothing verified" report on a branch that commits the text (D7).

## 5. PR review comment (ready to paste)

```markdown
**Review: request changes. Do not merge or ingest.**

The detection work is careful and reproduces (the jsonl's corpus side matches the base for all 4,741 compared articles; the §4 class counts reproduce). The fixes cannot land as committed. Law text changes only with the owner's word and the lawyer's sign-off (D16/D17), and the next ingest from main would write these 143 rewritten and 7 new rows into the live library with no rollback.

**Verification.** 0 of the 150 changed or added articles could be checked against an independently fetched official text (LOB's API returns 403; the Gazette serves images). Equality with the LOB text this branch captured is not verification.

**Regressions to older law (corpus was newer than LOB's consolidation):**
- landlords-tenants 5 and 7: back to 22/2011; Gazette 5253 lists the in-force 14/2013.
- labour 137: back to the pre-2019 text; the Constitutional Court quotes 137(ج) "as amended by 14/2019", and WIPO's consolidation to 14/2019 equals the base.
- penal-code 99 and 306: back to text that 27/2017 replaced (99's "missing" words are the words 27/2017 quotes in order to delete them).
- customs 161: probable regression to 16/2000 fees (LOB lists 37/2010 later).

**Operative text deleted or reversed:**
- customs 168: body replaced by the amending law's instructions («أولا: بإلغاء كلمة…»); paragraphs (أ)1-3 and (ب)1-3 gone.
- companies 248: opening «تتمتع الشركة الأجنبية غير العاملة بما يلي» removed.
- sales-tax 21: lead-in «(أ) يعفى من الضريبة» removed; ب now cites a paragraph that no longer exists.
- customs 199(ع): «في غير الأماكن» became «في الأماكن» (offence reversed); customs 192: «التهريب» became «التهرب».

**Duplicated text:** penal 467, criminal-procedure 63 and 140, execution 21 and 117, sales-tax 4. Each new «مكرر» row repeats text still inside its parent. At 63, 140 and 467 the «نص المادة مكرر» marker that FR Task 4.1 splits at was deleted. «مكرر» must go through Task 4.1 only.

**Not law text:** customs 14 now ends with a LOB `GetAttachment` URL, which also becomes customs 15's search heading.

**Missed:** companies 88, 192, 217, 218, 279 still carry pre-2023 text. 66-88 مكرر were never compared: LOB's 65 مكرر row holds them under «المادة (N): مكرر» labels the splitter does not read, so "LOB lacks Part V-bis" is wrong.

**Root causes:**
1. Whole-article replacement imports LOB typos, glued words and stray «0»/«?» (about 40 articles), sub-headings (10 articles) and NBSP/ZWNJ/tatweel (75 articles).
2. LOB is treated as the ceiling, with no "corpus newer than LOB" check.
3. "Amendment not applied" fires on ألا/أن لا, headings, missing spaces and quoted-for-deletion words: 11 replacements change no word of law text, and courts-formation 15 and court-fees 16 are pure false positives.

**Before any resubmission:**
- one PR per law, passage-only edits, an artifact pass, no URLs or captions;
- the «مكرر» splitter fixed, and a "corpus newer than LOB" check;
- a per-article provenance field; raw LOB payloads and scripts committed;
- derived files regenerated (statistics.json, article-index.json, shard-map.json, full-law copies, penal _metadata.json);
- glued titles kept until headings are stored separately (96 search headings would be lost);
- civil-code `known_gaps` kept until the Gazette check;
- the court-fees footer fixed so it does not call regulation 108/2008 «القانون المعدِّل»;
- the lawyer's sign-off recorded per law.

Please also confirm that the prompt and edition files (content/prompts/aqel-v1.2/v1.3-librechat.md, content/aqel-edition.test.mjs) are not in this range: in our checkout they differ only by CRLF.

Full review with per-article evidence: owner workspace, `.hq/docs/audits/librechat-platform/corpus-verify-review-2026-11-13.md`.
```

## 6. Owner decisions

Each decision is a choice; the recommended option comes first.

1. **The branch.** (a) Close it as committed and keep its report, J and appendices as draft evidence (docs-only PR after
   the corrections in 3.3 step 2). (b) Merge it and fix forward. **Recommend (a):** (b) puts unreviewed text in the
   corpus staging ingests.
2. **Authority and edit rule.** (a) The Gazette text decides. LOB is a finder, not the authority, and only the amended
   passage changes. (b) LOB's consolidated text is accepted as current. **Recommend (a):** LOB is demonstrably stale for
   landlords-tenants, labour 137, penal 99 and 306, and companies 265.
3. **Orthography.** (a) Keep the corpus spelling (hamza, ة, spacing) unless the Gazette shows otherwise, and fix the
   corpus's own typos (civil code «المقأول», 802 «بدا/بدأ») only through the lawyer. (b) Accept LOB's spelling wholesale.
   **Recommend (a).**
4. **«مكرر» articles.** (a) Only through FR Task 4.1's marker split (lawyer samples and your go first), done before any
   per-law PR that touches «مكرر»; restore the three deleted markers. (b) Accept LOB rows beside the merged text.
   **Recommend (a).**
5. **Glued trailing titles.** (a) Keep them until headings are stored separately (the recall ingest's rule). (b) Let
   LOB-based fixes drop them now (96 search headings lost). **Recommend (a).**
6. **Landlords-tenants.** Ask the lawyer to confirm 14/2013 is in force; then the registry's latest amendment becomes
   14/2013 (Gazette 5253, 2013-11-17), and the other articles 14/2013 changed are checked. Note that LOB's consolidated
   landlords-tenants text is stale. **Recommend yes.**
7. **What users see meanwhile.** The live library serves the base text, which LOB suggests is missing 20/2023 in about
   52 companies articles, 10/2023 in up to 8 labour articles, and 7/2025 and 33/2018 changes in customs. (a) Add a
   lawyer-worded note to those laws' results ("this text may not include amendment X") until the reviewed changes land.
   (b) Change nothing until then. **Your call.** (a) needs the lawyer's wording and is itself a registry change.
8. **Lawyer priority and Gazette access.** Proposed order:
   1. the confirmed regressions (penal 99 and 306, labour 137, landlords-tenants 5 and 7);
   2. the deletions and reversals (customs 168, 199, 192; companies 248; sales tax 21);
   3. civil procedure 182 and 193, and customs 161;
   4. the companies 20/2023 coverage (including 88, 192, 217, 218, 279 and 66-88 مكرر);
   5. the labour 10/2023 set;
   6. the rest.

   Decide whether to obtain Gazette copies of the offline issues: 4556 (40/2002), 4423 (16/2000), 2645 (Civil Code
   1976), 1487 (Penal Code 1960), 3775 (16/1991), 1859 (29/1965), 3194 (35/1983). Also decide whether to seek official
   LOB access, since its API is behind a WAF.
9. **Sequencing under R6.** (a) No corpus change goes to staging until the engine switch and FR Task 4.1 are done; then
   one law at a time, each with a P5-style record. (b) Interleave with them. **Recommend (a):** every corpus change
   invalidates the switch's P5/S3/S7 pins and the replay table.
10. **Provenance.** (a) Add a per-article source field (base source; LOB id, retrieval time and SHA-256; Gazette issue
    and page) and show an honest «المصدر» in citations. (b) Keep the shard-level `source:`. **Recommend (a).**
11. **The redo.** Whether the cloud agent redoes the work under the new rules (section 3.3 step 4 and section 4's gaps),
    one law per PR, starting with the laws whose only problem is the method (income tax 34, evidence 6, bar 61).
    **Recommend yes,** after decisions 2-5.
12. **Registry-only PR.** Approve the maritime commerce 3194 and courts formation 2019-05-01 values for a separate PR
    once the lawyer has seen them. Hold court fees until the footer wording is fixed, and keep civil code's `known_gaps`
    for 1287. **Recommend yes.**
13. **RUNBOOK P5b.** Replace the raw-byte folder hash with the key-order text digest, since line endings already break it
    on main (section 3.1). **Recommend yes,** before the engine switch's next attempt.

## Appendix: reviewer notes

All under `D:/Iqraa Law/.hq/scratch/corpus-verify-review/` (read-only evidence; gitignored scratch):

- `companies/`: `cmp-head-vs-recorded-lob.txt`, `missed-candidates.txt`, `stale-markers.txt`,
  `small-replacements.txt`, `damage-scan.txt`, `ends.txt`, `changed.json`, `per-article.tsv`, `notes.txt` (fetch
  attempts: LOB SPA, `OPS.ashx` 403, CCD PDF 403/404).
- `customs-penal/`: `customs_compare.txt`, `penal_compare.txt`, `customs.diff`, `penal.diff`, `tools/compare.py`,
  `web/jba2017/jba-penal-2017.pdf` (unofficial Bar Association copy of 27/2017).
- `law-text-labour-crimproc-civproc-exec/`: `changes.json`, `check-out.txt`, `wipo-dl/` (WIPO consolidation to
  14/2019), `gazette-dl/`.
- `law-text-b/`: `notes.md`, `article-changes.json`, `article-changes-readable.txt`, `diff_articles.py`, `dl-portal/7011.txt`
  (government portal income tax law).
- `technical-impact/`: `NOTES.md`, `parse_compare.py` (offline key-order digest), `offline_eval.py`, `offline_replay.py`,
  `changed-articles.md`, `parse-recall-src.json`, `eval-*-law.json`, `replay-compare.json`, `laws-json.diff`.
- `method/`: `trace.jsonl`, `edits.txt`, `tree-diff-raw.txt`, `artifacts.py`, `hidden.py`, `realchg.py`, `stats.py`.

Sources that could not be fetched in any lens: LOB records 3410 (companies), 3473 (customs), 3435 (penal), 3392
(labour), 3252 (criminal procedure), 3420 (civil procedure), 3365 (execution), 2803 (landlords-tenants), 3370 (sales
tax), 536 (civil code) at `https://www.lob.gov.jo/?v=3&lang=ar#!/LegislationDetails?LegislationID=<id>&LegislationType=2&isMod=false`;
Gazette issue pages 5294, 4935, 4709, 4711, 5922, 5796 and 5479 refused connections during this review.

## 7. Owner decisions (2026-11-13)

1. **The branch as committed:** its law-text commits are not merged. The comparison report, `corpus-diff.jsonl` and
   the per-law appendices are kept as draft evidence only after their false claims are corrected (section 4). The
   cloud agent handles this (prompt given by the owner).
2. **Authority and edit rule: the Official Gazette text decides; LOB is only a finder; a fix changes only the
   amended passage**, never the whole article, and never imports LOB page artifacts (links, stray digits, glued words,
   sub-chapter headings, LOB typing errors).
3. **Redo: yes, one law per pull request**, under rule 2, starting with the three small, low-risk fixes (income-tax 34,
   evidence 6, bar-association 61), each «draft, for lawyer review»; every changed article cites its amending law with
   Gazette issue, date and page, and its source text; no «مكرر» split outside the recall plan's Task 4.1 route; no
   corpus change reaches staging or the live library before the owner's word and the lawyer's sign-off.
4. **Meanwhile, visitors get a per-law notice** on results from companies, labour and customs saying the text may not
   include recent amendments (20/2023; 10/2023; 7/2025 and 33/2018), in wording the lawyer approves. The local main
   session builds this in the product; cloud agents do not.
