# ragflow-w1

Tools for test W1 in `.hq/docs/specs/spec-rag-system.md` («The decisive test», Part 2). Walid runs our 80
frozen retrieval queries through his own RAGFlow retrieval and returns the ranked results, and we score them
against our search. The owner, not an agent, sends anything to Walid. No agent contacts his server, or asks
for or holds his key. Python standard library only.

## make_package.py — what we send

It writes the package the owner sends Walid into one folder. The default folder is
`.hq/docs/specs/w1-for-walid/` beside the repository (`D:/Iqraa Law/.hq/docs/specs/w1-for-walid/`).

| File | What it holds |
|---|---|
| `w1-queries.jsonl` | Line 1 is a header: `{"set": "retrieval-v1", "w1": 1, "count": 80, "fields": ["query", "question"], "note": ...}`. Then 80 lines `{"id", "query", "question"}` in eval-set order. Nothing else from the eval set is written: no `expected`, `law`, `expected_notes` or `notes`. The ids are the eval set's own, so they still name each item's law (`civil-code-01`) and mark the six memorandum items (`civil-code-memo-NN`). No article number or note is written. |
| `run_w1.py` | A byte-for-byte copy of the `run_w1.py` beside `make_package.py`. |
| `SHA256SUMS` | The sha256 of both files, in `sha256sum` format, so `sha256sum -c SHA256SUMS` checks them. |

The owner sends only `w1-queries.jsonl` and `run_w1.py`, and keeps `SHA256SUMS` to check the returned file's
header. By email, the two files go in one .zip, or by link: Outlook blocks `.py` attachments (Microsoft,
«Blocked attachments in Outlook»). Zipping keeps the bytes, so the hashes still match. Zip the two files, not
the folder, which also holds the owner's note.

```bash
# Windows, Git Bash
cd "/d/Iqraa Law/AI Harness-w1/tools/ragflow-w1"
python make_package.py              # first build
python make_package.py --replace    # rebuild, for example after run_w1.py changed
# WSL
cd "/mnt/d/Iqraa Law/AI Harness-w1/tools/ragflow-w1" && python3 make_package.py
```

| Option | Meaning |
|---|---|
| `--eval PATH` | The eval set. Default: this repository's `content/eval/retrieval-v1.jsonl`. |
| `--out DIR` | The package folder. Its parent must exist. Default: as above. |
| `--runner PATH` | The `run_w1.py` to copy. Default: the one beside `make_package.py`. |
| `--replace` | Overwrite the three package files if they are already in `--out`. |
| `--allow-other-set` | Package an eval set that is not the frozen 80-item set. Only for tests or a later set. |

Exit codes: `0` written; `1` failed while writing; `2` refused before anything was written.

**What it refuses (exit 2, nothing written):**

- an eval set it cannot read: not UTF-8, a line that is not a JSON object, an item without a non-empty `id`,
  `query` or `question`, or a duplicate id;
- a set that is not the frozen one, unless `--allow-other-set`. The check is the set fingerprint, which must
  be `870ce8df5335…` (spec, «The decisive test»), plus a count of 80. The fingerprint is computed as
  `legal_search.evalset` computes it: the sha256 of the item lines, header excluded;
- a missing or empty `run_w1.py`;
- an `--out` that is a file, or whose parent folder is missing;
- any of the three package files already in `--out`, unless `--replace`.

**How it writes:**

- `--replace` overwrites only the three package files. Any other file in the folder, such as
  `message-for-walid.md`, is left as it is, and its name is printed.
- Files are written as bytes: UTF-8 with LF line ends and no BOM. Text mode on Windows would write CRLF, and
  the hashes would then not match what Walid receives.
- Each file is written under a temporary name and then renamed into place. `SHA256SUMS` is written last,
  after the two files have been read back and their hashes checked.
- Terminal output is ASCII, with non-ASCII escaped, so a cp1252 console cannot fail on an Arabic path.

On 2026-11-08 the sha256 of `w1-queries.jsonl` built from the frozen set was
`e0669ca06e6fb0f0cee1fcec1c0ee08cbaf7dc3e70aa05d136934a425294737c`. It changes only if the eval set or the
header note changes.

**Tests** (`tests/test_make_package.py`, 23 tests; they write only to temporary folders and use a stand-in
`run_w1.py`). The command runs every test in `tests/`, this file's and the other tools':

```bash
cd "/d/Iqraa Law/AI Harness-w1/tools/ragflow-w1" && python -B -X utf8 -m unittest discover -s tests -t . -v
```

- **The real set.** Item keys are exactly `id`, `query` and `question`. Ids and texts equal the eval set, in
  its order, and the header is as above. No gold key, notes text or source path appears. No expected article
  number appears unless the item's own query or question already holds it.
- **Planted gold.** A stand-in set carries marker strings in `expected`, `law`, `expected_notes` and `notes`.
  None of them reaches the package.
- **The files.** `SHA256SUMS` matches both files, `run_w1.py` is copied byte for byte, and the queries file is
  UTF-8 with LF and no BOM.
- **The refusals above,** and that `--replace` leaves other files alone.
- **A line separator inside a text.** A stand-in item holds U+2028 and U+2029. Its line stays one line under
  `str.splitlines()`, which `run_w1.py` uses to read the file.
- **Each check was shown to be tested.** Each check below was removed, and a test failed every time. The
  first eight were removed in a copy of the code; the U+2028 escaping was replaced by plain `json.dumps` at
  run time:
  - copying whole items;
  - one space in `SHA256SUMS`;
  - the `--replace` check;
  - the runner check;
  - the frozen-set check;
  - text-mode writes;
  - raw terminal output;
  - creating the folder before the checks;
  - escaping U+2028 and U+2029.

  Two checks have no test: the read-back of the written files, and the count of 80 (the fingerprint check
  already refuses any other set).

## The W1 flow, end to end

1. **The package.** It was built into `.hq/docs/specs/w1-for-walid/` on 2026-11-08, and the note
   `message-for-walid.md` there holds both hashes. Whenever `run_w1.py` changes, rebuild with
   `make_package.py --replace`, check that the `w1-queries.jsonl` line in `SHA256SUMS` still equals the value
   in the note, and copy the new `run_w1.py` line into it.
2. **The owner sends it.** The owner, not an agent, sends `w1-queries.jsonl` and `run_w1.py` with the Arabic
   text in `message-for-walid.md`, in one .zip by email. First comes the safe path's step 1: Walid's agreement
   and the rights terms, which the lawyer reads (Q-4). R6 (Walid intake and Part 2) is gated on Q-4. Either
   the lawyer has read the terms, or the owner records on purpose that Walid's reply is the agreement.
3. **Walid runs it** on his own machine, against his own RAGFlow, with a key he creates for this run and
   deletes afterwards. He runs three commands:
   - `--list-datasets`;
   - `--dry-run`;
   - the run itself, on law-text datasets only.

   The script sends `POST /api/v1/retrieval` one query at a time (`api/apps/restful_apis/chunk_api.py:393`
   in RAGFlow v0.27.3), plus reads of the dataset list and the version. It follows no redirect and writes
   `w1-results.jsonl` on his machine. He sends back that one file, with a line declaring its type, its rights
   status and whether it holds client data (safe path, step 2).
4. **The owner receives it: intake, then the screen.** Save the file outside every repository and do not
   open it. The options are in `python -I intake_w1.py --help` and its docstring.
   - **Intake.** `python -I intake_w1.py --file <file> --handover-id <slug> --client-data-declared no --rights
     "<his words>"` checks the file against the W1 contract. It prints counts, line numbers and key names
     only, never text: that is the metadata check and pattern count that step 4 allows an agent. The file
     lands in `.hq/quarantine/ragflow-export/<handover-id>/` with a manifest (safe path, step 3).
   - The header's `queries_sha256` and `script_sha256` must equal `SHA256SUMS`. If they differ, he ran
     something other than what was sent.
   - **The screen.** The owner or the lawyer screens the file before anything else opens it (step 4), and
     records it with `intake_w1.py --record-screening`. `score_w1.py` scores only a file whose screen is
     recorded as clear.
   - A return in any other shape cannot go through intake. It goes to the same folder by hand, with a
     hand-written manifest, and is not the frozen test.
5. **Score.** The results are scored against our search under the spec's W1 mapping rule and decision
   rule (c).
   - **The mapping rule.** A chunk counts as retrieving an article only when it holds at least half of that
     article's normalised tokens, in order. Scoring uses an equal served-text budget: his top chunks, up to
     the characters A1 serves in its top 5 for the same item. Items on a law his corpus lacks are reported
     separately, not as failures.
   - **Decision rule (c).** The `query` field is scored first, and the `question` field separately. Each is
     compared with our best arm on the same field.
   - **The results never become library material.** They are used only for scoring, stay in quarantine, are
     never ingested, and are deleted when the agreement says (REQ-RAG-047).

## run_w1.py — the script Walid runs

One file, Python 3.9 or later, standard library only: nothing to install. Walid runs it on his own machine,
against his own RAGFlow. It sends the queries in `w1-queries.jsonl` to his retrieval one at a time, and
writes the ranked chunks to one file, `w1-results.jsonl`, which he sends back. It is about 560 lines, and he
should read it before running it. He does not get this README: the script's docstring, which `--help`
prints, says what it sends, what it writes and what each exit code means, and `--help` gives each
option's default.

### What it sends

| Request | When | Key sent? | What it carries |
|---|---|---|---|
| `POST /api/v1/retrieval` | once per item and field: 160 by default | yes | the query or question text, the dataset ids, the settings below |
| `GET /api/v1/datasets?id=<id>` | once per `--dataset`, before the first query | yes | the dataset id |
| `GET /api/v1/system/version` | once, before the first query | **no** | nothing. RAGFlow serves it without login (v0.27.3 `system_api.py:44`; v1.0.0-rc3 `router.go:158`) |

