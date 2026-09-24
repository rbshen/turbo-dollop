"""One-time standalone script: backfill 5 years of daily OHLCV history from
Massive/Polygon into SharedBarsCache ("1d" rows) for every US-listed ticker
this app's daily-bar consumers need, ahead of the nightly jobs' own
incremental fetches taking over (see clients/daily_bar_sources.py,
clients/shared_bars_cache.py).

Why this exists: after the Phase 1 Massive migration
(docs/massive_feasibility_investigation_2026-09-23.md), each nightly job
already backfills a new/insufficient-history ticker automatically the
first time it reaches it -- but running that lazily, one ticker at a time,
would spread the one-time cost across several nights (whichever job
happens to touch a given ticker first) and leave the rest of that ticker's
consumers reading a stale/narrower Yahoo-sourced cache until their own job
catches up. This script does the whole universe in one pass instead, at a
flat 5-year window -- comfortably covers every consumer's own narrower
need (Liquidity Zones' ~4y is the widest recurring one; Chart D_2Y's
on-demand 5y is the widest overall).

Universe: the union of every daily-bar consumer's own universe -- full
tracked universe (Trend/Weinstein), S&P 500 (Market Breadth), the W1-W5
watchlist union (Liquidity Zones), the 11 SPDR sector ETFs + SPY (Sector
Heatmap), and the Moat-rated universe (Momentum). A non-US ticker (dot
suffix, core/tickers.py::is_non_us_ticker) is skipped entirely, not
attempted on Massive -- left exactly as-is on Yahoo, unaffected by this
migration.

Writes through clients/shared_bars_cache.py's own `_write_rows` upsert --
the same choke point the nightly jobs' live fetches use -- so a ticker
already touched by tonight's cron run before this script gets around to
it is simply overwritten with the same (or newer) data, never duplicated.

Run against a small subset first (recommended before the full universe):
    uv run python -m pipeline.backfills.backfill_massive_daily_bars --tickers AAPL,MSFT,ZZZZINVALID
    uv run python -m pipeline.backfills.backfill_massive_daily_bars --limit 15

Run against the full universe:
    uv run python -m pipeline.backfills.backfill_massive_daily_bars
"""

import argparse
import asyncio
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from clients.massive_client import massive_client
from clients.shared_bars_cache import DAILY_INTERVAL, _write_rows
from core.db import engine, init_db
from core.logging_config import configure_logging
from core.models import TickerScore
from core.tickers import is_non_us_ticker, normalize_ticker, to_massive_symbol
from data.sector_heatmap_data import SECTOR_ETFS
from data.watchlists import list_tickers_across_watchlists
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe, load_sp500_tickers

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "backfill_massive_daily_bars.log"

# Covers every daily-bar consumer's own window -- Liquidity Zones' ~4y is
# the widest RECURRING nightly need; Chart D_2Y's on-demand 5y is the
# widest overall, so this backfill matches that rather than the narrower
# 4y, future-proofing against a Chart view being the first thing to ask
# for a ticker's deepest history.
LOOKBACK_DAYS = 5 * 365

WATCHLIST_NAME_PATTERN = re.compile(r"^W[1-5]$")
# Same set data/momentum_data.py::MOAT_VALUES uses -- a ticker with no
# moat set at all is excluded, never included with a fabricated default.
MOAT_VALUES = {"wide_moat", "narrow_moat", "no_moat"}


def _resolve_universe(session: Session) -> list[str]:
    """Union of every daily-bar consumer's own universe -- see module
    docstring. Deduped and normalized; callers filter out non-US tickers
    separately (see main), not here, so a caller that wants the raw union
    for its own purposes still gets it complete."""
    tickers: set[str] = set(load_full_tracked_universe(session))
    tickers.update(load_sp500_tickers(session))
    lz_tickers, _ = list_tickers_across_watchlists(session, WATCHLIST_NAME_PATTERN)
    tickers.update(lz_tickers)
    tickers.update(t for t, _ in SECTOR_ETFS)
    tickers.add("SPY")
    moat_rows = session.exec(select(TickerScore.ticker, TickerScore.moat)).all()
    tickers.update(t for t, moat in moat_rows if moat in MOAT_VALUES)
    return sorted(normalize_ticker(t) for t in tickers)


