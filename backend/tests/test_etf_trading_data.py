"""The ETF Overview's "Trading data" block (data/etf_data.py::_trading_data): performance from cached daily
bars, 52-week range, volume averages, trailing-12-month distribution yield, beta for equity funds only; every
zero/None value omitted and the whole block None when nothing is left. Cache-only: every test also asserts
no FMP call was made. Each test builds its own in-memory engine and patches it onto every module that reads."""

import asyncio
import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import clients.shared_bars_cache as shared_bars_cache
import data.etf_data as etf_data
from clients.fmp_client import fmp_client
from clients.shared_bars_cache import DAILY_INTERVAL, _most_recent_completed_trading_date, _write_rows
from core.models import FundamentalsCache

EQUITY_INFO = {"symbol": "QQQ", "name": "Invesco QQQ Trust", "assetClass": "Equity", "expenseRatio": 0.18}
BOND_INFO = {"symbol": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "assetClass": "Fixed Income"}
COMMODITY_INFO = {"symbol": "GLD", "name": "SPDR Gold Shares", "assetClass": "Commodities"}
# What the faked /etf/info answers; _overview sets it per call.
INFO_RESPONSE: dict = {"payload": []}
PROFILE = {"companyName": "Invesco QQQ Trust", "isEtf": True, "beta": 1.232, "lastDividend": 3.09182, "marketCap": 5e11}
QUOTE = {"price": 742.03, "yearLow": 555.6, "yearHigh": 748.65}


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(etf_data, "engine", engine)
    monkeypatch.setattr(shared_bars_cache, "engine", engine)
    calls = []

    async def no_fmp(name, *_a, **_k):
        calls.append(name)
        raise AssertionError(f"the Trading data block must not call FMP ({name})")

    for name in ("get_profile", "get_quote", "get_price_change", "get_historical_price_eod"):
        monkeypatch.setattr(fmp_client, name, lambda *a, _n=name, **k: no_fmp(_n, *a, **k))

    async def etf_info(_ticker):
        return INFO_RESPONSE["payload"]

    monkeypatch.setattr(fmp_client, "get_etf_info", etf_info)
    return engine, calls


def _put(engine, ticker, statement_type, payload):
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker=ticker, statement_type=statement_type, period="latest", fetched_at=datetime.now(),
                raw_json=json.dumps(payload),
            )
        )
        session.commit()


def _bars(engine, ticker, closes: dict[date, float], volume=1_000_000):
    """Daily bars written long before today's close, so none is a provisional last bar."""
    index = pd.DatetimeIndex(sorted(closes))
    df = pd.DataFrame(
        {"open": 0.0, "high": 0.0, "low": 0.0, "close": [closes[d.date()] for d in index], "volume": volume}, index=index
    )
    with Session(engine) as session:
        _write_rows(session, ticker, DAILY_INTERVAL, df, fetched_at=datetime.now() + timedelta(days=1))
        session.commit()


def _session_days(count: int, end: date) -> list[date]:
    days: list[date] = []
    day = end
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return sorted(days)


def _flat_history(engine, ticker, last_close=110.0, volume=1_000_000, years=2):
    """About `years` of business days ending on the last completed session: 100 until the final day."""
    completed = _most_recent_completed_trading_date()
    days = _session_days(260 * years, completed)
    closes = {d: 100.0 for d in days}
    closes[days[-1]] = last_close
    _bars(engine, ticker, closes, volume)
    return days


def _overview(info, ticker="QQQ"):
    INFO_RESPONSE["payload"] = [info]
    return asyncio.run(etf_data.get_etf_overview(ticker))


