# A third reading from jordan-lawyer.com (draft, for lawyer review)

**Draft, for lawyer review («مسودة، لمراجعة المحامي»).** *Corrected 2026-11-13, after the review of this branch ([`docs/reviews/2026-11-13-corpus-verify-review.md`](../reviews/2026-11-13-corpus-verify-review.md)):* the website-residue removals this report first described as committed were taken back with every other law-text change on the branch, so nothing in section 5 is applied. Section 4 no longer says the site "supports" the first fix attempt. Section 8 adds the owner's export result for the live site (*corrected 2026-11-13*: first called a check; the export is outside the repository).

This adds one more reading to [the corpus verification of 2026-11-12](2026-11-12-corpus-vs-official.md). jordan-lawyer.com is a convenience copy. It can point to where a difference comes from, but it never proves a reading. Only the Official Gazette does. Nothing here marks any text as verified.

Data: [`2026-11-13-jordan-lawyer-third-reading.json`](2026-11-13-jordan-lawyer-third-reading.json). It holds every word-level verdict, the page hashes, the website residue found, the items flagged, the list of other laws on the site, and the owner's export result for the live site of 2026-11-13 (*corrected 2026-11-13*).

## 1. Source and its limits

- **Which copy.** The live site refused this session: every request to `jordan-lawyer.com` on 2026-11-12/13 got HTTP 429 from the host's rate limiter, `robots.txt` included. So this reading uses the copy of the site's pages already held in this repository, `jordanian-law/references/docs/markdown/` (3,138 pages; its index was generated on 2026-01-27). The copy keeps no page URL or retrieval date, only each page's publication date. The SHA-256 of each page file used is in the JSON.
- **Pages added or changed on the site after January 2026 are not covered.** The Internet Archive holds the site's sitemap as of 2026-04-07, but `web.archive.org` is not reachable from this environment.
- **Coverage.** The site's pages hold most articles of each law: civil-procedure 218 of 229, penal-code 462, evidence 71. The site often writes an article's heading as a link to a blog post, and those headings were read too. Neither the copy nor the site has a page for the maritime-commerce or investment-fund law.

Method: for every word-level difference between the corpus (as it is) and LOB, the same comparison as in the main report, the words on each side were looked for in the site's article of the same number. Each side was checked with three, then two, then one words of context, after the level (b) normalisation. If the article was not on the page, the whole page was searched. For every article LOB lists as amended after the corpus text ("amendment not applied") or that the corpus lacks ("missing in corpus"), the site's article was compared with both texts (word similarity of at least 0.9).

## 2. Where the corpus came from

Each law's shard files name their source:

| Source | Laws |
|---|---|
| jordan-lawyer.com | civil-code, civil-procedure, evidence, penal-code, criminal-procedure, mediation, courts-formation, magistrates-courts, major-felonies-court, court-fees, bar-association |
| aqel-lawfirm.com | commerce, maritime-commerce, companies, customs, income-tax, sales-tax, labour, landlords-tenants, execution, investment-fund |
| adaleh.info | majalla |

This decides what the third reading can show:

- **For the 11 laws taken from jordan-lawyer.com, the site is not an independent witness.** That the site agrees with the corpus shows only that the difference from LOB was in the source page, not made when the corpus was built. It says nothing about which reading the Gazette has.
- **For the 10 laws taken from aqel-lawfirm.com, jordan-lawyer.com is a second, independent copy for the 8 it has a page for** (not maritime-commerce or investment-fund; *corrected 2026-11-13*). Where it sides with LOB against the corpus, the corpus reading is most likely a fault of the aqel-lawfirm.com copy. It still needs the Gazette.

## 3. Word differences: which reading the site shares

These are the body differences only (the words differ). Counts are word-level operations, not articles. *Corrected 2026-11-13:* «glued caption» counts the operations where the corpus article ends with the next article's caption and LOB's does not, and the site, like LOB, does not glue it; they are no difference of law wording. The earlier «site = LOB» column counted both kinds together. *Corrected 2026-11-13:* three more kinds are now counted apart, in the JSON's `kind` and in columns of their own. «Chapter or part heading»: 106 operations where the corpus carries a heading such as «الباب الرابع …» or «الفصل الثاني …» that LOB's article lacks, all in commerce (34), companies (24) and customs (48), and 7 where LOB carries one that the corpus and the site lack (counted under «site = corpus»). «ملغاة» label: commerce's 187 repeal labels on articles 290 to 477, where LOB's article is empty. «Website residue»: 8 operations of the site's link text («انظر مقال …», «انظر شرح …», «للاطلاع على مقال …», «المصدر: موقع محامي الأردن»), listed in section 5. None of these is a difference of law wording.

