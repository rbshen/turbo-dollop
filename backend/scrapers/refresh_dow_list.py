"""Standalone script: refreshes the stored Dow Jones Industrial Average
constituent list from Wikipedia (see dow_scraper.py). Intended for a weekly
cron entry (see crontab.txt) -- index membership changes a handful of times
a year, not nightly, so this is deliberately separate from
nightly_fundamentals_fetch.py. Mirrors refresh_sp500_list.py exactly.

On any failure (network, page-structure change, suspiciously-low row
count), the existing stored list is left untouched -- see
dow_scraper.refresh_dow_constituents for the failure handling itself.

Run manually:
    uv run python -m scrapers.refresh_dow_list
"""

import asyncio
import logging
from pathlib import Path

from sqlmodel import Session

from db import engine, init_db
from scrapers.dow_scraper import refresh_dow_constituents
from logging_config import configure_logging

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


if __name__ == "__main__":
    asyncio.run(main())
