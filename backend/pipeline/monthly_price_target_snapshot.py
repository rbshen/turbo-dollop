"""Standalone script: monthly price-target-consensus snapshot for every
ticker in the stored S&P 500 + Dow constituent lists (see
nightly_fundamentals_fetch.py's load_universe_tickers, reused here).

FMP has no historical price-target-consensus series of its own -- unlike
grades-historical, which already ships a ready-made monthly series -- so
this script exists purely to start accumulating one, one PriceTargetSnapshot
row per ticker per run. It deliberately does NOT go through
cache.get_or_fetch: that cache overwrites the latest value in place, but
this table's whole purpose is to preserve every past snapshot (see
PriceTargetSnapshot's docstring in models.py). The Analyst Ratings tab's
price-target history line and its Recommendation Details table's "N ago"
Target column both start empty and fill in as this script accumulates
monthly runs.

Default schedule: 3am server time, first of the month (see crontab.txt in
this directory).

Run manually against the full stored list:
    uv run python -m pipeline.monthly_price_target_snapshot

Run against a small subset first (recommended before ever doing a first
full run):
    uv run python -m pipeline.monthly_price_target_snapshot --limit 15
    uv run python -m pipeline.monthly_price_target_snapshot --tickers AAPL,MSFT,ZZZZINVALID
"""

import argparse
import asyncio
import logging
import time
from datetime import date, datetime
from pathlib import Path

from sqlmodel import Session

from db import engine, init_db
from helpers.first import _first
from clients.fmp_client import fmp_client
from logging_config import configure_logging
from models import PriceTargetSnapshot
from pipeline.nightly_fundamentals_fetch import load_universe_tickers

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "monthly_price_target_snapshot.log"

# Same empirically-derived pacing as nightly_fundamentals_fetch.py -- see
# that module's comment for the underlying rate-limit investigation.
TARGET_REQUESTS_PER_MINUTE = 220


async def _snapshot_one_ticker(session: Session, ticker: str, snapshot_date: date) -> None:
    raw = _first(await fmp_client.get_price_target_consensus(ticker))
    session.add(
        PriceTargetSnapshot(
            ticker=ticker,
            snapshot_date=snapshot_date,
            target_consensus=raw.get("targetConsensus"),
            target_high=raw.get("targetHigh"),
            target_low=raw.get("targetLow"),
            target_median=raw.get("targetMedian"),
            fetched_at=datetime.now(),
        )
    )
    session.commit()


async def main(tickers: list[str] | None = None) -> dict:
    """`tickers=None` means "use the full stored S&P 500 + Dow list" --
    passing an explicit list (used by the CLI's --limit/--tickers and by
    tests) bypasses the DB lookup entirely. Returns the run summary dict so
    tests can assert on it directly rather than scraping the log."""
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    if tickers is None:
        with Session(engine) as session:
            tickers = load_universe_tickers(session)

    if not tickers:
        logger.error("No tickers to process -- run refresh_sp500_list.py/refresh_dow_list.py first, or pass an explicit ticker list.")
        return {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": []}

    fmp_client.min_request_interval = 60.0 / TARGET_REQUESTS_PER_MINUTE
    logger.info(
        "Starting monthly price-target snapshot for %d tickers (pacing %.3fs/request, target %d req/min).",
        len(tickers),
        fmp_client.min_request_interval,
        TARGET_REQUESTS_PER_MINUTE,
    )

    snapshot_date = date.today()
    start_time = time.monotonic()
    start_request_count = fmp_client.request_count
    failures: list[tuple[str, str]] = []

    with Session(engine) as session:
        for i, ticker in enumerate(tickers, start=1):
            try:
                await _snapshot_one_ticker(session, ticker, snapshot_date)
                logger.info("[%d/%d] %s: ok", i, len(tickers), ticker)
            except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
                logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
                failures.append((ticker, str(exc)))

    duration = time.monotonic() - start_time
    calls_made = fmp_client.request_count - start_request_count

    logger.info(
        "Monthly snapshot complete. Processed: %d. Failed: %d. FMP calls made: %d. Duration: %.1fs (%.1f min).",
        len(tickers),
        len(failures),
        calls_made,
        duration,
        duration / 60,
    )
    if failures:
        logger.info("Tickers with failures: %s", ", ".join(f"{t} ({e})" for t, e in failures))

    return {
        "processed": len(tickers),
        "failed": len(failures),
        "calls_made": calls_made,
        "duration_seconds": duration,
        "failures": failures,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monthly price-target-consensus snapshot.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N stored tickers (for testing).")
    parser.add_argument(
        "--tickers", type=str, default=None, help="Comma-separated explicit ticker list, overrides the stored list (for testing)."
    )
    return parser.parse_args()


def _resolve_cli_tickers(args: argparse.Namespace) -> list[str] | None:
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.limit:
        init_db()
        with Session(engine) as session:
            all_tickers = load_universe_tickers(session)
        return all_tickers[: args.limit]
    return None


if __name__ == "__main__":
    cli_args = _parse_args()
    asyncio.run(main(_resolve_cli_tickers(cli_args)))