| Law | corpus from | site page (articles found) | site = corpus | site = LOB, wording | site = LOB, glued caption | site = LOB, chapter or part heading | site = LOB, «ملغاة» label | site = LOB, website residue | both | neither | not on the page |
|---|---|---|---|---|---|---|---|---|---|---|---|
| civil-procedure | jordan-lawyer.com | `doc-0415` (218) | 58 | 1 | 0 | 0 | 0 | 0 | 0 | 3 | 0 |
| civil-code | jordan-lawyer.com | `doc-0098` (1441) | 236 | 0 | 0 | 0 | 0 | 0 | 13 | 0 | 0 |
| evidence | jordan-lawyer.com | `doc-1609` (71) | 7 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| landlords-tenants | aqel-lawfirm.com | `doc-0353` (22) | 3 | 6 | 9 | 0 | 0 | 0 | 0 | 1 | 0 |
| commerce | aqel-lawfirm.com | `doc-1627` (392) | 56 | 137 | 210 | 34 | 89 | 0 | 1 | 152 | 239 |
| penal-code | jordan-lawyer.com | `doc-0432` (462) | 166 | 0 | 0 | 0 | 0 | 3 | 11 | 2 | 0 |
| companies | aqel-lawfirm.com | `doc-1607` (308) | 60 | 112 | 109 | 24 | 0 | 0 | 4 | 6 | 2 |
| customs | aqel-lawfirm.com | `doc-1608` (253) | 62 | 56 | 97 | 48 | 0 | 0 | 1 | 7 | 0 |
| income-tax | aqel-lawfirm.com | `doc-0490` (82) | 3 | 59 | 35 | 0 | 0 | 0 | 2 | 1 | 0 |
| sales-tax | aqel-lawfirm.com | `doc-0487` (77) | 28 | 12 | 25 | 0 | 0 | 0 | 3 | 2 | 0 |
| labour | aqel-lawfirm.com | `doc-0073` (142) | 100 | 12 | 25 | 0 | 0 | 0 | 0 | 17 | 0 |
| execution | aqel-lawfirm.com | `doc-0395` (119) | 12 | 10 | 24 | 0 | 0 | 0 | 4 | 1 | 0 |
| mediation | jordan-lawyer.com | `doc-0451` (14) | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| criminal-procedure | jordan-lawyer.com | `doc-0416` (372) | 77 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| courts-formation | jordan-lawyer.com | `doc-0367` (23) | 8 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| magistrates-courts | jordan-lawyer.com | `doc-0450` (22) | 3 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 0 |
| major-felonies-court | jordan-lawyer.com | `doc-0399` (16) | 3 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| court-fees | jordan-lawyer.com | `doc-0568` (52) | 14 | 0 | 0 | 0 | 0 | 0 | 20 | 0 | 0 |
| bar-association | jordan-lawyer.com | `doc-1162` (110) | 43 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 |

"both": the site has both readings (the passage occurs twice). "neither": the site has a third reading or the context did not match. *Corrected 2026-11-13:* only the «site = LOB» columns are split by kind. «Site = corpus» holds the 7 headings LOB carries and no glued caption; «both», «neither» and «not on the page» count every kind: glued captions (35, 44 and 85), «ملغاة» labels (neither 12, not on the page 86) and website residue (both 2, neither 2). "site = LOB" includes passages the site has under another article number: commerce 148 (2 wording, 55 glued captions, 2 headings and all 89 «ملغاة» labels), companies 3, customs 5 (2 wording, 3 headings), income-tax 2, sales-tax 1 and labour 1. "site = corpus" likewise includes 2 such operations (commerce 1, customs 1).

*Corrected 2026-11-13:* restated for the jordan-lawyer.com laws. The first table counted 37 of their operations «not on the page» (civil-procedure 4, civil-code 2, evidence 2, penal-code 29). None is missing: the January copy filed each under another number (section 8). Civil-procedure 134, 168 and 213 are under «133», «167» and «212»; evidence 11 under «10»; penal-code 10, 170, 174, 209, 214, 221, 225, 236, 271, 349, 417, 421, 428, 446 and 458 under the number before (349 under «348 مكرر», 421 under «420», 458 under «456»); civil-code 86 and 744 under the page's own labels «8» and «74»; penal-code 378 مكرر inside 378. Looked up there, the site has the corpus reading in 26, both readings in 7 (LOB's article headings, which the merged January text also carries), neither in 2 and LOB's in 2. The last four are the site's link text in penal-code 10 and 421 and evidence 11 (website residue). Companies 252's 3 operations are restated the same way (under «251»). The JSON marks each restated operation «on the January page under «N»».

