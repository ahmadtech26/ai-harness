# ragflow-export

A read-only exporter for a RAGFlow server. It copies datasets, original documents and parsed chunk
text into a quarantine folder through RAGFlow's HTTP API, with a manifest of counts and SHA-256
hashes. It uses the Python standard library only: Python 3.11 or later, nothing to install.

**It has never been run against a real RAGFlow server.** It has only met the local fake server in
`tests/fake_ragflow.py`. Read [What this does not prove](#what-this-does-not-prove) before you rely on it.

## Before running it

- **Permission.** Run it only with the data owner's agreement, against his server, using a key he
  created for this purpose. We hold no access today.
- **A dedicated key.** As far as the research found, RAGFlow API keys have no read-only scope: the
  token record has no scope field. Any key can write and delete within its tenant. This tool is
  read-only because of how its client is written, not because of the key. Ask the owner to create
  one key for the export (avatar > API in the RAGFlow UI) and to delete it once the export is done.
- **The key goes in a file**, alone on one line, outside every repository. The tool has no option
  that takes the key itself.
- **Use https.** Plain `http://` is accepted only for this machine (localhost, 127.0.0.1, ::1),
  unless you pass `--allow-insecure-http`.
- **Dry run first.** `--dry-run` lists datasets and documents with the counts the server reports.
  It downloads nothing and writes no file.

## Running it

From the repository's `tools/ragflow-export` folder:

```bash
# Windows, Git Bash (-X utf8 lets Arabic names print in a pipe)
python -X utf8 -m ragflow_export --base-url https://ragflow.example.org --api-key-file /c/path/outside/repos/ragflow.key --dry-run
python -X utf8 -m ragflow_export --base-url https://ragflow.example.org --api-key-file /c/path/outside/repos/ragflow.key

# WSL
python3 -m ragflow_export --base-url https://ragflow.example.org --api-key-file /path/outside/repos/ragflow.key --dry-run
```

| Option | Meaning |
|---|---|
| `--base-url URL` | The server, for example `https://host:9380` or `https://host/prefix`. No user, password, query or fragment. |
| `--api-key-file PATH` | A file that holds the key alone. Its content is never printed. |
| `--out PATH` | The export folder. It must not exist yet or must be empty, and its parent must exist. Once symlinks and junctions are resolved, it must sit inside a folder named `quarantine` and outside every repository (no `.git` folder or file in it or in any folder above it). The default is `D:/Iqraa Law/.hq/quarantine/ragflow-export`, or `/mnt/d/...` under WSL. That location is gitignored, and no folder above it held a `.git` on 2026-11-06. |
| `--dataset ID_OR_NAME` | Export only this dataset. Repeatable. It matches an id, or an exact name compared after Unicode NFC. A value that matches nothing is refused before anything is written. |
| `--dry-run` | List only. |
| `--show-names` | Print dataset and document names in a dry run. Names are hidden by default because they may hold client facts. |
| `--resume` | Continue an unfinished export in `--out`. |
| `--probe-version` | Also `GET /api/v1/system/version`. That route's full path is not confirmed (see below). |
| `--page-size N` | Page size for listings, 1 to 1000 (default 30, RAGFlow's documented default). |
| `--max-attempts N` | Attempts per request on 429, 5xx, a dropped connection or a cut-off body (default 5). |
| `--timeout S` | Seconds per request (default 60). |
| `--ca-file PATH` | A CA bundle for a server with a private certificate. Certificate checks cannot be turned off. |
| `--allow-insecure-http` | Allow `http://` to another host. This sends the key unencrypted. |
| `--allow-non-quarantine-out` | Allow an `--out` that is not inside a `quarantine` folder, or that is inside a repository. |

Exit codes: `0` done; `1` stopped or incomplete, resumable with `--resume`; `2` refused before
anything was sent or written, including any mistyped argument; `130` interrupted.

## What it does

1. **It refuses before sending anything** when it finds a malformed base URL, a key file problem,
   `http` to a remote host, or an unsuitable output folder. An unsuitable folder is one outside a
   quarantine once links are resolved, one inside a repository, one whose parent is missing, one
   holding files this tool did not write, one that already holds a complete export, one holding an
   unfinished export without `--resume`, or an unfinished export from another server or another
   filter.
2. **It lists datasets** and applies `--dataset`.
3. **It creates the folder** (mode 700 where the system supports it). It writes `README.md` first:
   a quarantine notice saying the folder may hold client facts and must not enter the library
   before review. It then writes `export-state.json`.
4. **It handles each dataset in turn.** It lists the dataset's documents. For each document it
   streams the original to a temporary file and checks the length against `Content-Length`. Only a
   whole file is renamed into place. It then fetches every chunk page and writes `chunks.jsonl`
   (UTF-8, Arabic kept as is). Last, it writes `done.json` with each file's hash.
5. **When every document has succeeded**, it writes `SHA256SUMS` and then `manifest.json`. The
   manifest holds counts, per-file hashes, warnings, the routes used, and what was not exported.
   An export is complete only when `manifest.json` exists.

```
README.md  export-state.json  datasets.json  SHA256SUMS  manifest.json
datasets/<dataset id>/dataset.json
datasets/<dataset id>/documents.json
datasets/<dataset id>/documents/<document id>/{document.json, original.<ext>, chunks.jsonl, done.json}
```

Folder names come only from server ids that pass a strict check (letters, digits, `_`, `-`).
Windows device names (`CON`, `PRN`, `AUX`, `NUL`, `COM0` to `COM9`, `LPT0` to `LPT9`, in any letter
case) are refused. So are two ids that differ only in letter case: on a case-insensitive disk (NTFS,
and `/mnt/d` under WSL) they would share one folder. Two such datasets stop the run before anything
is written; the second of two such documents in one dataset is a failure for that document. Real
RAGFlow ids are believed to be lowercase hex, so this should only meet an odd or hostile server; that
belief was not checked against a real server.
A document's own name, such as `../../x.pdf` or `عقد/إيجار: نموذج؟.docx`, never becomes a path. It is
kept in `document.json` and the manifest, and only a plain ASCII extension is reused. Check the
files with `sha256sum -c SHA256SUMS` from inside the export folder.

**Terminal output.** Every line the tool prints, in a dry run, in the export log and in its error
messages, passes through one filter first. C0 and C1 control characters (escape sequences, a carriage
return or newline that could fake a console line), DEL, U+2028 and U+2029, and the bidi embedding,
override and isolate characters (U+202A to U+202E, U+2066 to U+2069) are printed as `\uXXXX`. Files
keep the server's text as served.

**Warnings.** These are recorded in the manifest and do not stop the export:
- a downloaded size that differs from the listed size;
- a chunk count that differs from the document's `chunk_count` or the chunk listing's `total`;
- duplicates while paging;
- a document count that differs from the dataset's `document_count`;
- a finished document whose files no longer matched their hashes on resume, and so was exported again.

## Read-only, and how the tests show it

- The client sends **GET only, and only to these routes**. Any other method (POST, PUT, PATCH,
  DELETE, HEAD, OPTIONS) and any other path raises `ReadOnlyViolation` before a connection is
  opened. Ids in paths must pass the same strict check. The tests that show it:
  - `ReadOnlyTests` shows that refused calls reach the fake server zero times.
  - `test_sends_only_get_requests_to_the_confirmed_routes` checks every request the fake recorded
    during a full export against an independent list of the confirmed routes.
- **Redirects are refused.** urllib would otherwise forward the `Authorization` header to the
  redirect target, even on another host. The test checks that the second server is never contacted.
- **Environment proxies are ignored.**
- **The key** is read from a file and sent only as `Authorization: Bearer`. It is redacted from
  every server message, kept out of `repr`, logs and files, and there is no command-line option for
  it. Argument abbreviations are off: otherwise `--api-key <key>` would be read as
  `--api-key-file <key>`, and the "cannot read file" error would print the key. An argument error
  never repeats what was typed, because argparse would otherwise echo a stray key in
  "unrecognized arguments" or "invalid value"; only the list of missing required options is printed
  as is. The tests search the whole export and the CLI output for the key, including when the server
  echoes it back and when the key is typed as an unknown option, a stray argument or an option value.
  One case is not covered: a key typed in place of the key file's path (`--api-key-file <key>`) is
  named in the "cannot read the API key file" error.
- **Each safety check was shown to be tested.** Each was removed in a copy of the code, and its test
  then failed. The 27 checks are:
  - the method check and the route allowlist;
  - redirect refusal and redaction;
  - the length check and the JSON-error check on downloads;
  - the https rule and the overwrite refusal;
  - skipping finished documents on resume, and hash verification on resume;
  - the quarantine rule, and safe file names;
  - the abbreviation switch and Retry-After;
  - hidden names in a dry run, and paging past a capped page size;
  - argument errors that repeat nothing typed;
  - the terminal filter, in the CLI log and in the dry run;
  - Windows device names, and ids that differ only in letter case, for documents and for datasets;
  - link resolution in the quarantine rule, and the refusal of a folder inside a repository;
  - a done record that names another document, and a done record that names a file the tool does not
    write;
  - the exit on a file-system error.

## Retries, failures, resume, pagination

- **Retries.** 429, 500, 502, 503, 504, dropped connections and cut-off bodies are retried up to
  `--max-attempts` times. The backoff is 1, 2, 4 ... seconds, capped at 60, and a numeric
  `Retry-After` is honoured up to 300 s. Other 4xx statuses and RAGFlow error codes are not retried.
  HTTP 401 or 403, or RAGFlow code 109, stop the run.
- **Per-document failures** are recorded and the run carries on: an HTTP or API error, an
  unexpected response shape, a pagination fault, or an unsafe id. Such failures leave the export
  *incomplete*: the run exits 1, writes no manifest, and lists the errors in `export-state.json`.
  If three documents in a row fail on the network, the run stops.
- **File-system errors** (a full disk, a permission refused, a file where a folder should be, an
  unreadable state file) stop the run with exit 1. The tool prints the error's type and path and,
  when an unfinished export exists, the resume hint. It prints no traceback.
- **Resume** (`--resume`, after a failure, a crash or Ctrl-C):
  - It reuses the dataset and document listings saved earlier, so documents added to the server
    after the first run are not picked up.
  - It skips a document only if its `done.json` exists, names this dataset and this document, names
    only the files the tool writes (`chunks.jsonl` and `original.<ext>`), and every file still
    matches its hash.
  - A `done.json` that names another document is a failure for that document, and the folder is
    left as it is. A `done.json` that names any other file, such as an absolute or `..` path, is not
    trusted, and the document is exported again.
  - It redoes everything else, overwriting that document's own unfinished files.
- **Pagination** sends `page=1,2,...` with `page_size`.
  - It stops at the reported `total`. When there is no total, it stops at the first short page.
  - It keeps going when the server returns fewer items per page than asked.
  - If a page repeats only items already seen, it stops with an error. This guards against a
    server that ignores `page`.

## Routes

Routes and parameters come from the research of 2026-11-04 (RAGFlow v1.0.0-rc3 `router.go` and
HTTP API reference; v0.27.3 uses the same dataset, document and chunk paths).

| Route | Status |
|---|---|
| `GET /api/v1/datasets?page&page_size` | confirmed |
| `GET /api/v1/datasets/{dataset_id}/documents?page&page_size` | route confirmed; the `page`/`page_size` parameters are assumed from the datasets route |
| `GET /api/v1/datasets/{dataset_id}/documents/{document_id}` (file bytes) | confirmed |
| `GET /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks?page&page_size` | confirmed |
| `GET /api/v1/system/version` | **unconfirmed**: the route exists in rc3's unauthenticated group, but its full path was not confirmed; sent only with `--probe-version`, and a failure is recorded, not fatal |

Not used:
- `POST /api/v1/retrieval`, single-chunk routes, `GET /api/v1/datasets/{id}`, the graph and artifact
  routes, and every write route.
- `/api/v1/system/tokens`, which lists keys. The client refuses it.

## What this does not prove

- **It has never met a real RAGFlow.** The fake server was written by the same author from the same
  understanding of the API, so the tool and the fake would share any misunderstanding of it.
- **The JSON field names are not confirmed.** `code`, `message`, `data`, `data.docs`,
  `data.chunks` and `total` come from the author's reading of the v0.x HTTP API reference. The
  research confirmed routes and parameters, not field names. Any other shape stops the run with
  `ShapeError`, which names the keys it saw. The tool does not guess. The v1.0 Go rewrite may
  differ.
- **The error behaviour is assumed.** The assumptions are:
  - code 109 means a refused key;
  - a failed download answers HTTP 200 with a JSON error;
  - a JSON body (`Content-Type: application/json`) with a non-zero `code` and a `message` is an error.

  The last rule would misread a genuine `.json` original that has exactly that shape.
- **Large documents.** How the chunk listing behaves past Elasticsearch's `max_result_window`
  (default 10,000) was not traced. The tool compares counts and warns, but it cannot fetch what the
  server will not page to.
- **Consistency.** If the server changes during an export, the listings can shift. Duplicates are
  detected, and missed items show only as count warnings. The tool is not a point-in-time snapshot.
- **It is not a backup.** Nothing here can be restored into RAGFlow. Embeddings are not exported,
  because the API strips them. Dataset settings beyond the listing fields, graphs, agents, chats
  and users are not exported either. A full copy would need a Docker volume backup, which the
  retrieval spec no longer requests: it would hold the whole store, client files included
  (`.hq/docs/specs/spec-rag-system.md`, the safe path, step 2).
- **It says nothing about text quality.** The tests show that chunk text is saved byte for byte as
  served, including harakat, hamza forms, Arabic punctuation, Arabic-Indic digits, tatweel, U+200F
  and U+FEFB. They say nothing about whether RAGFlow extracted it correctly. The research found
  weak points in its Arabic handling: no Arabic in the built-in OCR dictionary, no right-to-left
  handling found in PDF glyph ordering, and no `المادة` article marker. Treat every chunk as
  unverified and never as law text of record.
- **Not tested:**
  - real TLS (the tests use http on loopback), private CAs and proxies;
  - chunked transfer encoding, very large files, and a full disk;
  - Windows path-length limits (a long `--out` plus two 32-character ids may pass 260 characters);
  - two runs on one folder at the same time (there is no lock).
- **Read-only covers the client only.** None of these routes should change server state according
  to the docs, but the tool cannot prove what the server does on a GET. Older servers (before
  v0.27.3) had a tenant-authorisation gap on the download route, per one release note. That gap
  matters for the owner's security, not for this tool's correctness.

## Tests

```bash
# Windows, Git Bash
cd tools/ragflow-export && python -B -X utf8 -m unittest discover -s tests -t . -v
# WSL
cd tools/ragflow-export && python3 -B -m unittest discover -s tests -t . -v
```

- **The suite** is 78 tests. On 2026-11-06 it passed under Python 3.11.9 on Windows and 3.13.5 in
  WSL. The temporary folders sit on NTFS (case-insensitive) on Windows and on ext4 (case-sensitive)
  in WSL, so the letter-case tests ran on both kinds of disk. The link test uses a junction on
  Windows and a symlink in WSL.
- **The fake server** in `tests/fake_ragflow.py` binds to 127.0.0.1 on a free port and contacts
  nothing. It records every request, whatever the method.
- **Its data** is invented Arabic test text, not law text and not client data. The API key is a
  random value made fresh on each run.
- **The tests contact no real server.**
