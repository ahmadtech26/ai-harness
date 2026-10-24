"""A skill folder's content digest, stable across line endings, and the LF-normalised file read
the release copies. Text (any UTF-8 file) is compared with LF line endings; other bytes as is."""

import hashlib
from pathlib import Path


def read_normalised(path: Path) -> bytes:
    data = path.read_bytes()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return data
    return text.replace('\r\n', '\n').encode('utf-8')


def skill_files(folder: Path) -> list[Path]:
    return sorted(path for path in folder.rglob('*') if path.is_file() and not path.is_symlink())


def folder_digest(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in skill_files(folder):
        digest.update(path.relative_to(folder).as_posix().encode('utf-8'))
        digest.update(b'\0')
        digest.update(read_normalised(path))
        digest.update(b'\0')
    return 'sha256:' + digest.hexdigest()
