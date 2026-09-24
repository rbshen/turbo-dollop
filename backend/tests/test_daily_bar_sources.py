import asyncio
import json
from datetime import date, datetime, timedelta

import httpx
import pandas as pd
from sqlmodel import Session, SQLModel, create_engine

import clients.daily_bar_sources as daily_bar_sources
from clients.daily_bar_sources import (
    FMP_OVERLAP_DAYS,
    FMPDailySource,
    FMPWithFallback,
    FallbackTickers,
    MassiveDailySource,
    MassiveWithYahooFallback,
    YahooDailySource,
    get_daily_bar_source,
    route_by_source,
)
from core.models import FundamentalsCache, SharedBarsCache

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


def test_total_massive_failure_records_every_ticker_in_fallback_tickers():
    class FailingMassive:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, fallback_tickers=None):
            raise RuntimeError("Massive is down")

    class FakeYahoo:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, fallback_tickers=None):
            return {t: _bar_frame(TODAY) for t in tickers_with_days}

    source = MassiveWithYahooFallback(massive=FailingMassive(), yahoo=FakeYahoo())
    fallback_tickers: list[str] = []
    asyncio.run(source.get_daily_bars({"AAPL": 30, "MSFT": 30}, auto_adjust=False, fallback_tickers=fallback_tickers))

    assert sorted(fallback_tickers) == ["AAPL", "MSFT"]


def test_partial_massive_result_records_only_the_missing_tickers_in_fallback_tickers():
    class PartialMassive:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, fallback_tickers=None):
            return {"AAPL": _bar_frame(TODAY)}  # MSFT missing entirely

    class FakeYahoo:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, fallback_tickers=None):
            return {t: _bar_frame(TODAY) for t in tickers_with_days}

    source = MassiveWithYahooFallback(massive=PartialMassive(), yahoo=FakeYahoo())
    fallback_tickers: list[str] = []
    asyncio.run(source.get_daily_bars({"AAPL": 30, "MSFT": 30}, auto_adjust=False, fallback_tickers=fallback_tickers))

    assert fallback_tickers == ["MSFT"]


def test_fallback_tickers_left_none_by_default_does_not_error():
    """The out-param is optional -- every existing caller that doesn't pass
    it (get_or_fetch_bars_batch's default) must be unaffected."""
    class PartialMassive:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, fallback_tickers=None):
            return {}

    class FakeYahoo:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, fallback_tickers=None):
            return {t: _bar_frame(TODAY) for t in tickers_with_days}

    source = MassiveWithYahooFallback(massive=PartialMassive(), yahoo=FakeYahoo())
    result = asyncio.run(source.get_daily_bars({"AAPL": 30}, auto_adjust=False))

    assert "AAPL" in result


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


def test_get_daily_bar_source_is_fmp_first_with_yahoo_only_fallback_when_massive_disabled(monkeypatch):
    monkeypatch.setattr(daily_bar_sources.settings, "massive_enabled", False)
    source = get_daily_bar_source()
    assert isinstance(source, FMPWithFallback) and isinstance(source._fallback, YahooDailySource)


def test_get_daily_bar_source_is_fmp_then_massive_yahoo_when_massive_enabled(monkeypatch):
    monkeypatch.setattr(daily_bar_sources.settings, "massive_enabled", True)
    source = get_daily_bar_source()
    assert isinstance(source, FMPWithFallback) and isinstance(source._fallback, MassiveWithYahooFallback)


# ---- exchange-based routing (P2) ----


def _seed_profile(engine, ticker: str, exchange: str | None, country: str = "US") -> None:
    payload = [{"symbol": ticker, "exchange": exchange, "country": country}]
    with Session(engine) as session:
        session.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", raw_json=json.dumps(payload), fetched_at=datetime.now()))
        session.commit()


