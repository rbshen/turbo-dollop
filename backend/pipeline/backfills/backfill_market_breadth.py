"""One-time standalone script: seed MarketBreadthSnapshot with ~1 year of
history from the daily bars SharedBarsCache ALREADY holds -- no Yahoo fetch
at all. Kept out of pipeline/nightly_market_breadth.py on purpose: the
nightly job's fetch width must not grow to serve a backfill.

**Read-only against SharedBarsCache.** Fetching a deeper history through
get_or_fetch_bars_batch would widen the shared cache (409 tickers from 2y
to 5y), and its "grow to the widest window ever requested" logic would then
make every later nightly refetch pull the wider window for them --
roughly +300k rows and a longer nightly download, permanently. This script
reads what is stored (data.market_breadth_data.load_cached_daily_bars) and
never writes to that table.

**Which sessions get a row.** Computed from each ticker's own bars over
every session the cache supports, then kept only where >= 97% of the
constituents have a bar AND >= 97% are eligible for the 52-week window (252
own bars -- the hardest requirement, so it implies SMA20/SMA50/SMA200
eligibility). Earlier sessions would be a subset of the index rather than
the index, and a curve stitched across that boundary is misleading. With
the cache's usual ~2y depth that yields roughly the last year (first
kept session ~one 252-bar window after the oldest common bar).

**SURVIVORSHIP-BIASED.** Every backfilled session is computed over TODAY's
S&P 500 constituents (as of the last weekly index scrape), not the index as
it was on that date: a name that joined recently (e.g. RDDT, 2026-08-18) is
counted in earlier months, and a name that was removed is missing
entirely -- removals aren't tracked anywhere. Breadth over a
survivor-only universe reads systematically better in the past than the
real index did. Live nightly rows are point-in-time by construction; rows
written here carry is_backfilled=True so the two stay distinguishable, and
the frontend marks the boundary.

**Never overwrites.** Rows are inserted only where (universe, as_of_date)
does not already exist (on_conflict_do_nothing), so a re-run is a no-op
and can never replace a live nightly row; a later nightly run for the same
date replaces the backfilled one (see store_snapshots).

**The 20-day columns (added 2026-09-21) are filled onto existing rows.** The
insert above skips a date that already has a row, so the ~250 rows written
before the 20-day metric existed would never gain it. A second pass
(data.market_breadth_data.fill_missing_sma20) writes ONLY the three sma20
columns, ONLY where they are still NULL, ONLY on is_backfilled rows -- every
other column and every live row stays untouched, and a re-run fills nothing.

**Also backfills one row per GICS/SPDR sector (2026-09-22)** -- same
read-only SharedBarsCache reuse (the SAME `bars` this script already loads
for the sp500 pass is sliced per sector, no second read), same
never-overwrites-a-live-row insert-only convention, via
data.market_breadth_data.build_sector_backfill_rows/load_sector_buckets. No
sma20-fill pass is needed for these -- they're brand-new rows created after
the 20-day metric already existed, so they can never be missing it.

Run (previews the row count/date range, writes nothing):
    uv run python -m pipeline.backfills.backfill_market_breadth --dry-run

Run for real:
    uv run python -m pipeline.backfills.backfill_market_breadth
"""

import argparse
import logging
import time
from pathlib import Path

from sqlmodel import Session

from clients.shared_bars_cache import _most_recent_completed_trading_date
from core.db import engine, init_db
from core.logging_config import configure_logging
from data.market_breadth_data import (
    build_backfill_rows,
    build_sector_backfill_rows,
    fill_missing_sma20,
    load_cached_daily_bars,
    load_sector_buckets,
    store_snapshots,
)
from pipeline.nightly_fundamentals_fetch import load_sp500_tickers

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "backfill_market_breadth.log"

logger = logging.getLogger(__name__)


def main(dry_run: bool = False) -> dict:
    """Returns a summary dict so tests/manual runs can assert on it directly."""
    configure_logging(LOG_PATH)
    init_db()

    with Session(engine) as session:
        tickers = load_sp500_tickers(session)
        sector_tickers = load_sector_buckets(session)
    if not tickers:
        raise RuntimeError("No S&P 500 constituents -- run scrapers.refresh_sp500_list first")

    start_time = time.monotonic()
    completed = _most_recent_completed_trading_date()
    bars = load_cached_daily_bars(tickers)
    missing = sorted(set(tickers) - set(bars))
    values, summary = build_backfill_rows(bars, len(tickers), completed)
    inserted = 0 if dry_run else store_snapshots(values, overwrite=False)
    # After the insert, so freshly inserted rows (which already carry sma20) are not "pending".
    sma20_pending = fill_missing_sma20(values, dry_run=True)
    sma20_filled = 0 if dry_run else fill_missing_sma20(values)

    # Sector rows -- reuses the SAME `bars` just loaded above, no second read.
    sector_values, sector_summary = build_sector_backfill_rows(bars, sector_tickers, completed)
    sector_inserted = 0 if dry_run else store_snapshots(sector_values, overwrite=False)

    summary.update(
        {
            "constituents": len(tickers),
            "tickers_with_cached_bars": len(bars),
            "tickers_without_cached_bars": missing,
            "inserted": inserted,
            "already_present": 0 if dry_run else len(values) - inserted,
            "sma20_pending": sma20_pending,
            "sma20_filled": sma20_filled,
            "sectors": sector_summary,
            "sector_inserted": sector_inserted,
            "sector_already_present": 0 if dry_run else len(sector_values) - sector_inserted,
            "dry_run": dry_run,
            "duration_seconds": time.monotonic() - start_time,
        }
    )
    logger.info(
        "Market breadth backfill%s: %d/%d tickers had cached bars; %d sessions seen, %d kept (%s .. %s); inserted %d, already present %d; sma20 columns needing a fill %d, filled %d. "
        "Sectors: %d rows inserted across %d sectors, %d already present. "
        "Survivorship-biased: today's constituents applied to past dates.",
        " (DRY RUN)" if dry_run else "", summary["tickers_with_cached_bars"], summary["constituents"], summary["sessions_seen"],
        summary["kept"], summary["first_date"], summary["last_date"], inserted, summary["already_present"],
        sma20_pending, sma20_filled, sector_inserted, len(sector_summary), summary["sector_already_present"],
    )
    if missing:
        logger.warning("Market breadth backfill: no cached daily bars for %d ticker(s): %s", len(missing), missing)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="compute and report, write nothing")
    args = parser.parse_args()
    print(main(dry_run=args.dry_run))
