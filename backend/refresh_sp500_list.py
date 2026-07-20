"""Standalone script: refreshes the stored S&P 500 constituent list from
Wikipedia (see sp500_scraper.py). Intended for a weekly cron entry (see
crontab.txt) -- index membership changes a handful of times a year, not
nightly, so this is deliberately separate from nightly_fundamentals_fetch.py.

On any failure (network, page-structure change, suspiciously-low row
count), the existing stored list is left untouched -- see
sp500_scraper.refresh_sp500_constituents for the failure handling itself.

Run manually:
    uv run python refresh_sp500_list.py
"""

import asyncio
import logging
from pathlib import Path

from sqlmodel import Session

from db import engine, init_db
from logging_config import configure_logging
from sp500_scraper import refresh_sp500_constituents

LOG_PATH = Path(__file__).resolve().parent / "logs" / "sp500_list_refresh.log"


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


if __name__ == "__main__":
    asyncio.run(main())
