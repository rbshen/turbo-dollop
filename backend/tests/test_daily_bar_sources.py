import asyncio
from datetime import date, datetime, timedelta

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine

import clients.daily_bar_sources as daily_bar_sources
from clients.daily_bar_sources import (
    MassiveDailySource,
    MassiveWithYahooFallback,
    YahooDailySource,
    get_daily_bar_source,
    route_by_source,
)
from core.models import SharedBarsCache

TODAY = date(2026, 9, 23)


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(daily_bar_sources, "engine", engine)
    return engine


def _seed_row(engine, ticker: str, bar_date: date, close: float = 100.0) -> None:
    with Session(engine) as session:
        session.add(
            SharedBarsCache(
                ticker=ticker, interval="1d", bar_time=datetime.combine(bar_date, datetime.min.time()),
                open=close, high=close + 1, low=close - 1, close=close, volume=1000, fetched_at=datetime.now(),
            )
        )
        session.commit()


def _bar_frame(bar_date: date, close: float = 200.0) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [close - 1], "high": [close + 1], "low": [close - 2], "close": [close], "volume": [500]},
        index=pd.DatetimeIndex([pd.Timestamp(bar_date)]),
    )


# ---- route_by_source ----


def test_route_by_source_splits_dotted_tickers_to_non_us():
    us, non_us = route_by_source({"AAPL": 30, "0700.HK": 30, "MSFT": 60})
    assert us == {"AAPL": 30, "MSFT": 60}
    assert non_us == {"0700.HK": 30}


# ---- YahooDailySource ----


def test_yahoo_daily_source_groups_tickers_by_period_tier(monkeypatch):
    calls = []

    async def fake_get_history(tickers, period, interval, auto_adjust):
        calls.append((tuple(sorted(tickers)), period))
        return {t: _bar_frame(TODAY) for t in tickers}

    monkeypatch.setattr(daily_bar_sources.yahoo_client, "get_history", fake_get_history)

    source = YahooDailySource()
    result = asyncio.run(source.get_daily_bars({"AAPL": 30, "MSFT": 30, "SPY": 800}, auto_adjust=False))

    assert set(result) == {"AAPL", "MSFT", "SPY"}
    # AAPL/MSFT (30d -> "1mo" tier) batched into one call, SPY (800d -> "5y" tier) its own call.
    assert (("AAPL", "MSFT"), "1mo") in calls
    assert (("SPY",), "5y") in calls


# ---- MassiveDailySource ----


def test_never_cached_ticker_goes_through_backfill_range_call(monkeypatch):
    _fresh_engine(monkeypatch)

    class FakeClient:
        async def get_recent_splits(self, since):
            return []

        async def get_daily_bars(self, symbol, start, end, adjusted):
            assert symbol == "AAPL"
            assert end == TODAY
            return _bar_frame(TODAY)

        async def get_grouped_daily(self, day, adjusted):
            raise AssertionError("should not be called -- no incremental tickers")

    source = MassiveDailySource(client=FakeClient())
    result = asyncio.run(source.get_daily_bars({"AAPL": 30}, auto_adjust=False, reference=TODAY))

    assert "AAPL" in result
    assert not result["AAPL"].empty


