"""A read-only HTTP client for the RAGFlow routes the exporter needs, and nothing else.

Only GET is ever sent, and only to the four listing and download routes, plus an opt-in version
probe whose path is unconfirmed. Any other method or path raises ReadOnlyViolation before anything
leaves the machine. Redirects are refused, so the key is never sent to a second address, and
environment proxies are ignored. The key is read from a file, sent only in the Authorization header,
and redacted from every message the server returns.

Routes and parameters follow the research of 2026-11-04 (RAGFlow v1.0.0-rc3 router and HTTP API
reference; v0.27.3 uses the same paths). The JSON field names ("code", "data", "docs", "chunks",
"total") and the error codes are the author's reading of the v0.x HTTP API reference and are not
confirmed: an unexpected shape raises ShapeError instead of being guessed at.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ragflow_export import __version__
from ragflow_export.errors import (ApiError, ApiKeyError, AuthError, BadBaseUrl, HttpError, InsecureTransport,
                                   PaginationError, ReadOnlyViolation, RedirectRefused, ShapeError, TransportError)
from ragflow_export.files import safe_id, temporary


@dataclass(frozen=True)
class Route:
    name: str
    template: str
    confirmed: bool
    note: str


ROUTES = (
    Route('list_datasets', '/api/v1/datasets', True, 'page, page_size'),
    Route('list_documents', '/api/v1/datasets/{dataset_id}/documents', True,
          'page and page_size are assumed to work as for datasets; not confirmed'),
    Route('download_document', '/api/v1/datasets/{dataset_id}/documents/{document_id}', True, 'returns file bytes'),
    Route('list_chunks', '/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks', True, 'page, page_size'),
    Route('system_version', '/api/v1/system/version', False,
          'the route exists in rc3 but its full path was not confirmed; sent only with --probe-version'),
)
_ROUTE_BY_NAME = {route.name: route for route in ROUTES}
_ID = '[A-Za-z0-9][A-Za-z0-9_-]{0,127}'
_ROUTE_PATTERNS = [re.compile(re.sub(r'\{\w+\}', _ID, route.template)) for route in ROUTES]

AUTH_CODES = {109}  # RAGFlow's authentication error code as the author understands it; unconfirmed.
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER = 300.0
MAX_PAGES = 100_000
MAX_ERROR_BODY = 1 << 20


@dataclass(frozen=True)
class Listing:
    items: list
    total_reported: int | None
    duplicates: int


@dataclass(frozen=True)
class Download:
    sha256: str
    size: int
    content_type: str


class _Retry(Exception):
    def __init__(self, error: Exception, retry_after: float | None = None):
        super().__init__(str(error))
        self.error = error
        self.retry_after = retry_after


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise RedirectRefused(f'the server answered HTTP {code} with a redirect; redirects are refused '
                              'so the key is never sent to another address')


def load_api_key(path: Path) -> str:
    """Read the key from a file. Messages name the file but never repeat what it holds."""
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise ApiKeyError(f'cannot read the API key file {path}: {error.strerror or type(error).__name__}') from None
    try:
        key = raw.decode('utf-8-sig').strip()
    except UnicodeDecodeError:
        raise ApiKeyError(f'the API key file {path} is not UTF-8 text') from None
    _check_key(key)
    return key


def _check_key(key: object) -> None:
    if not isinstance(key, str) or not key:
        raise ApiKeyError('the API key is empty')
    if any(ch.isspace() for ch in key):
        raise ApiKeyError('the API key file must hold the key alone, on one line')
    if not key.isascii() or not key.isprintable():
        raise ApiKeyError('the API key holds characters an HTTP header cannot carry')


def _is_loopback(host: str) -> bool:
    host = host.lower()
    if host == 'localhost' or host.endswith('.localhost'):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _parse_base_url(base_url: str, allow_insecure_http: bool) -> tuple[str, str]:
    parts = urllib.parse.urlsplit((base_url or '').strip())
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise BadBaseUrl('the base URL must look like https://host[:port][/prefix]')
    if parts.username is not None or parts.password is not None:
        raise BadBaseUrl('the base URL must not hold credentials; the key is read from --api-key-file')
    if parts.query or parts.fragment:
        raise BadBaseUrl('the base URL must not hold a query or a fragment')
    try:
        parts.port
    except ValueError:
        raise BadBaseUrl('the base URL has an invalid port') from None
    if parts.scheme == 'http' and not allow_insecure_http and not _is_loopback(parts.hostname):
        raise InsecureTransport('plain http would send the key unencrypted; use https, or pass '
                                '--allow-insecure-http only on a network you trust')
    prefix = parts.path.rstrip('/')
    return f'{parts.scheme}://{parts.netloc.lower()}{prefix}', prefix


def _retry_after(value: str | None) -> float | None:
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None  # an HTTP date: fall back to the computed backoff
    return seconds if seconds is not None and seconds >= 0 else None


def as_count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _shape(path: str, data: object, expected: str) -> str:
    seen = f'an object with keys {sorted(map(str, data))}' if isinstance(data, dict) else type(data).__name__
    return (f'GET {path}: expected "data" to be {expected}, got {seen}. The response shape is not confirmed '
            'for this server version, so the tool stops rather than guess.')


def _datasets(path: str, payload: dict) -> tuple[list, int | None]:
    data = payload.get('data')
    if not isinstance(data, list):
        raise ShapeError(_shape(path, data, 'a list'))
    return data, as_count(payload.get('total'))


def _nested(key: str) -> Callable[[str, dict], tuple[list, int | None]]:
    def extract(path: str, payload: dict) -> tuple[list, int | None]:
        data = payload.get('data')
        if not isinstance(data, dict) or not isinstance(data.get(key), list):
            raise ShapeError(_shape(path, data, f'an object with a "{key}" list'))
        return data[key], as_count(data.get('total'))
    return extract


class RagflowClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 60.0, max_attempts: int = 5,
                 base_delay: float = 1.0, max_delay: float = 60.0, sleep: Callable[[float], object] = time.sleep,
                 allow_insecure_http: bool = False, ca_file: Path | None = None):
        self.base_url, self._prefix = _parse_base_url(base_url, allow_insecure_http)
        _check_key(api_key)
        self.__key = api_key
        self.timeout = timeout
        self.max_attempts = max(1, int(max_attempts))
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._sleep = sleep
        try:
            context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        except (OSError, ssl.SSLError) as error:
            raise InsecureTransport(f'cannot load --ca-file {ca_file}: {type(error).__name__}') from None
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(), urllib.request.HTTPSHandler(context=context))

    def __repr__(self) -> str:
        return f'RagflowClient(base_url={self.base_url!r})'

    def redact(self, text: str) -> str:
        text = text.replace(self.__key, '[REDACTED]')
        return re.sub(r'(?i)\b(bearer)\s+\S+', r'\1 [REDACTED]', text)

    # Public routes -------------------------------------------------------------------------------

    def list_datasets(self, page_size: int) -> list[dict]:
        return self._paged(self._path('list_datasets'), page_size, _datasets).items

    def list_documents(self, dataset_id: str, page_size: int) -> Listing:
        return self._paged(self._path('list_documents', dataset_id=dataset_id), page_size, _nested('docs'))

    def list_chunks(self, dataset_id: str, document_id: str, page_size: int) -> Listing:
        path = self._path('list_chunks', dataset_id=dataset_id, document_id=document_id)
        return self._paged(path, page_size, _nested('chunks'))

    def server_version(self) -> str:
        return str(self.request_json('GET', self._path('system_version')).get('data'))

    def download_document(self, dataset_id: str, document_id: str, dest: Path) -> Download:
        """Stream the original file to `dest` through a temporary file, so `dest` only ever holds a whole file."""
        path = self._path('download_document', dataset_id=dataset_id, document_id=document_id)
        tmp = temporary(dest)
        try:
            result = self._with_retries(lambda: self._stream_to(path, tmp))
            self._refuse_json_error(path, tmp, result)
            os.replace(tmp, dest)
            return result
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    # The single gate every request passes ---------------------------------------------------------

    def request_json(self, method: str, path: str, params: dict | None = None) -> dict:
        """One JSON request, with retries. `path` is relative to the base URL."""
        return self._check_payload(path, self._with_retries(lambda: self._read_body(method, path, params)))

    def _check(self, method: str, path: str) -> None:
        if method != 'GET':
            raise ReadOnlyViolation(f'refused {method} {path}: this client sends GET only')
        if not any(pattern.fullmatch(path) for pattern in _ROUTE_PATTERNS):
            raise ReadOnlyViolation(f'refused GET {path}: not one of the listing or download routes')

    def _open(self, method: str, path: str, params: dict | None):
        self._check(method, path)
        query = '?' + urllib.parse.urlencode(params) if params else ''
        request = urllib.request.Request(self.base_url + path + query, method='GET', headers={
            'Authorization': f'Bearer {self.__key}',
            'Accept': '*/*',
            'User-Agent': f'ragflow-export/{__version__} (read-only)',
        })
        if request.get_method() != 'GET' or request.data is not None:
            raise ReadOnlyViolation(f'refused a request to {path} that would carry a body')
        try:
            return self._opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            raise self._http_failure(path, error) from None
        except urllib.error.URLError as error:
            failure = TransportError(f'GET {path} could not reach the server: {self.redact(str(error.reason))}')
            if isinstance(error.reason, ssl.SSLError):
                raise failure from None  # a certificate problem does not heal by retrying
            raise _Retry(failure) from None
        except (http.client.HTTPException, OSError) as error:
            raise _Retry(TransportError(f'GET {path} failed: {type(error).__name__}')) from None

    def _http_failure(self, path: str, error: urllib.error.HTTPError) -> Exception:
        status = error.code
        try:
            snippet = error.read(300).decode('utf-8', 'replace')
        except (http.client.HTTPException, OSError):
            snippet = ''
        finally:
            error.close()
        snippet = self.redact(' '.join(snippet.split()))
        if status in (401, 403):
            return AuthError(f'GET {path} was refused with HTTP {status}: {snippet}')
        failure = HttpError(status, f'GET {path} returned HTTP {status}: {snippet}')
        if status in RETRY_STATUSES:
            return _Retry(failure, _retry_after(error.headers.get('Retry-After')))
        return failure

    def _with_retries(self, attempt: Callable[[], object]):
        for number in range(self.max_attempts):
            try:
                return attempt()
            except _Retry as retry:
                if number + 1 >= self.max_attempts:
                    raise retry.error from None
                self._sleep(self._delay(number, retry.retry_after))
        raise AssertionError('unreachable')

    def _delay(self, number: int, retry_after: float | None) -> float:
        delay = min(self.max_delay, self.base_delay * (2 ** number))
        if retry_after is not None:
            delay = max(delay, min(retry_after, MAX_RETRY_AFTER))
        return delay

    def _read_body(self, method: str, path: str, params: dict | None) -> bytes:
        response = self._open(method, path, params)
        try:
            return response.read()
        except (http.client.HTTPException, OSError) as error:
            raise _Retry(TransportError(f'GET {path}: the response was cut off ({type(error).__name__})')) from None
        finally:
            response.close()

    def _check_payload(self, path: str, body: bytes) -> dict:
        try:
            payload = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise ShapeError(f'GET {path} did not return JSON') from None
        if not isinstance(payload, dict) or as_count(payload.get('code')) is None:
            raise ShapeError(f'GET {path} returned JSON without a numeric "code" field')
        code = payload['code']
        if code != 0:
            message = self.redact(' '.join(str(payload.get('message', '')).split()))[:300]
            if code in AUTH_CODES:
                raise AuthError(f'GET {path}: the server refused the key (code {code}): {message}')
            raise ApiError(code, f'GET {path} returned code {code}: {message}')
        return payload

    # Paging and downloading ----------------------------------------------------------------------

    def _path(self, name: str, **ids: str) -> str:
        return _ROUTE_BY_NAME[name].template.format(**{key: safe_id(value) for key, value in ids.items()})

    def _paged(self, path: str, page_size: int, extract) -> Listing:
        """Follow page=1,2,... until a short page (no total) or the reported total, never looping on a repeat."""
        if page_size < 1:
            raise ValueError('page_size must be at least 1')
        seen: set[str] = set()
        items: list[dict] = []
        total: int | None = None
        duplicates = 0
        for page in range(1, MAX_PAGES + 1):
            batch, reported = extract(path, self.request_json('GET', path, {'page': page, 'page_size': page_size}))
            total = reported if reported is not None else total
            fresh = 0
            for item in batch:
                if not isinstance(item, dict) or not isinstance(item.get('id'), str):
                    raise ShapeError(f'GET {path} listed an item without a string "id"')
                if item['id'] in seen:
                    duplicates += 1
                    continue
                seen.add(item['id'])
                items.append(item)
                fresh += 1
            if not batch:
                break
            if fresh == 0:
                raise PaginationError(f'GET {path} page {page} repeated earlier items only: the server seems to '
                                      'ignore the page parameter, so the listing cannot be shown to be complete')
            if total is not None:
                if len(items) >= total:
                    break
            elif len(batch) < page_size:
                break
        else:
            raise PaginationError(f'GET {path} did not end within {MAX_PAGES} pages')
        return Listing(items, total, duplicates)

    def _stream_to(self, path: str, tmp: Path) -> Download:
        response = self._open('GET', path, None)
        digest = hashlib.sha256()
        size = 0
        try:
            content_type = response.headers.get('Content-Type', '')
            declared = response.headers.get('Content-Length')
            with open(tmp, 'wb') as handle:
                while True:
                    try:
                        block = response.read(1 << 16)
                    except (http.client.HTTPException, OSError) as error:
                        raise _Retry(TransportError(
                            f'GET {path}: the download was cut off ({type(error).__name__})')) from None
                    if not block:
                        break
                    handle.write(block)
                    digest.update(block)
                    size += len(block)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            response.close()
        if declared is not None and declared.strip().isdigit() and int(declared) != size:
            raise _Retry(TransportError(f'GET {path}: the download stopped at {size} of {declared.strip()} bytes'))
        return Download(digest.hexdigest(), size, content_type)

    def _refuse_json_error(self, path: str, tmp: Path, result: Download) -> None:
        """RAGFlow answers a failed download with a JSON error and HTTP 200. Such a body is not a file."""
        if result.content_type.split(';')[0].strip().lower() != 'application/json' or result.size > MAX_ERROR_BODY:
            return
        body = tmp.read_bytes()
        try:
            payload = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return
        if isinstance(payload, dict) and as_count(payload.get('code')) not in (None, 0) and 'message' in payload:
            self._check_payload(path, body)
