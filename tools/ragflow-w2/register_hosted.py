#!/usr/bin/env python3
"""register_hosted.py: register the hosted embedder (OpenRouter) for the W2 tenant, inside the runner.

Runs INSIDE ragbench-rf-runner (compose.yaml + compose.hosted.yaml), which shares the server's network namespace:
the API is http://127.0.0.1:9380. It reads two keys, each from a file only the runner has, and prints neither:
the owner's OpenRouter key from /keys/openrouter.key (a read-only bind of that one file), and the runner's
RAGFlow API key from /run/rf/key (make_key.py's, in the runner's tmpfs).

  python3 -I -B /w2/register_hosted.py register --model qwen/qwen3-embedding-8b --instance w2or \
      --data-policy "<what the owner set, H0>" --out /out/elasticsearch [--provider-order nebius]
  python3 -I -B /w2/register_hosted.py smoke --model qwen/qwen3-embedding-8b [--provider-order nebius]

register (no call to OpenRouter; v0.27.3 source, .hq/scratch/ragflow-src-v0.27.3/x/):
  PUT  /api/v1/providers                           {"provider_name": "OpenRouter"}
                                                   provider_api.py:72-121; provider_api_service.py:217-239
  POST /api/v1/providers/OpenRouter/instances      {"instance_name": "<i>"}: a name-only instance, no key, no call
                                                   provider_api.py:353-361; provider_api_service.py:725-753
  PUT  /api/v1/providers/OpenRouter/instances/<i>  {instance_name, api_key, base_url, region "", model_info,
                                                   "verify": false}: stores the key and the model; verify false
                                                   skips the provider check (provider_api.py:549-657;
                                                   provider_api_service.py:460-465)
  The key is in that one body and nowhere else. The dataset then names the model as «<model>@<i>@OpenRouter»
  (tenant_model_service.py:206-229), and the first call to OpenRouter is the parse's.
smoke (optional; ONE paid call of about 8 tokens, only when the owner approved it):
  POST /api/v1/providers/OpenRouter/connection     {api_key, base_url, model_info}: the server embeds «Test if the
                                                   api key is available» once, through the proxy, and stores nothing
                                                   (provider_api.py:380-458; provider_api_service.py:894-921, waiting
                                                   LLM_TIMEOUT_SECONDS). It proves the egress, the key, the guardrail
                                                   and that OpenRouter accepts RAGFlow's body (drop_params).
Never sent: GET /api/v1/providers/<p>/instances/<i>, which answers with the stored key in clear
(provider_api_service.py:1117). ROUTES lists every request this tool may send; anything else is refused first.

--provider-order (owner decision, PREMISES §8 item 2; off by default): the key is sent as the JSON text
{"api_key": <key>, "provider_order": <order>}, made in memory, so that RAGFlow's OpenRouter client adds
provider {order, allow_fallbacks: false} to every request (rag/llm/embedding_model.py:1528-1548;
api/db/joint_services/tenant_model_service.py:65-83 keeps such a payload whole).

Writes <out>/hosted-embedder.json (register only): factory, instance, model, embedding_model, base_url, max_tokens,
provider_order, verify, the data-policy note, and of the key only its length and a salted sha256 (a random 16-byte
salt, beside it), so key_leak_check.py can show it checks the key that was registered. Never the key.

The key file must hold exactly one OpenRouter key, «sk-or-v1-» and 64 lower-case hex characters (the shape of every
key in OpenRouter's key documentation, read 2026-11-09), on one line, with or without one line end (LF or CRLF), no
byte-order mark. Anything else is refused before anything is sent, and the message never quotes the file.

Exit codes: 0 done, 1 the server refused (a message cut at 200 characters, every key removed), 2 refused before
sending. Standard library only; Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FACTORY = 'OpenRouter'
BASE_URL = 'https://openrouter.ai/api/v1'   # OpenRouterEmbed's default (rag/llm/embedding_model.py:1524)
MAX_TOKENS = 32768                          # below Nebius's 40,960 context; our longest article is 1,868 tokens
RECORD = 'hosted-embedder.json'
OPENROUTER_KEY = re.compile(r'sk-or-v1-[0-9a-f]{64}')
RAGFLOW_KEY = re.compile(r'ragflow-[A-Za-z0-9_-]{20,}')
MODEL_ID = re.compile(r'[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._:-]*')   # an OpenRouter model id, no '@'
INSTANCE = re.compile(r'[0-9A-Za-z_-]+')                               # provider_api.py:353
PROVIDER_ORDER = re.compile(r'[a-z0-9-]+(/[a-z0-9.-]+)?(,[a-z0-9-]+(/[a-z0-9.-]+)?)*')  # comma list of slugs

ROUTES = (  # (method, path pattern); every one needs the RAGFlow key
    ('PUT', r'/api/v1/providers'),
    ('POST', rf'/api/v1/providers/{FACTORY}/instances'),
    ('PUT', rf'/api/v1/providers/{FACTORY}/instances/[0-9A-Za-z_-]+'),
    ('POST', rf'/api/v1/providers/{FACTORY}/connection'),
)

DONE, FAILED, REFUSED = 0, 1, 2


class Refused(Exception):
    """A problem found before anything was sent."""


class Failed(Exception):
    """The server refused a request."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Failed(f'HTTP {code}: a redirect; redirects are refused')


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def loopback_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ''
    try:
        loopback = host == 'localhost' or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if parts.scheme != 'http' or not loopback or parts.query or parts.fragment:
        raise Refused(f'{url!r}: only http:// to a loopback address')
    return url.rstrip('/')


