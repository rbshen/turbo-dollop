"""Nightly FMP last-close cache (Phase 6a) -- the fallback tier for the ticker header's
price (data/ticker_summary.py). Massive/Polygon and Yahoo used to answer when the
`profile_quote` group was off; now the header asks FMP live and, failing that, serves
the last official close this module cached after the previous US close.

Source: FMP `/historical-price-eod/full` (data group `daily_prices`), a short window
ending today; the newest bar on/before the most recently completed US session is the
close (a bar dated after it is an in-progress/partial one and is ignored, the same
rule the daily-bar source applies). Split- and spin-off-adjusted like every other
FMP daily price in the app. Stored latest-only in TickerLastClose.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta

import httpx
import pandas as pd
from sqlmodel import Session

from clients.daily_bar_sources import FMP_CONCURRENCY, FMP_PLAN_REQUESTS_PER_MIN, FMP_RATE_FRACTION, _Pacer, fmp_rows_to_frame
from clients.fmp_client import fmp_client
from core.data_groups import get_snapshot
from core.db import engine
from core.models import TickerLastClose

logger = logging.getLogger(__name__)

# A week+ of lookback always holds at least one real bar, even across a long weekend.
LOOKBACK_DAYS = 10


def pick_last_close(rows: object, completed_session: date) -> tuple[float, date] | None:
    """(close, bar date) of the newest bar dated on/before `completed_session`, or None."""
    frame = fmp_rows_to_frame(rows)
    if frame.empty:  # an empty/unusable payload has no datetime index to compare against
        return None
    frame = frame[frame.index <= pd.Timestamp(completed_session)]
    if frame.empty:
        return None
    close = float(frame["close"].iloc[-1])
    if close <= 0:
        return None
    return close, frame.index[-1].date()


def get_cached_last_close(ticker: str) -> tuple[float, date] | None:
    """(close, as_of_date) cached for `ticker`, or None if never written."""
    with Session(engine) as session:
        row = session.get(TickerLastClose, ticker)
        return (row.close, row.as_of_date) if row else None


def _upsert(ticker: str, close: float, as_of: date, now: datetime) -> None:
    with Session(engine) as session:
        row = session.get(TickerLastClose, ticker)
        if row is None:
            session.add(TickerLastClose(ticker=ticker, close=close, as_of_date=as_of, fetched_at=now))
        else:
            row.close, row.as_of_date, row.fetched_at = close, as_of, now
        session.commit()


async def refresh_last_closes(tickers: list[str], completed_session: date | None = None) -> dict:
    """Fetch and cache the last close for each ticker (concurrent, paced to half the
    plan's documented rate). A ticker FMP returns nothing usable for is counted in
    `failed` and keeps whatever close it had. Returns {processed, written, failed,
    failures, as_of}."""
    if completed_session is None:
        from clients.shared_bars_cache import _most_recent_completed_trading_date

        completed_session = _most_recent_completed_trading_date()
    today = date.today()
    plan_rate = FMP_PLAN_REQUESTS_PER_MIN.get(get_snapshot().fmp_plan, 300)
    pacer = _Pacer(60.0 / (plan_rate * FMP_RATE_FRACTION))
    sem = asyncio.Semaphore(FMP_CONCURRENCY)
    now = datetime.now()
    failures: list[tuple[str, str]] = []
    written = 0

    async def one(ticker: str) -> None:
        nonlocal written
        async with sem:
            await pacer.wait()
            try:
                rows = await fmp_client.get_historical_price_eod(
                    ticker, (today - timedelta(days=LOOKBACK_DAYS)).isoformat(), today.isoformat()
                )
            except (httpx.HTTPError, ValueError) as exc:
                # Type name only: an httpx error's message embeds the request URL (apikey).
                failures.append((ticker, type(exc).__name__))
                return
        picked = pick_last_close(rows, completed_session)
        if picked is None:
            failures.append((ticker, "no usable bar"))
            return
        _upsert(ticker, picked[0], picked[1], now)
        written += 1

    await asyncio.gather(*(one(t) for t in tickers))
    return {
        "processed": len(tickers), "written": written, "failed": len(failures), "failures": failures,
        "as_of": completed_session.isoformat(),
    }
