# Handoff for cloud agents, 2026-11-12 (state of the Iqraa Law demo and the owner's decisions)

Written by the local main session on 2026-11-12 ~18:45Z for agents that see only the GitHub repositories. The local
records (checkpoints, run sheet, ledgers, plans) are not in git; this file carries what you need from them. It holds no
visitor text, no secrets and no demo addresses.

## 1. Which branch to use

| Repository | Branch | Head | What it holds |
|---|---|---|---|
| ahmadtech26/ai-harness | `demo-fixes-2026-11-11` | this commit (parent `cb8e92e`) | **The live instructions** (AQEL v1.3), the skills, the law corpus and registry. `main` is 4+ commits behind: do not work from `main`. |
| ahmadtech26/ai-harness | `recall-plan` | `649559a` | The Python keyword engine (BM25, config T-B2) that serves the demo's library since 2026-11-12 15:54Z. |
| ahmadtech26/ai-platform | `ui-pass-2026-11-08` | `c78a69b` | The LibreChat fork overlay the demo runs. Changes now under review locally (POST streaming, an Arabic progress line, a per-turn Arabic reasoning reminder) are **not** pushed yet. |

## 2. Live state (2026-11-12 ~18:45Z)

- Product: LibreChat with the fork overlay; three tiers, each an agent with the same instructions:
  fast and advanced on `google/gemma-4-31b-it`, expert on `deepseek/deepseek-v4-pro-0813` (OpenRouter, zero data
  retention). Output caps: expert 32,768 tokens, fast and advanced 16,384. Reasoning is at each model's default.
- Instructions: AQEL v1.3, composed with the pinned skill `jordanian-case-analysis`; composed sha256 `4c60fa94…`,
  live on all three tiers since 18:30:20Z. Built by `content/prompts/build_aqel.py 1.3` (edition file
  `content/prompts/aqel-v1.3-librechat.md`). v1.3 = the owner's new text reworded for this product, plus the library
  budget rules (8 texts per answer, at most 5 per search, limit=3 when three searches are planned), the at-limit rule,
  and an Arabic-only reasoning rule placed at the very top of each language section and again in the library section.
- Known gap: models follow the Arabic-only reasoning rule only partly (bench before v1.3: reasoning mostly English in
  6 of 9 answers). A per-turn reminder in the fork is under review; measuring it continues.
- Library tools (MCP, legal-search): `search_law`, `get_article`, `get_memorandum`; 22 Jordanian statutes plus the
  Civil Code explanatory memorandum; no judgments, no doctrine. A citation guard runs in shadow mode (it flags, never
  blocks).

## 3. The owner's decisions of 2026-11-12 (all settled)

- D1 scope: the product runtime (tier agents, instructions and skills, library tools, the fork's hooks and guard), a
  developer skill for composing/installing/verifying instructions, and developer-side live-change safety hooks.
- D2 the guard judges only the visible answer; reasoning is saved for staff and telemetry but never shown to customers,
  who see Arabic progress («يفكّر…», «يكتب الإجابة…») with LibreChat's own counter as the only count.
- D3 the guard blocks only after D2, «bis» reading, the merged «مكرر» rows split and a measured false-flag rate.
- D4 law fetching changes instructions first, then the server's replies in one legal-search rebuild.
- D5 ship v1.3 now (done); the lawyer reviews after.
- D6 one legal-search rebuild with: separate per-answer and daily cap messages (stop, name the gap), a remaining-budget
  line on every reply, `law` required on `get_article` with a slug list, a «مكرر» fallback, duration/limit/engine in
  the search log.
- D7 keep 8 texts per answer, add the remaining-budget line.
- D8 fetch by exact reference, skipping articles already served, and a second search wording all ship now.
- D9 never lower reasoning effort.
- D10 sequential thinking: a fixed Arabic reasoning sequence with a short visible plan, checked by telemetry (planned
  text in section 5), plus a bench of a staged plan/fetch/draft/verify pipeline, adopted only if better.
- D11 telemetry: self-hosted Langfuse (after a security-rule amendment and an independent second opinion).
- D12 traces keep full question, reasoning and answer text, with pseudonymous ids.
- D13 build the Rust engine now (Option 4).
- D14/D15 add the Personal Status Law and the Sharia court procedure law, transcribed from the Legislation and Opinion
  Bureau (LOB) and checked against the Official Gazette by a named person; staging first.
- D16 a lawyer-marked answer set gates releases. D17 when a lawyer is named: the live instructions first.
- D18 no time or cost ceiling per answer; report it. D19 on a stop at the output cap: continue the answer, then an
  Arabic notice if it still cannot finish; log every case.

Standing preferences: never propose lowering reasoning effort or a per-answer ceiling; the model's thinking must be in
Arabic only; caps stay open.

## 4. Where things are in this repository

- Instructions: `content/prompts/build_aqel.py` (editions 1.1, 1.2, 1.3; exact, asserted replacements over the owner's
  source text), `content/prompts/aqel-v1.3-source.txt` (verbatim source), `aqel-v1.3-librechat.md` (built edition).
- Specialist: `content/specialists/aqel.json` (tools, skills, instructions file). Tier composition:
  `content/tier-agents.mjs`, `content/compose.mjs` (pinned skills are appended to the instructions).
- Skills: `content/skills/jordanian-case-analysis/SKILL.md` (pinned, always applied),
  `content/skills/legal-document-review/` (with `references/review-checklist.md`),
  `content/skills/jordanian-procedure-and-fees/SKILL.md`; `content/skills/RELEASED.json`.
- Law corpus: `jordanian-law/references/القوانين-الأردنية/` (the statutes' text files), registry
  `content/corpus/laws.json` (22 laws and their slugs), `corrections.json`, `law-aliases.json`, `grounding-laws.json`.
- Retrieval evaluation set: `content/eval/retrieval-v1.jsonl` (80 items; draft, not lawyer-reviewed).
- Tests: `node --test content/*.test.mjs` (67 tests; 66 pass, none fail, on `cb8e92e`). Build an edition:
  `python -X utf8 -I -B content/prompts/build_aqel.py 1.3`.

## 5. Planned, not yet live: the Arabic reasoning sequence (D10)

To be added to the edition after the Arabic-only reasoning block, with an English twin, and checked by telemetry:

- Headings, in Arabic and in this order, for the model's internal reasoning: «الفهم»، «المسائل»، «خطة البحث»، «الجلب»،
  «التحقق من الاستشهادات»، «الجواب».
- A visible «خطة البحث:» block in the answer before the first library call, one line per planned call:
  «- بحث: <رمز التشريع> | limit=<عدد> | <مصطلح النص التشريعي>» or «- جلب: <رمز التشريع> | <موضوع المادة بكلمات قليلة>»;
  never an article number or a rule from memory in the plan; any unplanned call is preceded by «تعديل الخطة:» and its
  reason.

## 6. Rules for any proposal you make

- Work on a new branch from `demo-fixes-2026-11-11` and open a pull request; never push to the demo branches directly.
- Change instructions only through `build_aqel.py` (a new edition or an asserted replacement), with tests; skills
  through their SKILL.md files. Nothing goes live without the owner's approval; the local main session applies it.
- Every legal statement must rest on a Jordanian article from the corpus above (quote the slug and article number);
  the model may cite only what the library returns, so skills must teach method and issue-spotting, not supply law
  from memory.
- Copyrighted sources: distil principles in your own words with source and page for traceability; no long verbatim
  passages in prompts or skills.
- The lawyer reviews legal content before release (D16, D17): mark every proposal «draft, for lawyer review».
- Commits: no `Co-Authored-By` or `Claude-Session` trailer.
