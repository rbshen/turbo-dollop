"""Standalone script: nightly fundamentals refresh for every ticker in the
full tracked universe -- index constituents (S&P 500 + Dow, see
sp500_scraper.py / dow_scraper.py / IndexConstituent) UNION any ticker with
cached FMP data, an existing TickerScore row, or a Watchlist entry (the
2026-08-06 "index + ever-viewed + watchlisted" decision, see
load_full_tracked_universe below) -- via the app's existing cache-aware
fetch pipeline --
get_step1_data / get_step2_data / get_step4_data / get_step5_data /
get_summary / get_segmentation_data. Nothing bespoke here: these are the
exact same functions Step 1/2/4/5, the ticker header, and the Summary
tab's segmentation charts already call, each already going through
get_or_fetch's cache-freshness check internally. The first run against a
cold cache does a full fetch (~7,000 calls, ~30 min at the paced rate
below); every run after that is mostly cache hits, since get_or_fetch only
calls FMP for a ticker/statement whose cache has actually gone stale.

get_segmentation_data was added later (2026-08-03) than the other five --
before this, a ticker could be fully warm on Step 1/2/4/5/Summary and still
cold-fetch segmentation live the first time someone opened its Summary tab,
since nothing else in this pipeline ever populated that cache key. It has
no dependency on any other step's output, so its place in the sequence
below is arbitrary -- grouped with the other per-ticker fetches, ahead of
the cross-step get_summary/compute_ticker_score calls, purely for
readability.

After fetching each ticker's raw data, also computes and stores its
Screener row (ticker_score.compute_ticker_score) -- cache_only=True since
the data was just cached moments earlier in this exact function, so this
adds zero extra FMP calls. See recompute_ticker_scores.py for the separate
on-demand path that re-scores every ticker from already-cached data alone,
without running this full fetch first.

Default schedule: 2am server time, nightly (see crontab.txt in this
directory). To change the schedule, edit that one crontab line -- nothing
in this script needs touching for a schedule change.

Run manually against the full stored list:
    uv run python -m pipeline.nightly_fundamentals_fetch

Run against a small subset first (recommended before ever doing a first
full cold-cache run):
    uv run python -m pipeline.nightly_fundamentals_fetch --limit 15
    uv run python -m pipeline.nightly_fundamentals_fetch --tickers AAPL,MSFT,ZZZZINVALID
"""

import argparse
import asyncio
import logging
import time
from pathlib import Path

from sqlmodel import Session, select

from core.config import settings
from core.db import engine, init_db
from clients.fmp_client import fmp_client
from core.logging_config import configure_logging
from core.models import FundamentalsCache, IndexConstituent, TickerScore, WatchlistTicker
from core.tickers import normalize_ticker
from data.segmentation_data import get_segmentation_data
from data.step1_data import get_step1_data
from data.step2_data import get_step2_data
from data.step4_data import get_step4_data
from data.step5_data import get_step5_data
from data.ticker_score import compute_ticker_score
from data.ticker_summary import get_summary

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "nightly_fundamentals_fetch.log"

# Investigation found the empirical FMP rate limit sits around 300-600
# requests/minute on a rolling window (300 concurrent requests succeeded,
# but a further batch right after started drawing 429s). 220/min leaves
# real headroom under even the conservative end of that range.
TARGET_REQUESTS_PER_MINUTE = 220


def load_sp500_tickers(session: Session) -> list[str]:
    rows = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
    return [row.ticker for row in rows]


def load_dow_tickers(session: Session) -> list[str]:
    rows = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "dow")).all()
    return [row.ticker for row in rows]


def load_universe_tickers(session: Session) -> list[str]:
    """Union of every index this pipeline covers -- today all 30 Dow
    constituents also happen to be S&P 500 members, but that's not
    guaranteed to stay true, and a Dow-only ticker must still get fetched
    nightly (and get a TickerScore row) once the Screener can filter to a
    Dow universe. load_sp500_tickers itself stays untouched/sp500-only --
    other callers (bulk_refresh_step4_annual.py) depend on that exact
    scope."""
    return sorted(set(load_sp500_tickers(session)) | set(load_dow_tickers(session)))


