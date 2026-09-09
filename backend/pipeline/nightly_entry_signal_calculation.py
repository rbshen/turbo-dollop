"""Standalone script: nightly BB+RSI (2h) technical entry-signal recompute,
scoped to the single named "Watchlist" watchlist (up to 100 tickers, today
50) -- NOT the full tracked universe, unlike every other nightly job in
this package. See CLAUDE.md's technical entry-signal section for the full
methodology and Phase 1 investigation this is built on.

Runs entirely on Yahoo Finance (clients/technical_sources.py) -- FMP's
intraday endpoints return HTTP 402 under the current subscription plan
(confirmed 2026-09-09), so this makes ZERO FMP calls and needs no `if not
settings.fmp_enabled: ...` guard, the same reasoning
nightly_trend_calculation.py's own docstring gives for its own Yahoo-only
fetches.

Fetches every Watchlist ticker's intraday bars in ONE batch call (see
clients/technical_sources.py::get_technical_source().get_intraday_bars),
then runs the pure calculation engine and upserts per ticker
(data.entry_signal_data.compute_and_store_entry_signal), matching
nightly_trend_calculation.py's own one-batch-fetch-then-per-ticker-compute
shape.

Run:
    uv run python -m pipeline.nightly_entry_signal_calculation
"""

import asyncio
import logging
import time
from pathlib import Path

from sqlmodel import Session

from clients.technical_sources import get_technical_source
from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from data.entry_signal_data import compute_and_store_entry_signal
from data.watchlists import get_watchlist_by_name, list_watchlist_tickers

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_entry_signal_calculation.log"

WATCHLIST_NAME = "Watchlist"
LOOKBACK_DAYS = 60
SOURCE_NAME = "yahoo"

logger = logging.getLogger(__name__)


async def main() -> dict:
    """Returns the run summary dict so tests can assert on it directly
    rather than scraping the log, same convention as
    nightly_trend_calculation.py::main."""
    configure_logging(LOG_PATH)
    init_db()

    with Session(engine) as session:
        watchlist = get_watchlist_by_name(session, WATCHLIST_NAME)
        if watchlist is None:
            logger.error('No watchlist named "%s" exists -- nothing to process.', WATCHLIST_NAME)
            return {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": []}
        tickers = [row.ticker for row in list_watchlist_tickers(session, watchlist.id)]

    if not tickers:
        logger.error('Watchlist "%s" has no tickers -- nothing to process.', WATCHLIST_NAME)
        return {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": []}

    logger.info('Starting nightly entry-signal calculation for %d "%s" tickers.', len(tickers), WATCHLIST_NAME)
    start_time = time.monotonic()

    bars_by_ticker = await get_technical_source().get_intraday_bars(tickers, LOOKBACK_DAYS)

    failures: list[tuple[str, str]] = []
    for i, ticker in enumerate(tickers, start=1):
        try:
            bars = bars_by_ticker.get(ticker)
            if bars is None or bars.empty:
                raise ValueError("No intraday bars returned")
            compute_and_store_entry_signal(ticker, bars, source=SOURCE_NAME)
            logger.info("[%d/%d] %s: ok", i, len(tickers), ticker)
        except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
            logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
            failures.append((ticker, str(exc)))

    duration = time.monotonic() - start_time
    logger.info(
        "Nightly entry-signal calculation complete. Processed: %d. Failed: %d. Duration: %.1fs.",
        len(tickers),
        len(failures),
        duration,
    )
    if failures:
        logger.info("Tickers with failures: %s", ", ".join(f"{t} ({e})" for t, e in failures))

    return {"processed": len(tickers), "failed": len(failures), "duration_seconds": duration, "failures": failures}


if __name__ == "__main__":
    with cron_heartbeat("pipeline.nightly_entry_signal_calculation"):
        asyncio.run(main())
