"""Standalone script: nightly Sector Heatmap recompute -- the 11 SPDR sector
ETFs x 8 trailing total-return windows (1d/1w/1m/3m/6m/9m/YTD/1y). See
data/sector_heatmap_data.py for the fetch/compute/persist logic and
scoring/etf_returns.py for the pure return math. Makes ZERO FMP calls
(Yahoo Finance only, one batch download, ~3-4s), so like
nightly_trend_calculation.py it needs no FMP_ENABLED guard.

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

from core.cron_health import cron_heartbeat
from core.db import init_db
from core.logging_config import configure_logging
from data.sector_heatmap_data import compute_and_store_sector_returns, prune_sector_etf_returns

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
    summary["duration_seconds"] = time.monotonic() - start_time
    logger.info(
        "Nightly sector heatmap complete. As of: %s. Processed: %d. Failed: %d. Pruned: %d. Duration: %.1fs.",
        summary["as_of_date"],
        summary["processed"],
        summary["failed"],
        summary["pruned"],
        summary["duration_seconds"],
    )
    return summary


if __name__ == "__main__":
    with cron_heartbeat("pipeline.nightly_sector_heatmap"):
        asyncio.run(main())
