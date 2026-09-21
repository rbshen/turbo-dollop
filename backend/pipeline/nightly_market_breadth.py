"""Standalone script: nightly market-breadth recompute -- the % of S&P 500
constituents above their 50-/200-day SMA and net new 52-week highs minus
lows, one MarketBreadthSnapshot row per session. See
data/market_breadth_data.py for the compute/gate/persist logic and
scoring/market_breadth.py for the pure math. Makes ZERO FMP calls (Yahoo
Finance bars only, via SharedBarsCache), so like nightly_trend_calculation.py
and nightly_sector_heatmap.py it needs no FMP_ENABLED guard.

Scheduled at 3:35 AM, AFTER the 3:10 trend job that fetches every S&P 500
ticker's 2y daily bars into SharedBarsCache: this reads that warm cache
(~3s, zero incremental Yahoo requests). Run before it -- or after a failed
trend job -- it self-heals with one live ~503-request batch (~30s-5min) and
writes through the shared cache like any other consumer.

Universe: IndexConstituent "sp500" strictly (load_sp500_tickers), not
load_universe_tickers' S&P 500 + Dow union.

Raises (so cron_heartbeat records a failed run) when fewer than 97% of the
constituents have a bar on the anchor session, writing nothing -- see
data/market_breadth_data.py's coverage-gate note. A weekend/holiday run
re-derives the same anchor and upserts over its own row, harmless.

Run:
    uv run python -m pipeline.nightly_market_breadth
"""

import asyncio
import logging
import time
from pathlib import Path

from sqlmodel import Session

from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from data.market_breadth_data import compute_and_store_market_breadth
from pipeline.nightly_fundamentals_fetch import load_sp500_tickers

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_market_breadth.log"

logger = logging.getLogger(__name__)


async def main() -> dict:
    """Returns the run summary dict so tests/manual runs can assert on it
    directly rather than scraping the log."""
    configure_logging(LOG_PATH)
    init_db()

    with Session(engine) as session:
        tickers = load_sp500_tickers(session)

    logger.info("Starting nightly market breadth calculation for %d S&P 500 constituents.", len(tickers))
    start_time = time.monotonic()
    summary = await compute_and_store_market_breadth(tickers)
    summary["duration_seconds"] = time.monotonic() - start_time
    logger.info(
        "Nightly market breadth complete. As of: %s. Constituents: %d. With bar: %d. Excluded: %d. Duration: %.1fs.",
        summary["as_of_date"],
        summary["constituents"],
        summary["with_bar"],
        summary["stale_excluded"],
        summary["duration_seconds"],
    )
    return summary


if __name__ == "__main__":
    with cron_heartbeat("pipeline.nightly_market_breadth"):
        asyncio.run(main())