def read_openrouter_key(path: Path) -> str:
    """The one key in the file, else Refused; no message quotes the file."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise Refused(f'no key file at {path}: the owner writes it (README.md, H0)') from None
    except OSError:
        raise Refused(f'the key file {path} cannot be read') from None
    if not raw:
        raise Refused('the key file is empty')
    if raw.startswith(b'\xef\xbb\xbf'):
        raise Refused('the key file starts with a byte-order mark: write the key without one')
    body = raw[:-2] if raw.endswith(b'\r\n') else raw[:-1] if raw.endswith(b'\n') else raw
    if b'\n' in body or b'\r' in body:
        raise Refused('the key file holds more than one line')
    try:
        key = body.decode('ascii')
    except UnicodeDecodeError:
        key = ''
    if not OPENROUTER_KEY.fullmatch(key):
        raise Refused('the key file does not hold one OpenRouter key («sk-or-v1-» and 64 lower-case hex '
                      'characters) on one line')
    return key


def read_ragflow_key(path: Path) -> str:
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        raise Refused('the RAGFlow API key file cannot be read') from None
    key = text.strip()
    if not RAGFLOW_KEY.fullmatch(key) or text.count('\n') > 1:
        raise Refused('the RAGFlow API key file must hold one RAGFlow key («ragflow-…») on one line (make_key.py)')
    return key


class Client:
    """The one gate every request passes. Answers are parsed; bodies are never printed."""

    def __init__(self, base_url: str, key: str, *, secrets_to_hide=(), timeout: float = 120.0):
        self.base, self._key, self.timeout = base_url, key, timeout
        self._hide = tuple(s for s in (key, *secrets_to_hide) if s)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def __repr__(self) -> str:
        return 'Client(...)'

    def redact(self, text) -> str:
        text = str(text)
        for secret in sorted(self._hide, key=len, reverse=True):
            text = text.replace(secret, '[REDACTED]')
        text = ' '.join(text.split())
        return re.sub(r'(?i)\bbearer\s+(?!\[REDACTED\])\S+', 'Bearer [REDACTED]', text)[:200]

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        if not any(m == method and re.fullmatch(p, path) for m, p in ROUTES):
            raise Refused(f'refused {method} {path}: not one of the requests this tool may send')
        headers = {'Accept': 'application/json', 'User-Agent': 'register_hosted/1',
                   'Authorization': f'Bearer {self._key}'}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
            error.close()
        except urllib.error.URLError as error:
            raise Failed(f'{method} {path}: cannot reach the server ({type(error.reason).__name__})') from None
        except OSError as error:
            raise Failed(f'{method} {path}: the connection failed ({type(error).__name__})') from None
        try:
            return status, json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise Failed(f'{method} {path}: HTTP {status}, the answer ({len(raw)} bytes) is not JSON') from None

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        status, payload = self.request(method, path, body)
        code = payload.get('code') if isinstance(payload, dict) else None
        if code != 0:
            message = self.redact(payload.get('message', '')) if isinstance(payload, dict) else ''
            raise Failed(f'{method} {path}: HTTP {status}, code {code}: {message}')
        return payload


def key_payload(key: str, provider_order: str | None) -> str:
    """What is stored as the instance's api_key: the key, or the JSON text RAGFlow's OpenRouter client reads a
    provider order from."""
    return json.dumps({'api_key': key, 'provider_order': provider_order}) if provider_order else key


def model_info(model: str) -> list:
    return [{'model_type': ['embedding'], 'model_name': model, 'max_tokens': MAX_TOKENS}]


def register(client: Client, args, key: str, log) -> dict:
    record_path = args.out / RECORD
    client.call('PUT', '/api/v1/providers', {'provider_name': FACTORY})
    log(f'ok   provider {FACTORY} added for the tenant')
    client.call('POST', f'/api/v1/providers/{FACTORY}/instances', {'instance_name': args.instance})
    log(f'ok   instance {args.instance} created by name only: no key, no call')
    client.call('PUT', f'/api/v1/providers/{FACTORY}/instances/{args.instance}', {
        'instance_name': args.instance, 'api_key': key_payload(key, args.provider_order), 'base_url': BASE_URL,
        'region': '', 'model_info': model_info(args.model), 'verify': False})
    log(f'ok   key and model stored with verify false: no call to OpenRouter (key of {len(key)} characters'
        + (f', provider order {args.provider_order}' if args.provider_order else ', no provider order') + ')')
    salt = secrets.token_hex(16)
    record = {'w2_hosted_registration': 1, 'registered_at': now(), 'factory': FACTORY, 'instance': args.instance,
              'model': args.model, 'embedding_model': f'{args.model}@{args.instance}@{FACTORY}', 'base_url': BASE_URL,
              'max_tokens': MAX_TOKENS, 'provider_order': args.provider_order, 'verify': False,
              'data_policy': args.data_policy,
              'key': {'length': len(key), 'salt': salt,
                      'salted_sha256': hashlib.sha256((salt + key).encode('ascii')).hexdigest()}}
    text = json.dumps(record, ensure_ascii=False, indent=1) + '\n'
    if key in text:  # cannot happen; the guard costs nothing
        raise Failed('the record would hold the key; nothing written')
    partial = record_path.with_name(RECORD + '.partial')
    with open(partial, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    partial.replace(record_path)
    log(f'wrote {RECORD}: the dataset\'s embedding_model is {record["embedding_model"]}')
    return record


def smoke(client: Client, args, key: str, log) -> None:
    client.call('POST', f'/api/v1/providers/{FACTORY}/connection', {
        'api_key': key_payload(key, args.provider_order), 'base_url': BASE_URL, 'model_info': model_info(args.model)})
    log(f'ok   smoke: one embedding call to {args.model} through the proxy answered (nothing stored)')


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description='Register the hosted embedder for the W2 tenant, inside the runner.')
    sub = ap.add_subparsers(dest='step', required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--base-url', default='http://127.0.0.1:9380')
    common.add_argument('--api-key-file', type=Path, default=Path('/run/rf/key'), help="the runner's RAGFlow key")
    common.add_argument('--key-file', type=Path, default=Path('/keys/openrouter.key'), help="the owner's OpenRouter key")
    common.add_argument('--model', required=True, help='the OpenRouter model id, e.g. qwen/qwen3-embedding-8b')
    common.add_argument('--provider-order', help='e.g. nebius: pin the provider in every request (owner decision)')
    common.add_argument('--timeout', type=float, default=120.0, help='seconds per request')
    reg = sub.add_parser('register', parents=[common], help='add the provider, the instance, the key and the model')
    reg.add_argument('--instance', required=True, help='the instance name, e.g. w2or (never «default»)')
    reg.add_argument('--data-policy', required=True, help="one line: the data-policy settings the owner made (H0)")
    reg.add_argument('--out', required=True, type=Path, help='the run folder, e.g. /out/elasticsearch')
    sub.add_parser('smoke', parents=[common], help='one paid embedding call through the proxy (owner approval)')
    return ap


def check_args(args) -> None:
    if not MODEL_ID.fullmatch(args.model):
        raise Refused(f'--model {args.model!r} is not an OpenRouter model id (<vendor>/<model>, no «@»)')
    if args.provider_order is not None and not PROVIDER_ORDER.fullmatch(args.provider_order):
        raise Refused('--provider-order must be OpenRouter provider slugs, comma-separated (e.g. nebius)')
    if args.step != 'register':
        return
    if not INSTANCE.fullmatch(args.instance) or args.instance == 'default':
        raise Refused('--instance must be letters, digits, «_» or «-», and not «default» '
                      '(provider_api.py:353; provider_api_service.py:737)')
    if not args.data_policy.strip() or '\n' in args.data_policy or '\r' in args.data_policy \
            or len(args.data_policy) > 500:
        raise Refused('--data-policy must be one non-empty line of at most 500 characters')
    if not args.out.is_dir():
        raise Refused(f'--out {args.out} is not a folder')
    if (args.out / RECORD).exists() or (args.out / (RECORD + '.partial')).exists():
        raise Refused(f'{args.out} already holds a registration ({RECORD})')


def main(argv: list[str] | None = None, *, stdout=None) -> int:
    stdout = stdout or sys.stdout
    hide: list[str] = []

    def log(message: str) -> None:
        for secret in sorted(hide, key=len, reverse=True):
            message = message.replace(secret, '[REDACTED]')
        print(message, file=stdout, flush=True)

    args = build_parser().parse_args(argv)
    try:
        base = loopback_url(args.base_url)
        check_args(args)
        rf_key = read_ragflow_key(args.api_key_file)
        hide.append(rf_key)
        key = read_openrouter_key(args.key_file)
        hide.append(key)
        hide.append(key_payload(key, args.provider_order))
        client = Client(base, rf_key, secrets_to_hide=(key, key_payload(key, args.provider_order)),
                        timeout=args.timeout)
        if args.step == 'register':
            register(client, args, key, log)
        else:
            smoke(client, args, key, log)
    except Refused as refusal:
        log(f'refused: {refusal}')
        return REFUSED
    except Failed as failure:
        log(f'failed: {failure}')
        return FAILED
    return DONE


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
