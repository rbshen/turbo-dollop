"""Standalone script: nightly Liquidity Zone (LP) detection recompute,
scoped to the union of every watchlist named W1 through W5 (up to 100
tickers each, deduped -- a ticker on more than one matching watchlist is
only processed once) -- NOT the full tracked universe, same scoping as
pipeline/nightly_entry_signal_calculation.py. See CLAUDE.md's "Liquidity
Zone (LP) detection (Technical)" section for the full methodology.

Unlike nightly_entry_signal_calculation.py (hard-forced Yahoo, since FMP's
intraday endpoints are plan-restricted), this feature's daily/weekly bars
work fine on FMP -- clients/daily_price_sources.py::get_daily_bar_source()
uses the ordinary settings.fmp_enabled toggle, so this job needs (and has)
a real FMP<->Yahoo branch, unlike the two other W1-W5-scoped/full-universe
technical jobs.

Fetches every tracked ticker's ~4yr daily OHLC in one shot (FMP: looped,
each call cache-gated; Yahoo: one batch call -- see
clients/daily_price_sources.py), then runs the pure calculation engine for
both Daily and Weekly off that same fetched frame and upserts per ticker
(data.liquidity_zone_data.compute_and_store_liquidity_zones), matching
nightly_entry_signal_calculation.py's own one-fetch-then-per-ticker-compute
shape. After the per-ticker loop, sweeps any existing row whose
computed_at is more than liquidity_zone_data.STALE_AFTER_DAYS old (e.g. a
ticker dropped from both watchlists) -- see
data.liquidity_zone_data.sweep_stale_liquidity_zones's own docstring for
what "stale" means here and why rows are cleared rather than deleted.

Run:
    uv run python -m pipeline.nightly_liquidity_zone_calculation
"""

import asyncio
import logging
import re
import time
from pathlib import Path

from sqlmodel import Session

from clients.daily_price_sources import LOOKBACK_YEARS, get_daily_bar_source
from core.config import settings
from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from data.liquidity_zone_data import compute_and_store_liquidity_zones, sweep_stale_liquidity_zones
from data.watchlists import list_tickers_across_watchlists
from helpers.liquidity_zone_config import get_liquidity_zone_config

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_liquidity_zone_calculation.log"

WATCHLIST_NAME_PATTERN = re.compile(r"^W[1-5]$")

logger = logging.getLogger(__name__)


async def main() -> dict:
    """Returns the run summary dict so tests can assert on it directly
    rather than scraping the log, same convention as
    nightly_entry_signal_calculation.py::main."""
    configure_logging(LOG_PATH)
    init_db()

    with Session(engine) as session:
        tickers, matched_names = list_tickers_across_watchlists(session, WATCHLIST_NAME_PATTERN)
        config = get_liquidity_zone_config(session)

    if not matched_names:
        logger.warning("No watchlist matching %s exists.", WATCHLIST_NAME_PATTERN.pattern)

    if not tickers:
        logger.error("No tickers found across %s -- nothing to process.", matched_names or WATCHLIST_NAME_PATTERN.pattern)
        swept = sweep_stale_liquidity_zones()
        return {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": [], "swept": swept}

    source_name = "fmp" if settings.fmp_enabled else "yahoo"
    logger.info(
        "Starting nightly liquidity-zone calculation for %d tickers across %s (source: %s).", len(tickers), matched_names, source_name
    )
    start_time = time.monotonic()

    bars_by_ticker = await get_daily_bar_source().get_daily_bars(tickers, LOOKBACK_YEARS)

    failures: list[tuple[str, str]] = []
    for i, ticker in enumerate(tickers, start=1):
        try:
            ohlcv = bars_by_ticker.get(ticker)
            if ohlcv is None or ohlcv.empty:
                raise ValueError("No daily OHLC bars returned")
            compute_and_store_liquidity_zones(ticker, ohlcv, source=source_name, config=config)
            logger.info("[%d/%d] %s: ok", i, len(tickers), ticker)
        except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
            logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
            failures.append((ticker, str(exc)))

    swept = sweep_stale_liquidity_zones()

    duration = time.monotonic() - start_time
    logger.info(
        "Nightly liquidity-zone calculation complete. Processed: %d. Failed: %d. Swept: %d. Duration: %.1fs.",
        len(tickers),
        len(failures),
        swept,
        duration,
    )
    if failures:
        logger.info("Tickers with failures: %s", ", ".join(f"{t} ({e})" for t, e in failures))

    return {"processed": len(tickers), "failed": len(failures), "duration_seconds": duration, "failures": failures, "swept": swept}


if __name__ == "__main__":
    with cron_heartbeat("pipeline.nightly_liquidity_zone_calculation"):
        asyncio.run(main())
