"""Standalone script: refreshes the stored S&P 500 constituent list from
Wikipedia (see sp500_scraper.py). Intended for a weekly cron entry (see
crontab.txt) -- index membership changes a handful of times a year, not
nightly, so this is deliberately separate from nightly_fundamentals_fetch.py.

On any failure (network, page-structure change, suspiciously-low row
count), the existing stored list is left untouched -- see
sp500_scraper.refresh_sp500_constituents for the failure handling itself.

A failed SyncResult is re-raised as a RuntimeError here (2026-09-11) --
see refresh_dow_list.py's own docstring for the confirmed incident that
motivated this (that job's identical shape silently reported "success" on
every failed run for weeks). This job hasn't hit the same latent gap yet,
but shares the exact same `if result.success: ... else: logger.error(...)`
shape with nothing propagating to cron_heartbeat, so it's fixed here too
rather than left to fail the same way later.

Run manually:
    uv run python -m scrapers.refresh_sp500_list
"""

import asyncio
import logging
from pathlib import Path

from sqlmodel import Session

from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from scrapers.sp500_scraper import refresh_sp500_constituents

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "sp500_list_refresh.log"


async def main() -> None:
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    with Session(engine) as session:
        result = await refresh_sp500_constituents(session)

    if result.success:
        logger.info("S&P 500 constituent list refreshed: %d tickers stored.", result.constituent_count)
    else:
        logger.error("S&P 500 constituent list refresh failed, existing list left unchanged: %s", result.error)
        raise RuntimeError(f"S&P 500 constituent list refresh failed: {result.error}")


if __name__ == "__main__":
    with cron_heartbeat("scrapers.refresh_sp500_list"):
        asyncio.run(main())
