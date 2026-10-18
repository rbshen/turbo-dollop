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

from clients.shared_bars_cache import INTRADAY_INTERVAL, get_or_fetch_bars_batch, stale_ticker_count
from core.cron_health import check_failure_threshold, cron_heartbeat
from core.data_groups import job_skip_reason
from core.db import engine, init_db
from core.logging_config import configure_logging
from data.warren_signal_data import (
    compute_and_store_warren_signal_with_events,
    prune_warren_signal_events,
    refresh_warren_score_fields,
    sweep_stale_warren_signals,
)
from data.warren_watch_data import update_warren_watch
from data.watchlists import MONITORED_WATCHLIST_PATTERN, list_monitored_tickers
from helpers.liquidity_zone_config import get_liquidity_zone_settings, peek_liquidity_zone_settings, to_engine_settings

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_warren_signal_calculation.log"

# 2 calendar years of 60m bars. 730 days is our own fetch choice, carried over from the Yahoo era
# (Yahoo's 60m limit), NOT an FMP limit: FMP's published Starter limit for 1hour bars is 5 years, and
# a Starter key served them back to 2004 (AAPL) / 2005 (SPY) in a 2026-10-14 check. Changing it moves
# the Chart 2H range's lookback (pinned equal), the shared-cache "2y" tier and RETENTION_DAYS' tests.
LOOKBACK_DAYS = 730

logger = logging.getLogger(__name__)


