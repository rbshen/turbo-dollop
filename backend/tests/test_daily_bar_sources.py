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
    UnservedTickers,
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


# ---- get_daily_bar_source ----


def test_get_daily_bar_source_is_the_fmp_daily_source_on_the_daily_prices_group():
    source = get_daily_bar_source()
    assert isinstance(source, FMPDailySource) and source._group == "daily_prices"
    assert not hasattr(daily_bar_sources, "YahooDailySource") and not hasattr(daily_bar_sources, "yahoo_client")


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


# ---- FMPDailySource ----


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


def test_fmp_source_returns_nothing_while_daily_prices_is_off_and_reports_every_ticker_unserved(monkeypatch):
    import core.data_groups as dg

    _fresh_engine(monkeypatch)
    dg.set_group_enabled("daily_prices", False)
    fmp = FakeFMP({"AAPL": _series(TODAY - timedelta(days=60), 61)})
    out = UnservedTickers()
    result = asyncio.run(FMPDailySource(client=fmp).get_daily_bars({"AAPL": 90, "MSFT": 90}, False, reference=TODAY, unserved_tickers=out))
    assert result == {} and fmp.calls == []
    assert sorted(out) == ["AAPL", "MSFT"]


def test_fmp_source_a_failing_or_empty_ticker_is_simply_absent(monkeypatch):
    _fresh_engine(monkeypatch)
    fmp = FakeFMP({"AAPL": _series(TODAY - timedelta(days=60), 61), "TWTR": {}}, failing={"MSFT"})
    out = UnservedTickers()
    result = asyncio.run(
        FMPDailySource(client=fmp).get_daily_bars({"AAPL": 90, "MSFT": 90, "TWTR": 90}, False, reference=TODAY, unserved_tickers=out)
    )
    assert set(result) == {"AAPL"}
    # No fallback provider: the unserved tickers are just reported, and describe() says so.
    assert sorted(out) == ["MSFT", "TWTR"]
    assert out.describe() == "2 not served by FMP (cached bars kept)"


def test_fmp_source_a_tiny_full_answer_never_replaces_existing_rows(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_series(engine, "AAPL", _series(TODAY - timedelta(days=100), 100))
    fmp = FakeFMP({"AAPL": _series(TODAY - timedelta(days=3), 3)})
    replace: list[str] = []
    result = asyncio.run(FMPDailySource(client=fmp).get_daily_bars({"AAPL": 400}, False, reference=TODAY, replace_tickers=replace))
    assert result == {} and replace == []


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
