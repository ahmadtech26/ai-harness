# ragflow-w2

The W2 tools: a throwaway, pinned RAGFlow v0.27.3 on this machine, holding our served articles, indexed by Walid's
indexing-pipeline canvas, and queried with `../ragflow-w1/run_w1.py`. The rules are in
`.hq/docs/specs/spec-rag-system.md`, block «Owner decision 2026-11-08: W2 first, run here, with a pre-registered
rule». Each tool has its own section below. Everything that runs on the host or in the runner uses the Python
standard library only.

## make_w2_corpus.py

It writes the W2 upload set: one markdown file per law holding our served articles, and `upload-manifest.json`,
which records what went in. The ingest tool uploads only the 22 `*.md` files and records the manifest's sha256 in
its W2 manifest.

```bash
# Windows, Git Bash
cd "/d/Iqraa Law/AI Harness-w1/tools/ragflow-w2"
python -I make_w2_corpus.py --canvas "D:/Iqraa Law/.hq/scratch/inbox-evidence-law-2026-11-07/اقرأ – فهرسة التشريعات القانونية.json"
# WSL: the same with python3 and /mnt/d/... paths
```

- **Inputs.**
  - The served corpus. It reads the shards under `jordanian-law/references/القوانين-الأردنية`, the registry
    (`content/corpus/laws.json`), `corrections.json` and `law-directory.md`. They are read through legal_search's
    standard-library modules (`corpus`, `corrections`, `registry`, `normalize`), imported from
    `../../services/legal-search/src`.
  - The ingest's checks, repeated, because `ingest.py` itself needs psycopg (ingest.py:45-77):
    - every correction names a registry law;
    - no article appears twice;
    - no known gap is present;
    - each law's count is its directory count minus its known gaps.
  - The canvas. It is untrusted data, read with `json` only (see the canvas rules below).
- **Output.** `--out`, by default `.hq/scratch/w2-run/in/`, which is created if missing.
  - A folder that is not empty is refused unless `--replace` is given.
  - `--replace` removes only this tool's own files: top-level regular `*.md` files and `upload-manifest.json`.
    Any other entry is named and the run is refused, with or without `--replace`.
- **Baseline.**
  - The library's corpus sha256 must equal `run.corpus_sha256` in `p3-evidence/eval-final.json`
    (`--baseline` sets the file). Otherwise W2 and T-B2 would not be indexing the same text.
  - `--no-baseline` skips this check and records `null` in the manifest. Only the tests use it.
- **Exit codes.** 0 written; 2 refused, with the reason on stderr. A refusal leaves nothing from this run in
  `--out`. The tool prints counts and hashes only, never article text.

### The file shape (`slug-title-served-v1`, pinned)

Each file is named `<registry slug>.md`. It is UTF-8 without a BOM, with LF line ends and one final LF:

```
# <registry title>
<blank>
### المادة <number>[ <suffix>]
<blank>
<served text, byte for byte>
<blank>
### المادة <number>[ <suffix>]
<blank>
<served text>
```

- **Article order.** Articles appear in legal_search's order: shards in file-name order, each shard top to
  bottom, then corrections applied (corpus.py:78-83, corrections.py:97-109).
- **The heading.** It is `"### " + Article.label`, with the number in ASCII digits. The penal-code relabel gives
  `### المادة 25 مكرر ثانياً`.
- **The served text.** It is `Article.text` as `apply_corrections` returns it, which ingest stores and search
  serves (db.py:229). Paragraph breaks (`\n\n`) and the inner `## الباب/الفصل` captions stay as they are.
- **Why the shape differs from the research generator.** `.hq/scratch/w2-research/pipeline/w2_files.py`
  recommended a different shape: captions demoted and no law heading. The owner pinned this shape instead. On
  the 2026-11-08 run, skipping each file's first two lines (the title line and the blank after it), the files
  equal that generator's `upload-demote-nohead/` output except for the 222 `#`-led body lines it demoted. That
  generator was built independently, from the bench export, so this also confirms the served text.

### The canvas rules

- **Which part is read.** Only the pipeline DSL's `components` entry whose `component_name` is `TitleChunker`. That
  is what RAGFlow runs; `graph.nodes[].data.form` is the editor's copy.
- **What it must hold.** Exactly one such component, the `group` method, and exactly one level family with at least
  3 levels. Empty patterns are dropped, as RAGFlow drops them (common.py:370). With several families, RAGFlow keeps
  the one that matches most lines (common.py:343-370); that case is not modelled, so it is refused.
- **How patterns are matched.** As RAGFlow v0.27.3 matches them (common.py:334-340): `re.match` on the stripped
  line, no flags, the first matching level wins, and lines caught by `not_bullet` are excluded
  (rag/nlp/__init__.py:366-368, retyped here because that code is RAGFlow's, not the canvas's).
- **Safety.** A pattern from the canvas is compiled, never executed as code. The worst it can do is be slow
  (catastrophic backtracking). Run the tool with `python -I`.

### Checks (all before writing, except the read-back)

- **Levels**, with his four levels (1 `# قانون …`, 2 `## الباب|الفصل …`, 3 `### المادة …`, 4 `####`):
  - Every heading line resolves to level 3.
  - The title line resolves to level 1 or to none.
  - No line of an article body matches any level other than 2 under a plain `re.match`, ignoring order and
    `not_bullet`.
  - The group chunker's target level in each file is 3 (`resolve_target_level`, common.py:514-521, at the
    canvas hierarchy), so sections start at articles.
  - The heading lines in each file number exactly its article count.
- **Text RAGFlow's markdown path would act on**, checked on each whole file:
  - A URL scheme, `www.`, or `data:`, `file:`, `javascript:`, `vbscript:`, `mailto:`.
  - A markdown image `![`, or an HTML `<img` or `src=`. RAGFlow fetches image sources over http(s) or from a
    local path (rag/app/naive.py:957-1060). `src=` is matched anywhere, in any case and with no word boundary,
    because RAGFlow's `html_img_re` (naive.py:959) has none: `xsrc='a.png'` would make it try `a.png` as a
    local file (naive.py:1055-1057).
  - A markdown link `[…](…)` or a reference definition `[…]:`.
  - The tag pattern `<(table|td|tr|th|tbody|thead|div)[^>]*>`. RAGFlow rewrites each match up to the next `>`,
    across lines and articles (deepdoc/parser/markdown_parser.py:100-113).
  - `<table`, a code fence, or any `|` (the markdown table passes run on any `|`, markdown_parser.py:74).
  - CR, U+FEFF, and C0 control characters other than LF and tab.
  - The bytes are also decoded as strict UTF-8.
- **Byte-for-byte check.** Served text outside the shard parser's normal form is refused: empty text, a run of
  three or more newlines, or a line with outer whitespace. A replace correction could produce any of these.
- **The read-back, after writing.**
  - Each file's bytes on disk equal the bytes rendered.
  - `legal_search.corpus.parse_shard` reads back exactly the served `(number, suffix, text)` list, in order.
  - This proves each served article appears once, with its text byte for byte.
  - On any failure the files written are removed, and `upload-manifest.json` is written only after all of them
    pass.

### upload-manifest.json

The manifest is deterministic: it holds no timestamp and no path of the run, so the same inputs give the same
bytes.

- **Format.** `w2_upload: 1`, and `file_shape` set to `slug-title-served-v1`.
- **Code.** `generator` (name and sha256 of this script) and `legal_search` (sha256 of the four modules used).
- **Inputs.** `inputs`: the sha256 of `laws.json`, `corrections.json` and `law-directory.md`.
- **Canvas.** `canvas`: its file name, sha256 and size, the TitleChunker's id, method, hierarchy and token cap, the
  level patterns as read, and `article_level: 3` and `caption_level: 2`.
- **Corpus.** Two digests and the baseline:
  - `corpus_sha256`: as `legal_search.evaluate.corpus_digest` and `score_w1.corpus_sha256` compute it, over each
    key and normalised text in key order;
  - `served_text_sha256`: the same rows with the text as served, so any changed byte changes it;
  - `baseline`: `{file, corpus_sha256, match}`, or `null`.
- **`upload_set_sha256`.** The sha256 of the lines `"<name> <sha256>\n"`, sorted by name.
- **`totals`.** `files`, `articles`, `bytes`, `caption_lines`, `title_lines_at_level_1` and `known_gaps`.
- **`angle_bracket_articles`.** The keys of served articles holding `<` or `>`. They are kept as served, and
  recorded rather than refused (see below).
- **`caption_tail_articles`.** The keys of served articles whose text ends in caption lines (lines that resolve
  to level 2), in file order. Each such line opens a section of its own (see the known limits below).
- **`caption_inner_articles`.** The keys of served articles holding a caption line with more of their own text
  after it. That text would follow the caption into its section.
- **`files[]`.** For each law, in registry order: `name`, `law`, `title`, `sha256`, `bytes`, `articles`, `lines`,
  `title_level` (1 or null), `caption_lines`, `target_level`, and `keys`. The keys are in file order, in the
  spec's form `<slug>:<number>[:<suffix>]`.

### Recorded run (2026-11-08)

- **Command.** The command above, with the default `--out`. It exited 0.
  - The run was then regenerated with `--replace` after comment-only edits to the script.
  - It was regenerated again with `--replace` after the review fixes (the wider `src=` hazard and the two caption
    records). It exited 0.
  - Each time, the 22 `.md` files kept their bytes (`sha256sum` before and after: no difference) and
    `upload_set_sha256` did not change. The generator and manifest hashes below are from the last run.
- **Totals.** 22 files, 6,592 articles, 3,918,455 bytes, 217 caption lines (majalla 216, evidence 1), and 19 title
  lines at level 1. The titles of civil-code, majalla and court-fees are body text. The target level is 3 in every
  file.
