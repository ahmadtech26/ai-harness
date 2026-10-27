import logging

import pytest

from legal_search.alerts import LOGGER


@pytest.fixture
def alert_caplog(caplog):
    """caplog with the alert lines in it. The alerts logger does not propagate to the root logger, where
    caplog listens (FastMCP puts a stderr handler there, which would print every alert twice), so caplog's
    handler is attached to the alerts logger itself for the test. Required on pytest 8; on pytest 9.1.1,
    which attaches caplog's handler to every non-propagating logger itself, it is a harmless no-op (the
    handler is already there, and `addHandler` adds a handler once)."""
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    LOGGER.addHandler(caplog.handler)
    yield caplog
    LOGGER.removeHandler(caplog.handler)
