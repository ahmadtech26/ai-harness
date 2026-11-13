# A third reading from jordan-lawyer.com (draft, for lawyer review)

**Draft, for lawyer review («مسودة، لمراجعة المحامي»).** *Corrected 2026-11-13, after the review of this branch ([`docs/reviews/2026-11-13-corpus-verify-review.md`](../reviews/2026-11-13-corpus-verify-review.md)):* the website-residue removals this report first described as committed were taken back with every other law-text change on the branch, so nothing in section 5 is applied. Section 4 no longer says the site "supports" the first fix attempt. Section 8 adds a check against the live site.

This adds one more reading to [the corpus verification of 2026-11-12](2026-11-12-corpus-vs-official.md). jordan-lawyer.com is a convenience copy. It can point to where a difference comes from, but it never proves a reading. Only the Official Gazette does. Nothing here marks any text as verified.

Data: [`2026-11-13-jordan-lawyer-third-reading.json`](2026-11-13-jordan-lawyer-third-reading.json). It holds every word-level verdict, the page hashes, the website residue found, the items flagged, the list of other laws on the site, and the check against the live site of 2026-11-13.

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

These are the body differences only (the words differ). Counts are word-level operations, not articles. *Corrected 2026-11-13:* «glued caption» counts the operations where the corpus article ends with the next article's caption and LOB's does not, and the site, like LOB, does not glue it; they are no difference of law wording. The earlier «site = LOB» column counted both kinds together.

| Law | corpus from | site page (articles found) | site = corpus | site = LOB, wording | site = LOB, glued caption | both | neither | not on the page |
|---|---|---|---|---|---|---|---|---|
| civil-procedure | jordan-lawyer.com | `doc-0415` (218) | 54 | 1 | 0 | 0 | 3 | 4 |
| civil-code | jordan-lawyer.com | `doc-0098` (1441) | 234 | 0 | 0 | 13 | 0 | 2 |
| evidence | jordan-lawyer.com | `doc-1609` (71) | 6 | 0 | 0 | 0 | 0 | 2 |
| landlords-tenants | aqel-lawfirm.com | `doc-0353` (22) | 3 | 6 | 9 | 0 | 1 | 0 |
| commerce | aqel-lawfirm.com | `doc-1627` (392) | 56 | 260 | 210 | 1 | 152 | 239 |
| penal-code | jordan-lawyer.com | `doc-0432` (462) | 147 | 1 | 1 | 4 | 0 | 29 |
| companies | aqel-lawfirm.com | `doc-1607` (308) | 60 | 134 | 108 | 4 | 6 | 5 |
| customs | aqel-lawfirm.com | `doc-1608` (253) | 60 | 104 | 99 | 1 | 7 | 0 |
| income-tax | aqel-lawfirm.com | `doc-0490` (82) | 3 | 59 | 35 | 2 | 1 | 0 |
| sales-tax | aqel-lawfirm.com | `doc-0487` (77) | 28 | 12 | 25 | 3 | 2 | 0 |
| labour | aqel-lawfirm.com | `doc-0073` (142) | 100 | 12 | 25 | 0 | 17 | 0 |
| execution | aqel-lawfirm.com | `doc-0395` (119) | 12 | 10 | 24 | 4 | 1 | 0 |
| mediation | jordan-lawyer.com | `doc-0451` (14) | 1 | 0 | 0 | 1 | 0 | 0 |
| criminal-procedure | jordan-lawyer.com | `doc-0416` (372) | 77 | 0 | 0 | 2 | 0 | 0 |
| courts-formation | jordan-lawyer.com | `doc-0367` (23) | 8 | 0 | 0 | 1 | 0 | 0 |
| magistrates-courts | jordan-lawyer.com | `doc-0450` (22) | 3 | 0 | 0 | 1 | 1 | 0 |
| major-felonies-court | jordan-lawyer.com | `doc-0399` (16) | 3 | 0 | 0 | 1 | 0 | 0 |
| court-fees | jordan-lawyer.com | `doc-0568` (52) | 14 | 0 | 0 | 20 | 0 | 0 |
| bar-association | jordan-lawyer.com | `doc-1162` (110) | 43 | 0 | 0 | 4 | 0 | 0 |