def test_insufficient_existing_depth_forces_backfill_not_incremental(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_row(engine, "AAPL", TODAY - timedelta(days=2))  # only 3 days of history

    class FakeClient:
        async def get_recent_splits(self, since):
            return []

        async def get_daily_bars(self, symbol, start, end, adjusted):
            return _bar_frame(TODAY)

        async def get_grouped_daily(self, day, adjusted):
            raise AssertionError("should not be called -- ticker needed backfill, not incremental")

    source = MassiveDailySource(client=FakeClient())
    # 730 days requested, but only 3 days cached -- insufficient, must backfill.
    result = asyncio.run(source.get_daily_bars({"AAPL": 730}, auto_adjust=False, reference=TODAY))

    assert "AAPL" in result


def test_sufficient_depth_and_recent_last_bar_uses_grouped_daily_incremental(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_row(engine, "AAPL", TODAY - timedelta(days=800))
    _seed_row(engine, "AAPL", TODAY - timedelta(days=1))  # last bar just 1 day stale

    class FakeClient:
        async def get_recent_splits(self, since):
            return []

        async def get_daily_bars(self, symbol, start, end, adjusted):
            raise AssertionError("should not be called -- ticker is merely stale, not insufficient")

        async def get_grouped_daily(self, day, adjusted):
            assert day == TODAY  # the one missing trading day
            return {"AAPL": _bar_frame(TODAY, close=345.0)}

    source = MassiveDailySource(client=FakeClient())
    result = asyncio.run(source.get_daily_bars({"AAPL": 730}, auto_adjust=False, reference=TODAY))

    assert result["AAPL"].iloc[-1]["close"] == 345.0


def test_stale_beyond_recency_slack_falls_back_to_full_backfill(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_row(engine, "AAPL", TODAY - timedelta(days=800))
    _seed_row(engine, "AAPL", TODAY - timedelta(days=10))  # stale beyond _BACKFILL_RECENCY_SLACK_DAYS (5)

    class FakeClient:
        async def get_recent_splits(self, since):
            return []

        async def get_daily_bars(self, symbol, start, end, adjusted):
            return _bar_frame(TODAY)

        async def get_grouped_daily(self, day, adjusted):
            raise AssertionError("should not be called -- too stale, must backfill instead")

    source = MassiveDailySource(client=FakeClient())
    result = asyncio.run(source.get_daily_bars({"AAPL": 730}, auto_adjust=False, reference=TODAY))

    assert "AAPL" in result


def test_recently_split_ticker_forces_backfill_even_if_otherwise_incremental(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_row(engine, "SMCI", TODAY - timedelta(days=800))
    _seed_row(engine, "SMCI", TODAY - timedelta(days=1))

    class FakeClient:
        async def get_recent_splits(self, since):
            return [{"ticker": "SMCI", "execution_date": TODAY.isoformat()}]

        async def get_daily_bars(self, symbol, start, end, adjusted):
            assert symbol == "SMCI"
            return _bar_frame(TODAY)

        async def get_grouped_daily(self, day, adjusted):
            raise AssertionError("should not be called -- split forces backfill")

    source = MassiveDailySource(client=FakeClient())
    result = asyncio.run(source.get_daily_bars({"SMCI": 730}, auto_adjust=False, reference=TODAY))

    assert "SMCI" in result


def test_grouped_daily_failure_for_one_day_is_tolerated_not_fatal(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_row(engine, "AAPL", TODAY - timedelta(days=800))
    _seed_row(engine, "AAPL", TODAY - timedelta(days=1))

    class FakeClient:
        async def get_recent_splits(self, since):
            return []

        async def get_daily_bars(self, symbol, start, end, adjusted):
            raise AssertionError("should not be called")

        async def get_grouped_daily(self, day, adjusted):
            raise RuntimeError("Massive is down")

    source = MassiveDailySource(client=FakeClient())
    result = asyncio.run(source.get_daily_bars({"AAPL": 730}, auto_adjust=False, reference=TODAY))

    # Tolerated, not raised -- ticker just stays absent from the result (still stale this run).
    assert "AAPL" not in result


# ---- MassiveWithYahooFallback ----


def test_total_massive_failure_falls_back_to_yahoo_for_everything(monkeypatch):
    class FailingMassive:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None):
            raise RuntimeError("Massive is down")

    yahoo_calls = []

    class FakeYahoo:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None):
            yahoo_calls.append(dict(tickers_with_days))
            return {t: _bar_frame(TODAY) for t in tickers_with_days}

    source = MassiveWithYahooFallback(massive=FailingMassive(), yahoo=FakeYahoo())
    result = asyncio.run(source.get_daily_bars({"AAPL": 30, "MSFT": 30}, auto_adjust=False))

    assert set(result) == {"AAPL", "MSFT"}
    assert yahoo_calls == [{"AAPL": 30, "MSFT": 30}]


def test_partial_massive_result_falls_back_to_yahoo_only_for_missing_tickers():
    class PartialMassive:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None):
            return {"AAPL": _bar_frame(TODAY)}  # MSFT missing entirely

    yahoo_calls = []

    class FakeYahoo:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None):
            yahoo_calls.append(dict(tickers_with_days))
            return {t: _bar_frame(TODAY) for t in tickers_with_days}

    source = MassiveWithYahooFallback(massive=PartialMassive(), yahoo=FakeYahoo())
    result = asyncio.run(source.get_daily_bars({"AAPL": 30, "MSFT": 30}, auto_adjust=False))

    assert set(result) == {"AAPL", "MSFT"}
    assert yahoo_calls == [{"MSFT": 30}]


# ---- get_daily_bar_source ----


def test_get_daily_bar_source_returns_yahoo_only_when_massive_disabled(monkeypatch):
    monkeypatch.setattr(daily_bar_sources.settings, "massive_enabled", False)
    assert isinstance(get_daily_bar_source(), YahooDailySource)


def test_get_daily_bar_source_returns_massive_with_fallback_when_enabled(monkeypatch):
    monkeypatch.setattr(daily_bar_sources.settings, "massive_enabled", True)
    assert isinstance(get_daily_bar_source(), MassiveWithYahooFallback)