`--list-datasets` sends only `GET /api/v1/datasets?page=N&page_size=30`. `--dry-run` sends nothing.

These are the only requests the script can make. `ROUTES` lists them, and `Client.call` refuses any other
method, path or query key before anything leaves the machine.

### What it never does

- **The key.** It reads the key only from a file holding the key alone, on one line, and sends it only in the
  `Authorization: Bearer` header of the requests above. It never prints, logs or writes the key. It
  removes the key and any Bearer token from a server message it shows, and the key from the results file,
  should a server echo it. A refusal does not repeat the `--api-key-file` path, which could be the key typed
  by mistake, and a `ragflow-` key typed as an unknown option is masked in argparse's message.
- **Other addresses.** It follows no redirect: a redirect stops the run. It uses no proxy, whatever the
  environment or the system settings say. It refuses `http://` unless the host is `localhost` or a loopback
  address, or `--allow-insecure-http` is given. Other `*.localhost` names do not count: Windows asks DNS for
  them. It cannot turn certificate checks off, and a certificate error stops the run without a retry. Use
  `--ca-file` for a private certificate.
- **Changes on the server.** It uploads, edits and deletes nothing. RAGFlow keys have no read-only scope,
  so this rests on the script, not on the key: Walid should create a key for this run and delete it after.
- **Model calls it can avoid.** `keyword`, `use_kg`, `toc_enhance`, `highlight` and `cross_languages` are
  sent switched off, and no reranker is used unless `--rerank-id` is given. Each query is still embedded
  once by the dataset's embedding model, as every RAGFlow search is. If that model is a paid API, the run
  makes 160 small embedding calls.
- **Response bodies.** It never prints a body. On an error it shows the code and the server's message on
  screen, cut at 200 characters, with the key removed. The results file keeps only the code and its
  `RetCode` name, as `code 100 (exception); the message was shown on screen only`. RAGFlow answers an
  exception with `repr(e)` as the message (v0.27.3 `api_utils.py:152`, reached from `chunk_api.py:601-604`),
  and an embedding backend's error can name hosts or addresses on his network. The same holds for the
  header's `ragflow_version_note`.
- **Overwriting.** It refuses an `--out` that exists, or whose `.partial` exists.
- **Gold.** It refuses a queries file whose items hold anything but `id`, `query` and `question`. Expected
  articles and notes cannot travel with it.

### The settings, and how they follow his canvas

The defaults reproduce the Retrieval node of his canvas «IQRA LAW – FINAL REVIEW v3», read from the
export on 2026-11-08. Its node holds top_n 20, similarity_threshold 0.2, keywords_similarity_weight 0.7,
rerank_candidates_count 64 and an empty rerank_id, and it has no top_k. The mapping is the one RAGFlow
v0.27.3's agent tool applies (`agent/tools/retrieval.py:214-223`).

| Option | Default | Sent as | From the canvas |
|---|---|---|---|
| `--page-size` | 20 | `page_size`, with `page` 1 | top_n 20 (`retrieval.py:214-215`) |
| `--similarity-threshold` | 0.2 | `similarity_threshold` | 0.2 (`:216`) |
| `--vector-similarity-weight` | 0.3 | `vector_similarity_weight` | 1 − keywords_similarity_weight 0.7 (`:217`) |
| `--top-k` | 1024 | `top_k` | absent, so the tool's default 1024 (`:89`, `:218`) |
| (fixed) | 64 | `rerank_candidates_count` | 64 (`:223`) |
| `--rerank-id` | none | `rerank_id`, only when given | empty |
| (fixed) | off | `keyword`, `use_kg`, `toc_enhance`, `highlight` false; `cross_languages` [] | off or absent |

- **Why `top_k`.** v0.27.3 reads it, logs that it is deprecated, and prefers `knn_top_k` when both are sent
  (`chunk_api.py:498-502`). v1.0.0-rc3 takes it as an alias (`dataset_types.go:52`). Older versions know
  only `top_k`.
- **Limits checked before sending (exit 2).**
  - `--page-size` must be 1 to 64. The server refuses `page` × `page_size` above `rerank_candidates_count`
    (`chunk_api.py:519`), and its REST maximum is 100 (`pagination_utils.py:19`).
  - `--similarity-threshold` and `--vector-similarity-weight` must be 0 to 1, and `--top-k` 1 to 2048, as
    rc3 checks (`dataset.go:1282-1318`).
- **Twenty chunks should cover the scoring budget.** His indexing pipeline appears to make one article per
  chunk (`walid-ragflow-agents-2026-11-07.md` §3.3, read from code, not measured), and the scorer cuts his
  list at the characters our top 5 articles serve.

**What the HTTP API cannot reproduce from his canvas.** The scorer must know these:

1. **The search text.** His canvas builds it in Python: ArticleLawMapper, TaskResolver and QueryBuilder
   give «المادة N» or «<question> | <law>». W1 sends our frozen `query` or `question` text unchanged.
2. **The law filter.** His node filters on `law_name` = the resolver's output (`meta_data_filter`,
   manual). It is not sent: per item it would need the law, which only our gold holds. W1 searches every
   law in the datasets given.
3. **The dense-only fallback.** His agent passes `allow_dense_fallback=False` (`retrieval.py:228`).
   `POST /api/v1/retrieval` does not pass it (`chunk_api.py:553-571`), so the default `True` applies
   (`rag/nlp/search.py:737`). When the hybrid search finds nothing, the API then runs a dense-only search
   (`search.py:350-391`). W1 can therefore return chunks where his agent would return none.
4. **The rest of his canvas** is not retrieval and is not run: the per-article loop, the joiner, the
   answering model, citations, and Retrieval TEST's query rewriter.

The rest is the same on both paths: page 1, the threshold, the weights, top_k, the candidate count, and
the tag rank feature `label_question` (`retrieval.py:222`, `chunk_api.py:567`).

### Running it (for Walid)

**Before running.**

- Create an API key for this run only, in RAGFlow under avatar > API. Put it alone in a text file outside
  any shared folder.
- Use your server's https address.
- Put `run_w1.py` and `w1-queries.jsonl` in one folder.

**Three steps.**

1. **`--list-datasets`** prints your datasets: id, name, counts, embedding model and chunk method. It
   prints them on your screen only, and writes nothing. It is the first step that contacts the server, so
   it tests the address and the key.
2. **`--dry-run`** checks the inputs only: the options, the key file, the queries file and `--out`. It prints
   the first request body and sends nothing, so it does not test the server or the key.
3. **The run.** Pick law-text datasets only, never one holding client files. Several `--dataset` options
   are allowed, but they must share one embedding model (RAGFlow refuses otherwise, `chunk_api.py:427`).

```text
# Windows (PowerShell or cmd), in the folder holding run_w1.py
python -I run_w1.py --base-url https://ragflow.example.org --api-key-file C:\keys\ragflow-w1.key --list-datasets
python -I run_w1.py --base-url https://ragflow.example.org --api-key-file C:\keys\ragflow-w1.key --dataset YOUR_DATASET_ID --dry-run
python -I run_w1.py --base-url https://ragflow.example.org --api-key-file C:\keys\ragflow-w1.key --dataset YOUR_DATASET_ID

# Linux or macOS
python3 -I run_w1.py --base-url https://ragflow.example.org --api-key-file ~/keys/ragflow-w1.key --dataset YOUR_DATASET_ID
```

`-I` keeps Python from loading anything from the current folder or from your user settings. Replace
`YOUR_DATASET_ID` with an id that `--list-datasets` prints.

| Option | Meaning |
|---|---|
| `--base-url URL` | Required. The server, e.g. `https://your-ragflow-host`, `https://host/prefix` or `http://localhost:9380`. In RAGFlow's own docker setup, 9380 is the plain-http API port and https comes from nginx on 443 (v0.27.3 `docker/docker-compose.yml:46`, `docker/nginx/ragflow.conf.python`). No user, password, query or fragment. |
| `--api-key-file PATH` | Required. A file holding the key alone, on one line. |
| `--dataset ID` | Repeatable; required for a run and a dry run. 32 hex characters, as `--list-datasets` prints. |
| `--queries PATH` | Default: `w1-queries.jsonl` beside the script. |
| `--out PATH` | Default: `w1-results.jsonl` in the current folder. Must not exist. |
| `--fields LIST` | `query`, `question` or both, comma-separated (default `query,question`, in that order). |
| `--list-datasets` | Print your datasets and write nothing. |
| `--dry-run` | Check the inputs, print the first request body, send nothing. |
| `--page-size`, `--similarity-threshold`, `--vector-similarity-weight`, `--top-k`, `--rerank-id` | The settings above. Change them only if the owner asks: the defaults are his canvas's. |
| `--allow-insecure-http` | Allow `http://` to a host other than this machine. This sends the key unencrypted. |
| `--ca-file PATH` | A CA bundle for a server with a private certificate. |
| `--timeout S` | Seconds per request (default 120). |
| `--max-attempts N` | Attempts per request on 429, 500, 502, 503, 504, a dropped connection or a timeout (default 5, at most 10). |

**Order.** All items run on `query` first, then all on `question`. A run that stops early still has the
`query` field, the one decision rule (c) scores first.

**Retries.** The waits are 1, 2, 4 and 8 seconds, or the server's `Retry-After` when longer, capped at 120 seconds. A
refused key (HTTP 401 or 403, or code 109 or 401) and a certificate error stop the run at once, without
retrying.

**Errors from RAGFlow.** Both versions answer most errors with HTTP 200 and a non-zero `code`
(`api_utils.py:322-333`; rc3 `http.go:779-792`). A missing or wrong key gets HTTP 401 with code 401
(`api/apps/__init__.py:273`, `:403-406`). An error on one query is written as that row's `error`, as the code
and its name only, and the run goes on.

