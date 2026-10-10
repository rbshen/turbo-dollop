"""Standalone script: the nightly cache-only data-quality sweep (3:26 AM, after the 3:25 score recompute, before the 3:28 signal snapshot).

Runs the three checks of scoring/data_quality.py over every tracked ticker's cached statements and makes the `DataQualityFlag` table equal
what holds now: new flags are added, flags that still hold keep their found/reviewed state, flags whose condition is gone are deleted.
Reads the database only (zero FMP calls, zero SEC calls), is idempotent and feeds no score. docs/specs/data-quality.md.

    uv run python -m pipeline.nightly_data_quality
"""

import logging
from pathlib import Path

from sqlmodel import Session

from core.cron_health import check_failure_threshold, cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from data.data_quality_data import SyncResult, sync_flags

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_data_quality.log"

logger = logging.getLogger(__name__)


def main() -> SyncResult:
    configure_logging(LOG_PATH)
    init_db()
    with Session(engine) as session:
        result = sync_flags(session)
    logger.info("Data quality sweep: %s", result)
    return result


def record_outcome(result: SyncResult, run) -> None:
    """Heartbeat mapping. A ticker with nothing cached is informational; a ticker whose check raised counts toward the shared failure
    threshold (the red `failure` state), over the tickers that had data to judge."""
    message = (
        f"{result.open_flags} open flags ({result.added} new, {result.cleared} cleared) over {result.scanned} tickers"
        + (f", {result.no_data} without cached statements" if result.no_data else "")
        + (f", {result.errors} failed" if result.errors else "")
    )
    check_failure_threshold(result.scanned + result.errors, result.errors, message)
    run.message = message


if __name__ == "__main__":
    with cron_heartbeat("pipeline.nightly_data_quality") as run:
        record_outcome(main(), run)