def test_equity_etf_shows_every_row(env):
    engine, calls = env
    _put(engine, "QQQ", "profile", [PROFILE])
    _put(engine, "QQQ", "quote", [QUOTE])
    days = _flat_history(engine, "QQQ", last_close=110.0, volume=2_000_000)

    td = _overview(EQUITY_INFO).trading_data

    assert td is not None and not calls
    assert td.perf_as_of == days[-1]
    # Every base in the flat history is 100 and the last close is 110 -> +10%, for 1M, YTD and 1Y alike.
    assert td.perf_1m == pytest.approx(10.0) and td.perf_ytd == pytest.approx(10.0) and td.perf_1y == pytest.approx(10.0)
    assert (td.week52_low, td.week52_high) == (555.6, 748.65)
    assert td.avg_volume_30d == 2_000_000
    assert td.avg_dollar_volume_20d == pytest.approx((19 * 100.0 + 110.0) / 20 * 2_000_000)
    assert td.distribution_ttm_per_share == pytest.approx(3.09182)
    assert td.distribution_ttm_yield_pct == pytest.approx(round(3.09182 / 742.03 * 100, 2))
    assert td.beta == 1.23


def test_performance_is_price_return_from_bars_not_the_cached_price_change_row(env):
    engine, calls = env
    _put(engine, "QQQ", "profile", [PROFILE])
    _put(engine, "QQQ", "price_change", [{"1M": 99.0, "ytd": 99.0, "1Y": 99.0}])  # a stale 7-day row: must not be read
    _flat_history(engine, "QQQ", last_close=105.0)

    td = _overview(EQUITY_INFO).trading_data

    assert td.perf_1m == pytest.approx(5.0) and td.perf_ytd == pytest.approx(5.0) and td.perf_1y == pytest.approx(5.0)
    assert not calls


@pytest.mark.parametrize("info", [BOND_INFO, COMMODITY_INFO])
def test_beta_is_hidden_for_a_bond_or_commodity_fund_but_the_other_rows_stay(env, info):
    engine, _ = env
    _put(engine, "TLT", "profile", [{**PROFILE, "beta": 2.4}])
    _put(engine, "TLT", "quote", [QUOTE])
    _flat_history(engine, "TLT")

    td = _overview(info, "TLT").trading_data

    assert td.beta is None
    assert td.perf_1m is not None and td.distribution_ttm_yield_pct is not None


def test_beta_is_hidden_when_the_asset_class_is_unknown_and_when_zero(env):
    engine, _ = env
    _put(engine, "QQQ", "profile", [PROFILE])
    _put(engine, "QQQ", "quote", [QUOTE])
    assert _overview({"symbol": "QQQ", "name": "x"}).trading_data.beta is None  # no asset class
    _put(engine, "SPY", "profile", [{**PROFILE, "beta": 0}])
    _put(engine, "SPY", "quote", [QUOTE])
    assert _overview(EQUITY_INFO, "SPY").trading_data.beta is None


def test_missing_bars_omit_the_performance_and_volume_rows_only(env):
    engine, _ = env
    _put(engine, "QQQ", "profile", [PROFILE])
    _put(engine, "QQQ", "quote", [QUOTE])

    td = _overview(EQUITY_INFO).trading_data

    assert (td.perf_1m, td.perf_ytd, td.perf_1y, td.perf_as_of) == (None, None, None, None)
    assert td.avg_volume_30d is None and td.avg_dollar_volume_20d is None
    assert td.week52_high == 748.65 and td.distribution_ttm_yield_pct is not None and td.beta == 1.23


def test_a_young_fund_omits_only_the_windows_its_bars_do_not_reach(env):
    engine, _ = env
    _put(engine, "QQQ", "profile", [PROFILE])
    completed = _most_recent_completed_trading_date()
    days = _session_days(60, completed)  # ~3 months of history: 1M reaches back, YTD / 1Y do not necessarily
    closes = {d: 100.0 for d in days}
    closes[days[-1]] = 120.0
    _bars(engine, "QQQ", closes)

    td = _overview(EQUITY_INFO).trading_data

    assert td.perf_1m == pytest.approx(20.0)
    assert td.perf_1y is None


