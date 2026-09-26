"""Standalone script: nightly trend-structure recompute across the full
tracked universe (see nightly_fundamentals_fetch.py::load_full_tracked_universe,
reused here rather than duplicated).

Reads daily bars through the shared bars cache (clients/shared_bars_cache.py), which fetches
from FMP `/historical-price-eod/full` (data group `daily_prices`). Yahoo Finance was removed in
Phase 6b: Skipped (a real `skipped` cron status) while the `daily_prices` data group is off -- Phase 6b removed the
Yahoo fallback, so there is nothing to compute on but stale cached bars (core/data_groups.py::job_skip_reason).

Fetches the whole universe's OHLCV in ONE batch call
(clients.shared_bars_cache.get_or_fetch_bars_batch) -- one incremental call per ticker, not a
loop over compute_and_store_trend_analysis -- then runs the pure calculation engine and upserts per ticker
(data.trend_analysis_data.compute_and_store_from_frames), rather than looping
compute_and_store_trend_analysis (which would fetch one ticker at a time).
The Weinstein RS benchmark (Settings > Weinstein, default SPY -- see
analysis/trend_structure/weinstein.py) rides along in this SAME batch call -- one more symbol, not a second
fetch -- but is never added to `tickers` itself, so it never gets its own
TrendAnalysis row and a benchmark fetch failure degrades every ticker's Weinstein RS/breakout fields to
null/false rather than counting as a per-ticker failure.

Run against the full tracked universe:
    uv run python -m pipeline.nightly_trend_calculation

Run against a small subset first:
    uv run python -m pipeline.nightly_trend_calculation --limit 15
    uv run python -m pipeline.nightly_trend_calculation --tickers AAPL,MSFT,ZZZZINVALID
"""

import argparse
import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session

from clients.daily_bar_sources import UnservedTickers, describe_unserved
from clients.shared_bars_cache import DAILY_INTERVAL, get_or_fetch_bars_batch, stale_ticker_count
from core.cron_health import cron_heartbeat
from core.data_groups import job_skip_reason
from core.db import engine, init_db
from core.logging_config import configure_logging
from core.tickers import normalize_ticker
from data.trend_analysis_data import WEINSTEIN_LOOKBACK_DAYS, compute_and_store_from_frames
from helpers.weinstein_config import load_weinstein_params
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe
from pipeline.stale_data_health_check import load_delisted_tickers

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_trend_calculation.log"

# Monday=0 .. Sunday=6, judged in UTC (the cron's own clock: 3:10 UTC).
WEEKLY_RESYNC_WEEKDAY_UTC = 6

logger = logging.getLogger(__name__)


