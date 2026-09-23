"""Standalone script: nightly Sector Heatmap recompute -- the 11 SPDR sector
ETFs x 8 trailing total-return windows (1d/1w/1m/3m/6m/9m/YTD/1y). See
data/sector_heatmap_data.py for the fetch/compute/persist logic and
scoring/etf_returns.py for the pure return math. Makes ZERO FMP calls (a
single shared-bars-cache batch fetch -- Massive/Polygon with an automatic
Yahoo fallback per clients/daily_bar_sources.py -- ~3-4s on a warm cache),
so like nightly_trend_calculation.py it needs no FMP_ENABLED guard.

Recomputes every window for every fund on every run -- there is no gate on
"is today a trading day": a weekend/holiday run re-derives the same anchor
(the last completed session) and upserts over its own rows, harmless.

Raises (so cron_heartbeat records a failed run) only when NOTHING could be
computed; individual funds failing are logged and reported in the summary,
same per-item isolation the other nightly jobs use.

After storing tonight's rows it prunes snapshots older than the rolling
retention window (data.sector_heatmap_data.RETENTION_DAYS, 370 days) -- a
step of this job rather than its own cron entry, same as the other nightly
jobs' prune calls. It is skipped when the compute raises.

Run:
    uv run python -m pipeline.nightly_sector_heatmap
"""

import asyncio
import logging
import time
from datetime import date
from pathlib import Path

from clients.shared_bars_cache import DAILY_INTERVAL, stale_ticker_count
from core.cron_health import cron_heartbeat
from core.db import init_db
from core.logging_config import configure_logging
from data.sector_heatmap_data import SECTOR_ETFS, compute_and_store_sector_returns, prune_sector_etf_returns

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_sector_heatmap.log"

logger = logging.getLogger(__name__)


async def main() -> dict:
    """Returns the run summary dict so tests/manual runs can assert on it
    directly rather than scraping the log."""
    configure_logging(LOG_PATH)
    init_db()

    logger.info("Starting nightly sector heatmap calculation.")
    start_time = time.monotonic()
    summary = await compute_and_store_sector_returns()
    # Only reached after a successful compute (it raises when nothing could be
    # computed), so a failed run never prunes -- see prune_sector_etf_returns.
    summary["pruned"] = prune_sector_etf_returns(date.fromisoformat(summary["as_of_date"]))
    # Stale-data guard (docs/yahoo_close_data_gap_investigation_2026-09-23.md)
    # -- see pipeline/nightly_trend_calculation.py's own equivalent comment
    # for the full reasoning.
    summary["stale_count"], _ = stale_ticker_count([t for t, _ in SECTOR_ETFS], DAILY_INTERVAL)
    summary["duration_seconds"] = time.monotonic() - start_time
    logger.info(
        "Nightly sector heatmap complete. As of: %s. Processed: %d. Failed: %d. Pruned: %d. Stale: %d. Duration: %.1fs.",
        summary["as_of_date"],
        summary["processed"],
        summary["failed"],
        summary["pruned"],
        summary["stale_count"],
        summary["duration_seconds"],
    )
    return summary


if __name__ == "__main__":
    with cron_heartbeat("pipeline.nightly_sector_heatmap") as run:
        summary = asyncio.run(main())
        run.message = (
            f"{summary['processed']}/{len(SECTOR_ETFS)} funds, {summary['stale_count']} still stale after fetch, "
            f"{summary['fallback_count']} fell back to Yahoo"
        )
