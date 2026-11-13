# A third reading from jordan-lawyer.com (draft, for lawyer review)

**Draft, for lawyer review («مسودة، لمراجعة المحامي»).** This adds one more reading to [the corpus verification of 2026-11-12](2026-11-12-corpus-vs-official.md). jordan-lawyer.com is a convenience copy. It can point to where a difference comes from, but it never proves a reading. Only the Official Gazette does. Nothing here marks any text as verified.

Data: [`2026-11-13-jordan-lawyer-third-reading.json`](2026-11-13-jordan-lawyer-third-reading.json). It holds every word-level verdict, the page hashes, the residue removed, the items flagged and the list of other laws on the site.

## 1. Source and its limits

- **Which copy.** The live site refused this session: every request to `jordan-lawyer.com` on 2026-11-12/13 got HTTP 429 from the host's rate limiter, `robots.txt` included. So this reading uses the copy of the site's pages already held in this repository, `jordanian-law/references/docs/markdown/` (3,138 pages; its index was generated on 2026-01-27). The copy keeps no page URL or retrieval date, only each page's publication date. The SHA-256 of each page file used is in the JSON.
- **Pages added or changed on the site after January 2026 are not covered.** The Internet Archive holds the site's sitemap as of 2026-04-07, but `web.archive.org` is not reachable from this environment.
- **Coverage.** The site's pages hold most articles of each law: civil-procedure 218 of 229, penal-code 462, evidence 71. The site often writes an article's heading as a link to a blog post, and those headings were read too. Neither the copy nor the site has a page for the maritime-commerce or investment-fund law.

Method: for every word-level difference between the corpus (before the proposed fixes) and LOB, the same comparison as in the main report, the words on each side were looked for in the site's article of the same number. Each side was checked with three, then two, then one words of context, after the level (b) normalisation. If the article was not on the page, the whole page was searched. For every article LOB lists as amended after the corpus text ("amendment not applied") or that the corpus lacks ("missing in corpus"), the site's article was compared with both texts (word similarity of at least 0.9).

## 2. Where the corpus came from

Each law's shard files name their source:

| Source | Laws |
|---|---|
| jordan-lawyer.com | civil-code, civil-procedure, evidence, penal-code, criminal-procedure, mediation, courts-formation, magistrates-courts, major-felonies-court, court-fees, bar-association |
| aqel-lawfirm.com | commerce, maritime-commerce, companies, customs, income-tax, sales-tax, labour, landlords-tenants, execution, investment-fund |
| adaleh.info | majalla |

This decides what the third reading can show:

- **For the 11 laws taken from jordan-lawyer.com, the site is not an independent witness.** That the site agrees with the corpus shows only that the difference from LOB was in the source page, not made when the corpus was built. It says nothing about which reading the Gazette has.
- **For the 10 laws taken from aqel-lawfirm.com, jordan-lawyer.com is a second, independent copy.** Where it sides with LOB against the corpus, the corpus reading is most likely a fault of the aqel-lawfirm.com copy. It still needs the Gazette.

## 3. Word differences: which reading the site shares

These are the body differences only (the words differ). Counts are word-level operations, not articles.