- **Captions.** 180 articles end in caption lines (majalla 179, evidence 1); `caption_inner_articles` is empty.
  None of the 180 is the last article of its file.
- **Corpus.** `corpus_sha256` is `1c31a2106af1…`, equal to eval-final.json's. The served-text sha256 is
  `f1100a684c0b…`.
- **Hashes.**
  - Canvas `3f0fcb62b79a…`;
  - generator `b4529d38fe5c…`;
  - upload set `4c64044f62a7…`;
  - `upload-manifest.json` `b073763228cbb83f9d1a2f5baabeae20fd95a024b18363c60c38e03a999e6bc1`.
- **Determinism.** A second run into another folder gave all 23 files byte for byte, the manifest included.
- **Regenerate after any edit.** Any edit to `make_w2_corpus.py` changes the generator sha256, and with it the
  manifest's sha256. Regenerate with `--replace` after such an edit.
- **Known gap.** civil-code 1287 has no text (laws.json `known_gaps`), so it is not in the set.

### What this does not prove, and known limits

- **The checks model only part of RAGFlow.** They cover RAGFlow's line-level title matching and the markdown passes
  named above. They do not cover its markdown element extractor or its token counts. The exact chunk total comes
  from the predictor, which runs RAGFlow's own chunker inside the pinned image, and is confirmed against the
  server.
- **Website and script fragments in our served text.** Eight served articles hold `<` or `>`, all kept byte for
  byte:
  - majalla 1851 ends with a website footer and jQuery code (`--> (function ($) { … })(jQuery); …`);
  - the last articles of mediation (14), courts-formation (23), major-felonies-court (16) and bar-association
    (110) end with a stray `<div`;
  - majalla 672, 761 and 832 end with a stray ` <`.

  They pass RAGFlow's tag rewrite only because no `>` follows a tag name in the same file. T-B2 indexes the same
  text, so the arms stay like with like. The fragments are a corpus-quality issue, to be fixed in the corpus, not
  here.
- **Invisible direction marks.** 192 zero-width or bidirectional marks (U+200B to U+200F and similar) in 76
  articles are kept as served.
- **Chunks holding two articles.** His group chunker merges a group under 32 tokens with the next one
  (group_chunker.py:22, :91). That is his recipe on our text; the shape does not try to prevent it.
- **Captions leave their article.** A kept `## الباب/الفصل` caption resolves to level 2, and the chunker opens a
  section at every line at or above the target level 3 (group_chunker.py:31). So each caption opens a section of
  its own. It then moves into the next article's chunk, unless its own article's group is under 32 tokens, in
  which case it stays with it (:91).
  - 180 articles are affected (`caption_tail_articles`: majalla 179, evidence 1). In all 180 the captions are
    trailing; none has more of its article's text after it (`caption_inner_articles` is empty).
  - No item of `content/eval/retrieval-v1.jsonl` expects any of the 180.
  - Two expected articles, majalla 300 and majalla 1660, follow such an article, so their chunk can start with
    the moved caption. All their own tokens stay in that chunk; only a few dozen characters of budget change.
  - Not measured: whether the moved caption tokens change which article a chunk is credited to under the mapping
    rule (score_w1.py:213-215). Token counts are cl100k, which the host cannot compute without tiktoken. The
    review that found this ran RAGFlow v0.27.3's own section code over the 22 files
    (`.hq/scratch/w2-review-corpus/scripts/rf_sections.py`, `captions.py`, `caption_share.py`): 6,831
    sections, 217 of which start at a caption.
  - This is the owner's pinned shape (captions kept, not demoted). It is recorded, not changed.

### Tests

```bash
cd "/d/Iqraa Law/AI Harness-w1/tools/ragflow-w2" && python -B -X utf8 -m unittest discover -s tests -t . -v
# WSL: cd "/mnt/d/Iqraa Law/AI Harness-w1/tools/ragflow-w2" && python3 -B -m unittest discover -s tests -t .
```

`tests/test_make_w2_corpus.py` holds 44 tests. They build an invented two-law library and a fixture canvas in
temporary folders.

- **Shape.**
  - The exact bytes of both files: title line, headings, a `—` inline heading, a `مكرر` article, a dropped `---`,
    a kept caption, and a known gap.
  - Every served text appears once, byte for byte.
  - No BOM and no CR.
  - A trailing caption (lease-law 2 مكرر) and a caption planted before more text (civil 4) are recorded in
    `caption_tail_articles` and `caption_inner_articles`.
- **Counts.**
  - Per-law counts and key order equal legal_search's `parse_law` plus `apply_corrections`, and the directory
    count minus gaps (with a relabel correction).
  - An off count is refused.
  - The manifest's hashes are recomputed: the files, the upload set and the canvas; `inputs` (each of the three
    files hashed on its own), the four legal_search module hashes, and the canvas's token cap, hierarchy and id.
  - `served_text_sha256` and `corpus_sha256` are recomputed from the shards, and differ.
  - A baseline mismatch is refused.
- **Library** (the ingest checks the tool repeats, and its own registry checks). Each is refused:
  - a duplicate «المادة 1», with the directory count raised to match;
  - text under the known gap civil 3, with the count raised to match;
  - a correction naming the law `nope`;
  - a folder missing from `law-directory.md`;
  - four unsafe slugs (`../x`, `Lease`, `a/b`, `-x`);
  - five titles that cannot stand on one `# ` line (trailing or leading space, empty, a newline, a leading `#`).
- **Canvas.**
  - A planted bad heading (`### مادة 2`) fails the level-3 check.
  - A stricter level-3 regex refuses a `مكرر` heading.
  - Body lines at levels 1, 3 (planted through an inline heading and through a correction) and 4 are refused.
  - A canvas whose level 2 is `^#\s+.+` makes the title line match levels 1 and 2, and is refused.
  - A level-2 caption is kept.
  - At hierarchy 2 the target level becomes 2, and the file is refused.
  - Seven canvas shapes are refused.
  - Empty patterns are dropped.
  - Title levels.
- **Hazards.**
  - Each of 19 plants, through a replace correction, is refused, naming the article. The plants added in review
    are `data:x`, `xsrc='a.png'`, `SRC="/etc/x.png"`, `<DIV a>`, `<table x` with no later `>` (so only the
    `<table` hazard can catch it), and DEL.
  - The tag rewrite is caught across articles.
  - An unclosed `<div` at the end of a file is kept and recorded.
  - A lone `>` is kept and recorded.
  - A `---` line is caught by the read-back, and the files are removed.
  - Text outside the parser's normal form is refused before anything is written.
- **Determinism.** The same bytes, manifest included, in two folders.
- **Out folder.**
  - A non-empty folder is refused, and its file is untouched.
  - Without `--replace`, a second run into the same folder is refused. With it, the run removes a stale
    `old-law.md` and rewrites the folder.
  - `--replace` never removes a foreign entry.
  - `--replace` never removes a symlinked `*.md`. Windows refuses `os.symlink` without a privilege, so the test
    patches `is_symlink` on one regular file.
  - An `--out` that is a file is refused, and the file is untouched.
  - A missing folder is created.
  - A `python -I` run from a folder holding a planted `json.py` succeeds.
- **Real data** (skipped when the library or the canvas is absent).
  - Our library gives 22 files and 6,592 articles. The per-law counts equal the directory minus the gaps, the
    target level is 3, and the corpus sha256 equals eval-final.json's.
  - Walid's canvas holds exactly the four patterns the fixture retypes, with group method and hierarchy 3. His
    file is read only by the tool, run as `python -I` in a subprocess.

On 2026-11-08, the suite passed on the host (Python 3.11.9, the Git Bash command) and in WSL (Python 3.13.5, the
WSL command). After the review fixes, the 44 tests passed again in both, and so did the whole `tests/` folder.

On 2026-11-08, each of 11 in-process mutations made at least one test fail. They were: the body-level check
removed; the tag, URL or CR hazard removed; the read-back removed; the out-folder refusal removed; captions
demoted; the title line dropped; every `###` line taken as level 3; the target level fixed at 3; and the corpus
sha changed. The runner, `.hq/scratch/w2-run/probe/mutate.py`, is outside the repository.

That sample was narrow. A review then ran source-level mutants on a copy of the script, one at a time, each against
the copied test file, and 19 that mattered survived. After the tests above were added, the same set was rerun, with
the `src=` mutant moved to the new pattern, the reviewer's «canvas reads graph node form» entry dropped (it only
rebuilt the same `components` dict, so it changed nothing), and 7 mutants added for the fix. The runner is
`.hq/scratch/w2-corpus-fix/mutants.py`, outside the repository. Of 34 mutants, 29 make a test fail. The 5 that
survive are equivalent, here or under his canvas:

- **The heading-count check removed.** `render` writes one heading line per article, so the count always matches,
  and the read-back would catch an extra article.
- **The read-back byte compare removed.** The bytes are read straight back after being written, so they can differ
  only on a disk fault. The parse compare that follows still checks the content.
- **The `not_bullet` exclusion removed.** It acts only on lines that start with a digit (rag/nlp/__init__.py:366-368).
  Every one of his patterns needs a leading `#`, so no line can match both.
- **The hierarchy clamp to 1 removed.** It matters only at hierarchy 0 or below. There RAGFlow does not call
  `resolve_target_level` but uses its own `most_level` (group_chunker.py:39-41), a case this tool does not model.
  His hierarchy is 3.
- **Caption flags taken from the plain matches.** A body line's plain matches can only be level 2 (anything else
  is refused), so this differs from the resolved level only when `not_bullet` excludes the line, which cannot
  happen under his canvas.

## The sealed stack

