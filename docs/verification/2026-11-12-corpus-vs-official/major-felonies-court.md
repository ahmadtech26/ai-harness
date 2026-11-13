# قانون محكمة الجنايات الكبرى (`major-felonies-court`): every article that is not identical to the official consolidated text

Draft, for lawyer review. Part of [the corpus verification of 2026-11-12](../2026-11-12-corpus-vs-official.md). The corpus side is the text as the product parses it (the corpus as it is); the official side is the Legislation and Opinion Bureau's consolidated text (LOB id 3244). The full texts of every article, identical ones included, are in [`2026-11-12-corpus-diff.jsonl`](../2026-11-12-corpus-diff.jsonl). Word differences are shown after the normalisation of level (b) and without the heading lines and paragraph numbers, so each line names a real change of words.

> **Review of 2026-11-13.** The first fix attempt was reverted; nothing below has been applied. The class "amendment not applied" is the detector's output, which the review found overstated: it fired on spelling variants, headings and quoted-for-deletion words, and it treated LOB as the ceiling (main report, [section 11](../2026-11-12-corpus-vs-official.md#11-known-defects-of-the-first-fix-attempt-reverted), D1 and D2). For this law: Article 4(ج): the lawyer must confirm against Gazette 5474 that 24/2017 put this paragraph into article 4 (review 2E).

## normalisation-only (10)

Equal once diacritics, tatweel, hamza seats, ى/ي, ة/ه, digits and punctuation are normalised. Each line: the first raw difference, corpus / LOB.

- المادة 2: «أدناه» / «ادناه»
- المادة 3: «تسمى (محكمة» / «تسمى( محكمة»
- المادة 6: «أو» / «او»
- المادة 7: «أية» / «اية»
- المادة 9: «أحكام» / «احكام»
- المادة 10: «أيام» / «ايام»
- المادة 11: «إذا» / «اذا»
- المادة 13: «الفقرتين (ب، ج)» / «الفقرتين( ب،ج )»
- المادة 14: «أو» / «او»
- المادة 15: «الأحكام» / «الاحكام»

## substantive difference (4)

### scope: body (3)

#### المادة 1
- word differences (1):
  - …ويعمل به من تاريخ **«1976»** … ⟵ المدونة ¦ LOB ⟶ …ويعمل به من تاريخ **«1986»** …

#### المادة 5
- word differences (2):
  - …تمارس المحكمه **«والنيابه»** العامه لديها الاختصاصات والصلاحيات… ⟵ المدونة ¦ LOB ⟶ …تمارس المحكمه **«النيابه»** العامه لديها الاختصاصات والصلاحيات…
  - …لقانون العقوبات وقانون اصول **«المحاكمات»** الجزاييه والقوانين الاخري المعمول… ⟵ المدونة ¦ LOB ⟶ …لقانون العقوبات وقانون اصول **«المحكمات»** الجزاييه والقوانين الاخري المعمول…

#### المادة 16
- word differences (1):
  - …بتنفيذ احكام هذا القانون **«للاطلاع علي مقال عن محكمه الجنايات الكبري وعنوانها وقضاتها واحكامها وكل ما يتعلق بها»** … ⟵ المدونة ¦ LOB ⟶ …بتنفيذ احكام هذا القانون **«—»** …

### scope: spacing-only (1)

#### المادة 8
- first difference: «العدلية إجراءات» / «العدليةاجراءات»

## amendment not applied (1)

### scope: body (1)

#### المادة 4
- corpus text equals LOB version «before 24/2017 (LOB 2232)»; LOB lists amendments of this article by: 13/2010, 24/2017
- amending law 24/2017: Gazette issue 5474, p. 4620
- word differences (1):
  - …الفقرتين من هذه الماده **«—»** … ⟵ المدونة ¦ LOB ⟶ …الفقرتين من هذه الماده **«لا يقبل الادعا بالحق الشخصي امام المحكمه وللمتضرر الحق في اللجو الي المحكمه النظاميه المختصه تستمر المحكمه في النظر في دعاوي الادعا بالحق الشخصي المنظوره لديها قبل نفاذ احكام هذا القانون المعدل»** …

> **المدونة:** تختص المحكمة بالنظر في الجرائم التالية حيثما وقعت في المملكة:
> 
> أ- جرائم القتل المنصوص عليها في المواد 326، 327، 328، 330، 338 من قانون العقوبات المعمول به.
> 
> ب- جرائم الاغتصاب وهتك العرض والخطف الجنائي المنصوص عليها في المواد من 292 الى 302 من قانون العقوبات المعمول به.
> 
> ج- الشروع في الجرائم المبينة في الفقرتين (أ) و (ب) من هذه المادة.

> **LOB:** أ- تختص المحكمة بالنظر في الجرائم التالية حيثما وقعت في المملكة:
> 
> 1- جرائم القتل المنصوص عليها في المواد 326-327- 328- 330-338 من قانون العقوبات المعمول به.
> 
> 2- جرائم الاغتصاب وهتك العرض والخطف الجنائي المنصوص عليها في المواد من 292 الى 302 من قانون العقوبات المعمول به.
> 
> 3- الشروع في الجرائم المبينة في الفقرتين( 1) و( 2) من هذه المادة.
> 
> ب- لا يقبل الادعاء بالحق الشخصي أمام المحكمة وللمتضرر الحق في اللجوء إلى المحكمة النظامية المختصة .
> 
> ج- تستمر المحكمة في النظر في دعاوى الادعاء بالحق الشخصي المنظورة لديها قبل نفاذ أحكام هذا القانون المعدل.