def test_stale_bars_omit_every_performance_row(env):
    engine, _ = env
    _put(engine, "QQQ", "profile", [PROFILE])
    completed = _most_recent_completed_trading_date()
    days = _session_days(400, completed - timedelta(days=30))  # newest bar a month old
    _bars(engine, "QQQ", {d: 100.0 for d in days})

    td = _overview(EQUITY_INFO).trading_data

    assert td.perf_1m is None and td.perf_ytd is None and td.perf_1y is None and td.perf_as_of is None


def test_the_in_progress_session_bar_is_not_used_as_the_close(env):
    engine, _ = env
    _put(engine, "QQQ", "profile", [PROFILE])
    completed = _most_recent_completed_trading_date()
    days = _session_days(260 * 2, completed)
    closes = {d: 100.0 for d in days}
    closes[days[-1]] = 110.0
    live = completed + timedelta(days=1)  # a bar after the last completed session (an in-progress one)
    closes[live] = 500.0
    _bars(engine, "QQQ", closes)

    td = _overview(EQUITY_INFO).trading_data

    assert td.perf_as_of == days[-1] and td.perf_1m == pytest.approx(10.0)


def test_a_provisional_last_bar_is_dropped(env):
    engine, _ = env
    _put(engine, "QQQ", "profile", [PROFILE])
    completed = _most_recent_completed_trading_date()
    days = _session_days(520, completed)
    closes = {d: 100.0 for d in days}
    index = pd.DatetimeIndex(sorted(closes))
    df = pd.DataFrame({"open": 0.0, "high": 0.0, "low": 0.0, "close": [closes[d.date()] for d in index], "volume": 1}, index=index)
    # The newest bar was written at 9:00 the same morning, i.e. before its own session closed.
    written = datetime.combine(days[-1], datetime.min.time()).replace(hour=9)
    with Session(engine) as session:
        _write_rows(session, "QQQ", DAILY_INTERVAL, df, fetched_at=written)
        session.commit()

    td = _overview(EQUITY_INFO).trading_data

    assert td.perf_as_of == days[-2]


@pytest.mark.parametrize("last_dividend", [0, None, -1.0, "n/a"])
def test_a_zero_or_missing_dividend_omits_the_distribution_rows(env, last_dividend):
    engine, _ = env
    _put(engine, "GLD", "profile", [{**PROFILE, "lastDividend": last_dividend}])
    _put(engine, "GLD", "quote", [QUOTE])

    td = _overview(COMMODITY_INFO, "GLD").trading_data

    assert td.distribution_ttm_per_share is None and td.distribution_ttm_yield_pct is None
    assert td.week52_low == 555.6


def test_the_yield_falls_back_to_the_last_bar_close_when_no_quote_is_cached(env):
    engine, _ = env
    _put(engine, "QQQ", "profile", [{**PROFILE, "lastDividend": 2.0}])
    _flat_history(engine, "QQQ", last_close=200.0)

    td = _overview(EQUITY_INFO).trading_data

    assert td.distribution_ttm_yield_pct == pytest.approx(1.0)
    assert td.week52_low is None and td.week52_high is None  # no quote -> no range


def test_a_half_known_52_week_range_is_omitted(env):
    engine, _ = env
    _put(engine, "QQQ", "profile", [PROFILE])
    _put(engine, "QQQ", "quote", [{"price": 742.03, "yearLow": 555.6, "yearHigh": 0}])

    td = _overview(EQUITY_INFO).trading_data

    assert td.week52_low is None and td.week52_high is None


def test_profile_market_cap_is_never_exposed(env):
    engine, _ = env
    _put(engine, "QQQ", "profile", [PROFILE])
    td = _overview(EQUITY_INFO).trading_data
    assert "market_cap" not in td.model_dump() and 5e11 not in td.model_dump().values()


def test_every_row_omitted_means_no_block(env):
    engine, calls = env
    # Nothing cached at all: no profile, no quote, no bars.
    overview = _overview(COMMODITY_INFO, "GLD")
    assert overview.status == "ok" and overview.trading_data is None
    # The only FMP call is the on-demand daily-bar warm-up (failing here, which it swallows).
    assert set(calls) == {"get_historical_price_eod"}
    # A profile that only carries zeros / nothing usable is the same.
    _put(engine, "SLV", "profile", [{"isEtf": True, "beta": 0, "lastDividend": 0}])
    assert _overview(COMMODITY_INFO, "SLV").trading_data is None


