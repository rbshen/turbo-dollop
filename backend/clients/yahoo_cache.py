"""Bespoke get-or-fetch-style caching for YahooPriceCache (Price/Quote's Yahoo
fallback only, as of 2026-09-19 -- see get_or_fetch_price_history's own
docstring; every other Yahoo bars consumer moved to
clients/shared_bars_cache.py) -- deliberately
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


async def get_or_fetch_price_history(ticker: str, period: str = "2y", cache_only: bool = False) -> list[YahooPriceCache]:
    """Cache-first read of a ticker's daily OHLCV history: returns the
    cached rows if fresh (per Settings.yahoo_price_cache_staleness_days),
    else fetches live via yahoo_client and upserts -- mirrors
    core/cache.py::get_or_fetch's staleness-check-then-fetch-then-upsert
    shape without reusing its FundamentalsCache-specific internals.
    cache_only=True never calls Yahoo live, returning whatever's cached even
    if stale (same convention as core/cache.py's own cache_only branch).

    **Sole remaining consumer: data/ticker_summary.py::
    _fetch_yahoo_latest_close** (Price/Quote's Yahoo fallback, which reads
    only the single most recent row's close). Trend/Weinstein Stage and
    Liquidity Zones moved to clients/shared_bars_cache.py (2026-09-19),
    which is also why this function no longer takes an auto_adjust
    parameter or has a batch variant: nothing left here needs either, and
    the adjusted-vs-unadjusted shared-row caveat that used to apply to this
    table (Trend writing raw bars where Price/Quote expected adjusted ones)
    is gone with those consumers -- this table is now only written (going forward)
    with yahoo_client's own default (auto_adjust=True) bars."""
    with Session(engine) as session:
        rows = _load_cached_rows(session, ticker)
        if not _is_stale(rows) or cache_only:
            return rows

        fetched = await yahoo_client.get_history([ticker], period=period)
        df = fetched.get(ticker)
        if df is None or df.empty:
            # Live fetch failed or returned nothing -- fall back to whatever's
            # cached, even if stale, same "stale is better than nothing"
            # semantics as core/cache.py's own fetch-failure handling.
            return rows

        _write_rows(session, ticker, df, datetime.now())
        return _load_cached_rows(session, ticker)
