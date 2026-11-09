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
- **Hosted mode** (`--embedder hosted`, the hosted run only): the same steps with a registered OpenRouter model in
  place of the built-in one and of the TEI-wait record («## Hosted run (owner, 2026-11-09)», «The tools»). The
  built-in mode described here is unchanged.

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
  - For the hosted run it also checks through a proxy: `--proxy`, `--tunnel` and `--tunnel-refused` («## Hosted
    run (owner, 2026-11-09)», «The tools»).
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
- **The hosted run's tests** (2026-11-09; «## Hosted run (owner, 2026-11-09)»). The fake gained the v0.27.3 provider
  routes (its docstring cites them): adding a provider once, a name-only instance, the instance update with its
  required fields, the instance listing, the key-returning instance read (which no tool may send), the connection
  check, and a dataset whose `<model>@<instance>@<factory>` must resolve to a registered model with a key.
  - **`tests/test_register_hosted.py`** (24 tests). The three routes in order and nothing else; the name-only
    instance, then the key with `verify` false and the exact body; the OpenRouter key in exactly one request body
    and in no path, query, header, output or file; the RAGFlow key in the `Authorization` header only; the record's
    keys, with the key's length and salted sha256 only; `--provider-order` sending the key as JSON made in memory;
    the stored model found by the dataset route. Refused before sending: a key file missing, empty, of two lines (or
    a blank second one), with a byte-order mark, with spaces, a RAGFlow key, a short key, capital hex, non-ASCII; an
    instance `default`, with a space or a slash, or empty; a model without a vendor, with an «@» or a space; an
    empty, blank or two-line note; a provider order in capitals, with a «;» or empty; an existing record; a
    non-loopback URL; the key-returning route and the listing. One line, with LF, CRLF or no end, is accepted.
    `Client.redact` alone, and `main`'s own log redacting both keys from a refusal or failure worded with them that
    never went through `Client.redact` (fix2). A provider already added stops it; a server message repeating both
    keys is shown redacted and nothing is written; a proxy named in the environment is not used. `smoke`: one connection check
    with the key and the model, the JSON form with a provider order, a failure shown redacted.
  - **`tests/test_rf_ingest_hosted.py`** (14 tests; the registration made by `register_hosted.py` against the same
    fake). The dataset made with the registered model and nothing sent to TEI; the manifest's keys, with
    `hosted_embedder` in place of `tei_wait_patch` and in its key order, the batch size and concurrency; the same
    chunks as the built-in mode; `wait` and `dump` run again; a model the server cannot resolve stopping before the
    upload; the OpenRouter key in no output or file. Refused: a `--tei-wait-patch`; `create`, `dump` and `all`
    without the model or the record, and the hosted options in the built-in mode, each with its message, a missing
    one with its own step's usage and «<step>: error:» line, as before the hosted mode (fix2); the stack's
    other embedder, both ways; four other `--embedding-model` values; eight broken records; a `dump` with another
    record than `create` kept.
  - **`tests/test_net_check_proxy.py`** (9 tests; a fake CONNECT proxy, certificates from
    `../ragflow-w1/tests/tls_cert.py`). A tunnel with a verified handshake; exactly the CONNECT line and the
    handshake sent, nothing after; an untrusted certificate (interception) fails; a refused tunnel fails; 403 counts
    as refused, 200 and 503 do not; a silent proxy fails both kinds; refusals without a tunnel, and either check
    without `--proxy`, refused.
  - **`tests/test_net_check_scan.py`** (10 tests, fix2, then stage 5 and its review). `--scan` against a real
    listener on 127.0.0.1: connected, and the listener receives 0 bytes; both ends of the range tried; each outcome
    counted and the connected, refused and timed-out ports named (the review's 111/46425, 80/443/8080 and 65,530
    refused shape); any port that accepts a connection fails the run (a `FAIL scan` line naming it, exit 1), and so
    does a refused one, alone among silent ports (a host answered); an error that is not silence (errno 24) fails as
    «not checked»; only timed-out, «no route to host» and «network unreachable» ports pass, with an `ok   scan`
    line; a clean scan does not hide another failed check; a list cut at 200 with the count of the rest; a name, a
    port 0 or 65536, a reversed or unreadable range, and `--scan-ports` without `--scan` refused before anything is
    tried.
  - **`tests/test_es_mapping.py`** (26 tests, stage 5 and its review) uses an invented `mapping.json` shaped like v0.27.3's (its
    pinned sha256 swapped for the fixture's) and the v0.27.3 source tree copy when it is there. `write`: one
    template added right after `*_1536_vec`, formatted as the source, its eleven lines the `*_1536_vec` block's with
    the two numbers changed; the record and the diff (11 lines added, none removed). Refused, nothing written: any
    source but the pinned one; CR bytes, not UTF-8; the `*_1536_vec` block found 0 or 2 times; a source already
    naming `*_4096_vec`; an earlier template that would take `q_4096_vec` (a `*_vec` match, a regex, a
    `match_mapping_type` it cannot judge), and one whose `match` is a list or a regex that does not compile (each
    counts as one that would, refused with a message, not a traceback); a property of that name; `--out` rules as
    `patch_tei_wait.py`'s, a symlinked `mapping.json` in it foreign even with `--replace`; a copy that reads back
    with other bytes, removed. The second pass: its text layer refuses changes the JSON does not show, its JSON layer
    a block put in the wrong place. `check`: the approved copy passes, and so does one with earlier templates that
    match only part of the name or a dot taken as a wildcard (`q_4096`, `4096_vec`, `q.4096.vec`, two regexes);
    another sha256 fails though the template is right; a wrong `dims`, `similarity`, `index`, `type` or an extra
    option fails though the sha256 is approved, and so do a template missing, after `*_bin`, twice, shadowed, after
    a second `*_1536_vec`, or after a template with a `match_pattern` it cannot judge; a list `match` or a regex that
    does not compile fails with `BAD` and `ES MAPPING NOT APPROVED`; unreadable JSON fails; a missing file is refused. On the real file:
    the pinned sha256 is the tree copy's, the copy's sha256 is `PATCHED_SHA256`, lines 204-214, the hunk
    `@@ -201,6 +201,17 @@`, the other 19 templates unchanged, and `check` fails the shipped file.
  - **`tests/test_key_leak_check.py`** (22 tests). Clean files pass and are counted; the key found in a file by its
    path, split across two reads once each, cut short by its pieces, on stdin under its label; files and stdin read
    together; the key file itself skipped; the last 16 characters of a secret whose length is no multiple of 16 found
    as a piece of their own (fix2). Streams (fix2): an empty stream incomplete, alone or beside files that were read;
    a stream shorter than `--min-bytes` incomplete, one of exactly that length a pass; a key found outranking a short
    stream; `--min-bytes` without `--stdin`, or below 0, refused; a `--scan` that read no file incomplete even beside a
    stream. Refused: a key file missing, empty, of two lines, short or with a space;
    nothing to search, a path that does not exist; an unreadable file makes it incomplete, but a key found outranks
    that; an empty folder is not a pass. The registered key confirmed by its salted sha256, another one refused.
    No test output holds the key or any of its pieces.
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
review's fixes, these 146 and the folder's 190 passed (`.hq/scratch/w2-stage4/fix1/suites.txt`). After the hosted
run's build (2026-11-09: 59 new tests in four files, the 190 unchanged), the folder's 249 passed
(`.hq/scratch/w2-stage4/build/logs/suites.txt`). After the two reviews' fixes (fix2: 16 new tests, one new file,
`tests/test_net_check_scan.py`), the folder's 265 passed (`.hq/scratch/w2-stage4/fix2/logs/suites.txt`). After
stage 5 (the gateway and the Elasticsearch mapping: 21 tests in one new file, `tests/test_es_mapping.py`, and two
more in `tests/test_net_check_scan.py`, two of whose six changed with `--scan`'s verdict), the folder's 288 passed,
and `../ragflow-w1`'s 261, `run_w1.py` still `b6440e5b…cb10` (`.hq/scratch/w2-stage5/build/logs/suites-w2.txt`,
`suites-w1.txt`). One more full run on that code, at 14:30Z, failed one older test once,
`test_a_failed_document_alone_is_parsed_again` (`tests/test_rf_ingest.py`), with nothing to show but `1 != 0`, since
its exit-code assertion carried no message (`build/logs/suites-w2-final.txt`); the runs before and after it passed
(`suites-w2.txt`, `suites-w2-final2.txt`), and the stage 5 review saw no failure in 48 runs of it, six at a time. That
assertion now prints the tool's output, so a repeat names its own cause; if it fails again it is quarantined, not
passed over. After the stage 5 review's fixes (five new tests in `tests/test_es_mapping.py` and one changed; two new
in `tests/test_net_check_scan.py` and four changed with `--scan`'s stricter verdict), the folder's 295 passed, and
`../ragflow-w1`'s 261, `run_w1.py` still `b6440e5b…cb10` (`.hq/scratch/w2-stage5/fix/logs/suites-w2.txt`,
`suites-w1.txt`). The new checks' mutations, each on a copy of the folder, never the worktree, were all killed; the
mutations the review's own list had left alive in `patch_es_mapping.py`, rerun as eight (its `:127` change split in
two, and the same change to the regex branch), were killed but one (`.hq/scratch/w2-stage5/fix/logs/mutations.txt`).
That one, the `settings` comparison in the second pass,
cannot be killed by any test: one insertion that passes the text layer either lands right after `*_1536_vec`, where
the settings cannot differ, or fails the template comparison beside it. It stays as part of the JSON layer, which
is meant to hold without the text layer.

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
- **The hosted run's build, 2026-11-09.** A list chosen by the builder (`.hq/scratch/w2-stage4/build/mutate_build.py`,
  47 mutations and two controls, one copy each, across `net_check.py`, `register_hosted.py`, `rf_ingest.py`'s hosted
  mode, `key_leak_check.py` and `score_w1.py`'s hosted manifest), so it shows that each new check has a test, not how
  much the suite covers. 46 were killed (`build/logs/mutate.txt`). The survivor, a 16-character piece counted again
  at every read, was killed once the split test asserted the piece count too (`build/logs/mutate-leak-rerun.txt`).
  Each new test file's red run, before its code existed, and its green run are `build/logs/red-*.txt` and
  `green-*.txt`. Two layers of redaction in `register_hosted.py` mean that removing either alone shows nothing at its
  output; `Client.redact` therefore has its own test, and the second layer, in `main`'s `log`, had none until fix2
  gave it one (below).
- **The reviews' fixes (fix2), 2026-11-09.** The correctness review's own list
  (`.hq/scratch/w2-stage4/review2-correct/mutate_review.py`, 28 mutations) left 6 survivors: the log redaction
  above, the last 16-character piece, the hosted instance check in `score_w1.py`, and three built-in output paths
  of `score_w1.py` (the embedder row, the terminal line, the hosted banner). fix2's list
  (`.hq/scratch/w2-stage4/fix2/mutate_fix2.py`, one copy each) repeats those six with the review's own text, adds 18
  for fix2's changes (the stream rules and `--min-bytes` of `key_leak_check.py`, `net_check.py --scan`, the step's
  usage in `rf_ingest.py`) and two controls: all 24 killed, both controls passing (`fix2/logs/mutate.txt`). The red
  runs: `fix2/logs/red-w2.txt`, before any code (the new options unknown), and `red-w2-stubs.txt`, with the options
  accepted and ignored so that each new test fails on its own assertion; the tests that pin behaviour already there
  (the six survivors) were shown by the mutations instead.