`compose.yaml` (project `ragbench-rf`) is the throwaway RAGFlow v0.27.3. It was reconciled from the research
draft (`.hq/scratch/w2-research/deploy/compose.yaml`), with the critic's gaps closed (table below). RAGFlow
claims cite the v0.27.3 source in `.hq/scratch/ragflow-src-v0.27.3/x/`.

| Service | Container | Image | Store | Role |
|---|---|---|---|---|
| `es01` (profile `es`) | `ragbench-rf-es01` | `elasticsearch:8.11.3` | tmpfs 12g | the deciding engine |
| `infinity` (profile `infinity`) | `ragbench-rf-infinity` | `infiniflow/infinity:v0.7.4-x64-v3` | tmpfs 12g | the exploratory engine, on a fresh stack |
| `mysql` | `ragbench-rf-mysql` | `mysql:8.0.40` | tmpfs 4g | accounts, datasets, documents, tasks |
| `minio` | `ragbench-rf-minio` | `pgsty/silo:RELEASE.2026-08-06T00-00-00Z` | tmpfs 4g | the uploaded files |
| `redis` | `ragbench-rf-redis` | `valkey/valkey:8` | tmpfs 2g, no snapshot | the task queue and cache |
| `tei` | `ragbench-rf-tei` | `ghcr.io/huggingface/text-embeddings-inference:cpu-1.8` | the model, read-only | the built-in embedder |
| `tei-probe` | `ragbench-rf-tei-probe` | `python:3.12-slim` | none | waits for TEI, then exits |
| `ragflow` | `ragbench-rf-server` | `infiniflow/ragflow:v0.27.3` | logs on tmpfs 1g | the API server and task executor |
| `runner` | `ragbench-rf-runner` | `python:3.12-slim` | tmpfs `/tmp`, `/run/rf` | our tools, and the key |

Each image is referenced as `<tag>@${RF_PIN_*}`. The prepare step fills the digests from
`docker buildx imagetools inspect` into `.hq/scratch/w2-run/state/pins.vars`, passed with `--env-file`. A
missing pin stops compose before anything starts (every variable is `:?`-guarded; checked: without the pins
file, `config` exits 1 naming each missing value).

**Isolation.**

- **Names.** Every container is `ragbench-rf-*`. The one network is `ragbench-rf-net`. The base file creates no
  named volume. Teardown matches the prefix `^ragbench-rf-` only. The existing volume `ragbench-cargo` has no
  compose labels and does not match.
- **No egress.** `ragbench-rf-net` is `internal: true`. Docker drops all traffic between an internal network and
  any other network. No service joins a second network, and upstream's `extra_hosts: host.docker.internal` is
  dropped. `net_check.py` proves it at run time from the server's namespace and from the TEI network, with a
  positive control each time (runbook P7, E2).
  - `internal: true` removes the route out, not the bridge's own address. The one host-side address a container
    on it may still reach directly is the network's gateway, on its own subnet. So P7 and E2 also block the
    gateway (read with `docker network inspect`) on 443 and on a port another container publishes. That result
    is recorded as it comes; it has not been run yet.
  - A «no address» result for `host.docker.internal` only says the name does not resolve on an internal
    network. It proves nothing about the host's address; the gateway lines are the test of that.
- **Nothing published.** No service has `ports:`. Checked on 2026-11-08 by rendering both profiles with
  `docker compose config --format json` (placeholder pins and secrets): no service lists a port, the network is
  internal, and the runner's `network_mode` is `service:ragflow`.
- **How our tools reach the API.** The runner shares the server's network namespace, so
  `http://127.0.0.1:9380` is the API and it is loopback. run_w1.py accepts loopback http without
  `--allow-insecure-http` (run_w1.py:125-146). The runner reaches nothing the server cannot.
- **Sign-up off from the first boot.**
  - `REGISTER_ENABLED=0` is read at start (common/settings.py:342-346).
  - The one account is made by `--init-superuser` from `DEFAULT_SUPERUSER_*` in the secrets file
    (api/ragflow_server.py:125-132; api/db/init_data.py:42-82).
  - `POST /api/v1/users` refuses before anything else (user_api.py:504-509), and `rf_ingest.py preflight`
    probes it.
- **What runs in the server.**
  - `API_PROXY_SCHEME=python`: the Python API server and task executor start only then
    (docker/entrypoint.sh:340-343, :389-393).
  - The admin server, the MCP server and data sync are off (entrypoint.sh:49-50, :93-95).
  - `SANDBOX_ENABLED=0`. No chat model is configured.
- **Secrets.**
  - One file, `RF_SECRETS`, holds them, with random hex values. It is written by the prepare step, never printed,
    outside every repository: `C:/Users/accou/.ragbench-rf/secrets.conf` if writable, otherwise
    `.hq/scratch/w2-run/secrets/` (gitignored, mounted nowhere).
  - It reaches es01, mysql, minio, redis and the server as `env_file`. TEI, tei-probe and the runner get none of
    it.
  - Nothing reads a file named `.env`.
- **The API key.** `make_key.py` creates it over HTTP inside the server. It is piped into the runner's tmpfs
  (`/run/rf/key`, mode 0700), so it never touches the host disk. It dies with the runner and with MySQL's
  tmpfs.
- **Stores on tmpfs.** Nothing survives `down`. The sizes are caps.
  - The ES tmpfs is 12g because upstream's absolute watermarks need free room (docker-compose-base.yml:22-25).
  - MySQL runs upstream's documented opt-in for a rebuildable database (no binlog, relaxed flushing,
    docker-compose-base.yml:227-241).
  - Valkey keeps no snapshot and no append-only file.
- **The one volume fallback.** `compose.store-volumes.yaml` moves MinIO or Infinity to a throwaway named volume
  (`ragbench-rf-minio-data`, `ragbench-rf-infinity-data`). Use it only if that store refuses tmpfs at start.
  - Why it might: both may open files with O_DIRECT, which tmpfs accepts only from Linux 6.6.
  - This machine runs 6.18.54.1-microsoft-standard-WSL2 (`docker info`, 2026-11-08), so the fallback is not
    expected to be needed.
- **TEI.**
  - It serves `Qwen/Qwen3-Embedding-0.6B` at the pinned revision from `.hq/scratch/w2-run/models`, read-only,
    with `HF_HUB_OFFLINE=1`.
  - The server uses it as the built-in embedder, because `COMPOSE_PROFILES` contains `tei-`
    (common/settings.py:392-395; api/db/joint_services/tenant_model_service.py:265-280).
  - If the model loads too slowly through Docker Desktop's Windows share, `compose.tei-volume.yaml` reads a
    checked copy from the throwaway volume `ragbench-rf-tei-models` instead (runbook P8).
  - RAGFlow posts raw text to TEI's `/embed` for chunks and queries alike (rag/llm/embedding_model.py:1245-1255),
    so Qwen3's query instruction is never used. That is RAGFlow's behaviour, and it is kept.
- **TEI readiness without curl.**
  - Upstream gives TEI no health check (docker-compose-base.yml:422-433), and its image may hold no curl.
  - The one-shot `tei-probe` (`tei_probe.py wait`, Python only) polls `/health`, then checks that `/info`
    names the model and that `/embed` returns one vector.
  - The server `depends_on` it with `service_completed_successfully`. The other stores keep upstream's own
    health checks (docker-compose-base.yml:31-35, :96-100, :271-275, :317-321, :337-341).
- **Embedding batch size.**
  - `EMBEDDING_BATCH_SIZE` (common/settings.py:517) is required from the first boot. It comes from the prepare
    probe (`tei_probe.py time`).
  - `MAX_CONCURRENT_CHUNK_BUILDERS=1` keeps one embedding batch at a time in flight, as the probe timed it
    (rag/svr/task_executor_limiter.py:21-26).
  - TEI never gets more than 16 texts per call, whatever the setting: `BuiltinEmbed.encode` splits at 16
    (embedding_model.py:245-255).
- **DEBUG logging, kept whole.**
  - `LOG_LEVELS=root=DEBUG,…` makes the server log its dense-only fallback, a root-logger DEBUG line
    (rag/nlp/search.py:357, :394).
  - Named loggers are set one by one (common/log_utils.py:50-70). The doc-store clients, which log whole
    queries and answers at DEBUG (rag/utils/es_conn.py:342, :353), and the HTTP clients stay at INFO.
  - The server logs to `json-file`, capped at 20 files of 100 MB (2 GB). The ingest logs at root DEBUG for
    hours onto the Docker Desktop VM disk the other containers share, so the log is not left unbounded. This
    daemon's default driver is `local` (`docker info`, 2026-11-08), which keeps only 5 files of 20 MB.
  - `docker logs` reads the rotated files too, so a line is lost only once the cap is spent. Only the span of one
    query arm must survive, and E7 saves each arm's log right after the arm. Rotation drops the oldest lines
    first, and `fallback_items.py` stops when an answered request has no retrieval call in the saved log, so
    its exit 0 shows that the saved log covers the arm.
- **The runner.**
  - `python:3.12-slim`, the image already on this machine, pinned by its local digest. It is read-only,
    `init: true`, with tmpfs `/tmp` and `/run/rf`.
  - Mounts: `/w2` (these tools, read-only), `/w1` (`../ragflow-w1`, read-only, for `run_w1.py`), `/pkg`
    (`.hq/docs/specs/w1-for-walid`, read-only, for the queries), `/in` (the upload set, read-only), `/canvas`
    (the canvas copy, read-only) and `/out` (run outputs, the only writable mount).
  - The server gets `/w2`, `/in` and `/canvas` read-only, for `predict_chunks.py` and `make_key.py`. It
    writes nothing to the host.
  - Every bind sets `create_host_path: false`, so a missing folder stops `up` rather than appearing empty.