def test_the_block_is_not_built_when_the_overview_is_not_ok(env):
    engine, _ = env
    _put(engine, "QQQ", "profile", [PROFILE])
    _flat_history(engine, "QQQ")
    INFO_RESPONSE["payload"] = []  # FMP has no fund record

    overview = asyncio.run(etf_data.get_etf_overview("QQQ"))

    assert overview.status == "no_data" and overview.trading_data is None


def test_reading_bars_never_writes_or_widens_the_shared_cache(env):
    engine, _ = env
    _put(engine, "QQQ", "profile", [PROFILE])
    _flat_history(engine, "QQQ")
    with Session(engine) as session:
        before = session.exec(select(shared_bars_cache.SharedBarsCache)).all()
    _overview(EQUITY_INFO)
    with Session(engine) as session:
        after = session.exec(select(shared_bars_cache.SharedBarsCache)).all()
    assert len(before) == len(after) and {r.fetched_at for r in before} == {r.fetched_at for r in after}


# --- on-demand daily-bar warm-up (2026-10-02): a viewed ETF with no/behind bars gets them fetched ----


def _record_bar_fetches(monkeypatch, engine, *, write_history=False, raise_error=False):
    fetches = []

    async def fake_get_or_fetch_bars(ticker, interval, lookback_days, **kwargs):
        fetches.append((ticker, interval, lookback_days))
        if raise_error:
            raise RuntimeError("FMP is down")
        if write_history:
            _flat_history(engine, ticker, last_close=110.0)

    monkeypatch.setattr(etf_data, "get_or_fetch_bars", fake_get_or_fetch_bars)
    return fetches


def test_an_etf_with_no_cached_bars_gets_them_fetched_so_the_block_is_not_empty(env, monkeypatch):
    engine, _ = env
    _put(engine, "QQQ", "profile", [PROFILE])
    fetches = _record_bar_fetches(monkeypatch, engine, write_history=True)

    td = _overview(EQUITY_INFO).trading_data

    assert fetches == [("QQQ", DAILY_INTERVAL, etf_data.TRADING_DATA_BAR_LOOKBACK_DAYS)]  # one fetch, daily bars
    assert td is not None and td.perf_1m == pytest.approx(10.0)


def test_current_bars_are_not_refetched(env, monkeypatch):
    engine, _ = env
    _flat_history(engine, "QQQ")
    fetches = _record_bar_fetches(monkeypatch, engine)

    _overview(EQUITY_INFO)

    assert fetches == []  # an ETF in the nightly universe always has current bars: zero extra calls


def test_bars_behind_the_last_completed_session_are_refreshed(env, monkeypatch):
    engine, _ = env
    completed = _most_recent_completed_trading_date()
    old_days = _session_days(300, completed - timedelta(days=25))  # an ETF that left the universe a while ago
    _bars(engine, "QQQ", {d: 100.0 for d in old_days})
    fetches = _record_bar_fetches(monkeypatch, engine)

    _overview(EQUITY_INFO)

    assert [f[0] for f in fetches] == ["QQQ"]


def test_a_failed_bar_fetch_never_breaks_the_overview(env, monkeypatch):
    engine, _ = env
    _put(engine, "QQQ", "profile", [PROFILE])
    fetches = _record_bar_fetches(monkeypatch, engine, raise_error=True)

    overview = _overview(EQUITY_INFO)

    assert fetches and overview.status == "ok"


def test_no_bar_fetch_when_the_overview_is_not_ok(env, monkeypatch):
    engine, _ = env
    fetches = _record_bar_fetches(monkeypatch, engine)
    INFO_RESPONSE["payload"] = []  # FMP answers [] -> no_data

    overview = asyncio.run(etf_data.get_etf_overview("AAPL"))

    assert overview.status != "ok" and fetches == []
