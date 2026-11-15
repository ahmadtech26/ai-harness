# Lawyer lists, one per law (verification pass 2026-11-14, draft, for lawyer review)

One file per law. Each lists every article whose record is not `verified`, by result / reason or differs_from /
difference, and the `gazette_offline` articles by the Gazette issue still needed. For every article whose Gazette
reading differs from the stored text, it gives the two readings word by word (stored → Gazette). It ends with the
reader's notes (open questions, fixes made, decisions held for the owner).

The lists were made from the records as they stand once every verification PR has merged (records, Gazette fixes and
re-verifications, the records recomputed on the cleaned text of §7, and the owner's corrections of 2026-11-15: three repeals
still ending with a glued title are `differs` / `trailing-title`, and Qistas is a helper source only): 6592 articles,
48 verified, 646 differs, 5898 unverifiable.

| Law | Articles | Verified | Differs | Unverifiable |
|---|---|---|---|---|
| [companies](companies.md) | 314 | 1 | 16 | 297 |
| [civil-code](civil-code.md) | 1448 | 0 | 0 | 1448 |
| [majalla](majalla.md) | 1851 | 0 | 0 | 1851 |
| [penal-code](penal-code.md) | 489 | 3 | 57 | 429 |
| [commerce](commerce.md) | 480 | 0 | 188 | 292 |
| [maritime-commerce](maritime-commerce.md) | 386 | 0 | 0 | 386 |
| [civil-procedure](civil-procedure.md) | 229 | 3 | 14 | 212 |
| [criminal-procedure](criminal-procedure.md) | 372 | 5 | 19 | 348 |
| [customs](customs.md) | 254 | 1 | 10 | 243 |
| [labour](labour.md) | 142 | 1 | 26 | 115 |
| [bar-association](bar-association.md) | 110 | 0 | 13 | 97 |
| [execution](execution.md) | 119 | 6 | 110 | 3 |
| [income-tax](income-tax.md) | 82 | 9 | 73 | 0 |
| [sales-tax](sales-tax.md) | 77 | 3 | 34 | 40 |
| [evidence](evidence.md) | 74 | 0 | 4 | 70 |
| [court-fees](court-fees.md) | 52 | 1 | 36 | 15 |
| [courts-formation](courts-formation.md) | 23 | 1 | 3 | 19 |
| [landlords-tenants](landlords-tenants.md) | 22 | 0 | 5 | 17 |
| [magistrates-courts](magistrates-courts.md) | 22 | 8 | 14 | 0 |
| [major-felonies-court](major-felonies-court.md) | 16 | 0 | 0 | 16 |
| [investment-fund](investment-fund.md) | 16 | 6 | 10 | 0 |
| [mediation](mediation.md) | 14 | 0 | 14 | 0 |
| **all** | 6592 | 48 | 646 | 5898 |

Why so few are `verified`: `v1` keeps hamza, letter forms and punctuation, and the Gazette, the Bureau and the stored
text each write these differently (the Gazette prints «او», «اذا», «احكام» without hamza and labels as «أ-»; the stored
text has «أو», «إذا», «أ.»). Most `differs` articles agree in words. Whether to restyle the stored text to the Gazette's
spelling, or to widen the normalisation, is the owner's decision. Most `unverifiable` articles need a Gazette issue
from before 4632, which the Gazette site does not hold.

Penal code: 419 articles whose Gazette issues (1487 and others before 4632) are offline were read only in Qistas's
consolidated text. Qistas is a helper source only (owner 2026-11-15, «Helper source only»): never the Gazette and never
counted toward `verified`. Those records keep the Qistas reading in a separate `helper` block (evidence rows labelled
`qistas`), are `unverifiable` (`gazette_offline`; no archive.org scan of these issues is known), and penal-code.md
lists the Qistas comparison in its own section, apart from the Gazette readings.

The earlier open items (PRs #1–#27) are in [../lawyer-open-items.md](../lawyer-open-items.md).
Follow-ups of 2026-11-15 (not blocking: superseded issues in evidence lines, two-page image hashes, the 20/2023
companies passages, the maritime-commerce registry gap) are in [../2026-11-15-follow-ups.md](../2026-11-15-follow-ups.md).
