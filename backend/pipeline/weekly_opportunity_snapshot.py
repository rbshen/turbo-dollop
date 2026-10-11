"""Standalone script: the weekly opportunity agent -- builds two frozen lists (Momentum, Reversal) across the whole tracked
universe from STORED data only and saves a dated snapshot (OpportunityRun + OpportunitySnapshotRow). Rules and tiers:
scoring/opportunity_rules.py; orchestration: data/opportunity_data.py; spec: docs/specs/opportunities.md.

Makes ZERO FMP calls and no LLM call: it reads the shared bars cache (in chunks of 60 tickers, so memory stays flat), TickerScore,
TrendAnalysis, the Warren / BB+RSI event tables and MarketBreadthSnapshot. It writes only the two new tables, insert-only.
Existing nightly jobs, the stage engine and the scoring are not touched.

Runs once for one as-of date (default: the last completed XNYS session). A rerun for the same as-of date is a no-op; `--force`
replaces that run's rows in one transaction. It refuses (raises, writes nothing) when fewer than 90% of the gate-passing tickers
have a Weinstein row computed from the as-of bar, i.e. when the nightly stage job has not caught up.

NOT SCHEDULED. It is registered in core/cron_health.py (CRON_JOB_NAMES, DISABLED_CRON_JOBS) and has a commented-out line in
crontab.txt, but nothing runs it until the owner enables the cron (steps in docs/specs/opportunities.md, "Enabling the weekly cron").

Run:
    uv run python -m pipeline.weekly_opportunity_snapshot
    uv run python -m pipeline.weekly_opportunity_snapshot --as-of 2026-10-09
    uv run python -m pipeline.weekly_opportunity_snapshot --as-of 2026-10-09 --force
    uv run python -m pipeline.weekly_opportunity_snapshot --dry-run     # compute and print the counts, write nothing
"""

import argparse
import logging
import time
from datetime import date
from pathlib import Path

from core.cron_health import cron_heartbeat
from core.db import init_db
from core.logging_config import configure_logging
from data.opportunity_data import compute_run, existing_run_id, latest_completed_session, persist_run

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "weekly_opportunity_snapshot.log"

logger = logging.getLogger(__name__)


def main(as_of: date | None = None, force: bool = False, dry_run: bool = False) -> dict:
    """Returns the run summary dict so tests/manual runs can assert on it directly rather than scraping the log.
    `as_of=None` means the last completed XNYS session. `dry_run` computes and returns the counts without writing."""
    configure_logging(LOG_PATH)
    init_db()

    as_of = as_of or latest_completed_session()
    if not force and not dry_run:
        existing = existing_run_id(as_of)
        if existing is not None:
            logger.info("Opportunity run for %s already exists (id %s): nothing to do (use --force to replace it).", as_of, existing)
            return {"status": "exists", "run_id": existing, "as_of_date": as_of.isoformat(), "skipped": True}

    logger.info("Starting weekly opportunity run for as-of %s.", as_of)
    started = time.monotonic()
    computed = compute_run(as_of)
    elapsed = time.monotonic() - started
    totals = computed.summary["list_totals"]
    logger.info(
        "Opportunity run computed in %.1fs: universe %d, gate passed %d, Momentum %d, Reversal %d, gate drops %s.",
        elapsed, computed.universe_size, computed.summary["gate_passed"], totals["momentum"], totals["reversal"], computed.gate_drops,
    )
    if dry_run:
        return {"status": "dry_run", "as_of_date": as_of.isoformat(), "summary": computed.summary, "duration_seconds": elapsed}
    result = persist_run(computed, force=force)
    logger.info("Opportunity run %s: %s", result["status"], result)
    return {**result, "summary": computed.summary, "duration_seconds": elapsed, "skipped": False}


def run_message(result: dict) -> str:
    """The heartbeat's one-line message for a finished run."""
    if result.get("skipped"):
        return f"run for {result['as_of_date']} already exists (no-op)"
    totals = result["summary"]["list_totals"]
    return f"{result['status']} {result['as_of_date']}: Momentum {totals['momentum']}, Reversal {totals['reversal']}, {result['summary']['gate_passed']} through the gate"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Weekly opportunity agent: Momentum and Reversal lists from stored data.")
    parser.add_argument("--as-of", type=str, default=None, help="As-of date (YYYY-MM-DD); default: the last completed XNYS session.")
    parser.add_argument("--force", action="store_true", help="Replace the existing run for this as-of date (one transaction).")
    parser.add_argument("--dry-run", action="store_true", help="Compute and report the counts; write nothing.")
    args = parser.parse_args()
    if args.force and args.dry_run:
        parser.error("--force and --dry-run cannot be combined")
    return args


if __name__ == "__main__":
    cli_args = _parse_args()
    with cron_heartbeat("pipeline.weekly_opportunity_snapshot") as run:
        outcome = main(date.fromisoformat(cli_args.as_of) if cli_args.as_of else None, force=cli_args.force, dry_run=cli_args.dry_run)
        run.message = run_message(outcome) if outcome.get("status") != "dry_run" else "dry run (nothing written)"
