# ragflow-w2

The W2 tools: a throwaway, pinned RAGFlow v0.27.3 on this machine, holding our served articles, indexed by Walid's
indexing-pipeline canvas, and queried with `../ragflow-w1/run_w1.py`. The rules are in
`.hq/docs/specs/spec-rag-system.md`, block «Owner decision 2026-11-08: W2 first, run here, with a pre-registered
rule», with its later bullets (the interval details; raising RAGFlow's wait on the embedder, «## TEI wait patch»).
Each tool has its own section below. Everything that runs on the host or in the runner uses the Python standard
library only.

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
  named volume. Teardown is `down` on the compose project `ragbench-rf` (compose.yaml:38), then sweeps that
  match the prefix `^ragbench-rf-` only. The existing volume `ragbench-cargo` has no compose labels and does
  not match.
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
  - Render `docker compose config` with the real secrets file only into a pipe, never to a file: compose copies
    `env_file` values into the rendered `environment`. (The prepare stage once wrote it to a file and deleted it:
    `.hq/scratch/w2-run/state/prepare-2.json`, `notes[1]`.)
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
- **Embedding batch size, concurrency and the TEI wait** (owner, 2026-11-08 later; «## TEI wait patch» below).
  - `EMBEDDING_BATCH_SIZE` (common/settings.py:517) is required from the first boot. It is 1, the owner's value,
    written into the pins file by P7. (The probe, `tei_probe.py time`, found no batch size that fits RAGFlow's
    30 s wait; its timings are the record the TEI-wait section cites.)
  - `MAX_CONCURRENT_TASKS` is `${RF_MAX_CONCURRENT_TASKS:-1}`: one document at a time
    (rag/svr/task_executor_limiter.py:20, default 5). The runner records the same variable in the manifest.
  - `MAX_CONCURRENT_CHUNK_BUILDERS=1` keeps one embedding batch at a time in flight, as the probe timed it
    (rag/svr/task_executor_limiter.py:21-26).
  - The server imports a copy of `rag/llm/embedding_model.py` whose two TEI waits are 900 s, mounted read-only
    over the module from `RF_TEI_WAIT_DIR` (`:?`-guarded). `ENABLE_TIMEOUT_ASSERTION` is set nowhere.
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
    (the canvas copy, read-only), `/patch` (the TEI-wait patch folder, read-only, for `rf_ingest.py`) and `/out`
    (run outputs, the only writable mount).
  - The server gets `/w2`, `/in` and `/canvas` read-only, for `predict_chunks.py` and `make_key.py`; the
    patched `embedding_model.py` read-only over `/ragflow/rag/llm/embedding_model.py`, and `/patch` read-only,
    for `check_tei_wait.py`. It writes nothing to the host.
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
| MAJOR: embedding timeouts; batch size left as a fallback | closed, with a limit | the batch size is required at first boot (1, the owner's value, after the timed probe found none that fits). Only failed documents are re-parsed, at most twice, through `/documents/parse`. The 30-second wait on the two TEI calls is raised to 900 s by the owner's decision, in a mounted copy checked in the server (`## TEI wait patch`); that a call is never retried remains RAGFlow's |
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
  - checks the TEI-wait record (`--tei-wait-patch`, required on `create`, `dump` and `all`; «## TEI wait patch»)
    and that the patched file beside it has the recorded sha256, and keeps the record in the state file;
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
- **`wait`** polls the document list (every 30 s by default). It prints one progress line per poll, ending
  `settled <n>`, and one line each time a finished or failed document's run or chunk count changes; for a
  failure, that line ends with the last line of its progress message, redacted and cut at 200 characters. When
  every document has stopped and some failed, the failed ones alone are parsed again, at most twice.
  - **It blocks until all 22 have settled** (`unsettled()`): the run is `DONE`, `chunk_count` is a whole
    number above 0, and the previous poll read the same run and count. `DONE` alone is not enough. With a
    pipeline canvas, v0.27.3 sets the task to 1.0 when the Tokenizer finishes (rag/flow/pipeline.py:107-125),
    `_sync_progress` then marks the document `DONE` (api/db/services/document_service.py:1162-1180), and
    `chunk_count` is raised only after the insert into the store
    (rag/svr/task_executor_refactor/dataflow_service.py:161-181). The Elasticsearch run saw
    «maritime-commerce.md: DONE, 0 chunks», then 386 chunks 30 s later. The earlier rule (every document
    `DONE`) could record 0 for the last document (a pipeline document has one task, whose count is raised once,
    by all its chunks: dataflow_service.py:179), and `dump` would then refuse, or write a manifest one law
    short. A document settles one poll after the first read of its final count: two polls after `DONE` in the
    0, then 386 case.
  - It fails after `--max-wait` (12 h by default; run it again to keep waiting), naming each document that is
    `DONE` but not settled, and why: `<count> chunks` (0, none, negative or not a whole number),
    `count still changing: 100 -> 386`, or `DONE since the last poll only`.
  - A document that stays `DONE` with 0 chunks can never settle, so it holds `wait` for the whole `--max-wait`.
    v0.27.3 leaves such a document at 0 when the pipeline's output is empty (dataflow_service.py:127-131 and
    :140-142 return before the count) or when the count update fails (:178-181 log it, and :183 still sets the
    task to 1.0). If the progress lines read `done 22 … settled 21` for many polls, look at that document in the
    server log and stop `wait` by hand.
  - Settling needs a second poll and the timeout is checked after every poll, so `--max-wait 0`, or one shorter
    than the first listing takes, fails even on a finished dataset (the earlier rule returned at the first poll).
  - `all` runs the same `wait()` as the `wait` step (`main()`), so the rule holds on both paths.
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
| `max_concurrent_tasks` | `W2_MAX_CONCURRENT_TASKS`, from the same `RF_MAX_CONCURRENT_TASKS` as the server's `MAX_CONCURRENT_TASKS` |
| `tei_wait_patch` | `{file, image_sha256, patched_sha256, changed_lines, wait_s, diff}`: the first five from `--tei-wait-patch` (patch_tei_wait.py's patch.json, without its `anchors`), and `diff` the text of `embedding_model.diff` beside it (the spec, «The change»: «Its diff and both sha256 go in the W2 manifest»). `wait_s` must be a whole number above 30, both sha256 64 lower-case hex and different, two changed lines in ascending order, the file `rag/llm/embedding_model.py`, and the patched file beside the record must have `patched_sha256`. The diff must name `a/` and `b/rag/llm/embedding_model.py` and remove and add exactly the changed lines, each `timeout=30)` becoming `timeout=<wait_s>)`, each added line equal to the patched file's line of that number. `dump` refuses a patch other than the one `create` kept |

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
    30-second client timeout, which has no retry. On this machine it found none (one text alone takes 38 s),
    and the owner set the batch size to 1 and the wait to 900 s instead («## TEI wait patch»).
- **`patch_tei_wait.py`** and **`check_tei_wait.py`** make and check the TEI-wait patch: «## TEI wait patch».
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

- **`tests/test_rf_ingest.py`** (76 tests) runs rf_ingest.py against `tests/fake_ragflow_w2.py`, a local fake of
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
  - **Settling** (the fake's `chunk_count_steps`: a document `DONE` before its count is set). A document `DONE`
    with 0 chunks for one poll, then 386, is recorded as 386, through `all` and through the `wait` step; 0 read
    on two polls is not settled; a count rising 100, 386, 386 is recorded as 386; the progress line counts the
    settled ones (0, 21, 22). A document that stays `DONE` with 0 chunks, beside one whose count keeps rising,
    fails after `--max-wait` naming both and why, with no chunk listed. As before: all `DONE` and stable from
    the start, and a failure parsed again alone; a document still settling is not parsed again with a failed
    one. A `chunk_count` that is not a number (`"n/a"`) for one poll is waited out, not a crash.
    `unsettled()` itself: only `DONE` with a whole count above 0 (386, and 1), read the same on the previous
    poll, settles (not after `RUNNING` or `FAIL` with the same count, not a count falling 400 to 386, not 386 or
    1 after `386.0` or `True`, not `True`, `386.0`, `"386"`, 0, -1 or none). A document that leaves `DONE`
    (another client parses it again) and comes back with its old count settles only on the poll after: a
    scripted listing (`PreviousPoll`), since the fake has no such read.
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
  - **The TEI-wait record.** The fixture is patch_tei_wait.py's own output (`build`) for a small source whose
    anchors sit on lines 1247 and 1253, so the producer and this reader are tested together. The manifest's
    `tei_wait_patch` (the five fields and the diff text, in the contract's key order) and
    `max_concurrent_tasks`. Refused before sending: a `wait_s` of `"900"`, 30, 29, `true`, 900.0 or none; a
    sha256 in capitals, of 63 characters, not hex or a number; a patched file beside the record that differs
    from it; another file, a record whose two sha256 are equal, one changed line, changed lines out of order
    (`[1253, 1247]`); a diff that is missing, names another file, is the diff of another wait, has its hunk moved
    by a line, adds one more line, has a blank row inside the hunk, or has CRLF line ends; a concurrency that is
    empty, 0 or not a number; `create` and `all` without `--tei-wait-patch`. And a `dump` with another patch
    (made with a wait of 600) than `create` kept writes no manifest.
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
- **`tests/test_tei_wait.py`** (32 tests) uses an invented `embedding_model.py` shaped like v0.27.3's, with a
  `timeout=30` line in a class before and after `HuggingFaceEmbed`, and the v0.27.3 source tree copy when it
  is there.
  - **`patch_tei_wait.py`.** Only the two anchor lines change, and only their number (the decoys stay); the
    record, the diff, another `--wait`, `--replace`; `changed_lines` ascending when `encode_queries` comes before
    `encode`; on the real file, lines 1247 and 1253 only, six `timeout=30` lines left, and the record's two
    sha256 and wait equal to check_tei_wait.py's `APPROVED`. Refused: an anchor not found, found twice, outside the class, under the other
    method; CR line ends; not UTF-8; another sha256 than `--expect-sha256`; a wait of 30 or 5; a method that
    would still hold 30; a non-empty `--out`, and foreign entries even with `--replace`; the source inside
    `--out`. The second pass refuses another changed line, a change beyond the number, another number and a
    line fewer.
  - **`check_tei_wait.py`.** The code-constant logic on small classes: both at 900 pass; 30 is named for each
    method; one method left at 30 is caught alone; a float 30 counts; a missing method is named. Then its
    `main` in a child Python, on a fake `/ragflow` and a fake `/proc` (each run passes the fixture's own sha256
    as the expected ones): the patched module passes; a stale unchecked-hash `.pyc` of the shipped file, which
    the import system uses without reading the source, is caught; an import that resolves to another file
    holding the patched bytes (the fixture's `rag/llm/__init__.py` sets `__path__` elsewhere), so that only
    the module-origin check can fail, is caught with exactly that one `BAD` line; the shipped file in place of
    the patched one is caught; `ENABLE_TIMEOUT_ASSERTION` in the container or in a task executor's environment
    is caught; a task executor at the default concurrency, a batch size of 16, and no task executor are caught;
    bad input: a `wait_s` of `"900"`, 30 or `true`, a record of another file, and, with the defaults, a record
    that is not the approved patch (the fixture's sha256), or one whose wait is 600.

On 2026-11-08 these 132 tests, and the whole folder's suite with the generator's tests (176), passed on the
host (Python 3.11.9, the Git Bash command above). On 2026-11-09, after the settle fix (`wait` above), these
144 and the folder's 188 passed the same way (`.hq/scratch/w2-stage4/waitfix/suites-2.txt`). After the stage-4
review's fixes, these 146 and the folder's 190 passed (`.hq/scratch/w2-stage4/fix1/suites.txt`).

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
- **The TEI-wait stage, 2026-11-08.** The stage-3 review's list (`.hq/scratch/w2-review-stage3/mutate_review.py`,
  17 entries with two controls, across this folder and score_w1.py) left 5 survivors
  (`mutate-review.txt`): the module-origin check and the file-name check of check_tei_wait.py, rf_ingest.py's
  changed-lines order, and the scorer's strata-terms warning and its printing. After the fixes, the same list
  kills all 5 (`.hq/scratch/w2-fix-stage3/mutate-review-after.txt`); one entry no longer applies, since the
  line it mutated was rewritten to add the diff. A second list for the checks the fixes added
  (`.hq/scratch/w2-fix-stage3/mutate_new.py`, 12 mutations) kills all 12 (`mutate-new.txt`, with the one
  survivor of its first run, the diff's line numbers, killed after its check was made independent:
  `mutate-new-2.txt`). A mistyped `APPROVED` is caught only by the test on the real v0.27.3 file, which these
  copies skip; that test ran in the real suite.
- **The settle fix, 2026-11-09.** A list chosen by the builder, not a reviewer, so it shows that each part of
  the rule has a test, not how much the suite covers: `.hq/scratch/w2-stage4/waitfix/mutate.py`, 13 mutations
  of rf_ingest.py's settle rule, one copy of the folder each, run against all of `tests/test_rf_ingest.py`.
  All 13 are killed (`mutate.txt`): the `> 0` check dropped or made `>= 0`; `True` taken as a whole number; the
  stability check dropped, or reduced to the count alone, or to the run alone; `previous` updated before it is
  compared; the old rule (every document `DONE`); the re-parse without its `failed` guard, or extended to the
  documents still settling; the progress line counting `DONE`; the timeout message without its list; a reason
  swapped. Comparing the count without the run is caught only by the `unsettled()` tests: the fake has no
  `RUNNING` read that already holds the final count. The tests' run before the fix: `red.txt` (6 failures,
  14 errors, the `as before` tests passing); after it: `green.txt`.
- **The stage-4 review, 2026-11-09.** The reviewer's list (`.hq/scratch/w2-stage4/review1-code/mutate_review.py`,
  14 mutations, two of them controls) killed 5. Three survivors touched the settle rule: a falling count taken
  as stable, a count of 1 not settled, and `previous` kept for `DONE` documents only. New tests kill them. The
  same list with three mutations of this stage's changes added (`.hq/scratch/w2-stage4/fix1/mutate_fix1.py`)
  kills 11 of 17 (`mutate.txt`). The 6 survivors: the re-parse waiting until the others settle (acceptable
  either way); a reason's exact text; and four checks older than the fix, with no test yet: the timeout at
  `>=`, `sleep(0)`, the `seen` reset after a re-parse, and `dump` taking any count that is not none. The tests'
  run before this stage's code changes: `fix1/red.txt` (2 failures, 1 error); after them: `fix1/green.txt`.

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

## TEI wait patch

The spec's block «Owner decision 2026-11-08 (later): raise RAGFlow's wait on the embedder; run both engines» lets
the server run with one changed file. This section says why, what changes, what cannot, and how the run checks
it. RAGFlow claims cite the v0.27.3 source in `.hq/scratch/ragflow-src-v0.27.3/x/`.

### Why

Measured on this machine in the prepare step (`.hq/scratch/w2-run/state/probe.json`; in `.hq/scratch/w2-run/logs/`,
`prepare-p7-tei-clean.txt`, `main-trial-cpu20.txt` and `main-trial-mkl22.txt`), one call at a time:

- The pinned TEI (`cpu-1.8`, candle on CPU; its ONNX backend refused, since the revision has no `onnx/model.onnx`)
  embeds the longest article block, in customs (1,868 Qwen tokens), in 38.05 to 38.89 s with its 12-CPU cap.
  Capped at 20 CPUs it took 35.48 and 36.24 s, at 22 CPUs 36.38 and 36.55 s: its maths library uses the Docker
  VM's 12 cores whatever the cap (spec).
- That is about 20.5 ms per Qwen token, close to linear, so batching gains nothing: 2 texts took 73.86 and
  79.43 s, 4 texts 140.71 s.
- So a text above about 1,460 tokens needs more than 30 s. Of the 6,592 article blocks, 5 are above it:
  companies 1, customs 1, income-tax 3.
- RAGFlow v0.27.3 gives each TEI call 30 s and does not retry: `requests.post(..., timeout=30)` in
  `HuggingFaceEmbed.encode` (rag/llm/embedding_model.py:1247) and `encode_queries` (:1253). The built-in TEI
  embedder hands every call to that class (BuiltinEmbed, embedding_model.py:240, :251, :258). So those three
  laws could never be parsed, a re-parse would fail the same way, and `w2_check.py` could never print ALL MATCH.

### What changes

- **One file, two numbers.** `patch_tei_wait.py` changes `timeout=30)` to `timeout=900)` at the end of those two
  lines, and nothing else.
  - It finds them by their exact full text as they stand in v0.27.3, and refuses when either is not found
    exactly once, sits outside `class HuggingFaceEmbed` or under the other method, or when the file has a CR
    byte or is not UTF-8.
  - A second, independent pass compares both texts line by line: the result must differ only on those two
    lines, and only in that number. Then it compiles the result, and the two methods' own constants must hold
    900 and no 30. It writes `embedding_model.py`, `embedding_model.diff` and `patch.json` (`file`,
    `image_sha256`, `patched_sha256`, `changed_lines`, `wait_s`, `anchors`); `--out` follows
    `make_w2_corpus.py`'s rule (not empty only with `--replace`, never a foreign entry).
  - The other six `timeout=30` lines in the file (614, 900, 986, 1140, 1461, 1481) belong to other providers and
    stay as they are.
- **The source is the image's own file.** P9 copies `/ragflow/rag/llm/embedding_model.py` out of the pinned
  image. Read in the image on 2026-11-08, its sha256 is
  `c2e46e1cb5d128122a48b8283d135b81321441655dbd9c22c9ecd8035a6c0536`, the same as the source tree copy's; P9 checks
  it and passes it as `--expect-sha256`. The dry run on the source tree copy changed lines 1247 and 1253 only
  (64,482 bytes in, 64,484 out) and wrote patched sha256
  `90f3a20d0bfab00175670c90c93e410592029bbf7b75b7aadfe944f71c74acab` (`.hq/scratch/w2-run/state/tei-wait-dryrun/`).
- **Mounted, not rebuilt.** `compose.yaml` mounts the patched file read-only over
  `/ragflow/rag/llm/embedding_model.py`, from `RF_TEI_WAIT_DIR`, which has a `:?` guard. Without it,
  `docker compose config` exits 1 naming it, for the server and the runner, with either profile; with it, both
  profiles render (`.hq/scratch/w2-run/logs/build-tei-wait-compose.txt`).
  - That path is the module the server imports. The image's working directory and `PYTHONPATH` are `/ragflow`
    (Dockerfile:275, :282; `docker image inspect` of the pin: `WorkingDir=/ragflow`, `PYTHONPATH=/ragflow/`), its
    code is `COPY rag rag` (Dockerfile:303), and `rag/llm/__init__.py` imports `rag.llm.embedding_model` when
    the server starts (:168-170, `importlib.import_module` for each entry of `MODULE_MAPPING`).
  - The same folder is mounted read-only at `/patch` in the server, for the check, and in the runner, for the
    manifest.
- **No byte code can stand in for the file.** Checked in the pinned image on 2026-11-08 with a read-only,
  network-less, throwaway container (`.hq/scratch/w2-run/logs/build-tei-wait-dryrun.txt`):
  - no `__pycache__` folder and no `.pyc` under `/ragflow` outside `.venv`, and no `embedding_model*.pyc`
    anywhere on the root file system;
  - `PYTHONDONTWRITEBYTECODE=1` in the image's environment, so the server writes none;
  - Python 3.13.11, `sys.pycache_prefix` unset, hash-based `.pyc` checks at their default.
  With no `.pyc` to read, the import system compiles the mounted source. A `.pyc` that appeared later would be
  caught by the check below.
- **Two operational settings, not retrieval settings.**
  - `MAX_CONCURRENT_TASKS=1` (rag/svr/task_executor_limiter.py:20, default 5): one document at a time, so TEI never
    merges two long requests into one slow batch. It comes from `RF_MAX_CONCURRENT_TASKS` (default 1), which
    the runner reads too.
  - `EMBEDDING_BATCH_SIZE=1` (common/settings.py:517), so no call pads short texts to a long one's length.
    `RF_EMBEDDING_BATCH_SIZE` stays required, and P7 writes 1.
  - `MAX_CONCURRENT_CHUNK_BUILDERS=1` stays: one embedding call in flight (task_executor_limiter.py:21, :26).
- **`ENABLE_TIMEOUT_ASSERTION` stays unset.** Every `@timeout` wrapper on the ingest path is
  `common.connection_utils.timeout`, which enforces its limit only when that variable is set
  (common/connection_utils.py:30-100: the gate at :52 for functions, at :70 for coroutines).
  - Which path runs. The task executor reads `TE_RUN_MODE`, default `"0"` (rag/svr/task_executor.py:1806), and
    `"0"` runs `TaskManager.run_refactored_task` (:1820); only another value runs the legacy `do_handle_task`
    (:1812, :1824). Nothing here sets `TE_RUN_MODE`: not compose.yaml, and not the image, whose environment is
    `PATH`, `PYTHONDONTWRITEBYTECODE`, `VIRTUAL_ENV` and `PYTHONPATH` (`build-tei-wait-dryrun.txt`, «image
    config»). So the refactored path runs.
  - Its wrappers: rag/svr/task_executor_refactor/task_handler.py:199 (3 h, on `handle`), chunk_service.py:143
    (80 min, `build_chunks`) and :246 (60 s, the MinIO upload), dataflow_service.py:245 (60 s, `_embed_chunks`),
    each importing that `timeout` (task_handler.py:52, chunk_service.py:41, dataflow_service.py:42). The
    pipeline's own: rag/flow/base.py:58 (`COMPONENT_EXEC_TIMEOUT`, 10 min, on `_invoke`) and
    rag/flow/tokenizer/tokenizer.py:99 (60 s, `batch_encode`), importing it at base.py:23 and tokenizer.py:26.
    The legacy path's wrappers (task_executor.py:328, :434, :772, :886, :1097, :1448) are the same `timeout`
    (:69).
  - The one wait on the path that the variable does not gate: rag/flow/base.py:46,
    `await asyncio.wait_for(self._invoke(**kwargs), timeout=self._param.timeout)`, run for every component of
    the canvas (File, Parser, TitleChunker and Tokenizer are all `ProcessBase`: file.py:31, parser.py:332,
    title_chunker.py:22, tokenizer.py:52). Its default is 100,000,000 s (base.py:29, `ProcessParamBase`), and the canvas copy (sha256
    `3f0fcb62…588d`) sets no `timeout` anywhere (`grep -c timeout` on it prints 0), so it never fires here.
  - The variable is set nowhere: not in compose.yaml (a comment names it), not in the image's environment (above),
    not by docker/entrypoint.sh, and not in the secrets file, whose 12 names `prepare.json` records (p2_secrets;
    the file was not opened). `check_tei_wait.py` checks it in the container and in every running task executor
    and API server.
- **What it decides.** Nothing: no chunk, vector or score. TEI computes the same vector whether RAGFlow waits 30
  or 900 s; only whether RAGFlow is still waiting for it changes. Both engines run the same patch.

### What cannot change

- A call that needs more than 900 s still fails, and is still not retried. The longest measured takes about 39 s.
- The file name is embedded once per document, outside the limiter (tokenizer.py:95), before the chunk batches.
  With one task at a time it does not overlap another document's calls.
- The patch cannot be applied to another RAGFlow version: the anchors, and P9's `--expect-sha256`, are v0.27.3's.

### How it is checked

- **`rf_ingest.py --tei-wait-patch /patch/patch.json`**, required on `create`, `dump` and `all`, checks the
  record (a whole `wait_s` above 30, two 64-hex sha256 that differ, two changed lines in ascending order, the
  file name), that the patched file beside it has `patched_sha256`, and that `embedding_model.diff` beside it is
  the diff of that change: it names `a/` and `b/rag/llm/embedding_model.py`, and removes and adds exactly the
  changed lines, each `timeout=30)` becoming `timeout=<wait_s>)`, each added line equal to the patched file's
  line. It writes `tei_wait_patch` (the five fields and `diff`, the diff's text: the spec puts «its diff and both
  sha256» in the manifest), `embedding_batch_size` and `max_concurrent_tasks` into the W2 manifest. `dump`
  refuses a patch other than the one `create` kept in the state file.
- **`check_tei_wait.py`** runs in the server's own Python (E2, and again after E5):
  `docker exec ragbench-rf-server /ragflow/.venv/bin/python -B /w2/check_tei_wait.py --patch /patch/patch.json
  --max-concurrent-tasks 1 --embedding-batch-size 1`. It first checks that patch.json is the approved patch:
  `image_sha256` `c2e46e1c…0536` (the image's file), `patched_sha256` `90f3a20d…acab` (P9's output from those
  bytes, the dry run's) and `wait_s` 900, its `APPROVED`, which `--expect-image-sha256`, `--expect-patched-sha256`
  and `--expect-wait` override only for tests. Any other record exits 2 before anything is imported, so a patch
  made from an edited file (P9 without `--expect-sha256`) cannot pass E2. Then it imports
  `rag.llm.embedding_model` and checks:
  - the module file is `/ragflow/rag/llm/embedding_model.py`, read from source, with no `.pyc` where the import
    system would look for one;
  - its sha256 is `patched_sha256`;
  - the loaded `HuggingFaceEmbed.encode` and `encode_queries` are the code compiled from that file now, and their
    own constants hold 900 and no 30;
  - the container's environment, and that of every running task executor and API server
    (`/proc/<pid>/environ`), have no `ENABLE_TIMEOUT_ASSERTION` and the given `MAX_CONCURRENT_TASKS` and
    `EMBEDDING_BATCH_SIZE`; and a task executor is running.
  It ends `TEI WAIT LOADED: …` (exit 0) or `TEI WAIT NOT SHOWN: …` (exit 1); bad input exits 2.
- **The dry run**, 2026-11-08, in the pinned image with the dry-run file mounted (`build-tei-wait-dryrun.txt`):
  every line `ok`, `encode`'s constants `[900]`, `encode_queries`' `[900, 0]`. The one `BAD` line was «no task
  executor is running», as expected in a one-shot container. The control, without the mount, printed the
  image's sha256 and the constants `[30]` and `[30, 0]`, and failed. That run predates the approved-patch check;
  the dry-run record is the approved pair (`image_sha256` `c2e46e1c…`, `patched_sha256` `90f3a20d…`, 900), and
  `tests/test_tei_wait.py` checks that patching the source tree copy gives exactly `APPROVED`.
- **`score_w1.py --own-run`** requires the three fields (`tei_wait_patch` with its six keys, the diff's header,
  and only the changed lines changed from 30 to the wait) and prints them in its «W2 manifest» table, the diff in
  the JSON report only. A patch other than the approved one gets a warning, not a deciding gap: the patch is
  operational, and E2 has already refused it.

What the check cannot prove: it imports the module afresh, in a new process; it cannot read the code inside the
server processes already running. The bridge is the mount: read-only, made when the container was created,
before any process in it started, and holding the bytes whose sha256 the check reads. Running it again after
the ingest shows those bytes did not change during it.

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
RF_DOC_ENGINE=elasticsearch RF_EMBEDDING_BATCH_SIZE=probe-pending RF_TEI_WAIT_DIR=patch-pending \
  bash "$HEAVY" docker compose "${CF[@]}" --profile es --profile infinity pull
docker images --digests | grep -E 'ragflow|elasticsearch|infinity|mysql|silo|valkey|text-embeddings|python'
```

Check: each digest printed equals its pin. (`probe-pending` and `patch-pending` only satisfy interpolation
here. The server is never started before P7 writes the batch size and P9 the patch folder into the pins file;
`rf_ingest.py` refuses a batch size that is not a number, and a bind source that does not exist stops `up`.)

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
export RF_TEI_WAIT_DIR=patch-pending   # interpolation only, until P9; `unset RF_TEI_WAIT_DIR` there
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
# The batch size is the owner's (2026-11-08 later), not the probe's: 1. The probe's timings stay as the record.
grep -q '^RF_EMBEDDING_BATCH_SIZE=' "$PINS" || echo "RF_EMBEDDING_BATCH_SIZE=1" >> "$PINS"; grep '^RF_EMBEDDING_BATCH_SIZE=' "$PINS"
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
- The pins file holds `RF_EMBEDDING_BATCH_SIZE=1`, the owner's value. On this machine `tei_probe.py time` exits 1
  («no batch size stays under 15.0 s»): one long text alone takes 38 s (`state/probe.json`), which is why P9
  exists. The same 1 serves the Infinity stack.

**P8. Only if the wait times out (the model too slow through the Windows share).** Copy the model into a
throwaway volume, check the copy, and use the override from then on:

```bash
RF_EMBEDDING_BATCH_SIZE=probe-pending docker compose "${CF[@]}" --profile es rm -sf tei   # RF_TEI_WAIT_DIR as P7 set it
docker volume create ragbench-rf-tei-models
docker run --rm --name ragbench-rf-tei-copy --network none --mount type=volume,source=ragbench-rf-tei-models,target=/m \
  --mount "type=bind,source=$RUN/models,target=/src,readonly" "python:3.12-slim@$(sed -n 's/^RF_PIN_PYTHON=//p' "$PINS")" cp -a /src/. /m/
docker run --rm -i --name ragbench-rf-tei-verify --network none --mount type=volume,source=ragbench-rf-tei-models,target=/m,readonly \
  "python:3.12-slim@$(sed -n 's/^RF_PIN_PYTHON=//p' "$PINS")" sh -c 'cd /m/Qwen/Qwen3-Embedding-0.6B && sha256sum -c -' < "$RUN/state/model-files.sha256"
CF+=(-f "$T/compose.tei-volume.yaml")      # and add this line to P0 for every later shell
```

Then repeat P7 from `up -d tei`.

### P9. The TEI-wait patch (owner, 2026-11-08 later; «## TEI wait patch»)

```bash
unset RF_TEI_WAIT_DIR                      # P7's placeholder; from here on the pins file names the real folder
SRC="$RUN/patch-src"; mkdir -p "$SRC"
[ -e "$SRC/embedding_model.py" ] && echo "STOP: $SRC/embedding_model.py exists; look at it, or remove it, first"
docker create --name ragbench-rf-patch-src "infiniflow/ragflow@$(sed -n 's/^RF_PIN_RAGFLOW=//p' "$PINS")" >/dev/null
docker cp ragbench-rf-patch-src:/ragflow/rag/llm/embedding_model.py "$SRC/embedding_model.py"
docker rm ragbench-rf-patch-src
printf '%s  %s\n' c2e46e1cb5d128122a48b8283d135b81321441655dbd9c22c9ecd8035a6c0536 "$SRC/embedding_model.py" | sha256sum -c -
python -I -B "$T/patch_tei_wait.py" --source "$SRC/embedding_model.py" --out "$RUN/patch" \
  --expect-sha256 c2e46e1cb5d128122a48b8283d135b81321441655dbd9c22c9ecd8035a6c0536
cat "$RUN/patch/embedding_model.diff"
grep -q '^RF_TEI_WAIT_DIR=' "$PINS" || echo "RF_TEI_WAIT_DIR=$RUN/patch" >> "$PINS"; grep '^RF_TEI_WAIT_DIR=' "$PINS"
```

Check:
- `docker create` starts nothing (it only makes a container to copy from), and `docker rm` removes it.
- `sha256sum` prints `OK`: the image's file is the one read in the image on 2026-11-08.
- The tool prints lines 1247 and 1253, each `timeout=30 -> timeout=900`, and the patched sha256
  `90f3a20d0bfab00175670c90c93e410592029bbf7b75b7aadfe944f71c74acab`, the dry run's on the same bytes. The diff
  shows those two lines and no other.
- The pins file names `$RUN/patch` (a path with a space needs no quotes there; checked with `docker compose
  config`). From here on the server cannot start without it.
- That render holds the real secrets: send it only into a pipe, never to a file, because compose copies
  `env_file` values into the rendered `environment` («## The sealed stack», «Secrets»).

### E. One run (first Elasticsearch, then Infinity on a fresh stack)

Set the engine, then run E1 to E8:

```bash
ENG=elasticsearch PROF=es STORE=ragbench-rf-es01:9200          # the Infinity run: ENG=infinity PROF=infinity STORE=ragbench-rf-infinity:23817
export RF_DOC_ENGINE=$ENG; O="$RUN/out/$ENG"
grep -q '^RF_EMBEDDING_BATCH_SIZE=[0-9][0-9]*$' "$PINS" || echo "STOP: no batch size in the pins file"
grep -q '^RF_TEI_WAIT_DIR=' "$PINS" && [ -s "$(sed -n 's/^RF_TEI_WAIT_DIR=//p' "$PINS")/patch.json" ] \
  || echo "STOP: no TEI-wait patch in the pins file (P9)"
[ -z "${RF_TEI_WAIT_DIR:-}" ] || echo "STOP: RF_TEI_WAIT_DIR is set in this shell and overrides the pins file: unset it"
```

**E1. Start the stack.**

```bash
bash "$HEAVY" docker compose "${CF[@]}" --profile "$PROF" up -d
docker compose "${CF[@]}" --profile "$PROF" ps -a --format '{{.Name}} {{.State}} {{.Health}}'
```

Check: repeat `ps` until `ragbench-rf-server` is `running healthy` (its start period is 300 s). `tei-probe` has
`exited`, with exit 0 (`docker inspect -f '{{.State.ExitCode}}' ragbench-rf-tei-probe`).
- `up -d` recreates a container only when its own service definition changed. On 2026-11-08, after the TEI-wait
  change to compose.yaml, `docker compose config --hash` of tei, es01, mysql, minio and redis equalled the
  running containers' `com.docker.compose.config-hash` labels, so the TEI that is already warm is kept.
- `config --hash`, `config --services` and `config --quiet` print no values. A full render (`config`,
  `config --format json`) made with the real secrets file holds its values, so send it only into a pipe, never
  to a file: compose copies `env_file` values into the rendered `environment`.

**E2. Isolation checks.**

```bash
docker network inspect ragbench-rf-net --format '{{.Internal}}'                     # true
docker ps --format '{{.Names}} {{.Ports}}' | grep '^ragbench-rf-' | grep -- '->'   # prints nothing
docker exec ragbench-rf-server printenv DOC_ENGINE TEI_MODEL API_PROXY_SCHEME REGISTER_ENABLED EMBEDDING_BATCH_SIZE MAX_CONCURRENT_TASKS
docker inspect ragbench-rf-server --format '{{range .Mounts}}{{if eq .Destination "/ragflow/rag/llm/embedding_model.py"}}{{.Source}} rw={{.RW}}{{end}}{{end}}'
docker exec ragbench-rf-server /ragflow/.venv/bin/python -B /w2/check_tei_wait.py --patch /patch/patch.json \
  --max-concurrent-tasks 1 --embedding-batch-size "$(sed -n 's/^RF_EMBEDDING_BATCH_SIZE=//p' "$PINS")" \
  2> "$RUN/logs/tei-wait-check-$ENG.stderr.txt" | tee "$RUN/logs/tei-wait-check-$ENG.txt"
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

Check: `printenv` gives the engine, `Qwen/Qwen3-Embedding-0.6B`, `python`, `0`, `1` and `1`. The log driver line is
`json-file map[max-file:20 max-size:100m]`. Every `net_check` line is `ok`, the gateway lines included (a
gateway `FAIL` means what P7 says: stop and report).
- The mount line names `$RUN/patch/embedding_model.py` with `rw=false`.
- `check_tei_wait.py` exits 0, every line `ok` (the first ends `: the approved patch`; a record of any other
  source or wait exits 2 there), ending `TEI WAIT LOADED: HuggingFaceEmbed.encode and
  encode_queries wait 900 s; MAX_CONCURRENT_TASKS 1, EMBEDDING_BATCH_SIZE 1; ENABLE_TIMEOUT_ASSERTION unset`.
  Anything else: stop. The server is not running the patched wait, and no document must be parsed on it.

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
  --tei-wait-patch /patch/patch.json --out "/out/$ENG" | tee "$RUN/logs/ingest-$ENG.txt"
# after an interruption: ... rf_ingest.py wait --engine "$ENG" --out "/out/$ENG", then ... dump ... the same way,
# dump with --tei-wait-patch /patch/patch.json
docker exec ragbench-rf-server /ragflow/.venv/bin/python -B /w2/check_tei_wait.py --patch /patch/patch.json \
  --max-concurrent-tasks 1 --embedding-batch-size "$(sed -n 's/^RF_EMBEDDING_BATCH_SIZE=//p' "$PINS")" \
  2> "$RUN/logs/tei-wait-check-$ENG-after.stderr.txt" | tee "$RUN/logs/tei-wait-check-$ENG-after.txt"
```

Check: exit 0, and the last line is `wrote <n> chunks to chunks.jsonl and w2-manifest.json …`. The log holds
`TEI-wait patch: rag/llm/embedding_model.py lines [1247, 1253], wait 900 s, patched sha256 90f3a20d…`. The check
after the ingest ends `TEI WAIT LOADED` again: the mounted bytes did not change during it.
- `all` runs straight through. Its `wait` returns only when every document has settled (rf_ingest.py above:
  `DONE`, a chunk count above 0, the same on two polls), so the last progress line before `parse done for every
  document` ends `settled 22`. The manual stop is no longer needed.
- The two runs of 2026-11-08 predate this fix and waited for the server by hand. Elasticsearch stopped `all`
  with SIGTERM between two polls, then ran `wait` and `dump` once the server log held 22 «handle_task done»
  lines (`.hq/scratch/w2-run/state/run-es.json`, `steps.e5_interrupt_all`). Infinity ran `create`, the same log
  watch, then `wait` and `dump` (`run-infinity.json`). Both waited with `--max-reparse 0`, a recorded deviation
  (`run-es.json`, `deviations_from_runbook`): the default 2 parses a failed document again on its own. This
  runbook has no command that counts those lines, and none is added: the settle rule is the check.

**E6. The gate: ALL MATCH before any query.**

```bash
python -I -B "$T/w2_check.py" --predicted "$O/predicted-chunks.jsonl" --dumped "$O/chunks.jsonl" \
  --manifest "$O/w2-manifest.json" --ingest-state "$O/ingest-state.json"
```

```bash
python -I -c "import json,sys; m=json.load(open(sys.argv[1],encoding='utf-8')); p=json.load(open(sys.argv[2],encoding='utf-8')); d=open(sys.argv[3],encoding='utf-8',newline='').read(); t=m['tei_wait_patch']; print({k:v for k,v in t.items() if k!='diff'}=={k:p[k] for k in t if k!='diff'}, t['diff']==d, t['wait_s'], m['embedding_batch_size'], m['max_concurrent_tasks'])" "$O/w2-manifest.json" "$RUN/patch/patch.json" "$RUN/patch/embedding_model.diff"
```

Check: `ALL MATCH`, exit 0, and the manifest now says `"all_match": true`. Anything else: stop. No query runs on
a dataset that does not match. The second command prints `True True 900 1 1`: the manifest records the patch the
server ran (patch.json's five fields, and the diff byte for byte), the batch size and the concurrency.

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

**E8. Tear the stack down before the next one, except TEI** (and `ragbench-rf-tei-models` if P8 made it). The
owner's later decision has one TEI container serve both engines, since it holds no state; removing it would cost
the Infinity run the 27-minute warmup again (about 33 GB at its peak).

```bash
TEI0=$(docker inspect -f '{{.Id}} {{.State.StartedAt}}' ragbench-rf-tei); echo "TEI before: $TEI0"
SVC=$(docker compose "${CF[@]}" --profile es --profile infinity config --services | grep -vx tei); echo $SVC
[ -n "$SVC" ] && docker compose "${CF[@]}" --profile es --profile infinity rm --stop --force --volumes $SVC
docker ps -a --format '{{.Names}}' | grep -E '^ragbench-rf-' | grep -vx ragbench-rf-tei | xargs -r docker rm -f
docker volume ls --format '{{.Name}}' | grep -E '^ragbench-rf-' | grep -vx ragbench-rf-tei-models | xargs -r docker volume rm
docker ps -a --format '{{.Names}} {{.State}}' | grep -E '^ragbench-rf-'                # ragbench-rf-tei running, alone
[ "$(docker inspect -f '{{.Id}} {{.State.StartedAt}}' ragbench-rf-tei)" = "$TEI0" ] && echo "TEI kept, not restarted"
```

Check:
- The service list has every service but `tei` (es01, infinity, mysql, minio, redis, tei-probe, ragflow,
  runner; `config --services` reads them from compose.yaml, so the list cannot drift from it). `rm --stop
  --force --volumes` stops and removes those containers and their anonymous volumes. The store volumes of
  `compose.store-volumes.yaml`, if that file was used, go with the `volume rm` line.
- Only `ragbench-rf-tei` is left, `running`, and the last line prints `TEI kept, not restarted`: same
  container id, same start time.
- `ragbench-rf-net` stays, since TEI is on it; it holds no state. F removes it at the end.

Then the Infinity run: set `ENG=infinity PROF=infinity STORE=ragbench-rf-infinity:23817` and do E1 to E8. `up -d`
in E1 creates the removed services and keeps the warm TEI, whose service definition does not depend on the
engine (no `RF_DOC_ENGINE` in it), so its config hash is unchanged. Every store is fresh, so the account, the
key, the dataset and the ingest are all redone. P7's batch size and P9's patch are reused. After the Infinity
run's E8, F removes TEI and the network.

### F. Final teardown, and the check that nothing that existed before is gone

`down` interpolates the whole file. After P7 and P9 the pins file holds `RF_EMBEDDING_BATCH_SIZE` and
`RF_TEI_WAIT_DIR`; before them, prefix it with `RF_EMBEDDING_BATCH_SIZE=probe-pending RF_TEI_WAIT_DIR=patch-pending`,
as in P4.

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
  lists are equal. If a «gone» line appears, it was not ours (`down` is scoped by the compose project
  `ragbench-rf`, and every other command above matches `^ragbench-rf-`), and
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
