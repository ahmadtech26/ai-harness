> Copied from the local main session's records on 2026-11-13 for cloud agents. Paths under `.hq/` or `D:/Iqraa Law/` point to local evidence that is not in this repository; the findings themselves are complete here.

# Review of the distillation branch (al-Sanhuri principles, AQEL 1.4), 2026-11-12

- **Branch:** `ahmadtech26/ai-harness` `origin/distill/book-principles-2026-11`, head `ff5cd5c`, base `49ad460`
  (= `demo-fixes-2026-11-11`, which holds the live instructions). Reviewed read-only from the worktree
  `D:/Iqraa Law/AI Harness-distill`.
- **Written by:** a cloud agent, from `docs/handoff/2026-11-12-state-for-cloud-agents.md` (owner decisions D1-D19 and
  the rules for proposals in its section 6).
- **Reviews merged here (seven):** four legal reviews by theme (T01-T07, T08-T13, T14-T18, T19-T23), one
  build/test/compose review, one product-safety review, and one source-fidelity review. None of them ran git or
  touched the live demo or its containers. None edited the worktree. Their notes and scripts are listed in the appendix.
- **Status of everything below:** findings and proposals. The owner decides. Nothing here is applied.

## Bottom line

Nothing in this branch should go live as committed. The work is careful in three ways. All 1,019 article citations
checked resolve to an article in the corpus. The text that would ship shares no run of seven or more words with any of
the book's 12 volumes. None of the model-facing text gives the model an article number, a period, or an amount (one
search term aside).

Three problems block it:

1. **Law.** 22 catalogue entries misstate Jordanian law, and 48 more need smaller corrections. Seven of the 22
   reach lines the model would read: four plainly (V10-05, V1A-22, V1B-09, V2-06) and three partly (V1A-09, V1B-27,
   V1B-22). The catalogue's own second review («التحقق: … القانون الأردني: ok») marks several of the wrong entries as
   fine, so it cannot be relied on.
2. **Packaging.** Merged as committed, the branch changes the live prompt even with v1.3 still selected. The pinned
   skill was edited, which changes the composed sha256 from `4c60fa94` to `855c343e`. The branch also lists a new
   skill that the instance does not have and that the instructions-only apply path cannot install.
3. **Owner decisions.** The D10 block departs from the planned plan-line grammar, and its visible plan conflicts with
   v1.3's rule on tool details. Both are owner decisions.

## 1. Verdict per deliverable

**How the verdicts were set.** Handoff section 6 and D16/D17 put every model-facing text with legal substance behind
the lawyer. So:

- **only after the lawyer**: the text is model-facing and carries legal substance. The listed fixes are prerequisites,
  and the lawyer is the gate.
- **adopt after listed fixes**: the deliverable has no legal substance, or the model never reads it.
- **reject**: the deliverable should not be merged in its committed form.

No deliverable qualifies for "adopt now".

| # | Deliverable | Verdict | Why |
|---|---|---|---|
| 1 | Catalogue `docs/distillation/2026-11-12-book-principles.md` (260 entries, T01-T23) | **Adopt after listed fixes** | The model never reads it; it is the lawyer's working draft. Its citations are sound: 1,019 of 1,019 resolve, and 20 of 20 spot-checked book pages discuss what the entries say. But 22 entries misstate Jordanian law and 48 need smaller corrections (section 2). Its «التحقق» lines say "ok" on several wrong entries (V3-22, V3-03, V2-11, V2-23, V2-29, V1B-09). Correct it before the lawyer spends time on it. The owner answers licence questions 1-3 (section 4) before it is merged into a branch others work from, or mirrored. |
| 2 | AQEL 1.4 distilled checks (`DISTILLED_CHECKS_AR/_EN` in `content/prompts/build_aqel.py:501-582`) | **Only after the lawyer** | This is legal method, appended to every prompt on all three tiers. No reviewer found an error of law in the nine bullets. They contain no digit and no article number. All 26 v1.3 rule phrases and all 22 slugs survive unchanged. Before the lawyer sees it, three things must change. (a) The block asks for retrieval on many topics with no budget qualifier. That works against v1.3's 8-text and limit=3 budget, and invites the thin, spread-out searching seen on 2026-11-11. (b) It hard-codes laws as "not loaded", including personal status, which D14/D15 will add. (c) Its contract-grade list differs from the skill's list. Cost: +6,257 characters, about 1,780 tokens on every model call. A staging bench must come before release. |
| 3 | D10 reasoning sequence (`build_aqel.py:597-633`, `REASONING_SEQUENCE_AR/_EN`) | **Adopt after listed fixes** | This is the owner's own design (D10), with no legal substance. The six headings, their order, their placement after «لغة التفكير», the «تعديل الخطة:» line and the "no article number in the plan" rule all match handoff section 5. It reinforces Arabic-only reasoning and lowers nothing. Two problems: the visible plan line names the law in Arabic, where the plan calls for a slug, so the planned telemetry regex never matches; and the visible `limit=<عدد>` conflicts with v1.3's tool-details rule. Fixes: the owner decides both (section 6); split D10 into its own edition so it can be taken without the lawyer-gated checks; ask for Western digits in `limit=`; update the tests. Cost: +1,338 characters, about 380 tokens per call. |
| 4 | New skill `content/skills/jordanian-civil-issue-map/` (SKILL.md + 9 references, 260 lines) | **Only after the lawyer** | It is method-shaped. It has no digits and no article numbers, and all 564 search terms occur in the named law. But the errors of seven catalogue entries reach its lines (eight lines, counting the checklist copy; section 2, column "reaches the model"). 42 search terms are legal propositions, and one is an amount («ثلث التركة»). 25 lines mention Egyptian law. Two lines invite fiqh from memory. Every reference file starts with a comment naming al-Sanhuri, and the model reads it. It cannot reach the agents through the instructions-only apply. Its paths are bare (`references/…`). Its cost against `recursion_limit` 16 has not been benched. |
| 5 | Pinned-skill edits (`content/skills/jordanian-case-analysis/SKILL.md`, 1.0.0 → 1.1.0, lines 24, 27, 34) | **Reject (as committed)** | These lines change the live composed prompt even on v1.3, with no edition gate: `4c60fa94` → `855c343e`, +420 characters on every call. Two of the three lines repeat 1.4 bullets 3 and 5, so under 1.4 the same guidance would appear three times per prompt (Arabic, English, pinned). The third line points every civil question to a skill that is not deployed. The right final form is different: one pointer line, in the skill's own commit, landing only with the approved and deployed skill. |
| 6 | Document-review checklist (`content/skills/legal-document-review/references/review-checklist.md`, 879 → 15,144 characters; plus the pointer at `legal-document-review/SKILL.md:26`) | **Only after the lawyer** | It adds 50 lines copied byte for byte from the issue map. They carry the same legal content and the same problems: V10-05 at `:9`, fiqh from memory at `:16`, propositional terms such as `:54`. No test covers them. SKILL.md step 4 also points to the issue map, so both copies can load in one answer. Keep one route only (section 5). |
| 7 | `content/specialists/aqel.json` (adds `jordanian-civil-issue-map` to `skills`) | **Only after the lawyer** | The one-line listing is right in itself, but only once the skill is approved and inside a release image. As committed, `content/release.mjs:96-100` `skillIds()` fails with "skill … is not deployed on this instance" (`RELEASED.json` is still empty). Once deployed, it would expose a draft skill to all three tiers while v1.3 is live. `instructionsFile` correctly still names v1.3. Move the listing into the skill's commit. |

## 2. Legal error list

**What counts.** An entry is counted when it does one of four things. (i) Its statement of Jordanian law is
contradicted by a corpus article or by the explanatory memorandum. (ii) It drops a condition or qualifier that the
Jordanian text has, or misreads that text's scope. (iii) It leaves out an in-library article that decides its point.
(iv) It presents as law, without saying so in the entry, a point that no Jordanian article supports.

Three kinds of finding are **not counted** and are listed separately at the end of this section: claims about the
Egyptian side that rest only on reviewer recall, Egyptian rules that the entry itself flags in «الفرق», and drafting
slips such as stale notes, confidence labels and titles.

