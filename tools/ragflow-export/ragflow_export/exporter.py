"""Export RAGFlow datasets, documents and parsed chunks into a quarantined folder, or only list them.

Layout of an export folder:

    README.md                                   quarantine notice, written before any data
    export-state.json                           progress, failures and warnings of each run
    datasets.json                               the selected datasets, as listed
    datasets/<dataset id>/dataset.json
    datasets/<dataset id>/documents.json        every document of the dataset, as listed
    datasets/<dataset id>/documents/<document id>/document.json
    datasets/<dataset id>/documents/<document id>/original.<ext>
    datasets/<dataset id>/documents/<document id>/chunks.jsonl
    datasets/<dataset id>/documents/<document id>/done.json      written last for that document
    SHA256SUMS                                  every file above, for `sha256sum -c`
    manifest.json                               written last of all: it marks a complete export

Folder names are server ids that passed files.safe_id and are unique ignoring letter case; a document's
own name is kept only as data. Every line meant for a terminal passes through for_terminal first.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TextIO

from ragflow_export import __version__
from ragflow_export.client import ROUTES, RagflowClient, as_count
from ragflow_export.errors import (ApiError, FilterError, HttpError, IncompleteExport, OutDirRefused,
                                   PaginationError, RequestFailed, ShapeError, TransportError, UnsafeIdentifier)
from ragflow_export.files import (TMP_SUFFIX, folder_key, is_own_file_name, read_json, safe_extension, safe_id,
                                  sha256_file, write_atomic, write_json)

__all__ = ['ExportOptions', 'TMP_SUFFIX', 'dry_run', 'export', 'for_terminal', 'plan_out_dir', 'select_datasets']

README_NAME = 'README.md'
STATE_NAME = 'export-state.json'
DATASETS_NAME = 'datasets.json'
MANIFEST_NAME = 'manifest.json'
SUMS_NAME = 'SHA256SUMS'
FORMAT_VERSION = 1
OS_NOISE = {'desktop.ini', 'thumbs.db', '.ds_store'}
TRANSPORT_FAILURES_BEFORE_STOP = 3
PER_DOCUMENT_ERRORS = (HttpError, ApiError, ShapeError, PaginationError, UnsafeIdentifier)
NOTICE = ('May hold client facts. Quarantined: must not enter the library, the corpus or any repository before '
          'a lawyer reviews it and the owner approves. Chunk text is RAGFlow extraction, unverified, never law '
          'text of record.')
NOT_INCLUDED = [
    'embeddings: the RAGFlow dataset API does not return them',
    'dataset settings beyond the fields the dataset listing returns',
    'knowledge graph and artifact routes',
    'chat assistants, agents, conversations, users and API keys',
]


# C0 and C1 controls (escape sequences, a carriage return or a newline that could fake a line), DEL, the
# line and paragraph separators, and the bidi embedding, override and isolate characters.
_NOT_FOR_TERMINAL = re.compile('[\x00-\x1f\x7f-\x9f  ‪-‮⁦-⁩]')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def for_terminal(text: object) -> str:
    """Server text (ids, names, statuses, error messages) as one inert line: unsafe characters become \\uXXXX."""
    return _NOT_FOR_TERMINAL.sub(lambda match: f'\\u{ord(match.group()):04x}', str(text))


def _log_stderr(message: str) -> None:
    print(for_terminal(message), file=sys.stderr)


@dataclass(frozen=True)
class ExportOptions:
    out_dir: Path
    dataset_filter: tuple[str, ...] = ()
    resume: bool = False
    page_size: int = 30
    allow_non_quarantine_out: bool = False
    probe_version: bool = False
    show_names: bool = False
    now: Callable[[], str] = utc_now


def _normalise(text: str) -> str:
    return unicodedata.normalize('NFC', text).strip()


def _filter_key(options: ExportOptions) -> list[str]:
    return sorted({_normalise(value) for value in options.dataset_filter})


def select_datasets(datasets: list[dict], wanted: tuple[str, ...]) -> list[dict]:
    """Datasets whose id or name equals a wanted value (names compared in Unicode NFC). Refuses a value that matches none."""
    if not wanted:
        return list(datasets)
    keys = {_normalise(value) for value in wanted}

    def matches(dataset: dict, key: str) -> bool:
        return dataset.get('id') == key or _normalise(str(dataset.get('name', ''))) == key

    unmatched = [value for value in wanted if not any(matches(d, _normalise(value)) for d in datasets)]
    if unmatched:
        raise FilterError(f'--dataset matched no dataset: {", ".join(unmatched)}. A --dry-run lists the ids '
                          '(add --show-names to see names)')
    return [dataset for dataset in datasets if any(matches(dataset, key) for key in keys)]


def _repository_root(path: Path) -> Path | None:
    """The nearest folder at or above `path` that holds a .git folder or file (a worktree has a file)."""
    return next((folder for folder in (path, *path.parents) if (folder / '.git').exists()), None)


def plan_out_dir(options: ExportOptions) -> str:
    """'new' or 'resume', or OutDirRefused. Reads the folder but never changes it."""
    out = Path(options.out_dir)
    # Resolved, so a symlink or a junction cannot carry a "quarantine" path into another folder.
    absolute = Path(os.path.realpath(out))
    if not options.allow_non_quarantine_out:
        if 'quarantine' not in (part.lower() for part in absolute.parts):
            raise OutDirRefused(f'{out} is not inside a folder named "quarantine" (resolved: {absolute}), and an '
                                'export may hold client facts; pass --allow-non-quarantine-out only for a place as '
                                'private and as untracked')
        repository = _repository_root(absolute)
        if repository is not None:
            raise OutDirRefused(f'{out} is inside the repository {repository}, and an export may hold client facts; '
                                'choose a quarantine outside every repository, or pass --allow-non-quarantine-out '
                                'only for a place as private and as untracked')
    if not absolute.parent.is_dir():
        raise OutDirRefused(f'the parent folder of {out} does not exist; create it on purpose first')
    if absolute.exists() and not absolute.is_dir():
        raise OutDirRefused(f'{out} exists and is not a folder')
    names = {path.name for path in absolute.iterdir()} if absolute.is_dir() else set()
    if MANIFEST_NAME in names:
        raise OutDirRefused(f'{out} already holds a complete export, which is never overwritten; choose another --out')
    if STATE_NAME in names:
        if options.resume:
            return 'resume'
        raise OutDirRefused(f'{out} holds an unfinished export; pass --resume to continue it, or choose another --out')
    if any(name.lower() not in OS_NOISE for name in names):
        raise OutDirRefused(f'{out} is not empty and was not written by this tool; choose an empty or a new folder')
    if options.resume:
        raise OutDirRefused(f'there is no unfinished export in {out} to resume')
    return 'new'


def readme_text(base_url: str, started: str) -> str:
    return f"""# RAGFlow export: quarantined

