"""Standalone script: refreshes the stored Dow Jones Industrial Average
constituent list from Wikipedia (see dow_scraper.py). Intended for a weekly
cron entry (see crontab.txt) -- index membership changes a handful of times
a year, not nightly, so this is deliberately separate from
nightly_fundamentals_fetch.py. Mirrors refresh_sp500_list.py exactly.

On any failure (network, page-structure change, suspiciously-low row
count), the existing stored list is left untouched -- see
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

Run manually:
    uv run python -m scrapers.refresh_dow_list
"""

import asyncio
import logging
from pathlib import Path

from sqlmodel import Session

from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from scrapers.dow_scraper import refresh_dow_constituents
from core.logging_config import configure_logging

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "dow_list_refresh.log"


async def main() -> None:
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    with Session(engine) as session:
        result = await refresh_dow_constituents(session)

    if result.success:
        logger.info("Dow constituent list refreshed: %d tickers stored.", result.constituent_count)
    else:
        logger.error("Dow constituent list refresh failed, existing list left unchanged: %s", result.error)
        raise RuntimeError(f"Dow constituent list refresh failed: {result.error}")


if __name__ == "__main__":
    with cron_heartbeat("scrapers.refresh_dow_list"):
        asyncio.run(main())
