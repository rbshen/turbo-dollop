"""Standalone script: re-score every ticker in the full tracked universe --
index constituents (S&P 500 + Dow) UNION any ticker with cached FMP data,
an existing TickerScore row, or a Watchlist entry (see
nightly_fundamentals_fetch.py::load_full_tracked_universe, reused here,
not duplicated) -- reading ONLY already-cached raw data -- makes zero FMP
calls. This exists specifically for when scoring logic changes (which has
happened repeatedly in this project -- e.g. the Step 4 window extension)
so every tracked ticker's Screener score can be refreshed immediately,
without waiting for or triggering a full nightly data refetch.

Widened from its original S&P 500 + Dow-only scope (2026-08-15) after a
confirmed real staleness bug: TSM/ASML/MELI are watchlist-only (not index
members), so a Speculative Growth scoring fix that shipped the same day
never reached their TickerScore rows via this path -- see CLAUDE.md's
Speculative Growth section. `load_universe_tickers` (S&P 500 + Dow only)
is still used as-is by monthly_price_target_snapshot.py and
stale_data_health_check.py, which have their own, deliberately narrower
index-only scope -- this module no longer uses it.

Pure computation, no network -- safe to run anytime, no pacing needed.
Also runnable from the UI via POST /api/screener/recompute (main.py), which
calls recompute_all() directly -- NOT main() below, which calls
configure_logging()/init_db() as a standalone-script entry point would.
Calling those from inside the already-running FastAPI app would hijack its
logging setup on every request, so main.py deliberately imports the lower-
level function instead.

Run against the full stored list:
    uv run python -m pipeline.recompute_ticker_scores

Run against a small subset first:
    uv run python -m pipeline.recompute_ticker_scores --limit 15
    uv run python -m pipeline.recompute_ticker_scores --tickers AAPL,MSFT,ZZZZINVALID
"""

import argparse
import asyncio
import logging
import time
from pathlib import Path

from sqlmodel import Session

from core.db import engine, init_db
from core.logging_config import configure_logging
from core.tickers import normalize_ticker
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe
from data.ticker_score import compute_ticker_score

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "recompute_ticker_scores.log"

logger = logging.getLogger(__name__)


async def recompute_all(tickers: list[str] | None = None) -> dict:
    """`tickers=None` means "use the full tracked universe"
    (load_full_tracked_universe) -- passing an explicit list (used by the
    CLI's --limit/--tickers, the API endpoint, and tests) bypasses the DB
    lookup entirely. Returns the run summary dict, same shape as
    nightly_fundamentals_fetch.main()'s (minus calls_made, which is always
    0 here by design -- this path never calls FMP). Deliberately does NOT
    touch logging config or call init_db() -- see this module's docstring
    for why."""
    if tickers is None:
        with Session(engine) as session:
            tickers = load_full_tracked_universe(session)

    if not tickers:
        logger.error("No tickers to process -- run refresh_sp500_list.py first, or pass an explicit ticker list.")
        return {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": []}

    logger.info("Starting cache-only score recompute for %d tickers.", len(tickers))

    start_time = time.monotonic()
    failures: list[tuple[str, str]] = []
    skipped = 0

    for i, ticker in enumerate(tickers, start=1):
        try:
            result = await compute_ticker_score(ticker, cache_only=True)
            if result is None:
                skipped += 1
                logger.info("[%d/%d] %s: skipped (no cached profile)", i, len(tickers), ticker)
            else:
                logger.info("[%d/%d] %s: ok (overall_score=%s)", i, len(tickers), ticker, result.overall_score)
        except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
            logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
            failures.append((ticker, str(exc)))

    duration = time.monotonic() - start_time

    logger.info(
        "Recompute complete. Processed: %d. Skipped (no cached data): %d. Failed: %d. Duration: %.1fs (%.1f min).",
        len(tickers),
        skipped,
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
    }


async def main(tickers: list[str] | None = None) -> dict:
    """Standalone-script entry point: sets up file+console logging and
    ensures the DB schema exists, then delegates to recompute_all(), which
    resolves the full tracked universe when tickers=None. Not used by the
    API endpoint -- see this module's docstring."""
    configure_logging(LOG_PATH)
    init_db()
    return await recompute_all(tickers)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cache-only Screener score recompute for the full tracked ticker universe.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N tracked tickers (for testing).")
    parser.add_argument(
        "--tickers", type=str, default=None, help="Comma-separated explicit ticker list, overrides the tracked universe (for testing)."
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
    asyncio.run(main(_resolve_cli_tickers(cli_args)))