تنبيه: هذا المجلد معزول. قد يحتوي على وقائع ومعلومات تخص موكلين. لا يُنقل أي شيء منه إلى المكتبة أو إلى أي مستودع قبل مراجعته والموافقة عليه.

Written by ragflow-export {__version__} from {base_url}, started {started}.

- This folder may hold client facts: in the original files, in dataset and document names, and in the chunk text.
- It must not enter the library, the law corpus, the evaluation set, prompts or any repository before a lawyer
  has reviewed it and the owner has approved it. Nothing here is approved.
- Chunk text is RAGFlow's own extraction. It is unverified and is never law text of record: compare it with
  the official source first.
- Embeddings are not here: the RAGFlow API does not return them.
- Share it only with the people doing the review, by a private route agreed with the data owner. Keep and
  delete it as agreed with the data owner.
- The export is complete only when manifest.json exists. Check the files with `sha256sum -c SHA256SUMS`
  from this folder.
"""


def _probe_version(client: RagflowClient) -> dict:
    route = next(route for route in ROUTES if route.name == 'system_version')
    record: dict = {'route': route.template, 'confirmed': route.confirmed}
    try:
        record['value'] = client.server_version()
    except RequestFailed as error:
        record['error'] = f'{type(error).__name__}: {error}'
    return record


def _document_warnings(document: dict, size: int, chunks) -> list[str]:
    warnings = []
    reported_size = as_count(document.get('size'))
    if reported_size is not None and reported_size != size:
        warnings.append(f'downloaded {size} bytes; the document listing reported {reported_size}')
    fetched = len(chunks.items)
    reported_chunks = as_count(document.get('chunk_count'))
    if reported_chunks is not None and reported_chunks != fetched:
        warnings.append(f'fetched {fetched} chunks; the document listing reported {reported_chunks}')
    if chunks.total_reported is not None and chunks.total_reported != fetched:
        warnings.append(f'fetched {fetched} chunks; the chunk listing reported a total of {chunks.total_reported}')
    if chunks.duplicates:
        warnings.append(f'the chunk listing repeated {chunks.duplicates} chunks while paging')
    return warnings


def _claim_folder(claimed: dict[str, str], identifier: str, kind: str) -> None:
    """Record that `identifier` owns its folder; refuse an id that would share it with another one."""
    holder = claimed.setdefault(folder_key(identifier), identifier)
    if holder != identifier:
        raise UnsafeIdentifier(f'refused {kind} id {identifier!r}: it differs from {holder!r} only in letter case, '
                               'and both would share one folder on a case-insensitive disk')


def _verified_done(doc_dir: Path, dataset_id: str, document_id: str) -> tuple[dict | None, str | None]:
    """The document's done record if every file it names still has its recorded hash, else a reason to redo it.

    A record that belongs to another document raises UnsafeIdentifier: redoing it would overwrite that document.
    """
    path = doc_dir / 'done.json'
    if not path.is_file():
        return None, None
    try:
        done = read_json(path)
        owner = (done['dataset_id'], done['document_id'])
    except (ValueError, KeyError, TypeError, OSError):
        return None, 'its done record could not be read'
    if owner != (dataset_id, document_id):
        raise UnsafeIdentifier(f'the folder of document {document_id!r} holds the done record of document '
                               f'{owner[1]!r} in dataset {owner[0]!r}; it is left as it is')
    try:
        for key in ('original', 'chunks'):
            name = done[key]['path']
            if not is_own_file_name(name):
                return None, f'its done record names a file this tool does not write ({name!r})'
            file = doc_dir / name
            if not file.is_file() or sha256_file(file) != done[key]['sha256']:
                return None, f'{name} no longer matched its recorded hash'
    except (KeyError, TypeError, OSError):
        return None, 'its done record could not be read'
    return done, None


class _Run:
    def __init__(self, client: RagflowClient, options: ExportOptions, state: dict, log: Callable[[str], object]):
        self.client = client
        self.options = options
        self.out = Path(options.out_dir)
        self.state = state
        self.log = log
        self.folders: dict[str, dict[str, str]] = {}  # dataset id -> folder key -> the document id that has it

    def save(self) -> None:
        write_json(self.out / STATE_NAME, self.state)

    def warn(self, dataset_id: str, document_id: str | None, message: str) -> None:
        self.state['warnings'].append({'dataset_id': dataset_id, 'document_id': document_id, 'message': message})

    def fail(self, dataset_id: str, document_id: object, error: Exception) -> None:
        self.state['failures'].append({'dataset_id': dataset_id, 'document_id': document_id,
                                       'error': type(error).__name__, 'message': str(error)})

    def datasets(self, datasets: list[dict]) -> None:
        transport_streak = 0
        for index, dataset in enumerate(datasets, start=1):
            dataset_id = safe_id(dataset.get('id'))
            folder = self.out / 'datasets' / dataset_id
            documents = self.documents(folder, dataset)
            self.log(f'dataset {index}/{len(datasets)} {dataset_id}: {len(documents)} documents')
            for position, document in enumerate(documents, start=1):
                label = f'  document {position}/{len(documents)} {document.get("id")}'
                try:
                    outcome = self.document(folder, dataset_id, document)
                except TransportError as error:
                    transport_streak += 1
                    self.fail(dataset_id, document.get('id'), error)
                    self.log(f'{label}: failed ({type(error).__name__})')
                    if transport_streak >= TRANSPORT_FAILURES_BEFORE_STOP:
                        raise
                    continue
                except PER_DOCUMENT_ERRORS as error:
                    transport_streak = 0
                    self.fail(dataset_id, document.get('id'), error)
                    self.log(f'{label}: failed ({type(error).__name__})')
                    continue
                transport_streak = 0
                self.log(f'{label}: {outcome}')

    def documents(self, folder: Path, dataset: dict) -> list[dict]:
        listing_path = folder / 'documents.json'
        if listing_path.is_file():
            return read_json(listing_path)
        listing = self.client.list_documents(dataset['id'], self.options.page_size)
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / 'dataset.json', dataset)
        if listing.total_reported is not None and listing.total_reported != len(listing.items):
            self.warn(dataset['id'], None, f'listed {len(listing.items)} documents; the document listing reported '
                                           f'a total of {listing.total_reported}')
        if listing.duplicates:
            self.warn(dataset['id'], None, f'the document listing repeated {listing.duplicates} entries while paging')
        write_json(listing_path, listing.items)
        self.save()
        return listing.items

    def document(self, folder: Path, dataset_id: str, document: dict) -> str:
        doc_id = safe_id(document.get('id'))
        _claim_folder(self.folders.setdefault(dataset_id, {}), doc_id, 'document')
        doc_dir = folder / 'documents' / doc_id
        done, problem = _verified_done(doc_dir, dataset_id, doc_id)
        if done is not None:
            return 'already exported'
        if problem:
            self.warn(dataset_id, doc_id, f'exported again because {problem}')
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / 'done.json').unlink(missing_ok=True)
        write_json(doc_dir / 'document.json', document)
        original = f'original.{safe_extension(document.get("name"))}'
        download = self.client.download_document(dataset_id, doc_id, doc_dir / original)
        chunks = self.client.list_chunks(dataset_id, doc_id, self.options.page_size)
        body = ''.join(json.dumps(chunk, ensure_ascii=False, sort_keys=True) + '\n' for chunk in chunks.items)
        data = body.encode('utf-8')
        write_atomic(doc_dir / 'chunks.jsonl', data)
        write_json(doc_dir / 'done.json', {
            'dataset_id': dataset_id,
            'document_id': doc_id,
            'completed_at': self.options.now(),
            'original': {'path': original, 'sha256': download.sha256, 'bytes': download.size,
                         'content_type': download.content_type},
            'chunks': {'path': 'chunks.jsonl', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                       'count': len(chunks.items), 'total_reported': chunks.total_reported},
            'warnings': _document_warnings(document, download.size, chunks),
        })
        return f'{download.size} bytes, {len(chunks.items)} chunks'

    def manifest(self, datasets: list[dict]) -> dict:
        counts = {'datasets': len(datasets), 'documents': 0, 'documents_exported': 0, 'chunks': 0, 'original_bytes': 0}
        warnings = list(self.state['warnings'])
        entries = []
        for dataset in datasets:
            dataset_id = dataset['id']
            folder = self.out / 'datasets' / dataset_id
            documents = read_json(folder / 'documents.json')
            reported = as_count(dataset.get('document_count'))
            if reported is not None and reported != len(documents):
                warnings.append({'dataset_id': dataset_id, 'document_id': None,
                                 'message': f'listed {len(documents)} documents; the dataset listing reported {reported}'})
            doc_entries = []
            for document in documents:
                doc_dir = folder / 'documents' / document['id']
                done = read_json(doc_dir / 'done.json')
                relative = doc_dir.relative_to(self.out).as_posix()
                doc_entries.append({
                    'id': document['id'],
                    'name': document.get('name'),
                    'parse_status': document.get('run'),
                    'original': {'path': f'{relative}/{done["original"]["path"]}', 'sha256': done['original']['sha256'],
                                 'bytes': done['original']['bytes'], 'content_type': done['original']['content_type'],
                                 'size_reported': as_count(document.get('size'))},
                    'chunks': {'path': f'{relative}/{done["chunks"]["path"]}', 'sha256': done['chunks']['sha256'],
                               'count': done['chunks']['count'], 'count_reported': as_count(document.get('chunk_count')),
                               'total_reported': done['chunks']['total_reported']},
                })
                warnings += [{'dataset_id': dataset_id, 'document_id': document['id'], 'message': message}
                             for message in done['warnings']]
                counts['documents'] += 1
                counts['documents_exported'] += 1
                counts['chunks'] += done['chunks']['count']
                counts['original_bytes'] += done['original']['bytes']
            entries.append({'id': dataset_id, 'name': dataset.get('name'), 'document_count_reported': reported,
                            'chunk_count_reported': as_count(dataset.get('chunk_count')), 'documents': doc_entries})
        probed = self.state.get('server_version') is not None
        return {
            'tool': 'ragflow-export',
            'tool_version': __version__,
            'format_version': FORMAT_VERSION,
            'status': 'complete',
            'notice': NOTICE,
            'base_url': self.client.base_url,
            'dataset_filter': self.state['dataset_filter'],
            'datasets_visible': self.state.get('datasets_visible'),
            'server_version': self.state.get('server_version'),
            'created_at': self.state['created_at'],
            'completed_at': self.options.now(),
            'runs': len(self.state['runs']),
            'routes': [{'name': route.name, 'method': 'GET', 'path': route.template, 'confirmed': route.confirmed,
                        'note': route.note} for route in ROUTES if route.confirmed or probed],
            'counts': counts,
            'datasets': entries,
            'warnings': warnings,
            'not_included': NOT_INCLUDED,
        }

    def write_sums(self) -> str:
        lines = []
        for path in sorted(p for p in self.out.rglob('*') if p.is_file()):
            relative = path.relative_to(self.out).as_posix()
            if relative not in (SUMS_NAME, MANIFEST_NAME):
                lines.append(f'{sha256_file(path)}  {relative}\n')
        data = ''.join(lines).encode('utf-8')
        write_atomic(self.out / SUMS_NAME, data)
        return hashlib.sha256(data).hexdigest()


def export(client: RagflowClient, options: ExportOptions, log: Callable[[str], object] = _log_stderr) -> dict:
    """Run or resume an export. Returns the manifest; raises IncompleteExport if any document failed."""
    out = Path(options.out_dir)
    mode = plan_out_dir(options)
    wanted = _filter_key(options)
    state: dict | None = None
    if mode == 'resume':
        state = read_json(out / STATE_NAME)
        if state.get('format_version') != FORMAT_VERSION:
            raise OutDirRefused(f'the unfinished export in {out} was written by another format version')
        if state.get('base_url') != client.base_url:
            raise OutDirRefused(f'the unfinished export in {out} came from {state.get("base_url")}, not {client.base_url}')
        if state.get('dataset_filter') != wanted:
            raise OutDirRefused(f'the unfinished export in {out} used --dataset {state.get("dataset_filter")}, '
                                f'not {wanted}; resume it with the same filter')

    selected = visible = None
    if state is None or not (out / DATASETS_NAME).is_file():
        visible = client.list_datasets(options.page_size)
        selected = select_datasets(visible, options.dataset_filter)
        folders: dict[str, str] = {}
        for dataset in selected:
            _claim_folder(folders, safe_id(dataset.get('id')), 'dataset')

    if state is None:
        if not out.exists():
            os.mkdir(out, 0o700)
        started = options.now()
        write_atomic(out / README_NAME, readme_text(client.base_url, started).encode('utf-8'))
        state = {'tool': 'ragflow-export', 'tool_version': __version__, 'format_version': FORMAT_VERSION,
                 'base_url': client.base_url, 'dataset_filter': wanted, 'created_at': started,
                 'status': 'in_progress', 'datasets_visible': None, 'runs': [], 'failures': [], 'warnings': []}
    if selected is not None:
        write_json(out / DATASETS_NAME, selected)
        state['datasets_visible'] = len(visible)
    datasets = read_json(out / DATASETS_NAME)

    run = _Run(client, options, state, log)
    record = {'started_at': options.now(), 'outcome': 'running'}
    state['runs'].append(record)
    state['status'] = 'in_progress'
    state['failures'] = []
    if options.probe_version and state.get('server_version') is None:
        state['server_version'] = _probe_version(client)
    run.save()
    log(f'exporting {len(datasets)} datasets from {client.base_url} to {out}')

    try:
        run.datasets(datasets)
    except BaseException as error:
        record['outcome'] = 'interrupted' if isinstance(error, KeyboardInterrupt) else f'stopped: {type(error).__name__}'
        record['finished_at'] = options.now()
        run.save()
        raise
    for leftover in out.rglob('*' + TMP_SUFFIX):
        leftover.unlink()
    record['finished_at'] = options.now()
    if state['failures']:
        record['outcome'] = state['status'] = 'incomplete'
        run.save()
        documents = sum(len(read_json(out / 'datasets' / d['id'] / 'documents.json')) for d in datasets)
        raise IncompleteExport(f'{len(state["failures"])} of {documents} documents failed, so the export is incomplete '
                               f'and has no manifest; their errors are in {out / STATE_NAME}',
                               list(state['failures']))
    record['outcome'] = state['status'] = 'complete'
    run.save()
    manifest = run.manifest(datasets)
    manifest['sha256sums_sha256'] = run.write_sums()
    write_json(out / MANIFEST_NAME, manifest)
    counts = manifest['counts']
    log(f'export complete: {counts["datasets"]} datasets, {counts["documents"]} documents, '
        f'{counts["chunks"]} chunks, {counts["original_bytes"]} bytes in {out}')
    return manifest


def _reported(value: object) -> str:
    count = as_count(value)
    return '?' if count is None else str(count)


def dry_run(client: RagflowClient, options: ExportOptions, out: TextIO | None = None) -> dict:
    """List datasets and documents with the counts the server reports. Downloads nothing and writes no file."""
    stream = out or sys.stdout

    def say(line: str) -> None:
        print(for_terminal(line), file=stream)

    def name(item: dict) -> str:
        return f' "{item.get("name")}"' if options.show_names else ''

    try:
        verdict = {'new': 'start a new export', 'resume': 'resume the unfinished export there'}[plan_out_dir(options)]
    except OutDirRefused as error:
        verdict = f'refuse: {error}'
    visible = client.list_datasets(options.page_size)
    selected = select_datasets(visible, options.dataset_filter)
    say('RAGFlow dry run: listing only. Nothing is downloaded and no file is written.')
    say(f'server: {client.base_url}')
    if options.probe_version:
        version = _probe_version(client)
        say(f'server version (unconfirmed route {version["route"]}): {version.get("value", version.get("error"))}')
    say(f'datasets visible: {len(visible)}, selected: {len(selected)}')
    totals = {'documents': 0, 'bytes': 0, 'chunks': 0}
    for dataset in selected:
        dataset_id = safe_id(dataset.get('id'))
        listing = client.list_documents(dataset_id, options.page_size)
        say(f'dataset {dataset_id}{name(dataset)}: {len(listing.items)} documents listed '
            f'({_reported(dataset.get("document_count"))} reported), {_reported(dataset.get("chunk_count"))} chunks reported')
        for document in listing.items:
            say(f'  document {document.get("id")}{name(document)}: {_reported(document.get("size"))} bytes, '
                f'{_reported(document.get("chunk_count"))} chunks, parse status {document.get("run", "?")}')
            totals['documents'] += 1
            totals['bytes'] += as_count(document.get('size')) or 0
            totals['chunks'] += as_count(document.get('chunk_count')) or 0
    say(f'total: {len(selected)} datasets, {totals["documents"]} documents, {totals["bytes"]} bytes and '
        f'{totals["chunks"]} chunks reported')
    say(f'output folder {options.out_dir}: a real run would {verdict}')
    if not options.show_names:
        say('Names are hidden because they may hold client facts; --show-names prints them.')
    return {'datasets_visible': len(visible), 'datasets': len(selected), **totals}
