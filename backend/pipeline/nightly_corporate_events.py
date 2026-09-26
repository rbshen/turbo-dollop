"""Standalone script: nightly refresh of the FMP-backed earnings / dividends / splits
cache (CorporateEvent, Phase 6a) for every US-listed tracked ticker -- the same
universe as the price-target and last-close jobs (`load_us_price_target_universe`).
Feeds the Chart tab's E/D markers (data/chart_events_data.py reads the cache first).

Each run UPSERTS a ticker's rows from FMP's answer (`/earnings`, `/dividends` nightly;
`/splits` weekly -- see data/corporate_events_data.py::splits_due; group
`corporate_events`), so the first run after deploy IS the backfill and a later run picks
up newly announced report dates, newly declared dividends and newly filled-in EPS
actuals. Nothing is deleted because FMP's response omitted it (plan-downgrade safe); the
one deletion is the 4-year trailing prune (`prune_old_events`) that closes each run.
~590 tickers x 2 calls = ~1,180 calls on an ordinary night (was ~1,770), ~1,770 on the
week's splits night, paced to half the plan's documented rate (~1-2 min). A failed
endpoint keeps that ticker's previous rows for that type.

Default schedule: 3:12 AM server time (UTC). Skipped (a real `skipped` cron status)
while the `corporate_events` group is not live -- the cache then serves as-is.

Run manually (this is also the one-time backfill):
    uv run python -m pipeline.nightly_corporate_events
    uv run python -m pipeline.nightly_corporate_events --tickers AAPL,TSLA
"""

import argparse
import asyncio
import logging
import time
from pathlib import Path

from sqlmodel import Session

from clients.daily_bar_sources import FMP_CONCURRENCY, FMP_PLAN_REQUESTS_PER_MIN, FMP_RATE_FRACTION, _Pacer
from core.cron_health import cron_heartbeat
from core.data_groups import get_snapshot, job_skip_reason
from core.db import engine, init_db
from core.logging_config import configure_logging
from core.tickers import normalize_ticker
from data.corporate_events_data import EVENT_TYPES, NIGHTLY_EVENT_TYPES, prune_old_events, refresh_ticker_events, splits_due
from pipeline.nightly_price_target_snapshot import load_us_price_target_universe

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_corporate_events.log"


async def refresh_all(tickers: list[str], with_splits: set[str] | None = None) -> dict:
    """Refresh every ticker (concurrent across tickers, sequential over a ticker's
    endpoints; request starts paced across the whole run). `with_splits` = tickers whose
    splits are due this run (None = all). Returns the run summary."""
    plan_rate = FMP_PLAN_REQUESTS_PER_MIN.get(get_snapshot().fmp_plan, 300)
    # Pace ticker STARTS at the run's average request count per ticker.
    total_calls = sum(len(NIGHTLY_EVENT_TYPES) + (1 if with_splits is None or t in with_splits else 0) for t in tickers)
    pacer = _Pacer((total_calls / max(len(tickers), 1)) * 60.0 / (plan_rate * FMP_RATE_FRACTION))
    sem = asyncio.Semaphore(FMP_CONCURRENCY)
    failures: list[tuple[str, str]] = []
    rows_written = 0

    async def one(ticker: str) -> None:
        nonlocal rows_written
        async with sem:
            await pacer.wait()
            types = EVENT_TYPES if with_splits is None or ticker in with_splits else NIGHTLY_EVENT_TYPES
            result = await refresh_ticker_events(ticker, types)
        errors = [f"{k}: {v}" for k, v in result.items() if isinstance(v, str)]
        rows_written += sum(v for v in result.values() if isinstance(v, int))
        if errors:
            failures.append((ticker, "; ".join(errors)))

    await asyncio.gather(*(one(t) for t in tickers))
    return {
        "processed": len(tickers), "failed": len(failures), "failures": failures, "rows_written": rows_written,
        "fmp_calls": total_calls,
    }


async def main(tickers: list[str] | None = None) -> dict:
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    skip_reason = job_skip_reason("corporate_events")
    if skip_reason:
        logger.info("Corporate-events refresh %s.", skip_reason)
        return {"processed": 0, "failed": 0, "failures": [], "rows_written": 0, "skipped": True, "skip_reason": skip_reason}

    if tickers is None:
        with Session(engine) as session:
            tickers = load_us_price_target_universe(session)
    if not tickers:
        logger.error("No tickers to process.")
        return {"processed": 0, "failed": 0, "failures": [], "rows_written": 0}

    start = time.monotonic()
    result = await refresh_all(tickers, splits_due(tickers))
    result["pruned"] = prune_old_events()
    result["duration_seconds"] = time.monotonic() - start
    logger.info(
        "Corporate-events refresh complete. Processed: %d. With a failed endpoint: %d. Rows stored: %d. FMP calls: %d. Pruned (older than retention): %d. Duration: %.1fs.",
        result["processed"], result["failed"], result["rows_written"], result["fmp_calls"], result["pruned"], result["duration_seconds"],
    )
    if result["failures"]:
        logger.info("Tickers with failures: %s", ", ".join(f"{t} ({e})" for t, e in result["failures"]))
    return result


def record_outcome(result: dict, run) -> None:
    """Skipped when gated; a run where EVERY ticker had a failed endpoint raises
    (heartbeat "failure" -- FMP down / key revoked); otherwise "success"."""
    if result.get("skipped"):
        run.skip(result["skip_reason"])
    elif result["processed"] and result["failed"] == result["processed"]:
        raise RuntimeError(f"corporate-events refresh failed for all {result['failed']} tickers")
    else:
        run.message = f"{result['processed'] - result['failed']} refreshed, {result['failed']} with a failed endpoint"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Nightly FMP earnings/dividends/splits cache refresh.")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated explicit ticker list (for testing).")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    explicit = [normalize_ticker(t) for t in cli_args.tickers.split(",") if t.strip()] if cli_args.tickers else None
    with cron_heartbeat("pipeline.nightly_corporate_events") as run:
        record_outcome(asyncio.run(main(explicit)), run)
