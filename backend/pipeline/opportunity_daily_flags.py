"""Standalone script: the daily flag job of the opportunity agent (Phase 2b v1). For the names of the LATEST weekly opportunity list it
looks, on the newest completed session, for three triggers and stores each hit as an OpportunityDailyFlag:

  D1.entry_event.v1     a stored Warren (blue_up / yellow_up) or BB+RSI event dated after the list's as-of date (covered names only)
  D2.stage_upgrade.v1   the Weinstein stage moved up against the stage frozen on the list row (Reversal names)
  D3.pullback_to_ma.v1  a Momentum name within 5% of its stage MA, still an Advance, MA slope and RS positive

Triggers: scoring/opportunity_triggers.py; orchestration and the cohort rule: data/opportunity_daily_data.py; spec: docs/specs/opportunities.md,
"Daily flags (Phase 2b v1)". Zero FMP calls (the bars cache and the stored tables are only read), no LLM.

SCHEDULED 2026-10-12 at 03:45 UTC (`45 3 * * *` in crontab.txt): after the 03:40 outcome updater, 15 minutes before the Saturday 04:00 weekly
job. Registered in core/cron_health.py (CRON_JOB_NAMES, a 36 h cadence, JOB_METADATA).

HEARTBEAT: a normal "no-op: SPY has no bar newer than ..." run (a weekend, a market holiday, a night the bars did not move) is a SUCCESS. The
no-op test uses this job's OWN last-seen SPY bar date (the newest OpportunityDailyRun with one), not the outcome updater's. A failure is an
exception (no SPY bars, a crash) or ticker-level read failures that pass core.cron_health.check_failure_threshold. A trigger that could not
be judged (an upstream job of the night did not succeed, no final bar, a stale stage row) is recorded as INCOMPLETE in the run row and is not
a failure of this job. A dry run writes nothing, not even a heartbeat.

Run (from backend/):
    uv run python -m pipeline.opportunity_daily_flags --once
    uv run python -m pipeline.opportunity_daily_flags --dry-run                  # compute and print, write nothing
    uv run python -m pipeline.opportunity_daily_flags --once --as-of 2026-10-12  # one session, skips the new-SPY-bar check
"""

import argparse
import logging
import time
from datetime import date
from pathlib import Path

from core.cron_health import check_failure_threshold, cron_heartbeat
from core.db import init_db
from core.logging_config import configure_logging
from data.opportunity_daily_data import DailyResult, finish_log, run_daily, start_log

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "opportunity_daily_flags.log"

logger = logging.getLogger(__name__)


def main(as_of: date | None = None, dry_run: bool = False) -> DailyResult:
    """Returns the DailyResult so tests and manual runs can assert on it rather than scrape the log. A real run opens and closes one
    OpportunityDailyRun row ("running" -> success / noop / failure); a failure re-raises after closing it."""
    configure_logging(LOG_PATH)
    init_db()
    started = time.monotonic()
    log_id = None if dry_run else start_log()
    try:
        result = run_daily(as_of=as_of, dry_run=dry_run)
    except BaseException as exc:
        finish_log(log_id, "failure", f"{type(exc).__name__}: {exc}")
        raise
    finish_log(log_id, result.status, result.message(), result)
    logger.info("Opportunity daily flags (%.1fs): %s", time.monotonic() - started, result.detail())  # the full detail; the stored message is the quiet one
    for ticker, why in sorted(result.failed.items()):
        logger.warning("Daily flags: %s left incomplete: %s", ticker, why)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Opportunity daily flags: triggers on the latest weekly list (manual run).")
    parser.add_argument("--once", action="store_true", help="Run once (the normal run): a no-op unless SPY has a bar newer than this job's last.")
    parser.add_argument("--dry-run", action="store_true", help="Compute and report what would be flagged; write nothing.")
    parser.add_argument("--as-of", type=str, default=None, help="Only this session, YYYY-MM-DD (skips the new-SPY-bar check).")
    args = parser.parse_args()
    if not (args.once or args.dry_run or args.as_of):
        parser.error("say what to do: --once, --dry-run or --as-of")
    return args


def run_scheduled(cli: argparse.Namespace) -> DailyResult:
    """The command-line run. A real run is a cron heartbeat (success for a result or a no-op, failure for an exception or past the failure
    threshold); a dry run writes nothing, not even a heartbeat row."""
    as_of = date.fromisoformat(cli.as_of) if cli.as_of else None
    if cli.dry_run:
        return main(as_of, dry_run=True)
    with cron_heartbeat("pipeline.opportunity_daily_flags") as run:
        outcome = main(as_of)
        run.message = outcome.message()
        check_failure_threshold(outcome.attempted, len(outcome.failed), outcome.message())
    return outcome


if __name__ == "__main__":
    print(run_scheduled(_parse_args()).message())