def load_full_tracked_universe(session: Session) -> list[str]:
    """Union of every ticker this app tracks: index constituents (S&P 500 + Dow),
    any ticker with at least one cached FMP *profile* fetch, any ticker with a
    TickerScore row, and any ticker on any Watchlist -- the 2026-08-06 "index +
    ever-viewed + watchlisted" decision. Watchlisting a ticker doesn't itself
    trigger a fetch or score (see watchlists.py/watchlist_data.py), so Watchlist
    must be unioned explicitly rather than assumed to already be covered by the
    scored/cached sets.

    Deliberately filtered to statement_type=="profile" rather than every
    FundamentalsCache.ticker: this table also caches non-ticker lookups under a
    ticker-shaped key -- confirmed live via CADUSD/DKKUSD/EURUSD/TWDUSD, FX
    spot-rate rows Valuation's currency-conversion step caches under
    statement_type="forex_rate" (see CLAUDE.md's Valuation FX section). Unlike
    nightly_score_recompute.py's cache_only sweep (harmless either way -- scoring
    a currency pair just yields no TickerScore), this job makes live FMP calls
    per ticker, so an unfiltered union would burn a wasted get_profile("EURUSD")
    call every night, forever. "profile" is the same ground-truth signal
    purge_invalid_tickers.py already uses to recognize a real ticker lookup.

    Shared with nightly_score_recompute.py, which imports this rather than keeping
    its own copy -- the "ever-viewed" half of this decision landed there first
    (2026-08-09) without Watchlist, while this job never got either half; one
    definition keeps both jobs' universes from drifting apart again."""
    index_tickers = load_universe_tickers(session)
    cached_tickers = session.exec(
        select(FundamentalsCache.ticker).where(FundamentalsCache.statement_type == "profile").distinct()
    ).all()
    scored_tickers = session.exec(select(TickerScore.ticker)).all()
    watchlist_tickers = session.exec(select(WatchlistTicker.ticker).distinct()).all()
    return sorted(set(index_tickers) | set(cached_tickers) | set(scored_tickers) | set(watchlist_tickers))


async def _refresh_one_ticker(ticker: str) -> None:
    await get_step1_data(ticker)
    await get_step2_data(ticker)
    await get_step4_data(ticker)
    await get_step5_data(ticker)
    await get_segmentation_data(ticker)
    # live_quote=False (2026-08-16): this batch write gets superseded the
    # moment anyone actually views the ticker (which force-fetches quote
    # live independently), so force-fetching it here every night for the
    # whole tracked universe was pure waste -- confirmed the single largest,
    # most consistent contributor to nightly call volume of any endpoint
    # checked (essentially the full ~570-ticker universe, unconditionally,
    # every night). Falls back to the normal staleness-gated fetch instead.
    await get_summary(ticker, live_quote=False)
    await compute_ticker_score(ticker, cache_only=True)


async def main(tickers: list[str] | None = None) -> dict:
    """`tickers=None` means "use the full tracked universe" (index + ever-viewed +
    watchlisted, see load_full_tracked_universe) -- passing an explicit list (used
    by the CLI's --limit/--tickers and by tests) bypasses the DB lookup entirely.
    Returns the run summary dict so tests can assert on it directly rather than
    scraping the log."""
    configure_logging(LOG_PATH)
    logger = logging.getLogger(__name__)
    init_db()

    if not settings.fmp_enabled:
        # Check first thing, before even resolving the ticker universe --
        # every fetch this job makes is live (cache_only=False), so running
        # it while FMP is paused would just loop the full universe
        # attempting-then-catching a failure per statement per ticker for
        # no benefit. nightly_score_recompute.py needs no equivalent check;
        # it's already cache_only=True throughout, zero FMP calls.
        logger.info("Nightly fundamentals fetch skipped: FMP paused (FMP_ENABLED=False).")
        return {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": [], "skipped": True}

    if tickers is None:
        with Session(engine) as session:
            tickers = load_full_tracked_universe(session)

    if not tickers:
        logger.error("No tickers to process -- run refresh_sp500_list.py/refresh_dow_list.py first, or pass an explicit ticker list.")
        return {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": []}

    fmp_client.min_request_interval = 60.0 / TARGET_REQUESTS_PER_MINUTE
    logger.info(
        "Starting nightly fundamentals fetch for %d tickers (pacing %.3fs/request, target %d req/min).",
        len(tickers),
        fmp_client.min_request_interval,
        TARGET_REQUESTS_PER_MINUTE,
    )

    start_time = time.monotonic()
    start_request_count = fmp_client.request_count
    failures: list[tuple[str, str]] = []

    for i, ticker in enumerate(tickers, start=1):
        try:
            await _refresh_one_ticker(ticker)
            logger.info("[%d/%d] %s: ok", i, len(tickers), ticker)
        except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
            logger.error("[%d/%d] %s: FAILED - %s", i, len(tickers), ticker, exc)
            failures.append((ticker, str(exc)))

    duration = time.monotonic() - start_time
    calls_made = fmp_client.request_count - start_request_count

    logger.info(
        "Nightly fetch complete. Processed: %d. Failed: %d. FMP calls made: %d. Duration: %.1fs (%.1f min).",
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
    parser = argparse.ArgumentParser(description="Nightly S&P 500 fundamentals refresh.")
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
            all_tickers = load_full_tracked_universe(session)
        return all_tickers[: args.limit]
    return None


if __name__ == "__main__":
    cli_args = _parse_args()
    asyncio.run(main(_resolve_cli_tickers(cli_args)))