"both": the site has both readings (the passage occurs twice). "neither": the site has a third reading or the context did not match. "site = LOB" includes passages the site has under another article number: 148 of commerce's 470, companies 3, customs 5, income-tax 2, sales-tax 1 and labour 1. "site = corpus" likewise includes 2 such operations (commerce 1, customs 1) (*corrected 2026-11-13*).

What it shows:

1. **The 11 laws taken from jordan-lawyer.com:** the site shares the corpus reading in 590 operations and LOB's in 3. These differences were already on the site. They are not transcription errors made when the corpus was built.
   - The 3 exceptions are not differences of wording. They are words that on the site are links to its blog posts: penal-code 52 («انظر شرح المادة 52 …») and 332 («انظر مقال …»), both listed in section 5, and the heading words «( أسباب الطعن بالتمييز )» of civil-procedure 198, which are flagged.
   - The 4 "neither" cases are single words or short phrases where the corpus, the site and LOB do not all match, such as civil-procedure 164 «بنسبة» against LOB's «بنسنة», 217 «وقف» against «وفق», and magistrates-courts 19 «وقانون اصول» against «واصول» (*corrected 2026-11-13*).
   - More generally, the titles the corpus gives articles of these laws after «— » are the site's link titles. The official text has no such titles. The main report counts them as formatting.
2. **The 8 aqel-lawfirm.com laws the site has a page for** (not maritime-commerce or investment-fund): *Corrected 2026-11-13:* jordan-lawyer.com sides with LOB in 597 operations that differ in law wording, and in 535 more where the corpus has the next article's caption glued on; it sides with the corpus in 322.
   - In law wording, for commerce (260 to 56), companies (134 to 60), customs (104 to 60), income-tax (59 to 3) and landlords-tenants (6 to 3), a second unofficial copy does not share most of the corpus's departures from LOB. They point to the aqel-lawfirm.com copy (*corrected 2026-11-13*).
   - Labour is the exception: the site shares the corpus reading 100 times and LOB's 12 times in law wording (25 more are glued captions).

## 4. Amendments: is the site's text current?

For the articles the main report found out of date or missing, this is what the site's article has:

| Law | site matches LOB's text | site matches the corpus text | site differs from both | not on the page |
|---|---|---|---|---|
| companies | 39 | 3 | 9 | 0 |
| customs | 7 | 23 | 0 | 0 |
| labour | 9 | 1 | 0 | 0 |
| income-tax | 1 | 0 | 0 | 0 |
| sales-tax | 1 | 1 | 1 | 1 (4 مكرر) |
| execution | 1 (21 مكرر) | 0 | 0 | 1 (117 مكرر) |
| penal-code | 0 | 17 | 2 | 2 (422; 467 مكرر) |
| criminal-procedure | 0 | 9 | 0 | 2 (63 مكرر, 140 مكرر) |
| civil-procedure | 0 | 2 (182, 193) | 0 | 1 (191) |
| landlords-tenants | 0 | 2 | 0 | 0 |
| evidence | 0 | 1 (6) | 0 | 1 (75) |
| courts-formation, major-felonies-court, court-fees, bar-association | 0 | 1 each | 0 | 0 |
| civil-code | 0 | 0 | 1 (1287) | 0 |

*Corrected 2026-11-13:* the rows counted here are the detector's «amendment not applied» and «missing» rows, and many are not stale articles. Detector false positives (D1): courts-formation 15, court-fees 16, evidence 6, bar-association 61, penal 80, 99, 228, 287, criminal-procedure 68, 338, 341. No amendment content: penal 102, 300. Customs 14 (A2) differs only by LOB's caption and link. The columns were first headed «current» and «older», which assumed LOB was current.

