"""On-demand ~10-year daily bars from FMP, stored in their own table (FMP Phase 3).

Consumers: the Chart tab's weekly 4y range (data/chart_data.py) and the Analyst Ratings
price overlay (data/analyst_ratings_data.py). Everything else that reads daily bars reads
`SharedBarsCache["1d"]` (nightly, ~5y) and never touches this.

    bars = await get_long_history("KO")      # DataFrame | None

`None` means "not available from FMP -- use today's Yahoo path" (the caller's fall-
through); a DataFrame is lowercase open/high/low/close/volume on a naive ascending
DatetimeIndex, the whole stored window (the caller trims what it needs).

Behaviour (per ticker, single-flight -- concurrent first opens make ONE FMP call):
  * no row, group live          -> synchronous fetch of LONG_HISTORY_YEARS, write, serve.
  * row fresh                   -> serve it, no FMP call. Fresh = its last bar is the most
                                   recently completed US session AND that bar was written
                                   after the session's close (+ settle) -- the Phase 2 rule.
  * row stale, group live       -> incremental top-up (`from = last bar - 7d`), the 0.5%
                                   overlap check on shared dates; a mismatch means FMP
                                   restated history (split / spin-off / symbol reuse), so
                                   the full window is refetched and REPLACES the row.
                                   No shrink guard: any non-empty answer replaces.
  * group off                   -> an existing row is served as-is (cached-only, never
                                   wiped); no row -> None.
  * group live, FMP error/empty -> cold: None, nothing written. Warm-but-stale: the
                                   existing row (same basis, a few days behind) rather
                                   than switching the chart onto Yahoo's basis.

The group is `daily_prices_long` (Premium). FMP caps a response at 5,000 rows
(~19.9y), so a 10y request fits in one call and no paging exists. Never logged: the
request URL (it embeds the API key); only the exception TYPE.

The freshness clock is the US session for every ticker (a non-US ticker on a local-only
holiday reads stale and costs one redundant, idempotent top-up per view).
"""

import asyncio
import logging
import weakref
from datetime import date, datetime, time, timedelta, timezone

import httpx
import pandas as pd
from sqlalchemy import delete, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from clients.daily_bar_sources import (
    FMP_OVERLAP_DAYS,
    FMP_OVERLAP_TOLERANCE,
    fmp_rows_to_frame,
)
from clients.fmp_client import FMPGroupDisabledError, fmp_client
from core.data_groups import effective_state
from core.db import engine
from core.models import LongHistoryBars

logger = logging.getLogger(__name__)

LONG_HISTORY_YEARS = 10
GROUP = "daily_prices_long"
_OHLCV = ["open", "high", "low", "close", "volume"]

# One lock per (event loop, ticker): asyncio.Lock binds to the loop it is first contended
# on, and this process runs one loop (uvicorn) but tests run many.
_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = weakref.WeakKeyDictionary()


def _lock_for(ticker: str) -> asyncio.Lock:
    per_loop = _locks.setdefault(asyncio.get_running_loop(), {})
    return per_loop.setdefault(ticker, asyncio.Lock())


def _completed_session(reference: datetime | None) -> date:
    from clients.shared_bars_cache import _most_recent_completed_trading_date

    return _most_recent_completed_trading_date(reference)


def _read(ticker: str) -> tuple[pd.DataFrame, datetime | None]:
    """The stored frame and the newest write time (max fetched_at, which stands in for
    "when the last bar was written" -- a top-up rewrites the last bar and appends)."""
    with Session(engine) as session:
        rows = session.exec(
            select(
                LongHistoryBars.bar_time, LongHistoryBars.open, LongHistoryBars.high, LongHistoryBars.low,
                LongHistoryBars.close, LongHistoryBars.volume,
            )
            .where(LongHistoryBars.ticker == ticker)
            .order_by(LongHistoryBars.bar_time)
        ).all()
        if not rows:
            return pd.DataFrame(columns=_OHLCV), None
        fetched_at = session.exec(select(func.max(LongHistoryBars.fetched_at)).where(LongHistoryBars.ticker == ticker)).one()
    frame = pd.DataFrame.from_records(rows, columns=["bar_time", *_OHLCV]).set_index("bar_time")
    frame.index = pd.DatetimeIndex(frame.index)
    return frame, fetched_at


