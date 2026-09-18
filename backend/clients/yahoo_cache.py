"""Bespoke get-or-fetch-style caching for YahooPriceCache -- deliberately
separate from core/cache.py, which is hard-wired to FundamentalsCache's
(ticker, statement_type, period) + raw_json-blob shape (see
core/models.py::YahooPriceCache's own docstring for why this needed its own
table and, by extension, its own small set of helpers rather than reuse).
No FMP_ENABLED-style kill-switch check anywhere here -- see
clients/yahoo_client.py's docstring for why none is needed.
"""

from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from clients.yahoo_client import yahoo_client
from core.config import settings
from core.db import engine
from core.models import YahooPriceCache


def _load_cached_rows(session: Session, ticker: str) -> list[YahooPriceCache]:
    return list(
        session.exec(select(YahooPriceCache).where(YahooPriceCache.ticker == ticker).order_by(YahooPriceCache.date)).all()
    )


def _is_stale(rows: list[YahooPriceCache]) -> bool:
    if not rows:
        return True
    latest_fetched_at = max(row.fetched_at for row in rows)
    return datetime.now() - latest_fetched_at >= timedelta(days=settings.yahoo_price_cache_staleness_days)


def _write_rows(session: Session, ticker: str, df: pd.DataFrame, fetched_at: datetime) -> None:
    for row_date, row in df.iterrows():
        bar_date = row_date.date() if hasattr(row_date, "date") else row_date
        open_ = float(row["Open"])
        high = float(row["High"])
        low = float(row["Low"])
        close = float(row["Close"])
        volume = int(row["Volume"]) if not pd.isna(row["Volume"]) else 0
        stmt = sqlite_insert(YahooPriceCache).values(
            ticker=ticker,
            date=bar_date,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            fetched_at=fetched_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "date"],
            set_={"open": open_, "high": high, "low": low, "close": close, "volume": volume, "fetched_at": fetched_at},
        )
        session.execute(stmt)
    session.commit()


async def get_or_fetch_price_history(
    ticker: str, period: str = "2y", cache_only: bool = False, auto_adjust: bool = True
) -> list[YahooPriceCache]:
    """Cache-first read of a ticker's daily OHLCV history: returns the
    cached rows if fresh (per Settings.yahoo_price_cache_staleness_days),
    else fetches live via yahoo_client and upserts -- mirrors
    core/cache.py::get_or_fetch's staleness-check-then-fetch-then-upsert
    shape without reusing its FundamentalsCache-specific internals.
    cache_only=True never calls Yahoo live, returning whatever's cached even
    if stale (same convention as core/cache.py's own cache_only branch).

    auto_adjust defaults to True, matching this table's original consumer
    (data/ticker_summary.py::_fetch_yahoo_latest_close, the Price/Quote
    Yahoo fallback -- left unchanged by the 2026-09-18 Yahoo-consolidation
    work). data/trend_analysis_data.py passes auto_adjust=False explicitly,
    since Trend/Weinstein Stage now want raw (non-dividend-adjusted) bars.
    Both share this one YahooPriceCache table keyed only on (ticker, date)
    -- adding an `adjusted` column to that key isn't possible without a
    real table-recreate migration this app has no tooling for (see
    core/models.py::WarrenSignalEvent's own comment on why that class of
    problem gets a new table instead) -- so whichever caller fetches a
    given (ticker, date) row LAST determines what's stored there, and an
    already-fresh cache is served as-is regardless of which auto_adjust
    the caller that populated it used. This is safe in practice only
    because ticker_summary's own read never looks past the single most
    recent row's close, and an adjusted vs. unadjusted close are always
    identical for the CURRENT/latest bar (adjustment only ever rescales
    OLDER bars retroactively, for a corporate action that happened after
    them) -- confirmed empirically for O/UNH/F. Older rows in this table
    reflect whichever caller fetched them last; nothing currently reads
    those older rows from the adjusted side, so this doesn't matter today,
    but a future adjusted-side consumer of anything but the latest row
    would need its own storage, not this shared table."""
    with Session(engine) as session:
        rows = _load_cached_rows(session, ticker)
        if not _is_stale(rows) or cache_only:
            return rows

        fetched = await yahoo_client.get_history([ticker], period=period, auto_adjust=auto_adjust)
        df = fetched.get(ticker)
        if df is None or df.empty:
            # Live fetch failed or returned nothing -- fall back to whatever's
            # cached, even if stale, same "stale is better than nothing"
            # semantics as core/cache.py's own fetch-failure handling.
            return rows

        _write_rows(session, ticker, df, datetime.now())
        return _load_cached_rows(session, ticker)


async def get_or_fetch_price_history_batch(
    tickers: list[str], period: str = "2y", auto_adjust: bool = True, force: bool = False
) -> dict[str, list[YahooPriceCache]]:
    """Batch variant for the nightly job -- one yfinance multi-ticker
    download covering every ticker whose cache is stale, rather than N
    individual live fetches. A ticker with an already-fresh cache is
    skipped entirely (no Yahoo call for it at all). See
    get_or_fetch_price_history's own docstring for auto_adjust's meaning
    and the shared-table caveat -- pipeline/nightly_trend_calculation.py
    passes auto_adjust=False here.

    force=True always live-fetches every requested ticker, ignoring
    _is_stale entirely -- clients/daily_price_sources.py::get_daily_bars
    (Liquidity Zones) passes this, since this cache's staleness check is
    purely time-based (was ANY row for this ticker refreshed recently?),
    not coverage-based (does the cache actually hold as much history as
    THIS caller asked for?). Liquidity Zones and Trend/Weinstein
    (pipeline/nightly_trend_calculation.py) now both read through this one
    shared table, 15 minutes apart in cron (Trend 3:10am, Liquidity Zones
    3:25am) -- confirmed every Liquidity Zone ticker is already unioned
    into Trend's own full-tracked-universe fetch (see
    pipeline/nightly_fundamentals_fetch.py::load_full_tracked_universe's
    own "any ticker on any Watchlist" clause), so without `force`, Trend's
    own period="2y" fetch would leave every overlapping ticker's cache
    "fresh" by the time Liquidity Zones' job runs -- silently serving it
    ~2 years of history instead of the ~5 it actually requested, truncating
    its Weekly (4yr) timeframe every single night. This didn't exist before
    2026-09-18: Liquidity Zones previously read this shared table only in
    the rare FMP-disabled fallback state, not on every run. `force=True` is
    cheap here specifically because Liquidity Zones' own population (the
    W1-W5 watchlist union, capped at 500 tickers total) is small enough
    that a guaranteed-live nightly batch fetch costs nothing extra worth
    caching around -- Trend's own much larger (full-universe) fetch keeps
    its normal staleness-gated behavior unchanged."""
    with Session(engine) as session:
        stale_tickers = tickers if force else [t for t in tickers if _is_stale(_load_cached_rows(session, t))]

    if stale_tickers:
        fetched = await yahoo_client.get_history(stale_tickers, period=period, auto_adjust=auto_adjust)
        now = datetime.now()
        with Session(engine) as session:
            for ticker, df in fetched.items():
                if df is not None and not df.empty:
                    _write_rows(session, ticker, df, now)

    with Session(engine) as session:
        return {ticker: _load_cached_rows(session, ticker) for ticker in tickers}
