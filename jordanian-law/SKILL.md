---
name: jordanian-law
description: |
  Jordanian law library and legal case analyst. Two layers: (1) STATUTE — 22 codified
  Jordanian laws, 6,593 articles verbatim (civil, penal, commerce, companies, labor, tax,
  customs, execution, procedure, evidence, Majalla, and more) with per-article topic
  classification and the Civil-Code explanatory memorandum (766 official notes);
  (2) COMMENTARY — 3,138 practitioner documents (articles, case studies, templates/نماذج)
  linked to the articles they cite. Activates when: analyzing cases under Jordanian law;
  citing or quoting a specific المادة; researching القانون المدني with المذكرة الإيضاحية;
  determining jurisdiction, procedure, or fees; drafting from a legal template; or finding
  commentary that discusses a given law article.
metadata:
  version: "3.0"
---

# Jordanian Law — Statute Library + Commentary

**Layer 1 — STATUTE** (`references/القوانين-الأردنية/`): authoritative law text. Cite from here.
**Layer 2 — COMMENTARY** (`references/docs/`): practitioner articles & templates. Context, not authority.

## Quick Reference — 22 laws, 6,593 articles

| Category | Laws (articles) |
|----------|-----------------|
| موضوعي مدني | القانون المدني (1449) · مجلة الأحكام العدلية (1851) · المالكين والمستأجرين (22) |
| موضوعي جزائي | العقوبات (489) |
| موضوعي تجاري | التجارة (480) · التجارة البحرية (386) · الشركات (314) |
| ضرائب وجمارك | الجمارك (254) · ضريبة الدخل (82) · ضريبة المبيعات (77) |
| عمل واستثمار | العمل (142) · صندوق الاستثمار (16) |
| إجراءات حقوقية | أصول المدنية (229) · البينات (74) · التنفيذ (119) · الوساطة (14) |
| إجراءات جزائية | أصول الجزائية (372) |
| المحاكم والمهنة | تشكيل المحاكم (23) · الصلح (22) · الجنايات الكبرى (16) · الرسوم (52) · نقابة المحامين (110) |

Full directory: [law-directory.md](references/القوانين-الأردنية/law-directory.md) · Evidence rules: [evidence-rules.md](references/القوانين-الأردنية/evidence-rules.md)

## Recipe 1 — Fetch an article (2 reads, never a whole law)

1. Read `references/القوانين-الأردنية/shard-map.json` (12 KB) → for law + article N pick the shard whose `[lo,hi]` contains N. (`N مكرر` lives with N.)
2. `grep -n "### المادة N" <shard>` → then Read the shard at that offset (~40 lines). Shards are 4–53 KB; NEVER read `article-index.json`, `topic-index.json`, or a whole big JSON to find one article.

## Recipe 2 — Arabic search normalization

Corpus spelling varies (hamza often dropped). When grepping, normalize:

| Instead of | grep pattern |
|---|---|
| أ / إ / آ | `[اأإآ]` |
| ة / ه (final) | `[ةه]` |
| ى / ي | `[ىي]` |
| word may carry prefixes | allow `(ال|و|ف|ب|ل|لل)?` before the stem |

Example: العربون → `grep -rn "[اأ]لعربون\|عربون" <law>/sections/`. Prefer stems (`عربون` not `العربون`).

## Recipe 3 — Civil-Code memorandum (المذكرة الإيضاحية)

1. Look up the article in `references/القوانين-الأردنية/memorandum-article-index.json` (58 KB) → note number(s).
2. `grep -m1 '"<note>":' references/القوانين-الأردنية/memorandum_civil_law.json` → the full note is on that one line. Do NOT read the whole 1.7 MB file. Keys are note-sequence numbers (1–766), not article numbers.

## Recipe 4 — Find articles by topic

Per-topic files: `references/القوانين-الأردنية/topics/<slug>.json` (36 topics: contract, sale, company, commerce, tax, employment, enforcement, evidence, penalty, …). Each lists `{law, article}` refs. Read only the topic file you need.

## Recipe 5 — Commentary & templates (Layer 2)

- **Docs that discuss المادة N of a law:** `references/docs/by-law/<law-slug>.json` → `articles["N"]` = substantively relevant doc ids (use these); `mentions["N"]` = loose hits, mostly full-law reprints of other laws — cite only if nothing relevant exists. Available laws: `by-law/_index.json`.
- **Browse/search by category:** `references/docs/catalog/<category>.json` (10 slim catalogs: قانون-مدني، إجراءات-قضائية، قانون-جنائي، قانون-عمل، قانون-شركات، عقود-ونماذج، قانون-استثمار، قانون-دستوري، ملكية-فكرية، تجارة-دولية). Every doc has a defined `subcategory`; schema overview in `references/docs/docs-classification.json`. Each entry: `id, title, date, type, subcategory, file, cites`.
- **Read a doc:** `references/docs/markdown/<category>/<file>` (avg 26 KB).
- **Templates/نماذج:** category `عقود-ونماذج` (174 docs), `"type": "template"`.
- Commentary is one practitioner's view (jordan-lawyer.com) — quote statutes from Layer 1, never from a doc.

## Case Analysis Workflow

1. **CLASSIFY** the case (حقوقية/جزائية/تجارية/عمالية/ضريبية) → pick laws from Quick Reference; `relationships.json` maps procedural↔substantive pairings.
2. **LOCATE** articles via Recipe 1 (+ Recipe 4 for exploratory topic search).
3. **ANALYZE & CITE**: quote article text verbatim; for civil articles add the memorandum note (Recipe 3); optionally add commentary/templates (Recipe 5).

Output format: الوقائع → المسألة القانونية → النصوص المطبقة (quoted, with law + المادة number) → التحليل → الخلاصة.

## Key file paths

| Purpose | Path |
|---------|------|
| **Article→shard lookup (start here)** | `references/القوانين-الأردنية/shard-map.json` |
| Statistics (SSOT) | `references/القوانين-الأردنية/statistics.json` |
| Law relationships | `references/القوانين-الأردنية/relationships.json` |
| Per-law metadata | `references/القوانين-الأردنية/{law}/sections/_metadata.json` |
| Article text shards | `references/القوانين-الأردنية/{law}/sections/*.md` |
| Topic annotations (per law) | `references/القوانين-الأردنية/{law}/sections/article-annotations.json` |
| Topics (per topic) | `references/القوانين-الأردنية/topics/*.json` |
| Memorandum + its index | `references/القوانين-الأردنية/memorandum_civil_law.json` + `memorandum-article-index.json` |
| Docs by-law index | `references/docs/by-law/*.json` |
| Docs catalogs | `references/docs/catalog/*.json` |
| Doc text | `references/docs/markdown/{category}/*.md` |

## Validation rules

- Every legal conclusion cites specific article(s); article text quoted exactly as in the shard.
- If an article is not found: check `shard-map.json` range, then the law's `_metadata.json`; say plainly if it is not in the corpus. Never invent article text.
- Statute (Layer 1) overrides commentary (Layer 2) on any conflict.
- All texts are Arabic (RTL); answer in the user's language; keep quotes in Arabic.