| Law | corpus from | site page (articles found) | site = corpus | site = LOB | both | neither | not on the page |
|---|---|---|---|---|---|---|---|
| civil-procedure | jordan-lawyer.com | `doc-0415` (218) | 54 | 1 | 0 | 3 | 4 |
| civil-code | jordan-lawyer.com | `doc-0098` (1441) | 234 | 0 | 13 | 0 | 2 |
| evidence | jordan-lawyer.com | `doc-1609` (71) | 6 | 0 | 0 | 0 | 2 |
| landlords-tenants | aqel-lawfirm.com | `doc-0353` (22) | 3 | 15 | 0 | 1 | 0 |
| commerce | aqel-lawfirm.com | `doc-1627` (392) | 56 | 470 | 1 | 152 | 239 |
| penal-code | jordan-lawyer.com | `doc-0432` (462) | 147 | 2 | 4 | 0 | 29 |
| companies | aqel-lawfirm.com | `doc-1607` (308) | 60 | 242 | 4 | 6 | 5 |
| customs | aqel-lawfirm.com | `doc-1608` (253) | 60 | 203 | 1 | 7 | 0 |
| income-tax | aqel-lawfirm.com | `doc-0490` (82) | 3 | 94 | 2 | 1 | 0 |
| sales-tax | aqel-lawfirm.com | `doc-0487` (77) | 28 | 37 | 3 | 2 | 0 |
| labour | aqel-lawfirm.com | `doc-0073` (142) | 100 | 37 | 0 | 17 | 0 |
| execution | aqel-lawfirm.com | `doc-0395` (119) | 12 | 34 | 4 | 1 | 0 |
| mediation | jordan-lawyer.com | `doc-0451` (14) | 1 | 0 | 1 | 0 | 0 |
| criminal-procedure | jordan-lawyer.com | `doc-0416` (372) | 77 | 0 | 2 | 0 | 0 |
| courts-formation | jordan-lawyer.com | `doc-0367` (23) | 8 | 0 | 1 | 0 | 0 |
| magistrates-courts | jordan-lawyer.com | `doc-0450` (22) | 3 | 0 | 1 | 1 | 0 |
| major-felonies-court | jordan-lawyer.com | `doc-0399` (16) | 3 | 0 | 1 | 0 | 0 |
| court-fees | jordan-lawyer.com | `doc-0568` (52) | 14 | 0 | 20 | 0 | 0 |
| bar-association | jordan-lawyer.com | `doc-1162` (110) | 43 | 0 | 4 | 0 | 0 |

"both": the site has both readings (the passage occurs twice). "neither": the site has a third reading or the context did not match. "site = LOB" includes, for commerce, companies, customs, income-tax and sales-tax, a few passages the site has under another article number.

What it shows:

1. **The 11 laws taken from jordan-lawyer.com:** the site shares the corpus reading in 590 operations and LOB's in 3. These differences were already on the site. They are not transcription errors made when the corpus was built.
   - The 3 exceptions are not differences of wording. They are words that on the site are links to its blog posts: penal-code 52 («انظر شرح المادة 52 …») and 332 («انظر مقال …»), both removed below, and the heading words «( أسباب الطعن بالتمييز )» of civil-procedure 198, which are flagged.
   - The 4 "neither" cases are single words where the corpus, the site and LOB do not all match, such as civil-procedure 164 «بنسبة» against LOB's «بنسنة» and 217 «وقف» against «وفق».
   - More generally, the titles the corpus gives articles of these laws after «— » are the site's link titles. The official text has no such titles. The main report counts them as formatting.
2. **The 10 laws taken from aqel-lawfirm.com:** jordan-lawyer.com sides with LOB in 1,132 operations and with the corpus in 322.
   - For commerce (470 to 56), companies (242 to 60), customs (203 to 60), income-tax (94 to 3) and landlords-tenants (15 to 3), a second unofficial copy does not share most of the corpus's departures from LOB. They point to the aqel-lawfirm.com copy.
   - Labour is the exception: the site shares the corpus reading 100 times and LOB's 37 times.

## 4. Amendments: is the site's text current?

For the articles the main report found out of date or missing, this is what the site's article has:

| Law | site has LOB's (current) text | site has the corpus's (older) text | site differs from both | not on the page |
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

- **For companies, labour and income-tax, a second unofficial copy already carries LOB's text** for most of the articles the proposed fixes bring up to date. This supports those fixes, but it does not replace the Gazette.
- **The site's own text is out of date for the penal code, criminal procedure and the jordan-lawyer.com laws generally, despite page titles that say «حتى 2025».** A page title on this site is no evidence that the text is current.

