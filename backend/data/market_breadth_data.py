"""Orchestration layer for the market-breadth signal -- % of S&P 500
constituents above their 50/200-day SMA and net new 52-week highs. Same
shape as data/sector_heatmap_data.py: resolve the anchor session, run the
pure math (scoring/market_breadth.py), gate on coverage, persist
(models.py::MarketBreadthSnapshot), and a read path that never computes
live. Independent of FMP and of Step 1-5/Overall Assessment scoring --
zero FMP calls, no FMP_ENABLED guard needed.

Bars come from SharedBarsCache via clients.shared_bars_cache.
get_or_fetch_bars_batch with the SAME call the 3:10 trend job makes
(1d, 730 days, auto_adjust=False), so a run after it is a warm-cache read
with zero incremental Yahoo requests; if the trend job failed or overran
this self-heals with one live fetch and writes through the shared cache
like any other consumer. Every metric is computed from those raw bars
directly, not from TrendAnalysis (latest-only, no 52-week fields, and a
failed fetch leaves an old row behind).

**Coverage gate.** Breadth is a ratio, so a partial Yahoo response would
still produce plausible-looking percentages over the survivors. A run whose
anchor session has bars for fewer than MIN_COVERAGE of the constituents
raises rather than saving a skewed row -- cron_heartbeat then records a
failed run, the same "raise only when the output can't be trusted" contract
nightly_sector_heatmap uses for total failure. Below the gate nothing is
written, so an older date stays the latest one and the page's own as-of
date shows the job has fallen behind. At or above it, `stale_excluded`
records the tickers that were dropped from every count."""

import logging
from datetime import date, datetime

import pandas as pd
from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from clients.shared_bars_cache import DAILY_INTERVAL, _most_recent_completed_trading_date, get_or_fetch_bars_batch
from core.db import engine
from core.models import MarketBreadthSnapshot
from scoring.market_breadth import aggregate_flags, snapshot_frame, ticker_flags

logger = logging.getLogger(__name__)

UNIVERSE = "sp500"  # the same name IndexConstituent.index_name uses

# Same call the trend job makes, so this reads the cache it just warmed. 730
# days is the "2y" yfinance tier; "1y" would return 251 bars, one short of a
# 252-session window.
FETCH_LOOKBACK_DAYS = 730

# Fraction of constituents that must have a bar on the anchor session for a
# row to be saved. 0.97 tolerates 15 missing of 503 (488/503 = 97.02%).
MIN_COVERAGE = 0.97

# How many missing tickers an error/summary names -- enough to see a pattern
# (a renamed symbol vs. a wholesale Yahoo failure) without a 500-name message.
MISSING_SAMPLE = 25

_STORED_COLUMNS = (
    "computed_at",
    "constituents",
    "stale_excluded",
    "sma50_eligible",
    "sma50_above",
    "pct_above_sma50",
    "sma200_eligible",
    "sma200_above",
    "pct_above_sma200",
    "hl_eligible",
    "new_highs",
    "new_lows",
    "net_new_highs",
    "is_backfilled",
)


class InsufficientCoverageError(RuntimeError):
    """The anchor session has bars for too few constituents to trust."""


def coverage_ok(with_bar: int, constituents: int) -> bool:
    return constituents > 0 and with_bar / constituents >= MIN_COVERAGE


def _resolve_anchor(session_dates: pd.DatetimeIndex, completed_date: date) -> pd.Timestamp | None:
    """The latest session, across every fetched ticker, that is not after
    the last COMPLETED session -- the sector heatmap's rule: taking it from
    the data makes a market holiday anchor to the real last trading day, and
    the `<=` cap drops the in-progress bar yfinance returns during market
    hours (its "close" would be a live price)."""
    eligible = session_dates[session_dates <= pd.Timestamp(completed_date)]
    return eligible.max() if len(eligible) else None


def _row_values(snapshot: pd.Series, as_of: pd.Timestamp, computed_at: datetime, is_backfilled: bool) -> dict:
    """One snapshot_frame row as plain-Python column values (numpy scalars
    cannot be bound by sqlite3; a NaN percentage becomes NULL)."""

    def pct(name: str) -> float | None:
        value = snapshot[name]
        return None if pd.isna(value) else float(value)

    return {
        "universe": UNIVERSE,
        "as_of_date": as_of.date(),
        "computed_at": computed_at,
        "constituents": int(snapshot["constituents"]),
        "stale_excluded": int(snapshot["stale_excluded"]),
        "sma50_eligible": int(snapshot["sma50_eligible"]),
        "sma50_above": int(snapshot["sma50_above"]),
        "pct_above_sma50": pct("pct_above_sma50"),
        "sma200_eligible": int(snapshot["sma200_eligible"]),
        "sma200_above": int(snapshot["sma200_above"]),
        "pct_above_sma200": pct("pct_above_sma200"),
        "hl_eligible": int(snapshot["hl_eligible"]),
        "new_highs": int(snapshot["new_highs"]),
        "new_lows": int(snapshot["new_lows"]),
        "net_new_highs": int(snapshot["net_new_highs"]),
        "is_backfilled": is_backfilled,
    }


