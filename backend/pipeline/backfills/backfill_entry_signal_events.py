"""One-time standalone script: backfills TechnicalEntrySignalEvent with
historical BB+RSI (2h) fires, scoped to the same union of every watchlist
named W1 through W5 the nightly job itself reads (see
pipeline/nightly_entry_signal_calculation.py::WATCHLIST_NAME_PATTERN,
reused directly here rather than duplicated).

Why period="2y", not the f"{lookback_days}d" interpolation
clients/technical_sources.py::YahooTechnicalSource builds for the nightly
job's own (much shorter, 60-day) lookback: the historical-backfill
feasibility investigation confirmed that arbitrary "Nd" period strings
behave inconsistently in yfinance 1.6.0 for large N (e.g. "730d" silently
returned ~1065 calendar days of data, while "800d" hit Yahoo's real
"requested range must be within the last 730 days" error) -- an
undocumented, version-specific quirk, not a reliable contract. The
canonical enum value "2y" was confirmed to reliably return exactly
Yahoo's real 730-calendar-day 2h/60m-interval limit, verified against all
96 real W1/W2/W3 tickers in one batch call (96/96 succeeded, ~15s) during
that investigation. This script uses "2y" for that reason.

Deliberately EXCLUDES "today" (the day the script is run) from what it
inserts: compute_historical_entry_signals keeps the FIRST firing candle
per day (see its own docstring for why that differs from the nightly
job's LAST-firing convention), while tonight's regular nightly cron run
will independently evaluate today via compute_entry_signal (LAST firing
candle). Since both write into the same TechnicalEntrySignalEvent table
and today's LAST and FIRST firing candles can be genuinely different
timestamps (not just the same row twice), letting both write for the same
calendar day would produce two distinct rows for one day -- a real,
avoidable duplicate, not something on_conflict_do_nothing's exact-
timestamp uniqueness check would catch. Drawing the line at "today belongs
to the nightly job, everything before belongs to the backfill" avoids
this entirely: run the backfill any day, any number of times, and it
never contests today's row with tonight's cron run.

Run against a small subset first (recommended before the full universe):
    uv run python -m pipeline.backfills.backfill_entry_signal_events --limit 5
    uv run python -m pipeline.backfills.backfill_entry_signal_events --tickers AAPL,MSFT,ZZZZINVALID

Preview without writing:
    uv run python -m pipeline.backfills.backfill_entry_signal_events --dry-run

Run against the full W1-W5 union:
    uv run python -m pipeline.backfills.backfill_entry_signal_events
"""

import argparse
import asyncio
import logging
import time
from datetime import date
from pathlib import Path

from sqlmodel import Session

from analysis.entry_signal.engine import compute_historical_entry_signals
from clients.yahoo_client import yahoo_client
from core.db import engine, init_db
from core.logging_config import configure_logging
from data.entry_signal_data import record_historical_entry_signal_events
from data.watchlists import list_tickers_across_watchlists
from pipeline.nightly_entry_signal_calculation import WATCHLIST_NAME_PATTERN

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "backfill_entry_signal_events.log"

BACKFILL_YAHOO_PERIOD = "2y"
BACKFILL_YAHOO_INTERVAL = "60m"

logger = logging.getLogger(__name__)


def _resolve_tickers(limit: int | None, tickers_override: str | None) -> list[str]:
    if tickers_override:
        return [t.strip().upper() for t in tickers_override.split(",") if t.strip()]
    with Session(engine) as session:
        tickers, _ = list_tickers_across_watchlists(session, WATCHLIST_NAME_PATTERN)
    return tickers[:limit] if limit is not None else tickers


async def backfill(limit: int | None = None, tickers_override: str | None = None, dry_run: bool = False) -> dict:
    """Returns a summary dict (mirrors the nightly job's own return shape)
    so tests/callers can assert on it directly rather than scraping logs."""
    init_db()
    tickers = _resolve_tickers(limit, tickers_override)
    if not tickers:
        logger.error("No tickers resolved -- nothing to backfill.")
        return {"processed": 0, "failed": 0, "inserted": 0, "duration_seconds": 0.0, "failures": []}

    today = date.today()
    logger.info("Starting historical entry-signal backfill for %d ticker(s), excluding %s (today).", len(tickers), today)
    start_time = time.monotonic()

    raw = await yahoo_client.get_history(tickers, period=BACKFILL_YAHOO_PERIOD, interval=BACKFILL_YAHOO_INTERVAL)

    failures: list[tuple[str, str]] = []
    total_inserted = 0
    for i, ticker in enumerate(tickers, start=1):
        try:
            df = raw.get(ticker)
            if df is None or df.empty:
                raise ValueError("No intraday bars returned")
            ohlcv = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
            results = compute_historical_entry_signals(ohlcv)
            results = [r for r in results if r.fired_at.date() < today]
            inserted = 0 if dry_run else record_historical_entry_signal_events(ticker, results)
            total_inserted += inserted
            logger.info("[%d/%d] %s: %d historical fire(s), %d inserted", i, len(tickers), ticker, len(results), inserted)
        except Exception as exc:  # noqa: BLE001 -- one bad ticker must never abort the whole backfill
            logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
            failures.append((ticker, str(exc)))

    duration = time.monotonic() - start_time
    logger.info(
        "Backfill complete. Processed: %d. Failed: %d. Inserted: %d. Duration: %.1fs.%s",
        len(tickers),
        len(failures),
        total_inserted,
        duration,
        " (dry run -- nothing written)" if dry_run else "",
    )
    if failures:
        logger.info("Tickers with failures: %s", ", ".join(f"{t} ({e})" for t, e in failures))

    return {
        "processed": len(tickers),
        "failed": len(failures),
        "inserted": total_inserted,
        "duration_seconds": duration,
        "failures": failures,
    }


def main() -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N tickers.")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated ticker override, ignoring the W1-W5 union.")
    parser.add_argument("--dry-run", action="store_true", help="Compute and log without writing to the database.")
    args = parser.parse_args()

    configure_logging(LOG_PATH)
    return asyncio.run(backfill(limit=args.limit, tickers_override=args.tickers, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
