"""Sweep alerts (spec C.5): one JSON line at error level per event, on stderr (the container log), so a log
shipper or `docker compose logs legal-search` can pick them out. No email or webhook is configured."""

import json
import logging
import sys

LOGGER = logging.getLogger('legal_search.alerts')
if not LOGGER.handlers:  # this logger writes the bare JSON line itself
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter('%(message)s'))
    LOGGER.addHandler(_handler)
LOGGER.setLevel(logging.INFO)
# FastMCP's constructor runs logging.basicConfig (a stderr handler on the root logger, which uvicorn keeps):
# a propagating alert would be written twice.
LOGGER.propagate = False


def alert(event: str, **fields) -> None:
    """Emits {"level": "error", "event": <event>, ...fields} as one line."""
    LOGGER.error(json.dumps({'level': 'error', 'event': event, **fields}, ensure_ascii=False, sort_keys=True, default=str))
