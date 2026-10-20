import logging
import re
from pathlib import Path

# Matches "apikey=<value>" case-insensitively, stopping at the next query
# separator/quote so it works whether it's mid-URL ("...&apikey=X&...") or
# at the end of one.
_APIKEY_PATTERN = re.compile(r'(apikey=)[^&\s"\']+', re.IGNORECASE)


def redact_apikey(text: str) -> str:
    """Strips the FMP apikey query parameter from arbitrary text. Shared by
    RedactApiKeyFilter (log records) and core.cron_health (CronRunLog's
    error_summary, which surfaces via the API/UI banner -- a destination
    that needs the same protection a raw exception message embedding a
    fetch URL could otherwise leak into)."""
    return _APIKEY_PATTERN.sub(r"\1REDACTED", text)


class RedactApiKeyFilter(logging.Filter):
    """Strips the FMP apikey query parameter from a log record's rendered
    message, and from its traceback text, before it's written anywhere. httpx
    logs full request URLs (apikey and all) at INFO level, an httpx
    HTTPStatusError's str() embeds the full URL, and the standalone scripts
    that use this module run at INFO to capture per-ticker fetch activity --
    without this filter, the real API key ends up in plaintext in both the
    log file and the terminal."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_apikey(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        if record.exc_info and not record.exc_text:
            # A logger.warning(..., exc_info=True) renders the traceback inside the handler's formatter, after any
            # filter ran. Rendering it here and storing it as exc_text makes the formatter reuse the redacted copy.
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_apikey(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_apikey(record.stack_info)
        return True


# The loggers that can emit a raw FMP request URL, by their real names (each module logs through
# logging.getLogger(__name__), so these are the module paths, not the bare file names; tests/test_logging_config.py
# pins them against the modules): httpx/httpcore's own request logging, cache.py's failed-fetch warnings and the FMP
# client.
REDACTED_LOGGER_NAMES = ("httpx", "httpcore", "core.cache", "clients.fmp_client")


def _attach(target: logging.Filterer, redact_filter: logging.Filter) -> None:
    if not any(isinstance(f, RedactApiKeyFilter) for f in target.filters):
        target.addFilter(redact_filter)


def apply_redaction_filters() -> None:
    """Attaches the redaction filter in the three places a record carrying a
    raw FMP request URL can pass through, without touching handlers'
    levels, formatters or output destination (so it is safe to call from the
    live FastAPI app (main.py) without fighting uvicorn's own logging setup):

    * the specific loggers above, which run it before the record reaches any
      handler whatever the handler configuration;
    * every handler already on the root logger -- a logger's own filters do
      not run for records propagated up from a child logger, so this covers
      any other module (data.*, pipeline.*) that logs an httpx exception;
    * logging.lastResort, the stderr handler Python falls back to when the
      root logger has no handler at all, which is the case in the uvicorn
      process.

    Idempotent: calling it again attaches nothing twice."""
    redact_filter = RedactApiKeyFilter()
    for name in REDACTED_LOGGER_NAMES:
        _attach(logging.getLogger(name), redact_filter)
    for handler in logging.getLogger().handlers:
        _attach(handler, redact_filter)
    if logging.lastResort is not None:
        _attach(logging.lastResort, redact_filter)


def configure_logging(log_path: Path) -> None:
    """Shared logging setup for the standalone scripts (nightly fundamentals
    fetch, S&P 500 list refresh): file + console output, both with the
    redaction filter attached so a real API key can never reach either."""
    log_path.parent.mkdir(exist_ok=True)
    apply_redaction_filters()
    redact_filter = RedactApiKeyFilter()

    file_handler = logging.FileHandler(log_path)
    file_handler.addFilter(redact_filter)

    stream_handler = logging.StreamHandler()
    stream_handler.addFilter(redact_filter)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[file_handler, stream_handler],
        # basicConfig is a no-op if the root logger already has handlers
        # (e.g. pytest's own logging capture) -- force=True makes this
        # script's explicit configuration always take effect, which is also
        # what makes the redaction filter reliably testable.
        force=True,
    )