- **Stage 5, 2026-11-09: the gateway and the Elasticsearch mapping.** A list chosen by the builder
  (`.hq/scratch/w2-stage5/build/mutate_stage5.py`, one copy of the folder each under that stage's scratch): 22
  mutations of `patch_es_mapping.py` (the sha256 pin, the CR refusal, the block's two numbers, its place, the
  anchor count, a source already naming 4096, the precedence check and its regex and unjudgeable branches, the
  property check, each layer of the second pass, the `--out` rules, the diff's hunk, the approved sha256, and
  `check`'s sha256, shape, place, count and exit), 3 of `net_check.py --scan`'s verdict, and two controls. The
  first run left four survivors, each a guard another guard covered (`logs/mutations-run1.txt`); the tests then
  named each refusal's own message, and the second pass was cut to two layers, each with a case only it catches.
  Second run: all 25 killed, both controls passing (`logs/mutations.txt`). Red runs before any code:
  `red/test_es_mapping-red.txt` (the tool missing), `red/test_net_check_scan-red.txt` (4 failures),
  `red/check-render-red.txt` (4 `FAIL` lines and the guard not stopping the render).

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
`D:/...` (with `MSYS_NO_PATHCONV=1`), and bash reads `heavy.sh` by its POSIX path. The hosted OpenRouter run has
its own runbook, H0 to H10, in «## Hosted run (owner, 2026-11-09)» at the end.

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

## Hosted run (owner, 2026-11-09)

The owner's one extra run with an embedder hosted on OpenRouter, reported only (spec-rag-system.md:472, «The hosted
run»; decided «now» on 2026-11-09, :475 point 3). It is exploratory: the deciding cell stays the local Elasticsearch
run with the built-in Qwen3-Embedding-0.6B, and `score_w1.py` refuses `--w2-decide` on a hosted manifest. Its
premises were checked first: `.hq/scratch/w2-stage4/premises/PREMISES-hosted-run.md` (cited below as PREMISES §n),
with the raw public data it read in `premises/web/`. This section builds the stack and the tools; nothing here has
run against OpenRouter, and no agent reads the key.

### What is sent where

| What | Path | When |
|---|---|---|
| The text of every chunk (6,612 chunks, about 2.2 M characters of our served law text in W2) and each file name once (22 calls, `rag/flow/tokenizer/tokenizer.py:95`) | server → `ragbench-rf-proxy` (Squid, CONNECT only, no TLS interception) → `openrouter.ai:443` → the provider the owner's guardrail allows (Nebius) | H5, the parse |
| The word «ok», once per document task when RAGFlow binds the embedder (about 22 calls, `rag/svr/task_executor_refactor/task_handler.py:384`); each goes through `LLMBundle.encode`, so `used-tokens.txt` counts it (`api/db/services/llm_service.py:219`) | the same | H5, the parse |
| The 80 items' `query` and `question` texts, once per arm (2 arms: 320 calls) | the same | H7 |
| One test sentence, «Test if the api key is available» (about 8 tokens) | the same | H4, only if the owner approved the smoke call |
| The OpenRouter key | the owner's file → the runner (a read-only bind of that one file) → the server, in one `PUT` body over loopback → MySQL on tmpfs, in plain text (`tenant_model_instance.api_key`, `api/db/db_models.py:1863-1872`) → the `Authorization` header of the server's OpenAI client, inside TLS | H4 to H10 |

Nothing else leaves the stack: no canvas, no upload manifest, no result, no log, no query to Hugging Face or PyPI
(the proxy answers those 403). Squid sees only `CONNECT openrouter.ai:443`, never a header, a body or the key.
OpenRouter keeps request metadata (token counts, latency) and screens all traffic for CSAM in flight, ZDR included;
whether its «Anonymous Input Categorization» samples embeddings is not stated (PREMISES §2). The text is our
published Jordanian law text and the draft test queries, which the owner accepted sending (spec :472).

**The key at rest.** In MySQL on tmpfs, so it is gone at teardown. `GET /api/v1/providers/<p>/instances/<i>`
answers with it in clear (`api/apps/services/provider_api_service.py:1117`); no tool here may send that route
(`register_hosted.py` ROUTES, tested). No RAGFlow log line on this path prints it (PREMISES §4), `peewee` stays at
WARNING so no SQL statement is logged, and the openai SDK redacts its `Authorization` header. The key is checked for
in every saved file, the server's log and the containers' configuration (H3, H4, H7, H9).

### The data-policy switches the owner sets (H0)

All on openrouter.ai, logged in (PREMISES §2). A key in the file changes none of them, and no agent can see them.

1. **Privacy** (https://openrouter.ai/settings/privacy). Data training: «Allow paid endpoints that train on request
   data», «Allow free endpoints that train on request data», «Allow free endpoints that publish prompts» and «Allow
   1% data discount» all **off**. ZDR: enforce for **All other models** (Qwen is in that group), Safety Retention
   **ZDR only**. Click **Save changes**, reload, and check that the toggles stayed (the labels come from a
   third-party issue of 2026-09-24; the page itself was not seen).
2. **Observability** (https://openrouter.ai/workspaces/default/observability): «Input & Output Logging» **off**,
   «Broadcast» **off**.
3. **A guardrail** (Workspaces → Default → Guardrails → New Guardrail): model allowlist `qwen/qwen3-embedding-8b`;
   provider allowlist **Nebius** only; ZDR enforced for All other models, Safety Retention ZDR only; budget **$2**.
   Assign it to the key. Its «Eligibility preview» must show exactly one endpoint: «Nebius |
   qwen/qwen3-embedding-8b». This is the layer that binds: a breach is a documented 403, an allowlist nothing
   satisfies a documented 404, and the openai SDK retries neither (PREMISES §2, §5).

### The key file

`C:/Users/accou/.ragbench-rf/openrouter.key`, written by the owner (H0), never opened by an agent. One line: the raw
key, `sk-or-v1-` and 64 lower-case hex characters (the shape of every key in OpenRouter's key documentation, read
2026-11-09; `premises/web/doc-api_api-reference_api-keys_create-keys.md`), with or without one line end, no
byte-order mark. `register_hosted.py` refuses anything else before it sends anything, and its messages never quote
the file. A dedicated key: credit limit **$2**, no reset, an expiry a few days after the run; disable or delete it
after H10. The folder also holds `secrets.conf`, so compose binds the file alone, never the folder.

### The model and its cost

**`qwen/qwen3-embedding-8b`, on Nebius only** (PREMISES §3): bf16, $0.01 per million tokens, a 40,960-token context,
on OpenRouter's ZDR list with `safety_retention: false`. Its MMTEB mean is 70.58 against 64.33 for the local 0.6B
(Hugging Face model card); it is the 0.6B's big sibling, so the run changes the model's size, not its family.
DeepInfra is the fallback if Nebius is down on the day: one provider, never both, or documents and queries are
embedded by different deployments.

- **Expected cost:** about 0.9 M tokens (864,009 measured Qwen tokens of the corpus, plus the file names and the
  320 queries) × $0.01/M ≈ **$0.009**. That assumes the 8B's tokenizer is the 0.6B's (same Qwen3 vocabulary; not
  verified) and that OpenRouter bills the provider's count.
- **Ceiling:** 1.55 M tokens (RAGFlow's cl100k count) × $0.04/M (SiliconFlow's price, should routing go wrong) ≈
  **$0.06**. The key's $2 limit is over 30 times that.
- RAGFlow logs the provider-reported count of each call (`LLMBundle.encode used_tokens`,
  `api/db/services/llm_service.py:219`, `:247`); H9 sums it for the reconciliation with OpenRouter's activity page.

### The stack: `compose.hosted.yaml` and `squid.conf`

`compose.hosted.yaml` is an overlay, used only on top of `compose.yaml` with the profiles `es` and `hosted`. What is
not named in it is `compose.yaml`'s: the same pinned server, the same Elasticsearch store set, the same runner, the
same internal network, no published port. Its header lists every change; in short:

| Change | Why |
|---|---|
| `tei` and `tei-probe` move to the profile `builtin`, never enabled here; the server's wait for `tei-probe` becomes `required: false` | no TEI on this stack (the pattern compose.yaml uses for `es01` and `infinity`) |
| The server's volumes are restated (`!override`) without the TEI-wait patch and `/patch` | the hosted run uses the shipped `embedding_model.py` (PREMISES §5) |
| The server reads `$HR/es-mapping/mapping.json` (`RF_ES_MAPPING_DIR`, with a `:?` guard), bound read-only over `/ragflow/conf/mapping.json`: the image's file with one more template, `*_4096_vec` (`dense_vector`, `dims` 4096, `cosine`, `index` true, as the 512/768/1024/1536 ones), written by `patch_es_mapping.py` in H1 | the model's vectors go to `q_4096_vec` (`tokenizer.py:124`), which no shipped template matches, so Elasticsearch 8.11 would map it by its own dynamic mapping (PREMISES §6); with the template, the mapping RAGFlow sends decides it (below, «The Elasticsearch mapping») |
| `COMPOSE_PROFILES` without `tei-cpu` | no built-in embedder (`common/settings.py:392-395`; every TEI path is gated on «tei-»), and the boot-time tenant has no default embedding model to test (`api/db/init_data.py:91-94`) |
| `ragbench-rf-proxy` (`ubuntu/squid:7.2-26.04_edge`, by digest) on `ragbench-rf-net` and on `ragbench-rf-egress`, the one non-internal network; nobody else joins it | the only route out (spec :472) |
| `ragbench-rf-net`'s subnet pinned to `10.231.47.0/27`, its gateway to `10.231.47.1` | `squid.conf`'s `src` ACLs name both: only the subnet may use the proxy, so the egress side cannot, and the gateway address is refused first. The pin also keeps that address reserved, so no container is given it |
| `ragbench-rf-net` gets the bridge option `com.docker.network.bridge.inhibit_ipv4: "true"`; still internal | the bridge has no IPv4 address on the Docker engine's side, so the engine's own listeners (111 and 46425 answered on `10.231.47.1` before) are out of the stack's reach over IPv4; names, peers and the proxy work as before (below, «The gateway») |
| Every service on `ragbench-rf-net` (es01, mysql, minio, redis, proxy, ragflow, and the runner, which has its own capabilities though it shares the server's namespace): `cap_drop: [NET_RAW]` | the bridge keeps an IPv6 link-local address on the engine's side, where 111 still accepted a connection; the containers have IPv6 off on eth0, so only a raw frame reached it, and a raw frame needs `CAP_NET_RAW`, which Docker grants by default (stage 5 review; below, «IPv6 and raw frames») |
| The proxy: `sysctls` `net.ipv4.ip_forward` and `net.ipv4.conf.all.forwarding` `"0"`; `squid.conf`: `pinger_enable off` | the proxy is on both networks, and a container's namespace forwards by default (`ip_forward` 1), so a raw frame addressed to it from `ragbench-rf-net` could have been routed onto `ragbench-rf-egress` (the review's inference). Live, the engine dropped every such frame on the internal bridge before any container counted it (below, «IPv6 and raw frames»), so this is a second guard; Squid's ICMP helper is setuid root and opens raw sockets, which the proxy may no longer |
| The server: `HTTPS_PROXY`/`https_proxy` = `http://ragbench-rf-proxy:3128`, `NO_PROXY`/`no_proxy` naming every internal host, `localhost`, `127.0.0.1` and `::1`; no `HTTP_PROXY` | openai 2.41.0 on httpx 0.28.1 honours them (PREMISES §5). Every internal URL is `http://`, so no internal call can reach the proxy even if `NO_PROXY` missed a name. The server waits for the proxy to start |
| `LOG_LEVELS` adds `openai=INFO` | at root DEBUG the SDK would log every request's options, chunk text included (PREMISES §4) |
| `LLM_TIMEOUT_SECONDS=60` | the wait of a provider check, default 10 s (`provider_api_service.py:894`); only the smoke call uses it |
| The runner: `W2_EMBEDDER=hosted` and no TEI variables; `/out` is `.hq/scratch/w2-hosted/out`, `/hr` the whole hosted folder (read-only, for the leak check), `/keys/openrouter.key` the key file (read-only); no `/patch`, no proxy variable | the key reaches no other container and no environment variable |

**Operational settings** (spec: they decide no chunk, vector or score):
- `EMBEDDING_BATCH_SIZE=16` (the hosted pins file). RAGFlow's OpenRouter client sends at most 16 inputs per request
  anyway (`OpenRouterEmbed.encode`, `rag/llm/embedding_model.py:1552-1553`), so the pipeline's batches match it:
  about 440 requests instead of about 6,650 at 1. W2's 1 was for TEI on CPU only. Whether a provider's numbers vary
  in their last bits with a batch's make-up was not checked; it decides nothing here.
- `MAX_CONCURRENT_TASKS=1` (compose.yaml's default): one document at a time, so the in-flight spend and the request
  rate stay small (OpenRouter's in-flight budget answers 402, which the openai SDK does not retry; no rate limit is
  documented for paid models; PREMISES §3, §6), and the setting is the local run's. `MAX_CONCURRENT_CHUNK_BUILDERS`
  stays 1.

**Squid** (`squid.conf`) allows `CONNECT openrouter.ai:443` from `ragbench-rf-net` and nothing else: the network's
gateway refused first, `dstdomain -n` (an IP literal is never looked up in reverse), port 443 only, CONNECT only, a
destination that resolves to a private address refused, no cache, no `ssl_bump`. Each request is one line in
`/var/log/squid/access.log` (tmpfs), in the form `<time> <client> CONNECT openrouter.ai:443 200 TCP_TUNNEL <bytes>
<server>`, or `… 403 TCP_DENIED …` for a refusal. A tunnel is one line, written when it closes, not when it opens:
the openai client keeps its tunnel open between calls, so the log counts tunnels, not embedding calls, and a tunnel
still open is not in it yet (H9 stops the server before the last copy). `docker logs ragbench-rf-proxy` does not
carry the log (the image's Pebble does not forward its service's output); the runbook reads it with `docker exec`.

**What was checked on 2026-11-09, before anything ran** (logs in `.hq/scratch/w2-stage4/build/`, then
`review2-safety/` and `fix2/` beside it):
- The overlay renders (`docker compose config`, placeholder secrets and pins): `fix2/render/check-render.txt`, 22
  lines `ok` (the build's 21, `build/render/check-render.txt`, and the gateway pin). Services es01, mysql, minio,
  redis, proxy, ragflow, runner; no TEI; only the proxy on the egress network; `ragbench-rf-net` at `10.231.47.0/27`
  with its gateway `10.231.47.1`; no port; the key bind in the runner only. Without `--profile hosted` the project
  refuses to load («service "ragflow" depends on undefined service "proxy"», `fix2/render/no-hosted-profile.txt`),
  so the hosted server cannot start without its proxy; `compose.yaml` alone renders as before
  (`build/render/base-alone.txt`).
- The pin: `docker buildx imagetools inspect ubuntu/squid:7.2-26.04_edge` gave
  `sha256:041c64dd14c81548023c9532e4c2fac487e9a3f9f490913b50547d2974722025`, the digest the premises read from Docker
  Hub (`build/logs/squid-imagetools-inspect.txt`); pulled by digest (`build/logs/squid-pull.txt`). The tag moves
  (rebuilt 2026-11-07), so H1 pins this digest instead of reading the tag again.
- `squid -k parse` in that image (its binary is `/usr/sbin/squid-gnutls`), offline, of the `squid.conf` with the
  gateway refused: exit 0, no warning (`fix2/selftest/parse-2.txt`; the build's, before that change,
  `build/logs/squid-parse-2.txt`).
- Three live self-tests, each with the proxy alone as `ragbench-rf-proxy` on two throwaway networks
  (`ragbench-rf-st-int`, internal, `10.231.47.0/27`; `ragbench-rf-st-egress`), clients on them, and everything
  removed afterwards: the build's (`build/proxy_selftest.sh`, `build/logs/proxy-selftest.txt`), the safety review's
  (`review2-safety/proxy-selftest-review.txt`), and fix2's, after the gateway was refused
  (`fix2/selftest/proxy_selftest_fix2.sh`, `proxy-selftest-fix2.txt`). From the internal network: direct
  `1.1.1.1:443` unreachable (errno 101), `openrouter.ai`, `huggingface.co` and `pypi.org` without an address;
  `CONNECT openrouter.ai:443` answered 200 and a TLS 1.3 handshake verified openrouter.ai's certificate (no
  interception), with nothing sent after it; `huggingface.co:443`, `pypi.org:443`, `1.1.1.1:443`,
  `host.docker.internal:443`, `openrouter.ai:80` and `www.openrouter.ai:443` each refused with 403
  `ERR_ACCESS_DENIED`; of the review's 20 raw request forms (fix2 repeated all but the IP literal), only
  `openrouter.ai:443` itself (any case, a trailing dot, HTTP/1.0) got 200; its IP literal, other names and ports, a
  lying `Host`, a plain or absolute `GET` and the cache manager got 403, and a userinfo form 400. From the egress network, both a CONNECT and a GET got 403 (the `src` ACL). `access.log`, read
  with `docker exec`, held every line (`docker logs` held only Pebble's), and a tunnel held open for 12 s was
  logged only when it closed (fix2, step 5). **Not exercised:** a client at the gateway's own address, which only
  a container on the Docker engine's host network could be; the rule that refuses it rests on the parse and on
  the `src` ACL working from the egress side. Since stage 5 no interface holds that address («The gateway»).
- The internal network's gateway answered on two ports (`review2-safety/`, then fix2): closed by the build since,
  below («The gateway»).
- Stage 5 (2026-11-09, later; logs in `.hq/scratch/w2-stage5/build/`): the overlay with the two fixes below renders
  (`render/check-render.txt`, 28 lines `ok`: the 22 above, the network option, no option on the egress network,
  and the mapping bind in the server alone, read-only, with no other server mount); without `RF_ES_MAPPING_DIR` the
  render stops («required variable RF_ES_MAPPING_DIR is missing a value»); `compose.yaml` alone renders as before,
  its network without driver options. The same check run against the overlay before the change failed on those
  lines (`red/check-render-red.txt`). `squid.conf`'s comments changed, not its rules; `squid -k parse` of it in the
  pinned image, offline: exit 0, no warning (`logs/squid-parse.txt`).
- The stage 5 review's fixes (2026-11-09, later; logs in `.hq/scratch/w2-stage5/fix/`): the render check, extended
  (`render/check-render.txt`, 39 lines `ok`: the 28 above, `cap_drop [NET_RAW]` on each of the seven services, no
  service adding a capability or privileged, the proxy's two sysctls at `"0"` and no other service's); the same
  check against the overlay before the change failed on the eight lines that need it, the seven `cap_drop` lines
  and the sysctls (`red/check-render-red.txt`);
  `compose.yaml` alone renders as before, without `cap_drop` or `sysctls`. `squid.conf` gains one rule,
  `pinger_enable off` (the pinned Squid 7.7 is built with `--enable-icmp`, so its helper would start): `squid -k
  parse` in the pinned image, offline, with `NET_RAW` dropped: exit 0, no warning (`logs/squid-parse.txt`).

### The gateway

**The finding** (2026-11-09; `.hq/scratch/w2-stage4/review2-safety/`, then fix2 with `net_check.py --scan`). A TCP
connect scan of `10.231.47.1`, every port, nothing sent, from the internal network: 111 and 46425 accepted a
connection; 80, 443 and 8080, ports other containers publish, timed out; the other 65,530 refused. The gateway was
the Docker engine's side of the bridge, so the stack could reach two services of the Docker VM: 111 is by
convention rpcbind, 46425 was not identified, and `wsl.exe -e ss -ltn` showed neither in the default WSL
distribution, so they are on Docker Desktop's side (inferred). W2's gateway lines tested 443 and a published port,
which time out, so they could not show it; the W2 stacks, on the same Docker, most likely had the same exposure
(inferred). The owner did not accept it as a residual risk (2026-11-09), so the build removes it.

**The fix.** `compose.hosted.yaml` gives `ragbench-rf-net` the bridge driver option
`com.docker.network.bridge.inhibit_ipv4: "true"`; the network stays internal and its subnet and gateway stay
pinned. Docker's bridge driver documentation (https://docs.docker.com/engine/network/drivers/bridge/, read
2026-11-09; the engine here is 29.9.1): the option is to «Prevent Docker from assigning an IP address to the bridge»,
for user-defined bridge networks only, and with it «north-south traffic (to and from the bridge network) won't work
unless you've manually configured the gateway address on the bridge, or a device attached to it». The Engine 28.0.0
release notes (https://docs.docker.com/engine/release-notes/28/, moby PR 49261) add that an internal bridge
network with this option reserves no gateway address unless one is configured. Ours is configured, so `10.231.47.1`
stays reserved (no container is given it, and `squid.conf` still refuses it as a client) while no interface holds
it. The same notes describe the finding itself (PR 49262): an internal network's bridge normally has an address,
through which its containers reach the host's services, those listening on every address included. That PR's
gateway mode `isolated` (internal networks only) has the same IPv4 effect, and for IPv6 is said to keep the bridge
from a link-local address too; on this engine, on an IPv4-only network, it did not (below, «IPv6 and raw frames»),
so it is not used. The IPv4 fix alone was not enough: the build's claim here that the containers' IPv6 being off
closed the IPv6 side was wrong, and the stage 5 review showed why (below).

**Seen live, 2026-11-09** (`.hq/scratch/w2-stage5/build/live_gateway.sh`, `logs/live-gateway.txt`): the proxy
service started from the compose files themselves (placeholder pins and secrets, `up --no-deps proxy`), which made
`ragbench-rf-net` and `ragbench-rf-egress`; two throwaway clients, `ragbench-rf-st-*` (python:3.12-slim by digest),
on `ragbench-rf-net`; everything removed afterwards.
- `docker network inspect ragbench-rf-net`: internal, `10.231.47.0/27`, IPAM gateway `10.231.47.1`, option
  `com.docker.network.bridge.inhibit_ipv4` `true`; the proxy, the peer and the client at `.2`, `.3` and `.4`.
- In the client: one route, `10.231.47.0/27` on eth0, and no default route; the addresses `10.231.47.4` and
  `127.0.0.1`; IPv6 off on eth0 (`disable_ipv6` 1, only `::1` on lo).
- Docker's embedded DNS (`127.0.0.11`): `ragbench-rf-proxy` and `proxy` gave `10.231.47.2`, `ragbench-rf-st-peer`
  `10.231.47.3`; TCP by name to the peer and to the proxy (both names) connected.
- The proxy from the subnet: `CONNECT openrouter.ai:443` answered 200 (the tunnel closed at once, nothing sent
  through it), `CONNECT huggingface.co:443` 403; its log holds both lines.
- `net_check.py --scan 10.231.47.1`, every port (4 min 16 s): **no port accepted a connection** (61,664 timed out,
  3,871 «no route to host», errno 113; none refused, so the stricter verdict the review asked for, below, passes it
  too), and the client's neighbour table left `10.231.47.1` unresolved (`00:00:00:00:00:00`, flags `0x0`): nothing
  on the bridge answers for that address over IPv4.
- The control, in the same run: an internal network made without the option (`ragbench-rf-st-ctl`,
  `10.231.47.32/27`) and a client on it. The scan of its gateway, `10.231.47.33`, found **111 and 46425**
  connected, as before (80, 443 and 8080 timed out). So the empty scan is the option's doing, not a change in the
  engine.

**IPv6 and raw frames** (the stage 5 review, 2026-11-09, later: `.hq/scratch/w2-stage5/review-security/`, then the
fixes, `.hq/scratch/w2-stage5/fix/`). `inhibit_ipv4` takes the bridge's IPv4 address away, not its IPv6 link-local
one. The containers have IPv6 off on eth0 (`disable_ipv6` 1; `/proc/sys` is read-only, so they cannot turn it back
on), but Docker gives every container `CAP_NET_RAW` by default, and with it a root process sends frames of its own
making through a packet socket (`AF_PACKET`), IPv6 ones included, whatever eth0's setting. The review did that from a
client on a network built as the overlay builds this one: an ICMPv6 echo to all nodes was answered by one address,
the engine's side of the bridge, and a TCP SYN to its port 111 got a SYN-ACK (46425 and 1 a reset), so the engine's
rpcbind was still reachable (`rv_run.log`). Root runs in the server and the runner, in redis (its entrypoint is
overridden), in minio and in mysql's entrypoint; Elasticsearch runs as 1000:0 and Squid as 584792, but Squid's ICMP
helper, `/usr/lib/squid/pinger`, is setuid root. The `isolated` gateway modes did not help on an IPv4-only network:
with `gateway_mode_ipv6=isolated`, beside `inhibit_ipv4` or with `gateway_mode_ipv4=isolated`, the link-local address
stayed and 111 still answered (`rv_fix.log`, cases A and B). Without `CAP_NET_RAW` the client could not open the
packet socket at all (case C). An IPv6 subnet (a ULA) with `isolated` left nobody answering (`rv_fix_d.log`, case D);
it is not used, since it would give every container an IPv6 address, which `squid.conf`'s `src` rules and `NO_PROXY`
do not name.

**The fix for raw frames.** Every service on `ragbench-rf-net` drops `CAP_NET_RAW` (`cap_drop: [NET_RAW]`, the runner too: it shares
the server's namespace but has its own capabilities); the proxy routes nothing between its two networks
(`net.ipv4.ip_forward` and `net.ipv4.conf.all.forwarding` `"0"`); Squid's ICMP helper is off (`pinger_enable off`).
Nothing in the stack needs `CAP_NET_RAW`: the stores and the server open ordinary sockets (the server's entrypoint
starts nginx and Python, and nothing in it pings: `docker/entrypoint.sh`, read from the source), and Squid uses its
helper only to measure round trips, which a tunnel-only proxy does not need. Only `NET_RAW` is dropped, not every
capability: mysql's entrypoint needs `SETUID` and `SETGID` for `gosu`, and the server's nginx binds port 80.

**Seen live, 2026-11-09, later** (`.hq/scratch/w2-stage5/fix/live/live_fix.sh`, `live-fix.txt`): es01, mysql, minio,
redis and the proxy started from the compose files as they now are (placeholder pins and secrets, `up --no-deps`; no
server, no runner, no key), throwaway `ragbench-rf-s6-*` containers beside them, everything removed afterwards.
- The four stores healthy after 90 s and the proxy running, each with `drop=[CAP_NET_RAW] add=[] privileged=false`
  and the bounding set `00000000a80405fb`, Docker's default `a80425fb` without bit 13: H3's capability lines print
  `ok` for all five. The proxy's forwarding values are `0` and `0`, and its `cache.log` names no pinger.
- A client with `NET_RAW` dropped: the packet socket refused (EPERM), IPv6 off on eth0 with only `::1` on lo, and the
  review's probe stops at the socket (`PermissionError`). The control, a client with Docker's default set on the same
  network: H3's capability and socket lines `FAIL` it, and its probe got the bridge's link-local answer and a SYN-ACK
  on 111 again. So the finding holds on the network compose builds, with the stores and the proxy on it.
- The pinned server image's own interpreters (`python3` and `/ragflow/.venv/bin/python`, as a one-off, not the
  server) on `ragbench-rf-net` with `NET_RAW` dropped: the packet socket refused; with the default set, opened, and
  H3's line `FAIL`s it. IPv6 is off on its eth0.
- The proxy still serves: `CONNECT openrouter.ai:443` 200 (the tunnel closed at once, nothing sent through it),
  `CONNECT huggingface.co:443` 403.
- Forwarding (the review's inference that a raw frame addressed to the proxy could be routed onto the egress
  network; `fwd_probe.py`, then `live_fwd.sh`, `live-fwd.txt`). From a client with Docker's default set, one UDP frame
  at a time, each addressed to a dual-homed container's MAC, and a listener on `ragbench-rf-egress`. The stand-in,
  a container on both networks with forwarding on (1, the default), counted the frame for its own address on
  `ragbench-rf-net` (`InReceives` and `InDelivers` +1, so the frames are well made), but not one for its own address
  on the egress network, nor one for the listener; the proxy (forwarding 0) counted nothing either, and the
  listener got nothing. So the engine drops, on the internal bridge, every frame whose destination is outside
  `10.231.47.0/27`, before any container's IP layer sees it (inferred: Docker's rules for an internal network,
  which this setup cannot read). The path is closed twice, then: by the engine, and by no container holding
  `CAP_NET_RAW`; the proxy's sysctls are a third guard, kept since they cost nothing.
- H3's gateway lines with the new verdict, from the client without `NET_RAW` (4 min 17 s): `--block` `:443` and `:1`
  errno 113; `scan connected: none`, `scan refused: none`, `ok   scan 10.231.47.1: no port answered (errno 113
  3908, timeout 61627)`; then `ok   arp 10.231.47.1: unresolved, nothing on the bridge answers for it`. The control,
  an internal network without the option (`10.231.47.32/27`): `FAIL block 10.231.47.33:1` (refused), `FAIL scan
  10.231.47.33: 65532 port(s) answered, so a host holds this address (connected 2: 111 46425; refused 65530)` and
  `FAIL arp 10.231.47.33: resolved by a host`, exit 1 each. Under the old rule that gateway would have failed only on
  its two listeners.

**What it leaves as it was.** What listens on 111 and 46425 is still not identified; the stack just cannot reach
it. The proxy is also on `ragbench-rf-egress`, a normal bridge whose gateway is its route out, so it can still reach
the engine's address there, 111 and 46425 included; it runs Squid alone (uid 584792, no effective capabilities, its
setuid ICMP helper off), whose rules let a client CONNECT to `openrouter.ai:443` and nothing else, refusing IP
literals before anything else and private destinations; only a client that took over Squid itself could reach the
engine from there. That is the one way left to the engine's listeners, and H0 puts it before the owner. H3 checks the
option, the seven containers' capabilities, a packet socket refused in the server and the runner, IPv6 off, the
proxy's forwarding off, and scans the gateway address again: any port that answers, or a neighbour entry that
resolves, stops the run.

### The Elasticsearch mapping

**Why.** The hosted model returns 4096 numbers, so RAGFlow stores each vector in `q_4096_vec` (`"q_%d_vec" %
len(v)`, `rag/flow/tokenizer/tokenizer.py:124`). v0.27.3's `conf/mapping.json` has `dense_vector` templates for
`*_512_vec`, `*_768_vec`, `*_1024_vec` and `*_1536_vec` only (`conf/mapping.json:160-203`), and none of its other
templates matches that name, so Elasticsearch 8.11 would decide the field by its own dynamic mapping (PREMISES §6).
The owner did not accept relying on that (2026-11-09), so the build declares it.

**The file the server reads.** Each Elasticsearch connection reads `os.path.join(get_project_base_directory(),
"conf", "mapping.json")` once, when its process starts (`common/doc_store/es_conn_base.py:38-51`), and `create_idx`
sends that file's `settings` and `mappings` as they are (`:120-127`). The task executor calls it before a tenant's
first chunks are stored, after binding the embedder (`rag/svr/task_executor_refactor/task_handler.py:223-229`,
`:307-313`, on the refactored path that runs, «## TEI wait patch»; the legacy path the same way,
`rag/svr/task_executor.py:1504`, `:744-747`). `get_project_base_directory()` is the folder above `common/` unless
`RAG_PROJECT_BASE` or `RAG_DEPLOY_BASE` is set (`common/file_utils.py:22-42`). Neither is set: not in the image's
environment (`docker image inspect` of the pin), not in `docker/` or the Dockerfile, not in `compose.yaml` or the
overlay, and not among the secrets file's 12 names (`.hq/scratch/w2-run/state/prepare.json`, p2_secrets; the file
was not opened). The code is `COPY common common` and `COPY conf conf` under `WORKDIR /ragflow` (Dockerfile:275,
:301, :307). So the file is `/ragflow/conf/mapping.json`, and the overlay mounts the copy there, read-only.

**The copy.** `patch_es_mapping.py write` (H1) refuses any source but the pinned image's file (sha256
`49877a9153c466479ce75a81e5da49e952567ca9c3cb1d46e2b20c2a6bab8097`; copied out of the pin on 2026-11-09, byte for
byte the source tree copy's, `.hq/scratch/w2-stage5/build/logs/mapping-src-from-image.txt`). It finds the
`*_1536_vec` block by its exact eleven lines and inserts after it the same lines with `*_1536_vec` and `1536`
changed to `*_4096_vec` and `4096`: the same name (`dense_vector`), keys, order and options (`type` `dense_vector`,
`index` true, `similarity` `cosine`). It checks the result twice, as text (the source's lines and the block, nothing
else) and as JSON (the same settings, mappings and templates in the same order, but the one, right after
`*_1536_vec`), and checks that the new template is the first one that would take `q_4096_vec` and that no property
names it. It writes `mapping.json` (sha256 `136b31a0d07b89116e814c99562ecfacbb52aee66ea91e12bf24ba0c4174ef90`, lines
204-214 added, nothing removed), `mapping.diff` and `mapping-patch.json` (`logs/patch-es-mapping-write.txt`; GNU
`patch` applies the diff to the image's file and gives the copy byte for byte, `logs/patch-es-mapping-check.txt`).
`check --copy` verifies a copy: that sha256, and the template's shape, place and precedence. H3 runs it in the
server, against `/ragflow/conf/mapping.json`.

**Seen live, 2026-11-09** (`.hq/scratch/w2-stage5/build/live_es.sh`, `logs/live-es.txt`; every container and
network `ragbench-rf-st-*`, removed afterwards):
- The pinned server image's own Python (3.13.11), network none, read-only, the copy mounted as the overlay mounts
  it: `RAG_PROJECT_BASE` and `RAG_DEPLOY_BASE` unset, the file `ESConnectionBase` reads is
  `/ragflow/conf/mapping.json`, and it holds `*_512_vec`, `*_768_vec`, `*_1024_vec`, `*_1536_vec` and `*_4096_vec`;
  `patch_es_mapping.py check --copy /ragflow/conf/mapping.json` there (H3's command) ends `ES MAPPING OK`. The
  control, the image without the mount, gets two `BAD` lines and `ES MAPPING NOT APPROVED`.
- Elasticsearch 8.11.3 from the pinned digest (`58a3a280…292a`), single node, security off (no secret), on an
  internal network with no published port, and a client beside it. Each body was sent as `create_idx` sends it (one
  `PUT /<index>` with `settings` and `mappings`).
  - The patched body: all 20 templates stored, the five `dense_vector` ones in order, the last `*_4096_vec` with
    `{"dims": 4096, "index": true, "similarity": "cosine", "type": "dense_vector"}`. One document with 4096 floats in
    `q_4096_vec`: the field reads back exactly that, and a kNN search on it finds the document.
  - The template decides: 3 floats in another field it matches, `x_4096_vec`, are refused («has a different number
    of dimensions [3] than defined in the mapping [4096]»), and the field stays unmapped.
  - The shipped body: 19 templates, no `*_4096_vec`. The same 3 floats in `x_4096_vec` are mapped by Elasticsearch
    itself, as `float`; the 4096 floats in `q_4096_vec`, by its dynamic mapping, as the same `dense_vector`, dims
    4096, cosine, indexed.

**What it changes.** For this model, nothing in the field's mapping: Elasticsearch 8.11.3's own dynamic mapping gives
`q_4096_vec` the same four settings (seen above). What changes is who decides: RAGFlow's file, as for the
512/768/1024/1536 sizes, so a vector of another length, or another dynamic-mapping rule, can no longer give the
field another mapping without failing. The hosted server's one departure from the image as shipped is this file
(it runs the shipped `embedding_model.py`, without the TEI-wait patch); the network option is the stack's, not the
image's.

### The tools

- **`register_hosted.py`** (runner; its docstring cites every route). `register` adds the provider `OpenRouter`,
  creates the instance by name only, then stores the key and the model with `verify: false`, so no call reaches
  OpenRouter (`provider_api_service.py:460-465`). The key is in that one body. It writes `hosted-embedder.json`:
  factory, instance, model, `embedding_model` (`<model>@<instance>@OpenRouter`), base URL, `max_tokens` 32768,
  provider order, `verify` false, the owner's data-policy note, and of the key only its length and a salted sha256.
  `--provider-order nebius` (owner decision, PREMISES §8 item 2; off by default) sends the key as the JSON text
  `{"api_key", "provider_order"}`, made in memory, so RAGFlow adds `provider {order, allow_fallbacks: false}` to
  every request (`rag/llm/embedding_model.py:1528-1548`). `smoke` makes the one paid check call through
  `POST /providers/OpenRouter/connection`, nothing stored. Refused before sending: a key file missing, empty, of two
  lines, with a byte-order mark or not one OpenRouter key; an instance name RAGFlow refuses, or `default`; a model
  that is not an OpenRouter id; an empty or multi-line note; a provider order that is not slugs; an existing record;
  a non-loopback URL. A provider already added stops it (the stack is fresh; registration is not re-run).
- **`rf_ingest.py --embedder hosted`** (the docstring's hosted paragraph): `create`, `dump` and `all` take
  `--embedding-model` and `--hosted-record` instead of `--tei-wait-patch`, which is refused. `W2_EMBEDDER` must say
  hosted; preflight sends nothing to TEI; the record is checked (version, factory, base URL, `verify` false, an
  instance that is not `default`, `embedding_model` = model@instance@factory, a note) and must name the very
  `--embedding-model`; `dump` refuses a record other than the one `create` kept. The manifest has
  `embedder {name, revision null, via "hosted-openrouter"}` and `hosted_embedder` (model, instance, factory,
  base_url, provider_order, data_policy) in place of `tei_wait_patch`. The canvas, the upload set, the settle rule,
  the dump and its checks are the built-in mode's, and so is the gate: the Tokenizer embeds the chunker's text and
  stores it unchanged (`rag/flow/tokenizer/tokenizer.py:99-124`), so `predict_chunks.py`, `w2_check.py` and ALL
  MATCH stand as they are. The built-in mode is unchanged (its 76 tests unchanged and passing).
- **`net_check.py`**: `--proxy`, `--tunnel host:port` (CONNECT answered 200, then a TLS handshake verified for that
  host; nothing sent after it; the positive control through the proxy) and `--tunnel-refused host:port` (the proxy
  must answer 403; a 200 or any other status, such as a 503 when the rules let it through and the connection beyond
  failed, is a `FAIL`). The direct `--reach`/`--block` lines are as before. `--scan IP` (with `--scan-ports`,
  default every port) tries a TCP connection to every port of one address, each socket closed as it opens, nothing
  sent: the count of each outcome, the ports that connected, were refused and timed out, then its verdict. The
  address must be silent: only a timeout, «no route to host» (errno 113) and «network unreachable» (101) pass
  (`ok   scan <IP>: no port answered (…)`). A port that accepts a connection, and one that refuses it, are a `FAIL`
  (exit 1), since a refusal is a host's answer: a gateway that came back with nothing listening would refuse every
  port and pass a rule that fails only listeners (stage 5 review). Any other error is a `FAIL` too: that port was not
  shown silent. H3 scans the gateway address with it («The gateway»).
- **`patch_es_mapping.py`** (host, then the server): `write --source <the image's conf/mapping.json> --out <folder>`
  writes the copy with the `*_4096_vec` template, its diff and `mapping-patch.json` (`file`, `source_sha256`,
  `patched_sha256`, `inserted_lines`, `after_template`, `template`, `field`); it refuses any source but the pinned
  v0.27.3 file, a CR byte or non-UTF-8 text, a `*_1536_vec` block found other than once, a source that already names
  `*_4096_vec`, an earlier template or a property that would take `q_4096_vec`, a result that is not the source
  and the block (checked as text and as JSON), and an `--out` that is a file, not empty without `--replace`, holds a
  foreign entry or the source. `check --copy <file>` prints one line for the sha256 (the approved copy's,
  `136b31a0…ef90`) and one for the template (shape, place, precedence), then `ES MAPPING OK: <file>` (exit 0) or
  `ES MAPPING NOT APPROVED: …` (exit 1); a file it cannot read exits 2. Standard library, Python 3.9 or later
  (the server's is 3.13). «The Elasticsearch mapping» says why.
- **`key_leak_check.py`** (runner): reads the key from its mount, searches every file under `--scan` and the
  `--stdin` stream for the whole key and each of its 16-character pieces, and prints counts and paths only. With
  `--registration` it first checks the key against the record's salted sha256, so it cannot pass by searching for
  another key. Exit 1 when it finds any, 2 when the check is incomplete: a file it could not read, a `--scan` that
  read no file, or a `--stdin` stream of 0 bytes or of fewer than `--min-bytes`, which the runbook takes from a count
  of the same stream made just before, so that an empty, failed or cut-short `docker logs` is never a pass. A key
  found outranks an incomplete check. It finds bytes as they are, not a key re-encoded (base64, URL or UTF-16).
- **`score_w1.py`** reads a hosted manifest under `.hq/scratch/w2-hosted/out/<engine>/` only, prints the hosted
  embedder in the «W2 manifest» table, and never decides (`../ragflow-w1/README.md`, «Own runs (W2)»).

### Runbook H (owner, then the main agent)

Git Bash on this machine, as P and E. Stop at the first check that fails. The W2 stack must be gone (F) before H2.

**H0. Owner steps, before H1.**
1. Credits: a positive balance on the account (the minimum purchase and fees are on the credits page; not checked
   here).
2. The data-policy switches above: privacy (Save changes, reload), observability, the guardrail assigned to the key,
   its «Eligibility preview» showing only «Nebius | qwen/qwen3-embedding-8b».
3. The key: dedicated, limit $2, no reset, short expiry; written to the key file without the key on a command line.
   Copying it puts it on the Windows clipboard, so first, in Settings → System → Clipboard, turn off the sync
   across devices (it would upload the key to Microsoft) and preferably «Clipboard history». Then copy the key and,
   in PowerShell, `Get-Clipboard | Set-Content -NoNewline -Encoding ascii -Path
   C:\Users\accou\.ragbench-rf\openrouter.key` (ASCII: no byte-order mark). Then, on the same settings page, «Clear
   clipboard data», so that no copy stays in the clipboard history.
4. The decisions, written down for the main agent:
   - (a) the provider, Nebius (recommended) or DeepInfra, matching the guardrail; H1 checks its ZDR entry.
   - (b) whether `register_hosted.py` adds `--provider-order nebius`. **Recommended: yes**, as a second,
     request-level pin beside the guardrail: every request then carries `provider {order: [nebius],
     allow_fallbacks: false}`. Its slug is not verified (`nebius` is read from the endpoint tag `nebius/bf16`), but a
     wrong slug can only make the calls fail, never route them elsewhere, since no fallback is taken (PREMISES §2);
     the smoke call or the first parse would show it.
   - (c) whether the one smoke call is approved.
   - (e) the residual retention at OpenRouter above.

   (d) and (f) are no longer the owner's to accept (owner, 2026-11-09: not accepted, fixes built instead), and
   their letters are kept so that (e) keeps its own. (d), Elasticsearch's own mapping of 4096-dimension vectors:
   the server reads a copy of `conf/mapping.json` that declares `*_4096_vec` (H1 writes it, H3 checks it in the
   server, H5 reads it back from the live index; «The Elasticsearch mapping»). (f), the gateway's listeners:
   `ragbench-rf-net` has no IPv4 address on the Docker side, and no container on it holds `CAP_NET_RAW`, so the
   engine's IPv6 link-local address on the bridge, where 111 still answered a raw frame (stage 5 review), is out of
   reach too. H3 checks the option, the capabilities of all seven containers, a packet socket refused in the server
   and the runner, IPv6 off on the stack's interface, and every port of `10.231.47.1` silent with the address
   unresolved; any answer stops the run («The gateway»).

   **For the owner to know before H1** (no fix is built for it, so if it is not acceptable, say so and the run does
   not start): the proxy itself stays on `ragbench-rf-egress`, a normal bridge whose gateway is its route out to
   openrouter.ai, and from there it can reach the same engine listeners, 111 and 46425, on that gateway's address.
   Only Squid runs in that container (uid 584792, no capabilities, its setuid ICMP helper off, forwarding off), and
   its rules let a client CONNECT to `openrouter.ai:443` and nothing else, IP literals and private addresses refused
   («The gateway», «What it leaves as it was»). A client of the stack could reach those listeners only by taking
   over Squid itself.

   **The owner's answers, 2026-11-09** (AskUserQuestion): (a) Nebius; (b) yes, `--provider-order nebius`; (c) the
   one smoke call approved; (e) the residual retention accepted; the proxy's reach to 111 and 46425 above accepted.
   The privacy switches of step 2 are account-wide, so they bind every key on the account: the stakeholder demo was
   moved to a free model that does not train on prompts for that reason (owner, same day).
5. One line for the record, the data-policy note H4 passes, for example: «owner set 2026-11-09: training off,
   ZDR only (All other models), guardrail qwen/qwen3-embedding-8b on Nebius only, $2 budget; observability off».

**H1. Variables, folders, pins and pulls.**

```bash
set -o pipefail
export MSYS_NO_PATHCONV=1 RF_WS="D:/Iqraa Law" RF_DOC_ENGINE=elasticsearch
T="D:/Iqraa Law/AI Harness-w1/tools/ragflow-w2"; RUN="D:/Iqraa Law/.hq/scratch/w2-run"
HR="D:/Iqraa Law/.hq/scratch/w2-hosted"; HEAVY="/d/Iqraa Law/.hq/scratch/heavy.sh"; PINS="$HR/state/pins.vars"
CF=(-f "$T/compose.yaml" -f "$T/compose.hosted.yaml" --project-directory "$T" --env-file "$PINS")
PROVIDER=Nebius                     # H0 (a), as OpenRouter writes it: Nebius or DeepInfra
[ -s "$RUN/state/secrets-path.txt" ] && export RF_SECRETS="$(cat "$RUN/state/secrets-path.txt")"   # P2's file; if gone, run P2
mkdir -p "$HR/state" "$HR/out/elasticsearch" "$HR/logs"
docker ps -a --format '{{.ID}} {{.Names}}' | sort > "$HR/state/before-containers.txt"
docker volume ls --format '{{.Name}}' | sort > "$HR/state/before-volumes.txt"
docker network ls --format '{{.ID}} {{.Name}}' | sort > "$HR/state/before-networks.txt"
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | sort > "$HR/state/before-images.txt"
grep -c 'ragbench-rf-' "$HR"/state/before-*.txt                                     # 0 for each file
docker network ls -q | xargs docker network inspect --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}} {{end}}' \
  | grep -F '10.231.47.' || echo "subnet 10.231.47.0/27 free"
[ -s /c/Users/accou/.ragbench-rf/openrouter.key ] && echo "key file present (not opened)"
ls "$RUN/in"/*.md | wc -l; sha256sum "$RUN/canvas/indexing-pipeline.json" "$RUN/in/upload-manifest.json"
# the pins: W2's own digests (the same server, stores and runner), and the squid digest the self-tests ran; no tag
# is read again (valkey/valkey:8 and ubuntu/squid:7.2-26.04_edge move)
{ for v in RF_PIN_RAGFLOW RF_PIN_ES RF_PIN_MYSQL RF_PIN_MINIO RF_PIN_VALKEY RF_PIN_PYTHON; do
    grep -m1 "^$v=sha256:[0-9a-f]\{64\}$" "$RUN/state/pins.vars" || echo "$v=MISSING"; done
  echo "RF_PIN_SQUID=sha256:041c64dd14c81548023c9532e4c2fac487e9a3f9f490913b50547d2974722025"
  echo "RF_EMBEDDING_BATCH_SIZE=16"
  echo "RF_OPENROUTER_KEY_FILE=C:/Users/accou/.ragbench-rf/openrouter.key"
  echo "RF_ES_MAPPING_DIR=$HR/es-mapping"          # written below, after the pull, by patch_es_mapping.py
  # compose.yaml is interpolated whole before the overlay drops TEI: these three are set, and nothing uses them
  echo "RF_PIN_INFINITY=sha256:$(printf '0%.0s' $(seq 64))"; echo "RF_PIN_TEI=sha256:$(printf '0%.0s' $(seq 64))"
  echo "RF_TEI_REVISION=$(printf '0%.0s' $(seq 40))"; echo "RF_TEI_WAIT_DIR=not-used-by-the-hosted-run"
} > "$PINS"; cat "$PINS"
while read -r name want; do got=$(sed -n "s/^$name=//p" "$PINS")
  [ "$got" = "$want" ] && echo "same      $name" || echo "DIFFERENT $name: $got, expected $want"
done <<'EOF'
RF_PIN_RAGFLOW sha256:4ab74ec388e2d897419e01518a516e9386e5ff812587a1025e6f6a407b2ad067
RF_PIN_ES sha256:58a3a280935d830215802322e9a0373faaacdfd646477aa7e718939c2f29292a
RF_PIN_MYSQL sha256:d58ac93387f644e4e040c636b8f50494e78e5afc27ca0a87348b2f577da2b7ff
RF_PIN_MINIO sha256:29a498b24669cae1fed11c1a2fb2b3d73c68829a0a9c0b14e71b386671d38fac
RF_PIN_VALKEY sha256:8f836008e0986c36adf50da714c7060cf689dbb335f61fe077939d90fa650809
RF_PIN_SQUID sha256:041c64dd14c81548023c9532e4c2fac487e9a3f9f490913b50547d2974722025
RF_PIN_PYTHON sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
EOF
docker compose "${CF[@]}" --profile es --profile hosted config --services          # names only, no values
bash "$HEAVY" docker compose "${CF[@]}" --profile es --profile hosted pull          # by digest; only what F removed
docker images --digests | grep -E 'ragflow|elasticsearch|mysql|silo|valkey|squid|python'
# the Elasticsearch mapping («The Elasticsearch mapping»): the pinned image's own file, and the copy with *_4096_vec
SRC="$HR/mapping-src"
if [ -e "$SRC" ] || [ -e "$HR/es-mapping" ]; then
  echo "STOP: $SRC or $HR/es-mapping exists: look at them; to run this step again, remove both folders first"
else
  mkdir -p "$SRC"
  docker create --name ragbench-rf-mapping-src "infiniflow/ragflow@$(sed -n 's/^RF_PIN_RAGFLOW=//p' "$PINS")" >/dev/null
  docker cp ragbench-rf-mapping-src:/ragflow/conf/mapping.json "$SRC/mapping.json"
  docker rm ragbench-rf-mapping-src
  printf '%s  %s\n' 49877a9153c466479ce75a81e5da49e952567ca9c3cb1d46e2b20c2a6bab8097 "$SRC/mapping.json" | sha256sum -c - \
    && python -I -B "$T/patch_es_mapping.py" write --source "$SRC/mapping.json" --out "$HR/es-mapping"
fi
cat "$HR/es-mapping/mapping.diff"
python -I -B "$T/patch_es_mapping.py" check --copy "$HR/es-mapping/mapping.json"
grep "^RF_ES_MAPPING_DIR=" "$PINS"
# the model's endpoints and OpenRouter's ZDR list, both public (no key sent), kept as fetched
curl -fsS --proto '=https' https://openrouter.ai/api/v1/endpoints/zdr -o "$HR/state/zdr-on-the-day.json"
curl -fsS --proto '=https' https://openrouter.ai/api/v1/models/qwen/qwen3-embedding-8b/endpoints \
  -o "$HR/state/model-endpoints-on-the-day.json"
python -I -c '
import json, sys
zdr_path, eps_path, chosen = sys.argv[1:4]
zdr = {(r["provider_name"], r["tag"]): r for r in json.load(open(zdr_path, encoding="utf-8"))["data"]
       if r["model_id"] == "qwen/qwen3-embedding-8b"}
eps = json.load(open(eps_path, encoding="utf-8"))["data"]["endpoints"]
for e in eps:
    z = zdr.get((e["provider_name"], e["tag"]))
    print(e["provider_name"], e["tag"], e["quantization"], e["pricing"]["prompt"],
          "ZDR safety_retention %s" % z["safety_retention"] if z else "NOT on the ZDR list")
mine = [e for e in eps if e["provider_name"] == chosen]
good = bool(mine) and all(zdr.get((e["provider_name"], e["tag"]), {}).get("safety_retention") is False for e in mine)
print(("ok   %s: %d endpoint(s), each on the ZDR list without safety retention" if good else "STOP %s: %d endpoint(s), not all on the ZDR list without safety retention") % (chosen, len(mine)))
' "$HR/state/zdr-on-the-day.json" "$HR/state/model-endpoints-on-the-day.json" "$PROVIDER" | tee "$HR/state/zdr-on-the-day.txt"
```

Check: 0 ours before; the subnet free; the key file present (its size is read by H3 inside the runner); 22 files,
the canvas `3f0fcb62…588d` and the upload manifest `b0737632…6bc1` (P6, the W2 run); no `MISSING` pin and seven
`same` lines (the `ragbench-rf-*` digests are W2's, from `$RUN/state/pins.vars`, and the squid one the self-tests');
the services es01, mysql, minio, redis, proxy, ragflow, runner and no TEI; each pinned digest present in `docker
images --digests`. The mapping: no `STOP` line (a `STOP` means `$HR/mapping-src` or `$HR/es-mapping` is already
there, and nothing is copied or written: look at both, and to run the step again remove both folders first; the
block was run twice offline, the second time changing nothing, `.hq/scratch/w2-stage5/fix/snippets/h1-guard-test.txt`);
`docker create` starts nothing and `docker rm` removes it; `sha256sum` prints `OK`
(the image's file, read on 2026-11-09), and only then does the tool write; it prints `lines 204-214: the *_4096_vec template …` and the patched
sha256 `136b31a0d07b89116e814c99562ecfacbb52aee66ea91e12bf24ba0c4174ef90`; the diff adds those eleven lines after
the `*_1536_vec` block and removes none; `check` ends `ES MAPPING OK`; the pins file names `$HR/es-mapping` (from
here on the server cannot start without it; `config` and `pull` above run before the folder exists, and accept it,
`.hq/scratch/w2-stage5/build/logs/h1-order-missing-mapping-dir.txt`). The endpoint lines list every provider that serves the model, each with its ZDR entry (on
2026-11-09: Nebius `nebius/bf16 bf16 0.00000001`, DeepInfra and SiliconFlow, all three `ZDR safety_retention False`,
PREMISES §2-§3), and the last line is `ok   Nebius: 1 endpoint(s), each on the ZDR list without safety retention`
(the provider of H0 (a)). A `STOP` line, or an endpoint of that provider at another price or quantization: stop and
ask the owner. Another provider `NOT on the ZDR list` is recorded, not a stop: the guardrail's provider allowlist
keeps it out (PREMISES §2, the layer that binds). The join was checked against the premises' copies of both lists
and three altered copies (`.hq/scratch/w2-stage4/fix2/runbook-snippets/endpoints-check.txt`). Anything else: stop.

**H2. Up.**

```bash
docker network ls --format '{{.Name}}' | grep -E '^ragbench-rf-' && echo "STOP: a ragbench-rf network exists (F first)"
bash "$HEAVY" docker compose "${CF[@]}" --profile es --profile hosted up -d
docker compose "${CF[@]}" --profile es --profile hosted ps -a --format '{{.Name}} {{.State}} {{.Health}}'
```

Check: repeat `ps` until `ragbench-rf-server` is `running healthy` (start period 300 s); `ragbench-rf-proxy`
`running`; no `ragbench-rf-tei`. A subnet clash fails `up` before anything starts.

**H3. Isolation, proxy and key checks.**

```bash
set -o pipefail                                                                                 # as H1: the «pipeline exit» lines need it
docker network inspect ragbench-rf-net --format '{{.Internal}} {{range .IPAM.Config}}{{.Subnet}} {{.Gateway}}{{end}} {{index .Options "com.docker.network.bridge.inhibit_ipv4"}}'   # true 10.231.47.0/27 10.231.47.1 true
docker network inspect ragbench-rf-egress --format '{{.Internal}} {{range .Containers}}{{.Name}} {{end}}'   # false ragbench-rf-proxy
for c in ragbench-rf-server ragbench-rf-es01 ragbench-rf-mysql ragbench-rf-minio ragbench-rf-redis ragbench-rf-proxy; do
  echo "$c: $(docker inspect $c --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}')"; done
docker ps --format '{{.Names}} {{.Ports}}' | grep '^ragbench-rf-' | grep -- '->'                 # prints nothing
# no process on ragbench-rf-net may send a frame of its own making («The gateway», «IPv6 and raw frames»): CAP_NET_RAW
# dropped in all seven (Docker's record, and the bounding set a new process in each gets: bit 13 clear), a packet
# socket refused in the server and in the runner (each has its own capabilities), IPv6 off on the stack's interface
for c in ragbench-rf-server ragbench-rf-runner ragbench-rf-es01 ragbench-rf-mysql ragbench-rf-minio ragbench-rf-redis ragbench-rf-proxy; do
  B=$(docker exec "$c" cat /proc/self/status | awk '$1 == "CapBnd:" {print $2}')
  echo "$c $(docker inspect -f 'drop={{.HostConfig.CapDrop}} add={{.HostConfig.CapAdd}} privileged={{.HostConfig.Privileged}}' "$c") CapBnd=${B:-unread}"
  [ -n "$B" ] && [ $(( 0x$B >> 13 & 1 )) = 0 ] && echo "ok   $c: no CAP_NET_RAW" || echo "FAIL $c: CAP_NET_RAW held, or not read"
done
NORAW='import socket
try:
    socket.socket(socket.AF_PACKET, socket.SOCK_RAW).close()
except PermissionError:
    print("ok   AF_PACKET refused (EPERM): no raw frames from here")
else:
    raise SystemExit("FAIL AF_PACKET opened: this container can send raw frames")'
docker exec ragbench-rf-server python3 -I -c "$NORAW"; echo "server exit $?"
docker exec ragbench-rf-runner python3 -I -c "$NORAW"; echo "runner exit $?"
docker exec ragbench-rf-server cat /proc/sys/net/ipv6/conf/eth0/disable_ipv6 /proc/net/if_inet6 | awk 'NR == 1 {d = $1; next} {n++; if ($6 != "lo") bad = 1}
END {if (d == "1" && n == 1 && !bad) print "ok   IPv6 off on eth0, only ::1 on lo"; else {print "FAIL IPv6: eth0 disable_ipv6 " d ", " n " address(es)"; exit 1}}'; echo "pipeline exit $?"
docker exec ragbench-rf-proxy cat /proc/sys/net/ipv4/ip_forward /proc/sys/net/ipv4/conf/all/forwarding   # 0 and 0: no routing between its two networks
docker exec ragbench-rf-server printenv COMPOSE_PROFILES HTTPS_PROXY https_proxy NO_PROXY LLM_TIMEOUT_SECONDS EMBEDDING_BATCH_SIZE MAX_CONCURRENT_TASKS
docker exec ragbench-rf-server sh -c 'for v in HTTP_PROXY http_proxy ALL_PROXY all_proxy; do printenv $v >/dev/null && echo "SET $v"; done; echo done'
docker inspect ragbench-rf-server --format '{{range .Mounts}}{{.Destination}} {{end}}'          # /w2 /in /canvas /ragflow/conf/mapping.json and the image's own
docker exec ragbench-rf-server sha256sum /ragflow/rag/llm/embedding_model.py                    # c2e46e1c…0536, as shipped
docker inspect ragbench-rf-server --format '{{range .Mounts}}{{if eq .Destination "/ragflow/conf/mapping.json"}}{{.Source}} rw={{.RW}}{{end}}{{end}}'
docker exec ragbench-rf-server /ragflow/.venv/bin/python -I -B /w2/patch_es_mapping.py check --copy /ragflow/conf/mapping.json
docker exec ragbench-rf-server sh -c 'test -e /keys/openrouter.key && echo "STOP: key in the server" || echo "no key file in the server"'
docker inspect ragbench-rf-runner --format '{{range .Mounts}}{{if eq .Destination "/keys/openrouter.key"}}{{.Source}} rw={{.RW}}{{end}}{{end}}'
docker exec ragbench-rf-runner sh -c 'wc -c < /keys/openrouter.key'                               # 73 or 74 (or 75 with CRLF)
docker inspect ragbench-rf-server ragbench-rf-runner ragbench-rf-proxy ragbench-rf-es01 ragbench-rf-mysql ragbench-rf-minio ragbench-rf-redis \
  | docker exec -i ragbench-rf-runner python3 -I -B /w2/key_leak_check.py --key-file /keys/openrouter.key --stdin docker-inspect; echo "pipeline exit $?"
docker exec ragbench-rf-server sh -c 'cat /proc/[0-9]*/environ 2>/dev/null' \
  | docker exec -i ragbench-rf-runner python3 -I -B /w2/key_leak_check.py --key-file /keys/openrouter.key --stdin server-processes-environ; echo "pipeline exit $?"
GW=$(docker network inspect ragbench-rf-net --format '{{range .IPAM.Config}}{{.Gateway}} {{end}}' | awk '{print $1}')   # 10.231.47.1: pinned, held by no interface
PUB=$(docker ps --format '{{.Ports}}' | tr ',' '\n' | sed -n 's/^ *0\.0\.0\.0:\([0-9][0-9]*\)->.*/\1/p' | head -1)
echo "gateway: ${GW:-none listed by IPAM}; a port another container publishes: ${PUB:-none, 80 is used}" | tee "$HR/state/gateway.txt"
GWB=(); [ -n "$GW" ] && GWB=(--block "$GW:443" --block "$GW:${PUB:-80}" --block "$GW:1")   # :1, closed: a refusal there is a host
docker exec ragbench-rf-runner python3 -I -B /w2/net_check.py --reach 127.0.0.1:9380 --reach ragbench-rf-es01:9200 \
  --reach ragbench-rf-proxy:3128 --block 1.1.1.1:443 --block openrouter.ai:443 --block huggingface.co:443 \
  --block pypi.org:443 --block host.docker.internal:443 "${GWB[@]}" --proxy ragbench-rf-proxy:3128 --tunnel openrouter.ai:443 \
  --tunnel-refused huggingface.co:443 --tunnel-refused pypi.org:443 --tunnel-refused 1.1.1.1:443 \
  --tunnel-refused host.docker.internal:443 --tunnel-refused ragbench-rf-mysql:3306 --tunnel-refused openrouter.ai:80 \
  --tunnel-refused www.openrouter.ai:443 --timeout 10 | tee "$HR/logs/net-check.txt"
# the gateway address, every TCP port, nothing sent (about 4 to 5 minutes): no interface holds it, so nothing may
# answer; a port that connects or refuses (or any error but silence) is a FAIL line and exit 1, and the run stops;
# then, at once, the neighbour table: the address unresolved, so no host on the bridge answered ARP for it, whatever
# the protocol (UDP included) («The gateway»)
docker exec ragbench-rf-runner python3 -I -B /w2/net_check.py --reach 127.0.0.1:9380 --block "$GW:443" --block "$GW:1" \
  --scan "$GW" | tee -a "$HR/state/gateway.txt"; echo "pipeline exit $?"
docker exec ragbench-rf-runner cat /proc/net/arp | awk -v gw="$GW" '$1 == gw {n++; if ($3 == "0x0" && $4 == "00:00:00:00:00:00") u++}
END {if (n == 1 && u == 1) print "ok   arp " gw ": unresolved, nothing on the bridge answers for it"; else {print "FAIL arp " gw ": " (n ? "resolved by a host" : "no entry (read it right after the scan)"); exit 1}}' \
  | tee -a "$HR/state/gateway.txt"; echo "pipeline exit $?"
# the proxy's log: every line not one the runbook expects is printed (define unexpected() again in a new shell)
unexpected() { awk '$3 == "CONNECT" && $4 == "openrouter.ai:443" && $5 == 200 && $6 == "TCP_TUNNEL" {next}
  $3 == "CONNECT" && $5 == 403 && $6 ~ /^TCP_DENIED(_ABORTED)?$/ && $4 ~ /^((huggingface\.co|pypi\.org|1\.1\.1\.1|host\.docker\.internal|www\.openrouter\.ai|raw\.githubusercontent\.com):443|ragbench-rf-mysql:3306|openrouter\.ai:80)$/ {next}
  $3 == "-" && $4 == "error:transaction-end-before-headers" && $6 == "NONE_NONE" {next}
  {print "UNEXPECTED " $0}' "$@"; }
docker exec ragbench-rf-proxy cat /var/log/squid/access.log > "$HR/logs/proxy-access-h3.log"; echo "copy exit $?"
awk '{print $3, $4, $5, $6}' "$HR/logs/proxy-access-h3.log" | sort | uniq -c
unexpected "$HR/logs/proxy-access-h3.log"                                                      # prints nothing
docker logs ragbench-rf-server 2>&1 | grep -c 'Super user initialized'                          # 1
docker logs ragbench-rf-server 2>&1 | grep -m1 'log levels:'                                   # root DEBUG, openai INFO, peewee WARNING
```

Check: the networks as commented (`ragbench-rf-net` internal, its subnet and gateway pinned, and the option
`inhibit_ipv4` `true`), the server on `ragbench-rf-net` only and the proxy on both; no port. Each of the seven
containers prints `drop=[CAP_NET_RAW] add=[] privileged=false CapBnd=00000000a80405fb` (Docker's default bounding
set, `a80425fb`, without bit 13; the strings seen live on 2026-11-09 on the five containers started from the compose
files, the stores and the proxy, `.hq/scratch/w2-stage5/fix/live/live-fix.txt`; the server and the runner were not
started, and the overlay gives them the same `cap_drop`, so H3 is the first sight of theirs)
and `ok   <container>: no CAP_NET_RAW`; the packet socket prints `ok   AF_PACKET refused (EPERM): no raw frames
from here`, then `server exit 0`, and the same with `runner exit 0`; IPv6 prints `ok   IPv6 off on eth0, only ::1 on
lo` and `pipeline exit 0`; the proxy's two values are `0` and `0`. A `FAIL` line, an `unread` bounding set, another
exit, or a proxy value of `1`: stop; a process on the network could send frames of its own making, which reached the
engine's port 111 over IPv6 («The gateway», «IPv6 and raw frames»).
`printenv` gives `elasticsearch,cpu,metadata-mysql`, the proxy twice, the `NO_PROXY` list, `60`, `16`, `1`; the second
line prints only `done`. No mount at `/ragflow/rag/llm/embedding_model.py` or `/patch`, and the module's sha256 is
the shipped `c2e46e1cb5d128122a48b8283d135b81321441655dbd9c22c9ecd8035a6c0536` (P9). The mapping is bound from
`…/w2-hosted/es-mapping/mapping.json` with `rw=false`, and the check, in the server's own Python, prints two `ok`
lines (the sha256 `136b31a0…ef90`; the template) and ends `ES MAPPING OK: /ragflow/conf/mapping.json`: the bind was
made when the container was created, before any process in it started, so every Elasticsearch connection read
this file (H5 reads the result back from the live index). The key file is absent from
the server and bound read-only (`rw=false`) into the runner. Both leak checks end `NO KEY FOUND`, each followed by
`pipeline exit 0` (a container missing from `docker inspect`, or a stream of 0 bytes, is not a pass): the key is in
no container's configuration or environment and in no process environment of the server. Every gating `net_check`
line is `ok`: the direct lines blocked, `tunnel openrouter.ai:443 … TLS verified`, every `refused … CONNECT 403`.
The gateway lines (`--block 10.231.47.1:…`: 443, the published port and 1) are `ok` with errno 113 or `timed out`; a
refusal fails them, since only a host refuses. The gateway scan prints `scan connected: none`, `scan refused: none`
and `ok   scan 10.231.47.1: no port answered (…)`, then `pipeline exit 0`: on 2026-11-09 every port timed out or had
no route to host, errno 113 («The gateway»). The neighbour table then prints `ok   arp 10.231.47.1: unresolved,
nothing on the bridge answers for it` and `pipeline exit 0`. A `FAIL scan` or `FAIL arp` line, a port in `scan
connected` or `scan refused`, or another exit: stop, and tell the owner; the network is not what
compose.hosted.yaml builds.
The proxy's log, read with `docker exec` (not `docker logs`), is not empty, and the tally
shows only: `CONNECT openrouter.ai:443 200 TCP_TUNNEL` (H3's own tunnel); `CONNECT <host> 403 TCP_DENIED` (or
`TCP_DENIED_ABORTED`) once for each of H3's seven refusals; one `- error:transaction-end-before-headers 0 NONE_NONE`
from the reach probe of `ragbench-rf-proxy:3128`; and up to two `CONNECT raw.githubusercontent.com:443 403
TCP_DENIED`, the LiteLLM library's fetch of its price list at import, which then falls back to its bundled copy
(in W2 this fetch, failing on DNS, was the only outbound attempt either full server log names:
`.hq/scratch/w2-run/logs/server-elasticsearch-full.log`, `server-infinity-full.log`; here it meets the proxy
instead: inferred, not seen). `unexpected` prints nothing. Anything else, or a missing or empty log: stop;
the CONNECT lines are the run's record of what left the stack. The runner shares the server's network namespace,
so both appear in the log under the same client address.

**H4. The RAGFlow key, the registration and (only if approved) the smoke call.**

```bash
set -o pipefail
docker exec -i ragbench-rf-server /ragflow/.venv/bin/python -I -B /w2/make_key.py \
  | docker exec -i ragbench-rf-runner sh -c 'umask 077 && cat > /run/rf/key && test -s /run/rf/key' && echo "key stored in the runner's tmpfs"
docker exec ragbench-rf-runner python3 -I -B /w2/rf_ingest.py preflight --engine elasticsearch --embedder hosted
POLICY="<H0 step 5, one line>"
docker exec ragbench-rf-runner python3 -I -B /w2/register_hosted.py register --model qwen/qwen3-embedding-8b \
  --instance w2or --data-policy "$POLICY" --out /out/elasticsearch | tee "$HR/logs/register.txt"   # + --provider-order nebius if H0 (b)
# only if H0 (c) approved the one paid check call (same --provider-order as register):
docker exec ragbench-rf-runner python3 -I -B /w2/register_hosted.py smoke --model qwen/qwen3-embedding-8b | tee "$HR/logs/smoke.txt"
# the server's log, checked as a stream (nothing on disk yet): only from a running server, and never shorter than a
# count of the same stream made just before (a failed or cut-short docker logs is not a pass)
[ "$(docker inspect -f '{{.State.Running}}' ragbench-rf-server)" = true ] && echo "server running" || echo "STOP: the server is not running"
N=$(docker logs ragbench-rf-server 2>&1 | wc -c); echo "server log: $N bytes"
docker logs ragbench-rf-server 2>&1 | docker exec -i ragbench-rf-runner python3 -I -B /w2/key_leak_check.py \
  --key-file /keys/openrouter.key --registration /out/elasticsearch/hosted-embedder.json --stdin server-log \
  --min-bytes "$N"; echo "pipeline exit $?"
docker exec ragbench-rf-proxy cat /var/log/squid/access.log | tail -3
```

Check: every preflight line `ok`, with `embedder: hosted; no TEI on this stack` and 0 datasets; `register` prints
three `ok` lines and `wrote hosted-embedder.json: the dataset's embedding_model is
qwen/qwen3-embedding-8b@w2or@OpenRouter`. The smoke call, if made, prints `ok   smoke: …`; its tunnel adds one
`TCP_TUNNEL` line for `openrouter.ai:443` once it closes (the server's client may keep it open, so the line can come
later); a 400 means OpenRouter refuses RAGFlow's `drop_params` (PREMISES §4) and
the run stops there (the OpenAI-compatible factory, Path B, is not built). A 401, 402, 403 or 404 means the key,
the credits, the guardrail or its allowlist (PREMISES §2): fix it on openrouter.ai, then tear down and start again,
since registration is not re-run on a used stack. `server running`; the leak check reads at least `$N` bytes and
ends `NO KEY FOUND`, then `pipeline exit 0`.

**H5. Predict, ingest, and the live mapping check.**

```bash
O="$HR/out/elasticsearch"
docker exec ragbench-rf-server /ragflow/.venv/bin/python -B /w2/predict_chunks.py \
  --canvas /canvas/indexing-pipeline.json --in-dir /in > "$O/predicted-chunks.jsonl" 2> "$O/predict-summary.txt"
cmp "$O/predicted-chunks.jsonl" "$RUN/out/elasticsearch/predicted-chunks.jsonl" && echo "the W2 prediction, byte for byte"
grep -c ' repeated texts 0$' "$O/predict-summary.txt"                                            # 22
bash "$HEAVY" docker exec ragbench-rf-runner python3 -I -B /w2/rf_ingest.py all --engine elasticsearch --embedder hosted \
  --embedding-model qwen/qwen3-embedding-8b@w2or@OpenRouter --hosted-record /out/elasticsearch/hosted-embedder.json \
  --canvas /canvas/indexing-pipeline.json --in-dir /in --upload-manifest /in/upload-manifest.json \
  --out /out/elasticsearch | tee "$HR/logs/ingest.txt"
# after the ingest (or in a second shell once a progress line reads «done 1» or more): the live mapping, through the server
docker exec ragbench-rf-server /ragflow/.venv/bin/python -I -B -c "import base64,json,os,urllib.request as u; r=u.Request('http://ragbench-rf-es01:9200/ragflow_*/_mapping/field/q_*_vec', headers={'Authorization': 'Basic ' + base64.b64encode(('elastic:' + os.environ['ELASTIC_PASSWORD']).encode()).decode()}); d=json.load(u.build_opener(u.ProxyHandler({})).open(r, timeout=30)); [print(i, f, json.dumps(m['mapping'][f], sort_keys=True)) for i, v in d.items() for f, m in v['mappings'].items()]" | tee "$HR/logs/es-vector-mapping.txt"
# the same index's vector templates, as Elasticsearch stored them when create_idx sent the mounted file
docker exec ragbench-rf-server /ragflow/.venv/bin/python -I -B -c "import base64,json,os,urllib.request as u; r=u.Request('http://ragbench-rf-es01:9200/ragflow_*/_mapping', headers={'Authorization': 'Basic ' + base64.b64encode(('elastic:' + os.environ['ELASTIC_PASSWORD']).encode()).decode()}); d=json.load(u.build_opener(u.ProxyHandler({})).open(r, timeout=30)); [print(i, 'template', n, t['match'], json.dumps(t['mapping'], sort_keys=True)) for i, v in d.items() for e in v['mappings'].get('dynamic_templates', []) for n, t in e.items() if t.get('match', '').endswith('_vec')]" | tee "$HR/logs/es-vector-templates.txt"
```

Check: the prediction is W2's byte for byte (same image, canvas and files), 22 files with `repeated texts 0`. The
ingest ends `wrote <n> chunks to chunks.jsonl and w2-manifest.json …`, after `settled 22`; its log holds `hosted
embedder: qwen/qwen3-embedding-8b@w2or@OpenRouter at https://openrouter.ai/api/v1 …`. **The stop rule:** the
chunk index (`ragflow_<tenant>`) lists five vector templates, `*_512_vec`, `*_768_vec`, `*_1024_vec`, `*_1536_vec`
and `*_4096_vec`, the last `{"dims": 4096, "index": true, "similarity": "cosine", "type": "dense_vector"}`: the index
was made from the mounted copy, so the declared template, not Elasticsearch's own mapping, decided the field («The
Elasticsearch mapping»). And the field mapping prints `q_4096_vec` with exactly those four settings. A missing
`*_4096_vec` template (the index was made from another body), a `float` type, or another field: no query runs. A document that fails names its cause in the progress line (an embedding error is the provider's
answer); `--max-reparse` parses it again at most twice, which costs a few more tokens.

**H6. The gate.**

```bash
python -I -B "$T/w2_check.py" --predicted "$O/predicted-chunks.jsonl" --dumped "$O/chunks.jsonl" \
  --manifest "$O/w2-manifest.json" --ingest-state "$O/ingest-state.json"
python -I -c "import json,sys; m=json.load(open(sys.argv[1],encoding='utf-8')); print(m['all_match'], m['chunk_count'], m['embedder'], m['hosted_embedder'], m['embedding_batch_size'], m['max_concurrent_tasks'], 'tei_wait_patch' in m)" "$O/w2-manifest.json"
```

Check: `ALL MATCH` and 6,612 chunks, as W2; the manifest line ends `16 1 False` after the hosted embedder as
registered. Anything else: stop.

**H7. The two arms, v3 and rt.** As E7, with the hosted paths, and the server's log checked for the key before it
is saved to disk:

```bash
DS=$(python -I -c "import json,sys; print(json.load(open(sys.argv[1]))['dataset_id'])" "$O/w2-manifest.json")
docker exec ragbench-rf-runner sha256sum /w1/run_w1.py /pkg/w1-queries.jsonl
for arm in v3 rt; do
  extra=(); [ "$arm" = rt ] && extra=(--vector-similarity-weight 0.4)
  T0=$(docker exec ragbench-rf-runner date -u +%Y-%m-%dT%H:%M:%SZ)
  bash "$HEAVY" docker exec ragbench-rf-runner python3 -I -B /w2/timed_run.py --log "/out/elasticsearch/run-$arm.log" -- \
    python3 -I -B /w1/run_w1.py --base-url http://127.0.0.1:9380 --api-key-file /run/rf/key --dataset "$DS" \
    --queries /pkg/w1-queries.jsonl --out "/out/elasticsearch/w2-results-$arm.jsonl" "${extra[@]}" || echo "STOP: arm $arm exited non-zero"
  [ "$(docker inspect -f '{{.State.Running}}' ragbench-rf-server)" = true ] || echo "STOP: the server is not running"
  N=$(docker logs --timestamps --since "$T0" ragbench-rf-server 2>&1 | wc -c)
  docker logs --timestamps --since "$T0" ragbench-rf-server 2>&1 | docker exec -i ragbench-rf-runner python3 -I -B \
    /w2/key_leak_check.py --key-file /keys/openrouter.key --stdin "server-log-$arm" --min-bytes "$N" \
    && docker logs --timestamps --since "$T0" ragbench-rf-server > "$HR/logs/server-$arm.log" 2>&1
  python -I -B "$T/fallback_items.py" --results "$O/w2-results-$arm.jsonl" --server-log "$HR/logs/server-$arm.log" \
    --run-log "$O/run-$arm.log" --out "$O/w2-fallback-$arm.json"
done
```

Check: as E7 (the sha256 values, 160 rows per arm, `fallback_items.py` exit 0), no `STOP` line, and each arm's
stream check `NO KEY FOUND`, over at least `$N` bytes, before its log is written: under `set -o pipefail` (H4) a
failed `docker logs` or an incomplete check leaves the log unwritten, and `fallback_items.py` then stops on the
missing file. Each query is one embedding call through the proxy.

**H8. Score (exploratory).**

```bash
S="D:/Iqraa Law/AI Harness-w1/tools/ragflow-w1/score_w1.py"
for arm in v3 rt; do
  bash "$HEAVY" python -X utf8 -I "$S" --results "$O/w2-results-$arm.jsonl" --own-run --manifest "$O/w2-manifest.json" \
    --out-dir "$O/score-$arm" --fallback "$O/w2-fallback-$arm.json" | tee "$HR/logs/score-$arm.txt"
done
```

Check: each prints `own run (W2): elasticsearch, qwen/qwen3-embedding-8b (hosted: OpenRouter instance w2or), …` and
`not the deciding cell: the embedder is hosted …`. Never pass `--w2-decide`: it is refused.

**H9. The leak check and the record.**

```bash
set -o pipefail
# 1. while the server runs: its whole log as a stream, and every file saved so far, for the key; then its token count
[ "$(docker inspect -f '{{.State.Running}}' ragbench-rf-server)" = true ] && echo "server running" || echo "STOP: the server is not running"
N=$(docker logs ragbench-rf-server 2>&1 | wc -c); echo "server log: $N bytes"
docker logs ragbench-rf-server 2>&1 | docker exec -i ragbench-rf-runner python3 -I -B /w2/key_leak_check.py \
  --key-file /keys/openrouter.key --registration /out/elasticsearch/hosted-embedder.json --scan /hr --stdin server-log \
  --min-bytes "$N" | tee "$HR/logs/key-leak-check.txt"; echo "pipeline exit $?"
docker logs ragbench-rf-server 2>&1 | grep -o 'used_tokens: [0-9]*' | awk '{n++; s += $2} END {print n " calls, " s " tokens"}' \
  | tee "$HR/logs/used-tokens.txt"
# 2. stop the server, so that every tunnel its client kept open closes and is logged; then the proxy's log, once
docker stop --timeout 30 ragbench-rf-server
docker exec ragbench-rf-proxy cat /var/log/squid/access.log > "$HR/logs/proxy-access.log"; echo "copy exit $?"
awk '{print $3, $4, $5, $6}' "$HR/logs/proxy-access.log" | sort | uniq -c | tee "$HR/logs/proxy-access-tally.txt"
unexpected "$HR/logs/proxy-access.log"                                                         # prints nothing (H3 defines it)
# 3. the proxy's log too, the one file saved after step 1
docker exec ragbench-rf-runner python3 -I -B /w2/key_leak_check.py --key-file /keys/openrouter.key \
  --scan /hr/logs/proxy-access.log | tee "$HR/logs/key-leak-check-proxy-log.txt"
```

Check: `server running`; the first leak check reads at least `$N` bytes of the server's log and every saved file of
the hosted folder, and ends `NO KEY FOUND`, then `pipeline exit 0`. `used-tokens.txt` holds the calls and tokens
RAGFlow logged (`LLMBundle.encode` and `encode_queries`, `api/db/services/llm_service.py:219`, `:247`): one call per
embedding request at batch size 16, the 22 file names and the 320 queries included. After `docker stop` (it prints
`ragbench-rf-server`) and `copy exit 0`, the tally holds H3's lines (above), the smoke call's tunnel if it was made,
and the embedding calls' `CONNECT openrouter.ai:443 200 TCP_TUNNEL` lines: one per tunnel, not per call, since the
client reuses a tunnel. `unexpected` prints nothing; any line it prints: stop and show it to the owner before H10
(the copy stays in `$HR/logs`). The proxy log's own check ends `NO KEY FOUND` (the runner shares the stopped server's
network namespace, but it reads files only; should it not answer, record that: the proxy saw no more than the CONNECT
line). `used-tokens.txt` and `proxy-access-tally.txt`, written after the first scan, hold only counts that grep and
awk cut from those logs, so neither can hold the key. A `KEY FOUND`: stop, keep the stack, and tell the owner to revoke the key at once.

**H10. Teardown, and the check that nothing that existed before is gone.**

```bash
# what the engine destroys while the teardown runs, subscribed to first (its replay buffer rolls within minutes here)
docker events --filter event=destroy --format '{{.Type}} {{.Actor.Attributes.name}}' > "$HR/state/destroyed-during-teardown.txt" & EV=$!
docker compose "${CF[@]}" --profile es --profile hosted down --volumes --remove-orphans --timeout 30
docker ps -a --format '{{.Names}}' | grep -E '^ragbench-rf-' | xargs -r docker rm -f
docker network ls --format '{{.Name}}' | grep -E '^ragbench-rf-' | xargs -r docker network rm
docker volume ls --format '{{.Name}}' | grep -E '^ragbench-rf-' | xargs -r docker volume rm
kill "$EV"; sort "$HR/state/destroyed-during-teardown.txt" | uniq -c
docker ps -a --format '{{.ID}} {{.Names}}' | sort > "$HR/state/after-containers.txt"
docker volume ls --format '{{.Name}}' | sort > "$HR/state/after-volumes.txt"
docker network ls --format '{{.ID}} {{.Name}}' | sort > "$HR/state/after-networks.txt"
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | sort > "$HR/state/after-images.txt"
for k in containers volumes networks images; do
  echo "== $k that existed before and are gone:"; comm -23 "$HR/state/before-$k.txt" "$HR/state/after-$k.txt"
  echo "== $k of ours left:"; grep -E '(^| )ragbench-rf-' "$HR/state/after-$k.txt"
done
grep -E ' ragbench-rf-(net|egress)$' "$HR/state/after-networks.txt" || echo "both networks removed, the egress one included"
grep -x ragbench-cargo "$HR/state/after-volumes.txt"
```

Check: every «of ours left» list empty; `both networks removed, the egress one included`; `ragbench-cargo` still
listed. `down` is scoped by the compose project `ragbench-rf` and needs both files so that it knows the proxy and the
egress network; every other command matches `^ragbench-rf-`. Every «gone» list empty, or holding only names that do
not start with `ragbench-rf-`: this Docker engine also runs other projects, which create and remove their own
objects while ours run (stage 5's reviews saw `rp-0-1-rv-*`, `recall-mx-*` and `magento-pim85` objects come and go
during their own runs, removed by name only, `.hq/scratch/w2-stage5/review-security/rv_fix.log`, `rv_fix_d.log`; its
fixes saw `forge-pim85*`, `rp-1-1-*` and randomly named containers go, some come back under new IDs, and three
foreign containers destroyed within the few seconds one throwaway container ran,
`.hq/scratch/w2-stage5/fix/live/live-fix.txt`, `events-subscription-test.txt`). No command here can remove such an
object, so record it and do not stop; the sorted list printed after `kill` is what the engine destroyed while the
teardown ran (ours are the `ragbench-rf-*` lines; the engine does not say who removed the others). Read it from the
subscription, not with `--since`: a replay of a run's 21-minute window, begun 7 minutes after it ended, came back empty
(`events-live-fix.txt`). A `ragbench-rf-*` name among the «gone» cannot occur, since H1 found none before: if one does, stop.
The pulled images, the squid one included, are removed as F says, by digest, only if the owner agrees.

**Then the owner, on openrouter.ai** (nothing after the run checks the provider otherwise: RAGFlow logs only the
token count of each call, not which provider served it, `rag/llm/embedding_model.py:1544-1550`):
1. The Activity page (or its logs) for this key: every row shows the provider of H0 (a), Nebius, and the model
   `qwen/qwen3-embedding-8b`, and the number of rows is about the call count in `used-tokens.txt` (a request the
   openai client retried, or one that failed, adds a row; the smoke call is one). **Any row with another provider or
   model: the run did not keep to its data policy.** Record it as non-compliant in the run record, with the rows,
   and tell the main agent. The page was not seen by an agent, so its column names may differ.
2. The spend beside the token sum in `used-tokens.txt` (at $0.01 per million tokens, about $0.009 expected).
3. Disable or delete the key, and delete the key file. Clear the clipboard data again if the key was copied since H0.

### What this does not prove, and what is not settled

- **Nothing here has run against RAGFlow or OpenRouter.** The provider routes are read from the v0.27.3 source and
  tested against the fake (`tests/fake_ragflow_w2.py`); H4 is their first live use.
- **`drop_params`.** RAGFlow's OpenRouter client always sends `drop_params: true`, which OpenRouter's embeddings
  schema does not list; only the smoke call or the first parse shows whether it is accepted (PREMISES §4). The
  OpenAI-compatible factory (Path B) is not built.
- **The request-level pin's slug.** `--provider-order nebius` assumes `nebius` is the provider slug OpenRouter's
  `provider.order` takes (the endpoint's tag is `nebius/bf16`); not verified. The guardrail binds either way.
- **4096 dimensions** are declared by the mounted mapping's `*_4096_vec` template, at Elasticsearch 8.11's ceiling
  for `dims` (PREMISES §6). That template, the copy in the pinned server image's Python and the field in a pinned
  Elasticsearch were seen live, but not yet in a RAGFlow server creating its own index: H3's check and H5's two
  read-backs are the stop rules.
- **The server's boot without TEI.** `TEI_MODEL` and `TEI_HOST` stay in the server's environment (the overlay merges
  it), unused because every use is gated on «tei-» in `COMPOSE_PROFILES`; and the boot-time tenant gets no default
  embedding model, so nothing embeds at boot. Both are read from the source, not seen; H2's health check is the
  first sight.
- **The proxy, live, only in self-tests.** Its log, its `src` ACL from the egress side and a tunnel logged at its
  close were seen (above); the refusal of the gateway address as a client was not, and now cannot be, since no
  interface holds that address («The gateway»). Stage 5 saw it serve `CONNECT openrouter.ai:443` (200) and refuse
  `huggingface.co:443` (403) on the network as the overlay now builds it, and its review's fixes saw the same with
  `CAP_NET_RAW` dropped, forwarding off and the ICMP helper off (`.hq/scratch/w2-stage5/fix/live/live-fix.txt`,
  step 5). The LiteLLM price-list fetch through the
  proxy at boot is inferred from W2's log, not seen; H3 lists it as expected and stops on anything else.
- **The gateway.** What listens on 111 and 46425 on the Docker engine's side is still not identified; it is out of
  the stack's reach, seen on a network the overlay built, with a control network beside it where both still answer
  («The gateway»). Over IPv4 that rests on Docker 29.9.1 honouring `inhibit_ipv4`; over IPv6 (the bridge's
  link-local address, where 111 still answers) on no container holding `CAP_NET_RAW` and every container's eth0
  having IPv6 off. The capabilities were seen on the stores and the proxy started from the compose files, and in
  the server image's own interpreters, not on a running server or runner; H3 checks all of it on the day, on the
  stack itself. Nothing in the server needs `CAP_NET_RAW` (its entrypoint starts nginx and Python, and nothing in it
  pings; read from the source, `docker/entrypoint.sh`): H2's health check is the first sight of the server
  without it. The W2 stacks (`compose.yaml` alone, unchanged) kept Docker's default capabilities, so the same raw
  path was most likely open there (inferred, not tested).
- **The proxy's own reach.** From its namespace on `ragbench-rf-egress`, the engine's listeners are still reachable
  at that network's gateway; only Squid's rules and its unprivileged user stand between a client and them (H0, «For
  the owner to know»). H3 does not try that address through the proxy: its rule `deny !openrouter` refuses every IP
  literal before any other, as the self-tests saw (`1.1.1.1:443` and openrouter.ai's own address refused 403).
- **Which provider served the calls** is known only from OpenRouter's Activity page, which the owner reads after the
  run (H10). The guardrail's provider allowlist binds before it, and `--provider-order` (H0 (b)) adds a pin on every
  request; neither leaves a trace in the stack.
- **The tokenizer and the cost.** The 8B's tokenizer is assumed to be the 0.6B's; the cost is an estimate.
- **The owner's settings** cannot be checked by an agent; the guardrail's «Eligibility preview» is the owner's check.
