"""Standalone script: nightly Liquidity Zone (LP) detection recompute,
scoped to the union of every watchlist named W1 through W5 (up to 100
tickers each, deduped -- a ticker on more than one matching watchlist is
only processed once) -- NOT the full tracked universe, same scoping as
pipeline/nightly_entry_signal_calculation.py. See CLAUDE.md's "Liquidity
Zone (LP) detection (Technical)" section for the full methodology.

**FMP-independent, unconditionally (2026-09-18).** This job used to have a
real FMP<->Yahoo branch (clients/daily_price_sources.py, since deleted,
gated on the ordinary the FMP data-group state toggle) -- unlike
nightly_entry_signal_calculation.py's BB+RSI feed, FMP's daily EOD endpoint
was never plan-restricted, so that branch was the normal degrade pattern
rather than BB+RSI's hard-forced single source. That branch is now
removed: Liquidity Zones is one of six technical-analysis features
(alongside Chart, Weinstein Stage, Trend, Warren, BB+RSI) moved off FMP
entirely, so a paused FMP subscription can never affect what price levels
this feature detects.

**FMP daily bars (Phase 2, 2026-09-24; Massive/Polygon before it, removed in
Phase 6a), with an automatic per-ticker Yahoo fallback.** Reads every tracked ticker's ~4yr daily OHLC
through the shared bars cache (clients/shared_bars_cache.py, interval
"1d" -- the same row Trend/Weinstein Stage reads at a narrower 2y width,
so whichever of the two nightly jobs runs first does the one live fetch
per overlapping ticker and the other reads it back; this job needs no
knowledge of which, or of which underlying provider answered it -- see
clients/daily_bar_sources.py), then runs the pure calculation engine for
both Daily and Weekly off that same fetched frame and upserts per ticker
(data.liquidity_zone_data.compute_and_store_liquidity_zones), matching
nightly_entry_signal_calculation.py's own one-fetch-then-per-ticker-compute
shape. Each row's own `source` field (core/tickers.py::
resolve_daily_bar_source_label) is a best-effort "which provider generally
serves this ticker" label, not a literal per-fetch record -- see that
function's own docstring. After the per-ticker loop, sweeps any existing
row whose computed_at is more than liquidity_zone_data.STALE_AFTER_DAYS
old (e.g. a ticker dropped from both watchlists) -- see
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

from clients.daily_bar_sources import FallbackTickers, describe_fallback
from clients.shared_bars_cache import DAILY_INTERVAL, get_or_fetch_bars_batch, stale_ticker_count
from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from core.tickers import resolve_daily_bar_source_label
from data.liquidity_zone_data import LOOKBACK_DAYS, compute_and_store_liquidity_zones, sweep_stale_liquidity_zones
from data.watchlists import list_tickers_across_watchlists
from helpers.liquidity_zone_config import get_liquidity_zone_settings, to_engine_settings
from pipeline.stale_data_health_check import load_delisted_tickers

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
        settings = to_engine_settings(get_liquidity_zone_settings(session))
        delisted = load_delisted_tickers(session)

    if not matched_names:
        logger.warning("No watchlist matching %s exists.", WATCHLIST_NAME_PATTERN.pattern)

    skipped_delisted = sorted(set(tickers) & delisted)
    if skipped_delisted:
        tickers = [t for t in tickers if t not in delisted]

    if not tickers:
        logger.error("No tickers found across %s -- nothing to process.", matched_names or WATCHLIST_NAME_PATTERN.pattern)
        swept = sweep_stale_liquidity_zones()
        return {
            "processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": [], "swept": swept,
            "stale_count": 0, "fallback_count": 0, "fallback_yahoo_count": 0, "skipped_delisted_count": len(skipped_delisted),
        }

    logger.info(
        "Starting nightly liquidity-zone calculation for %d tickers across %s (%d skipped as delisted).",
        len(tickers), matched_names, len(skipped_delisted),
    )
    start_time = time.monotonic()

    fallback_tickers = FallbackTickers()
    bars_by_ticker = await get_or_fetch_bars_batch(
        tickers, DAILY_INTERVAL, LOOKBACK_DAYS, auto_adjust=False, fallback_tickers=fallback_tickers
    )

    # Stale-data guard (docs/yahoo_close_data_gap_investigation_2026-09-23.md)
    # -- see pipeline/nightly_trend_calculation.py's own equivalent comment
    # for the full reasoning.
    stale_count, _ = stale_ticker_count(tickers, DAILY_INTERVAL)

    failures: list[tuple[str, str]] = []
    for i, ticker in enumerate(tickers, start=1):
        try:
            ohlcv = bars_by_ticker.get(ticker)
            if ohlcv is None or ohlcv.empty:
                raise ValueError("No daily OHLC bars returned")
            compute_and_store_liquidity_zones(ticker, ohlcv, source=resolve_daily_bar_source_label(ticker), settings=settings)
            logger.info("[%d/%d] %s: ok", i, len(tickers), ticker)
        except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
            logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
            failures.append((ticker, str(exc)))

    swept = sweep_stale_liquidity_zones()

    duration = time.monotonic() - start_time
    logger.info(
        "Nightly liquidity-zone calculation complete. Processed: %d. Failed: %d. Swept: %d. Stale: %d. Duration: %.1fs.",
        len(tickers),
        len(failures),
        swept,
        stale_count,
        duration,
    )
    if failures:
        logger.info("Tickers with failures: %s", ", ".join(f"{t} ({e})" for t, e in failures))

    return {
        "processed": len(tickers),
        "failed": len(failures),
        "duration_seconds": duration,
        "failures": failures,
        "swept": swept,
        "stale_count": stale_count,
        "fallback_count": len(fallback_tickers), "fallback_yahoo_count": len(fallback_tickers.yahoo),
        "skipped_delisted_count": len(skipped_delisted),
    }


if __name__ == "__main__":
    with cron_heartbeat("pipeline.nightly_liquidity_zone_calculation") as run:
        summary = asyncio.run(main())
        run.message = (
            f"{summary['processed']} tickers, {summary['stale_count']} still stale after fetch, "
            f"{describe_fallback(summary['fallback_count'], summary['fallback_yahoo_count'])}, {summary['skipped_delisted_count']} skipped as delisted"
        )