What it shows:

1. **The 11 laws taken from jordan-lawyer.com:** *Corrected 2026-11-13:* the site shares the corpus reading in 616 operations (590 before the restatement above) and LOB's in 5. These differences were already on the site. They are not transcription errors made when the corpus was built. 6 of the 616 are LOB's chapter or part headings, which the corpus and the site both lack (civil-code 88, 465, 1321 and 1424, penal-code 95, criminal-procedure 200).
   - The 5 exceptions are not differences of wording. They are words that on the site are links to its blog posts: penal-code 52 («انظر شرح المادة 52 …») and 332 («انظر مقال …»), and, restated, penal-code 421 and evidence 11, all listed in section 5 and now counted as website residue; and the heading words «( أسباب الطعن بالتمييز )» of civil-procedure 198, which are flagged (*corrected 2026-11-13*).
   - Of the 6 "neither" cases, 4 are single words or short phrases where the corpus, the site and LOB do not all match, such as civil-procedure 164 «بنسبة» against LOB's «بنسنة», 217 «وقف» against «وفق», and magistrates-courts 19 «وقانون اصول» against «واصول» (*corrected 2026-11-13*). The other 2, restated, are the site's link text in penal-code 10 and 421 (*corrected 2026-11-13*).
   - More generally, the titles the corpus gives articles of these laws after «— » are the site's link titles. The official text has no such titles. The main report counts them as formatting.
2. **The 8 aqel-lawfirm.com laws the site has a page for** (not maritime-commerce or investment-fund): *Corrected 2026-11-13:* jordan-lawyer.com sides with LOB in 404 operations that differ in law wording. In 729 more it sides with LOB where there is no difference of wording: 534 where the corpus has the next article's caption glued on, 106 chapter or part headings and 89 «ملغاة» labels. It sides with the corpus in 324. The first figures (597 in wording, 535 glued captions, 322 with the corpus) counted the headings and labels as wording, and read customs 191 and 193, whose «للنائب العام» paragraphs the site has, as glued captions on LOB's side; companies 252 is now restated.
   - In law wording, for commerce (137 to 55), companies (112 to 60), income-tax (59 to 3) and landlords-tenants (6 to 3), a second unofficial copy does not share most of the corpus's departures from LOB. They point to the aqel-lawfirm.com copy (*corrected 2026-11-13*). Customs is no longer among them (56 to 62): 48 of its first 104 were chapter or part headings (*corrected 2026-11-13*).
   - Labour is the exception: the site shares the corpus reading 100 times and LOB's 12 times in law wording (25 more are glued captions). Sales-tax (28 to 12) and execution (12 to 10) lean the same way (*corrected 2026-11-13*).

## 4. Amendments: is the site's text current?

For the articles the main report found out of date or missing, this is what the site's article has:

| Law | site matches LOB's text | site matches the corpus text | site differs from both | not on the page |
|---|---|---|---|---|
| companies | 39 | 3 | 9 | 0 |
| customs | 5 | 22 | 3 (188, 192, 229) | 0 |
| labour | 9 | 1 | 0 | 0 |
| income-tax | 1 | 0 | 0 | 0 |
| sales-tax | 1 | 1 | 1 | 1 (4 مكرر) |
| execution | 1 (21 مكرر) | 0 | 0 | 1 (117 مكرر) |
| penal-code | 0 | 20 | 1 (287) | 0 |
| criminal-procedure | 0 | 11 | 0 | 0 |
| civil-procedure | 0 | 3 (182, 191, 193) | 0 | 0 |
| landlords-tenants | 0 | 2 | 0 | 0 |
| evidence | 0 | 2 (6, 75) | 0 | 0 |
| courts-formation, major-felonies-court, court-fees, bar-association | 0 | 1 each | 0 | 0 |
| civil-code | 0 | 0 | 1 (1287) | 0 |

