"""MCP tool calls against legal-search, run INSIDE the legal-search container (the service is not
published to the host). lib.mjs `mcpCalls` runs

    docker compose exec -T legal-search python3 -I - <base64 JSON>      (this file on stdin)

The argument is base64 of {"user": <X-Iqraa-User>, "calls": [{"tool": <name>, "arguments": {...}}, ...]}.
The shared secret is read here from LEGAL_SEARCH_SECRET_FILE, so it never appears on a command line or in
a workspace file. FastMCP runs stateless, so each call is one bare tools/call POST (proved in the test
stack by test_mcp_tool_calls_are_decided_by_the_guard). Prints one JSON line {"results": [<tool text>, ...]}
in call order; a JSON-RPC error becomes "ERROR: <message>".
"""

import base64
import json
import os
import sys
import urllib.request

URL = 'http://127.0.0.1:8000/mcp'
HOST = 'legal-search:8000'  # LEGAL_SEARCH_ALLOWED_HOSTS is legal-search:*


def read_secret() -> str:
    with open(os.environ['LEGAL_SEARCH_SECRET_FILE'], encoding='utf-8') as handle:
        return handle.read().strip()


def call(secret: str, user: str, index: int, tool: str, arguments: dict) -> str:
    body = json.dumps({'jsonrpc': '2.0', 'id': index, 'method': 'tools/call',
                       'params': {'name': tool, 'arguments': arguments}}).encode('utf-8')
    request = urllib.request.Request(URL, data=body, method='POST', headers={
        'Host': HOST,
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
        'X-Iqraa-Secret': secret,
        'X-Iqraa-User': user,
    })
    with urllib.request.urlopen(request, timeout=60) as response:
        text = response.read().decode('utf-8')
    data = [line[5:].strip() for line in text.splitlines() if line.startswith('data:')]
    message = json.loads(data[-1] if data else text)
    if 'error' in message:
        return f"ERROR: {message['error'].get('message', message['error'])}"
    return ''.join(part.get('text', '') for part in message['result']['content'])


def main() -> None:
    plan = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
    secret = read_secret()
    results = [call(secret, plan['user'], index, item['tool'], item.get('arguments', {}))
               for index, item in enumerate(plan['calls'], 1)]
    print(json.dumps({'results': results}))


if __name__ == '__main__':
    main()