def update_watch_table(tickers: list[str], bars_by_ticker: dict, dry_run: bool = False) -> dict:
    """The final step: replay every ticker's completed 2h candles from the fixed anchor on the bars the job just read and
    rewrite the Warren Signals watch rows whose result differs (data/warren_watch_data.py, docs/specs/warren-signals-page.md;
    stateless since 2026-10-17, no extra download). A failure here is counted on its own and never changes the Warren signal
    results above; the 2nd-LP settings are read once. `dry_run` writes nothing (not even the settings row) and returns the
    per-ticker outcomes and field changes in `watch_details`."""
    start = time.monotonic()
    with Session(engine) as session:
        if dry_run:  # a pure read: get_liquidity_zone_settings would create the default row
            settings = to_engine_settings(peek_liquidity_zone_settings(session))
        else:
            settings = to_engine_settings(get_liquidity_zone_settings(session))
    created = changed = lp_calls = 0
    gate = {"uses": 0, "eligible": 0, "walked": 0, "none": 0, "off": 0, "short": 0}
    no_atr: list[str] = []  # tickers with no usable daily ATR for any candle the replay read (the LP gate is off for them)
    details: list[tuple[str, str, dict]] = []
    failures: list[tuple[str, str]] = []
    for ticker in tickers:
        try:
            bars = bars_by_ticker.get(ticker)
            if bars is None or bars.empty:
                raise ValueError("No intraday bars returned")
            update = update_warren_watch(ticker, bars, settings, dry_run=True) if dry_run else update_warren_watch(ticker, bars, settings)
            created += update.outcome == "created"
            changed += update.outcome == "changed"
            lp_calls += update.lp_calls
            for key in gate:
                gate[key] += update.lp_gate.get(key, 0)
            if not update.daily_atr:
                no_atr.append(ticker)
            if update.outcome in ("created", "changed"):
                details.append((ticker, update.outcome, update.changes))
        except Exception as exc:  # noqa: BLE001 -- one bad ticker must never abort the watch step
            logger.error("Warren watch %s: FAILED - %s", ticker, exc)
            failures.append((ticker, str(exc)))
    duration = time.monotonic() - start
    logger.info(
        "Warren watch table updated. Tickers: %d. Created: %d. Changed: %d. Failed: %d. LP calls: %d. Duration: %.1fs.",
        len(tickers), created, changed, len(failures), lp_calls, duration,
    )
    # The LP gate (daily ATR): how its selections went, and where it was off because no daily ATR existed (docs/specs/warren-signals-page.md).
    logger.info(
        "Warren watch LP gate: %d selections, %d 2nd LP eligible, %d walked to a lower LP, %d with no eligible LP, %d with no daily ATR (gate off), %d with fewer than 2 supports. "
        "Tickers with no daily ATR: %d%s.",
        gate["uses"], gate["eligible"], gate["walked"], gate["none"], gate["off"], gate["short"], len(no_atr), f" ({', '.join(no_atr[:10])})" if no_atr else "",
    )
    return {
        "watch_attempted": len(tickers), "watch_failed": len(failures), "watch_created": created, "watch_changed": changed,
        "watch_lp_calls": lp_calls, "watch_seconds": duration, "watch_failures": failures, "watch_details": details,
        "watch_lp_gate": gate, "watch_no_daily_atr": no_atr,
    }


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
        return {
            "processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": [], "swept": swept, "pruned": pruned,
            "stale_count": 0,
        }

    logger.info("Starting nightly Warren signal calculation for %d tickers across %s.", len(tickers), matched_names)
    start_time = time.monotonic()

    # Reads through the shared bars cache (interval "60m"): BB+RSI's nightly
    # job reads the same row at a narrower 60-day width, so whichever of the
    # two runs first each night does the one live fetch and the other reads
    # it back -- this job needs no knowledge of which. auto_adjust=False
    # (2026-09-18): raw, non-dividend-adjusted bars. The cache already
    # returns lowercase columns and an America/New_York tz-aware index.
    bars_by_ticker = await get_or_fetch_bars_batch(tickers, INTRADAY_INTERVAL, LOOKBACK_DAYS, auto_adjust=False)

    # Stale-data guard: after the fetch attempt above, how many tickers' cached 60m bars still don't reflect the
    # most recently completed bar (an FMP error / empty answer leaves the cached bars as they were). Surfaced in
    # the log line and the heartbeat message only -- same as nightly_trend_calculation.py -- never a failure and
    # never a reason to skip a ticker's compute.
    stale_count, _ = stale_ticker_count(tickers, INTRADAY_INTERVAL)

    failures: list[tuple[str, str]] = []
    # The event log is reconciled with each ticker's replay as it is computed (data/warren_signal_data.py::reconcile_events): a ticker whose
    # bars are missing or whose replay fails raises BEFORE any event is touched, so a failed ticker keeps its events as they were.
    events_added = events_deleted = 0
    events_skipped: list[tuple[str, str]] = []
    events_changed: list[str] = []
    for i, ticker in enumerate(tickers, start=1):
        try:
            bars = bars_by_ticker.get(ticker)
            if bars is None or bars.empty:
                raise ValueError("No intraday bars returned")
            _, plan = compute_and_store_warren_signal_with_events(ticker, bars, source="fmp")
            events_added += len(plan.added)
            events_deleted += len(plan.deleted)
            if plan.changed:
                events_changed.append(ticker)
            if plan.skipped:
                events_skipped.append((ticker, plan.skipped))
            logger.info("[%d/%d] %s: ok", i, len(tickers), ticker)
        except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
            logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
            failures.append((ticker, str(exc)))

    swept = sweep_stale_warren_signals()
    pruned = prune_warren_signal_events()
    # The Warren fields of TickerScore / EtfScreenerRow follow the log in the same run for every ticker whose events changed.
    score_rows_refreshed = refresh_warren_score_fields(events_changed) if events_changed else 0
    if events_added or events_deleted:
        logger.info("Warren events reconciled: %d added, %d deleted across %d tickers; %d score rows refreshed.", events_added, events_deleted, len(events_changed), score_rows_refreshed)
    watch = update_watch_table(tickers, bars_by_ticker)

    duration = time.monotonic() - start_time
    logger.info(
        "Nightly Warren signal calculation complete. Processed: %d. Failed: %d. Swept: %d. Pruned: %d. Stale: %d. Duration: %.1fs.",
        len(tickers),
        len(failures),
        swept,
        pruned,
        stale_count,
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
        "stale_count": stale_count,
        "events_added": events_added,
        "events_deleted": events_deleted,
        "events_skipped": events_skipped,
        "events_changed_tickers": events_changed,
        "score_rows_refreshed": score_rows_refreshed,
        **watch,
    }


def record_outcome(summary: dict, run) -> None:
    """Heartbeat mapping: "skipped" for a gated run, else a "N computed, F failed, S swept, P pruned, K still stale
    after fetch" message that raises (heartbeat "failure") past core.cron_health.check_failure_threshold. The stale
    count is informational only (like the daily-bar jobs'): it is not part of the failure threshold."""
    if summary.get("skipped"):
        run.skip(summary["skip_reason"])
        return
    processed, failed = summary["processed"], summary["failed"]
    message = (
        f"{processed - failed} computed, {failed} failed, {summary['swept']} swept, {summary['pruned']} pruned, "
        f"{summary['stale_count']} still stale after fetch"
    )
    check_failure_threshold(processed, failed, message)
    if summary.get("events_added") or summary.get("events_deleted") or summary.get("events_skipped"):
        message += f"; events: {summary['events_added']} added, {summary['events_deleted']} deleted, {len(summary['events_skipped'])} skipped"
    if "watch_attempted" in summary:
        message += f"; watch table: {summary['watch_created']} created, {summary['watch_changed']} changed, {summary['watch_failed']} failed"
        check_failure_threshold(summary["watch_attempted"], summary["watch_failed"], message)
    run.message = message


if __name__ == "__main__":
    with cron_heartbeat("pipeline.nightly_warren_signal_calculation") as run:
        record_outcome(asyncio.run(main()), run)
