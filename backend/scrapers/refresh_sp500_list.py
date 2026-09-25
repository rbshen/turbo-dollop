"""Standalone script: refreshes the stored S&P 500 constituent list from
FMP's /sp500-constituent endpoint (see sp500_scraper.py; this replaced the
prior Wikipedia-scrape pipeline 2026-09-15, once FMP Ultimate's constituent
endpoints became available on this plan -- previously 402). Intended for a
weekly cron entry (see crontab.txt) -- index membership changes a handful of
times a year, not nightly, so this is deliberately separate from
nightly_fundamentals_fetch.py.

On any failure (network/FMP error, response-shape change, suspiciously-low
row count), the existing stored list is left untouched -- see
sp500_scraper.refresh_sp500_constituents for the failure handling itself.

A failed SyncResult is re-raised as a RuntimeError here (2026-09-11) --
see refresh_dow_list.py's own docstring for the confirmed incident that
motivated this (that job's identical shape silently reported "success" on
every failed run for weeks). This job hasn't hit the same latent gap yet,
but shares the exact same `if result.success: ... else: logger.error(...)`
shape with nothing propagating to cron_heartbeat, so it's fixed here too
rather than left to fail the same way later.

the index_membership data group not live (2026-09-15): skipped cleanly before any fetch is
attempted, via the same early-return guard nightly_fundamentals_fetch.py/
nightly_price_target_snapshot.py use -- checked here rather than left to
FMPDisabledError propagating up through refresh_sp500_constituents, since
that path would return a failed SyncResult and hit the RuntimeError re-raise
above, recording a false "failure" in cron_heartbeat for what is actually a
deliberate, healthy no-op. The existing stored list is left untouched
either way.

Run manually:
    uv run python -m scrapers.refresh_sp500_list
"""

import asyncio
import logging
from pathlib import Path

from sqlmodel import Session

from core.data_groups import job_skip_reason
from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from scrapers.sp500_scraper import refresh_sp500_constituents

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "sp500_list_refresh.log"


async def main() -> int | None:
    """Returns the number of tickers synced, or None if skipped (FMP
    disabled) -- lets the cron_heartbeat wrapper below tell the two states
    apart for its own summary message."""
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    skip_reason = job_skip_reason("index_membership")
    if skip_reason:
        logger.info("S&P 500 constituent list refresh %s.", skip_reason)
        return None

    with Session(engine) as session:
        result = await refresh_sp500_constituents(session)

    if result.success:
        logger.info("S&P 500 constituent list refreshed: %d tickers stored.", result.constituent_count)
        return result.constituent_count
    else:
        logger.error("S&P 500 constituent list refresh failed, existing list left unchanged: %s", result.error)
        raise RuntimeError(f"S&P 500 constituent list refresh failed: {result.error}")


if __name__ == "__main__":
    with cron_heartbeat("scrapers.refresh_sp500_list") as run:
        count = asyncio.run(main())
        if count is None:
            run.skip(job_skip_reason("index_membership") or "skipped")
        else:
            run.message = f"{count} tickers synced"