**Count: 70 entries.** 22 are in table A (wrong; fix before the lawyer sees the catalogue), 18 in table B (qualifier
dropped, overstated or misparaphrased) and 30 in table C (no Jordanian article, or a missing citation). Line numbers
refer to `docs/distillation/2026-11-12-book-principles.md`. All corpus quotations were checked by the reviewers. Four
of them (civil-code 247, 304, 1004 and 1149) were checked again for this report.

### A. Wrong on Jordanian law (22)

"Reaches the model" says whether the error also appears in a line the model reads (skill references or checklist). The
1.4 prompt bullets carry none of these errors.

| # | Entry (line) | Jordanian citation | What is wrong | Fix | Reaches the model |
|---|---|---|---|---|---|
| A1 | V1A-09 (350, note 355) | civil-code 106; **missing civil-code 1149** | The entry says whether a judgment can stand in for a promised contract over land depends on land-registration laws «غير الموجودة في المكتبة». The Civil Code in the library settles it. civil-code 1149: «التعهد بنقل ملكية عقار يقتصر على الالتزام بالضمان إذا أخل أحد الطرفين بتعهده». | Add civil-code 1149. Reword the real-estate sentence so the model searches that rule before it suggests a judgment in place of the contract. | Partly: `contracts.md:35` asks "judgment or compensation?" but never sends the model to 1149. |
| A2 | V10-05 (184) | civil-code 240; **missing civil-code 73, 77; evidence 28-30** | (1) It uses 240, which reads doubt in the debtor's favour when interpreting a contract, to settle doubt over whether a suretyship exists at all. That is a proof question: the burden lies on the claimant, and the writing rules apply. (2) «مسؤولية تقصيرية إذا صدرت عن عمد أو رعونة» is Egyptian fault language with no Jordanian article. Jordanian harm rests on الإضرار, with التعدي or التعمد for the causer (civil-code 256-257). | Keep 240 for the extent of the surety's obligation. Cite 73/77 and evidence 28-30 for its existence. Drop the «عمد أو رعونة» clause, or recast it through 256-257. | **Yes**: `contracts.md:18` and `review-checklist.md:9`. The search term «يفسر الشك في مصلحة المدين» is used for the existence question. |
| A3 | V1A-22 (512) | civil-code 207; **missing evidence 12** | It adds a third condition for binding a successor in title: the contract must have a fixed date before the transfer. 207 sets only two: the right is among the thing's مستلزمات, and the successor knew of it. Whether a date counts against third parties is an Evidence Law rule: evidence 12, «لا يكون السند العادي حجة على الغير في تاريخه الا منذ أن يكون له تاريخ ثابت». | Keep 207's two conditions. Treat the date as a proof question, citing evidence 12. | **Yes**: `contracts.md:54` «وأسبقية تاريخ العقد». |
| A4 | V1B-09 (729, method 736) | civil-code 266, 268 | It states rules as law with no Jordanian article (the entry's own note says so): only certain harm is compensated, probable harm is not, a lost chance is certain harm measured by its probability, and the harmed interest must be lawful. The method line still tells the model «ولا تطالب بالاحتمالي». The second review marked it ok. | The method asks whether each item of harm has happened, is certain to happen, or is only probable, then sends the model to 266 and 268. Drop the instruction, or mark it as doctrine for the lawyer. | **Yes**: `harm-and-enrichment.md:17`. |
| A5 | V1B-27 (912) | civil-code 301, 302, 307; **missing civil-code 304** | It says a gestor (فضولي) need only show ordinary care, even if the result is not achieved. That is the Egyptian rule. civil-code 304: «الفضولي مسؤول عما يلحق رب العمل من اضرار وللمحكمة تحديد الضمان إذا كانت الظروف تبرر ذلك». The Jordanian text has no ordinary-care threshold. | Cite 304. Correct the difference note and the method line. | Mildly: `harm-and-enrichment.md:35` «والعناية المبذولة». |
| A6 | V1B-22 (850) | labour 86, 89; **missing civil-code 788-789** | It says doctors, lawyers and engineers are, in principle, bound only to use care. For buildings, civil-code 788 makes the engineer and the contractor jointly liable for collapse and for defects that threaten soundness, even when the cause is a defect in the land. 789 divides that liability. Medical liability sits under a special law that is not in the library (reviewer recall). | Cite 788-789. Confine the care statement to what a Jordanian text supports. Add a step: check for a special professional-liability law, and say when the library lacks it. | Mildly: `harm-and-enrichment.md:27` «ومعيار العناية المطلوب» takes the care standard for granted. |
| A7 | V3-22 (1589; note 1594; check 1598) | civil-code 247 | It says impossibility must be permanent, and that a temporary one «توقف التنفيذ فقط». 247: «ومثل الاستحالة الجزئية الاستحالة الوقتية في العقود المستمرة وفي كليهما يجوز للدائن فسخ العقد بشرط علم المدين». The entry is marked high confidence and "ok". | Limit "temporary only suspends" to the book's Egyptian view. Add the 247 rule for continuing contracts. Change the check line to partly. | No (`obligations.md:56` asks only "permanent or temporary"). |
| A8 | V3-03 (1347; note 1352) | civil-code 393-401, 400; memorandum note on 393-401 | It says the memorandum "does not address retroactivity, so do not commit either way". The memorandum adopts the fiqh view that a condition has no retroactive effect, citing Majalla 82, which civil-code 400 reproduces. | Rewrite the note and drop the "no finding without case law" advice. Cite civil-code 400; Majalla 82 is then redundant. | No (`obligations.md:30` sends the model to the memorandum). |
| A9 | V2-11 (1054; note 1059) | evidence 30 | It says Jordan made the Egyptian inferred exceptions express, including interpretation of the deed and defects of consent. evidence 30 lists only its own seven items: fraud, deception and duress with the facts specified, the drafting circumstances, the deed's relation to another deed, illegality, and so on. It names no mistake, no exploitation, and no interpretation of an ambiguous deed. | List evidence 30's seven exceptions exactly. Mark the "not a contradiction of the writing" list as the book's doctrine. | No (`proof.md:20`). |
| A10 | V3-01 (1323; 1327-1328) | civil-code 393, 402; **missing civil-code 396** | It says the certainty test (a condition is uncertain, a term is certain) "appears in the two Jordanian definitions". Neither 393 nor 402 contains it. The uncertainty requirement for a condition is in 396 («معدوما على خطر الوجود لا متحققاً ولا مستحيلاً»). For a term, only the memorandum (note 303) states it. | Cite 396. Attribute the term test to the memorandum. | No (`obligations.md:28`). |
| A11 | V2-06 (995; 999-1000) | civil-procedure 87, 88 | It says the fine falls on whoever "fails to prove" a denial or a forgery claim. 87(2) fines the person when the investigation shows the denial or the claim to be untrue. For a denial, the burden lies on whoever produced the deed (88, «بناء على طلب مبرز السند»). The forgery claimant's burden is stated with no article. | Paraphrase 87(2) correctly. Cite the forgery claimant's burden, or flag it as doctrine. | **Yes**: `proof.md:15` «جزاء الإخفاق في الإنكار أو التزوير». |
| A12 | V1B-17 (1163; 1165-1167) | civil-code 268 | It says a later, unforeseen worsening «يجيز مطالبة جديدة». 268 only lets the court reserve a right to ask for review «خلال مدة معينة», and the paraphrase drops that period. | Say: check whether the judgment reserved a review right, and for what period. Restore «خلال مدة معينة». | No (`obligations.md:9`). |
| A13 | V2-23 (1223; 1225) | civil-code 364, 361, 107; memorandum on 364 | It states as settled that a penalty clause is due only with fault (خطأ), harm, causation and notice, that it falls with rescission, and that it cannot be claimed while specific performance is possible. Only "compensation must be due" (memorandum on 364) and notice (361) have Jordanian support. «خطأ» is the Egyptian term that 1.4's own harm bullet tells the model not to build on. The check line says ok. | Present these as the book's doctrine. For Jordan, state only what 361, 364 and the memorandum support. Mark the rest "search; no Jordanian text". | No (`obligations.md:14`). |
| A14 | V2-29 (1297; 1299) | civil-code 368 | It says that for simulation «لا يشترط إعسار ولا دين مستحق ويكفي إثباتها». 368(1) gives the choice only to creditors and special successors «متى كانوا حسني النية», and only against a contract «الذي أضر بهم». Both Jordanian conditions are dropped. | Add good faith and harm under 368. Flag the rest as the book's view. | No (`obligations.md:23`). |
| A15 | V45-06 (1722) | civil-code 558; **missing civil-code 566, 1148** | It says a Jordanian gift is complete on delivery «لا بالرسمية», without limit. 566 makes a gift's effect depend on the procedures the law requires for transferring ownership, and frees only movables from registration. 1148: «لا تنتقل الملكية … الا بالتسجيل». | Limit «لا بالرسمية» to movables, or add 566 and 1148 and say a gift of real estate depends on registration. | No (`sale-and-property-contracts.md:13`). |
| A16 | V6-15 (2096) | civil-code 684(2) | It says the lessor warrants against any third party's claim of right («مستأجر آخر، مشترٍ، صاحب ارتفاق»). 684(2) covers only another lessee, or a person who took the right from the lessor. A third party with independent title is not covered by any cited article, and the note says it «يقارب المصري» without mentioning the narrower scope. | Narrow the list to 684(2). Mark the independent-title example as the book's. Add a search step. | No (`lease.md:18` matches 684(2)). |
| A17 | V7-12 (2371) | civil-code 836(2), 837, 838 | It opens with the Egyptian rule «الوكالة العامة لا تخوّل إلا الإدارة». 836(2) says a general agency allows exchanges and dispositions other than gifts, which need express mention. Only «الفرق» records this. It also states a burden-of-proof rule with no evidence-law article. | Lead with the tension between 836(2) and 837/838, and mark the Egyptian rule. Cite an `evidence` article for the burden, or flag it. | No (`work-and-insurance.md:19`). |
| A18 | V10-19 (3137; 3142) | civil-code 1343, 1398; **missing civil-code 164(2)** | It says Jordanian law keeps the mortgage valid «بإطلاق دون استثناء الشرط الدافع». The general rule in 164(2) contains exactly that exception («ما لم يكن الشرط هو الدافع الى التعاقد فيبطل العقد ايضا»). Whether 1343 displaces it is an open question, yet the entry states it as settled, at high confidence. | Cite 164(2). Say the relation between 1343 and 164(2) must be checked. Lower confidence to متوسطة. The possessory-pledge part rests on recall (see the list below). | No (`securities.md:26`). |
| A19 | V10-27 (3238) | **missing civil-code 1004** (and 1424) | It says «ولم أجد نصاً أردنياً صريحاً على بقاء الامتياز مع الحوالة». civil-code 1004: «تبقى للدين المحال به ضماناته بالرغم من تغيير شخص المدين». A privilege is an accessory real security (1424). The entry's own V10-14 note (3087) cites 1004. | Cite 1004. Explain that Jordanian حوالة changes the debtor, and that the library is silent on a creditor-side transfer and on subrogation. | No (`securities.md:34`). |
| A20 | V89-27 (2895; 2900; check 2904) | civil-code 1181, 1182, 1184 | It says the library's prescription texts are limited to movables and unregistered real property. 1184 bars the absolute-ownership claim against a possessor of real property with no "unregistered" limit; only 1181 and 1182 carry «غير مسجل». It stays at high confidence although the second review said partly. | Limit the claim to 1181-1182. Say that 1184 has no registration qualifier and that registered land depends on laws outside the library. Lower confidence. | No (`property.md:39`). |
| A21 | V89-19 (2802; 2807) | civil-code 1127; **missing evidence 12** | The السند paraphrases 1127 as alternatives (official papers, OR the testator's hand and signature, OR a certified signature). The corpus text is cumulative: «أوراق رسمية محررة بخط المتوفى وعليها إمضاؤه». The corpus may be missing an «أو», but either way the tool will return a different text from the paraphrase. «ووصف التصرف يفصل فيه القاضي المدني» has no anchor. The entry relies on «ثابت التاريخ» without evidence 12. | Quote 1127 as the corpus has it and flag it for the Gazette check. Drop or qualify the jurisdiction sentence. Add evidence 12. | No (`property.md:31`). |
| A22 | V89-20 (2814; note 2825) | civil-code 1140, 1141, 1176; **missing civil-code 73, 77; evidence 28, 29** | It states a proof rule for builders (juristic act versus material fact) with no anchor. It stretches 1176, which concerns a possessor's good faith, to put the burden on the landowner. It turns 1141's option («كان للمحدث ان يمتلك») into an automatic result («تملكها المحدث»). | Anchor the proof rule to evidence 28/29 and the burden to 73/77, or remove it. Mark the use of 1176 as inference. Restore 1141's optional wording. | No (`property.md:32`). |

### B. Qualifier dropped, overstated or misparaphrased (18)

| Entry (line) | What is wrong | Fix |
|---|---|---|
| V1A-04 (291, 296) | Leaves out civil-code 1149 (promise to transfer real property). The "writing for proof only" point has no Evidence Law anchor. | Add 1149. Point the form-for-proof branch to evidence 28-30. |
| V1B-01 (638-639) | Offers civil-code 358 as the "closest text" limiting contractual exemption clauses. 358 is a duty-of-care rule for obligations of preservation or management. | Say no general Jordanian article on exemption clauses was found; 358(2) applies only to obligations of care. |
| V1A-06 (319) | Labels civil-code 96 «خيار المجلس». The article covers only withdrawing an offer before acceptance, and the label could lead the model to claim a right to undo the contract after acceptance. | Use the article's own wording. |
| V3-04 (1359) | civil-code 404(1) requires a judgment («إذا حكم بإفلاسه أو إعساره»). The principle and the paraphrase drop it. | Restore the judgment requirement. |
| V2-03 (960) | civil-code 372 requires assets that exceed the debts («يزيد»), not assets that are merely "enough" («كفاية»). | Correct the wording. |
| V2-09 (1030) | The paraphrase of evidence 28 drops «ما لم يوجد اتفاق أو نص يقضي بغير ذلك». | Restore the qualifier. |
| V2-12 (1066) | «أو ممن يمثله» is not in evidence 30. | Remove it. |
| V2-18 (1137) | «مع التسبيب» is not in civil-procedure 86. | Remove it. |
| V1B-15 (924) | The notes treat the bar in criminal-procedure 6(2) as absolute; 6(3) allows the claim to be moved to the criminal court. | Correct the notes. |
| V45-04 (1698) | The paraphrase of civil-code 184 drops «في العقود التي تحتمل الفسخ». | Add the limit. |
| V45-22 (1908) | Calls revocation of a gift by consent «إقالة». civil-code 580 calls it «إبطالا لأثر العقد». | Use 580's term. |
| V45-24 (1930) | Says a partner exempted from loss OR excluded from profit affects the partnership. civil-code 590 pairs the two conditions. | Align with 590, or flag the "or" version as the author's. |
| V6-17 (2120) | Says rent «تسقط أو تنقص بقدر ما فات» in general. For partial loss, civil-code 697(2) gives rescission. The note also leaves out 687 (rent reduction for a defect). | Add 687 and qualify the principle. |
| V7-01 (2252) | «متى توافرت التبعية قُدّم قانون العمل» ignores the exclusions in labour 3 (public servants and municipal employees; agricultural and domestic workers go to a regulation). civil-code 832(2) applies only to workers subject to the Labour Law. | Add labour 3 and a scope-check step. |
| V89-22 (2843) | The paraphrase of civil-code 1159 drops the limit in 1159(4): amiri land «التي تحت يد المستحقين لمنفعتها». | Restore the qualifier. (The kinship "difference" is in the recall list below.) |
| V89-10 (2683, 2688) | «ولو قبل القسمة ما لم يُجزه» is not in civil-code 1031. Pairing 1031, which says ابطال, with 153 (فسخ for mistake) weakens the special text. | Mark the before-partition point as the author's. Let 1031 govern and drop 153. (The timing "difference" is in the recall list.) |
| V89-09 (2671) | «القانون الأردني حسم المسألة» overstates civil-code 1144, which applies only once partition is requested. | Say «يعالج حالة طلب القسمة» and keep the open question about 1035. |
| V6-30 (3275) | Says landlords-tenants 5 applies "its provisions" to pending cases. 5(أ)(4) says «أحكام هذه المادة», and carves out cases decided under Law 22/2011. | Say "this article" and mention the carve-out. |

### C. Stated as law with no Jordanian article, or a citation missing (30)

The fix for each of these is the same unless the row says otherwise. Either add the article, or tag the point
«من الشرح المصري — لا نص أردني في المكتبة», as the catalogue's section 1 promises.

| Entry (line) | Unsupported point, or missing citation |
|---|---|
| V2-17 (1125) | A change of legal basis opens a new action; res judicata covers reasons tied to the operative part. |
| V2-26 (1261) | A mere licence (رخصة) is excluded; the defendant may raise its defences against the debtor. |
| V2-30 (1309) | Connection arising from harm caused by the thing (civil-code 389 covers expenses only). |
| V3-06 (1383) | An implied solidarity agreement must be decisive; doubt counts against solidarity; the creditor bears the burden. |
| V3-08 (1407) | Mutual representation of co-debtors in acts that benefit them (435-438 apply it, but no article states it). |
| V3-16 (1518) | The conditions for a valid real offer. |
| V3-17 (1530) | The debt does not revive if the substitute performance is evicted. |
| V3-19 (1554) | Judicial set-off takes effect from the judgment. |
| V2-07 (1007) | Missing citation: evidence 11 (the date of an ordinary deed binds its parties); evidence 30(4) and 30(7) (proving antedating). |
| V2-19 (1175) | Missing citation: civil-code 448 (impossibility from a foreign cause ends the obligation). |
| V45-05 (1710) | «معيار الخبرة يحتاج إلى اتفاق صريح». Rephrase as a question (who decides the trial result under the contract) or drop it. |
| V45-09 (1757) | «الشيخوخة ليست مرضاً» and the chronic-illness rule. Align with the test in civil-code 543 and mark both as the author's. |
| V45-16 (1838) | «ولا من أخفى عمداً سبباً يعلمه». |
| V45-21 (1897) | The cap «لم يلتزم الموهوب له بأكثر من قيمة الموهوب», and the exclusions for a natural obligation and for a reward. |
| V45-26 (1953) | The commercial-interest claim has no citation. Cite commerce 110, as top-10 row 7 (line 142) already does. |
| V6-13 (2072) | Narrow reading of a clause that moves repairs to the lessee; «على المؤجر في التقنين الحديث». |
| V6-23 (2179) | The surety does not carry into a tacit renewal; capacity and applicable law are judged at renewal. Phrase these as questions. |
| V7-10 (2347) | «ويُفسَّر الشك لصالح المنع». |
| V7-14 (2395) | Burden allocation for apparent agency. Cite an `evidence` article or mark it as the author's. |
| V7-17 (2430) | «ويقع عليه هو عبء إثبات ذلك». Cite or mark. |
| V7-20 (2466) | Three Egyptian case-law points, one of them a presumption. Also correct the stale note: civil-procedure 32 is cited, and correctly. |
| V7-23 (2504) | The presumption from vague answers, and the other book points. Add a note on civil-code 923 (it sends missing rules to special insurance laws, which are not in the library). |
| V7-27 (2551) | «العمد المبرَّر» and non-intentional fault, stated generally. civil-code 934-935 cover fire insurance only. |
| V89-02 (2588) | The average-neighbour test and the mitigation measures are not in civil-code 1027. The compensation route has no citation: cite 256 or say "needs research". |
| V89-13 (2718) | «ويسقط الحق فيه بالإجازة الصريحة أو الضمنية بعد العلم». |
| V89-29 (2919) | The ownership-claim and contractual-return proof statements. Cite civil-code 73/77 or mark them. |
| V10-06 (2981) | «لا يزيد عبئاً على التزام الأصيل وقد يقل» (nothing in civil-code 946-1017). |
| V10-14 (3077) | «ويحتج الكفيل بذلك ولو نزل المدين عنه». |
| V10-18 (3125) | Relies on «ثابت التاريخ» without evidence 12. Add it. |
| V10-26 (3221) | Same as V10-18. Add evidence 12. |

### Not counted: lawyer to confirm (the Egyptian side rests on reviewer recall)

Leave the wording as it is and tag each point «يؤكده المحامي». The library holds no Egyptian law.

- V1A-16 (427): the "Jordanian features" «بغير حق» and threats to relatives or honour may be shared with Egyptian
  art. 127.
- V89-25 (2877): the deferred-price rule may be shared with Egyptian art. 945(2). One part is not recall: the
  real difference, recourse against the seller or the buyer under civil-code 1165(3), is missing, so add it.
- V89-22: the kinship exclusion may reproduce Egyptian art. 939(b).
- V89-10: the timing rule may match Egyptian art. 826/2.
- V89-19(b): Egyptian Wills Law 71/1946 art. 2 may have the same claim-hearing rule.
- V10-19: Egyptian art. 1108 may already extend the bar to possessory pledge.
- V6-02 (3297): the Egyptian rent regime is described in the present tense, from the treatise's era.

### Not counted: Egyptian rule stated in «المبدأ» and flagged only in «الفرق» (presentation)

- V3-09 (1418, civil-code 265)
- V3-28 (1660, civil-code 1162)
- V7-08 (2323, civil-code 790)

Fix: mark the Egyptian rule inside «المبدأ» itself.

### Not counted: drafting (fix with the corrections)

**Stale or contradictory notes:**

- V1B-07 (706/716): header عالية, notes say متوسطة and "memorandum not read".
- V1A-13 (482).
- V10-04 (2979).
- V10-12 (3063).
- V10-23 (3195).
- V2-02 (948): «خلافاً لما ورد في البند», and Majalla advice that contradicts the note.

**Missed sources and wording:**

- V1B-20 (830): cite the memorandum's actual-control reading (السيطرة الفعلية).
- V10-09 (3017) and section 7 (3326): "no Jordanian article at all" is inaccurate for V10-09 and V10-23. Say "no
  Jordanian article for the Egyptian institution itself".
- V89-03 (2600): present majalla 1199 as historical background only. civil-code 1024 carries the rule.

**Confidence labels:** these entries stay at عالية although the second review said partly: V89-01 (2585), V89-10,
V89-27, V10-02 (2954), V10-07 (3002), V10-08 (3014), V10-19 and V1B-29 (3294). The «التحقق» lines that say ok on table
A entries also need updating.

**Fidelity points (section 4):**

- Section 1 and section 4 say "no book text" and "section titles in our words".
- 8 titles copy the book's headings word for word.
- 4 «المصدر» titles copy them too.
- 10 page ranges are very wide.
- About 98 entries rely on pages named only in their notes.

## 3. Build, test and compose facts, and the prompt-size cost

All of these were run on copies. Commands and hashes are in
`D:/Iqraa Law/.hq/scratch/distill-review/build-tests-compose/NOTES.txt`.

### Build

- Edition 1.3 built with the branch's `build_aqel.py` is byte-identical to `aqel-v1.3-librechat.md` on
  `demo-fixes-2026-11-11`: sha256 `ae344ee2…`, 48,147 bytes, LF. Its CRLF form equals the shipped edition `adeb8fcd…`.
  **The branch does not change the v1.3 edition.**
- The committed 1.3 and 1.4 files equal a fresh build once CRLF is turned to LF.
- Going from 1.3 to 1.4 adds 26 lines and changes only the version line. All 26 v1.3 rule phrases appear the same
  number of times in 1.4:
  - the budget rules (limit=3 as 3+3+2), the at-limit rule and the daily cap;
  - Arabic-only reasoning, at the top and in the library section, in both languages;
  - the 22-statutes lines;
  - law= (AR and EN), and the rule that slugs are not shown;
  - majalla and memorandum;
  - the privacy rule and its carve-out;
  - call hints, no re-fetch, suspension, and the corpus marker.

  22 of the 22 registry slugs are present.

### Compose

**Reproducibility.** A fresh copy of the ship content composes to `4c60fa94` exactly.

**Character counts.** The two reviews reported different numbers for the same files. The build review counted raw
CRLF characters. The product-safety review counted after converting to LF. Confirmed here:

| Composed text | sha256 | Characters (raw, CRLF) | Characters (LF) | Change (LF) |
|---|---|---|---|---|
| Live (v1.3 + pinned skill 1.0.0) | `4c60fa94` | 35,626 | 35,435 | — |
| Branch as committed (aqel.json still on v1.3) | `855c343e` | 36,046 | 35,855 | +420, from the pinned-skill edit alone |
| Branch with aqel.json pointed at 1.4 | `dff129d8` | 43,671 | 43,455 | +8,020 (+22.6%) |

**Where the 8,020 characters come from.** No block was removed. The rows sum to 8,016; the other four characters are
block separators.

| Block | Characters |
|---|---|
| Arabic distilled checks | +2,766 |
| Arabic D10 | +783 |
| English distilled checks | +3,491 |
| English D10 | +555 |
| Pinned-skill edits | +420 |
| Version line | +1 |

**Token cost.** The v1.3 bench measured about 3.51 characters per token on Gemma. On that basis the growth is about
**+2,290 tokens on every model call**, and about **+8,900 prompt tokens per answer** at the bench's 3.9 calls per
answer. Per part:

| Part | Tokens per call |
|---|---|
| Distilled checks | ~1,780 |
| D10 | ~380 |
| Pinned edits | ~120 |

This is a Gemma figure only; no DeepSeek measurement exists. The English twin is 56% of the checks' growth (3,491 of
6,257 characters), so it is where to trim if the owner wants a smaller prompt. Per D18 this is reported, not capped.

**On-demand cost.** This is paid only when the model loads the skill:

| Item | Size |
|---|---|
| Issue-map SKILL.md body | 2,308 characters |
| Skill description | 344 characters |
| Each reference file | 6,547-13,530 characters (11-23 KB) |
| Review checklist | +14,265 characters |

**Agent plan.** On the branch with 1.4:

- Every tier lists the skills `legal-document-review`, `jordanian-procedure-and-fees` and `jordanian-civil-issue-map`,
  with `skills_enabled` set to true.
- Only `jordanian-case-analysis` is pinned.
- `lintAgentBody` accepts the 1.4 body.

### Tests

- `node --test content/*.test.mjs` runs 76 tests: the handoff's 67 plus 9 new (6 for v1.4, 3 for the issue map). No
  test was lost.
  - LF copy: 75 pass, 0 fail, 1 todo.
  - This CRLF Windows worktree: 74 pass, **1 fail**, 1 todo.
- The failure is `content/issue-map.test.mjs`. Line 52 splits on `'\n'` without first converting CRLF to LF, so on a
  CRLF checkout the form test fails. Worse, the "every search term is in the named law's text" test then **passes
  with nothing checked**: 564 terms on 260 lines go unchecked. Two reviewers found this separately. On an LF copy, all
  564 terms (and the checklist's 104) occur in their law, with 0 problems.
- `aqel-edition.test.mjs` still tests only 1.3. Run against 1.4: 22 tests, 19 pass, 2 fail, 1 todo. Both failures are
  placement checks only (`:62` and the English check near `:76`): D10 now sits between the reasoning-language block and
  the library heading. No rule was lost.
- The todo test (`aqel-edition.test.mjs:188`) passes on both base and branch, so its todo marker is out of date. This
  was already true on the base.
- skill-ci (WSL python3): all skills pass.
- `aqel-v14.test.mjs:94-98` asserts the Arabic-name plan line. It must flip if the owner chooses slugs.

### Release path

The new skill cannot reach the agents through the v1.3 apply method. That method composes the text and then runs
`.hq/scratch/demo/providers/use-instructions.mjs:47`, which only sets `instructions`. Skills ship inside the release
image: `deploy/release/build.sh:105` writes `RELEASED.json`, which is still `{"skills": {}}`. `content/release.mjs`
`skillIds()` fails for any listed skill the instance lacks.

The composed v1.4 text would still tell the model to use the skill:

- the pinned body, composed line 238;
- `legal-document-review/SKILL.md:26`.

## 4. Source and licence notes (questions only; no legal conclusions)

**What was checked.** All 12 volumes' OCR (about 52 MB) were downloaded into gitignored
`.hq/scratch/distill-review/source/ocr/` and read with `python -I`. Nothing was committed.

- **Shipped text.** The 1.4 additions, the issue-map skill, the three skill edits, the build_aqel.py additions and the
  two test files were compared with all 12 volumes, not only each entry's own volume. No run of 7 or more words is
  shared with the book, under strict or loose matching. The longest shared run is 6 words: a list of contract names at
  `jordanian-civil-issue-map/SKILL.md:28`. The other 5-word runs are statute phrases or stock terms.
- **Catalogue** (committed, but the model never reads it). It has 25 runs of 7-11 words:
  - 15 are statute wording in «السند»;
  - 4 are in «الفرق»;
  - 4 are «المصدر» titles that copy the book's headings (lines 401, 2362, 2686, 3140);
  - 2 more are statute wording.

  None is in «المبدأ», «الصياغة» or «ملاحظات». Eight titles copy the book's headings whole: V1A-02, V1A-09, V2-29,
  V7-11, V89-24, V10-09, V10-12 and V10-22. So two of the catalogue's claims are slightly overstated: section 1, "No
  book text is in this repository", and section 4, "the section in our words".
- **Page citations.** The 20 spot-checked entries plus 3 extras all discuss on the cited page what the entry says (19
  fully; V2-18 partly, and it labels itself so). All 260 viewer links are consistent. Two traceability gaps:
  - 10 entries cite 20 or more pages. Examples: V6-15 (72 pages), V2-17 (61), V1B-23 (58), V2-12 (50).
  - About 98 entries rely on pages that are named only in their notes and fall outside the cited range.
- **Provenance in served text.** Line 1 of each of the nine reference files is an English comment naming al-Sanhuri's
  «الوسيط», and `read_file` returns it to the model with the file. `review-checklist.md:2` has a similar comment.
  `SKILL.md:11` (frontmatter) and a `build_aqel.py` comment (around line 496) name the source too. None of these names
  the licence. The composed edition does not mention the source.

**Licence facts as found.** The item metadata (archive.org `9_20250410`, fetched 2026-11-12) gives:

- licence: CC BY-ND 4.0;
- creator: عبد الرزاق السنهوري;
- publicdate: 2025-04-10;
- uploader: a private account, not a named publisher or estate;
- no rights field.

No publisher or edition line was found in the OCR. The author died in 1971. Unauthenticated, the GitHub API returns 404
for `ahmadtech26/ai-harness`, so the repository appears to be private.

**Questions for the owner or lawyer** (as the source-fidelity review framed them):

1. Who holds the rights in this edition? Is it still protected in Jordan and in Egypt, given the author's death in
   1971? Could the uploader validly apply CC BY-ND, and if not, does the licence matter?
2. Does distilling legal ideas and method into our own words, keyed to Jordanian articles, need permission at all? If
   it does, are the catalogue's per-page summaries, and the views attributed to «السنهوري» or «المؤلف», "Adapted
   Material" under CC 4.0 §1(a)?
3. Do any of these count as "Sharing" under the licence?
   - sending prompts and skills to model providers;
   - giving answers to paying users;
   - pushing to the private repository, or to any future public mirror.
4. If attribution is needed, what form should it take: creator, licence name and link, and a note that the material
   was modified? Or should model-facing text carry no source at all, so that nothing implies endorsement?
5. Do the statute wording and the book's short headings in the catalogue fall outside protection, as official texts or
   minimal titles?
6. Do archive.org's terms of use limit what may be done with the downloaded text? How long may the OCR copies in
   `.hq/scratch` be kept?

## 5. PR review comment (ready to paste)

The cloud agent sees only GitHub, so this comment uses repo-relative paths and catalogue ids only.

````markdown
## Review of `distill/book-principles-2026-11` (ff5cd5c): changes requested

Thank you: this is careful work. Seven independent reviews ran: four legal reviews by theme, build/test/compose,
product safety, and source fidelity. All 1,019 article citations resolve to an article in the corpus. The shipped text
shares no run of 7+ words with any of the 12 volumes. Edition 1.3 rebuilds byte-identical. The D10 headings and order
match the plan. Nothing is approved to go live. Please make the changes below and keep everything marked «draft, for
lawyer review». Instructions change only through `build_aqel.py` asserted replacements, with tests. No `Co-Authored-By`
or `Claude-Session` trailers.

### 1. Packaging (do now)

1. **Do not change the live prompt from this branch.** `content/skills/jordanian-case-analysis/SKILL.md` (1.0.0 →
   1.1.0) is appended to every prompt. Composed as committed with v1.3 still selected, it changes the live composed
   sha256 (+420 characters per call). Revert it on this branch.
2. **Put the skill's wiring in one separate commit, titled so it lands only with the approved skill:**
   - the `content/specialists/aqel.json` listing of `jordanian-civil-issue-map`;
   - the pointer at `content/skills/legal-document-review/SKILL.md:26`;
   - one pinned pointer line (the current «في النزاعات المدنية والتجارية ومراجعة العقود استعن بقوائم المسائل في
     مهارة `jordanian-civil-issue-map`…»).

   Drop the other two pinned additions: DISTILLED_CHECKS bullets 3 and 5 already carry them, so under 1.4 they would
   appear three times per prompt.
3. **Write down how the skill reaches the agents.** `content/release.mjs` `skillIds()` fails for a skill the instance
   lacks, and `content/skills/RELEASED.json` is empty. The skill must ship in a release image and be released with
   `release.mjs`. An instructions-only apply does not update the agents' skills. Say this in the PR description.
4. **Make D10 independent.** Make the D10 reasoning sequence buildable without DISTILLED_CHECKS (its own edition id),
   in its own commit, so the owner can take either one alone.
5. **Keep one route for the checklist.** `legal-document-review/references/review-checklist.md` now repeats 50
   issue-map lines byte for byte, and `legal-document-review/SKILL.md` step 4 also points to the issue map. Choose
   one:
   - keep the copies, drop the pointer, and add a test that each copied line equals its issue-map line; or
   - keep the pointer and drop the copies.

### 2. Tests (do now)

6. `content/issue-map.test.mjs:52`: convert CRLF to LF before `.split('\n')`, with `.replace(/\r\n/g, '\n')` as in
   `aqel-v14.test.mjs`. On a CRLF checkout the form test fails, and the corpus-term test passes with zero lines checked.
   In the term test, also assert that the number of lines with a `law=` match is above zero.
7. Run the same form, digit and corpus-term checks on every skill's `references/` lines that end in an id comment.
   Today the checklist is not covered.
8. If 1.4 stays, run `content/aqel-edition.test.mjs` on 1.4 as well. Change its two placement checks (`:62`, and the
   English one near `:76`) to allow the D10 block between the reasoning-language block and the library heading. The
   todo at `:188` already passes, so remove the todo marker.

### 3. Model-facing text (do now)

9. **Lines that carry a catalogue error.** Fix each one together with its entry in part 5.
   - `jordanian-civil-issue-map/references/harm-and-enrichment.md:17` (V1B-09): remove «ولا تطالب بالاحتمالي». Ask
     whether each item of harm has happened, is certain to happen, or is only probable, and send the model to the
     Civil Code's texts on measuring compensation and on reassessment.
   - `contracts.md:54` (V1A-22): remove «وأسبقية تاريخ العقد». Keep the two conditions of civil-code 207 (connection
     to the thing; the successor's knowledge). Treat the date as a proof question, with search term «تاريخ ثابت» and
     `law="evidence"`.
   - `contracts.md:18` and `review-checklist.md:9` (V10-05): separate doubt about *whether* a suretyship exists (a
     proof question) from doubt about its *extent* (interpretation). Pick search terms for the proof branch that
     occur in civil-code 73/77 or evidence 28; the term test will confirm them.
   - `proof.md:15` (V2-06): replace «جزاء الإخفاق في الإنكار أو التزوير» with «جزاء ثبوت عدم صحة الإنكار أو ادعاء
     التزوير».
   - `harm-and-enrichment.md:35` (V1B-27): drop «والعناية المبذولة». The Jordanian gestor text sets no ordinary-care
     threshold. Add the search term «الفضولي مسؤول».
   - `harm-and-enrichment.md:27` (V1B-22): before any "standard of care", have the model check two things: whether a
     retrieved text imposes a result (the contractor and engineer warranty for buildings), and whether a special
     professional-liability law applies and is in the library.
   - `contracts.md:35` (V1A-09): for a promise about real property, send the model to the Civil Code text on promises
     to transfer ownership of real property (search term «التعهد بنقل ملكية عقار») before it suggests a judgment in
     place of the contract.
10. `jordanian-civil-issue-map/SKILL.md:24-32`: write the full paths
    `skills/jordanian-civil-issue-map/references/<file>.md`, the form `read_file` advertises.
11. Line 1 of each of the nine reference files, and `review-checklist.md:2`: the comment naming al-Sanhuri/«الوسيط»
    is served to the model. Move provenance to SKILL.md frontmatter metadata, or to a file that is not served.
    Attribution itself waits for the owner.
12. **Fiqh from memory.** In `work-and-insurance.md:32` (V7-22), `property.md:20` and `review-checklist.md:16` (V89-12):
    - Use «اذكر أن الآراء الفقهية خارج المكتبة ولا تعرضها من الذاكرة».
    - For division (قسمة), name the statutory options to search instead.
13. **Reason clauses that state law.** Rewrite them as questions to check against the retrieved text. Examples:
    - `proof.md:24` (V2-15, «لأن توجيهها تنازل عنها»)
    - `proof.md:17` (V2-08)
    - `proof.md:14` (V2-05)
    - `harm-and-enrichment.md:11` (V1B-03)
    - `obligations.md:20` (V2-26)
    - `work-and-insurance.md:33` and `:36` (V7-23, V7-26)
    - `securities.md:14` (V10-07)
14. `proof.md:26` (V2-17): the text says to search the Civil Procedure Law but tags `law="evidence"`. Fix the tag or
    the wording.
15. **`build_aqel.py` DISTILLED_CHECKS_AR/_EN: the budget.** Open the block with one budget sentence, with an English
    twin, for example: «طبّق هذه الضوابط على المسألة الحاسمة أولًا وضمن رصيد الإجابة؛ وما لم يتسع له الرصيد فاذكره
    بموضوعه دون حكم». Make each "retrieve" directive conditional on the issue being decisive. As written, one contract
    dispute can call for 6-9 searches against v1.3's budget of 8 texts and limit=3.
16. **One term for discernment.** `build_aqel.py:522` says «التمييز» where `harm-and-enrichment.md:11` says «الإدراك»
    for the same point. Use one term.

### 4. The owner's decisions (2026-11-13) and what is still open

- **Decided: the D10 visible plan line uses Arabic law names and no limit.** Keep «<اسم التشريع بالعربية>» as the
  branch has it, and remove `limit=<عدد>` from the visible plan lines (`build_aqel.py:598-601`, `:609-610`,
  `:616-617`, the leftover at `:633`, `aqel-v14.test.mjs:94-98`): «- بحث: <اسم التشريع> | <مصطلح النص التشريعي>»
  and «- جلب: <اسم التشريع> | <موضوع المادة بكلمات قليلة>». v1.3's no-codes, no-tool-details rule stays as it is.
  Update the tests to this grammar; the telemetry check maps the names through `content/corpus/law-aliases.json` and
  reads the limit from the actual tool call.
- **Decided: D10 ships on its own, ahead of the legal checks.** Split the D10 sequence into its own edition (1.4a, or
  1.4 with D10 only and the distilled checks moved to a later edition), so it can be benched and released while the
  checks, the skill and the checklist wait for the lawyer.
- **Decided: search terms are statutory noun phrases only.** Rewrite the 42 propositional terms (examples: «الرهن لا
  يتجزا», «لا يسال أحد عن فعل غيره», «لا ينعقد الرهن التاميني الا بتسجيله», «الاضطرار لا يبطل حق الغير», «الشرط باطل»,
  «يفسر الشك في مصلحة المدين», «البينة على من ادعى», «لا ينقضي الحق بمرور الزمان», «يعزل وكيله متى أراد», and the
  amount «ثلث التركة») as noun phrases, and add a test that rejects a term that begins with a negation or a verb, or
  contains an amount.
- **Decided: no Egyptian law in model-facing text.** Add a ضابط in SKILL.md and in DISTILLED bullet 1 forbidding any
  mention of, or comparison with, Egyptian law or commentary in the answer, and remove the 25 model-facing lines that
  mention it. Comparisons stay in the catalogue, for the lawyer.
- **Still open (do not change until told): the contract-grade list.** Bullet 4 (`build_aqel.py:517-519`) gives one list and `contracts.md:49` (V1A-20) gives a
  different one. Either list them, or say «بالمراتب التي يسميها النص المسترجع».
- **Hard-coded "not loaded" subjects.** These appear at `build_aqel.py:514-515` and `:553-555`, `SKILL.md:40`, ten lines
  in `property.md`, `sale-and-property-contracts.md:18` and four lines in the checklist. The alternative is a pointer
  to the loaded-laws list. Personal status and Sharia procedure are planned additions.

### 5. Catalogue corrections (`docs/distillation/2026-11-12-book-principles.md`)

**A. Wrong on Jordanian law. Fix these before the lawyer sees the catalogue, and update the «التحقق» line of each.**

- V1A-09: add civil-code 1149 (a promise to transfer real property gives only a right to compensation). The library
  does settle this point.
- V10-05: keep civil-code 240 for the extent of the surety's obligation. Cite civil-code 73/77 and evidence 28-30 for
  whether the suretyship exists. Drop or recast «عمد أو رعونة» via civil-code 256-257.
- V1A-22: civil-code 207 has no fixed-date condition. Move the date to evidence 12.
- V1B-09: no Jordanian article supports the certain/probable/lost-chance rules. Make them questions, or mark them as
  doctrine.
- V1B-27: add civil-code 304 (the gestor is liable for the harm; the court sets the amount; there is no ordinary-care
  threshold).
- V1B-22: add civil-code 788-789. Limit the obligation-of-care statement. Note that the special medical-liability law
  is not in the library.
- V3-22: civil-code 247 treats a temporary impossibility in a continuing contract like a partial one (the
  counter-obligation ends, and the creditor may rescind). Remove «فالمؤقتة توقف التنفيذ فقط», or mark it as Egyptian.
- V3-03: the memorandum note for 393-401 does address retroactivity (fiqh view, Majalla 82 = civil-code 400). Rewrite
  the note.
- V2-11: evidence 30 lists seven exceptions. It names no mistake, no exploitation, and no interpretation of an
  ambiguous deed. List it exactly.
- V3-01: the certainty test is in civil-code 396 (for a condition) and in the memorandum (for a term), not in 393 or
  402.
- V2-06: civil-procedure 87(2) fines when the investigation shows the denial or claim to be untrue. The burden for a
  denial lies on whoever produced the deed (88).
- V1B-17: civil-code 268 allows only a reserved review «خلال مدة معينة». It does not allow a new claim. Restore the
  period.
- V2-23: present the four conditions and the effects of rescission and specific performance as the book's doctrine.
  For Jordan, state only 361, 364 and the memorandum.
- V2-29: add the good-faith and harm conditions of civil-code 368(1).
- V45-06: «لا بالرسمية» holds for movables only. Add civil-code 566 and 1148.
- V6-15: civil-code 684(2) covers another lessee, or a person who took the right from the lessor, and nobody else.
  Narrow the list.
- V7-12: civil-code 836(2) contradicts the opening Egyptian rule. Lead with 836(2) versus 837/838. Cite or flag the
  burden.
- V10-19: add civil-code 164(2) (the motivating-condition exception). Say its relation to 1343 is open. Lower the
  confidence.
- V10-27: add civil-code 1004 (a transferred debt keeps its securities).
- V89-27: civil-code 1184 has no "unregistered" limit. Narrow the claim to 1181-1182. Lower the confidence.
- V89-19: quote civil-code 1127 exactly as the corpus has it (cumulative), and flag it for the Gazette check. Drop or
  qualify the court-jurisdiction sentence. Add evidence 12.
- V89-20: anchor the proof rule to evidence 28/29 and civil-code 73/77, or remove it. Mark the use of 1176 as
  inference. Restore the optional wording of 1141.

**B. Restore the qualifier or correct the paraphrase.**

- V1A-04: add 1149; evidence 28-30.
- V1B-01: say no general article on exemption clauses was found; 358(2) concerns obligations of care only.
- V1A-06: replace «خيار المجلس» with the wording of 96.
- V3-04: 404(1) requires a judgment.
- V2-03: 372 says «يزيد».
- V2-09: restore «ما لم يوجد اتفاق أو نص يقضي بغير ذلك» (evidence 28).
- V2-12: remove «أو ممن يمثله».
- V2-18: remove «مع التسبيب».
- V1B-15: criminal-procedure 6(3) allows moving the claim.
- V45-04: add «في العقود التي تحتمل الفسخ» (184).
- V45-22: use 580's «إبطالا لأثر العقد».
- V45-24: 590 pairs the two conditions.
- V6-17: add 687; 697(2) gives rescission for partial loss.
- V7-01: add labour 3 and a scope step.
- V89-22: restore 1159(4)'s qualifier.
- V89-10: mark «ولو قبل القسمة» as the author's; let 1031 govern and drop 153.
- V89-09: replace «حسم» with «يعالج حالة طلب القسمة».
- V6-30: say «أحكام هذه المادة», and mention the carve-out in 5(أ)(4).

**C. Add the article, or tag the point «من الشرح المصري — لا نص أردني في المكتبة».**

- Add the article:
  - V2-07: evidence 11 and 30(4)/(7).
  - V2-19: civil-code 448.
  - V45-26: commerce 110, as in top-10 row 7.
  - V10-18 and V10-26: evidence 12.
  - V89-29: civil-code 73/77.
  - V89-02: civil-code 256 for compensation, or "needs research".
- Tag the point:
  - V2-17, V2-26, V2-30;
  - V3-06, V3-08, V3-16, V3-17, V3-19;
  - V45-05, V45-09 (align with 543), V45-16, V45-21;
  - V6-13, V6-23 (as questions);
  - V7-10, V7-14, V7-17, V7-20 (and correct its stale note on civil-procedure 32), V7-23 (add a civil-code 923 note),
    V7-27 (fire insurance only);
  - V89-13, V10-06, V10-14.

**Presentation.** In V3-09, V3-28 and V7-08, mark the Egyptian rule inside «المبدأ» itself; today only «الفرق» says
it.

**Egyptian side, recall only.** Do not change these; tag them «يؤكده المحامي».

- V1A-16
- V89-25: also add the recourse point from 1165(3).
- V89-22: the kinship clause.
- V89-10: the timing clause.
- V89-19: the Wills Law point.
- V10-19: the possessory-pledge point.
- V6-02: say "in the Egyptian legislation the book explains".

**Drafting.**

- Update the stale notes in V1B-07, V1A-13, V7-20, V10-04, V10-12 and V10-23.
- Cite the memorandum's actual-control reading in V1B-20.
- Remove the leftovers in V2-02.
- Present majalla 1199 as background in V89-03.
- Record the post-fix confidence in V89-01, V89-10, V89-27, V10-02, V10-07, V10-08, V10-19 and V1B-29.
- Section 7: say V10-09 and V10-23 have "no Jordanian article for the Egyptian institution itself", not "no Jordanian
  article at all".
- Section 1 and section 4: either reword the 8 titles that copy the book's headings (V1A-02, V1A-09, V2-29, V7-11,
  V89-24, V10-09, V10-12, V10-22) and the 4 «المصدر» titles at lines 401, 2362, 2686 and 3140, or change the two
  claims. Note that «السند» fields carry statute wording.
- Make «المصدر» list every page range an entry relies on. About 98 entries name pages only in their notes. Narrow the
  ten 20+-page ranges to the decisive pages; for example, V2-17 → 649, 677-678, 708-709.
````

## 6. What the owner must decide

1. **D10 visible plan line.** This covers the plan-line grammar and the privacy rule together, because one choice
   settles both. Pick one form:
   - **(a) Technical block, as planned in handoff section 5.** The line reads «- بحث: <slug> | limit=<n> | …». Add
     one sentence exempting the «خطة البحث:» block from both v1.3's no-slugs rule and its tool-details rule. The
     planned telemetry regex then works unchanged. *Recommended*: it is the owner's own D10 text, and slugs are
     canonical.
   - **(b) Customer-facing line.** The line uses the Arabic law name and drops `limit=`. Telemetry then maps names
     through `law-aliases.json` and reads the limit from the actual tool call. This is friendlier to read, but the
     model's wording of law names varies and can defeat the mapping.

   Either way, require Western digits.
2. **Ship D10 ahead of the distilled checks?** It carries no legal content. If yes, it needs its own edition (requested
   in the PR comment), a sha256 recompose and approval like v1.3, and measurement by telemetry (D11) or the staging
   bench. Also decide whether D16's lawyer-marked answer set gates this release too.
3. **Deployment route for `jordanian-civil-issue-map`.** Either build a release image with the skill and release it
   through `release.mjs` before any instruction names it, or hold every pointer line (pinned skill, legal-document-review
   step 4, aqel.json) until then. Instructions-only apply cannot add a skill.
4. **Search-term policy.** Should terms be the shortest distinctive noun phrase («تجزئة الرهن», «اعذار المدين», «مرض
   الموت») and never a proposition? This is recommended, with a test that flags terms beginning with a negation or a
   verb. The other option is to keep the 42 propositional terms (one of them the amount «ثلث التركة») for the lawyer to
   judge.
5. **Egyptian law in model-facing text.** Either forbid the model to mention, or compare with, Egyptian law or
   commentary in answers (recommended; matches v1.3 rule 6), or allow comparisons with lawyer-checked difference claims.
6. **Contract grades in the prompt.** Either keep 1.4 bullet 4's explicit list (باطل، فاسد، موقوف، نافذ، غير لازم;
   catalogue top-10 #2), or replace it with «the grades the retrieved text names». The list is Jordanian
   classification supplied from the prompt, which sits awkwardly with bullet 1 and with the "no rule to repeat" product
   rule.
7. **"Not loaded" laws.** Either keep the hard-coded list (land registration, personal status and inheritance,
   insolvency, Sharia matters), or point to the loaded-laws list in the instructions (recommended, because D14/D15 will
   add personal status and Sharia procedure, and the hard-coded text would then make the model deny a loaded law).
8. **Licence.** Answer the six questions in section 4 with the lawyer. Do it before the catalogue is merged into a
   branch others work from or mirrored, and before choosing between attribution and no source in model-facing text.
   Also decide how long the OCR copies may stay in `.hq/scratch`.
9. **Prompt cost.** Either accept about +2,290 tokens per call (+22.6%, Gemma-calibrated; about +8,900 per answer) for
   the full 1.4, or trim the English twin of the checks, which is 56% of their growth. Per D18 this is reported, not a
   ceiling.
10. **After the staging bench.** If loading the skill pushes answers into `recursion_limit` 16, either raise the limit
    or narrow the "use the issue map on every civil question" pointer. D9 rules out lowering reasoning.

**Already decided; noted here for order only.** Per D17 the lawyer reviews the live v1.3 instructions first. The
corrected catalogue, the 1.4 checks, the issue map and the checklist come after. The bench (PS-05/06: searches per
answer, graph steps, recursion errors, Arabic-only reasoning) is a D10/D16 requirement before any release, not a
separate decision.

## 7. Outside this pull request (for the main session)

1. **Article headings with text in them.** Three reviews found this independently. Some headings carry the article
   text inline (civil-code 73, 75-78 and 80; evidence 28 and 62). Some carry a title after a dash (civil-procedure 32
   «القضاء المستعجل», 113, 167). Some carry «مكرر» (59, 81, 188 and 222 مكرر). A parser expecting a bare
   `### المادة N` misses them; the catalogue author's own `article.py` missed civil-procedure 32 and evidence 28.
   Confirm that live `get_article` and `search_law` (legal-search) return these articles. Check this on the engine's
   tests or on staging, not on the live demo.
2. **Memorandum index noise.** `memorandum-article-index.json` maps by any «المادة (N)» mention. The combined
   `القانون-المدني-الأردني-مع-المذكرة.md` places each note one heading off; for example, the real note for 1015-1016 is
   note 606. Catalogue section 8 says `memorandum.py` ignores the index. Confirm this.
3. **Gazette check items.**
   - civil-code 1127 may be missing an «أو» (V89-19).
   - The Evidence Law's witness-proof threshold may be out of date (catalogue section 8.3).
4. **Stale todo marker.** The todo at `aqel-edition.test.mjs:188` already passes on the base branch.

## Appendix: the seven reviews and where their evidence is

| Review | Scope | Headline | Notes and scripts (local) |
|---|---|---|---|
| Legal T01-T07 | 61 entries, 223 citations | 0 missing, 6 medium, 7 low | `.hq/scratch/distill-review/legal-t01-t07/` (notes.md, art.py, memo.py, dump.py, entries.json) |
| Legal T08-T13 | 62 entries, 235 citations | 0 missing, 5 contradicted, 3 overstated, 10 unsupported, 9 slips | `.hq/scratch/distill-review/legal-T08-T13/` (verdicts.md, extract.py, terms.py, memo.py) |
| Legal T14-T18 | 76 entries, 300 citations | 0 missing, 3 medium, 19 low | `.hq/scratch/distill-review/legal-T14-T18/` (findings.jsonl, art.py, show.py, memo.py) |
| Legal T19-T23 | 61 entries, 261 citations | 0 missing, 15 partly right (3 corpus-contradicted) | `.hq/scratch/distill-review/legal-T19-T23/` (verdicts.md, extract.py, read_T19..T23.txt) |
| Build/test/compose | builds, tests, compose, size | 1.3 identical; live hash changes; CRLF test bug | `.hq/scratch/distill-review/build-tests-compose/` (NOTES.txt, diffs, logs, scripts) |
| Product safety | model-facing text, wiring | D10 grammar; ungated pinned edit; propositional terms; budget | `.hq/scratch/distill-review/product-safety/` (composed-branch-v13/v14.md, term-predicates.txt, declaratives.txt) |
| Source fidelity | book overlap, page cites, licence | pass; catalogue claims slightly overstated; licence questions | `.hq/scratch/distill-review/source-fidelity/` (shingle-report.json, spotcheck.json, locality.json, scripts/) |

## 8. Owner answers (recorded by the main agent, 2026-11-13 ~00:xxZ)

- **D10 visible plan line: «Arabic names, no limit»** (overrides this report's recommendation of slugs): «- بحث: <اسم
  التشريع بالعربية> | <مصطلح النص التشريعي>» and «- جلب: <اسم التشريع بالعربية> | <موضوع المادة>»; no limit= and no slug
  in the visible plan, so v1.3's no-slugs/no-tool-details rule stands unchanged; the plan-followed check maps names to
  slugs through content/corpus/law-aliases.json and reads the limit from the actual tool call. The PR comment in §5
  must say this instead of asking for slugs.
- **D10 timing: «Yes, after a bench»**: D10 ships as its own edition ahead of the lawyer-gated legal checks, after a
  short bench within the 5 USD test budget.
- **Egyptian law: «Forbid in model text»**: no mention of or comparison with Egyptian law or commentary in any
  model-facing text; comparisons stay in the catalogue for the lawyer.
- **Search terms: «Noun phrases only»**: statutory noun phrases; a test rejects terms beginning with a negation or a
  verb, or containing an amount.