def store_snapshots(values: list[dict], overwrite: bool) -> int:
    """Upserts snapshot rows. overwrite=True (the nightly job) replaces any
    existing row for the same (universe, as_of_date) -- including a
    backfilled one, since a live row is point-in-time -- so a weekend/holiday
    re-run of the same anchor is idempotent. overwrite=False (the backfill)
    inserts only missing dates and never touches an existing row, so a
    backfill re-run can never clobber a live row. Returns the number of NEW
    rows inserted (an overwritten row counts 0) -- taken as a before/after row
    count, since an executemany upsert has no reliable rowcount."""
    if not values:
        return 0
    with Session(engine) as session:
        before = session.exec(select(func.count()).select_from(MarketBreadthSnapshot)).one()
        stmt = sqlite_insert(MarketBreadthSnapshot)
        if overwrite:
            stmt = stmt.on_conflict_do_update(
                index_elements=["universe", "as_of_date"],
                set_={c: getattr(stmt.excluded, c) for c in _STORED_COLUMNS},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=["universe", "as_of_date"])
        session.execute(stmt, values)
        session.commit()
        return session.exec(select(func.count()).select_from(MarketBreadthSnapshot)).one() - before


async def compute_and_store_market_breadth(tickers: list[str], completed_date: date | None = None) -> dict:
    """Computes the latest completed session's breadth row for `tickers`
    (the caller resolves the universe -- pipeline/nightly_market_breadth.py
    passes load_sp500_tickers) and upserts it. `completed_date` (default:
    derived from the clock) is a testing/manual-run seam.

    Raises RuntimeError when there are no tickers or no bars at all, and
    InsufficientCoverageError when fewer than MIN_COVERAGE of the tickers
    have a bar on the anchor session -- in both cases nothing is written."""
    if not tickers:
        raise RuntimeError("Market breadth: empty universe -- run scrapers.refresh_sp500_list first")
    completed = completed_date or _most_recent_completed_trading_date()

    bars = await get_or_fetch_bars_batch(tickers, DAILY_INTERVAL, FETCH_LOOKBACK_DAYS, auto_adjust=False)
    flags = ticker_flags(bars)
    counts = aggregate_flags(flags)

    anchor = _resolve_anchor(counts.index, completed) if len(counts) else None
    if anchor is None:
        raise RuntimeError(f"Market breadth: no usable bars for any of {len(tickers)} tickers on/before {completed}")

    missing = sorted(t for t in tickers if t not in flags or anchor not in flags[t].index)
    with_bar = len(tickers) - len(missing)
    if not coverage_ok(with_bar, len(tickers)):
        raise InsufficientCoverageError(
            f"Market breadth: only {with_bar}/{len(tickers)} constituents ({with_bar / len(tickers):.1%}) have a bar on "
            f"{anchor.date()}, below the {MIN_COVERAGE:.0%} coverage gate -- not saving a skewed row. "
            f"Missing: {missing[:MISSING_SAMPLE]}{' ...' if len(missing) > MISSING_SAMPLE else ''}"
        )

    snapshot = snapshot_frame(counts.loc[[anchor]], len(tickers)).iloc[0]
    values = _row_values(snapshot, anchor, datetime.now(), is_backfilled=False)
    store_snapshots([values], overwrite=True)

    if missing:
        logger.warning("Market breadth: %d constituent(s) had no bar on %s and were excluded: %s", len(missing), anchor.date(), missing)
    summary = {
        "as_of_date": anchor.date().isoformat(),
        "constituents": len(tickers),
        "with_bar": with_bar,
        "stale_excluded": len(missing),
        "missing": missing[:MISSING_SAMPLE],
        "pct_above_sma50": values["pct_above_sma50"],
        "pct_above_sma200": values["pct_above_sma200"],
        "new_highs": values["new_highs"],
        "new_lows": values["new_lows"],
        "net_new_highs": values["net_new_highs"],
    }
    logger.info(
        "Market breadth complete for %s: %d/%d constituents, %%>SMA50 %s, %%>SMA200 %s, net new highs %d.",
        anchor.date(), with_bar, len(tickers),
        None if values["pct_above_sma50"] is None else round(values["pct_above_sma50"], 1),
        None if values["pct_above_sma200"] is None else round(values["pct_above_sma200"], 1),
        values["net_new_highs"],
    )
    return summary
