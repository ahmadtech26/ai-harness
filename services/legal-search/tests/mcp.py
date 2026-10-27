"""MCP tool calls through the ASGI app. FastMCP runs stateless, so a bare tools/call needs no initialize."""

import json


def tool_text(client, user: str, tool: str, arguments: dict, headers: dict | None = None) -> str:
    response = client.post(
        '/mcp',
        headers={'host': 'legal-search:8000', 'x-iqraa-user': user, 'accept': 'application/json, text/event-stream',
                 **(headers or {})},
        json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': tool, 'arguments': arguments}},
    )
    data = [line[5:].strip() for line in response.text.splitlines() if line.startswith('data:')]
    message = json.loads(data[-1] if data else response.text)
    return ''.join(part.get('text', '') for part in message['result']['content'])
