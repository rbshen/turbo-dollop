import importlib
import io
import logging

import httpx
import pytest

from core.logging_config import REDACTED_LOGGER_NAMES, RedactApiKeyFilter, apply_redaction_filters, configure_logging


def _filtered_message(raw_message: str) -> str:
    record = logging.LogRecord(
        name="httpx", level=logging.INFO, pathname=__file__, lineno=1, msg=raw_message, args=(), exc_info=None
    )
    RedactApiKeyFilter().filter(record)
    return record.getMessage()


def test_redacts_apikey_in_the_middle_of_a_url():
    message = (
        'HTTP Request: GET https://financialmodelingprep.com/stable/quote?symbol=AAPL&apikey=SECRET12345 "HTTP/1.1 200 OK"'
    )
    result = _filtered_message(message)
    assert "SECRET12345" not in result
    assert "apikey=REDACTED" in result
    assert "symbol=AAPL" in result  # other query params must survive untouched


def test_redacts_apikey_at_the_end_of_a_url():
    message = "GET https://financialmodelingprep.com/stable/profile?symbol=MSFT&apikey=ABCDEF999"
    result = _filtered_message(message)
    assert "ABCDEF999" not in result
    assert result.endswith("apikey=REDACTED")


def test_case_insensitive_apikey_param_name():
    message = "GET https://example.com/x?ApiKey=SHOULDNOTLEAK"
    result = _filtered_message(message)
    assert "SHOULDNOTLEAK" not in result


def test_message_without_apikey_is_left_unchanged():
    message = "Starting nightly fundamentals fetch for 500 tickers."
    result = _filtered_message(message)
    assert result == message


def test_configure_logging_writes_redacted_output_to_the_log_file(tmp_path):
    log_path = tmp_path / "test.log"
    configure_logging(log_path)

    fake_key_shaped_value = "FAKE0000TESTKEY0000PLACEHOLDER0"
    logging.getLogger("httpx").info(
        "HTTP Request: GET https://financialmodelingprep.com/stable/quote?symbol=AAPL&apikey=%s \"HTTP/1.1 200 OK\"",
        fake_key_shaped_value,
    )
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_path.read_text()
    assert fake_key_shaped_value not in content
    assert "apikey=REDACTED" in content


# --- Redaction reaches the loggers the code really uses ------------------------------------------------------------

SECRET = "FAKE0000TESTKEY0000PLACEHOLDER0"
URL = f"https://financialmodelingprep.com/stable/quote?symbol=AAPL&apikey={SECRET}"
REAL_LOGGER_MODULES = ["core.cache", "clients.fmp_client"]


def _httpx_error() -> httpx.HTTPStatusError:
    """What FMPClient's raise_for_status raises: the message embeds the whole request URL, apikey included."""
    return httpx.HTTPStatusError(
        f"Client error '401 Unauthorized' for url '{URL}'\nFor more information check: https://developer.mozilla.org",
        request=httpx.Request("GET", URL),
        response=httpx.Response(401),
    )


class _Capture(logging.Handler):
    """Formats every record that reaches it the way a file handler would, traceback included."""

    def __init__(self) -> None:
        super().__init__()
        self.stream = io.StringIO()
        self.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self.stream.write(self.format(record) + "\n")

    @property
    def text(self) -> str:
        return self.stream.getvalue()


def _log_the_failure(logger: logging.Logger) -> None:
    """The three ways the app logs an httpx error: in the message, as a %s argument, and as a traceback."""
    error = _httpx_error()
    logger.warning("GET %s failed", URL)
    logger.warning("FMP fetch failed for %s: %s", "AAPL", error)
    try:
        raise error
    except httpx.HTTPStatusError:
        logger.warning("fetch failed", exc_info=True)
        logger.exception("fetch failed again")


@pytest.mark.parametrize("module_name", REAL_LOGGER_MODULES)
def test_the_redacted_names_are_the_real_logger_names(module_name):
    module = importlib.import_module(module_name)
    assert module.logger.name in REDACTED_LOGGER_NAMES, (
        f"{module_name} logs as {module.logger.name!r}, which apply_redaction_filters does not cover"
    )


@pytest.mark.parametrize("module_name", REAL_LOGGER_MODULES)
def test_apikey_is_redacted_through_each_real_logger(module_name):
    logger = importlib.import_module(module_name).logger
    apply_redaction_filters()
    capture = _Capture()
    logger.addHandler(capture)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        _log_the_failure(logger)
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)
    assert capture.text.count("apikey=REDACTED") >= 4
    assert SECRET not in capture.text
    assert "symbol=AAPL" in capture.text  # the rest of the URL survives


def test_apikey_is_redacted_through_httpx_own_logger():
    apply_redaction_filters()
    capture = _Capture()
    logger = logging.getLogger("httpx")
    logger.addHandler(capture)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        logger.info('HTTP Request: GET %s "HTTP/1.1 401 Unauthorized"', URL)
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)
    assert SECRET not in capture.text
    assert "apikey=REDACTED" in capture.text


def test_apikey_is_redacted_for_a_logger_the_filter_was_not_attached_to():
    """data.etf_data and others log an httpx exception too; their records reach the root handler, where the filter sits."""
    root = logging.getLogger()
    capture = _Capture()
    root.addHandler(capture)
    previous_level = root.level
    root.setLevel(logging.INFO)
    try:
        apply_redaction_filters()
        _log_the_failure(logging.getLogger("data.etf_data"))
    finally:
        root.removeHandler(capture)
        root.setLevel(previous_level)
    assert capture.text.count("apikey=REDACTED") >= 4
    assert SECRET not in capture.text


def test_the_last_resort_handler_is_covered_for_the_api_process():
    """Under uvicorn the root logger has no handler, so Python writes warnings through logging.lastResort."""
    apply_redaction_filters()
    capture = _Capture()
    capture.filters = list(logging.lastResort.filters)  # the filters apply_redaction_filters put on it
    assert any(isinstance(f, RedactApiKeyFilter) for f in logging.lastResort.filters)
    record = logging.LogRecord("data.etf_data", logging.WARNING, __file__, 1, "failed: %s", (_httpx_error(),), None)
    assert all(f.filter(record) for f in capture.filters)
    capture.handle(record)
    assert SECRET not in capture.text


def test_apply_redaction_filters_is_idempotent():
    apply_redaction_filters()
    apply_redaction_filters()
    for name in REDACTED_LOGGER_NAMES:
        assert sum(isinstance(f, RedactApiKeyFilter) for f in logging.getLogger(name).filters) == 1


@pytest.mark.parametrize("module_name", REAL_LOGGER_MODULES)
def test_cron_entry_point_logging_redacts_through_each_real_logger(tmp_path, module_name):
    """configure_logging is what every cron job's main() calls: the log file must never hold the key."""
    log_path = tmp_path / "cron.log"
    configure_logging(log_path)
    logger = importlib.import_module(module_name).logger
    _log_the_failure(logger)
    _log_the_failure(logging.getLogger("pipeline.some_job"))  # a logger the filters are not attached to by name
    for handler in logging.getLogger().handlers:
        handler.flush()
    content = log_path.read_text()
    assert SECRET not in content
    assert content.count("apikey=REDACTED") >= 8
