"""One-time standalone script: force-refresh the balance_sheet_statement
(quarterly) cache entry for every ticker that currently has one, ignoring
the normal cache-staleness window.

Why this exists: ticker_summary.py's balance-sheet-quarterly fetch was
hardcoded to limit=1 (a holdover from before Step 4/Step 5/the Financials
tab were bumped to TOTAL_QUARTERS_NEEDED in the "Add Financials tab"
commit). Since ticker_summary.py backs the Summary tab -- the default tab,
which fetches first on every ticker page load -- its limit-1 request almost
always won the race for any given ticker and cached a thin 1-row result
under the shared ("balance_sheet_statement", "quarterly") cache key before
Step 4/5/the Financials tab ever got a chance to fetch the deeper version.
That bug is now fixed at the call site, but every ticker already cached
under the old race stays stuck at 1 row until its cache naturally goes
stale (7 days) or someone hits "Refresh data". This backfills all of them
in one pass instead of waiting.

Deliberately targets tickers already present in the cache under this exact
key (not the stored S&P 500 list) -- this is a targeted repair of existing
thin rows, not a general prefetch, so it should touch exactly the tickers
affected by the bug and nothing else.

Run against a small subset first (recommended before the full list):
    uv run python bulk_refresh_balance_sheet_quarterly.py --limit 15
    uv run python bulk_refresh_balance_sheet_quarterly.py --tickers AAPL,MSFT,ZZZZINVALID

Run against every affected ticker:
    uv run python bulk_refresh_balance_sheet_quarterly.py
"""

import argparse
import asyncio
import logging
import time
from pathlib import Path

from sqlmodel import Session, select

from cache import force_fetch
from db import engine, init_db
from fmp_client import fmp_client
from logging_config import configure_logging
from models import FundamentalsCache
from ttm import TOTAL_QUARTERS_NEEDED

LOG_PATH = Path(__file__).resolve().parent / "logs" / "bulk_refresh_balance_sheet_quarterly.log"

# Same pacing approach as nightly_fundamentals_fetch.py/bulk_refresh_step4_annual.py,
# at the lower end of the requested 200-250 req/min range.
TARGET_REQUESTS_PER_MINUTE = 220


def load_cached_tickers(session: Session) -> list[str]:
    """Every ticker with an existing balance_sheet_statement/quarterly cache
    row, regardless of index membership -- the bug affects whatever
    happens to be cached, not just S&P 500 constituents."""
    rows = session.exec(
        select(FundamentalsCache.ticker).where(
            FundamentalsCache.statement_type == "balance_sheet_statement",
            FundamentalsCache.period == "quarterly",
        )
    ).all()
    return sorted(set(rows))


async def _refresh_one_ticker(session: Session, ticker: str) -> None:
    await force_fetch(
        session,
        ticker,
        "balance_sheet_statement",
        "quarterly",
        lambda: fmp_client.get_balance_sheet_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
    )


async def main(tickers: list[str] | None = None) -> dict:
    """`tickers=None` means "every ticker currently cached under this key" --
    passing an explicit list (used by the CLI's --limit/--tickers and by
    tests) bypasses the DB lookup entirely. Returns the run summary dict,
    same shape as bulk_refresh_step4_annual.main()."""
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    if tickers is None:
        with Session(engine) as session:
            tickers = load_cached_tickers(session)

    if not tickers:
        logger.error("No cached balance_sheet_statement/quarterly rows found -- nothing to refresh.")
        return {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": []}

    fmp_client.min_request_interval = 60.0 / TARGET_REQUESTS_PER_MINUTE
    logger.info(
        "Starting bulk balance_sheet_statement (quarterly) refresh for %d tickers "
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
        description="One-time bulk refresh of balance_sheet_statement (quarterly) for every currently-cached ticker."
    )
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N cached tickers (for testing).")
    parser.add_argument(
        "--tickers", type=str, default=None, help="Comma-separated explicit ticker list, overrides the cached list (for testing)."
    )
    return parser.parse_args()


def _resolve_cli_tickers(args: argparse.Namespace) -> list[str] | None:
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.limit:
        init_db()
        with Session(engine) as session:
            all_tickers = load_cached_tickers(session)
        return all_tickers[: args.limit]
    return None


if __name__ == "__main__":
    cli_args = _parse_args()
    asyncio.run(main(_resolve_cli_tickers(cli_args)))