- **Caps.** es01 8g and 4 CPUs, Infinity 10g and 4 CPUs, the server 12g and 6 CPUs, TEI 12 CPUs. The machine
  has 24 CPUs and 64 GB (`docker info`).

### The critic's gaps: closed, or carried as a known limit

| Gap (critic-summary.txt) | Status | Where |
|---|---|---|
| BLOCKER: the runbooks disagree on how calls reach the server and where the key lives | closed | every API call runs in the runner (`rf_ingest.py`, `run_w1.py`); no host port, no host-key file, no web-UI key, no host curl to the API |
| BLOCKER: nothing can score W2 output | handed on | `rf_ingest.py` writes the W2 manifest (contract below) and `w2_check.py` sets `all_match`. `--own-run` in `score_w1.py` belongs to the scorer step |
| MAJOR: no pre-registered rule; engine; embedder | closed by the owner | spec amendment 2026-11-08: Elasticsearch + Qwen3-0.6B + FINAL REVIEW v3 + `query` on half B decides. Profiles `es`/`infinity`, one engine per fresh stack, and one TEI model per stack |
| MAJOR: two file shapes, two generators, two simulators | closed | the shape is pinned (`slug-title-served-v1`, `make_w2_corpus.py`). There is one predictor, which runs RAGFlow's own chunker in the pinned image, and `w2_check.py`'s ALL MATCH gates every query |
| MAJOR: the dense-only fallback is not recorded | closed, with limits | DEBUG logging kept whole, `timed_run.py` stamps, and `fallback_items.py`, whose limits are stated in its docstring and below |
| MAJOR: the threshold mostly mutes the dense leg | carried | a known limit, written into the spec amendment. It is the report's to state |
| MAJOR: no held-out-half reading | handed on | half B is the scorer step's |
| MAJOR: embedding timeouts; batch size left as a fallback | closed, with a limit | the batch size comes from a timed probe and is required at first boot. Only failed documents are re-parsed, at most twice, through `/documents/parse`. The 30-second, no-retry client timeout itself remains RAGFlow's |
| MAJOR: TEI health check relies on curl; egress tests pass for the wrong reason | closed | `tei-probe` in Python. `net_check.py` checks every egress block after a positive control and does not count «refused» as blocked. Besides `host.docker.internal`, whose «no address» proves little, P7 and E2 block the network's own gateway |
| MINOR: corpus step 5 cannot run | closed | `predict_chunks.py` runs by `docker exec` with `/ragflow/.venv/bin/python` and `/ragflow` on `sys.path` |
| MINOR: a naive dataset could be queried by mistake | closed | `rf_ingest.py` creates exactly one dataset, pipeline-bound, on a stack it checks holds none; the manifest records its id |
| MINOR: names, paths, teardown differ | closed | one project and prefix, `.hq/scratch/w2-run`; only the 22 `*.md` are uploaded, and 22 documents are checked |
| MINOR: heavy.sh does not hold the heavy work | carried | the parse wait and both query runs are blocking commands under `heavy.sh`. Its slot still frees itself after 45 minutes (heavy.sh:10), and no more is claimed |
| MINOR: faithfulness rests on unverified facts | carried | the report says «his indexing-pipeline canvas». Its sha256 is recorded, and `rf_ingest.py` refuses a pipeline stored differently from the file |
| MINOR: dataset language and file names | closed / recorded | language `English`, RAGFlow's default (db_models.py:1269), sent explicitly and recorded; file names are registry slugs (the pinned shape) |
| MINOR: digest checks are circular | closed | `imagetools inspect` before any pull, compared with the Docker Hub digests read on 2026-11-08; pulls are by digest |

## rf_ingest.py, predict_chunks.py and w2_check.py

These three build the W2 dataset and prove it holds what RAGFlow's own chunker makes of our files, before any
query is sent. The helpers that go with them are described below them.

### rf_ingest.py (runs in the runner)

