"""Standalone script: deletes FundamentalsCache rows older than
Settings.cache_retention_days (default 180) -- distinct from
cache_staleness_days, which only controls when a row is refetched, never
when it's deleted. A ticker inside the nightly-refreshed S&P 500/Dow
universe is upserted in place forever (see cache.py::get_or_fetch) and never
accumulates rows on its own; growth instead comes from one-off lookups of
tickers outside that universe that are never revisited. This bounds that
growth without touching cache freshness for actively-used tickers.

Run (deletes for real):
    uv run python -m pipeline.prune_cache

Preview without deleting:
    uv run python -m pipeline.prune_cache --dry-run

Override the retention window for one run:
    uv run python -m pipeline.prune_cache --retention-days 90
"""

import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete
from sqlmodel import Session, func, select

from core.config import settings
from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from core.models import FundamentalsCache

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "prune_cache.log"

logger = logging.getLogger(__name__)


def prune_cache(retention_days: int, dry_run: bool = False) -> int:
    """Returns the number of rows deleted (or that would be deleted, under
    --dry-run)."""
    cutoff = datetime.now() - timedelta(days=retention_days)
    with Session(engine) as session:
        count = session.exec(
            select(func.count()).select_from(FundamentalsCache).where(FundamentalsCache.fetched_at < cutoff)
        ).one()
        if count and not dry_run:
            session.execute(delete(FundamentalsCache).where(FundamentalsCache.fetched_at < cutoff))
            session.commit()
    return count


def main(retention_days: int | None = None, dry_run: bool = False) -> int:
    configure_logging(LOG_PATH)
    init_db()
    retention = retention_days if retention_days is not None else settings.cache_retention_days
    count = prune_cache(retention, dry_run=dry_run)
    if dry_run:
        logger.info("Dry run: %d FundamentalsCache row(s) older than %d days would be deleted.", count, retention)
    else:
        logger.info("Pruned %d FundamentalsCache row(s) older than %d days.", count, retention)
    return count


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete FundamentalsCache rows past the retention window.")
    parser.add_argument(
        "--retention-days", type=int, default=None, help="Override Settings.cache_retention_days for this run."
    )
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted without deleting.")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    with cron_heartbeat("pipeline.prune_cache"):
        main(cli_args.retention_days, dry_run=cli_args.dry_run)
