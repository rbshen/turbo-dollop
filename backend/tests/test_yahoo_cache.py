import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import clients.yahoo_cache as yahoo_cache_module
from core.models import YahooPriceCache


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _sample_df(n: int = 5, start_price: float = 100.0) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": [start_price + i for i in range(n)],
            "High": [start_price + i + 1 for i in range(n)],
            "Low": [start_price + i - 1 for i in range(n)],
            "Close": [start_price + i for i in range(n)],
            "Volume": [1000 + i for i in range(n)],
        },
        index=dates,
    )


def test_get_or_fetch_price_history_fetches_and_caches_when_empty(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(yahoo_cache_module, "engine", engine)

    call_count = {"n": 0}

    async def fake_get_history(tickers, period="2y", interval="1d", auto_adjust=True):
        call_count["n"] += 1
        return {"AAPL": _sample_df()}

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history)

    rows = asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL"))

    assert call_count["n"] == 1
    assert len(rows) == 5
    assert rows[0].close == 100.0


_ET = ZoneInfo("America/New_York")


def _et(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """A US/Eastern wall-clock moment in the week of Mon 2026-09-14 (Fri is
    the 18th, Sat the 19th, Mon the 21st)."""
    return datetime(2026, 9, day, hour, minute, second, tzinfo=_ET)


def _stored(moment: datetime) -> datetime:
    """How datetime.now() would have stamped fetched_at at `moment` -- naive,
    server-local -- so tests don't depend on the machine's timezone."""
    return moment.astimezone().replace(tzinfo=None)


def _row(fetched_at: datetime) -> YahooPriceCache:
    return YahooPriceCache(
        ticker="AAPL", date=pd.Timestamp("2026-09-18").date(), open=1, high=2, low=0.5, close=1.5, volume=100,
        fetched_at=_stored(fetched_at),
    )


@pytest.fixture(autouse=True)
def _ttl_60s(monkeypatch):
    monkeypatch.setattr(yahoo_cache_module.settings, "yahoo_quote_intraday_ttl_seconds", 60)


# (fetched, read, stale?) -- 2026-09-18 is a Friday. The failing case the old
# flat 1-day timer got wrong is the first "after the close" row: fetched
# mid-session (a partial bar), read hours later, still called fresh.
@pytest.mark.parametrize(
    "fetched, read, stale",
    [
        # session open: fresh only for the short TTL
        (_et(18, 11, 0, 0), _et(18, 11, 0, 30), False),
        (_et(18, 11, 0, 0), _et(18, 11, 2, 0), True),
        (_et(18, 9, 45), _et(18, 9, 45), False),  # first minutes of the session
        # THE BUG: fetched mid-session, read after the close -- a partial bar
        (_et(18, 10, 0), _et(18, 16, 30), True),
        (_et(18, 10, 0), _et(18, 20, 0), True),
        (_et(18, 15, 59), _et(19, 12, 0), True),  # ...and across the weekend
        # fetched inside the post-close settle allowance is still not final
        (_et(18, 16, 5), _et(18, 16, 20), True),
        # fetched after the close (+ settle): final, and stays fresh with no refetch
        (_et(18, 16, 11), _et(18, 16, 30), False),
        (_et(18, 17, 0), _et(18, 23, 0), False),
        (_et(18, 17, 0), _et(19, 12, 0), False),  # Saturday
        (_et(18, 17, 0), _et(21, 8, 0), False),  # Monday pre-open
        # pre-open on a trading day: yesterday's close is still the newest one
        (_et(17, 17, 0), _et(18, 8, 0), False),
        # ...but once the session opens, a night-old fetch is stale
        (_et(17, 17, 0), _et(18, 9, 31), True),
        # after today's close, a fetch from before it is stale
        (_et(17, 17, 0), _et(18, 17, 0), True),
        # a full day behind, however you read it
        (_et(16, 17, 0), _et(18, 12, 0), True),
    ],
)
def test_is_stale_tracks_the_market_session_not_a_flat_timer(fetched, read, stale):
    assert yahoo_cache_module._is_stale([_row(fetched)], reference=read) is stale


def test_is_stale_with_no_rows_is_always_stale():
    assert yahoo_cache_module._is_stale([], reference=_et(19, 12, 0)) is True


def test_is_stale_uses_the_newest_fetch_across_rows():
    rows = [_row(_et(17, 17, 0)), _row(_et(18, 17, 0))]
    assert yahoo_cache_module._is_stale(rows, reference=_et(19, 12, 0)) is False


def test_holiday_costs_one_refetch_not_a_permanent_stale_row(monkeypatch):
    # Monday "session" that never happened (a holiday): the old row (fetched Fri
    # after close) reads stale once, then the refetch -- same bars, since Yahoo has
    # no Monday bar -- is fresh, judged off fetched_at rather than the last bar's date.
    engine = _fresh_engine()
    monkeypatch.setattr(yahoo_cache_module, "engine", engine)
    with Session(engine) as session:
        session.add(_row(_et(18, 17, 0)))
        session.commit()
    calls = {"n": 0}

    async def fake_get_history(tickers, period="2y", interval="1d", auto_adjust=True):
        calls["n"] += 1
        return {"AAPL": _sample_df(n=1)}

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history)
    monday_evening = _et(21, 20, 0)
    asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL", reference=monday_evening))
    asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL", reference=monday_evening + timedelta(hours=1)))
    assert calls["n"] == 1


