"""Standalone script: nightly Warren RSI/ADX/WVF (2h) technical entry-signal
recompute, scoped to the same union of every watchlist named W1 through W5
that pipeline/nightly_entry_signal_calculation.py (BB+RSI) reads. See
CLAUDE.md's Warren signal section for the full methodology.

A dedicated script, not folded into nightly_entry_signal_calculation.py --
same "one feature, one script" convention pipeline/nightly_liquidity_zone_
calculation.py's own CLAUDE.md entry documents choosing, doubly justified
here since Warren's fetch (2-year lookback) and computation shape (a full
state-machine replay every run -- see analysis/warren_signal/
state_machine.py's own docstring for why this is safe) are fundamentally
different from BB+RSI's (60-day lookback, latest-day-only), even though both
run on the same W1-W5 union.

Fetches every watchlist ticker's intraday bars in ONE batch call, using
yahoo_client directly (not clients/technical_sources.py's own
get_intraday_bars, which builds an f"{lookback_days}d" period string --
confirmed unreliable at this magnitude by the historical BB+RSI backfill
investigation; period="2y" is the confirmed-reliable form for Yahoo's real
730-day 60m-interval limit, see pipeline/backfills/
backfill_entry_signal_events.py's own comment). Runs entirely on Yahoo
Finance, zero FMP calls -- FMP's intraday endpoints return HTTP 402 under
the current subscription plan (confirmed 2026-09-09), so this needs no
`if not settings.fmp_enabled: ...` guard either, same reasoning
nightly_entry_signal_calculation.py's own docstring gives.

Unlike BB+RSI, there is no separate one-time backfill script for this
signal (see data/warren_signal_data.py's own module docstring) -- running
this script once already backfills all available history, since every run
replays from scratch.

Measured cost -- CORRECTED 2026-09-12 after a real run against the live
98-ticker W1-W5 union exposed a flaw in the original pre-shipping estimate
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
import re
import time
from pathlib import Path

from sqlmodel import Session

from clients.yahoo_client import yahoo_client
from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from data.warren_signal_data import compute_and_store_warren_signal, prune_warren_signal_events, sweep_stale_warren_signals
from data.watchlists import list_tickers_across_watchlists

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_warren_signal_calculation.log"

WATCHLIST_NAME_PATTERN = re.compile(r"^W[1-5]$")
YAHOO_PERIOD = "2y"
YAHOO_INTERVAL = "60m"
SOURCE_NAME = "yahoo"

logger = logging.getLogger(__name__)


async def main() -> dict:
    """Returns the run summary dict so tests can assert on it directly
    rather than scraping the log, same convention as
    nightly_entry_signal_calculation.py::main."""
    configure_logging(LOG_PATH)
    init_db()

    with Session(engine) as session:
        tickers, matched_names = list_tickers_across_watchlists(session, WATCHLIST_NAME_PATTERN)

    if not matched_names:
        logger.warning("No watchlist matching %s exists.", WATCHLIST_NAME_PATTERN.pattern)

    if not tickers:
        logger.error("No tickers found across %s -- nothing to process.", matched_names or WATCHLIST_NAME_PATTERN.pattern)
        swept = sweep_stale_warren_signals()
        pruned = prune_warren_signal_events()
        return {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": [], "swept": swept, "pruned": pruned}

    logger.info("Starting nightly Warren signal calculation for %d tickers across %s.", len(tickers), matched_names)
    start_time = time.monotonic()

    raw = await yahoo_client.get_history(tickers, period=YAHOO_PERIOD, interval=YAHOO_INTERVAL)
    bars_by_ticker = {
        ticker: df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        for ticker, df in raw.items()
    }

    failures: list[tuple[str, str]] = []
    for i, ticker in enumerate(tickers, start=1):
        try:
            bars = bars_by_ticker.get(ticker)
            if bars is None or bars.empty:
                raise ValueError("No intraday bars returned")
            compute_and_store_warren_signal(ticker, bars, source=SOURCE_NAME)
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


if __name__ == "__main__":
    with cron_heartbeat("pipeline.nightly_warren_signal_calculation"):
        asyncio.run(main())