- **For companies, labour and income-tax, a second unofficial copy carries LOB's text** for most of the articles the first fix attempt replaced. That makes them candidates for a passage-only fix, but it settles nothing. The site may copy LOB, and the review found defects inside those LOB texts (typos, glued words, stray «أو» in income-tax 34). The Gazette decides.
- **Where the review found the corpus newer than LOB** (*added and corrected 2026-11-13*): the site sides with the corpus at landlords-tenants 5 and 7, labour 137 and probably customs 161, where it is an independent copy. It also does at penal 99 and 306 and civil-procedure 182 and 193, but for the penal code and civil procedure the site is the corpus's own source. The exception is companies 265, where the site keeps LOB's pre-2017 «المحامي المدني». The regressions (D2) are A3, A10, A11, A18, A32 and A33. Listed apart: customs 168 (A1: the corpus already has 33/2018) and civil-procedure 182 and 193 (A25, A26: not shown stale). None of this is proof either way.
- **For the rows that survive the review, the site's own text is as old as the corpus's, despite page titles that say «حتى 2025»** (*corrected 2026-11-13*): penal 185, 208, 308 مكرر, 334 مكرر and 407 (probable 27/2017 updates), criminal-procedure 14, 136, 237 and 288, and civil-procedure 191 (absent from the January page). A page title on this site is no evidence that the text is current. The courts-formation, bar-association and mediation page titles carry no year.

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

*Corrected 2026-11-13:* the search for residue ran over the `sections/` shards of the 22 laws with these patterns: «انظر مقال», «انظر شرح», «للاطلاع على مقال», «المصدر\s*:», «موقع محامي», «حتى 20xx» at the end of a line, «https?://», «^<» and «<div», «&nbsp;», a date alone on a line, «تنزيل», «تحميل», «بصيغة», «Word», «اضغط», «شارك», «اقرأ»/«إقرأ», «مقالات ذات صلة» and «الوسوم». Its other matches were law text (for example «يشارك», «تحميل البضائع», «بصيغة الماضي»). It did not search for copyright footers, scripts, «-->», tables of contents, a lone «<» at the end of a line, editorial notes, inline reference numbers, or the folders' full copies; the rows added above come from the owner's session's scan.

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

1. **The website residue in section 5:** that each line is not law text, before any per-law pull request removes it. The flagged items are also for the reviewer to decide.
2. **For the 8 aqel-lawfirm.com laws the site has:** the readings in law wording where jordan-lawyer.com and LOB agree against the corpus. The JSON lists each one (`site_agrees_with: "LOB"`, `kind: "wording"`); glued captions (`kind: "trailing caption"`) are not corpus errors of wording. They are the likeliest corpus errors, and each still needs the Gazette (*corrected 2026-11-13*).
3. **For the 11 jordan-lawyer.com laws:** nothing here bears on the Gazette reading. The comparison with the Gazette in the main report stands as the open item.

## 8. The owner's export of the live site, 2026-11-13 (*added 2026-11-13*)

The owner ran `jordan_lawyer_export.py` from an ordinary connection on 2026-11-13. It took 3,148 posts and 103 pages through the site's WordPress API and page HTML, missing only one theme widget. The export zip has SHA-256 `326c8dd722c1811457daf65db61c05de83b1ecddd14c7cec456e79e9c4c4d337`; it is kept outside the repository. Each of the 19 law pages above was matched by title. *Corrected 2026-11-13:* 14 of the 19 pages were retitled to 2026; the five whose title has no year were not; 2026-03-24 is the pages' last-modified date. Each page was compared article by article with the January copy. The export is outside the repository, so this section is the owner's export result and cannot be checked from the repository alone; the JSON records, for each of the 48 articles that differ, the January and live words that differ, and lists the 37 articles found only on the live pages with their verdicts on the live text (`live_site_2026_11_13.detail`).

- **No article's wording changed.** 48 articles differ between the two copies. In 47 of them the only difference is heading or link words at the start or end. The site writes each article's heading as a link to a blog post, and the live copy also ends some pages with a list of related laws («قوانين أردنية مهمة»). The 48th, penal-code 332, is a heading placed differently.
- **So the renaming to «حتى 2026» did not bring new amendments into the text.** The verdicts in sections 3 and 4 hold for the live site. Rerun on the live pages, they change only where the export's pages yield more articles, for example 485 penal-code articles instead of 462.
- The page modification dates on the live site are 2022-02-20, 2022-07-24, 2024-07-11, 2025-02-11, 2026-03-24, 2026-04-21.