*Corrected 2026-11-13:* the rows counted here are the detector's «amendment not applied» and «missing» rows, and many are not stale articles. Detector false positives (D1): courts-formation 15, court-fees 16, evidence 6, bar-association 61, penal 80, 228, 287, criminal-procedure 68, 338, 341 (*corrected 2026-11-13*: penal 99 was listed here too; the corpus is newer there, A10, as the bullet «Where the review found the corpus newer than LOB» below says). No amendment content: penal 102, 300. Customs 14 (A2) differs only by LOB's caption and link. The columns were first headed «current» and «older», which assumed LOB was current.

*Corrected 2026-11-13:* restated for the jordan-lawyer.com laws, none of their rows is «not on the page». Penal-code 422 is on the January page under «420» and civil-procedure 191 under «190» (section 8), and both are the corpus text word for word; for 191 that is the corpus's pre-6/2024 text. On the live site (the owner's export) both are under their own numbers and are again the corpus text word for word: LOB's 422 differs only by «الإعادة»/«والإعادة» (no amendment content), and LOB's 191 adds 6/2024's «غير القابلة للتقدير أو», which neither the corpus nor the site has. (The JSON's first live verdicts for the two, «differs from both (0.85)», counted the addresses of the page's links.) Penal-code 208 was counted «differs from both» because January «208» also holds 209; on 208's own part the site has the corpus text word for word. Penal-code 467 مكرر and criminal-procedure 63 مكرر and 140 مكرر sit inside 467, 63 and 140 on the page, as in the corpus (467 مكرر: 87 of LOB's 88 words; the other two: all of LOB's words). LOB's evidence 75 is the page's 74, as in the corpus (LOB's numbering is one ahead; review D9). These are counted under «site matches the corpus text»; the penal row's «differs from both» is now 287 alone.

*Corrected 2026-11-13:* customs 188, 192 and 229 are moved from «site matches LOB's text» (188, 192) and «site matches the corpus text» (229) to «differs from both»: on the term in question the site matches neither reading. It reads «مدعي عام» where LOB reads «مدعي عام الجمارك» and the corpus «المدعي العام» (188, 192) or «مدعي عام الجمارك» and «المدعي العام» (229(أ) and (ج)). In 192 it also reads «جريمة التهرب» where LOB and the corpus read «جريمة التهريب»; like LOB it reads «جرم التهرب المشهود» where the corpus reads «جرم التهريب المشهود». In 229 it lacks the referral clause, like the corpus. Law 10/2019 bears on all three (main report, customs section).

- **For companies, labour and income-tax, a second unofficial copy carries LOB's text** for most of the articles the first fix attempt replaced. That makes them candidates for a passage-only fix, but it settles nothing. The site may copy LOB, and the review found defects inside those LOB texts (typos, glued words, stray «أو» in income-tax 34). The Gazette decides.
- **Where the review found the corpus newer than LOB** (*added and corrected 2026-11-13*): the site sides with the corpus at landlords-tenants 5 and 7, labour 137 and probably customs 161, where it is an independent copy. It also does at penal 99 and 306 and civil-procedure 182 and 193, but for the penal code and civil procedure the site is the corpus's own source. The exception is companies 265, where the site keeps LOB's pre-2017 «المحامي المدني». The regressions (D2) are A3, A10, A11, A18, A32 and A33. Listed apart: customs 168 (A1: the corpus already has 33/2018) and civil-procedure 182 and 193 (A25, A26: not shown stale). None of this is proof either way.
- **For the rows that survive the review, on the jordan-lawyer.com laws, where the site is the corpus's own source, the site's own text is as old as the corpus's, despite page titles that say «حتى 2025»** (*corrected 2026-11-13*): penal 185 (paragraph 1 replaced by 8/2011, then 27/2017), 308 مكرر (27/2017), 334 مكرر (27/2017 and 10/2022) and 407 (8/2011), and criminal-procedure 14, 136, 237 and 288. *Corrected 2026-11-13:* the sentence first read «penal 185, 208, 308 مكرر, 334 مكرر and 407 (probable 27/2017 updates)» and included civil-procedure 191 «absent from the January page». Each penal article has its own amending law (main report, penal-code section). Penal 208 is dropped: the corpus already has 7/2018's text, and only the number «4-» is missing ([PR #20](https://github.com/ahmadtech26/ai-harness/pull/20)). Civil-procedure 191 is dropped: it was on the January page (see the restatement above). A page title on this site is no evidence that the text is current. The courts-formation, bar-association and mediation page titles carry no year.

## 5. Website residue found in the law text (not applied)

Reading the site's pages next to the corpus showed text in the corpus that is not law text. It is page furniture the build carried over:
- the site's cross-links to its own blog posts («انظر مقال …»);
- a source credit;
- the site's link to its next page;
- stray `<div` lines.

Where it sat in a heading after «— », the product's parser read it as the first words of the article. *Corrected 2026-11-13:* the removals were committed on 2026-11-13 and taken back the same day with every other law-text change on the branch, so they are not applied. Each is a candidate for a later per-law pull request, for the lawyer to approve.

| Law | Article | Website residue |
|---|---|---|
| civil-procedure | 86 | the line «انظر مقال الأحكام القانونية للكشف والخبرة» at the head of the article |
| civil-procedure | 141 | «(انظر مقال الحجز التحفظي)» in the heading (the title «الحجز الاحتياطي» stays) |
| evidence | 11 | the heading's only words, «(انظر مقال عن السند العادي والإقرار الخطي)» |
| evidence | 27 | «(انظر مقال عن كيفية مناقشة الشهود)» at the end |
| penal-code | 10 | the heading's only words, «(انظر مقال عن الاختصاص الدولي الجزائي للمحاكم الأردنية)» |
| penal-code | 52 | «انظر شرح المادة 52» in the heading (the site's title «إسقاط دعوى الحق العام بإسقاط الحق الشخصي» stays, like every other site title) |
| penal-code | 332 | «(انظر مقال عن الإيذاء البسيط والإيذاء البليغ)» on the glued heading line (the heading «إيذاء الأشخاص» stays, like every other glued heading) |
| penal-code | 350 | «(انظر مقال عن التهديد بالقتل بوسيلة الكترونية)» at the end |
| penal-code | 421 | the heading's only words, and the same link in paragraph 5, «(انظر مقال الشيك المكتبي وفقا لأحدث التعديلات)», where it ends the opening sentence, before conditions أ and ب (*corrected 2026-11-13*) |
| major-felonies-court | 16 | «للاطلاع على مقال عن محكمة الجنايات الكبرى …», the link text «محكمة الجنايات الكبرى», `<div` |
| courts-formation | 23 | «جدول رسوم المحاكم حتى 2025» (the site's link to its next page), `<div` |
| bar-association | 110 | «المصدر :  موقع محامي الأردن.», `<div` |
| mediation | 14 | `<div` |
| majalla | 1851 | everything after «1876م.» in `sections/16-كتاب-القضاء.md:442`: the adaleh.info footer («جميع الحقوق محفوظة لدى مركز عدالة …») and script code (*added 2026-11-13*) |
| majalla | 672, 761, 832 | a trailing « <» (`03-كتاب-الكفالة.md:402`, `05-كتاب-الرهن.md:406`, `06-كتاب-الأمانات.md:454`); each book's closing date stays (*added 2026-11-13*) |
| majalla | 1249 | a leading «PP» (`10-كتاب-الشركات-1235-1341.md:101`) (*added 2026-11-13*) |
| evidence | 1 | the site's table of contents inside article 1 (`sections/00-قانون-البينات-الكامل.md` lines 18-30: «جدول محتويات القانون» and six chapter entries); line 32, the chapter heading over article 2, stays (*added 2026-11-13*) |
| civil-procedure | 86 | the same leftover in the folder copy, `قانون-أصول-المحاكمات-المدنية.md:638`, as the bare line «انظر مقال» (*added 2026-11-13*) |
| commerce | 480 | the website sidebar after the closing date «8/ 3/ 1966» (`قانون-التجارة/sections/09-المواد-457-480.md:129`): «تشريعات أخرى المذكرة الايضاحية للقانون المدني الاردني … قانون العقوبات وتعديلاته»; the date stays. From the owner's review of 2026-11-13; removed in [PR #26](https://github.com/ahmadtech26/ai-harness/pull/26) (*added 2026-11-13*) |

Flagged for the reviewer:

| Law | Article | Text | Why |
|---|---|---|---|
| courts-formation | 23 | «11/3/2001» | a date after the last article: perhaps the law's date, not article text |
| mediation | 14 | «2/2/2006» | the same, at the end of the last article |
| magistrates-courts | 22 | «18/7/2017» | the same |
| civil-procedure | 198 | «( أسباب الطعن بالتمييز )» in the heading | on the site, a link to a blog post; kept like every other site title |
| criminal-procedure | 370 | «1961/2/28» (`sections/08-المواد-331-370.md:426`; folder copy :2410) | a date after the last article (*added 2026-11-13*) |
| execution | 119 | «14/3/2007» | the same (*added 2026-11-13*) |
| investment-fund | 16 | «24/5/2016» | the same (*added 2026-11-13*) |
| income-tax | 82 | «30/12/2014» | the same (*added 2026-11-13*) |
| courts-formation, magistrates-courts | folder copies | the dates in `قانون-تشكيل-المحاكم-النظامية.md:277` and `قانون-محاكم-الصلح.md:210` | the same dates in the folder copies (*added 2026-11-13*) |
| penal-code | 72, 177, 389 | «(النص بعد تعديل 2022)», «تعديل 2022», «( تعديل 2022 )» in the headings | the site's notes, not law text; kept (*added 2026-11-13*) |
| commerce, companies, income-tax | many | the editorial «ملاحظة» notes: 187 in commerce shards (articles 290 to 477 repealed by article 140 of Insolvency Law 21/2018); «*ملاحظة: تم الاستعاضة عن عبارة (المحامي العام المدني) …» in companies `09-المواد-265-289.md:19` and :104 and income-tax `03-المواد-55-81.md:14` | they carry legal information; kept for the lawyer (*added 2026-11-13*) |
| majalla | all | the inline reference numbers (for example «الدعوى 1613 … محكما 1790، فيكون حكمه 1786» in 1851) | part of the adaleh.info edition; kept (*added 2026-11-13*) |
| maritime-commerce | `02-المواد-114-178.md:324` | «م}جرها» | a typo for the lawyer, not website text (*added 2026-11-13*) |

*Corrected 2026-11-13:* this list first included a LOB attachment link in customs 14. That link was not in the corpus: the first fix attempt wrote it in (review A2), and the revert removed it.

*Corrected 2026-11-13:* the search for residue ran over the `sections/` shards of the 22 laws with these patterns: «انظر مقال», «انظر شرح», «للاطلاع على مقال», «المصدر\s*:», «موقع محامي», «حتى 20xx» at the end of a line, «https?://», «^<» and «<div», «&nbsp;», a date alone on a line (*corrected 2026-11-13:* by the regular expression `^\s*\d{1,2}/\d{1,2}/\d{4}\s*$`, day and month first, a four-digit year, no spaces inside, so it missed «1961/2/28» and «8/ 3/ 1966»; *corrected 2026-11-13:* that expression matches only «11/3/2001» (courts-formation 23) and «18/7/2017» (magistrates-courts 22), each alone on its line. Mediation 14's «2/2/2006» ends a line of text; it was found by reading the end of the article, to which the «<div» pattern on the next line pointed. Criminal-procedure 370's «1961/2/28», execution 119's «14/3/2007», investment-fund 16's «24/5/2016» and income-tax 82's «30/12/2014» come from the owner's session's scan, whose pattern is not recorded here), «تنزيل», «تحميل», «بصيغة», «Word», «اضغط», «شارك», «اقرأ»/«إقرأ», «مقالات ذات صلة» and «الوسوم». Its other matches were law text (for example «يشارك», «تحميل البضائع», «بصيغة الماضي»). It did not search for copyright footers, scripts, «-->», tables of contents, a lone «<» at the end of a line, editorial notes, inline reference numbers, or the folders' full copies; the rows added above come from the owner's session's scan. *Corrected 2026-11-13:* the owner's review added «تشريعات أخرى» to the patterns. A search for «تشريعات (أ|ا)خرى» over the shards and the folder copies of the base (`demo-fixes-2026-11-11`) finds 6 lines. One is residue: commerce 480, listed above ([PR #26](https://github.com/ahmadtech26/ai-harness/pull/26)). The other 5 are law text: companies `04-المواد-87-119.md:39`, `07-المواد-191-227.md:64` and `09-المواد-265-289.md:129`, penal-code `05-المواد-273-325.md:62`, labour `00-المواد-1-32.md:154`.

## 6. Laws on the site that the library does not hold

The repository's copy of the site has 196 other law, regulation or instruction texts with at least five articles each. The full list, with page ids and article counts, is in the JSON under `other_laws_on_site`. Those closest to the product's work:

| Field | Texts on the site (page id) |
|---|---|
| Courts and procedure | قانون التحكيم (`doc-0356`), قانون استقلال القضاء (`doc-0455`), قانون القضاء الإداري (`doc-1174`), قانون المحكمة الدستورية (`doc-0721`), قانون تنفيذ الأحكام الأجنبية (`doc-0368`), قانون الكاتب العدل (`doc-0426`), قانون انتهاك حرمة المحاكم 1959 (`doc-0070`), قانون إدارة قضايا الدولة (`doc-1013`), قانون محكمة أمن الدولة (`doc-1624`), قانون محاكمة الوزراء (`doc-0489`), قانون إنشاء محاكم البلديات (`doc-0061`), قانون محكمة أمانة العاصمة (`doc-1630`), نظام رسوم المحاكم (`doc-0085`; the library holds only its schedule), نظام الرسوم وطوابع المرافعة 1966 (`doc-0093`), نظام وتعليمات الخبرة أمام المحاكم النظامية (`doc-0467`), نظام استعمال الوسائل الإلكترونية في الإجراءات المدنية (`doc-0476`), نظام الوسائل الحديثة في الإجراءات الجزائية (`doc-0466`), نظام المساعدة القانونية (`doc-0462`), النظام الداخلي لنقابة المحامين (`doc-0089`), نظام عوائد أتعاب المحاماة 1973 (`doc-0097`) |
| Property and civil | قانون الملكية العقارية (`doc-0539`, 220 articles), قانون ملكية الطوابق والشقق (`doc-0388`), قانون ضمان الحقوق بالأموال المنقولة (`doc-0461`), قانون إيجار الأموال غير المنقولة وبيعها لغير الأردنيين (`doc-0411`), قانون التركات للأجانب وغير المسلمين (`doc-1618`), قانون المحافظة على أملاك الدولة (`doc-1191`), قانون المعاملات الإلكترونية (`doc-0596`), قانون حماية البيانات الشخصية (`doc-3071`), قانون المسؤولية الطبية (`doc-0459`) |
| Commercial and finance | قانون الإعسار (`doc-0458`) and its regulation (`doc-0524`), قانون الأوراق المالية (`doc-0576`), قانون تنظيم أعمال التأمين (`doc-1192`), قانون التأجير التمويلي (`doc-1172`), قانون الوكلاء والوسطاء التجاريين (`doc-1598`), قانون المنافسة (`doc-1603`), قانون المنافسة غير المشروعة والأسرار التجارية (`doc-1628`), قانون الأسماء التجارية (`doc-1615`), قانون العلامات التجارية (`doc-1606`), قانون براءات الاختراع (`doc-1605`), قانون حق المؤلف (`doc-1201`), قانون تسجيل الشركات الأجنبية (`doc-0072`), نظام تصفية الشركات (`doc-1221`), قانون الضمان الاجتماعي (`doc-0385`) |
| Criminal | قانون الجرائم الإلكترونية (`doc-0429`), قانون المخدرات (`doc-1572`), قانون الجرائم الاقتصادية (`doc-1604`), قانون مكافحة غسل الأموال وتمويل الإرهاب 2021 (`doc-0589`), قانون منع الاتجار بالبشر (`doc-0491`), قانون منع الإرهاب (`doc-0479`), قانون الأحداث (`doc-1183`), قانون العفو العام 2024 (`doc-0478`), قانون تسليم المجرمين الفارين (`doc-0567`), قانون السير (`doc-1616`) |
| Public law | الدستور الأردني (`doc-0086`), قانون الجنسية (`doc-1614`), قانون الأحوال المدنية (`doc-0370`), نظام الخدمة المدنية 2020 (`doc-0610`) |
| Repealed (the site says so) | قانون الاستثمار الأردني الملغي (`doc-0389`), قانون تقسيم الأموال غير المنقولة الملغى (`doc-0393`) |

These are candidates only. Under decisions D14/D15, a law joins the library from LOB's consolidated text with its Gazette issue checked, not from this site. The site's pages can then serve as one more reading, as here.

## 7. What a named reviewer must confirm

1. **The website residue in section 5:** that each line is not law text, before any per-law pull request removes it. The flagged items are also for the reviewer to decide (*corrected 2026-11-13*: the list first spoke of «the four flagged items»).
2. **For the 8 aqel-lawfirm.com laws the site has:** the readings in law wording where jordan-lawyer.com and LOB agree against the corpus. The JSON lists each one (`site_agrees_with: "LOB"`, `kind: "wording"`). *Corrected 2026-11-13:* there are 404: landlords-tenants 6, commerce 137, companies 112, customs 56, income-tax 59, sales-tax 12, labour 12, execution 10. Glued captions (`kind: "trailing caption"`), chapter or part headings (`"chapter or part heading"`), commerce's «ملغاة» labels (`"repeal label"`) and the site's link text (`"website residue"`) are not corpus errors of wording. The 404 are the likeliest corpus errors, and each still needs the Gazette. One of them is not wording either: companies 273, where the corpus row joins 273 and 273 مكرر and LOB's 273 row holds 273 مكرر.
3. **For the 11 jordan-lawyer.com laws:** nothing here bears on the Gazette reading. The comparison with the Gazette in the main report stands as the open item.

## 8. The owner's export of the live site, 2026-11-13 (*added 2026-11-13*)

The owner ran `jordan_lawyer_export.py` from an ordinary connection on 2026-11-13. It took 3,148 posts and 103 pages through the site's WordPress API and page HTML, missing only one theme widget. The export zip has SHA-256 `326c8dd722c1811457daf65db61c05de83b1ecddd14c7cec456e79e9c4c4d337`; it is kept outside the repository. Each of the 19 law pages above was matched by title. *Corrected 2026-11-13:* 14 of the 19 pages were retitled to 2026, and 13 of those 14 were last modified on 2026-03-24 (court-fees on 2026-04-21); the five whose title has no year were not retitled. Each page was compared article by article with the January copy. The export is outside the repository, so this section is the owner's export result and cannot be checked from the repository alone; the JSON records, for each of the 48 articles that differ, the January and live words that differ, and lists the 37 articles found only on the live pages, each with a verdict on the live text or the reason it has none (`live_site_2026_11_13.detail`; *corrected 2026-11-13*).

- *Corrected 2026-11-13:* **In 34 of the 48 articles that differ, the January copy had filed article N+1 under N.** Its «N» holds live N's text followed by live N+1's (penal-code «420» and «456» hold two more each): where the January copy lost an article's label, the article ran on into the one before. January penal-code «9» holds corpus 10, and January execution «6» holds corpus 7. The 34 are civil-procedure 2, 133, 135, 140, 160, 167, 190, 205 and 212; evidence 10 and 52; penal-code 9, 84, 96, 104, 169, 173, 208, 213, 220, 224, 235, 238, 270, 320, 348 مكرر, 416, 420, 427, 445, 456 and 467; companies 251; execution 6. The JSON records each January N against live N+1 (`live_site_2026_11_13.january_filed_under_previous_number`). The comparison set January N against live N alone, so **«wording unchanged» is not established for these 34.** Compared as one block, January N against live N to N+1, the only words that differ are the heading or link words of N+1.
- **The other 14 articles** (*corrected 2026-11-13*). In 12 the only difference is heading or link words at the start or end: civil-procedure 198 and 225, civil-code 763, 1054 and 1449, evidence 74, penal-code 418 and 476, labour 142, criminal-procedure 370, magistrates-courts 22, court-fees 52. The site writes each article's heading as a link to a blog post, and the live copy also ends some pages with a list of related laws («قوانين أردنية مهمة»). Penal-code 332 is a heading placed differently. In execution 77 the opening words «ترفق بقائمة شروط البيع ما يلي» are on both copies; the January copy puts them on a line of their own, which the comparison read as a heading. The first version said «No article's wording changed», with 47 of 48 differences at the edges; it did not see the 34.
- *Corrected 2026-11-13:* **So the renaming to «حتى 2026» brought no new amendment into the 14 articles compared one to one, and the block comparison of the other 34 shows none.** The verdicts in sections 3 and 4 hold for the live site. Rerun on the live pages, they change only where the export's pages yield more articles, for example 485 penal-code articles instead of 462; the restatements in sections 3 and 4 find the same articles on the January page under the number before.
- **The 37 articles found only on the live pages** (*corrected 2026-11-13*). 36 are the N+1 articles above. The 37th is civil-procedure 1, whose January text has no article number (it sits under the link «التسمية وبدء العمل»). 22 have a verdict on the live text in the JSON (`live_only_verdicts`). The other 15 have none because the corpus and LOB do not differ in words there (formatting, normalisation only, numbering, or a trailing title), so the site has no reading to share: civil-procedure 1, 3, 136, 141, 161 and 206; evidence 53; penal-code 85, 97, 105, 239, 321, 457 and 468; execution 7. On each, the live text has the corpus's words (similarity 0.99 to 1.00; `live_only_reasons`).
- The page modification dates on the live site are 2022-02-20, 2022-07-24, 2024-07-11, 2025-02-11, 2026-03-24, 2026-04-21.
