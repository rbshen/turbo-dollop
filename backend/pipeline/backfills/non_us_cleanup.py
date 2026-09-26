"""One-time non-US cleanup (2026-09-26), run after Fathom dropped non-US ticker support. Already
run; kept as documentation of how it was done (like the other backfills here). Run from backend/:

    uv run python -m pipeline.backup_db                                  # ALWAYS back up first
    uv run python -m pipeline.backfills.non_us_cleanup --dry-run
    uv run python -m pipeline.backfills.non_us_cleanup

Two steps, each idempotent (a second run changes nothing):
  1. Delete every row for the known leftover Hong Kong tickers (KNOWN_HK_TICKERS) and for any other
     tracked ticker that is not US-listed (pipeline/non_us_purge.py -- the same detection the weekly
     stale_data_health_check runs), across every table with a `ticker` column.
  2. Delete the non-US DiscountRateConfig rows (the HK/FR per-country rates); only US is supported.

`main()` also runs init_db(), whose obsolete-column sweep drops TickerScore.country and
SavedScreenerFilter.country (the removed Screener Country filter).

On 2026-09-26 the real DB already held none of the six tickers (an earlier cleanup had purged them),
so the real run changed only the HK discount-rate row and the two columns.

Touches the real DB (core.db.engine) by design, like every pipeline script; tests exercise `run()`
against an in-memory engine.
"""

import argparse
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session

from core.db import engine as real_engine
from core.db import init_db
from pipeline.non_us_purge import find_non_us_tickers, purge_tickers

logger = logging.getLogger(__name__)

KNOWN_HK_TICKERS = ("0005.HK", "0728.HK", "0857.HK", "0883.HK", "0941.HK", "3988.HK")


def run(engine: Engine, dry_run: bool = False) -> dict:
    """Returns what changed (or would change, under dry_run)."""
    with Session(engine) as session:
        detected = set(find_non_us_tickers(session))
    tickers = sorted(detected | set(KNOWN_HK_TICKERS))
    rows = purge_tickers(engine, tickers, dry_run=dry_run)

    discount_rows = 0
    with engine.begin() as conn:
        if conn.execute(text("select 1 from sqlite_master where type='table' and name='discountrateconfig'")).first():
            discount_rows = conn.execute(text("select count(*) from discountrateconfig where region != 'US'")).scalar_one()
            if not dry_run and discount_rows:
                conn.execute(text("delete from discountrateconfig where region != 'US'"))
    return {"tickers_checked": tickers, "rows_deleted_by_table": rows, "discount_rate_rows_deleted": discount_rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="One-time cleanup of non-US tickers and the HK/FR discount rates.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change; write nothing.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if not args.dry_run:
        init_db()  # drops the removed Screener country columns (idempotent)
    result = run(real_engine, dry_run=args.dry_run)
    logger.info("%s: %s", "Dry run (nothing written)" if args.dry_run else "Done", result)


if __name__ == "__main__":
    main()