| Exit | Meaning | What is written |
|---|---|---|
| `0` | Every query answered. | `w1-results.jsonl` |
| `1` | Incomplete. Either some queries answered with an error, or the run stopped: refused key, redirect, server unreachable after retries, or an answer the script does not know. | After errors: `w1-results.jsonl`, with `counts.error` above 0. After a stop: only `w1-results.jsonl.partial`, with `finished_at` null and `counts.not_run` above 0. If the stop came before the first query, nothing is written. |
| `2` | Refused before anything was sent: an option, the key file, the queries file, or an existing `--out`. | nothing |
| `130` | Interrupted (Ctrl-C). | `w1-results.jsonl.partial` if queries were sent |

The results are written once, at the end of the run: first to `<out>.partial`, then renamed to `<out>` only
when every planned query was sent. A `.partial` file is never a complete result. To try again, choose a new
`--out` or move the old files away. There is no resume: a run is 160 retrieval calls.

### What Walid sends back

He sends `w1-results.jsonl` alone. He does not send the key file, and does not send a `.partial` unless the
owner asks. With it goes the declaration the spec's safe path asks for: the file's type (evaluation
results), its rights status, and whether it holds client data.

**What the file holds.**

- **Line 1, the header.** It holds:
  - the sha256 of the script and of the queries file;
  - start and finish times, and the RAGFlow version, or null with a note;
  - for each dataset: its id, its document and chunk counts, its embedding model, chunk method and
    `parser_config`. The embedding model is the server's `embedding_model_name` when it gives one, else its
    `embedding_model`. v0.27.3 can store an opaque tenant_model id in `embedding_model` and gives the name
    beside it (`dataset_api_service.py:508-510`); v1.0.0-rc3 puts the name in `embedding_model` itself
    (`internal/service/dataset/crud.go:730`). The key set stays the contract's;
  - the settings sent, the fields run, and the counts.

  It holds no dataset name and no server address.
- **Then one line per field and item.** Each holds the text sent, `ok` or `error`, and the chunks in rank
  order. Each chunk has its full text, document name and id, chunk id, and the three similarity scores.
  Chunk text is text from his datasets, which is why only law-text datasets should be searched.

The results are evaluation evidence, never library material (REQ-RAG-047). See «The W1 flow, end to end»
for intake.

### What this does not prove

- **It has never met a real RAGFlow server.** It has only met the fake in `tests/fake_ragflow.py`, and
  that fake was written from the same reading of the source.
- **The request fields, defaults, answer shape and error codes are a reading of the RAGFlow v0.27.3 source,**
  with v1.0.0-rc3 checked beside it. Walid's version is unknown, and an older one may differ:
  - a missing version route gives a null version, with a note;
  - different chunk field names stop the run with «no data.chunks list» rather than guess.
- **It was not run on Python 3.9.** It was parsed with the 3.9 grammar (`ast.parse(..., feature_version=(3, 9))`)
  and tested on Python 3.11.9.
- **The defaults reproduce his canvas's retrieval call only as far as the HTTP API allows** (see above).
  The results measure his engine, texts and settings on our queries, not his agent.
- **The returned file cannot prove that it came from this script unchanged.** Its header hashes show
  which script and queries he says he ran. The agreement with Walid is what stands behind them.
- **`script_sha256` is the hash of the file as it sits on his machine.** Line-end conversion (git
  `autocrlf`, or saving in some editors) changes it. Send the script as an attachment, not as pasted text.

### Tests

`tests/test_run_w1.py` holds 51 tests. They run against `tests/fake_ragflow.py`, a fake server on
127.0.0.1 that contacts nothing, and write only to temporary folders. For the TLS tests,
`tests/tls_cert.py` makes a fresh self-signed certificate for 127.0.0.1 at test time, with the standard
library only, so no key is stored in the repository.

```bash
cd "/d/Iqraa Law/AI Harness-w1/tools/ragflow-w1" && python -B -X utf8 -m unittest discover -s tests -t . -v
# WSL: cd "/mnt/d/Iqraa Law/AI Harness-w1/tools/ragflow-w1" && python3 -B -m unittest discover -s tests -t .
```

They cover:

- **The request.**
  - The full first request body, compared as a whole, so a changed default fails.
  - The key in the Authorization header of the retrieval and dataset requests, and absent from the version
    request.
  - The defaults against the canvas mapping, and `--rerank-id` sent only when given.
  - Field order, and `--fields`.
  - A `--base-url` path prefix kept in every request.
  - Proxy settings in the environment ignored: a fake proxy receives nothing.
- **The output.**
  - Arabic round-trip, with harakat, tatweel, Arabic-Indic digits, a right-to-left mark and a ligature.
  - Row and chunk shape.
  - No dataset name, owner nickname, host or port anywhere in the file.
  - Header hashes, settings and counts.
  - A null version with a note when the route is missing, and no server text in the note.
  - The embedding model's name rather than v0.27.3's tenant_model id, a legacy name kept as it is, and the
    facts of the dataset asked for when the server lists more.
  - A key echoed into a chunk is removed.
- **Refusals (exit 2, nothing sent).** Plain http to another host or to a `*.localhost` name, an empty key
  file, a two-line key file, an existing `--out` or `.partial`, a missing `--out` folder, a queries file
  carrying `expected`, a queries header with a key outside the contract, a page size above 64, a malformed
  dataset id, an unknown flag and an abbreviated one (`--data`).
  - Neither a key given as the `--api-key-file` path nor one typed after an unknown option is repeated.
  - A redirect stops the run, and its target receives nothing.
  - The gate refuses five requests outside the allowlist.
- **Failures.**
  - A 503 is retried, then the run succeeds.
  - Retries that run out leave only a `.partial` file.
  - A refused key stops at the first request, whether HTTP 401 or code 109 in the answer.
  - An error on one query is recorded and the run goes on. Its message, here holding
    `http://10.0.0.5:11434`, is shown on screen and kept out of the file.
  - The bare key, and another Bearer token, in a server message are not shown.
  - An `--out` that appears during the run is left alone; the run exits 1 with a `.partial`.
- **TLS.** A certificate the system does not trust stops the run at the first request, with no retry and
  nothing received by the server; with `--ca-file` the run succeeds.
  - Ctrl-C writes a `.partial` file and exits 130.
- **Modes.** `--dry-run` sends and writes nothing; `--list-datasets` sends only dataset listings, writes
  nothing and shows the embedding model's name.
- **Isolation.** A run as `python -I run_w1.py` from a foreign folder, against a server that echoes the
  Authorization header in an error and the key in a chunk. The key appears in none of stdout, stderr or
  the results file.

On 2026-11-08, each of 21 mutations of `run_w1.py` made at least one of these tests fail. Among them are a removed
`ProxyHandler({})`, an unverified TLS context, a TLS error retried, either redaction layer removed,
`AUTH_CODES` emptied, the base-url prefix dropped, `allow_abbrev` on, the server's message written to the
file, and `*.localhost` counted as loopback.

## intake_w1.py and score_w1.py — our side

`intake_w1.py` puts the file Walid returns into quarantine with a manifest. `score_w1.py` scores it against
our search under the spec's W1 mapping rule and decision rule (c) (`.hq/docs/specs/spec-rag-system.md`,
«The decisive test», Part 2). Both are Python standard library only. Run both with `python -I`, because
they read his file.

```bash
# Windows, Git Bash, from this folder
cd "/d/Iqraa Law/AI Harness-w1/tools/ragflow-w1"
# 1. Intake. Save his file outside every repository and do not open it.
python -I intake_w1.py --file "/c/Users/<you>/Downloads/w1-results.jsonl" --handover-id walid-w1-1 \
  --client-data-declared no --rights "<what Walid declared>"
# 2. A person (the owner or the lawyer) screens the file, then records the outcome.
python -I intake_w1.py --record-screening --handover-id walid-w1-1 --screened-by "<name>" --outcome clear
# 3. Score. --laws-held: the laws his dataset holds, from his --list-datasets facts or his declaration.
python -I score_w1.py --results "/d/Iqraa Law/.hq/quarantine/ragflow-export/walid-w1-1/w1-results.jsonl" \
  --out-dir "/d/Iqraa Law/.hq/docs/audits/librechat-platform/w1-walid-w1-1" \
  --laws-held "<law slugs he declared, comma-separated>"
# Check the scorer on our own data (no file from Walid needed)
python -I score_w1.py --self-check
# Score our own W2 run (README «Own runs (W2)»): no intake, no screen, a W2 manifest instead
python -I score_w1.py --own-run \
  --results "/d/Iqraa Law/.hq/scratch/w2-run/out/elasticsearch/w2-results-v3.jsonl" \
  --manifest "/d/Iqraa Law/.hq/scratch/w2-run/out/elasticsearch/w2-manifest.json" \
  --fallback "/d/Iqraa Law/.hq/scratch/w2-run/out/elasticsearch/w2-fallback-v3.json" \
  --out-dir "/d/Iqraa Law/.hq/scratch/w2-run/out/elasticsearch/score-v3" --w2-decide
# WSL: the same commands with python3 and /mnt/d/... paths
```

Do not take `--laws-held` from his zip. The zip held five law files (`walid-ragflow-laws-2026-11-07.md`),
but the dataset his agents query named only two laws, evidence and civil procedure, as of 11-04
(`walid-ragflow-agents-2026-11-07.md`, §3.1, and §4 question 4). Leave `--laws-held` out to infer the laws from
his chunks. If you give it, the scorer checks it against the same evidence (below).

Exit codes for both: `0` done; `2` refused, nothing written. `--self-check` exits `1` if a check fails.

### intake_w1.py