`python3 -I -B /w2/rf_ingest.py <step> --engine elasticsearch|infinity …`. Its docstring lists every route it
may send, with the v0.27.3 source lines; `ROUTES` refuses anything else before it is sent. It uses no proxy and
follows no redirect, and only loopback http (and `ragbench-rf-tei` for TEI's `/info`) is accepted.

- **`preflight`** checks, and prints one line each:
  - the version is `v0.27.3`;
  - healthz is ok;
  - `registerEnabled` is 0, and a sign-up probe is refused with code 103;
  - `GET /system/status` names the doc engine asked for (es_conn_base.py:72; infinity_conn_base.py:512);
  - TEI's `/info` names `W2_TEI_MODEL`;
  - and it counts the datasets.
- **`create`**:
  - checks the inputs. The canvas must be exactly File → Parser → TitleChunker → Tokenizer. The upload set must
    be exactly the 22 `<slug>.md` files `upload-manifest.json` lists, byte for byte (sha256), with
    `file_shape` `slug-title-served-v1`, made against the same canvas (`canvas.sha256`), each starting
    «# » and holding «### المادة»;
  - runs `preflight` and refuses a stack that already holds a dataset;
  - imports the canvas DSL as it is (`POST /api/v1/agents`, `canvas_category` `dataflow_canvas`), and refuses
    if the stored components differ from the file;
  - creates the dataset `w2-laws-<engine>` with `embedding_model` `<model>@Builtin`, `parse_type` 2,
    `pipeline_id` and `language`, and no `chunk_method`. The dataset still lists `chunk_method` `naive`,
    because `create_with_name` fills `parser_id` when none is given (knowledgebase_service.py:494). The
    binding that counts is `pipeline_id`, which each document is checked to carry (file_service.py:672);
  - uploads the 22 files in one multipart request, one `file` part each, and checks the names, the sizes and
    the pipeline id of the 22 documents created;
  - starts the parse with `POST /datasets/<id>/documents/parse`.
- **`wait`** polls the document list (every 30 s by default). It prints one progress line per poll, and one
  line when a document finishes or fails, with the last line of its progress message, redacted and cut at 200
  characters. When every document has stopped, the failed ones alone are parsed again, at most twice. It
  blocks until all 22 are `DONE`, or fails after `--max-wait` (12 h by default; run it again to keep waiting).
- **`dump`** lists every chunk of every document, in pages of 100 (the REST maximum). It keeps each chunk id
  once, and needs the unique count to equal the listing's total, the document's `chunk_count` and the count at
  the end of the parse; a listing that does not add up is listed again, up to 3 times. It then checks the
  dataset's own `document_count` (22) and `chunk_count`, and writes `chunks.jsonl` and `w2-manifest.json`.
  A chunk text that repeats inside one law can never add up (see predict_chunks.py below), which is why runbook
  E4 stops on any repeat before the ingest starts.
- **`all`** runs create, wait and dump. Each step keeps `ingest-state.json` (ids, hashes, parse rounds), so
  `wait` and `dump` can be run again after an interruption. A folder that already holds a run is refused.
- **The key.**
  - It is read from `/run/rf/key` and sent only in the `Authorization` header of the routes that need it: never
    to the anonymous routes, never to TEI.
  - It never prints a response body. Messages are cut at 200 characters, with the key and any Bearer token
    removed. Every file it writes is scrubbed of the key too.
- **Exit codes.** 0 done; 1 a check failed or the server refused, with the state kept; 2 refused before
  sending.

**The W2 manifest** (`out/<engine>/w2-manifest.json`, exactly the contract's keys):

| Key | Value, and where it comes from |
|---|---|
| `w2`, `created_at` | 1; the time of the dump |
| `engine` | `--engine`. It must equal `W2_DOC_ENGINE` (compose) and the server's `/system/status` |
| `embedder` | `{name: W2_TEI_MODEL, revision: W2_TEI_REVISION, via: "builtin-tei"}`. The name is checked against TEI's `/info` and the dataset's `embedding_model` |
| `ragflow_version` | `GET /system/version` |
| `ragflow_image_digest` | the digest in `W2_RAGFLOW_IMAGE`, the server's pinned image |
| `dataset_id`, `language`, `document_count`, `chunk_count` | the dataset as the server lists it after the dump |
| `predicted_chunk_count`, `all_match` | `null` and `false`; only `w2_check.py` sets them |
| `canvas_sha256`, `upload_manifest_sha256` | the sha256 of the bytes read |
| `file_shape` | `slug-title-served-v1`, checked against the upload manifest |
| `embedding_batch_size` | `W2_EMBEDDING_BATCH_SIZE`, the value the server was started with |

### predict_chunks.py (runs in the server container)

It is run as `docker exec ragbench-rf-server /ragflow/.venv/bin/python -B /w2/predict_chunks.py --canvas … --in-dir /in`,
with its stdout saved on the host.

- **Why `docker exec`.** It does not use `docker run`, because the image's entrypoint refuses unknown arguments
  (Dockerfile:321; docker/entrypoint.sh:164-166). It does not use `python -I`, which would drop
  `PYTHONPATH=/ragflow/` (Dockerfile:282). It also puts `/ragflow` first on `sys.path` itself, and takes its
  own folder off it.
- **What it runs.** RAGFlow's own code, not a copy:
  - `Parser._markdown` with the canvas's Parser params (ParserParam update and check, as
    agent/canvas.py:113-124 does);
  - then the canvas's TitleChunker method (group here) with TitleChunkerParam, fed what the pipeline feeds it
    (rag/flow/base.py:41-45; rag/flow/pipeline.py:175-177);
  - token counts from `common.token_utils`.
- **The Tokenizer is not run.** It never changes chunk text (rag/flow/tokenizer/tokenizer.py:127-195), and the
  stored content is that text (rag/svr/task_executor.py:946-948).
- **Output.**
  - A header line `{"w2_predict": 1, "canvas_sha256", "files": {name: sha256}, …}`, then one ASCII JSON line
    per chunk.
  - A summary per file on stderr: chunks, chunks with two or more article headings, chunks with none, the
    largest token count, and repeated texts. The runbook saves it as `predict-summary.txt`.
- **Why a repeated text stops the run (E4).** It is not simply «stored once»:
  - RAGFlow gives a chunk the id xxh64(text + document id) (task_executor.py:926-927), so copies share an id;
  - but it adds every copy to the document's and the dataset's `chunk_count` (task_executor.py:972;
    document_service.py:774, :790-793);
  - Elasticsearch keeps one row per id (es_conn.py:378-380). Infinity deletes the batch's ids and then inserts
    the whole batch (infinity_conn.py:626-635), so copies in one batch may both stay.
  - So `dump` cannot make the counts add up, `w2_check.py`'s multiset comparison cannot match, and the scorer
    needs `predicted_chunk_count` equal to `chunk_count` (score_w1.py:893-894). Handling repeats would mean
    engine-specific arithmetic nobody can check here. The runbook therefore requires `repeated texts 0` for all
    22 files before E5. How likely a repeat is in our corpus is unknown until E4 runs.

### w2_check.py (runs on the host)

It compares `predicted-chunks.jsonl` with `chunks.jsonl`, per law and in total.

- **What it compares.**
  - The counts, and the texts byte for byte, as multisets. The order is not compared: pipeline chunks carry no
    `chunk_order_int` (task_executor.py:919-951), and the listing sorts on it (chunk_api.py:631-640;
    search.py:302-306), so the listing order is not the file order.
  - That the predictor read 22 files, and the manifest's `document_count` (22) and `chunk_count`. The manifest
    holds no document names: the names are compared law by law, and against the ingest state.
  - That the predictor read the same canvas (`canvas_sha256`) and the same files, by name and sha256, as were
    uploaded. `--ingest-state` is required for that; without it the check refuses (exit 2).
  - A text predicted twice inside one law is BAD, with the reason above.
- **What it prints.** One line per law, then `ALL MATCH`, or the first differences (`--show`, 3 per law).
  Texts that share a first line are paired, and it says at which character they part.
- **What it writes.**
  - The manifest, atomically: `predicted_chunk_count`, and `all_match` true only on ALL MATCH. Any other
    outcome sets `all_match` back to false.
  - `w2-check.json`, with the per-law counts and the sha256 of both inputs.
- **Exit codes.** 0 ALL MATCH, 1 differences, 2 bad input. Bad input leaves the manifest untouched.
- **The gate.** No query is sent before ALL MATCH.

### The helpers

- **`make_key.py`** runs in the server container and writes one API key to stdout, for a pipe into the
  runner's tmpfs only.
  - It logs in as the boot-time account, with RAGFlow's own `crypt()`.
  - It takes the JWT from the answer's `Authorization` header and creates the key with
    `POST /system/tokens`.
  - It refuses to run when stdout is a terminal. Errors give a code or an HTTP status only.
  - Reviewed against deploy's draft, it adds: the terminal refusal, no redirect, a check that the token has no
    whitespace, and running from the read-only `/w2` mount rather than stdin.
- **`tei_probe.py`** has two commands.
  - `wait` is the readiness gate described above.
  - `time` is the prepare probe. It takes the 16 longest article blocks of the upload set, about one chunk
    each, and times `/embed` for batches of 16, 8, 4, 2 and 1, twice each. It prints
    `EMBEDDING_BATCH_SIZE=<largest batch whose slowest call is under 15 s>`. The 15 s is half of RAGFlow's
    30-second client timeout, which has no retry.
- **`net_check.py`** takes `--reach` targets (the positive control, which must connect) and `--block` targets
  (which must not).
  - Only a name that does not resolve, an unreachable network or host, or a timeout count as blocked.
  - «Connection refused» means a host answered, so it fails the check.
- **`timed_run.py`** runs a command and writes each output line with a UTC timestamp to `--log`. It exits with
  the command's code.
- **`fallback_items.py`** writes `w2-fallback-<arm>.json` as `{"query": [ids], "question": [ids]}`: the items
  whose returned chunks came only from the dense-only fallback. A report goes beside it.
  - **How it matches.** Every retrieval call logs «[Search] page=» at its start (search.py:776), through the
    same root logger and level as the fallback lines. A fallback line belongs to the nearest such line before
    it from the same process. Calls map to run_w1's requests in plan order when their number equals the number
    of requests. Otherwise they are placed by time, from the `timed_run.py` stamps, and the last attempt in a
    request's span wins. Every call must also lie inside its request's span.
  - **`--run-log` is required.** Without the stamps, an equal count could hide two errors that cancel: a request
    refused before retrieval and a retried one. The mapping would then be shifted by one. Without the flag it
    refuses (exit 2).
  - **When it stops.** On any disagreement it writes nothing and exits 1: a call outside every request's span,
    an answered request with no call in its span, or a fallback line from a process that logged no call. A
    progress line that names another item than its results row is refused (exit 2). Calls logged outside the
    run's time window are ignored.
  - **What it lists.** A fallback that returned nothing is reported, not listed: the item is empty either way.
  - **What it cannot prove.**
    - That no other client called retrieval meanwhile. The stack is sealed, and an extra call breaks the count,
      but a concurrent call that replaced a retried one would not be seen.
    - That no fallback line was lost some other way. Rotation drops the oldest lines first, so a fallback line
      cannot rotate away without the call before it, and a lost call of an answered request stops the tool.
      A fallback line lost alone would not be seen.
    - Anything about the unlogged relaxed hybrid retry (search.py:378-391).
    - Exact times. The cross-check stops it if a delay misplaces a call.

### Tests

The tests run with the same command as the generator's tests above. Nothing here contacts another host.

- **`tests/test_rf_ingest.py`** (53 tests) runs rf_ingest.py against `tests/fake_ragflow_w2.py`, a local fake of
  the v0.27.3 routes, whose shapes are cited in its docstring. The fake has one setting per answer that
  rf_ingest.py checks, so each check has a test in which that answer is wrong.
  - **Routes.** The routes and their order. The canvas imported as it is, as a dataflow canvas. The dataset
    body exactly (`parse_type` 2, the pipeline id, `…@Builtin`, no `chunk_method`). One multipart request with
    22 `file` parts, each byte for byte. The key only in the `Authorization` header of the routes that need it.
    Chunk pages of 100.
  - **Results.** Every chunk dumped once. The manifest with exactly the contract's keys, `all_match` false, and
    the hashes and run facts.
  - **Polling.** Only a failed document parsed again. Giving up after two rounds, with no manifest. Progress
    lines. `wait` and `dump` re-run from the state file. An unstable listing listed again, and one that never
    adds up writing nothing.
  - **Refusals.** 21 files; an unlisted `.md`; changed bytes; another canvas; a component outside the chain;
    the chain out of order; another `file_shape`; a file name that is not a slug; a file without its title
    line; a used out folder; an out folder not named after the engine; another engine; a TEI revision that is
    not 40 hex; a non-loopback URL; a stack holding a dataset; open sign-up; another version; another doc
    engine; TEI serving another model; a pipeline stored differently.
  - **Server answers**, each wrong once, and the run stops before the next step: healthz `nok` (HTTP 500); a
    sign-up refused with another message; the pipeline stored as another canvas category; the dataset stored
    with another `pipeline_id`, `embedding_model` or `language`; a document stored without our pipeline id or
    with another; a document renamed as a duplicate; a parse started for 21 of 22; a 23rd document in the
    dataset; a document `chunk_count` other than its listing; a count that changes between `wait` and `dump`;
    a dataset `document_count` or `chunk_count` other than the dump; a redirect, refused and not followed; a
    proxy named in the environment, not used.
  - **The key.** The key in no output and no file, even when the server echoes it: in a failure message, in a
    stored dataset name written to the state file, and in a TEI answer that is logged. A key file holding
    anything else is refused.
- **`tests/test_w2_check.py`** (15 tests).
  - The same texts in another order match and set `all_match`.
  - One changed byte is found and located. A missing chunk; a stored-only document; a wrong manifest count;
    another canvas; other file bytes; a prediction of 21 files; a manifest `document_count` of 21. A mismatch
    resets an earlier `all_match`, and repeats are named.
  - The report hashes. Bad input, a check without `--ingest-state` and an ingest state without its file list
    leave the manifest untouched.
- **`tests/test_fallback_items.py`** (16 tests) uses invented log fixtures.
  - **Matching.** The right field and item. A call logged before the run, ignored. A fallback that returned
    nothing. A retried request placed by time, and judged by the attempt whose answer was kept.
  - **Refusals.** No `--run-log`; a call outside every request; an answered request with no logged call; a
    progress line naming another item than its row; a call outside its request's time; a fallback line from a
    process that logged no retrieval call; no DEBUG lines; an incomplete run; an existing output.
  - **`timed_run.py`.** It stamps each line and keeps the exit code, and refuses an existing log.
- **`tests/test_probes.py`** (7 tests). `tei_probe.py`'s batch choice and article blocks. `net_check.py`:
  connected; refused counts as not blocked; an unresolvable name is blocked; no positive control is refused.

On 2026-11-08 these 91 tests, and the whole folder's suite with the generator's tests (135), passed on the
host (Python 3.11.9, the Git Bash command above).

**What the tests catch, measured with a list chosen by a reviewer, not by the builder.** An earlier version of
this section reported «21 of 21 mutations killed». That was true of a list the builder chose, and it did not
measure coverage. The review's list, `.hq/scratch/w2-review-stack/mutate_review.py` (31 mutations, one copy of
the folder per mutation, never the worktree), measures it instead:
- Before the fix: **1 of 31 killed** (only the canvas-sha check). Re-run on 2026-11-08 on a snapshot of the
  folder as it was: `.hq/scratch/w2-fix-stack/before-pristine.txt`.
