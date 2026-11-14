# Lawyer lists, one per law (verification pass 2026-11-14, draft, for lawyer review)

One file per law. Each lists every article whose record is not `verified`, by result / reason or differs_from /
difference, and the `gazette_offline` articles by the Gazette issue still needed. For every article whose Gazette
reading differs from the stored text, it gives the two readings word by word (stored → Gazette). It ends with the
reader's notes (open questions, fixes made, decisions held for the owner).

The lists were made from the records as they stand once every verification PR has merged (records, Gazette fixes and
re-verifications, and the penal code's comparison with Qistas): 6592 articles, 50 verified, 1063 differs, 5479
unverifiable.

| Law | Articles | Verified | Differs | Unverifiable |
|---|---|---|---|---|
| [companies](companies.md) | 314 | 2 | 15 | 297 |
| [civil-code](civil-code.md) | 1448 | 0 | 0 | 1448 |
| [majalla](majalla.md) | 1851 | 0 | 0 | 1851 |
| [penal-code](penal-code.md) | 489 | 4 | 475 | 10 |
| [commerce](commerce.md) | 480 | 0 | 188 | 292 |
| [maritime-commerce](maritime-commerce.md) | 386 | 0 | 0 | 386 |
| [civil-procedure](civil-procedure.md) | 229 | 3 | 14 | 212 |
| [criminal-procedure](criminal-procedure.md) | 372 | 5 | 19 | 348 |
| [customs](customs.md) | 254 | 1 | 10 | 243 |
| [labour](labour.md) | 142 | 1 | 26 | 115 |
| [bar-association](bar-association.md) | 110 | 0 | 13 | 97 |
| [execution](execution.md) | 119 | 7 | 109 | 3 |
| [income-tax](income-tax.md) | 82 | 9 | 73 | 0 |
| [sales-tax](sales-tax.md) | 77 | 3 | 34 | 40 |
| [evidence](evidence.md) | 74 | 0 | 4 | 70 |
| [court-fees](court-fees.md) | 52 | 0 | 37 | 15 |
| [courts-formation](courts-formation.md) | 23 | 1 | 3 | 19 |
| [landlords-tenants](landlords-tenants.md) | 22 | 0 | 5 | 17 |
| [magistrates-courts](magistrates-courts.md) | 22 | 8 | 14 | 0 |
| [major-felonies-court](major-felonies-court.md) | 16 | 0 | 0 | 16 |
| [investment-fund](investment-fund.md) | 16 | 6 | 10 | 0 |
| [mediation](mediation.md) | 14 | 0 | 14 | 0 |
| **all** | 6592 | 50 | 1063 | 5479 |

Why so few are `verified`: `v1` keeps hamza, letter forms and punctuation, and the Gazette, the Bureau and the stored
text each write these differently (the Gazette prints «او», «اذا», «احكام» without hamza and labels as «أ-»; the stored
text has «أو», «إذا», «أ.»). Most `differs` articles agree in words. Whether to restyle the stored text to the Gazette's
spelling, or to widen the normalisation, is the owner's decision. Most `unverifiable` articles need a Gazette issue
from before 4632, which the Gazette site does not hold.

Penal code: its 419 articles whose Gazette issue (1487) is offline are compared with Qistas's consolidated text,
under the owner's exception of 2026-11-14 (Qistas accepted as an authentic source). Their «Gazette» reading in
penal-code.md is Qistas's text, not a Gazette page.

The earlier open items (PRs #1–#27) are in [../lawyer-open-items.md](../lawyer-open-items.md).