| Option | Meaning |
|---|---|
| `--file PATH` | The returned file. |
| `--handover-id SLUG` | Lower-case letters, digits and dashes, at most 64 characters. Names the quarantine folder. |
| `--client-data-declared no\|yes` | Walid's declaration for this file. Required. `yes` is refused (safe path, step 2). |
| `--rights TEXT` | The rights status he declared. Default: not yet checked by the lawyer. |
| `--origin TEXT`, `--received YYYY-MM-DD` | Recorded in the manifest. The date defaults to today. |
| `--quarantine-root DIR` | Default `<workspace>/.hq/quarantine/ragflow-export`. |
| `--package DIR` | The package we sent, to compare the header hashes with. Default `<workspace>/.hq/docs/specs/w1-for-walid`. |
| `--record-screening --screened-by NAME --outcome clear\|flagged` | Record a person's screen (safe path, step 4). |

**It refuses**, before it writes anything:
- a file that breaks the contract:
  - the header is not on line 1;
  - a header, dataset, line or chunk key is missing, or a key is outside the contract (so a dataset `name`, a
    `base_url` or a `host` is refused);
  - `counts` holds a key other than `items`, `planned`, `ok`, `error` and `not_run`, lacks one, or holds a
    value that is not a whole number;
  - `settings` holds a name that `run_w1.py` does not send, or a value of the wrong type. A test checks that
    every name `run_w1.py` sends is accepted;
  - `finished_at` is null (an unfinished run);
  - chunk ranks are not 1, 2, 3 ... in order;
  - a second line has the same field and id;
  - an id is not an eval-set id;
  - an `ok` line carries an error; an `error` line has chunks, or an error longer than 500 characters;
  - text that is not UTF-8 or not JSON;
  - a line over 4 MiB, or a file over 512 MiB.
- a file that looks like it holds a secret, anywhere in it: a RAGFlow key (`ragflow-` plus 20 or more
  characters; v0.27.3 makes keys as `"ragflow-" + secrets.token_urlsafe(32)`, `api/utils/api_utils.py:351`), a
  Bearer token (`Bearer [REDACTED]`, as `run_w1.py` writes it, is accepted), or the word Authorization.
- a file that looks like it holds a server address: a URL or `localhost` anywhere, or an IP address outside
  chunk text. IPv4, and IPv6 in brackets, with `::`, or with all eight groups (so the header's times, such as
  `08:00:00+00:00`, pass). Chunk text is not checked for IP shapes, because a statute can number a clause
  `1.2.3.4`.