async def _backfill_one_ticker(session: Session, ticker: str, fetched_at: datetime) -> int:
    """Returns the number of bars written (0 if Massive had nothing for
    this ticker -- not an error, just recorded as such in the summary)."""
    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    df = await massive_client.get_daily_bars(to_massive_symbol(ticker), start, end, adjusted=True)
    if df.empty:
        return 0
    _write_rows(session, ticker, DAILY_INTERVAL, df, fetched_at)
    return len(df)


async def main(tickers: list[str] | None = None) -> dict:
    """`tickers=None` means "use the full resolved universe" -- passing an
    explicit list (used by the CLI's --limit/--tickers and by tests)
    bypasses the DB lookup entirely. Returns the run summary dict so a
    manual run can assert on it directly rather than scraping the log."""
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    if tickers is None:
        with Session(engine) as session:
            tickers = _resolve_universe(session)

    us_tickers = [t for t in tickers if not is_non_us_ticker(t)]
    skipped_non_us = len(tickers) - len(us_tickers)

    if not us_tickers:
        logger.error("No US-listed tickers to process.")
        return {
            "processed": 0,
            "failed": 0,
            "skipped_non_us": skipped_non_us,
            "bars_written": 0,
            "duration_seconds": 0.0,
            "failures": [],
        }

    logger.info(
        "Starting Massive daily-bar backfill for %d US-listed ticker(s) (%d non-US skipped, left on Yahoo), "
        "%d-year lookback.",
        len(us_tickers),
        skipped_non_us,
        LOOKBACK_DAYS // 365,
    )

    start_time = time.monotonic()
    fetched_at = datetime.now()
    failures: list[tuple[str, str]] = []
    bars_written = 0

    with Session(engine) as session:
        for i, ticker in enumerate(us_tickers, start=1):
            try:
                n = await _backfill_one_ticker(session, ticker, fetched_at)
                bars_written += n
                logger.info("[%d/%d] %s: ok (%d bars)", i, len(us_tickers), ticker, n)
            except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
                logger.error("[%d/%d] %s: FAILED - %s", i, len(us_tickers), ticker, exc)
                failures.append((ticker, str(exc)))

    duration = time.monotonic() - start_time
    logger.info(
        "Massive daily-bar backfill complete. Processed: %d. Failed: %d. Bars written: %d. Duration: %.1fs (%.1f min).",
        len(us_tickers),
        len(failures),
        bars_written,
        duration,
        duration / 60,
    )
    if failures:
        logger.info("Tickers with failures: %s", ", ".join(f"{t} ({e})" for t, e in failures))

    return {
        "processed": len(us_tickers),
        "failed": len(failures),
        "skipped_non_us": skipped_non_us,
        "bars_written": bars_written,
        "duration_seconds": duration,
        "failures": failures,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-time backfill of Massive/Polygon 5y daily OHLCV bars into SharedBarsCache."
    )
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N resolved-universe tickers (for testing).")
    parser.add_argument(
        "--tickers", type=str, default=None, help="Comma-separated explicit ticker list, overrides the resolved universe (for testing)."
    )
    return parser.parse_args()


def _resolve_cli_tickers(args: argparse.Namespace) -> list[str] | None:
    if args.tickers:
        return [normalize_ticker(t) for t in args.tickers.split(",") if t.strip()]
    if args.limit:
        init_db()
        with Session(engine) as session:
            all_tickers = _resolve_universe(session)
        return all_tickers[: args.limit]
    return None


if __name__ == "__main__":
    cli_args = _parse_args()
    asyncio.run(main(_resolve_cli_tickers(cli_args)))
