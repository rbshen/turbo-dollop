"""Standalone script: the opportunity outcome updater -- prices every listed row of the stored weekly opportunity runs against the cached
daily bars (5 / 10 / 20 / 60 sessions after entry, price-only, SPY and sector-ETF benchmarks, a 10% intraday stop recorded beside the
return) and upserts OpportunityOutcome rows. Engine: scoring/opportunity_outcomes.py; orchestration: data/opportunity_outcome_data.py;
spec: docs/specs/opportunities.md, "Outcome tracking".

SCHEDULED (2026-10-12): every night at 03:40 UTC (11:40 Hong Kong) in crontab.txt, after the nightly chain and the 03:30 backup, registered in
core/cron_health.py (daily cadence, overdue after 36 h) and wrapped in cron_heartbeat below. One OpportunityOutcomeRun row per real run
(status, message, the SPY bar date it saw) is also kept: it is what the next run reads to decide whether SPY has a new bar. A dry run writes
nothing at all, and is not a heartbeat either.

HEARTBEAT: a normal "no-op: SPY has no bar newer than ..." run (weekends, market holidays, a night the bars did not move) is a SUCCESS: the
job ran and had nothing to do. A failure is an exception (no SPY bars, a crash) or a run where the ticker-level failures pass
core.cron_health.check_failure_threshold (everything attempted failed, or >= the rate threshold with enough tickers attempted); a few
failed tickers stay green and are named in the message and in the run's `partial` status.

It ALSO prices the daily flags' outcomes (OpportunityFlagOutcome, Phase 2b v1; data/opportunity_flag_outcome_data.py) in the same invocation, with
the same engine and conventions: this updater is the only writer of OpportunityOutcome and OpportunityFlagOutcome, and the daily flag job
(pipeline/opportunity_daily_flags.py) writes flags only, so the two cannot double-count. A database with no flags behaves exactly as before.

Zero FMP calls (the bars cache is only read), no LLM. Idempotent: only pending rows are recomputed, final rows are frozen. A normal run
is a no-op unless SPY has a bar newer than the last run's (or a listed row has no outcome rows yet); --run-id / --as-of target one run
and skip that check. One ticker failing leaves its rows pending and does not stop the others.

Run (from backend/):
    uv run python -m pipeline.opportunity_outcome_update --once
    uv run python -m pipeline.opportunity_outcome_update --dry-run                 # compute and print, write nothing
    uv run python -m pipeline.opportunity_outcome_update --once --as-of 2026-10-09
    uv run python -m pipeline.opportunity_outcome_update --once --run-id 1
"""

import argparse
import logging
import time
from datetime import date
from pathlib import Path

from core.cron_health import check_failure_threshold, cron_heartbeat
from core.db import init_db
from core.logging_config import configure_logging
from data.opportunity_flag_outcome_data import update_outcomes_and_flags
from data.opportunity_outcome_data import UpdateResult, finish_log, start_log, summary_of

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "opportunity_outcome_update.log"

logger = logging.getLogger(__name__)


def main(run_id: int | None = None, as_of: date | None = None, dry_run: bool = False) -> UpdateResult:
    """Returns the UpdateResult so tests and manual runs can assert on it rather than scrape the log. A real run opens and closes one
    OpportunityOutcomeRun row ("running" -> success / noop / partial / failure); a failure re-raises after closing it."""
    configure_logging(LOG_PATH)
    init_db()
    started = time.monotonic()
    log_id = None if dry_run else start_log()
    try:
        result = update_outcomes_and_flags(run_id=run_id, as_of=as_of, dry_run=dry_run)
    except BaseException as exc:
        finish_log(log_id, "failure", f"{type(exc).__name__}: {exc}")
        raise
    # a partial run stores no SPY date, so the next normal run goes ahead and retries the tickers that failed
    finish_log(log_id, result.status, result.message(), None if result.status == "partial" else result.spy_last_bar_date, summary_of(result))
    logger.info("Opportunity outcome update (%.1fs): %s", time.monotonic() - started, result.message())
    for ticker, why in sorted(result.failed.items()):
        logger.warning("Outcome update: %s left as it was: %s", ticker, why)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Opportunity outcome updater: forward returns of the listed names (manual run).")
    parser.add_argument("--once", action="store_true", help="Run once (the normal run): a no-op unless SPY has a new bar.")
    parser.add_argument("--dry-run", action="store_true", help="Compute and report what would change; write nothing.")
    parser.add_argument("--run-id", type=int, default=None, help="Only this OpportunityRun id (skips the new-SPY-bar check).")
    parser.add_argument("--as-of", type=str, default=None, help="Only the run with this as-of date, YYYY-MM-DD (skips the new-SPY-bar check).")
    args = parser.parse_args()
    if not (args.once or args.dry_run or args.run_id is not None or args.as_of):
        parser.error("say what to do: --once, --dry-run, --run-id or --as-of")
    return args


def run_scheduled(cli: argparse.Namespace) -> UpdateResult:
    """The command-line run. A real run is a cron heartbeat (success for a result or a no-op, failure for an exception or past the
    failure threshold); a dry run writes nothing, not even a heartbeat row."""
    as_of = date.fromisoformat(cli.as_of) if cli.as_of else None
    if cli.dry_run:
        return main(cli.run_id, as_of, dry_run=True)
    with cron_heartbeat("pipeline.opportunity_outcome_update") as run:
        outcome = main(cli.run_id, as_of)
        run.message = outcome.message()
        check_failure_threshold(outcome.attempted, len(outcome.failed), outcome.message())
    return outcome


if __name__ == "__main__":
    print(run_scheduled(_parse_args()).message())