def test_mid_session_fetch_is_refetched_after_the_close_and_then_kept(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(yahoo_cache_module, "engine", engine)
    prices = iter([101.0, 105.5])
    calls = {"n": 0}

    async def fake_get_history(tickers, period="2y", interval="1d", auto_adjust=True):
        calls["n"] += 1
        df = _sample_df(n=1, start_price=next(prices))
        df.index = pd.DatetimeIndex([pd.Timestamp("2026-09-18")])
        return {"AAPL": df}

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history)
    get = lambda at: asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL", reference=at))  # noqa: E731

    assert get(_et(18, 11, 0))[-1].close == 101.0  # cold fetch: the live, partial price
    assert get(_et(18, 11, 0, 30))[-1].close == 101.0  # 30s later: served from cache
    assert calls["n"] == 1
    assert get(_et(18, 17, 0))[-1].close == 105.5  # after the close: refetched, now the final close
    assert get(_et(19, 12, 0))[-1].close == 105.5  # weekend: kept, no refetch
    assert calls["n"] == 2


def test_get_or_fetch_price_history_returns_cached_when_fresh(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(yahoo_cache_module, "engine", engine)

    with Session(engine) as session:
        session.add(_row(_et(18, 17, 0)))
        session.commit()

    def fail_if_called(tickers, period="2y", interval="1d", auto_adjust=True):
        raise AssertionError("must not fetch live when cache is fresh")

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fail_if_called)

    rows = asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL", reference=_et(19, 12, 0)))

    assert len(rows) == 1


def test_get_or_fetch_price_history_cache_only_never_fetches_live(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(yahoo_cache_module, "engine", engine)

    def fail_if_called(tickers, period="2y", interval="1d", auto_adjust=True):
        raise AssertionError("cache_only must never call Yahoo live")

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fail_if_called)

    rows = asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL", cache_only=True))

    assert rows == []  # nothing cached yet, cache_only never fetches to fill it


def test_upsert_overwrites_same_ticker_date_row_not_duplicate(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(yahoo_cache_module, "engine", engine)

    async def fake_get_history_v1(tickers, period="2y", interval="1d", auto_adjust=True):
        return {"AAPL": _sample_df(n=1, start_price=100.0)}

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history_v1)
    asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL"))

    # Force staleness so a second fetch actually happens, with a different close.
    with Session(engine) as session:
        row = session.exec(select(YahooPriceCache).where(YahooPriceCache.ticker == "AAPL")).first()
        row.fetched_at = datetime.now() - timedelta(days=10)
        session.add(row)
        session.commit()

    async def fake_get_history_v2(tickers, period="2y", interval="1d", auto_adjust=True):
        return {"AAPL": _sample_df(n=1, start_price=200.0)}

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history_v2)
    rows = asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL"))

    assert len(rows) == 1  # same (ticker, date) key -- updated in place, not duplicated
    assert rows[0].close == 200.0
