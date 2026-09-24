"""Standalone script: refreshes the stored Nasdaq-100 constituent list from
FMP's /nasdaq-constituent endpoint (see nasdaq_scraper.py). Mirrors
refresh_dow_list.py/refresh_sp500_list.py exactly. Intended for a weekly
cron entry (see crontab.txt) -- index membership changes a handful of times
a year, not nightly, so this is deliberately separate from
nightly_fundamentals_fetch.py.

On any failure (network/FMP error, response-shape change, suspiciously-low
row count), the existing stored list is left untouched -- see
nasdaq_scraper.refresh_nasdaq_constituents for the failure handling itself.

A failed SyncResult is re-raised as a RuntimeError here, mirroring
refresh_dow_list.py's own fix (2026-09-11) -- since cron_heartbeat only
distinguishes success/failure by whether an exception escapes the `with`
block, a failed run must never be recorded as a "success" CronRunLog row.

The index_membership data group not live: skipped cleanly before any fetch is attempted, via the
same early-return guard refresh_dow_list.py/refresh_sp500_list.py use --
checked here rather than left to FMPDisabledError propagating up through
refresh_nasdaq_constituents, since that path would return a failed
SyncResult and hit the RuntimeError re-raise above, recording a false
"failure" in cron_heartbeat for what is actually a deliberate, healthy
no-op. The existing stored list is left untouched either way.

Run manually:
    uv run python -m scrapers.refresh_nasdaq_list
"""

import asyncio
import logging
from pathlib import Path

from sqlmodel import Session

from core.data_groups import job_skip_reason
from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from scrapers.nasdaq_scraper import refresh_nasdaq_constituents
from core.logging_config import configure_logging

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nasdaq_list_refresh.log"


async def main() -> int | None:
    """Returns the number of tickers synced, or None if skipped (FMP
    disabled) -- lets the cron_heartbeat wrapper below tell the two states
    apart for its own summary message."""
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    skip_reason = job_skip_reason("index_membership")
    if skip_reason:
        logger.info("Nasdaq-100 constituent list refresh %s.", skip_reason)
        return None

    with Session(engine) as session:
        result = await refresh_nasdaq_constituents(session)

    if result.success:
        logger.info("Nasdaq-100 constituent list refreshed: %d tickers stored.", result.constituent_count)
        return result.constituent_count
    else:
        logger.error("Nasdaq-100 constituent list refresh failed, existing list left unchanged: %s", result.error)
        raise RuntimeError(f"Nasdaq-100 constituent list refresh failed: {result.error}")


if __name__ == "__main__":
    with cron_heartbeat("scrapers.refresh_nasdaq_list") as run:
        count = asyncio.run(main())
        if count is None:
            run.skip(job_skip_reason("index_membership") or "skipped")
        else:
            run.message = f"{count} tickers synced"
