"""Standalone script: monthly Momentum snapshot -- a 3-way composite
price-momentum signal (3mo/6mo/12mo trailing return average) over Fathom's
Moat-rated universe. See data/momentum_data.py for the compute/persist
logic and scoring/momentum.py for the pure ranking engine. Makes ZERO FMP
calls (Yahoo Finance only, via clients/yahoo_client.py), same framing as
nightly_trend_calculation.py -- no FMP_ENABLED guard needed.

Scheduled to *try* daily across the first several days of the month
(crontab.txt: `0 3 1-5 * *`) rather than on the literal 1st, because the
lookback windows must anchor to a month's FINAL close -- running at 3am on
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
"""

import argparse
import asyncio
import logging
from datetime import date
from pathlib import Path

from core.cron_health import cron_heartbeat
from core.db import init_db
from core.logging_config import configure_logging
from data.momentum_data import compute_and_store_momentum_snapshot
from helpers.trading_calendar import resolve_month_end_anchor

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "monthly_momentum_snapshot.log"

logger = logging.getLogger(__name__)


async def main(force_anchor: date | None = None) -> dict:
    """`force_anchor=None` means "use today's real gate/anchor resolution"
    -- passing an explicit date (the CLI's --force-anchor, and tests)
    bypasses resolve_month_end_anchor entirely. Returns the run summary
    dict so tests/manual runs can assert on it directly rather than
    scraping the log."""
    configure_logging(LOG_PATH)
    init_db()

    anchor_date = force_anchor if force_anchor is not None else resolve_month_end_anchor(date.today())

    if anchor_date is None:
        logger.info("Momentum snapshot skipped: today is not the first NYSE trading day of the month.")
        return {"processed": 0, "skipped": True, "reason": "not the first trading day of the month"}

    logger.info("Starting Momentum snapshot for anchor date %s.", anchor_date)
    summary = await compute_and_store_momentum_snapshot(anchor_date)
    logger.info(
        "Momentum snapshot complete for %s: %d/%d tickers scored, %d dropped for insufficient price history.",
        anchor_date,
        summary["processed"],
        summary["universe_size"],
        summary["dropped"],
    )
    return {**summary, "skipped": False}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monthly Momentum snapshot (3mo/6mo/12mo composite return ranking).")
    parser.add_argument(
        "--force-anchor",
        type=str,
        default=None,
        help="Bypass the first-trading-day-of-month gate and compute against this anchor date (YYYY-MM-DD).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    forced = date.fromisoformat(cli_args.force_anchor) if cli_args.force_anchor else None
    with cron_heartbeat("pipeline.monthly_momentum_snapshot"):
        asyncio.run(main(forced))
