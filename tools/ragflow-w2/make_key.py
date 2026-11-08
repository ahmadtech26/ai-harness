#!/usr/bin/env python3
"""make_key.py: create one RAGFlow API key for the W2 throwaway and write it to stdout, for a pipe only.

Runs INSIDE ragbench-rf-server, and its stdout goes straight into the runner's tmpfs:
  set -o pipefail
  docker exec -i ragbench-rf-server /ragflow/.venv/bin/python -I -B /w2/make_key.py \
    | docker exec -i ragbench-rf-runner sh -c 'umask 077 && cat > /run/rf/key && test -s /run/rf/key'
The key passes through the pipe in memory: it is never printed, never on the host disk, and it dies
with the runner's tmpfs at teardown (and with MySQL's tmpfs, which holds the only other copy).

What it does (RAGFlow v0.27.3 source, .hq/scratch/ragflow-src-v0.27.3/x/):
  1. Reads DEFAULT_SUPERUSER_EMAIL and DEFAULT_SUPERUSER_PASSWORD from this container's environment:
     the account --init-superuser created at boot (api/db/init_data.py:42-82; api/ragflow_server.py:125-132).
     They come from the secrets file through compose.yaml's env_file.
  2. POST /api/v1/auth/login (user_api.py:60-142) with the password encrypted by RAGFlow's own crypt()
     (api/utils/crypt.py:34-43), because login decrypts it with conf/private.pem (user_api.py:109-114).
  3. Takes the JWT from the answer's Authorization header (common/connection_utils.py:103-118).
  4. POST /api/v1/system/tokens with that header (system_api.py:323-370) and writes data.token,
     «ragflow-» + token_urlsafe(32) (api/utils/api_utils.py:348-351), to stdout with one newline.
It refuses to run when stdout is a terminal, so the key cannot land on a screen by mistake. Errors go
to stderr as a code or an HTTP status only, never a body, the password or the key. Standard library
plus RAGFlow's crypt module (in the image; /ragflow is put on sys.path explicitly, since -I drops
PYTHONPATH). Talks only to http://127.0.0.1:9380, with no proxy and no redirect.
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:9380/api/v1'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'redirect refused', headers, fp)


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def post(path, body, auth=None):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if auth:
        headers['Authorization'] = auth
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode('utf-8'), headers=headers, method='POST')
    with OPENER.open(req, timeout=60) as resp:
        return resp.headers.get('Authorization'), json.loads(resp.read().decode('utf-8'))


def main():
    if sys.stdout.isatty():
        sys.exit('make_key: stdout is a terminal; pipe it into the runner as the docstring shows')
    sys.path.insert(0, '/ragflow')
    from api.utils.crypt import crypt  # RAGFlow's module, in the server image

    email = os.environ.get('DEFAULT_SUPERUSER_EMAIL', '')
    password = os.environ.get('DEFAULT_SUPERUSER_PASSWORD', '')
    if not email or not password:
        sys.exit('make_key: DEFAULT_SUPERUSER_EMAIL / DEFAULT_SUPERUSER_PASSWORD are not set in the server container')
    jwt, body = post('/auth/login', {'email': email, 'password': crypt(password)})
    if not isinstance(body, dict) or body.get('code') != 0 or not jwt:
        sys.exit('make_key: login refused, code %s' % (body.get('code') if isinstance(body, dict) else '?'))
    _, body = post('/system/tokens', {}, auth=jwt)
    token = ((body.get('data') or {}).get('token') if isinstance(body, dict) else None) or ''
    if body.get('code') != 0 or not token.startswith('ragflow-') or any(c.isspace() for c in token):
        sys.exit('make_key: token not created, code %s' % body.get('code'))
    sys.stdout.write(token + '\n')
    sys.stdout.flush()


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as e:
        sys.exit('make_key: HTTP %s' % e.code)
    except urllib.error.URLError as e:
        sys.exit('make_key: server not reachable (%s)' % type(e.reason).__name__)
    except (OSError, ValueError) as e:
        sys.exit('make_key: %s' % type(e).__name__)