async def main(tickers: list[str] | None = None) -> dict:
    """`tickers=None` means "use the full tracked universe" -- passing an
    explicit list (used by the CLI's --limit/--tickers and by tests)
    bypasses the DB lookup entirely, including the delisted-ticker skip
    below. Returns the run summary dict so tests can assert on it directly
    rather than scraping the log."""
    configure_logging(LOG_PATH)
    init_db()

    skip_reason = job_skip_reason("daily_prices")
    if skip_reason:
        # Data group off (no fallback provider since Phase 6b): computing on stale cached bars
        # would only look healthy. __main__ records CronRunLog status "skipped".
        logger.info("Nightly trend calculation %s.", skip_reason)
        return {"skipped": True, "skip_reason": skip_reason}

    skipped_delisted: list[str] = []
    if tickers is None:
        with Session(engine) as session:
            tickers = load_full_tracked_universe(session)
            delisted = load_delisted_tickers(session)
        if delisted:
            skipped_delisted = sorted(set(tickers) & delisted)
            tickers = [t for t in tickers if t not in delisted]

    if not tickers:
        logger.error("No tickers to process -- run refresh_sp500_list.py/refresh_dow_list.py first, or pass an explicit ticker list.")
        return {
            "processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": [], "stale_count": 0,
            "unserved_count": 0, "skipped_delisted_count": len(skipped_delisted),
        }

    logger.info(
        "Starting nightly trend-structure calculation for %d tickers (%d skipped as delisted).",
        len(tickers), len(skipped_delisted),
    )
    start_time = time.monotonic()

    # The Weinstein RS benchmark (Settings, default SPY) rides along in the SAME batch fetch
    # (Weinstein Stage Analysis's Mansfield RS benchmark) -- never added to `tickers` itself, so it
    # never gets its own TrendAnalysis row and never counts toward
    # processed/failed below.
    #
    # Reads through the shared bars cache (interval "1d"): every ticker also
    # on a W1-W5 watchlist overlaps Liquidity Zones' own (wider, ~4yr)
    # daily need, so whichever of the two jobs runs first each night does
    # the one live fetch for that ticker and the other reads it back --
    # this job never has to know or care which. auto_adjust=False
    # (2026-09-18 decision): raw, non-dividend-adjusted bars.
    # Weinstein Settings are read live from the DB once per run (not cached at
    # process start) -- a settings change applies on the next recompute.
    with Session(engine) as session:
        weinstein_params = load_weinstein_params(session)
    benchmark_ticker = weinstein_params.rs_benchmark
    unserved_tickers = UnservedTickers()
    # Sunday (UTC) run = the weekly full resync: force makes the FMP daily
    # source refetch every ticker's whole 5y window instead of the nightly
    # overlap check, so a sub-0.5% provider restatement (e.g. a small
    # spin-off) can't leave a permanent basis offset in the cache. This is
    # the one nightly job that fetches; the LZ/Breadth/Heatmap jobs after it
    # read the warm cache.
    weekly_resync = datetime.now(timezone.utc).weekday() == WEEKLY_RESYNC_WEEKDAY_UTC
    bars_by_ticker = await get_or_fetch_bars_batch(
        tickers + [benchmark_ticker], DAILY_INTERVAL, WEINSTEIN_LOOKBACK_DAYS, auto_adjust=False,
        unserved_tickers=unserved_tickers, force=weekly_resync,
    )
    benchmark_ohlcv = bars_by_ticker.get(benchmark_ticker)

    # Stale-data guard (docs/yahoo_close_data_gap_investigation_2026-09-23.md):
    # after the fetch attempt above (FMP only -- see clients/daily_bar_sources.py), how many tickers
    # still don't reflect the most recently completed session. Reported via
    # this run's own cron_heartbeat message below rather than escalated to a
    # heartbeat failure -- a handful of stale tickers is normal (delistings,
    # a thin provider gap); Market Breadth's own coverage gate is the one
    # job that fails loudly on genuine insufficiency.
    stale_count, _ = stale_ticker_count(tickers, DAILY_INTERVAL)

    failures: list[tuple[str, str]] = []
    for i, ticker in enumerate(tickers, start=1):
        try:
            compute_and_store_from_frames(ticker, bars_by_ticker.get(ticker), benchmark_ohlcv=benchmark_ohlcv, params=weinstein_params)
            logger.info("[%d/%d] %s: ok", i, len(tickers), ticker)
        except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
            logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
            failures.append((ticker, str(exc)))

    duration = time.monotonic() - start_time
    logger.info(
        "Nightly trend calculation complete. Processed: %d. Failed: %d. Duration: %.1fs (%.1f min).",
        len(tickers),
        len(failures),
        duration,
        duration / 60,
    )
    if failures:
        logger.info("Tickers with failures: %s", ", ".join(f"{t} ({e})" for t, e in failures))

    return {
        "processed": len(tickers),
        "failed": len(failures),
        "duration_seconds": duration,
        "failures": failures,
        "stale_count": stale_count,
        "unserved_count": len(unserved_tickers),
        "skipped_delisted_count": len(skipped_delisted),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Nightly trend-structure (swing/BOS/blended-score) recompute.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N stored tickers (for testing).")
    parser.add_argument(
        "--tickers", type=str, default=None, help="Comma-separated explicit ticker list, overrides the stored list (for testing)."
    )
    return parser.parse_args()


def _resolve_cli_tickers(args: argparse.Namespace) -> list[str] | None:
    if args.tickers:
        return [normalize_ticker(t) for t in args.tickers.split(",") if t.strip()]
    if args.limit:
        init_db()
        with Session(engine) as session:
            all_tickers = load_full_tracked_universe(session)
        return all_tickers[: args.limit]
    return None


if __name__ == "__main__":
    cli_args = _parse_args()
    with cron_heartbeat("pipeline.nightly_trend_calculation") as run:
        summary = asyncio.run(main(_resolve_cli_tickers(cli_args)))
        if summary.get("skipped"):
            run.skip(summary["skip_reason"])
        else:
            run.message = (
                f"{summary['processed']} tickers, {summary['stale_count']} still stale after fetch, "
                f"{describe_unserved(summary['unserved_count'])}, {summary['skipped_delisted_count']} skipped as delisted"
            )
