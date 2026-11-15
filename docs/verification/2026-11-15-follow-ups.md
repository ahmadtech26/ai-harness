# Verification follow-ups (owner 2026-11-15, not blocking)

Draft, for the owner. Recorded with the corrections of 2026-11-15 to #87; none of them changes a verdict today, and each
is a later PR of its own.

1. **Gazette evidence lines that name a superseded issue and page** (the owner's count: 361). A Gazette line in
   `docs/verification/evidence/<law>.jsonl` gives the `issue` and `page` of the text it transcribes; where an article was
   later replaced or repealed, some lines still name the earlier issue rather than the issue of the text in force
   (`gazette_in_force` on recall-plan: from the last `replaced`, `added` or `repealed` amendment on). The records'
   references are not affected; the evidence lines should name the issue and page actually transcribed. (A first count
   on this branch, comparing each Gazette line's issue with its record's text in force, gives 353 after the Qistas lines
   left the Gazette source; the method of the owner's count decides.)
2. **Two-page articles and their image hashes.** Schema decided (2026-11-15, corpus-ci): `image_sha256` is a sha256 or
   a list of them, one per page image in page order, and `pages` lists `{issue, page, document_id, image_sha256}` per
   page. What remains: companies 151 (evidence line 193), a composite line over pages 5643-5644 and 3642-3643, has no
   image hash at all; and 10 companies lines whose page is a range carry a list of hashes but no `pages`, so which
   hash is which page is not recorded. Fill both from the page images.
3. **Gazette evidence text for the companies passages of 20/2023.** The companies records that cite the amending law
   20/2023 need the Gazette text of the amended passages in the evidence file, so the comparison can be re-run.
4. **The maritime-commerce registry gap in the lawyer list.** `content/corpus/laws.json` has no `amendment.gazette_date`
   for maritime-commerce's last amendment, 35/1983 (Gazette 3194, not online). Unlike criminal-procedure's list (item
   «crim C5, registry»), `docs/verification/lawyer/maritime-commerce.md` does not say so; add the item there.