- After the fix: **27 of 31 killed** (`.hq/scratch/w2-fix-stack/after-fixed.txt`). Every check of rf_ingest.py,
  w2_check.py and fallback_items.py on the list is killed. Without two of them (the created-names check and
  the «exactly our documents» check) the run still stops before the next step, by a crash rather than a clear
  message, so no wrong dataset gets through; the tests fail either way.
- The 4 survivors are helpers that no finding of the review named, and they have no test yet: net_check.py
  counting a timeout as blocked; timed_run.py masking a key in the command line; tei_probe.py's `/info` model
  check in `wait` and its vector-count check in `time`. They run in P7, E1, E2 and E7, where the operator reads
  their output.
- Three more, in `.hq/scratch/w2-fix-stack/mutate_extra.py` (`extra.txt`): the review's no-proxy and
  no-redirect mutation split in two, each half killed by its own test; and w2_check.py accepting an ingest
  state without a file list, killed.

Each of these files is outside the repository.

`predict_chunks.py` and `make_key.py` need RAGFlow's code and a running server: here they are only parsed, and
they are first exercised in runbook steps E3 and E4. `docker compose config --quiet` passed for both profiles,
alone and with each override file.

### What this does not prove

- **The fake is not RAGFlow.** The routes and answer shapes are read from the v0.27.3 source, not from a live
  server. The first live run checks them, and each step stops on the first answer that differs.
- **Predicted and stored can both be wrong the same way.** The predictor runs RAGFlow's own Parser and
  TitleChunker. A step that both of them skip would not show, but none is known: the stored text is the chunker's
  text (task_executor.py:919-951).
- **The probe's timing is one moment's.** The ingest also embeds each file name once per document
  (tokenizer.py:93-97). Other load on the machine can slow TEI after the probe.

## Runbook

Git Bash on this machine, in order, by the main agent: subagents run no git, and these steps hold the only
run state. Stop at the first check that fails. Heavy steps go through `heavy.sh`. Paths given to docker are
`D:/...` (with `MSYS_NO_PATHCONV=1`), and bash reads `heavy.sh` by its POSIX path. The hosted OpenRouter run is
not part of this runbook.

### P0. Variables (every new shell)

```bash
set -o pipefail                  # a step piped into tee keeps the step's exit code (P7, E5)
export MSYS_NO_PATHCONV=1
export RF_WS="D:/Iqraa Law"
T="D:/Iqraa Law/AI Harness-w1/tools/ragflow-w2"
RUN="D:/Iqraa Law/.hq/scratch/w2-run"
HEAVY="/d/Iqraa Law/.hq/scratch/heavy.sh"
PINS="$RUN/state/pins.vars"
CF=(-f "$T/compose.yaml" --project-directory "$T" --env-file "$PINS")
# only if P8 switched TEI to the volume copy: CF+=(-f "$T/compose.tei-volume.yaml")
[ -s "$RUN/state/secrets-path.txt" ] && export RF_SECRETS="$(cat "$RUN/state/secrets-path.txt")"
```

### P1. Folders, and a snapshot of what exists before

```bash
mkdir -p "$RUN/state" "$RUN/out/elasticsearch" "$RUN/out/infinity" "$RUN/models" "$RUN/logs" "$RUN/canvas"
docker ps -a --format '{{.ID}} {{.Names}}' | sort > "$RUN/state/before-containers.txt"
docker volume ls --format '{{.Name}}' | sort > "$RUN/state/before-volumes.txt"
docker network ls --format '{{.ID}} {{.Name}}' | sort > "$RUN/state/before-networks.txt"
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | sort > "$RUN/state/before-images.txt"
grep -c 'ragbench-rf-' "$RUN"/state/before-*.txt          # 0 for each file
grep -x ragbench-cargo "$RUN/state/before-volumes.txt"     # listed: it must still be there at the end
```

### P2. The secrets file, outside every repository

The values are random hex: the entrypoint `eval`s template lines (docker/entrypoint.sh:180-193), so they hold no
quote or `$`. They are never printed. If an agent's rules block the first place, the second is used.

```bash
SEC=/c/Users/accou/.ragbench-rf; SECW=C:/Users/accou/.ragbench-rf
if ! ( umask 077; mkdir -p "$SEC" && touch "$SEC/.w" && rm "$SEC/.w" ) 2>/dev/null; then
  SEC="/d/Iqraa Law/.hq/scratch/w2-run/secrets"; SECW="D:/Iqraa Law/.hq/scratch/w2-run/secrets"; ( umask 077; mkdir -p "$SEC" )
fi
F="$SEC/secrets.conf"
if [ -e "$F" ]; then echo "secrets file exists: reuse it or delete it first"; else
  ( umask 077; h() { python -I -c "import secrets,sys; print(secrets.token_hex(int(sys.argv[1])))" "$1"; }
    MY=$(h 16); MI=$(h 16)
    { printf 'MYSQL_PASSWORD=%s\nMYSQL_ROOT_PASSWORD=%s\n' "$MY" "$MY"
      printf 'ELASTIC_PASSWORD=%s\nREDIS_PASSWORD=%s\n' "$(h 16)" "$(h 16)"
      printf 'MINIO_USER=rag_flow\nMINIO_ROOT_USER=rag_flow\nMINIO_PASSWORD=%s\nMINIO_ROOT_PASSWORD=%s\n' "$MI" "$MI"
      printf 'RAGFLOW_SECRET_KEY=%s\n' "$(h 32)"
      printf 'DEFAULT_SUPERUSER_NICKNAME=w2\nDEFAULT_SUPERUSER_EMAIL=w2-owner@ragbench.invalid\nDEFAULT_SUPERUSER_PASSWORD=%s\n' "$(h 16)"
    } > "$F" ) && echo written
fi
echo "$SECW/secrets.conf" > "$RUN/state/secrets-path.txt"; export RF_SECRETS="$SECW/secrets.conf"
grep -c '=' "$F"                                            # 12 lines (counted, not shown)
```

### P3. Pin every image by digest (read-only registry calls)

```bash
pin() { docker buildx imagetools inspect "$1" | awk '$1 == "Digest:" {print $2; exit}'; }
{ echo "RF_PIN_RAGFLOW=$(pin infiniflow/ragflow:v0.27.3)"
  echo "RF_PIN_ES=$(pin elasticsearch:8.11.3)"
  echo "RF_PIN_INFINITY=$(pin infiniflow/infinity:v0.7.4-x64-v3)"
  echo "RF_PIN_MYSQL=$(pin mysql:8.0.40)"
  echo "RF_PIN_MINIO=$(pin pgsty/silo:RELEASE.2026-08-06T00-00-00Z)"
  echo "RF_PIN_VALKEY=$(pin valkey/valkey:8)"
  echo "RF_PIN_TEI=$(pin ghcr.io/huggingface/text-embeddings-inference:cpu-1.8)"
  echo "RF_PIN_PYTHON=$(docker image inspect python:3.12-slim --format '{{range .RepoDigests}}{{println .}}{{end}}' | sed -n 's/^python@//p' | head -1)"
  echo "RF_TEI_MODEL=Qwen/Qwen3-Embedding-0.6B"
  echo "RF_TEI_REVISION=97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
} > "$PINS"; cat "$PINS"
grep -c '^RF_PIN_[A-Z]*=sha256:[0-9a-f]\{64\}$' "$PINS"      # 8
while read -r name want; do got=$(sed -n "s/^$name=//p" "$PINS")
  [ "$got" = "$want" ] && echo "same      $name" || echo "DIFFERENT $name: $got, Docker Hub read $want"
done <<'EOF'
RF_PIN_RAGFLOW sha256:4ab74ec388e2d897419e01518a516e9386e5ff812587a1025e6f6a407b2ad067
RF_PIN_ES sha256:58a3a280935d830215802322e9a0373faaacdfd646477aa7e718939c2f29292a
RF_PIN_INFINITY sha256:53866c63220c5b1d42029ae646adc1d03f94692e0b3593db0097a86e2d49cba7
RF_PIN_MYSQL sha256:d58ac93387f644e4e040c636b8f50494e78e5afc27ca0a87348b2f577da2b7ff
RF_PIN_MINIO sha256:29a498b24669cae1fed11c1a2fb2b3d73c68829a0a9c0b14e71b386671d38fac
RF_PIN_VALKEY sha256:8f836008e0986c36adf50da714c7060cf689dbb335f61fe077939d90fa650809
RF_PIN_PYTHON sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
EOF
```

Check: 8 pins, and `same` on all seven lines. The expected digests are the ones the research read from Docker
Hub on 2026-11-08, through a page summariser, and the local python image's digest. A `DIFFERENT` line means a
moved tag or a misread: stop and look. TEI's digest had not been read before, so it is recorded here.

### P4. Pull by digest (prepare-time egress)

```bash
RF_DOC_ENGINE=elasticsearch RF_EMBEDDING_BATCH_SIZE=probe-pending \
  bash "$HEAVY" docker compose "${CF[@]}" --profile es --profile infinity pull
docker images --digests | grep -E 'ragflow|elasticsearch|infinity|mysql|silo|valkey|text-embeddings|python'
```

Check: each digest printed equals its pin. (`probe-pending` only satisfies interpolation here. The server is
never started before P8 writes the real batch size, and `rf_ingest.py` refuses anything but a number.)

### P5. The embedding model at its pinned revision

