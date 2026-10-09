"""Standalone script: monthly Momentum snapshot -- a 3-way composite
price-momentum signal (3mo/6mo/12mo trailing return average) over Fathom's
Moat-rated universe, followed by an ETF pass over the ETF universe
(`load_etf_universe`; same engine, stored in EtfMomentumSnapshot -- see
docs/specs/momentum.md). See data/momentum_data.py for the compute/persist
logic and scoring/momentum.py for the pure ranking engine. Each row also stores informational-only
1w/1mo returns (never part of the composite or rank). Makes ZERO FMP
fundamentals calls (a shared-bars-cache batch fetch of FMP daily bars); skipped -- a real
`skipped` cron status -- while the `daily_prices` group is off, same as
nightly_trend_calculation.py.

Scheduled to *try* daily across the first several days of the month
(crontab.txt: `50 2 1-5 * *`) rather than on the literal 1st, because the
lookback windows must anchor to a month's FINAL close -- running at 2:50am on
the calendar 1st would be before that day's own trading session even
starts, and a holiday can push the real first trading day of the month
past the 1st anyway (see helpers/trading_calendar.py::
resolve_month_end_anchor, which decides both "is today actually the day to
run" and "which month-end close to anchor to"). Every day this script runs
that ISN'T the real first trading day of the month is a deliberate no-op --
same `{"skipped": True}` summary-dict convention monthly_price_target_
snapshot.py already uses for its own FMP-paused no-op, so cron_heartbeat
still records a legitimate "success" for a correctly-gated skip.

Run manually (auto-detects whether today is the anchor day):
    uv run python -m pipeline.monthly_momentum_snapshot

Force a specific anchor date, bypassing the gate (for manual backfill/testing):
    uv run python -m pipeline.monthly_momentum_snapshot --force-anchor 2026-08-31

ETF backfill from the bars already cached (no FMP call, no stock pass, no group gate -- it only reads the DB):
    uv run python -m pipeline.monthly_momentum_snapshot --force-anchor 2026-08-31 --etf-only --cached-bars-only
"""

import argparse
import asyncio
import logging
from datetime import date
from pathlib import Path

from clients.daily_bar_sources import describe_unserved
from core.cron_health import cron_heartbeat
from core.data_groups import job_skip_reason
from core.db import init_db
from core.logging_config import configure_logging
from data.momentum_data import compute_and_store_etf_momentum_snapshot, compute_and_store_momentum_snapshot
from helpers.trading_calendar import resolve_month_end_anchor

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "monthly_momentum_snapshot.log"

logger = logging.getLogger(__name__)


async def main(force_anchor: date | None = None, etf_only: bool = False, cached_bars_only: bool = False) -> dict:
    """`force_anchor=None` means "use today's real gate/anchor resolution"
    -- passing an explicit date (the CLI's --force-anchor, and tests)
    bypasses resolve_month_end_anchor entirely. `etf_only` skips the stock pass; `cached_bars_only` (ETF pass
    only, so it requires `etf_only`) reads the shared bars cache without any FMP call, and therefore also
    bypasses the daily_prices group gate, which exists to stop fetches. Returns the run summary
    dict so tests/manual runs can assert on it directly rather than
    scraping the log. The stock pass is under key names unchanged from before the ETF pass existed; the ETF
    pass is under `etf`. Neither pass can hide the other's failure: both run, then the first error is re-raised
    (so cron_heartbeat records a failure), the other logged."""
    if cached_bars_only and not etf_only:
        raise ValueError("cached_bars_only applies to the ETF pass only; pass etf_only=True with it")

    configure_logging(LOG_PATH)
    init_db()

    anchor_date = force_anchor if force_anchor is not None else resolve_month_end_anchor(date.today())

    if anchor_date is None:
        logger.info("Momentum snapshot skipped: today is not the first NYSE trading day of the month.")
        return {"processed": 0, "skipped": True, "reason": "not the first trading day of the month"}

    skip_reason = None if cached_bars_only else job_skip_reason("daily_prices")
    if skip_reason:
        # Data group off (no fallback provider since Phase 6b): computing on stale cached bars
        # would only look healthy. __main__ records CronRunLog status "skipped".
        logger.info("Momentum snapshot %s.", skip_reason)
        return {"processed": 0, "skipped": True, "reason": skip_reason, "group_skipped": True}

    errors: list[BaseException] = []
    stock_summary: dict = {}
    if not etf_only:
        logger.info("Starting Momentum snapshot for anchor date %s.", anchor_date)
        try:
            stock_summary = await compute_and_store_momentum_snapshot(anchor_date)
        except Exception as exc:
            logger.exception("Momentum snapshot (stock pass) failed for anchor %s.", anchor_date)
            errors.append(exc)
        else:
            logger.info(
                "Momentum snapshot complete for %s: %d/%d tickers scored, %d dropped for insufficient price history.",
                anchor_date,
                stock_summary["processed"],
                stock_summary["universe_size"],
                stock_summary["dropped"],
            )

    logger.info("Starting ETF Momentum snapshot for anchor date %s.", anchor_date)
    etf_summary: dict = {}
    try:
        etf_summary = await compute_and_store_etf_momentum_snapshot(anchor_date, cached_only=cached_bars_only)
    except Exception as exc:
        logger.exception("ETF Momentum snapshot (ETF pass) failed for anchor %s.", anchor_date)
        errors.append(exc)

    if errors:
        for extra in errors[1:]:
            logger.error("Additional momentum pass failure (first one is re-raised): %r", extra)
        raise errors[0]

    return {**stock_summary, "etf": etf_summary, "etf_only": etf_only, "skipped": False}


def build_run_message(summary: dict) -> str:
    """The CronRunLog message for a completed run: the stock counts (unchanged wording) when the stock pass ran,
    then the ETF counts."""
    etf = summary["etf"]
    etf_part = f"ETFs {etf['processed']}/{etf['universe_size']}"
    if summary.get("etf_only"):
        return f"{etf_part}, {etf['stale_count']} still stale after fetch, {describe_unserved(etf['unserved_count'])}"
    return (
        f"stocks {summary['processed']}/{summary['universe_size']}, {etf_part}, "
        f"{summary['stale_count'] + etf['stale_count']} still stale after fetch, "
        f"{describe_unserved(summary['unserved_count'] + etf['unserved_count'])}, "
        f"{summary['skipped_delisted_count']} skipped as delisted"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monthly Momentum snapshot (3mo/6mo/12mo composite return ranking).")
    parser.add_argument(
        "--force-anchor",
        type=str,
        default=None,
        help="Bypass the first-trading-day-of-month gate and compute against this anchor date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--etf-only",
        action="store_true",
        help="Run only the ETF pass (skip the stock pass). For backfills; combine with --force-anchor.",
    )
    parser.add_argument(
        "--cached-bars-only",
        action="store_true",
        help="ETF pass reads the bars already cached: no FMP call, no cache write. Requires --etf-only.",
    )
    args = parser.parse_args()
    if args.cached_bars_only and not args.etf_only:
        parser.error("--cached-bars-only requires --etf-only")
    return args


if __name__ == "__main__":
    cli_args = _parse_args()
    forced = date.fromisoformat(cli_args.force_anchor) if cli_args.force_anchor else None
    with cron_heartbeat("pipeline.monthly_momentum_snapshot") as run:
        summary = asyncio.run(main(forced, etf_only=cli_args.etf_only, cached_bars_only=cli_args.cached_bars_only))
        if summary.get("group_skipped"):
            run.skip(summary["reason"])
        elif summary.get("skipped"):
            run.message = summary.get("reason", "skipped")
        else:
            run.message = build_run_message(summary)
