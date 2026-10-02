"""Standalone script: nightly Warren RSI/ADX/WVF (2h) technical entry-signal
recompute, scoped to the same union of every watchlist named E<number> or ETF
that pipeline/nightly_entry_signal_calculation.py (BB+RSI) reads. See
CLAUDE.md's Warren signal section for the full methodology.

A dedicated script, not folded into nightly_entry_signal_calculation.py --
same "one feature, one script" convention pipeline/nightly_liquidity_zone_
calculation.py's own CLAUDE.md entry documents choosing, doubly justified
here since Warren's fetch (2-year lookback) and computation shape (a full
state-machine replay every run -- see analysis/warren_signal/
state_machine.py's own docstring for why this is safe) are fundamentally
different from BB+RSI's (60-day lookback, latest-day-only), even though both
run on the same monitored-watchlist union.

Reads every watchlist ticker's intraday bars through the shared bars cache
(clients/shared_bars_cache.py, interval "60m", one batch call for whatever
needs a live fetch) rather than fetching independently -- the cache maps a
730-day request to FMP `/historical-chart/1hour` (data group `intraday_bars`; the only
provider since Yahoo's removal in Phase 6b). Skipped -- a real `skipped` cron status -- while
that group is off, same as nightly_entry_signal_calculation.py.

Unlike BB+RSI, there is no separate one-time backfill script for this
signal (see data/warren_signal_data.py's own module docstring) -- running
this script once already backfills all available history, since every run
replays from scratch.

Measured cost -- CORRECTED 2026-09-12 after a real run against the live
98-ticker monitored-watchlist union (then W1-W5) exposed a flaw in the original pre-shipping estimate
(see CLAUDE.md's Warren signal section for the full story): the original
synthetic benchmark fed the state-machine replay ALREADY-BUILT 2h candles
directly, entirely skipping the cost of build_2h_session_candles' own
per-day resample loop over a full 2-year history -- which turns out to
dominate real per-ticker cost (~0.9-1.0s/ticker, vs. the replay's own
~30-40ms). Real end-to-end run: 98 tickers, 98.9s total (fetch ~2-5s,
compute+store the rest). Extrapolated worst case (500 tickers, 100/list x
5 lists): roughly 500-560s (~9 minutes) compute + a batch fetch on the
order of tens of seconds. This is genuinely at the edge of a 5-minute cron
slot at worst case -- see crontab.txt's own comment for why this job now
gets a dedicated ~15-minute window instead of squeezing into the gap
between two other jobs.

Run:
    uv run python -m pipeline.nightly_warren_signal_calculation
"""

import asyncio
import logging
import time
from pathlib import Path

from sqlmodel import Session

from clients.shared_bars_cache import INTRADAY_INTERVAL, get_or_fetch_bars_batch
from core.cron_health import check_failure_threshold, cron_heartbeat
from core.data_groups import job_skip_reason
from core.db import engine, init_db
from core.logging_config import configure_logging
from data.warren_signal_data import compute_and_store_warren_signal, prune_warren_signal_events, sweep_stale_warren_signals
from data.watchlists import MONITORED_WATCHLIST_PATTERN, list_monitored_tickers

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_warren_signal_calculation.log"

# 2 calendar years -- the 60m-interval history window (~730 days).
LOOKBACK_DAYS = 730

logger = logging.getLogger(__name__)


async def main() -> dict:
    """Returns the run summary dict so tests can assert on it directly
    rather than scraping the log, same convention as
    nightly_entry_signal_calculation.py::main."""
    configure_logging(LOG_PATH)
    init_db()

    skip_reason = job_skip_reason("intraday_bars")
    if skip_reason:
        # Data group off (no fallback provider since Phase 6b): computing on stale cached bars
        # would only look healthy. __main__ records CronRunLog status "skipped".
        logger.info("Nightly Warren signal calculation %s.", skip_reason)
        return {"skipped": True, "skip_reason": skip_reason}

    with Session(engine) as session:
        tickers, matched_names = list_monitored_tickers(session)

    if not matched_names:
        logger.warning("No watchlist matching %s exists.", MONITORED_WATCHLIST_PATTERN.pattern)

    if not tickers:
        logger.error("No tickers found across %s -- nothing to process.", matched_names or MONITORED_WATCHLIST_PATTERN.pattern)
        swept = sweep_stale_warren_signals()
        pruned = prune_warren_signal_events()
        return {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": [], "swept": swept, "pruned": pruned}

    logger.info("Starting nightly Warren signal calculation for %d tickers across %s.", len(tickers), matched_names)
    start_time = time.monotonic()

    # Reads through the shared bars cache (interval "60m"): BB+RSI's nightly
    # job reads the same row at a narrower 60-day width, so whichever of the
    # two runs first each night does the one live fetch and the other reads
    # it back -- this job needs no knowledge of which. auto_adjust=False
    # (2026-09-18): raw, non-dividend-adjusted bars. The cache already
    # returns lowercase columns and an America/New_York tz-aware index.
    bars_by_ticker = await get_or_fetch_bars_batch(tickers, INTRADAY_INTERVAL, LOOKBACK_DAYS, auto_adjust=False)

    failures: list[tuple[str, str]] = []
    for i, ticker in enumerate(tickers, start=1):
        try:
            bars = bars_by_ticker.get(ticker)
            if bars is None or bars.empty:
                raise ValueError("No intraday bars returned")
            compute_and_store_warren_signal(ticker, bars, source="fmp")
            logger.info("[%d/%d] %s: ok", i, len(tickers), ticker)
        except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
            logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
            failures.append((ticker, str(exc)))

    swept = sweep_stale_warren_signals()
    pruned = prune_warren_signal_events()

    duration = time.monotonic() - start_time
    logger.info(
        "Nightly Warren signal calculation complete. Processed: %d. Failed: %d. Swept: %d. Pruned: %d. Duration: %.1fs.",
        len(tickers),
        len(failures),
        swept,
        pruned,
        duration,
    )
    if failures:
        logger.info("Tickers with failures: %s", ", ".join(f"{t} ({e})" for t, e in failures))

    return {
        "processed": len(tickers),
        "failed": len(failures),
        "duration_seconds": duration,
        "failures": failures,
        "swept": swept,
        "pruned": pruned,
    }


def record_outcome(summary: dict, run) -> None:
    """Heartbeat mapping: "skipped" for a gated run, else a "N computed, F failed, S swept, P pruned"
    message that raises (heartbeat "failure") past core.cron_health.check_failure_threshold."""
    if summary.get("skipped"):
        run.skip(summary["skip_reason"])
        return
    processed, failed = summary["processed"], summary["failed"]
    message = f"{processed - failed} computed, {failed} failed, {summary['swept']} swept, {summary['pruned']} pruned"
    check_failure_threshold(processed, failed, message)
    run.message = message


if __name__ == "__main__":
    with cron_heartbeat("pipeline.nightly_warren_signal_calculation") as run:
        record_outcome(asyncio.run(main()), run)