```bash
REV=97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3; M="$RUN/models/Qwen/Qwen3-Embedding-0.6B"; mkdir -p "$M/1_Pooling"
curl -fsS "https://huggingface.co/api/models/Qwen/Qwen3-Embedding-0.6B/revision/$REV" \
  | python -I -c "import json,sys; print(json.load(sys.stdin).get('sha'))"            # prints $REV
for f in config.json config_sentence_transformers.json generation_config.json merges.txt model.safetensors \
         modules.json tokenizer.json tokenizer_config.json vocab.json 1_Pooling/config.json; do
  bash "$HEAVY" curl -fsSL --proto '=https' --proto-redir '=https' --retry 3 -o "$M/$f" \
    "https://huggingface.co/Qwen/Qwen3-Embedding-0.6B/resolve/$REV/$f" || { echo "failed: $f"; break; }
done
( cd "$M" && printf '%s  %s\n' \
  0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd model.safetensors \
  def76fb086971c7867b829c23a26261e38d9d74e02139253b38aeb9df8b4b50a tokenizer.json | sha256sum -c - )
( cd "$M" && find . -type f | sort | xargs sha256sum ) > "$RUN/state/model-files.sha256"
```

Check: both lines `OK`, and `model.safetensors` is 1,191,586,416 bytes. The two sha256 values are the LFS ids
from the Hugging Face API, read by the research.

### P6. The canvas copy and the upload set

```bash
cp "D:/Iqraa Law/.hq/scratch/inbox-evidence-law-2026-11-07/اقرأ – فهرسة التشريعات القانونية.json" "$RUN/canvas/indexing-pipeline.json"
sha256sum "$RUN/canvas/indexing-pipeline.json"
python -I -c "import json,sys; m=json.load(open(sys.argv[1],encoding='utf-8')); print(m['canvas']['sha256'], m['file_shape'], len(m['files']))" "$RUN/in/upload-manifest.json"
ls "$RUN/in"/*.md | wc -l; sha256sum "$RUN/in/upload-manifest.json"
```

Check:
- Both canvas hashes are `3f0fcb62b79a0b292f05ccfc9ad198259acfb3b459a21c73c6ca4fc369bf588d`, and the manifest
  line ends `slug-title-served-v1 22`.
- There are 22 `.md` files. The manifest sha256 is the one `make_w2_corpus.py` recorded (its section above).
  If the upload set is missing, run that tool first.

### P7. Start TEI alone, wait for it, check its network, time it

```bash
export RF_DOC_ENGINE=elasticsearch
RF_EMBEDDING_BATCH_SIZE=probe-pending bash "$HEAVY" docker compose "${CF[@]}" --profile es up -d tei
RF_EMBEDDING_BATCH_SIZE=probe-pending docker compose "${CF[@]}" --profile es run --rm --no-deps --name ragbench-rf-tei-wait tei-probe
# the network's own gateway (the host side of the bridge), and a port another container publishes (read only)
GW=$(docker network inspect ragbench-rf-net --format '{{range .IPAM.Config}}{{.Gateway}} {{end}}' | awk '{print $1}')
PUB=$(docker ps --format '{{.Ports}}' | tr ',' '\n' | sed -n 's/^ *0\.0\.0\.0:\([0-9][0-9]*\)->.*/\1/p' | head -1)
echo "gateway: ${GW:-none listed by IPAM}; a port another container publishes: ${PUB:-none, 80 is used}" | tee "$RUN/state/gateway.txt"
GWB=(); [ -n "$GW" ] && GWB=(--block "$GW:443" --block "$GW:${PUB:-80}")
RF_EMBEDDING_BATCH_SIZE=probe-pending docker compose "${CF[@]}" --profile es run --rm --no-deps --name ragbench-rf-netcheck tei-probe \
  python3 -I -B /w2/net_check.py --reach ragbench-rf-tei:80 --block 1.1.1.1:443 --block huggingface.co:443 \
  --block host.docker.internal:443 "${GWB[@]}"
docker inspect ragbench-rf-tei --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}'
RF_EMBEDDING_BATCH_SIZE=probe-pending bash "$HEAVY" docker compose "${CF[@]}" --profile es run --rm --no-deps --name ragbench-rf-tei-time tei-probe \
  python3 -I -B /w2/tei_probe.py --url http://ragbench-rf-tei:80 time --in-dir /in | tee "$RUN/state/tei-probe.txt"
N=$(sed -n 's/^EMBEDDING_BATCH_SIZE=\([0-9][0-9]*\)$/\1/p' "$RUN/state/tei-probe.txt")
[ -n "$N" ] && echo "RF_EMBEDDING_BATCH_SIZE=$N" >> "$PINS" && echo "batch size $N"
```

Check:
- The wait prints `TEI ready: /data/Qwen/Qwen3-Embedding-0.6B, … one vector of 1024 dimensions` (1024 is
  inferred from the model card, not read).
- `net_check` ends with every line `ok`, the two gateway lines included. TEI is on `ragbench-rf-net` only.
  `$RUN/state/gateway.txt` (written here and again in E2) is the evidence the report cites for the gateway
  lines: the address tested, and whether the second port was one another container publishes or the
  fallback 80.
  - If IPAM lists no gateway, `gateway.txt` records that output and stands as the evidence instead; nothing
    more is claimed about a host-side address.
  - A `FAIL` on a gateway line means the host side of `ragbench-rf-net` answers: the Docker VM, and through it
    the ports other containers publish. Stop and report it. «No egress» would then hold only as «no route beyond
    the Docker VM», and whether to go on with that narrower claim is the owner's decision.
  - `host.docker.internal: no address` proves only that the name does not resolve here, not that the host's
    address is out of reach.
- `batch size N` is printed. The same N serves the Infinity stack: it is the same TEI, model and machine.

**P8. Only if the wait times out (the model too slow through the Windows share).** Copy the model into a
throwaway volume, check the copy, and use the override from then on:

```bash
docker compose "${CF[@]}" --profile es rm -sf tei
docker volume create ragbench-rf-tei-models
docker run --rm --name ragbench-rf-tei-copy --network none --mount type=volume,source=ragbench-rf-tei-models,target=/m \
  --mount "type=bind,source=$RUN/models,target=/src,readonly" "python:3.12-slim@$(sed -n 's/^RF_PIN_PYTHON=//p' "$PINS")" cp -a /src/. /m/
docker run --rm -i --name ragbench-rf-tei-verify --network none --mount type=volume,source=ragbench-rf-tei-models,target=/m,readonly \
  "python:3.12-slim@$(sed -n 's/^RF_PIN_PYTHON=//p' "$PINS")" sh -c 'cd /m/Qwen/Qwen3-Embedding-0.6B && sha256sum -c -' < "$RUN/state/model-files.sha256"
CF+=(-f "$T/compose.tei-volume.yaml")      # and add this line to P0 for every later shell
```

Then repeat P7 from `up -d tei`.

### E. One run (first Elasticsearch, then Infinity on a fresh stack)

Set the engine, then run E1 to E8:

```bash
ENG=elasticsearch PROF=es STORE=ragbench-rf-es01:9200          # the Infinity run: ENG=infinity PROF=infinity STORE=ragbench-rf-infinity:23817
export RF_DOC_ENGINE=$ENG; O="$RUN/out/$ENG"
grep -q '^RF_EMBEDDING_BATCH_SIZE=[0-9][0-9]*$' "$PINS" || echo "STOP: no batch size in the pins file"
```

**E1. Start the stack.**

```bash
bash "$HEAVY" docker compose "${CF[@]}" --profile "$PROF" up -d
docker compose "${CF[@]}" --profile "$PROF" ps -a --format '{{.Name}} {{.State}} {{.Health}}'
```

Check: repeat `ps` until `ragbench-rf-server` is `running healthy` (its start period is 300 s). `tei-probe` has
`exited`, with exit 0 (`docker inspect -f '{{.State.ExitCode}}' ragbench-rf-tei-probe`).

**E2. Isolation checks.**

```bash
docker network inspect ragbench-rf-net --format '{{.Internal}}'                     # true
docker ps --format '{{.Names}} {{.Ports}}' | grep '^ragbench-rf-' | grep -- '->'   # prints nothing
docker exec ragbench-rf-server printenv DOC_ENGINE TEI_MODEL API_PROXY_SCHEME REGISTER_ENABLED EMBEDDING_BATCH_SIZE
docker inspect ragbench-rf-server --format '{{.HostConfig.LogConfig.Type}} {{.HostConfig.LogConfig.Config}}'
GW=$(docker network inspect ragbench-rf-net --format '{{range .IPAM.Config}}{{.Gateway}} {{end}}' | awk '{print $1}')
PUB=$(docker ps --format '{{.Ports}}' | tr ',' '\n' | sed -n 's/^ *0\.0\.0\.0:\([0-9][0-9]*\)->.*/\1/p' | head -1)
echo "gateway: ${GW:-none listed by IPAM}; a port another container publishes: ${PUB:-none, 80 is used}" | tee -a "$RUN/state/gateway.txt"
GWB=(); [ -n "$GW" ] && GWB=(--block "$GW:443" --block "$GW:${PUB:-80}")
docker exec ragbench-rf-runner python3 -I -B /w2/net_check.py --reach 127.0.0.1:9380 --reach ragbench-rf-tei:80 \
  --reach "$STORE" --block 1.1.1.1:443 --block huggingface.co:443 --block pypi.org:443 --block host.docker.internal:443 \
  "${GWB[@]}"
docker logs ragbench-rf-server 2>&1 | grep -c 'Super user initialized'              # 1
docker logs ragbench-rf-server 2>&1 | grep -m1 'log levels:'                       # root DEBUG (log_utils.py:72-73)
```

Check: `printenv` gives the engine, `Qwen/Qwen3-Embedding-0.6B`, `python`, `0` and N. The log driver line is
`json-file map[max-file:20 max-size:100m]`. Every `net_check` line is `ok`, the gateway lines included (a
gateway `FAIL` means what P7 says: stop and report).

**E3. The API key, into the runner's tmpfs only.**