## 5. Website residue found in the law text, and removed

Reading the site's pages next to the corpus showed text in the corpus that is not law text. It is page furniture the build carried over:
- the site's cross-links to its own blog posts («انظر مقال …»);
- a source credit;
- the site's link to its next page;
- stray `<div` lines.

Where it sat in a heading after «— », the product's parser read it as the first words of the article. The proposed fixes remove it, one law per commit. No word of law text changes.

| Law | Article | Removed |
|---|---|---|
| civil-procedure | 86 | the line «انظر مقال الأحكام القانونية للكشف والخبرة» at the head of the article |
| civil-procedure | 141 | «(انظر مقال الحجز التحفظي)» in the heading (the title «الحجز الاحتياطي» stays) |
| evidence | 11 | the heading's only words, «(انظر مقال عن السند العادي والإقرار الخطي)» |
| evidence | 27 | «(انظر مقال عن كيفية مناقشة الشهود)» at the end |
| penal-code | 10 | the heading's only words, «(انظر مقال عن الاختصاص الدولي الجزائي للمحاكم الأردنية)» |
| penal-code | 52 | «انظر شرح المادة 52» in the heading (the site's title «إسقاط دعوى الحق العام بإسقاط الحق الشخصي» stays, like every other site title) |
| penal-code | 332 | «(انظر مقال عن الإيذاء البسيط والإيذاء البليغ)» on the glued heading line (the heading «إيذاء الأشخاص» stays, like every other glued heading) |
| penal-code | 350 | «(انظر مقال عن التهديد بالقتل بوسيلة الكترونية)» at the end |
| penal-code | 421 | the heading's only words, and the same link at the end of paragraph 5, «(انظر مقال الشيك المكتبي وفقا لأحدث التعديلات)» |
| major-felonies-court | 16 | «للاطلاع على مقال عن محكمة الجنايات الكبرى …», the link text «محكمة الجنايات الكبرى», `<div` |
| courts-formation | 23 | «جدول رسوم المحاكم حتى 2025» (the site's link to its next page), `<div` |
| bar-association | 110 | «المصدر :  موقع محامي الأردن.», `<div` |
| mediation | 14 | `<div` |

Flagged for the reviewer, not removed:

| Law | Article | Text | Why |
|---|---|---|---|
| customs | 14 | «قرار مجلس الوزراء بالموافقة على تخفيض رسوم الجمركية https://lob.gov.jo/OPSHandler/…» | a link to an LOB attachment (the Cabinet decision), not article text |
| courts-formation | 23 | «11/3/2001» | a date after the last article: perhaps the law's date, not article text |
| mediation | 14 | «2/2/2006» | the same, at the end of the last article |
| magistrates-courts | 22 | «18/7/2017» | the same |
| civil-procedure | 198 | «( أسباب الطعن بالتمييز )» in the heading | on the site, a link to a blog post; kept like every other site title |

The search for residue covered every shard of the 22 laws. It looked for these patterns: «انظر مقال», «انظر شرح», «للاطلاع على مقال», «المصدر :», «موقع محامي», «تنزيل», «بصيغة», URLs, HTML tags, «حتى 20xx» at the end of a line, and dates alone on a line. Every other match was law text (for example «يشارك», «تحميل البضائع»).

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

1. **The residue removals in section 5:** that each removed line is not law text. The four flagged items are also for the reviewer to decide.
2. **For the 10 aqel-lawfirm.com laws:** the readings where jordan-lawyer.com and LOB agree against the corpus. The JSON lists each one (`site_agrees_with: "LOB"`). They are the likeliest corpus errors, and each still needs the Gazette.
3. **For the 11 jordan-lawyer.com laws:** nothing here bears on the Gazette reading. The comparison with the Gazette in the main report stands as the open item.
4. **Whether the site has changed since January 2026.** That needs the live site or the Internet Archive's copy, and neither was reachable from this session.