- a long random-looking token (32 or more characters of letters, digits, `_` and `-`, mixing upper case,
  lower case and digits) anywhere except a document name or chunk text. Those two can hold such a token
  honestly (Walid's criminal-procedure file names its review file `IQRA_LAW_Criminal_Procedure_Articles_1-370_REVIEW`),
  so there it is counted for the screen as `long_mixed_token`.
- a declaration of client data, or no declaration;
- a handover folder that already exists and is not empty;
- a quarantine root that is not inside a folder named `quarantine` once links are resolved, or that is inside a
  repository.

Refusals name the line and the key, never the value.

**It writes** `<root>/<handover-id>/w1-results.jsonl`, a byte copy checked by sha256. Then it writes
`manifest.json`:
- the origin, the sha256, the declared type «W1 evaluation evidence», the rights status, the client-data flag
  and the date received (safe path, step 3);
- the REQ-RAG-047 use note;
- the contract facts: line, status and chunk counts per field, the header hashes and whether they equal the
  package we sent;
- pattern counts for the person who screens it: national ID shapes, phone numbers, case numbers, and the words
  «المدعي», «الموكل» and «موكلي». They run over every string in the file, keys included, and are counted by
  place: chunk content, document names, error strings, the header, and the rest (ids, sent text). Counts only.
  Statute text holds «المدعي» often, so a count in chunk content is not a finding;
- `screening: pending`, and an empty `screening_history`.

It prints counts and the sha256, never text from the file.

**The screen gates the score.** `score_w1.py` scores only a `w1-results.jsonl` whose folder passes the
intake's folder checks again: a handover id, inside a folder named `quarantine` once links are resolved, and
outside every repository. A copy of the pair anywhere else is refused. The manifest must still match the
file's sha256, record the client-data flag as `no`, and record the screen as `clear`. A `flagged` or `pending`
screen is refused. Each screen is added to `screening_history`. Once a screen is `flagged`, no other outcome can
be recorded: the file is returned or deleted as the agreement says, and is not opened further (safe path,
step 4).

### score_w1.py: the rules as built

| Option | Meaning |
|---|---|
| `--results PATH` | The quarantined `w1-results.jsonl`. Or `--self-check`. |
| `--out-dir DIR` | Where `w1-score.json` and `w1-score.md` are written. Required with `--results`. |
| `--laws-held a,b` | The law slugs his dataset holds. Default: inferred from his chunks. |
| `--allow-unevidenced-laws` | Keep a `--laws-held` law that none of his chunks comes from. Refused otherwise. |
| `--articles-lacking law:number,...` | Articles his copy lacks, for example `civil-code:107` (‡, below). |
| `--own-run --manifest PATH` | The results are our own W2 run, beside its `w2-manifest.json` («Own runs (W2)», below). |
| `--w2-decide` | With `--own-run`: print the pre-registered W2 reading. Refused unless the file is the deciding cell. |
| `--fallback PATH` | With `--own-run`: `w2-fallback-<arm>.json`, for the dense-only fallback sensitivity reading. |
| `--split PATH` | `split.json`. Default: the durable copy `p3-evidence/rag-bench-split.json`, else the bench's, with a warning. |
| `--package DIR` | With `--own-run`: the package the header hashes must equal. Default `.hq/docs/specs/w1-for-walid`. |
| `--bench DIR`, `--baseline PATH` | The bench folder and `eval-final.json`. Defaults: the workspace paths. |

**Article texts.** For every article, the text search_law serves. The registry, the shards and
`content/corpus/corrections.json` are read with `legal_search.registry`, `corpus.parse_law` and
`corrections.apply_corrections`, and the count is checked against `law-directory.md` minus known gaps. These
are the steps of `legal_search.ingest._law_articles` (`ingest.py:42-62`), which stores `a.text` (`db.py:229`).
`ingest` itself needs psycopg, so its steps are repeated here, as the bench's `py/export_corpus.py` used them.
The result is 6,592 articles, all byte-identical to the bench export. The corpus sha256 is computed as
`evaluate.corpus_digest` computes it (`1c31a2106af1`). The scorer refuses to run if the corpus sha256 or the
eval set sha256 (`870ce8df5335`) differs from the one `eval-final.json` was run on.

**Normalised tokens** are `legal_search.normalize.tokens`: folded, diacritics dropped, one clitic prefix
stripped, stopwords kept. These are the tokens the library indexes (`db.py:230` stores `normalize(text)`).

**The mapping rule** (spec ‡; the stretch limit is ours, also ‡). A chunk retrieves article A, of n tokens,
when some n consecutive tokens of the chunk hold at least half of A's tokens, in order: for some stretch of n
chunk tokens, `LCS(stretch, A tokens) >= ceil(n/2)`. The spec says «at least half of that article's normalised
tokens, in order», and neither it nor its sources define that more precisely.
- **Why a stretch.** Read over the whole chunk, the LCS has no limit on span. A long chunk of neighbouring
  articles from the same section then picks up half of an article's tokens in order from several of them,
  and «retrieves» an article it does not hold. The review of 2026-11-08 measured this on our own articles.
  Chunks of about 2,300 characters (about the median chunk of a file of the real run's shape, below) were cut
  from the same law's neighbouring articles, with the expected article left out. They mapped 17 of the 104
  expected articles, in 20 runs. In 16 of the runs no single article of the run maps the expected one. Among
  the items were civil-code-08 (the tracked item), and penal-code-07 and criminal-procedure-03, under-half
  items on the five laws.
- **Why n.** With a stretch of 2n or 1.5n chunk tokens, two runs still mapped an article only as a run: two
  adjacent articles held penal-code 68 (93 tokens) within 99 tokens, and majalla 305 (25 tokens) within 33.
  With n, none did, at 1,200, 2,300 or 4,700 characters. A chunk that holds the article whole, or half of it in
  one piece, still maps. Up to ⌊n/2⌋ other tokens may sit among the matched ones.
- `WINDOW_FACTOR` in `score_w1.py` sets the stretch. Which reading decides is the owner's call (‡). The
  report states the rule and marks it ‡.

It is computed bit-parallel (Allison-Dix and Hyyrö). Tests check it against the textbook dynamic programme,
over the whole chunk and over every stretch. Consequences the tests pin:
- exactly half maps, one token fewer does not;
- tokens all present but out of order do not map;
- half of a six-token article in order within six chunk tokens maps; within seven it does not;
- the same tokens scattered through a long chunk do not map; half an article in one piece inside a long chunk
  does;
- one chunk can retrieve two articles;
- an article split across two chunks counts for each chunk that holds half of it. Split 3 + 3, both map. Split
  4 + 3, only the first maps. Split in three, no chunk maps it, although all its text is served;
- an article with no token never maps. A one-token article («ملغاة») maps on any chunk with that word. Such an
  article is never an expected article.

**The null control** (in `--self-check`). For each of the 104 expected articles, two chunks of the same law's
neighbouring articles, after it and before it, in law order, the article left out: 207 runs (one article has
nothing before it). A run that maps the expected article is counted as mapping «through a single article»
when one article of the run maps it on its own (shared wording, which our arms scored through the rule earn
too), and «only as a run» otherwise. The self-check fails if any run maps an article only as a run. Results on
2026-11-08:

| run length (characters) | through a single article | only as a run |
|---|---|---|
| 1,200 | 2 (criminal-procedure 58, court-fees 22) | 0 |
| 2,300 | 3 (also companies 170) | 0 |
| 4,700 | 4 (also magistrates-courts 8) | 0 |

Without the stretch (the whole-chunk LCS), the same runs map 3, 4 and 5 through a single article and 11, 16
and 28 only as a run. The single-article case the stretch drops is majalla 19 (22 tokens): majalla 26 holds
half of it in order over its whole length, but not within 22 tokens. A real-data test checks the 1,200 row,
and that the control does fail without the stretch.

**The candidate restriction.** Each article is indexed under its rarest distinct tokens until they cover more
than ⌊n/2⌋ of its n positions. A chunk that maps A matches ⌈n/2⌉ of A's positions, and at most ⌊n/2⌋ lie
outside that set. So the chunk holds one of its tokens (pigeonhole). The stretch rule maps a subset of what
the whole-chunk LCS maps, so the index still drops nothing. Two bounds then skip work. The sum of A's counts
of the tokens A shares with the chunk bounds the LCS. The whole-chunk LCS bounds every stretch, so only an
article that passes it is tested stretch by stretch. Only stretches that start on one of A's tokens, and the
last one, are tested, each under a sliding count bound. Two tests compare the result with a scan that tests
every article on every stretch: no index, no count bound, no skipped stretch. The scan keeps the whole-chunk
LCS as a filter, since a stretch cannot hold more than the chunk. One test runs on a random corpus of 400
articles with 300 chunks, the other on our 6,592 articles with 8 chunks. Both match exactly. A third test
checks the stretch LCS, skipped stretches and bound included, against the dynamic programme on every stretch
of 600 random pairs.

**The equal served-text budget.** For each item and each comparison arm, the budget is the characters (code
points) of law text the arm serves in its top 5: `len(text)` of each article.
- search_law serves `format_articles(found)` (`tools.py:109`). Per article that is a «[i] heading» line, the
  text, and a publication and verification line built from the registry (`citation.py:62-69`). Only the text
  is counted. The rest is framing about the source, not retrieved law text. RAGFlow's chunk `content` holds no
  such framing. Counting the whole block instead is the owner's call (‡).
- W1's chunks count in rank order until their characters reach the budget. The chunk that crosses the budget
  counts up to the budget, cut back to its last whole word. So W1 never reads past the budget, and the cut
  piece's tokens are a prefix of the chunk's tokens. A chunk that starts at the budget never counts.
- The report also shows the crossing chunk counted whole and left out. Those readings are not used to decide.
- Mapped articles are deduplicated. Each takes the rank of the first chunk that maps it.

**The comparison arms.** Part 1 has not run, so the arms are recorded runs. Each one's ranked lists are
re-scored with `legal_search.metrics.summarise` on load. If a figure differs from the recorded one, the scorer
stops. The recomputed figures on 2026-11-08, all equal to the record:

| field | arm | source | recall@5 | hit@5 | MRR |
|---|---|---|---|---|---|
| query | A0, Postgres today | `.hq/docs/audits/librechat-platform/p3-evidence/eval-final.json` | 0.5625 | 0.6375 | 0.4874 |
| query | T-B2 `r2\|b2\|t0.5\|h1.0` | `p3-evidence/rag-bench-rows-round2.jsonl` | 0.7229 | 0.7875 | 0.5498 |
| query | T-B3d `r2\|b3d\|l2.0\|w16` | `p3-evidence/rag-bench-rows-round2.jsonl` | 0.7063 | 0.7625 | 0.5740 |
| question | A0q `pgrust:question:gold` | bench `results/perf/pg-rows-question.jsonl` | 0.4604 | 0.5250 | 0.3707 |
| question | B1q `r2\|q:question` | `p3-evidence/rag-bench-rows-round2.jsonl` | 0.6937 | 0.7625 | 0.5987 |
| question | T-B2q `r4\|q:question\|r2\|b2\|t0.5\|h1.0` | `p3-evidence/rag-bench-rows-round4.jsonl` | 0.6750 | 0.7375 | 0.6005 |
| question | T-B3dq `r4\|q:question\|r2\|b3d\|l2.0\|w16` | `p3-evidence/rag-bench-rows-round4.jsonl` | 0.6875 | 0.7500 | 0.6206 |
| question | B4q `r4\|q:question\|r2\|b4\|guardlight\|dismax` | `p3-evidence/rag-bench-rows-round4.jsonl` | 0.7000 | 0.7625 | 0.6003 |

The recorded figures are `results/score-all.json[cfg]['all']['overall']`, and `eval-final.json`'s metrics for
A0. «Our best arm» on a field is the arm with the highest recorded all-80 recall@5: T-B2 on the query field,
B4q on the question field. The report reads decision rule (c) against every arm and names the best one.

**Where the arms are read from.** `rows-round2.jsonl` and `rows-round4.jsonl` are read from their durable copies
in `.hq/docs/audits/librechat-platform/p3-evidence/` (`rag-bench-rows-round2.jsonl`, sha256 `7bccbab94956…`;
`rag-bench-rows-round4.jsonl`, `89f61a4ceaf1…`; copied 2026-11-08, byte-identical to the bench files). If a copy
is missing, the bench file is read, with a warning on the terminal and in the report. A0q's
`results/perf/pg-rows-question.jsonl` and the strata's `data/eval.jsonl` have no durable copy and are read from
the bench. If one of them, or any other source file, is missing, scoring is refused before any source is read,
and the refusal names each missing file (before, it crashed with a traceback). The report records each source's path
and sha256 (`sources` in the JSON, «Sources» in the markdown), and marks the bench ones «scratch bench». The
re-scored-equals-recorded check runs on whichever file is read.

**Halves** (`split.json`). The bench split T-B2's settings were tuned on: half A, 40 items, and the held-out
half B, 40 items. Read from `p3-evidence/rag-bench-split.json` (sha256 `6e7909beedf2…`), else from the bench's
`data/split.json` with a warning, or from `--split`. If neither copy exists and no `--split` is given, scoring is
refused (before, it crashed). Its ids must be the eval set's, each `A` or `B`, in two equal halves. Its key order
is kept: the intervals resample in that order («Intervals», below). Every report, W1 and W2, adds the scopes `half_A` and `half_B` (the held items of each half), with
intervals by keys and through the rule, in a «Halves» table beside the held scope (all 80 in an own run). For
W1 the half scopes are reported, not decisive. Decision rule (c)'s logic is unchanged, but its interval ends
are not: with the split loaded, its scopes now resample in the split's key order, not the eval set's
(«Intervals», «Order», below).

**Strata** (spec «Definitions», «The miss pattern»). They are defined on the `query` field and used for both
fields. An item's stratum is the share of its query terms that prefix-match its best single expected article.
The terms are the recorded `legal_search.db.query_terms(query)` in the bench's `data/eval.jsonl`, written by
`py/export_corpus.py:40`. They are used because `db.py` needs psycopg. The bench row must match the eval set's
query and expected articles. The derivation reproduces the spec's table: 17 under half, 49 half or more, 14
all, with Postgres reaching 4, 35 and 12. The scorer stops if it does not.
- The 17 under-half items: civil-code-01, civil-code-02, civil-code-memo-03, majalla-01, majalla-03,
  penal-code-02, penal-code-07, penal-code-08, civil-procedure-01, civil-procedure-03, criminal-procedure-02,
  criminal-procedure-03, criminal-procedure-05, execution-02, sales-tax-02, investment-fund-01,
  bar-association-02.
- The six never-reached items are all in it. civil-code-08 is half-or-more (3 of 6 terms).

**Laws his corpus holds.** `--laws-held` states them. Otherwise they are inferred, and marked «inferred». The
evidence is computed either way, and the report prints it.
- Each returned chunk, read whole at any rank, counts once: for the law of its best source. That is the
  mapped article the most of whose tokens it holds in order within one stretch, then the longer one. It counts
  only when that is 8 tokens or more.
- A law is inferred held when it is the best source of at least 3 chunks.
- With `--laws-held`, a law that is the best source of none of his chunks is refused: its items would count as
  his failures, not as «lacking». `--allow-unevidenced-laws` keeps it, with a warning. A given law that is the
  best source of only 1 or 2 chunks, and an inferred law that was not given, are warned about on the terminal
  and in the report.
- Counting every article a chunk maps does not work, because laws share wording. In a synthetic file of 3,200
  chunks cut only from the five laws' articles, that count put 22 laws above 3 mapped articles.
- Without the 8-token floor, the fake server's invented chunks, which only repeat the question, made 3 laws
  «held» through short articles.
- Checks of the inference, 2026-11-08:
  - the synthetic five-law file, with the stretch rule: exactly the five;
  - before the stretch rule, chunks of all 22 laws' served texts: all 22; the fake server's chunks: none.

An item's law is the law of its expected articles (`evalset.py:66-68`).

**Articles his copy lacks** (‡). `--articles-lacking civil-code:107,...` names articles his copy is known to
lack, in the form the report prints (`law:number`). Each must be an article of our library. An item whose
expected articles are all among them leaves the held scopes and is reported with the «lacking» items, marked
`articles`. An item with only some of them lacking stays held. Without the option, nothing changes.
- The spec says «items whose law his corpus lacks». The agents audit reads that as articles or laws
  (`walid-ragflow-agents-2026-11-07.md`, §5).
- The laws audit lists 25 civil-code articles his zip's copy lacks (`walid-ragflow-laws-2026-11-07.md`). One of
  them is an expected article: civil-code 107, the only expected article of civil-code-01. That item is
  under half, and T-B2 reaches it. Left in, it counts as a miss for W1 on both decisive scopes.
- Whether his dataset lacks it too is not known. Whether to pass it is the owner's call.

**Metrics and scopes**, per field present in his file. For each arm, at that arm's budget:
- W1 «reached» means an expected article is mapped within the budget. «Recall» is the share of expected
  articles mapped within it. The arm's own figures are hit@5 and recall@5.
- The scopes:
  - **held**: items on laws he holds, less those whose expected articles he lacks. This scope decides,
    because items he cannot hold are not failures;
  - **stratum ∩ held**: the under-half items among them;
  - **all 80** and **stratum (17)**: items he cannot hold count as misses here. Reported, not decisive;
  - **lacking**: the items he cannot hold, reported separately, each marked `law` or `articles`;
  - per law; and the 7 named items.
- A line with status `error`, or a missing line, counts as a miss and is listed. If he sent any text other
  than the frozen set's `query` or `question` for an item, scoring is refused.

**Intervals.** A paired bootstrap of W1 minus the arm over the scope's items: 10,000 resamples, seed 20261106,
a fresh `random.Random(seed)` per interval, `rng.choice` per item, and the 2.5% and 97.5% means. This is the
bench's `py/report.py` `bootstrap()` (lines 21-26); a test checks it against a copy of that code.
- **Order.** The resampling picks items by position, so the order of a scope's items moves the interval's ends.
  Every scope takes its items in `split.json`'s key order, as `report.py` does (line 22:
  `ids = [i for i in split if ...]`). That is not the eval set's file order. Only when no split is loaded (the
  self-check) is the eval set's order used. The report names the order under `rules.bootstrap.order`.