def _write(ticker: str, frame: pd.DataFrame, fetched_at: datetime, replace: bool) -> None:
    values = [
        {"ticker": ticker, "bar_time": ts, "open": o, "high": h, "low": low, "close": c, "volume": v, "fetched_at": fetched_at}
        for ts, o, h, low, c, v in zip(
            frame.index.to_pydatetime(), frame["open"].astype(float).tolist(), frame["high"].astype(float).tolist(),
            frame["low"].astype(float).tolist(), frame["close"].astype(float).tolist(),
            frame["volume"].fillna(0).astype("int64").tolist(),
        )
    ]
    if not values:
        return
    with Session(engine) as session:
        if replace:
            # ONE transaction: a failed insert never leaves a half-empty ticker.
            session.execute(delete(LongHistoryBars).where(LongHistoryBars.ticker == ticker))
        stmt = sqlite_insert(LongHistoryBars)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "bar_time"],
            set_={c: getattr(stmt.excluded, c) for c in ("open", "high", "low", "close", "volume", "fetched_at")},
        )
        session.execute(stmt, values)
        session.commit()


def _is_fresh(cached: pd.DataFrame, fetched_at: datetime | None, reference: datetime | None) -> bool:
    """Phase 2's rule: the last bar is the most recently completed session AND was written
    after that session's close (+10 min settle) -- a bar written mid-session is partial."""
    from clients.shared_bars_cache import _CLOSE_SETTLE, _EASTERN, _MARKET_CLOSE_HOUR_ET

    if cached.empty or fetched_at is None:
        return False
    last = cached.index.max().date()
    if last < _completed_session(reference):
        return False
    close = datetime.combine(last, time(_MARKET_CLOSE_HOUR_ET), tzinfo=_EASTERN) + _CLOSE_SETTLE
    return fetched_at.astimezone(_EASTERN) >= close  # naive fetched_at = server-local time


def _restated(cached: pd.DataFrame, fresh: pd.DataFrame) -> bool:
    """Any close the two share (other than the cache's own last bar, always overwritten)
    that differs by more than the tolerance."""
    last = cached.index.max()
    shared = fresh.index.intersection(cached.index)
    for ts in shared:
        old = float(cached.at[ts, "close"])
        if ts >= last or not old:
            continue
        if abs(float(fresh.at[ts, "close"]) / old - 1.0) > FMP_OVERLAP_TOLERANCE:
            return True
    return False


async def _fetch(client, ticker: str, start: date, end: date, reference: datetime | None):
    """Frame of completed sessions, or None on any failure/empty answer (logged by type only)."""
    try:
        rows = await client.get_historical_price_eod(ticker, start.isoformat(), end.isoformat(), group=GROUP)
    except FMPGroupDisabledError:
        return None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("FMP long-history fetch failed for %s (%s); falling back", ticker, type(exc).__name__)
        return None
    frame = fmp_rows_to_frame(rows)
    if frame.empty:
        return None
    # A bar dated after the last COMPLETED session is a live, partial one: never store it.
    frame = frame[frame.index <= pd.Timestamp(_completed_session(reference))]
    return frame if not frame.empty else None


async def get_long_history(
    ticker: str, reference: datetime | None = None, client=fmp_client
) -> pd.DataFrame | None:
    """See the module docstring. `reference` overrides "now" (a testability seam)."""
    async with _lock_for(ticker):
        cached, fetched_at = _read(ticker)
        if not effective_state(GROUP)[0]:
            return cached if not cached.empty else None  # cached-only: served as-is, never wiped
        from clients.shared_bars_cache import _eastern_today

        now = reference or datetime.now(timezone.utc)
        today = _eastern_today(now)
        if not cached.empty and _is_fresh(cached, fetched_at, reference):
            return cached
        if cached.empty:
            full = await _fetch(client, ticker, today - timedelta(days=365 * LONG_HISTORY_YEARS + 2), today, reference)
            if full is None:
                return None
            _write(ticker, full, datetime.now(), replace=True)
            return _read(ticker)[0]
        # stale warm row: incremental top-up
        top_up = await _fetch(client, ticker, cached.index.max().date() - timedelta(days=FMP_OVERLAP_DAYS), today, reference)
        if top_up is None:
            return cached  # FMP down / empty: the same-basis row a few days behind beats switching basis
        if _restated(cached, top_up):
            logger.info("FMP restated %s's history; refetching its full long-history window", ticker)
            full = await _fetch(client, ticker, today - timedelta(days=365 * LONG_HISTORY_YEARS + 2), today, reference)
            if full is None:
                return cached
            _write(ticker, full, datetime.now(), replace=True)
        else:
            _write(ticker, top_up, datetime.now(), replace=False)
        return _read(ticker)[0]