```bash
set -o pipefail
docker exec -i ragbench-rf-server /ragflow/.venv/bin/python -I -B /w2/make_key.py \
  | docker exec -i ragbench-rf-runner sh -c 'umask 077 && cat > /run/rf/key && test -s /run/rf/key' && echo "key stored in the runner's tmpfs"
docker exec ragbench-rf-runner sh -c 'wc -c < /run/rf/key'                       # about 52
docker exec ragbench-rf-runner python3 -I -B /w2/rf_ingest.py preflight --engine "$ENG"
```

Check: every preflight line is `ok`, and it reports 0 datasets. If the runner is recreated, the key is gone:
repeat E3.

**E4. Predict the chunks with RAGFlow's own code.**

```bash
docker exec ragbench-rf-server /ragflow/.venv/bin/python -B /w2/predict_chunks.py \
  --canvas /canvas/indexing-pipeline.json --in-dir /in > "$O/predicted-chunks.jsonl" 2> "$O/predict-summary.txt"
echo "exit $?"; tail -1 "$O/predict-summary.txt"; head -c 300 "$O/predicted-chunks.jsonl"; echo
grep -c ' repeated texts 0$' "$O/predict-summary.txt"                        # 22
grep -E ' repeated texts [1-9][0-9]*$' "$O/predict-summary.txt"              # prints nothing
```

Check:
- `exit 0`, the summary ends `TOTAL 22 files, <n> predicted chunks (RAGFlow v0.27.3…, method group)`, and the
  file starts with the `w2_predict` header.
- **The repeat gate.** 22 files with `repeated texts 0`, and no line with more. A repeat stops the run here,
  before the hours of E5: such a law can pass neither `dump` nor E6 (predict_chunks.py above says why). Report
  which file repeats which text; changing the tools to handle repeats is a new decision, not a runbook step.

**E5. Ingest (blocking; it can take hours on CPU).**

```bash
bash "$HEAVY" docker exec ragbench-rf-runner python3 -I -B /w2/rf_ingest.py all --engine "$ENG" \
  --canvas /canvas/indexing-pipeline.json --in-dir /in --upload-manifest /in/upload-manifest.json \
  --out "/out/$ENG" | tee "$RUN/logs/ingest-$ENG.txt"
# after an interruption: ... rf_ingest.py wait --engine "$ENG" --out "/out/$ENG", then ... dump ... the same way
```

Check: exit 0, and the last line is `wrote <n> chunks to chunks.jsonl and w2-manifest.json …`.

**E6. The gate: ALL MATCH before any query.**

```bash
python -I -B "$T/w2_check.py" --predicted "$O/predicted-chunks.jsonl" --dumped "$O/chunks.jsonl" \
  --manifest "$O/w2-manifest.json" --ingest-state "$O/ingest-state.json"
```

Check: `ALL MATCH`, exit 0, and the manifest now says `"all_match": true`. Anything else: stop. No query runs on
a dataset that does not match.

**E7. The two arms: v3 (FINAL REVIEW v3, run_w1's defaults) and rt (vector weight 0.4, Retrieval TEST).**

```bash
DS=$(python -I -c "import json,sys; print(json.load(open(sys.argv[1]))['dataset_id'])" "$O/w2-manifest.json")
docker exec ragbench-rf-runner sha256sum /w1/run_w1.py /pkg/w1-queries.jsonl
docker exec ragbench-rf-runner python3 -I -B /w1/run_w1.py --base-url http://127.0.0.1:9380 --api-key-file /run/rf/key \
  --dataset "$DS" --queries /pkg/w1-queries.jsonl --out "/out/$ENG/w2-results-v3.jsonl" --dry-run
for arm in v3 rt; do
  extra=(); [ "$arm" = rt ] && extra=(--vector-similarity-weight 0.4)
  T0=$(docker exec ragbench-rf-runner date -u +%Y-%m-%dT%H:%M:%SZ)
  bash "$HEAVY" docker exec ragbench-rf-runner python3 -I -B /w2/timed_run.py --log "/out/$ENG/run-$arm.log" -- \
    python3 -I -B /w1/run_w1.py --base-url http://127.0.0.1:9380 --api-key-file /run/rf/key --dataset "$DS" \
    --queries /pkg/w1-queries.jsonl --out "/out/$ENG/w2-results-$arm.jsonl" "${extra[@]}" || echo "STOP: arm $arm exited non-zero"
  docker logs --timestamps --since "$T0" ragbench-rf-server > "$RUN/logs/server-$ENG-$arm.log" 2>&1
  wc -c < "$RUN/logs/server-$ENG-$arm.log"                                       # far under 2 GB
  python -I -B "$T/fallback_items.py" --results "$O/w2-results-$arm.jsonl" --server-log "$RUN/logs/server-$ENG-$arm.log" \
    --run-log "$O/run-$arm.log" --out "$O/w2-fallback-$arm.json"
done
```

Check:
- The two sha256 values are `b6440e5b…6cb10` (run_w1.py) and `e0669ca0…737c` (`.hq/docs/specs/w1-for-walid/SHA256SUMS`).
- The dry run prints 160 requests.
- Each arm exits 0 and writes `w2-results-<arm>.jsonl` (160 rows, every field of every item).
- `fallback_items.py` exits 0 with `every call checked against the request times`. Exit 1 means the logs could
  not be matched: re-run that arm into a fresh `--out`, and do not use its fallback reading.
- The saved log covers the arm. Its size is far under the 2 GB cap, so nothing of the arm can have rotated away,
  and `fallback_items.py`'s exit 0 is the proof: it finds a logged retrieval call inside the span of every
  answered request, and rotation would have dropped the earliest of those first.

**E8. Tear the stack down before the next one** (keeps `ragbench-rf-tei-models` if P8 made it):

```bash
docker compose "${CF[@]}" --profile es --profile infinity down --volumes --remove-orphans --timeout 30
docker ps -a --format '{{.Names}}' | grep -E '^ragbench-rf-' | xargs -r docker rm -f
docker network ls --format '{{.Name}}' | grep -E '^ragbench-rf-' | xargs -r docker network rm
docker volume ls --format '{{.Name}}' | grep -E '^ragbench-rf-' | grep -vx ragbench-rf-tei-models | xargs -r docker volume rm
```

Then the Infinity run: set `ENG=infinity PROF=infinity STORE=ragbench-rf-infinity:23817`, start TEI again
(`up -d` in E1 starts it), and do E1 to E8. Every store is fresh, so the account, the key, the dataset and the
ingest are all redone. P7's batch size is reused.

### F. Final teardown, and the check that nothing that existed before is gone

```bash
docker compose "${CF[@]}" --profile es --profile infinity down --volumes --remove-orphans --timeout 30
docker ps -a --format '{{.Names}}' | grep -E '^ragbench-rf-' | xargs -r docker rm -f
docker network ls --format '{{.Name}}' | grep -E '^ragbench-rf-' | xargs -r docker network rm
docker volume ls --format '{{.Name}}' | grep -E '^ragbench-rf-' | xargs -r docker volume rm
docker ps -a --format '{{.ID}} {{.Names}}' | sort > "$RUN/state/after-containers.txt"
docker volume ls --format '{{.Name}}' | sort > "$RUN/state/after-volumes.txt"
docker network ls --format '{{.ID}} {{.Name}}' | sort > "$RUN/state/after-networks.txt"
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | sort > "$RUN/state/after-images.txt"
for k in containers volumes networks images; do
  echo "== $k that existed before and are gone:"; comm -23 "$RUN/state/before-$k.txt" "$RUN/state/after-$k.txt"
  echo "== $k of ours left:"; grep -E '(^| )ragbench-rf-' "$RUN/state/after-$k.txt"
done
grep -x ragbench-cargo "$RUN/state/after-volumes.txt"
```

Check:
- Every «gone» list is empty, and so is every «of ours left» list. `ragbench-cargo` is still listed.
- Other sessions may add things meanwhile, so the test is that nothing pre-existing went missing, not that the
  lists are equal. If a «gone» line appears, it was not ours (every command above matches `^ragbench-rf-`), and
  `docker events --since <start> --filter event=destroy` shows who removed it.
- Never run `docker system prune`, `docker volume prune`, `docker network prune`, or any cleanup matching
  `ragbench` without `-rf-`.

Then, as the owner decides:
- delete the secrets file (`cat "$RUN/state/secrets-path.txt"` names it), after `down`;
- keep or delete `$RUN/models`;
- remove the images this run pulled. Pick them by the eight pinned digests, never by «new since P1»: other
  sessions on this daemon may pull images during the hours of the run.

```bash
sed -n 's/^RF_PIN_[A-Z]*=//p' "$PINS" | sort -u > "$RUN/state/pinned-digests.txt"            # the 8 pins
docker images --digests --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Repository}}@{{.Digest}}' \
  | awk 'FILENAME == ARGV[1] { pin[$1] = 1; next }
         FILENAME == ARGV[2] { before[$1 " " $2] = 1; next }
         { n = split($3, ref, "@") } (ref[n] in pin) && !(($1 " " $2) in before) { print $3 }' \
      "$RUN/state/pinned-digests.txt" "$RUN/state/before-images.txt" - \
  | sort -u | tee "$RUN/state/remove-images.txt"
# after reading the list, and only if the owner agrees:
# xargs -r docker rmi < "$RUN/state/remove-images.txt"
```

  Check: every line is `<repository>@sha256:…` with one of our pins, at most seven (python's image was here
  before P1, so its `repository:tag ID` row is in `before-images.txt` and is left out). An image another session
  pulled at the same digest meanwhile is the same image, and a digest cannot tell the two apart. `docker rmi`
  is run without `-f`, so it refuses an image any container still uses; that is also why this stays the owner's
  decision.