- **This changed W1's interval ends.** Before W2, the scorer resampled every W1 scope (all 80, held, stratum,
  stratum ∩ held) in the eval set's order. Rule (c)'s logic is the same, but for the same input its interval
  ends move, by up to 0.0063 on the recorded arms. Recall@5 on all 80, eval-set order, then split order
  (`.hq/scratch/w2-review-score/r2/probes/order_w1.txt`): T-B2 minus A0 [+0.0521, +0.2729], then
  [+0.0542, +0.2667]; T-B2q minus B4q [-0.1000, +0.0437], then [-0.0938, +0.0437]; B4q minus A0q
  [+0.1500, +0.3375], then [+0.1479, +0.3333]. That can flip a borderline reading. The split order is the
  bench's, which the spec runs on. Whether W1 keeps it is a pre-registration detail for the owner to confirm
  before the package goes to Walid (‡). A real-data test pins one W1 rule (c) interval in split order, so any
  later change of order fails a test.
- **Off zero.** An end counts as above zero only when it is more than 1e-9, and as below zero only when it is
  less than -1e-9 (`ZERO_TOLERANCE`, recorded as `rules.bootstrap.zero_tolerance`). An item's recall is k/1,
  k/2 or k/3, since no item has more than 3 expected articles. So each difference is a multiple of 1/6, and a
  nonzero mean over n items is at least 1/(6n): 0.002 at 80 items. Without the tolerance, a resample whose
  thirds cancel exactly could leave float residue. For example, +1 on 5 items, -1/3 on 3 and 0 on 32 gave a
  low end of 2.8e-18. That read «wins» while printing +0.0000. No pinned value changes. The deciding reading
  could not meet the residue, because every half-B item has 1 or 2 expected articles. The exploratory all-80
  readings and W1's rule (c) could, because the one item with 3 expected articles is in half A.
- **Checked against the bench.** A real-data test reproduces PROOF-rag-bench.md's published interval in split
  order: B2 minus Postgres, MRR on half B, +0.132 [+0.019, +0.248] (the test pins 0.1319 [0.0187, 0.2479]). In
  the eval set's order the same differences give [+0.0169, +0.2506].

**Decision rule (c).** W1 «beats with an interval excluding zero» when the interval of W1 minus the arm lies
wholly above zero, on held recall or on stratum ∩ held recall. Otherwise it «does not beat».

**Like with like.** Under the rule, our own served text also «retrieves» an expected article when another
served article holds half of its tokens in order within one stretch. Each arm is therefore also scored through
the same rule. The report reads (c) against that too, and says when the two readings differ. Which reading
decides is the owner's call (‡). The spec scores every arm by its keys.
- With the stretch, our text gains nothing from how it is cut. A0's own text read as whole articles, as
  halves and as merged pairs gives 0.5625 each time, its recorded figure. Before the stretch, whole articles
  gave 0.5813 and merged pairs 0.6125: text that runs across two adjacent articles mapped. That credit was
  open to W1's long chunks and closed to our one-article «chunks», so the two readings were not comparable.
- What is left is shared wording: one article that holds half of another in order. Our arms earn it through
  the rule (T-B3d and A0q on companies-03, T-B2q and B4q on criminal-procedure-05), and W1 earns it the same
  way. The null control finds 2 to 4 such articles and none mapped only as a run.

**Outputs.** `w1-score.json` and `w1-score.md` in `--out-dir`. An existing one is refused. They hold ids, ranks,
counts, budgets, mapped article keys (ours) and metrics. They hold no chunk text, document names or chunk
ids; a test plants a marker in every chunk and checks both files. From his header they copy only the five
`counts`, the settings that are `run_w1.py`'s names with a number or a flag as value, and whether a rerank id
was sent.

### The self-check

`--self-check` reads each arm's own served texts as W1 chunks, at that arm's budget. It uses the whole articles
for every arm. For A0 it also splits each article in two halves at a word boundary (the halves join back
exactly) and merges articles in pairs. Then it runs the null control above.
- **Strict reading.** A chunk counts only for articles in the arm's top 5. W1 must equal the arm on every item.
  This checks the budget, the order, the cut and the metrics.
- **Rule reading.** W1 may not fall below the arm on any item. With whole articles, W1 must equal the arm
  scored through the rule.
- **Null control.** No neighbour run may map an article only as a run.

Result on 2026-11-08 (`python -I score_w1.py --self-check`, about 2 minutes): passed. In the strict reading
every arm gives back its recorded figures on every item:
- A0: recall 0.5625, 51/80 reached, 4/17 on the stratum, in all three variants.
- T-B2 0.7229, T-B3d 0.7063, A0q 0.4604, B1q 0.6937, T-B2q 0.6750, T-B3dq 0.6875, B4q 0.7000.

The rule reading equals the strict one for A0 (whole, halves and pairs), T-B2, B1q and T-B3dq. It rises on one
item for four arms, through shared wording:
- companies-03 for T-B3d (0.7188) and A0q (0.4729): both serve companies 173, which holds half of companies
  170 in order;
- criminal-procedure-05 for T-B2q (0.6813) and B4q (0.7063): both serve criminal-procedure 55, one of its two
  expected articles, which holds half of the other, 58.

The A0 whole-article interval of W1 minus A0 is +0.0000 [+0.0000, +0.0000].

**Time on a file of the real run's shape.** The canvas returns 20 chunks per query, with 512-token chunks. A
synthetic file of 80 items × 2 fields × 20 chunks was scored on this machine. Its chunks ran 4 to 12
consecutive articles of the five laws: 3,200 chunks, median 2,064 characters, 90th percentile 4,431 (a new
draw on 2026-11-08, after the review fixes; the earlier file had 2,294 and 4,693).
- With `--laws-held` (the five laws): 6 min 24 s. With inferred laws: 6 min 28 s, and the five laws were
  inferred.
- The two are close now because the evidence is computed in both. Before the review fixes they took 1 min 33 s
  and 4 min 29 s.
- Most of the time is the whole-chunk LCS that each candidate article must pass before its stretches are
  tested. The stretch tests add about a quarter (profiled on 300 such chunks).

### Own runs (W2)

