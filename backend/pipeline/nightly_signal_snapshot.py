"""Standalone script: the daily signal log (3:28 AM, after the 3:25 score recompute, before the 3:30 backup).

Appends one `TickerSignalSnapshot` row per tracked ticker (data/tracked_universe.py::load_tracked_universe) copied from its stored
`TickerScore` row: Overall verdict, Valuation verdict, Weinstein stage and whether it is Pass-family + Undervalued. Reads the database
only (zero FMP calls, ~1-2 s), is idempotent (a same-day re-run inserts nothing) and feeds no score. A ticker with no TickerScore row
yet has nothing to copy and is counted in the message.

    uv run python -m pipeline.nightly_signal_snapshot
"""

import logging
from datetime import date
from pathlib import Path

from sqlmodel import Session

from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from data.signal_snapshot_data import SnapshotResult, write_daily_snapshot

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_signal_snapshot.log"

logger = logging.getLogger(__name__)


def main(snapshot_date: date | None = None) -> SnapshotResult:
    configure_logging(LOG_PATH)
    init_db()
    with Session(engine) as session:
        result = write_daily_snapshot(session, snapshot_date or date.today())
    logger.info("Signal snapshot %s: %s", result.snapshot_date, result)
    return result


def record_outcome(result: SnapshotResult, run) -> None:
    """Heartbeat mapping. Skipped tickers (no stored score) are informational, never a failure; an empty log for a non-empty universe
    (nothing written and nothing already there) means TickerScore is empty or unreadable and is a failure."""
    message = f"{result.written} written, {result.already_present} already logged, {result.no_score} skipped (no stored score)"
    if result.universe > 0 and result.written + result.already_present == 0:
        raise RuntimeError(f"No snapshot row for any of {result.universe} tracked tickers: {message}")
    run.message = message


if __name__ == "__main__":
    with cron_heartbeat("pipeline.nightly_signal_snapshot") as run:
        record_outcome(main(), run)
