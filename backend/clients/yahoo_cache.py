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

from datetime import datetime, time, timedelta, timezone

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from clients.shared_bars_cache import (
    _EASTERN,
    _MARKET_CLOSE_HOUR_ET,
    _MARKET_OPEN_ET,
    _most_recent_completed_trading_date,
)
from clients.yahoo_client import yahoo_client
from core.config import settings
from core.db import engine
from core.models import YahooPriceCache

# How long after the 4pm ET close a fetch has to land before its last bar
# counts as the final close: the closing auction prints just after 16:00, so
# a fetch in the first minutes can still hold the last pre-auction trade. A
# conservative allowance, not a measured Yahoo figure.
_CLOSE_SETTLE = timedelta(minutes=10)


def _load_cached_rows(session: Session, ticker: str) -> list[YahooPriceCache]:
    return list(
        session.exec(select(YahooPriceCache).where(YahooPriceCache.ticker == ticker).order_by(YahooPriceCache.date)).all()
    )


def _session_is_open(now: datetime) -> bool:
    eastern = now.astimezone(_EASTERN)
    return eastern.weekday() < 5 and _MARKET_OPEN_ET <= eastern.time() < time(_MARKET_CLOSE_HOUR_ET)


def _is_stale(rows: list[YahooPriceCache], reference: datetime | None = None) -> bool:
    """Whether the newest cached fetch can still be served as the price.
    The row this feeds is a QUOTE (only the latest bar's close is read), and
    Yahoo's latest daily bar is the live last trade while the session is
    open and only becomes the final close afterwards -- so a flat TTL is
    wrong both ways:

    - session open (weekday 9:30-16:00 ET): the price moves continuously,
      so a fetch is fresh only for yahoo_quote_intraday_ttl_seconds (the
      FMP path this stands in for re-fetches on every page view; the short
      TTL just stops a refresh loop from hammering Yahoo).
    - session closed: nothing newer can exist until the next open, so a
      fetch is fresh iff it landed after the most recent session's close
      (plus _CLOSE_SETTLE). A fetch taken mid-session holds a partial bar
      and reads stale from the close on; one taken after the close stays
      fresh straight through the night and weekend with no refetch.

    Judged off fetched_at alone, never the last bar's date, so a market
    holiday (no bar for a session that "should" exist) can't leave a row
    permanently stale. Weekday-aware, deliberately NOT holiday-aware, and
    US-session-only, like shared_bars_cache's own close-aware checks --
    a holiday just costs an extra refetch per TTL, and a foreign-listed
    symbol is treated on the US clock."""
    if not rows:
        return True
    now = reference or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    # fetched_at is a naive datetime.now() (server-local); astimezone() on a
    # naive value reads it as local time, which is what it was written as.
    fetched_at = max(row.fetched_at for row in rows).astimezone(timezone.utc)
    if _session_is_open(now):
        return now - fetched_at >= timedelta(seconds=settings.yahoo_quote_intraday_ttl_seconds)
    last_close = datetime.combine(_most_recent_completed_trading_date(now), time(_MARKET_CLOSE_HOUR_ET), tzinfo=_EASTERN)
    return fetched_at < last_close + _CLOSE_SETTLE


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
    ticker: str, period: str = "2y", cache_only: bool = False, reference: datetime | None = None
) -> list[YahooPriceCache]:
    """Cache-first read of a ticker's daily OHLCV history: returns the
    cached rows if fresh (see _is_stale -- market-session-aware, not a flat
    timer), else fetches live via yahoo_client and upserts -- mirrors
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
        if not _is_stale(rows, reference) or cache_only:
            return rows

        fetched = await yahoo_client.get_history([ticker], period=period)
        df = fetched.get(ticker)
        if df is None or df.empty:
            # Live fetch failed or returned nothing -- fall back to whatever's
            # cached, even if stale, same "stale is better than nothing"
            # semantics as core/cache.py's own fetch-failure handling.
            return rows

        # `reference` (a testability seam, like shared_bars_cache's) drives the
        # written fetched_at too, so the freshness check and the stamp share a clock.
        fetched_at = (reference or datetime.now(timezone.utc)).astimezone().replace(tzinfo=None)
        _write_rows(session, ticker, df, fetched_at)
        return _load_cached_rows(session, ticker)
