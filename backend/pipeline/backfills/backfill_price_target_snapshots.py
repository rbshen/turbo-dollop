"""One-time standalone script: backfills PriceTargetSnapshot with a
reconstructed monthly price-target-consensus history, for every ticker in
the full tracked universe (see load_full_tracked_universe -- deliberately
broader than nightly_price_target_snapshot.py's own ongoing
load_universe_tickers scope, since a backfill's whole point is maximal
historical coverage; the monthly cron itself is unchanged by this script).

Why this exists: nightly_price_target_snapshot.py only ever appends a row
going forward from whenever it first ran -- confirmed live, only 2 rows
exist in production as of this script's own investigation, both dated
2026-07-27. FMP's own /price-target-consensus has no historical series of
its own, but /price-target-news does have real per-analyst target actions
going back to 2021+ for well-covered names (confirmed: AAPL 260 rows,
MSFT 271 rows) -- see helpers/price_target_history.py::
reconstruct_monthly_snapshots for the reconstruction itself (a rolling
most-recent-per-analyst consensus, one row per calendar month-end).

Idempotency is structural, not a special-cased skip: each ticker's existing
earliest PriceTargetSnapshot.snapshot_date (if any) is passed as
reconstruct_monthly_snapshots' own `before` bound, so reconstruction never
produces a month on or after whatever's already stored -- re-running this
script against an already-backfilled ticker reconstructs an empty month
range and inserts nothing, rather than needing a separate "already done"
flag. This also means a real (non-backfill) monthly-cron row is never
duplicated or contradicted: the backfill always stops the month before it.

Run against a small subset first (recommended before the full universe):
    uv run python -m pipeline.backfills.backfill_price_target_snapshots --limit 15
    uv run python -m pipeline.backfills.backfill_price_target_snapshots --tickers AAPL,MSFT,ZZZZINVALID

Preview without writing:
    uv run python -m pipeline.backfills.backfill_price_target_snapshots --dry-run

Run against the full tracked universe:
    uv run python -m pipeline.backfills.backfill_price_target_snapshots
"""

import argparse
import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from clients.fmp_client import fmp_client
from core.db import engine, init_db
from core.logging_config import configure_logging
from core.models import PriceTargetSnapshot
from core.tickers import normalize_ticker
from helpers.price_target_history import reconstruct_monthly_snapshots
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "backfill_price_target_snapshots.log"

# Same empirically-derived pacing as nightly_fundamentals_fetch.py.
TARGET_REQUESTS_PER_MINUTE = 220

# FMP caps /price-target-news at 100 rows/page regardless of a higher
# requested `limit` (confirmed live) -- paginate until an empty page.
NEWS_PAGE_SIZE = 100


async def _fetch_all_news(ticker: str) -> list[dict]:
    rows: list[dict] = []
    page = 0
    while True:
        page_rows = await fmp_client.get_price_target_news(ticker, page=page, limit=NEWS_PAGE_SIZE)
        if not page_rows:
            break
        rows.extend(page_rows)
        page += 1
    return rows


async def _backfill_one_ticker(session: Session, ticker: str, dry_run: bool) -> int:
    """Returns the number of rows inserted (0 if the ticker has no usable
    news history, or is already fully covered by existing snapshot rows)."""
    news_rows = await _fetch_all_news(ticker)
    if not news_rows:
        return 0

    existing_dates = session.exec(
        select(PriceTargetSnapshot.snapshot_date).where(PriceTargetSnapshot.ticker == ticker)
    ).all()
    earliest_existing = min(existing_dates) if existing_dates else None

    reconstructed = reconstruct_monthly_snapshots(news_rows, before=earliest_existing)
    if not reconstructed or dry_run:
        return len(reconstructed)

    now = datetime.now()
    for row in reconstructed:
        session.add(
            PriceTargetSnapshot(
                ticker=ticker,
                snapshot_date=row["snapshot_date"],
                target_consensus=row["target_consensus"],
                target_high=row["target_high"],
                target_low=row["target_low"],
                target_median=row["target_median"],
                fetched_at=now,
            )
        )
    session.commit()
    return len(reconstructed)


async def main(tickers: list[str] | None = None, dry_run: bool = False) -> dict:
    """`tickers=None` means "use the full tracked universe" -- passing an
    explicit list (used by the CLI's --limit/--tickers and by tests)
    bypasses the DB lookup entirely. Returns the run summary dict."""
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    if tickers is None:
        with Session(engine) as session:
            tickers = load_full_tracked_universe(session)

    if not tickers:
        logger.error("No tickers to process -- run refresh_sp500_list.py/refresh_dow_list.py first, or pass an explicit ticker list.")
        return {"processed": 0, "failed": 0, "inserted": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": []}

    fmp_client.min_request_interval = 60.0 / TARGET_REQUESTS_PER_MINUTE
    logger.info(
        "Starting price-target-snapshot backfill for %d tickers (pacing %.3fs/request, target %d req/min).%s",
        len(tickers),
        fmp_client.min_request_interval,
        TARGET_REQUESTS_PER_MINUTE,
        " (dry run -- nothing will be written)" if dry_run else "",
    )

    start_time = time.monotonic()
    start_request_count = fmp_client.request_count
    failures: list[tuple[str, str]] = []
    total_inserted = 0

    with Session(engine) as session:
        for i, ticker in enumerate(tickers, start=1):
            try:
                inserted = await _backfill_one_ticker(session, ticker, dry_run)
                total_inserted += inserted
                logger.info("[%d/%d] %s: %d month(s) %s", i, len(tickers), ticker, inserted, "would be inserted" if dry_run else "inserted")
            except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
                logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
                failures.append((ticker, str(exc)))

    duration = time.monotonic() - start_time
    calls_made = fmp_client.request_count - start_request_count

    logger.info(
        "Backfill complete. Processed: %d. Failed: %d. Rows inserted: %d. FMP calls made: %d. Duration: %.1fs (%.1f min).%s",
        len(tickers),
        len(failures),
        total_inserted,
        calls_made,
        duration,
        duration / 60,
        " (dry run -- nothing written)" if dry_run else "",
    )
    if failures:
        logger.info("Tickers with failures: %s", ", ".join(f"{t} ({e})" for t, e in failures))

    return {
        "processed": len(tickers),
        "failed": len(failures),
        "inserted": total_inserted,
        "calls_made": calls_made,
        "duration_seconds": duration,
        "failures": failures,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-time backfill of PriceTargetSnapshot from /price-target-news.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N stored tickers (for testing).")
    parser.add_argument(
        "--tickers", type=str, default=None, help="Comma-separated explicit ticker list, overrides the stored list (for testing)."
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute and log without writing to the database.")
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
    asyncio.run(main(_resolve_cli_tickers(cli_args), dry_run=cli_args.dry_run))
