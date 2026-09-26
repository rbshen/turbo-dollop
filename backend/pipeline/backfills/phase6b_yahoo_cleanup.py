"""One-time Phase 6b (2026-09-26) data cleanup after Yahoo Finance was removed. Already run; kept as
documentation of how the migration was done (like the other backfills here). Run from backend/:

    uv run python -m pipeline.backup_db                                  # ALWAYS back up first
    uv run python -m pipeline.backfills.phase6b_yahoo_cleanup --dry-run
    uv run python -m pipeline.backfills.phase6b_yahoo_cleanup

Three steps, each idempotent (a second run changes nothing):
  1. TechnicalEntrySignal.source "yahoo" -> "fmp". These are the latest-state rows (BB+RSI and
     Warren, one per ticker) written while Yahoo still served the 60m bars; new rows are always
     written "fmp". Only that table: other tables' "yahoo" labels (LiquidityZoneAnalysis) are
     overwritten by their nightly job on its next run.
  2. Delete the leftover DataSourceHealth rows for the removed sources ("massive", "yahoo"). Nothing
     reads them any more (Settings > Status shows FMP's data groups only).
  3. DROP TABLE yahoopricecache -- the model is gone, and no code reads or writes it.

Touches the real DB (core.db.engine) by design, like every pipeline script; tests exercise `run()`
against an in-memory engine.
"""

import argparse
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.db import engine as real_engine

logger = logging.getLogger(__name__)

REMOVED_SOURCES = ("massive", "yahoo")


def _table_exists(conn, name: str) -> bool:
    return conn.execute(text("select 1 from sqlite_master where type='table' and name=:n"), {"n": name}).first() is not None


def run(engine: Engine, dry_run: bool = False) -> dict[str, int]:
    """Returns the row counts each step changed (or would change, under dry_run)."""
    out = {"entry_signal_rows_rewritten": 0, "data_source_health_rows_deleted": 0, "yahoo_price_cache_rows_dropped": 0}
    with engine.begin() as conn:
        if _table_exists(conn, "technicalentrysignal"):
            out["entry_signal_rows_rewritten"] = conn.execute(
                text("select count(*) from technicalentrysignal where source = 'yahoo'")
            ).scalar_one()
            if not dry_run:
                conn.execute(text("update technicalentrysignal set source = 'fmp' where source = 'yahoo'"))
        if _table_exists(conn, "datasourcehealth"):
            placeholders = ", ".join(f":s{i}" for i in range(len(REMOVED_SOURCES)))
            params = {f"s{i}": s for i, s in enumerate(REMOVED_SOURCES)}
            out["data_source_health_rows_deleted"] = conn.execute(
                text(f"select count(*) from datasourcehealth where source in ({placeholders})"), params
            ).scalar_one()
            if not dry_run:
                conn.execute(text(f"delete from datasourcehealth where source in ({placeholders})"), params)
        if _table_exists(conn, "yahoopricecache"):
            out["yahoo_price_cache_rows_dropped"] = conn.execute(text("select count(*) from yahoopricecache")).scalar_one()
            if not dry_run:
                conn.execute(text("drop table yahoopricecache"))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="One-time cleanup after the removal of Yahoo Finance (Phase 6b).")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change; write nothing.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run(real_engine, dry_run=args.dry_run)
    logger.info("%s: %s", "Dry run (nothing written)" if args.dry_run else "Done", result)


if __name__ == "__main__":
    main()