The spec's block «Owner decision 2026-11-08: W2 first, run here, with a pre-registered rule» runs W2 on this
machine: our served articles, one generated file per law, in a throwaway pinned RAGFlow v0.27.3, indexed by
Walid's indexing-pipeline canvas and queried by `run_w1.py`. `--own-run` scores that file. It is our data, so
the third-party gates of the safe path (the quarantine copy and the person's screen) are skipped. A W2 manifest
ties the file to our dataset instead.

**The W2 manifest** is the shared contract. The ingest tool writes it when it creates the dataset, as
`.hq/scratch/w2-run/out/<engine>/w2-manifest.json`. A key outside this table, or a missing one, is refused, and
refusals name the key.

| key | checked |
|---|---|
| `w2` | 1 |
| `created_at` | an ISO-8601 time |
| `engine` | `elasticsearch` or `infinity`; the results sit in a folder of that name |
| `embedder` | exactly `name`, `revision` and `via`, each a non-empty string; `revision` is a 40 lower-case hex commit; `via` is `builtin-tei` |
| `ragflow_version` | exactly `v0.27.3` (so `v0.27.30` is refused), and equals the header's `ragflow_version` |
| `ragflow_image_digest` | holds `sha256:` and 64 hex characters |
| `dataset_id` | 32 lower-case hex characters, and the header's only dataset |
| `language` | a non-empty string |
| `document_count` | 22, and equals the header's |
| `chunk_count` | above 0, and equals the header's |
| `predicted_chunk_count` | equals `chunk_count` |
| `all_match` | `true`: the dataset's chunks matched the predictor exactly |
| `canvas_sha256`, `upload_manifest_sha256` | 64 lower-case hex characters |
| `file_shape` | `slug-title-served-v1` |
| `embedding_batch_size` | a whole number, 1 or more |

**The gate.** `--own-run` refuses, before it scores anything:
- a results file that does not resolve under `.hq/scratch/w2-run/out/` (a link that points elsewhere included),
  that does not sit directly in `out/<engine>/` (`out/nested/elasticsearch/` is refused), that is a link under
  another name, or that is not named `w2-results-v3.jsonl` or `w2-results-rt.jsonl`;
- a `--manifest` other than the `w2-manifest.json` beside it, or no manifest there;
- a manifest that breaks the contract above, including an `all_match` that is anything but the JSON value
  `true` (`false`, `"false"`, `"true"` and `1` are all refused) or a document count other than 22;
- a results folder whose name is not the manifest's engine;
- a file that breaks the results contract. Every `read_results` check and screen runs, as for Walid's file:
  keys, types, secrets, URLs, IP addresses and long tokens;
- a header whose datasets are not exactly the manifest's dataset id, or whose `document_count` or `chunk_count`
  differs from the manifest's;
- a header `script_sha256` or `queries_sha256` that is not the sha256 of the package's `run_w1.py` or
  `w1-queries.jsonl` (`--package`, default `.hq/docs/specs/w1-for-walid`);
- a header `ragflow_version` other than the manifest's;
- settings other than the arm's. `v3` is `run_w1.py`'s defaults, the FINAL REVIEW v3 Retrieval node: page_size
  20, similarity_threshold 0.2, vector_similarity_weight 0.3, top_k 1024, rerank_candidates_count 64, no
  rerank_id, and the options that call a model off. `rt` is the same with vector_similarity_weight 0.4
  (Retrieval TEST). The whole settings object must equal the arm's: a header that differs in any one key, or
  sends a `rerank_id`, is refused. A test checks both arms against `run_w1.py`'s own parser;
- a returned chunk whose `document_name` is not `<registry slug>.md`, for a slug of `content/corpus/laws.json`.
  Those 22 files are the only ones the ingest tool uploads. A chunk named like Walid's files
  (`IQRA_LAW_…_REVIEW.md`) is refused even beside a manifest that matches. The refusal gives the count, not the
  names. It is also refused when the registry does not have the manifest's 22 laws. A law that no returned chunk
  comes from is not refused: retrieval need not reach every law, and the laws-held note reports it;
- `--laws-held`, `--articles-lacking` or `--allow-unevidenced-laws` with `--own-run`, since they describe
  Walid's corpus; and `--manifest`, `--w2-decide` or `--fallback` without it.

A file from Walid copied under `out/` is refused. With no manifest beside it, there is none to match. Beside our
manifest, its dataset id differs. Tests pin both cases, and a file outside `out/`.

**Laws held and articles lacking.** An own run holds our whole corpus: all 22 laws and no article lacking. Every
item is held, so «held» is all 80. The evidence of laws (each returned chunk counted for the law of its best
source) is still computed and printed. A law that is the best source of fewer than 3 returned chunks gets a note
worded for our corpus: «<law> is the best source (8+ tokens) of N returned chunks, fewer than 3; the dataset
holds it, so this is what retrieval returned, not a missing law». The note moves no item. None of W1's warnings about laws held is raised, and the
report has no wording about his corpus (a test searches the markdown for «his» and «he»).

**The deciding reading** (`--w2-decide`). The amendment fixed one cell before anything ran:
- the cell: Elasticsearch, the built-in TEI `Qwen/Qwen3-Embedding-0.6B`, the `v3` arm, the `query` field;
- the pins it checks (`DECIDING` in `score_w1.py`):
  - the model revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`, the one the runbook fetches
    (`.hq/scratch/w2-research/deploy/runbook.md`, Step 4);
  - the canvas sha256 `3f0fcb62b79a0b292f05ccfc9ad198259acfb3b459a21c73c6ca4fc369bf588d`. That is the sha256 of
    the raw bytes of Walid's «اقرأ – فهرسة التشريعات القانونية.json», which `rf_ingest.py` hashes the same way.
    So the canvas must be imported as it is;
  - the embedding model the server reports for the dataset (the header's `datasets[1].embedding_model`, which
    `run_w1.py` reads from the server). It is parsed as v0.27.3 parses a composite name, from the right
    (`tenant_model_service.py:206-230`): the model must be exactly `Qwen/Qwen3-Embedding-0.6B`, and the
    provider `Builtin` or none. `Qwen/Qwen3-Embedding-0.6B-ft@Builtin`, `BAAI/bge-m3@Builtin` and an empty value
    are gaps. A 32-hex tenant-model id names no model: it is no gap, but the report warns that only the
    manifest names the embedder;
  - T-B2's rows read from the durable `p3-evidence/rag-bench-rows-round2.jsonl`, sha256
    `7bccbab9495646bc770d3ac5dbe6d243befd5a675d37861b32e5b3b46b0691ac`. The re-scored all-80 figures alone do
    not pin the half-B rows, and a bench copy read instead is a gap;
- against T-B2 (`r2|b2|t0.5|h1.0`), on the held-out half B (40 items) of the pinned split (`6e7909beedf2…`),
  in that split's key order;
- both scored through the mapping rule at T-B2's served-text budget. W2's chunks are cut at the budget, and
  T-B2's own top-5 text is mapped the same way: like with like, not T-B2's ranked keys;
- the paired bootstrap of W2 minus T-B2, 10,000 resamples, seed 20261106;
- «wins» only if the 95% interval lies above zero. Otherwise «not shown», with a note on what that means:
  - an interval that includes zero: «A smaller effect cannot be detected on 40 items»;
  - an interval wholly below zero: «W2 is behind T-B2 on half B: the whole interval lies below zero».
- A failed or missing half-B line counts as a W2 miss, and is listed. A failed half-A line is not listed there.

`--w2-decide` on any other file is refused, before the library loads, with each reason named: Infinity, the `rt`
arm, another embedder in the manifest or as the server reports it, another model revision, another canvas, no
query field, another split, or T-B2's rows from another source. Without the flag, the report still holds the
deciding reading when the file is the deciding cell, and says why not otherwise.

The RAGFlow image digest is recorded from the run and printed beside the pins, but not pinned. The digests in
`.hq/scratch/w2-research/deploy/compose.yaml` were read through a summariser (its lines 16-17), and no
`docker pull` has confirmed one yet. Pin it in `DECIDING` once one has; until then it is a known limit.

What 40 items can detect, as the tests pin it. With no item going the other way, W2 reaching 4 more half-B items
than T-B2 wins: the interval's low end is +0.025. Three more (+0.075 on average) is «not shown», because 4.4% of
the resamples hold none of the three.

**Exploratory**, printed under that heading and never deciding:
- the query field: W2 vs T-B2 through the rule on all 80 and on half A; vs T-B2's keys on half B; vs A0 and
  T-B3d on half B;
- the question field: vs T-B2q on half B, all 80 and half A, and vs B4q (the best question arm) on half B;
- W1's rule (c), read under its own name in each field's tables;
- Infinity on a fresh stack, and the `rt` arm: each is its own file, scored on its own.

**The dense-only fallback** (`--fallback`). `POST /api/v1/retrieval` keeps RAGFlow's dense-only fallback on;
his agent turns it off (the amendment). `w2-fallback-<arm>.json`, beside the results, holds
`{"query": [ids], "question": [ids]}`: the items whose returned chunks came only from that fallback, read from
the server's debug log. It must name each field of the results file and nothing else, its arm must be the
results file's, and each id must have an ok line with chunks. The sensitivity reading scores the file again with
those items' chunks emptied. It reports W2 vs T-B2 (T-B2q on the question field) on half B, all 80 and half A.
It is exploratory only, and the deciding reading is unchanged.

**Outputs.** `w2-score.json` and `w2-score.md` in `--out-dir`; an existing one is refused.
- The markdown opens with «# W2 score» and «Own run (W2)», then the manifest's fields as a table, the results
  facts, the laws held, the rules and the sources. Then «Deciding reading», then «Exploratory», then each
  field's tables, with W2 in place of W1.
- In the JSON, `w2_manifest` holds the manifest with its path and sha256; `w2_decision` the deciding reading,
  or `why_not`; `w2_exploratory` the other readings; `fallback_sensitivity` the sensitivity reading.
- The per-item and per-scope keys keep their W1 names (`w1_recall`, `w1_reached`). In a W2 report they hold
  W2's figures.
- No chunk text is written.

**What the gate does not prove.** The manifest is ours and is not signed: one written by hand to match another
file would pass. The ingest tool is its only writer. That the chunks came from the dataset the manifest names
rests on facts the server returned:
- the header's dataset facts, which `run_w1.py` reads from the server;
- each chunk's document name (one of our 22 `<slug>.md` files);
- for the deciding cell, the embedding model the server reports.

A file from another server whose dataset id, counts, document names and embedder all match would still pass.
Two pins are only as good as what was recorded:
- the image digest is not pinned (above);
- the version must be exactly `v0.27.3`. The image writes `git describe --tags --match=v* --first-parent
  --always` into its VERSION file (v0.27.3 `Dockerfile:267-269`). For a release built at the tag
  (`.github/workflows/release-python.yml:79`) that is exactly `v0.27.3`. A build after the tag reports
  `v0.27.3-N-g<hash>` and is refused. If the real server reports a suffix, that is a fact to look into, not a
  reason to widen the match.

### Tests

```bash
cd "/d/Iqraa Law/AI Harness-w1/tools/ragflow-w1" && python -B -X utf8 -m unittest tests.test_intake_w1 tests.test_score_w1 -v
```

- **`tests/test_intake_w1.py`**, 46 tests. They cover:
  - the contract refusals, the `counts` and `settings` checks, and every setting name `run_w1.py` sends;
  - the secret and address patterns, IPv6 included, with the accepted cases: the redacted Bearer, document
    names, clause numbers, the header's times;
  - the copy and the manifest: no fixture text reaches the terminal or the manifest;
  - the pattern counts in chunk content, document names, errors and the header;
  - the hash comparison with the package, the client-data and folder refusals, and a link named `quarantine`
    to another folder;
  - the screening gate: pending, flagged, a flagged screen recorded clear afterwards, the history, a changed
    file, a cleared pair copied out of quarantine, and a manifest edited to declare client data.
- **`tests/test_score_w1.py`**, 127 tests: 59 for W1 (the 57 from before W2, and 2 added in the third review)
  and 68 for W2. The W1 ones cover:
  - the bit-parallel LCS, over the whole chunk and over every stretch, against the dynamic programme;
  - the mapping-rule cases above;
  - the candidate restriction against full scans;
  - the budget, the cut (a space exactly at the budget included) and the three crossing rules;
  - the held, lacking and stratum scopes, an under-half item on a law he lacks, items whose articles he lacks,
    no reading when nothing is held, and the arm through the rule;
  - decision rule (c): W1 beating on held recall, the arm beating W1, and the through-rule reading differing
    from the key reading;
  - the inference of laws held by best source (the article held most within one stretch), and given laws
    refused or warned about against that evidence;
  - `--articles-lacking`, our best arm, the bootstrap against the bench's code and its determinism (on a
    fixture whose ends differ from their neighbours, so an off-by-one at either end fails), and an end that is
    zero in exact arithmetic not read as above or below zero;
  - the sent-text check, with a two-field file.

  The real-data tests need `.hq/scratch/rag-bench` and `eval-final.json`. They check that the strata are the
  spec's 17, that the A0 self-check gives back 0.5625, the null control at 1,200 characters, that a scored file
  writes no chunk text, that civil-code 107 lacking leaves civil-code-01 out of the held scopes, and one rule (c)
  interval pinned in split order: W1 (A0's own text) minus T-B2 on all 80, -0.2896 [-0.3875, -0.1896]. In the
  eval set's order the same differences give [-0.3937, -0.1875].

  The 68 W2 tests cover:
  - the own-run gate: our file beside its manifest accepted; refused for a Walid-shaped file with no manifest,
    the same file beside our manifest, a file outside `out/`, a file one folder below `out/<engine>/`, a link
    under another name, a dataset id other than the manifest's, a second dataset beside ours, a manifest whose
    `all_match` is not `true` (`false`, `"false"`, `"true"`, `1`), a document or chunk count other than the
    manifest's, header hashes other than the package's, settings other than the arm's (and the `rt` file
    accepted), settings that differ from v3 only in `similarity_threshold`, `top_k` or an added `rerank_id`, a
    server version other than the manifest's, a URL in a chunk (the screens still
    run), a manifest not beside the results or naming another engine, a file not named for an arm, a chunk from a
    document named like Walid's, and 16 manifests that break the contract, one per check (`w2`, `created_at`,
    the image digest, the batch size, both hashes, the revision, `v0.27.30` among them); a registry without
    the manifest's 22 laws; and every registry slug's `<slug>.md` accepted;
  - the arm settings against `run_w1.py`'s own parser;
  - the options: W2 options without `--own-run`, `--own-run` without a manifest or with `--laws-held`; and
    `--w2-decide` refused before the library loads, through `main`, for an Infinity file, a `--split` with
    another sha256, and a header whose server-reported embedder is not Qwen3;
  - the split: each item's half, in the file's key order; only the bench split recorded as pinned; refused for
    an id outside the set, a missing id, a third half and unequal halves; the durable copy first, the bench's
    with a warning, and a refusal when neither exists; arm sources from the durable copy, the bench's with a
    warning, and A0q's bench-only file with none; T-B2's source for the `--w2-decide` gate (the durable copy,
    the bench's, or none); and, with no bench folder, a refusal through `main` (exit 2) that names both
    bench-only files;
  - the half scopes, with and without a split, and each scope handed to the bootstrap in the split's order;
  - the deciding reading on 40 half-B items: a win, a loss (noted as behind, below zero) and a tie (noted as not
    detectable); three more items not shown and four a win; half A ignored; T-B2 through the rule, not by its
    keys; an expected article W2 serves only past T-B2's budget counted as a miss; a failed half-B line listed
    and counted as a miss, a failed half-A line not listed; no verdict for a
    file that is not the deciding cell; no gap for the deciding cell; each gap (engine, embedder, revision,
    canvas, arm, field, split, T-B2's rows not durable, another sha or missing); the server's embedding model
    (another model, a longer name, another provider, none) as gaps, an opaque tenant-model id as none; the
    printed «not shown» line;
  - own-run scoring on a fixture: every law held, nothing lacking, no warning; a server embedder other than the
    manifest's warned about and not deciding; an opaque tenant-model id warned about and still deciding; the
    report's «own run (W2)», the manifest's fields and no wording about his corpus; `w2-score.*` with no chunk
    text; the fallback sensitivity emptying its items and leaving the deciding reading alone; in a two-field
    file, question ids in the fallback emptying only the question field's items;
  - the fallback file: read per field; refused for another arm, a field the file lacks, an id with no chunks and
    an id given twice;
  - real data: the arms and the split from the durable copies, with no warning; half B in the split's order gives
    back PROOF-rag-bench.md's +0.132 [+0.019, +0.248]; a W1 report's held items of each half (9 and 7 of 16);
    T-B2's own top-5 text as an own run, which ties T-B2 on half B and reads «not shown» with all 22 laws held;
    and `--w2-decide` end to end through `main`, the deciding reading printed before «Exploratory».
- **Each check was shown to be tested.** On 2026-11-08, after the review fixes, 32 checks were each replaced by
  a broken version at run time, and both test modules were run each time. The script is
  `.hq/scratch/w1-scorer-fix/mutants.py`, built from the review's. Each time a test failed:
  - the review's 17: the interval's sign; the side of zero read; stratum ∩ held ignoring held; the reading
    strings swapped; the decision on all 80 and the whole stratum; the client-data flag at scoring; a space
    exactly at the budget; laws held ignored; W1 recall capped at 5; an `ok` line with an error; the quarantine
    root not resolved through links; the field filter; the through-rule interval against the arm's keys; our
    best arm by hit@5; given laws ignored; Arabic-Indic digits in the counts; the crossing chunk never cut;
  - 15 of the fixes: the stretch dropped; a stretch of 2n; the last stretch never tested; a sliding bound that
    only falls; an item «lacking» when any expected article is; an unevidenced given law kept; the scoring gate
    without the folder checks; a flagged screen recorded clear; IPv6 not refused; settings names and counts
    names not checked; the header and the document names and errors not counted on their own; the best source
    by whole-chunk LCS; the screening history overwritten.
  - The best-source check first survived (no test failed). A test was added for it, and the mutant was run
    again: a test failed.
- **The W2 checks were shown to be tested** (2026-11-08, after the second review). 28 checks were each
  replaced by a broken version at run time, and the W2 test classes were run each time
  (`.hq/scratch/w2-review-score/mutants3.py`, log `logs/mutants3.txt`). A test failed every time: 28 of 28.
  They include the 10 that had survived the review (the link name, five manifest keys, the half-B filter of
  failed lines, the split always pinned, `main`'s split to the deciding gate, the embedder warning), and
  each new check: the server's embedder, provider and name match, the revision and canvas pins, the split
  order in `score_field` and `load_split`, the document names and the registry count, the exact version,
  the folder depth, the below-zero note, T-B2's durable source and sha, and the missing-split refusal.
- **The third review's checks were shown to be tested** (2026-11-08). The six mutants of the second review that
  had survived (`.hq/scratch/w2-review-score/r2/mutants4.py`, run again unchanged, log `r3/mutants4-r3.txt`)
  are now each killed: two
  datasets accepted, settings compared on the vector weight only, the upper end one place higher, W2's chunks
  counted past the budget (now by the fast `W2DecisionTests`, not only the real-data ones), a truthy
  `all_match`, and the query ids emptying every field. The fixes' own mutants
  (`.hq/scratch/w2-review-score/r3/mutants6.py`, log `r3/mutants6.txt`; the real-data caches cleared before each
  run) are each killed too: no tolerance at either end, the upper end one place higher or lower, the eval set's
  order with a split loaded, no missing-source check, and `load_context` outside `main`'s refusal.

### What this does not prove

- **It has not met a real results file.** `run_w1.py` and these scripts were written to the same contract, by
  different builders. One join check was run on 2026-11-08, not kept as a test: `run_w1.py` against
  `tests/fake_ragflow.py` on the 80 real queries, then intake and score. Intake took the file, both header
  hashes matched the package, and scoring ran. The fake's chunks hold no law text, so no law was inferred
  held, and the reading was «cannot be read». The check was repeated after `run_w1.py` changed at 08:20, and
  again after the review fixes, with the same result. The settings and counts `run_w1.py` writes passed the
  stricter header checks.
- **The mapping rule is a proxy.** Its answer depends on chunking: an article split in three is served but not
  retrieved. The stretch limit is our reading of «in order», tuned on runs of our own articles; his chunks may
  differ from them. The «crossing chunk» and «through the rule» tables show how much the reading moves.
- **Which laws and articles his dataset holds is his to say.** The inference reads his chunks; `--laws-held`
  and `--articles-lacking` state it. Neither is checked against his server.
- **Bare host names are not caught.** A host name with no scheme (`ragflow.example.org`) in an error string
  passes intake. URLs, `localhost` and IP addresses are refused.
- **The question-field arms are recorded rows, not A1q.** A1q (spec Part 1) has not run. When it does, it
  replaces them as «our best arm» on that field.
- **The bench folder is still needed.** T-B2, T-B3d, B1q, T-B2q, T-B3dq, B4q and the split are read from their
  durable copies in `p3-evidence/`. A0q's rows and the strata's recorded query terms (`data/eval.jsonl`) have
  none, and are read from `.hq/scratch/rag-bench` at each run. Each source's path and sha256 is recorded in the
  report. If the bench folder goes, the scorer cannot score: it refuses, naming the missing files. Copying the
  two into `p3-evidence/` and adding them to `DURABLE` would close this. Their sha256 on 2026-11-08:
  `results/perf/pg-rows-question.jsonl` `6e72dd666cef13e8ce965049dcfa0c7748bd4cb71d6c8e5557cbbe65c4be2901`,
  `data/eval.jsonl` `d9538dd041b7b8e9e4ec45c9c4b4f16db9cf4723db832e4ec4eab74e3a60024b`.