def test_route_by_source_uses_listing_exchange_not_domicile(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_profile(engine, "TSM", "NYSE", country="TW")       # foreign-domiciled ADR: US
    _seed_profile(engine, "SPY", "AMEX", country="US")        # NYSE Arca ETF: US
    _seed_profile(engine, "CNSWF", "OTC", country="CA")       # OTC: US by decision
    _seed_profile(engine, "0005.HK", "HKSE", country="GB")    # HK listing of a UK bank: non-US
    us, non_us = route_by_source({"TSM": 10, "SPY": 10, "CNSWF": 10, "0005.HK": 10, "XLK": 10, "^GSPC": 10, "MC.PA": 10})
    assert set(us) == {"TSM", "SPY", "CNSWF", "XLK", "^GSPC"}  # no profile + no dot = US
    assert set(non_us) == {"0005.HK", "MC.PA"}


# ---- FMPDailySource / FMPWithFallback (P2) ----


class FakeFMP:
    """Stands in for fmp_client: serves rows from `series` ({ticker: {date: close}}),
    honouring `from`, newest-first like the real endpoint."""

    def __init__(self, series, failing=()):
        self.series, self.failing, self.calls = series, set(failing), []

    async def get_historical_price_eod(self, ticker, from_date, to_date, group="daily_prices"):
        self.calls.append((ticker, from_date))
        if ticker in self.failing:
            raise httpx.ConnectError("boom")
        rows = [
            {"symbol": ticker, "date": d.isoformat(), "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000}
            for d, c in sorted(self.series.get(ticker, {}).items(), reverse=True)
            if d.isoformat() >= from_date
        ]
        return rows


def _series(start: date, n: int, base: float = 100.0, scale: float = 1.0):
    return {start + timedelta(days=i): (base + i) * scale for i in range(n)}


def _seed_series(engine, ticker, series):
    for d, c in series.items():
        _seed_row(engine, ticker, d, close=c)


def test_fmp_source_never_cached_ticker_gets_a_full_window_and_is_marked_for_replace(monkeypatch):
    _fresh_engine(monkeypatch)
    fmp = FakeFMP({"AAPL": _series(TODAY - timedelta(days=60), 61)})
    replace: list[str] = []
    result = asyncio.run(FMPDailySource(client=fmp).get_daily_bars({"AAPL": 90}, False, reference=TODAY, replace_tickers=replace))
    assert len(result["AAPL"]) == 61 and list(result["AAPL"].columns) == ["open", "high", "low", "close", "volume"]
    assert replace == ["AAPL"] and fmp.calls == [("AAPL", (TODAY - timedelta(days=90)).isoformat())]


def test_fmp_source_incremental_overlaps_the_cache_and_does_not_replace(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    cached = _series(TODAY - timedelta(days=100), 100)  # last cached bar = TODAY - 1
    _seed_series(engine, "AAPL", cached)
    fresh = {**cached, TODAY: 200.0}
    fmp = FakeFMP({"AAPL": fresh})
    replace: list[str] = []
    result = asyncio.run(FMPDailySource(client=fmp).get_daily_bars({"AAPL": 90}, False, reference=TODAY, replace_tickers=replace))
    last_bar = TODAY - timedelta(days=1)
    assert fmp.calls == [("AAPL", (last_bar - timedelta(days=FMP_OVERLAP_DAYS)).isoformat())]  # ONE call, overlapping
    assert result["AAPL"].index.max() == pd.Timestamp(TODAY) and len(result["AAPL"]) == FMP_OVERLAP_DAYS + 2
    assert replace == []


def test_fmp_source_ignores_a_restated_last_bar_but_refetches_fully_when_earlier_overlap_moves(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    cached = _series(TODAY - timedelta(days=100), 100)
    _seed_series(engine, "AAPL", cached)
    last = TODAY - timedelta(days=1)
    # provisional last bar differs by 3% -- that alone must NOT trigger a full refetch
    only_last = {**cached, last: cached[last] * 1.03}
    fmp = FakeFMP({"AAPL": only_last})
    replace: list[str] = []
    asyncio.run(FMPDailySource(client=fmp).get_daily_bars({"AAPL": 90}, False, reference=TODAY, replace_tickers=replace))
    assert len(fmp.calls) == 1 and replace == []
    # a spin-off restates every earlier close by 10% -> full window refetch + replace
    restated = _series(TODAY - timedelta(days=100), 100, scale=0.9)
    fmp = FakeFMP({"AAPL": restated})
    replace = []
    result = asyncio.run(FMPDailySource(client=fmp).get_daily_bars({"AAPL": 90}, False, reference=TODAY, replace_tickers=replace))
    assert [c[1] for c in fmp.calls] == [(last - timedelta(days=FMP_OVERLAP_DAYS)).isoformat(), (TODAY - timedelta(days=90)).isoformat()]
    assert replace == ["AAPL"] and len(result["AAPL"]) > FMP_OVERLAP_DAYS + 2


def test_fmp_source_full_refresh_skips_the_incremental_path(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    cached = _series(TODAY - timedelta(days=100), 100)
    _seed_series(engine, "AAPL", cached)
    fmp = FakeFMP({"AAPL": cached})
    replace: list[str] = []
    asyncio.run(FMPDailySource(client=fmp).get_daily_bars({"AAPL": 90}, False, reference=TODAY, replace_tickers=replace, full_refresh=True))
    assert fmp.calls == [("AAPL", (TODAY - timedelta(days=90)).isoformat())] and replace == ["AAPL"]


def test_fmp_source_returns_nothing_while_daily_prices_is_off(monkeypatch):
    import core.data_groups as dg

    _fresh_engine(monkeypatch)
    dg.set_group_enabled("daily_prices", False)
    fmp = FakeFMP({"AAPL": _series(TODAY - timedelta(days=60), 61)})
    assert asyncio.run(FMPDailySource(client=fmp).get_daily_bars({"AAPL": 90}, False, reference=TODAY)) == {}
    assert fmp.calls == []


def test_fmp_source_a_failing_or_empty_ticker_is_simply_absent(monkeypatch):
    _fresh_engine(monkeypatch)
    fmp = FakeFMP({"AAPL": _series(TODAY - timedelta(days=60), 61), "TWTR": {}}, failing={"MSFT"})
    result = asyncio.run(FMPDailySource(client=fmp).get_daily_bars({"AAPL": 90, "MSFT": 90, "TWTR": 90}, False, reference=TODAY))
    assert set(result) == {"AAPL"}


def test_fmp_source_a_tiny_full_answer_never_replaces_existing_rows(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_series(engine, "AAPL", _series(TODAY - timedelta(days=100), 100))
    fmp = FakeFMP({"AAPL": _series(TODAY - timedelta(days=3), 3)})
    replace: list[str] = []
    result = asyncio.run(FMPDailySource(client=fmp).get_daily_bars({"AAPL": 400}, False, reference=TODAY, replace_tickers=replace))
    assert result == {} and replace == []


def test_fmp_with_fallback_serves_the_rest_from_the_fallback_and_reports_the_split(monkeypatch):
    class FMPOnlyAAPL:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, replace_tickers=None, full_refresh=False, **_):
            return {"AAPL": _bar_frame(TODAY)}

    class Chain:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, fallback_tickers=None, **_):
            if fallback_tickers is not None:
                fallback_tickers.append("ZZZ")  # Massive gave nothing for ZZZ -> Yahoo served it
            return {t: _bar_frame(TODAY, 50.0) for t in tickers_with_days}

    monkeypatch.setattr(daily_bar_sources.settings, "massive_enabled", True)
    out = FallbackTickers()
    result = asyncio.run(
        FMPWithFallback(fmp=FMPOnlyAAPL(), fallback=Chain()).get_daily_bars(
            {"AAPL": 30, "MSFT": 30, "ZZZ": 30}, False, reference=TODAY, fallback_tickers=out
        )
    )
    assert set(result) == {"AAPL", "MSFT", "ZZZ"} and result["AAPL"]["close"].iloc[0] == 200.0
    assert sorted(out) == ["MSFT", "ZZZ"] and out.yahoo == ["ZZZ"]
    assert out.describe() == "2 fell back from FMP (Massive 1, Yahoo 1)"


def test_fmp_with_fallback_survives_the_fmp_layer_raising(monkeypatch):
    class Boom:
        async def get_daily_bars(self, *a, **k):
            raise RuntimeError("fmp down")

    class Chain:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, fallback_tickers=None, **_):
            return {t: _bar_frame(TODAY) for t in tickers_with_days}

    result = asyncio.run(FMPWithFallback(fmp=Boom(), fallback=Chain()).get_daily_bars({"AAPL": 30}, False, reference=TODAY))
    assert set(result) == {"AAPL"}


def test_fmp_source_drops_a_partial_bar_dated_after_the_last_completed_session(monkeypatch):
    _fresh_engine(monkeypatch)
    monkeypatch.setattr(daily_bar_sources, "_completed_session", lambda: TODAY)
    series = {**_series(TODAY - timedelta(days=60), 61), TODAY + timedelta(days=1): 999.0}  # mid-session bar for "tomorrow"
    result = asyncio.run(FMPDailySource(client=FakeFMP({"AAPL": series})).get_daily_bars({"AAPL": 90}, False, reference=TODAY + timedelta(days=1)))
    assert result["AAPL"].index.max() == pd.Timestamp(TODAY)


def test_fmp_source_a_cache_a_few_days_short_of_the_window_still_counts_as_covering_it(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    cached = _series(TODAY - timedelta(days=88), 89)  # 3 days short of a 90-day window: boundary slack, not a narrow cache
    _seed_series(engine, "AAPL", cached)
    fmp = FakeFMP({"AAPL": cached})
    replace: list[str] = []
    asyncio.run(FMPDailySource(client=fmp).get_daily_bars({"AAPL": 90}, False, reference=TODAY, replace_tickers=replace))
    assert replace == [] and len(fmp.calls) == 1 and fmp.calls[0][1] > (TODAY - timedelta(days=30)).isoformat()


def test_get_daily_bar_source_non_us_is_intl_fmp_then_yahoo_only_whatever_massive_says(monkeypatch):
    monkeypatch.setattr(daily_bar_sources.settings, "massive_enabled", True)
    source = get_daily_bar_source(non_us=True)
    assert isinstance(source, FMPWithFallback) and isinstance(source._fallback, YahooDailySource)
    assert source._fmp._group == "daily_prices_intl" and source._fmp._non_us is True
    assert get_daily_bar_source()._fmp._group == "daily_prices"


def test_intl_fmp_source_is_gated_by_its_own_group_only(monkeypatch):
    import core.data_groups as dg

    _fresh_engine(monkeypatch)
    monkeypatch.setattr(daily_bar_sources, "_completed_session", lambda: TODAY)
    series = _series(TODAY - timedelta(days=60), 61)
    dg.set_group_enabled("daily_prices", False)  # the US group being off must not matter
    fmp = FakeFMP({"0005.HK": series})
    out = asyncio.run(FMPDailySource(client=fmp, group="daily_prices_intl", non_us=True).get_daily_bars({"0005.HK": 90}, False, reference=TODAY))
    assert "0005.HK" in out
    dg.set_group_enabled("daily_prices_intl", False)
    fmp = FakeFMP({"0005.HK": series})
    assert asyncio.run(FMPDailySource(client=fmp, group="daily_prices_intl", non_us=True).get_daily_bars({"0005.HK": 90}, False, reference=TODAY)) == {}
    assert fmp.calls == []


def test_non_us_fmp_source_strips_weekend_rows_but_the_us_source_does_not(monkeypatch):
    _fresh_engine(monkeypatch)
    monkeypatch.setattr(daily_bar_sources, "_completed_session", lambda: TODAY)
    # _series is one bar per calendar day, so it includes weekend dates
    series = _series(TODAY - timedelta(days=13), 14)
    us = asyncio.run(FMPDailySource(client=FakeFMP({"X": series})).get_daily_bars({"X": 90}, False, reference=TODAY))
    intl = asyncio.run(FMPDailySource(client=FakeFMP({"X": series}), group="daily_prices_intl", non_us=True).get_daily_bars({"X": 90}, False, reference=TODAY))
    assert len(us["X"]) == 14 and len(intl["X"]) == 10 and (intl["X"].index.dayofweek < 5).all()
