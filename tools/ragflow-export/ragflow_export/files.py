"""File helpers: atomic writes, hashing, and names that cannot leave their folder."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from ragflow_export.errors import UnsafeIdentifier

# Unfinished files carry this suffix and are renamed into place only when complete, so a crash
# never leaves a file that looks finished. It is distinctive so no exported name can end with it.
TMP_SUFFIX = '.ragflow-export-tmp'

# RAGFlow ids are 32 hex characters. This also admits other plain ids, but never a separator,
# a dot, a space or a non-ASCII letter, so an id is safe both in a URL path and as a folder name.
_SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')
_SAFE_EXTENSION = re.compile(r'[A-Za-z0-9]{1,10}')
# Windows opens these names as devices in any folder and in any letter case, so they cannot be folders.
_DEVICE_NAMES = frozenset({'con', 'prn', 'aux', 'nul'} | {f'{port}{n}' for port in ('com', 'lpt') for n in range(10)})
# The only file names a done record may name: what the exporter itself writes in a document folder.
_OWN_FILE_NAME = re.compile(r'chunks\.jsonl|original\.[a-z0-9]{1,10}')


def safe_id(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise UnsafeIdentifier(f'refused identifier {value!r}: only letters, digits, "_" and "-" are allowed')
    if value.lower() in _DEVICE_NAMES:
        raise UnsafeIdentifier(f'refused identifier {value!r}: Windows reserves that name for a device')
    return value


def folder_key(identifier: str) -> str:
    """Two ids with the same key share one folder on a case-insensitive disk (NTFS, and /mnt/d under WSL)."""
    return identifier.lower()


def is_own_file_name(name: object) -> bool:
    return isinstance(name, str) and _OWN_FILE_NAME.fullmatch(name) is not None


def safe_extension(name: object) -> str:
    """The extension of a document name if it is plain ASCII, else 'bin'. The name itself is never a path."""
    if isinstance(name, str) and '.' in name:
        extension = name.rsplit('.', 1)[1]
        if _SAFE_EXTENSION.fullmatch(extension):
            return extension.lower()
    return 'bin'


def temporary(path: Path) -> Path:
    return path.with_name(path.name + TMP_SUFFIX)


def write_atomic(path: Path, data: bytes) -> None:
    tmp = temporary(path)
    with open(tmp, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def write_json(path: Path, value: object) -> None:
    write_atomic(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8'))


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding='utf-8'))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 16), b''):
            digest.update(block)
    return digest.hexdigest()
