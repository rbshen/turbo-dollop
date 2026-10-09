"""Standalone script: nightly sector / industry average-P/E snapshot from FMP (data group `sector_industry_pe`).

2 snapshots (sector, industry) x 3 exchanges (NASDAQ, NYSE, AMEX) = 6 FMP calls for the last completed trading day,
upserted into `SectorIndustryPe` (data/sector_industry_pe_data.py, docs/specs/sector-industry-pe.md). Upsert-only: a
re-run, a weekend or a holiday re-writes the same day's rows. Skipped (a real `skipped` cron status) while the group
or the FMP master switch is off. One failed call does not stop the others; the run is marked failed only when every
call failed (check_failure_threshold) or when it wrote no row at all.

Default schedule: 3:05 AM server time, after the 2:00 fundamentals fetch (worst seen 64.5 min, ends ~3:04) and before
the 3:10 price-target snapshot. Nothing reads these rows yet, so no other job depends on this one.

Run manually:
    uv run python -m pipeline.nightly_sector_industry_pe
"""

import asyncio
import logging
import time
from pathlib import Path

from core.cron_health import check_failure_threshold, cron_heartbeat
from core.data_groups import job_skip_reason
from core.db import init_db
from core.logging_config import configure_logging
from data.sector_industry_pe_data import refresh_snapshots

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_sector_industry_pe.log"

logger = logging.getLogger(__name__)


async def main() -> dict:
    """Returns the run summary dict so tests/manual runs can assert on it directly."""
    configure_logging(LOG_PATH)
    init_db()

    skip_reason = job_skip_reason("sector_industry_pe")
    if skip_reason:
        logger.info("Nightly sector/industry P/E %s.", skip_reason)
        return {"skipped": True, "skip_reason": skip_reason}

    start = time.monotonic()
    result = await refresh_snapshots()
    summary = {
        "as_of_date": result.as_of.isoformat(),
        "attempted": result.attempted,
        "failed": result.failed,
        "no_data": result.no_data,
        "written": result.written,
        "failures": result.failures,
        "duration_seconds": time.monotonic() - start,
    }
    logger.info(
        "Nightly sector/industry P/E complete. As of: %s. Calls: %d. Failed: %d. No data: %d. Rows written: %d. Duration: %.1fs.",
        summary["as_of_date"], summary["attempted"], summary["failed"], summary["no_data"], summary["written"],
        summary["duration_seconds"],
    )
    return summary


def record_outcome(summary: dict, run) -> None:
    """A gated run is "skipped"; a run where every call failed or no row was written raises (heartbeat "failure");
    anything else is a "success" with the counts."""
    if summary.get("skipped"):
        run.skip(summary["skip_reason"])
        return
    message = (
        f"{summary['written']} rows for {summary['as_of_date']}, {summary['failed']} of {summary['attempted']} calls failed, "
        f"{summary['no_data']} with no data"
    )
    check_failure_threshold(summary["attempted"], summary["failed"], message)
    if summary["written"] == 0:
        raise RuntimeError(f"sector/industry P/E snapshot wrote no rows ({message})")
    run.message = message


if __name__ == "__main__":
    with cron_heartbeat("pipeline.nightly_sector_industry_pe") as run:
        record_outcome(asyncio.run(main()), run)
