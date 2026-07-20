"""One-time standalone script: force-refresh ONLY the balance_sheet_statement
(annual) and key_metrics (annual) cache entries for every ticker in the
stored S&P 500 list, ignoring the normal cache-staleness window.

Why this exists: Step 4's annual balance-sheet/key-metrics fetch limit was
bumped from 5 to 10 (see CLAUDE.md's Step 4 display-vs-scoring window
deviation), but tickers already cached before that change stay stuck at the
old 5-year data until their cache naturally goes stale (7 days) or someone
hits "Refresh data" for that one ticker. This backfills all ~500 S&P 500
tickers in one pass instead of waiting on either of those.

Deliberately narrower than nightly_fundamentals_fetch.py: only these two
statement_type/period cache keys are touched, nothing else, and via
cache.force_fetch (always overwrites) rather than get_or_fetch (which would
skip tickers whose cache isn't stale yet -- the whole point here is to
ignore staleness).

Run against a small subset first (recommended before the full list):
    uv run python bulk_refresh_step4_annual.py --limit 15
    uv run python bulk_refresh_step4_annual.py --tickers AAPL,MSFT,ZZZZINVALID

Run against the full stored S&P 500 list:
    uv run python bulk_refresh_step4_annual.py
"""

import argparse
import asyncio
import logging
import time
from pathlib import Path

from sqlmodel import Session

from cache import force_fetch
from db import engine, init_db
from fmp_client import fmp_client
from logging_config import configure_logging
from nightly_fundamentals_fetch import load_sp500_tickers

LOG_PATH = Path(__file__).resolve().parent / "logs" / "bulk_refresh_step4_annual.log"

DISPLAY_ANNUAL_WINDOW = 10

# Same pacing approach as nightly_fundamentals_fetch.py, at the lower end of
# the requested 200-250 req/min range.
TARGET_REQUESTS_PER_MINUTE = 220


async def _refresh_one_ticker(session: Session, ticker: str) -> None:
    await force_fetch(
        session,
        ticker,
        "balance_sheet_statement",
        "annual",
        lambda: fmp_client.get_balance_sheet_statement(ticker, "annual", DISPLAY_ANNUAL_WINDOW),
    )
    await force_fetch(
        session,
        ticker,
        "key_metrics",
        "annual",
        lambda: fmp_client.get_key_metrics(ticker, "annual", DISPLAY_ANNUAL_WINDOW),
    )


async def main(tickers: list[str] | None = None) -> dict:
    """`tickers=None` means "use the full stored S&P 500 list" -- passing an
    explicit list (used by the CLI's --limit/--tickers and by tests)
    bypasses the DB lookup entirely. Returns the run summary dict, same
    shape as nightly_fundamentals_fetch.main()."""
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    if tickers is None:
        with Session(engine) as session:
            tickers = load_sp500_tickers(session)

    if not tickers:
        logger.error("No tickers to process -- run refresh_sp500_list.py first, or pass an explicit ticker list.")
        return {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": []}

    fmp_client.min_request_interval = 60.0 / TARGET_REQUESTS_PER_MINUTE
    logger.info(
        "Starting bulk balance_sheet_statement/key_metrics (annual) refresh for %d tickers "
        "(pacing %.3fs/request, target %d req/min).",
        len(tickers),
        fmp_client.min_request_interval,
        TARGET_REQUESTS_PER_MINUTE,
    )

    start_time = time.monotonic()
    start_request_count = fmp_client.request_count
    failures: list[tuple[str, str]] = []

    with Session(engine) as session:
        for i, ticker in enumerate(tickers, start=1):
            try:
                await _refresh_one_ticker(session, ticker)
                logger.info("[%d/%d] %s: ok", i, len(tickers), ticker)
            except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
                logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
                failures.append((ticker, str(exc)))

    duration = time.monotonic() - start_time
    calls_made = fmp_client.request_count - start_request_count

    logger.info(
        "Bulk refresh complete. Processed: %d. Failed: %d. FMP calls made: %d. Duration: %.1fs (%.1f min).",
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
    parser = argparse.ArgumentParser(
        description="One-time bulk refresh of balance_sheet_statement/key_metrics (annual) for stored S&P 500 tickers."
    )
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
            all_tickers = load_sp500_tickers(session)
        return all_tickers[: args.limit]
    return None


if __name__ == "__main__":
    cli_args = _parse_args()
    asyncio.run(main(_resolve_cli_tickers(cli_args)))
