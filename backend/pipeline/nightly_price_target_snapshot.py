"""Standalone script: DAILY price-target-consensus snapshot for every
US-listed ticker the app tracks (see load_us_price_target_universe below).
Widened on 2026-09-25 from the S&P 500 + Dow constituent lists.

(Renamed from monthly_price_target_snapshot on 2026-09-27, when it went from
monthly to daily; older CronRunLog rows keep the old job name.)

FMP's own /price-target-consensus is a live-only value with no historical
series attached to it, so this script keeps accumulating one
PriceTargetSnapshot row per ticker per day, going forward. (The older history
was one-time-reconstructed from /price-target-news by
pipeline/backfills/backfill_price_target_snapshots.py using a different,
all-analysts methodology -- see PriceTargetSnapshot.methodology.) Every row
written here is tagged `live_consensus`.

The fetch goes through cache.get_or_fetch (`price_target_consensus`/`latest`,
1-day staleness), the same cache row the Analyst Ratings tab reads, so the
job and tab views share one fetch. The snapshot table itself still keeps
every past day: a re-run on the same (ticker, snapshot_date) updates that
day's row instead of duplicating it (unique index on the pair).

Default schedule: 2:10am server time daily (see crontab.txt in this
directory), after nightly_fundamentals_fetch and before the 3:10 trend job.

Run manually against the full US universe:
    uv run python -m pipeline.nightly_price_target_snapshot

Run against a small subset first:
    uv run python -m pipeline.nightly_price_target_snapshot --limit 15
    uv run python -m pipeline.nightly_price_target_snapshot --tickers AAPL,MSFT,ZZZZINVALID
"""

import argparse
import asyncio
import logging
import time
from datetime import date, datetime
from pathlib import Path

from sqlmodel import Session, select

from core.data_groups import job_skip_reason
from core.cron_health import cron_heartbeat
from core.cache import get_or_fetch
from core.db import engine, init_db
from helpers.first import _first
from clients.fmp_client import fmp_client
from core.logging_config import configure_logging
from core.models import PriceTargetSnapshot
from clients.daily_bar_sources import _profile_exchanges
from core.tickers import is_us_listed, normalize_ticker
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe
from pipeline.stale_data_health_check import load_delisted_tickers

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_price_target_snapshot.log"

# Same empirically-derived pacing as nightly_fundamentals_fetch.py -- see
# that module's comment for the underlying rate-limit investigation.
TARGET_REQUESTS_PER_MINUTE = 220


def load_us_price_target_universe(session: Session) -> list[str]:
    """The full tracked universe (`load_full_tracked_universe`: index + ever-viewed
    + scored + watchlisted) narrowed to US-LISTED tickers -- listing exchange off
    the cached FMP profile via `core.tickers.is_us_listed`, the same rule that
    routes daily bars, not domicile (TSM/BABA count, HKSE names don't) -- minus
    tickers flagged delisted, which would only fail every night."""
    tracked = load_full_tracked_universe(session)
    exchanges = _profile_exchanges(tracked)
    delisted = load_delisted_tickers(session)
    return [t for t in tracked if t not in delisted and is_us_listed(t, exchanges.get(t))]


LIVE_METHODOLOGY = "live_consensus"

# 1 day, not settings.cache_staleness_days: this is a daily reading.
PRICE_TARGET_STALENESS_DAYS = 1


