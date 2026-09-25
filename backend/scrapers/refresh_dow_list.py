"""Standalone script: refreshes the stored Dow Jones Industrial Average
constituent list from FMP's /dowjones-constituent endpoint (see
dow_scraper.py; this replaced the prior Wikipedia-scrape pipeline
2026-09-15, once FMP Ultimate's constituent endpoints became available on
this plan -- previously 402). Intended for a weekly cron entry (see
crontab.txt) -- index membership changes a handful of times a year, not
nightly, so this is deliberately separate from nightly_fundamentals_fetch.py.
Mirrors refresh_sp500_list.py exactly.

On any failure (network/FMP error, response-shape change, suspiciously-low
row count), the existing stored list is left untouched -- see
dow_scraper.refresh_dow_constituents for the failure handling itself.

A failed SyncResult is re-raised as a RuntimeError here (2026-09-11), after
`SyncResult(success=False, ...)` was found flowing straight into a logged
`logger.error(...)` with nothing propagating out of `main()` -- since
cron_heartbeat only distinguishes success/failure by whether an exception
escaped the `with` block, every failed run was recorded as a "success"
CronRunLog row. Confirmed live: the Dow list failed every weekly run from
2026-08-16 through 2026-09-06 (Wikipedia's "constituents" table went
missing) with `CronRunLog`/`GET /api/config/cron-health` showing "ok" the
whole time. The DB-safety behavior itself (never touch the stored list on
a failed sync) is unchanged -- this only makes an already-decided failure
visible to the heartbeat.

the index_membership data group not live (2026-09-15): skipped cleanly before any fetch is
attempted, via the same early-return guard nightly_fundamentals_fetch.py/
nightly_price_target_snapshot.py use -- checked here rather than left to
FMPDisabledError propagating up through refresh_dow_constituents, since that
path would return a failed SyncResult and hit the RuntimeError re-raise
above, recording a false "failure" in cron_heartbeat for what is actually a
deliberate, healthy no-op. The existing stored list is left untouched
either way.

Run manually:
    uv run python -m scrapers.refresh_dow_list
"""

import asyncio
import logging
from pathlib import Path

from sqlmodel import Session

from core.data_groups import job_skip_reason
from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from scrapers.dow_scraper import refresh_dow_constituents
from core.logging_config import configure_logging

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "dow_list_refresh.log"


async def main() -> int | None:
    """Returns the number of tickers synced, or None if skipped (FMP
    disabled) -- lets the cron_heartbeat wrapper below tell the two states
    apart for its own summary message."""
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    skip_reason = job_skip_reason("index_membership")
    if skip_reason:
        logger.info("Dow constituent list refresh %s.", skip_reason)
        return None

    with Session(engine) as session:
        result = await refresh_dow_constituents(session)

    if result.success:
        logger.info("Dow constituent list refreshed: %d tickers stored.", result.constituent_count)
        return result.constituent_count
    else:
        logger.error("Dow constituent list refresh failed, existing list left unchanged: %s", result.error)
        raise RuntimeError(f"Dow constituent list refresh failed: {result.error}")


if __name__ == "__main__":
    with cron_heartbeat("scrapers.refresh_dow_list") as run:
        count = asyncio.run(main())
        if count is None:
            run.skip(job_skip_reason("index_membership") or "skipped")
        else:
            run.message = f"{count} tickers synced"
