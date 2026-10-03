"""Standalone script: refresh the ETFs screener's read-model (models.py::EtfScreenerRow) for every ETF in the ETF
universe (data/tracked_universe.py::load_etf_universe). See data/etf_screener_refresh.py for what is computed from
where, the partial-write rule and the retention rule, and docs/specs/etf-screener.md.

**Registered 2026-10-03 (step 6)**: daily at 1:45 AM in crontab.txt, and in core/cron_health.py::CRON_JOB_NAMES /
_EXPECTED_CADENCE_HOURS / JOB_METADATA. The `cron_heartbeat` below is used for a real run only; a `--cache-only` or
`--dry-run` run is a manual inspection and writes no CronRunLog row.

Skipped (a real `skipped` cron status) while the `daily_prices` data group is off, like the other bar-reading jobs;
a live run also needs `etf_info` and `profile_quote` for the fund facts (when off, cached rows are served).

Run by hand:
    uv run python -m pipeline.nightly_etf_screener                       # live: fetches what is stale, writes (EtfScreenerRow, TrendAnalysis, TickerLastClose), prunes
    uv run python -m pipeline.nightly_etf_screener --tickers SPY,QQQ     # a subset (never prunes)
    uv run python -m pipeline.nightly_etf_screener --cache-only          # no network; still writes EtfScreenerRow rows only
    uv run python -m pipeline.nightly_etf_screener --cache-only --dry-run  # no network, no writes: prints the rows
"""

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from clients.daily_bar_sources import describe_unserved
from core.cron_health import check_failure_threshold, cron_heartbeat
from core.data_groups import job_skip_reason
from core.db import init_db
from core.logging_config import configure_logging
from core.tickers import normalize_ticker
from data.etf_screener_refresh import refresh_etf_screener
from pipeline.nightly_trend_calculation import WEEKLY_RESYNC_WEEKDAY_UTC

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_etf_screener.log"

logger = logging.getLogger(__name__)


async def main(
    tickers: list[str] | None = None, *, cache_only: bool = False, dry_run: bool = False, force_resync: bool | None = None
) -> dict:
    """Returns the run summary dict (see refresh_etf_screener). A dry run skips init_db() and the log file so that,
    with cache_only, it can run read-only against the real database. `force_resync=None` means "the weekly full
    resync day" (the stock-side bar job's weekday, Sunday UTC), as that job does for its own tickers."""
    if not dry_run:
        configure_logging(LOG_PATH)
        init_db()

    if not cache_only:
        skip_reason = job_skip_reason("daily_prices")
        if skip_reason:
            logger.info("ETF screener refresh %s.", skip_reason)
            return {"skipped": True, "skip_reason": skip_reason}

    if force_resync is None:
        force_resync = datetime.now(timezone.utc).weekday() == WEEKLY_RESYNC_WEEKDAY_UTC
    return await refresh_etf_screener(tickers, cache_only=cache_only, dry_run=dry_run, force_resync=force_resync)


def failure_summary(summary: dict) -> str:
    return (
        f"{summary['processed']} ETFs, {summary['written']} written, {summary['trend_written']} trend rows, "
        f"{summary['last_close_written']} last closes, {summary['failed']} failed, "
        f"{summary['pruned']} pruned, {summary['stale_count']} still stale after fetch, "
        f"{describe_unserved(summary['unserved_count'])}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh the ETFs screener read-model, and (live runs only) the ETFs' TrendAnalysis and TickerLastClose rows."
    )
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated explicit ticker list (never prunes).")
    parser.add_argument("--cache-only", action="store_true", help="Compute from cached data only; no network call. Writes EtfScreenerRow only (no TrendAnalysis, no TickerLastClose).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print; write no EtfScreenerRow, TrendAnalysis or TickerLastClose and prune nothing. Pair with --cache-only for a run that fetches nothing either.",
    )
    return parser.parse_args()


def _print_results(summary: dict) -> None:
    for ticker, result in summary["results"].items():
        print(f"{ticker}: {len(result.fields)} field(s)")
        for key, value in result.fields.items():
            print(f"    {key} = {value}")
        for note in result.notes:
            print(f"    - {note}")
        for error in result.errors:
            print(f"    ! {error}")
    print(f"would prune {summary['would_prune']} row(s); failed {summary['failed']}")


if __name__ == "__main__":
    args = _parse_args()
    tickers = [normalize_ticker(t) for t in args.tickers.split(",") if t.strip()] if args.tickers else None
    if args.dry_run or args.cache_only:
        result = asyncio.run(main(tickers, cache_only=args.cache_only, dry_run=args.dry_run))
        if args.dry_run:
            _print_results(result)
    else:
        with cron_heartbeat("pipeline.nightly_etf_screener") as run:
            result = asyncio.run(main(tickers))
            if result.get("skipped"):
                run.skip(result["skip_reason"])
            else:
                message = failure_summary(result)
                check_failure_threshold(result["processed"], result["failed"], message)
                run.message = message