async def _snapshot_one_ticker(session: Session, ticker: str, snapshot_date: date) -> None:
    data = await get_or_fetch(
        session,
        ticker,
        "price_target_consensus",
        "latest",
        lambda: fmp_client.get_price_target_consensus(ticker),
        PRICE_TARGET_STALENESS_DAYS,
    )
    raw = _first(data)
    if not raw:
        # Group went off mid-run with nothing cached, or FMP returned an empty
        # body: nothing to record. Raising keeps it in the failure count
        # rather than writing an all-null row.
        raise ValueError("no price-target consensus available")
    values = dict(
        target_consensus=raw.get("targetConsensus"),
        target_high=raw.get("targetHigh"),
        target_low=raw.get("targetLow"),
        target_median=raw.get("targetMedian"),
        fetched_at=datetime.now(),
        methodology=LIVE_METHODOLOGY,
    )
    existing = session.exec(
        select(PriceTargetSnapshot).where(PriceTargetSnapshot.ticker == ticker, PriceTargetSnapshot.snapshot_date == snapshot_date)
    ).first()
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
    else:
        session.add(PriceTargetSnapshot(ticker=ticker, snapshot_date=snapshot_date, **values))
    session.commit()


async def main(tickers: list[str] | None = None) -> dict:
    """`tickers=None` means "use the full US-listed tracked universe" --
    passing an explicit list (used by the CLI's --limit/--tickers and by
    tests) bypasses the DB lookup entirely. Returns the run summary dict so
    tests can assert on it directly rather than scraping the log."""
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    skip_reason = job_skip_reason("analyst_ratings")
    if skip_reason:
        # Check first, before resolving the ticker universe. get_or_fetch
        # itself degrades to cache-only when the group is off, which would
        # "succeed" while writing stale values under today's date -- so a
        # gated run must not fetch at all. `skipped: True` lets __main__
        # record CronRunLog status "skipped" instead of "success".
        logger.info("Daily price-target snapshot %s.", skip_reason)
        return {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": [], "skipped": True, "skip_reason": skip_reason}

    if tickers is None:
        with Session(engine) as session:
            tickers = load_us_price_target_universe(session)

    if not tickers:
        logger.error("No tickers to process -- no tracked US-listed tickers -- pass an explicit ticker list.")
        return {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": []}

    fmp_client.min_request_interval = 60.0 / TARGET_REQUESTS_PER_MINUTE
    logger.info(
        "Starting daily price-target snapshot for %d tickers (pacing %.3fs/request, target %d req/min).",
        len(tickers),
        fmp_client.min_request_interval,
        TARGET_REQUESTS_PER_MINUTE,
    )

    snapshot_date = date.today()
    start_time = time.monotonic()
    start_request_count = fmp_client.request_count
    failures: list[tuple[str, str]] = []

    with Session(engine) as session:
        for i, ticker in enumerate(tickers, start=1):
            try:
                await _snapshot_one_ticker(session, ticker, snapshot_date)
                logger.info("[%d/%d] %s: ok", i, len(tickers), ticker)
            except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
                logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
                failures.append((ticker, str(exc)))

    duration = time.monotonic() - start_time
    calls_made = fmp_client.request_count - start_request_count

    logger.info(
        "Daily snapshot complete. Processed: %d. Failed: %d. FMP calls made: %d. Duration: %.1fs (%.1f min).",
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
    parser = argparse.ArgumentParser(description="Daily price-target-consensus snapshot.")
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
            all_tickers = load_us_price_target_universe(session)
        return all_tickers[: args.limit]
    return None


def record_outcome(result: dict, run) -> None:
    """Map a main() summary onto the heartbeat: a gated run is "skipped", a run
    where every ticker failed raises (heartbeat "failure"), anything else is a
    "success" with a short written/failed message."""
    if result.get("skipped"):
        run.skip(result["skip_reason"])
    elif result["processed"] and result["failed"] == result["processed"]:
        # FMP down, key revoked, group flipped off mid-run: nothing was
        # written, so this must not read "success".
        raise RuntimeError(f"price-target snapshot wrote nothing: all {result['failed']} tickers failed")
    else:
        run.message = f"{result['processed'] - result['failed']} written, {result['failed']} failed"


if __name__ == "__main__":
    cli_args = _parse_args()
    with cron_heartbeat("pipeline.nightly_price_target_snapshot") as run:
        record_outcome(asyncio.run(main(_resolve_cli_tickers(cli_args))), run)
