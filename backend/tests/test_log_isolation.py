"""The conftest guard keeps every test out of backend/logs (tests/conftest.py::_forbid_writes_to_production_logs)."""

import logging
from pathlib import Path

from core.config import BASE_DIR
from core.logging_config import configure_logging

REAL_LOG_DIR = BASE_DIR / "logs"


def test_configure_logging_aimed_at_a_production_log_path_never_creates_or_writes_the_file():
    probe = REAL_LOG_DIR / "__test_log_isolation_probe__.log"
    assert not probe.exists()
    root_handlers = logging.getLogger().handlers[:]
    try:
        configure_logging(probe)
        logging.getLogger("isolation.probe").warning("this line must never reach a production log")
        assert not probe.exists()
    finally:
        probe.unlink(missing_ok=True)
        logging.getLogger().handlers[:] = root_handlers


def test_a_file_handler_outside_the_log_directory_still_writes(tmp_path):
    target = tmp_path / "ok.log"
    root_handlers = logging.getLogger().handlers[:]
    try:
        configure_logging(target)
        logging.getLogger("isolation.probe").warning("kept")
    finally:
        logging.getLogger().handlers[:] = root_handlers
    assert "kept" in Path(target).read_text()
