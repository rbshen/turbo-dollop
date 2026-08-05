import logging
import re
from pathlib import Path

# Matches "apikey=<value>" case-insensitively, stopping at the next query
# separator/quote so it works whether it's mid-URL ("...&apikey=X&...") or
# at the end of one.
_APIKEY_PATTERN = re.compile(r'(apikey=)[^&\s"\']+', re.IGNORECASE)


class RedactApiKeyFilter(logging.Filter):
    """Strips the FMP apikey query parameter from a log record's rendered
    message before it's written anywhere. httpx logs full request URLs
    (apikey and all) at INFO level, and the standalone scripts that use
    this module run at INFO to capture per-ticker fetch activity -- without
    this filter, the real API key ends up in plaintext in both the log file
    and the terminal."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _APIKEY_PATTERN.sub(r"\1REDACTED", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def apply_redaction_filters() -> None:
    """Attaches the redaction filter directly to the specific loggers that
    can emit a raw FMP/SEC request URL (httpx's own request logging, and
    cache.safe_fetch's warning on a failed fetch, which embeds the raw
    httpx exception -- URL and apikey included -- in its message). Filters
    attached to a logger run before that logger hands the record to any
    handler, so this works regardless of what handler configuration is in
    effect -- unlike configure_logging() below, it doesn't touch handlers,
    levels, or output destination, so it's safe to call from the live
    FastAPI app (main.py) without fighting uvicorn's own logging setup."""
    redact_filter = RedactApiKeyFilter()
    for name in ("httpx", "cache", "fmp_client", "sec_edgar"):
        logging.getLogger(name).addFilter(redact_filter)


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
