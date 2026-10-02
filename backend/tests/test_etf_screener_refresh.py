"""data/etf_screener_refresh.py + pipeline/nightly_etf_screener.py (docs/specs/etf-screener.md, step 4): every
computed field, the partial-write rule, seeds with nothing cached, fresh caches making no FMP call, per-ETF error
isolation, retention, and the cache_only / dry_run modes. No test touches the network or the real database: each
builds its own in-memory engine and patches it onto every module that reads, and any FMP client method not
explicitly faked raises."""

import asyncio
import json
from datetime import date, datetime, timedelta

import httpx
import pandas as pd
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import clients.shared_bars_cache as shared_bars_cache
import data.etf_data as etf_data
import data.etf_screener_refresh as refresh
import data.tracked_universe as tu
import pipeline.nightly_etf_screener as job
from analysis.trend_structure.weinstein import compute_weinstein_stage
from analysis.trend_structure.weinstein_pending import compute_weinstein_pending
from clients.fmp_client import fmp_client
from clients.shared_bars_cache import DAILY_INTERVAL, _most_recent_completed_trading_date, _write_rows
from core import data_groups
from core.models import (
    EtfScreenerRow,
    FundamentalsCache,
    TechnicalEntrySignal,
    TickerScore,
    TickerView,
    WarrenSignalEvent,
    Watchlist,
    WatchlistTicker,
)
from helpers.weinstein_config import load_weinstein_params

UPDATED_AT = "2026-10-01T23:07:10.015Z"
INFO = {"name": "Invesco QQQ Trust", "assetClass": "Equity", "expenseRatio": 0.18, "assetsUnderManagement": 498945995904,
        "updatedAt": UPDATED_AT}
PROFILE = {"companyName": "Invesco QQQ Trust, Series 1", "isEtf": True, "beta": 1.232}


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for module in (refresh, etf_data, tu, shared_bars_cache):
        monkeypatch.setattr(module, "engine", engine)
    state = {"fmp_calls": [], "batch_calls": [], "info": {}, "profile": {}, "batch_error": None, "bars_on_fetch": {}}

    async def get_etf_info(ticker):
        state["fmp_calls"].append(("etf_info", ticker))
        value = state["info"].get(ticker)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise AssertionError(f"unexpected /etf/info call for {ticker}")
        return value

    async def get_profile(ticker):
        state["fmp_calls"].append(("profile", ticker))
        value = state["profile"].get(ticker)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise AssertionError(f"unexpected /profile call for {ticker}")
        return value

    async def batch(tickers, interval, lookback_days, **kwargs):
        state["batch_calls"].append(list(tickers))
        if state["batch_error"] is not None:
            raise state["batch_error"]
        for ticker, closes in state["bars_on_fetch"].items():  # simulates the cache fill a live fetch performs
            _bars(engine, ticker, closes)
        return {}

    monkeypatch.setattr(fmp_client, "get_etf_info", get_etf_info)
    monkeypatch.setattr(fmp_client, "get_profile", get_profile)
    monkeypatch.setattr(refresh, "get_or_fetch_bars_batch", batch)
    state["engine"] = engine
    return state


# --- fixtures ---------------------------------------------------------------------------------------------


def _session_days(count: int, end: date) -> list[date]:
    days: list[date] = []
    day = end
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return sorted(days)


def _bars(engine, ticker, closes: dict[date, float]):
    index = pd.DatetimeIndex(sorted(closes))
    df = pd.DataFrame(
        {"open": 0.0, "high": 0.0, "low": 0.0, "close": [closes[d.date()] for d in index], "volume": 1_000_000}, index=index
    )
    with Session(engine) as session:
        # fetched "tomorrow": the last bar is never the provisional (written-before-close) kind
        _write_rows(session, ticker, DAILY_INTERVAL, df, fetched_at=datetime.now() + timedelta(days=1))
        session.commit()


def _history(last_close: float, sessions: int = 600, base: float = 100.0) -> dict[date, float]:
    """`base` for every session but the last, which closes at `last_close` (so 1Y = last/base - 1, 1D likewise)."""
    days = _session_days(sessions, _most_recent_completed_trading_date())
    closes = {d: base for d in days}
    closes[days[-1]] = last_close
    return closes


def _ramp(sessions: int = 1500) -> dict[date, float]:
    days = _session_days(sessions, _most_recent_completed_trading_date())
    return {d: 50.0 * (1.0004**i) for i, d in enumerate(days)}


def _cache(engine, ticker, statement_type, payload, age_days=0):
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker=ticker, statement_type=statement_type, period="latest",
                fetched_at=datetime.now() - timedelta(days=age_days), raw_json=json.dumps(payload),
            )
        )
        session.commit()


def _etf(engine, ticker, info=INFO, profile=PROFILE, viewed=True):
    _cache(engine, ticker, "profile", [dict(profile)])
    _cache(engine, ticker, "etf_info", [dict(info)])
    if viewed:
        with Session(engine) as session:
            session.add(TickerView(ticker=ticker, last_viewed_at=datetime.now()))
            session.commit()


def _row(engine, ticker) -> EtfScreenerRow | None:
    with Session(engine) as session:
        return session.get(EtfScreenerRow, ticker)


def _run(**kwargs):
    return asyncio.run(refresh.refresh_etf_screener(**kwargs))


# --- each computed field ----------------------------------------------------------------------------------


def test_every_field_is_computed_and_written_from_the_cached_data(env):
    engine = env["engine"]
    _etf(engine, "QQQ")
    _bars(engine, "QQQ", _history(120.0))
    _bars(engine, "SPY", _history(110.0))

    summary = _run(tickers=["QQQ"], cache_only=True)

    row = _row(engine, "QQQ")
    assert summary["written"] == 1 and summary["failed"] == 0
    assert row.name == "Invesco QQQ Trust, Series 1"  # the profile's name wins over /etf/info's
    assert row.asset_class == "Equity" and row.expense_ratio == 0.18 and row.aum == 498945995904
    assert row.info_updated_at == datetime(2026, 10, 1, 23, 7, 10, 15000)
    assert row.beta == 1.232
    assert row.last_price == 120.0
    assert row.pct_change_1d == pytest.approx(20.0)  # last two bars: 100 -> 120
    assert row.as_of_date == _most_recent_completed_trading_date()
    assert row.return_1y == pytest.approx(20.0)
    assert row.vs_spy_1y == pytest.approx(10.0)  # 20% minus SPY's 10%, percentage points
    assert row.updated_at is not None


def test_beta_is_stored_raw_even_for_a_bond_fund_and_zero_or_missing_is_not_stored(env):
    engine = env["engine"]
    _etf(engine, "TLT", info={"assetClass": "Fixed Income"}, profile={"companyName": "TLT", "beta": 2.4})
    _etf(engine, "ZERO", profile={"companyName": "Zero", "beta": 0})
    _etf(engine, "NONE", profile={"companyName": "None"})

    _run(tickers=["TLT", "ZERO", "NONE"], cache_only=True)

    assert _row(engine, "TLT").beta == 2.4  # the equity-only rule is applied on read, not here
    assert _row(engine, "ZERO").beta is None and _row(engine, "NONE").beta is None


def test_the_weinstein_fields_are_the_engines_output_with_the_live_settings(env):
    engine = env["engine"]
    _etf(engine, "XLK")
    _bars(engine, "XLK", _ramp())
    _bars(engine, "SPY", _ramp())

    _run(tickers=["XLK"], cache_only=True)

    bars = shared_bars_cache.read_cached_completed_daily_bars("XLK", refresh.WEINSTEIN_LOOKBACK_DAYS)
    benchmark = shared_bars_cache.read_cached_completed_daily_bars("SPY", refresh.WEINSTEIN_LOOKBACK_DAYS)
    with Session(engine) as session:
        params = load_weinstein_params(session)
    stage = compute_weinstein_stage(bars, benchmark, params)
    pending = compute_weinstein_pending(bars, params)
    row = _row(engine, "XLK")
    assert stage.stage is not None
    assert row.weinstein_stage == stage.stage
    assert row.weinstein_stage_since_date == stage.stage_since_date
    assert row.weinstein_stage_since_is_lower_bound == stage.stage_since_is_lower_bound
    assert row.weinstein_ma_slope_pct == stage.ma_slope_pct and row.weinstein_vs_ma_pct == stage.vs_ma_pct
    assert row.weinstein_pending_direction == pending.direction


def test_a_fund_with_too_little_history_gets_no_weinstein_fields_and_no_1y_return(env):
    engine = env["engine"]
    _etf(engine, "NEWETF")
    _bars(engine, "NEWETF", _history(105.0, sessions=40))
    _bars(engine, "SPY", _history(110.0))

    result = _run(tickers=["NEWETF"], cache_only=True)["results"]["NEWETF"]

    assert result.fields["last_price"] == 105.0 and result.fields["pct_change_1d"] == pytest.approx(5.0)
    assert "return_1y" not in result.fields and "vs_spy_1y" not in result.fields
    assert "weinstein_stage" not in result.fields
    assert any("Weinstein" in note for note in result.notes) and any("1Y" in note for note in result.notes)


def test_vs_spy_1y_is_left_out_and_logged_when_spy_has_no_bars(env, caplog):
    engine = env["engine"]
    _etf(engine, "QQQ")
    _bars(engine, "QQQ", _history(120.0))  # no SPY bars at all

    with caplog.at_level("WARNING"):
        result = _run(tickers=["QQQ"], cache_only=True)["results"]["QQQ"]

    assert result.fields["return_1y"] == pytest.approx(20.0)
    assert "vs_spy_1y" not in result.fields
    assert any("SPY bars missing" in note for note in result.notes)
    assert "SPY bars missing" in caplog.text
    assert _row(engine, "QQQ").vs_spy_1y is None


def test_vs_spy_1y_needs_spy_to_have_a_bar_on_the_etfs_own_as_of_date(env):
    engine = env["engine"]
    _etf(engine, "QQQ")
    _bars(engine, "QQQ", _history(120.0))
    spy = _history(110.0)
    del spy[max(spy)]  # SPY's newest bar is a session behind the ETF's
    _bars(engine, "SPY", spy)

    result = _run(tickers=["QQQ"], cache_only=True)["results"]["QQQ"]

    assert "vs_spy_1y" not in result.fields and any("SPY has no bar" in note for note in result.notes)


def test_spy_against_itself_is_zero(env):
    engine = env["engine"]
    _etf(engine, "SPY")
    _bars(engine, "SPY", _history(110.0))
    assert _run(tickers=["SPY"], cache_only=True)["results"]["SPY"].fields["vs_spy_1y"] == pytest.approx(0.0)


def test_signal_fields_are_read_from_the_monitored_job_tables_and_none_when_absent(env):
    engine = env["engine"]
    _etf(engine, "QQQ")
    _etf(engine, "GLD")
    fired = datetime.now() - timedelta(days=2)
    with Session(engine) as session:
        common = dict(timeframe="2h", fired_at=fired, source="fmp", as_of=fired, computed_at=fired)
        session.add(TechnicalEntrySignal(ticker="QQQ", signal_type="bb_rsi", **common))
        session.add(TechnicalEntrySignal(ticker="QQQ", signal_type="warren", signal_kind="blue_up", **common))
        session.add(WarrenSignalEvent(ticker="QQQ", timeframe="2h", signal_kind="blue_up", fired_at=fired, created_at=fired))
        session.commit()

    _run(tickers=["QQQ", "GLD"], cache_only=True)

    qqq, gld = _row(engine, "QQQ"), _row(engine, "GLD")
    assert qqq.bb_rsi_entry_signal is True and qqq.warren_active_signal_kind == "blue_up"
    assert qqq.warren_last_buy_fired_at == fired
    assert gld.bb_rsi_entry_signal is None and gld.warren_active_signal_kind is None and gld.warren_last_buy_fired_at is None


# --- partial writes ---------------------------------------------------------------------------------------


def test_a_transient_failure_never_overwrites_a_good_value_with_none(env):
    engine = env["engine"]
    _etf(engine, "QQQ")
    _bars(engine, "QQQ", _history(120.0))
    _bars(engine, "SPY", _history(110.0))
    _run(tickers=["QQQ"], cache_only=True)
    good = _row(engine, "QQQ").model_dump()

    # Next night: /etf/info and the profile are stale and FMP is down; no bars come back (empty cache).
    with Session(engine) as session:
        for row in session.exec(select(FundamentalsCache)).all():
            row.fetched_at = datetime.now() - timedelta(days=90)
            session.add(row)
        session.commit()
        for row in session.exec(select(shared_bars_cache.SharedBarsCache)).all():
            session.delete(row)
        session.commit()
    env["info"]["QQQ"] = httpx.ConnectError("down")
    env["profile"]["QQQ"] = httpx.ConnectError("down")

    summary = _run(tickers=["QQQ"])

    kept = _row(engine, "QQQ").model_dump()
    for column in ("asset_class", "expense_ratio", "aum", "name", "beta", "last_price", "pct_change_1d", "return_1y", "vs_spy_1y", "as_of_date"):
        assert kept[column] == good[column], column
    assert summary["failed"] == 1 and summary["results"]["QQQ"].errors  # reported, not hidden


def test_a_stale_cached_info_row_is_still_used_when_the_refetch_fails(env):
    engine = env["engine"]
    _cache(engine, "QQQ", "etf_info", [dict(INFO)], age_days=10)
    _cache(engine, "QQQ", "profile", [dict(PROFILE)])
    env["info"]["QQQ"] = httpx.ConnectError("down")

    result = _run(tickers=["QQQ"])["results"]["QQQ"]

    assert result.fields["asset_class"] == "Equity"  # the stale row, better than nothing
    assert any("etf_info fetch failed" in e for e in result.errors)


# --- seeds with nothing cached, fresh caches --------------------------------------------------------------


def test_seeds_with_no_profile_or_info_row_are_fetched_through_the_normal_paths(env):
    engine = env["engine"]
    for seed in ("XLB", "XLC"):
        env["info"][seed] = [{"name": f"{seed} SPDR", "assetClass": "Equity", "expenseRatio": 0.08, "updatedAt": UPDATED_AT}]
        env["profile"][seed] = [{"companyName": f"{seed} Fund", "isEtf": True, "beta": 1.1}]
        env["bars_on_fetch"][seed] = _history(105.0)
    env["bars_on_fetch"]["SPY"] = _history(110.0)

    summary = _run(tickers=["XLB", "XLC"])

    assert sorted(env["fmp_calls"]) == [("etf_info", "XLB"), ("etf_info", "XLC"), ("profile", "XLB"), ("profile", "XLC")]
    assert set(env["batch_calls"][0]) >= {"XLB", "XLC", "SPY"}  # one batch, SPY riding along
    for seed in ("XLB", "XLC"):
        row = _row(engine, seed)
        assert row.name == f"{seed} Fund" and row.asset_class == "Equity" and row.last_price == 105.0
        assert row.vs_spy_1y == pytest.approx(5.0 - 10.0)
    assert summary["written"] == 2 and summary["failed"] == 0
    with Session(engine) as session:  # the profile is cached now, so each seed is a known ETF from here on
        assert tu.partition_known_tickers(session)[1] >= {"XLB", "XLC"}


def test_seeds_with_nothing_cached_write_no_row_in_cache_only_mode(env):
    result = _run(tickers=["XLB"], cache_only=True)

    assert env["fmp_calls"] == [] and env["batch_calls"] == []
    assert result["results"]["XLB"].fields.get("asset_class") is None
    assert _row(env["engine"], "XLB") is None
    assert any("no /etf/info cached" in n for n in result["results"]["XLB"].notes)
    assert any("no profile cached" in n for n in result["results"]["XLB"].notes)


def test_a_fresh_cache_makes_no_fmp_call_for_info_or_profile(env):
    engine = env["engine"]
    _etf(engine, "QQQ")  # fetched just now: inside the 1-day /etf/info and 30-day profile windows
    _bars(engine, "QQQ", _history(120.0))

    summary = _run(tickers=["QQQ"])  # live mode

    assert env["fmp_calls"] == []  # the fakes would have raised AssertionError otherwise
    assert summary["failed"] == 0 and _row(engine, "QQQ").asset_class == "Equity"


def test_the_real_bar_cache_makes_no_fetch_for_a_current_wide_cache(env, monkeypatch):
    """The bars path is the existing get_or_fetch_bars_batch: a current, wide-enough cache is a no-fetch."""
    engine = env["engine"]
    monkeypatch.setattr(refresh, "get_or_fetch_bars_batch", shared_bars_cache.get_or_fetch_bars_batch)
    fetches = []

    class Source:
        async def get_daily_bars(self, tickers, *a, **k):
            fetches.append(list(tickers))
            return {}

    monkeypatch.setattr(shared_bars_cache, "get_daily_bar_source", lambda: Source())
    _etf(engine, "QQQ")
    for ticker in ("QQQ", "SPY"):
        _bars(engine, ticker, _ramp(1500))

    _run(tickers=["QQQ"])

    assert fetches == []


# --- isolation, retention ---------------------------------------------------------------------------------


def test_one_etf_failing_does_not_abort_the_run(env, monkeypatch):
    engine = env["engine"]
    for ticker in ("QQQ", "GLD", "SMH"):
        _etf(engine, ticker)
    real = refresh.upsert_etf_screener_row

    def flaky(session, ticker, *a, **k):
        if ticker == "GLD":
            raise RuntimeError("disk is full")
        return real(session, ticker, *a, **k)

    monkeypatch.setattr(refresh, "upsert_etf_screener_row", flaky)

    summary = _run(tickers=["QQQ", "GLD", "SMH"], cache_only=True)

    assert summary["processed"] == 3 and summary["written"] == 2 and summary["failed"] == 1
    assert summary["failures"][0][0] == "GLD"
    assert _row(engine, "QQQ") is not None and _row(engine, "SMH") is not None and _row(engine, "GLD") is None


def test_one_source_raising_costs_only_its_own_fields(env, monkeypatch):
    engine = env["engine"]
    _etf(engine, "QQQ")
    _bars(engine, "QQQ", _history(120.0))

    async def broken(*a, **k):
        raise RuntimeError("profile parser blew up")

    monkeypatch.setattr(refresh, "_profile_fields", broken)

    result = _run(tickers=["QQQ"], cache_only=True)["results"]["QQQ"]

    assert result.fields["asset_class"] == "Equity" and result.fields["last_price"] == 120.0
    assert "beta" not in result.fields and any(e.startswith("profile:") for e in result.errors)


def _seed_universe_state(engine):
    """QQQ viewed (in), OLD an ETF unviewed for 90 days (expired), plus stored rows for both, a delisted ETF and
    a non-ETF."""
    _etf(engine, "QQQ")
    _etf(engine, "OLD", viewed=False)
    with Session(engine) as session:
        session.add(TickerView(ticker="OLD", last_viewed_at=datetime.now() - timedelta(days=90)))
        _etf_delisted = FundamentalsCache(
            ticker="GONE", statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json='{"isEtf": true}'
        )
        session.add(_etf_delisted)
        session.add(TickerScore(ticker="GONE", computed_at=datetime.now(), delisted_at=datetime.now()))
        for ticker in ("QQQ", "OLD", "GONE", "AAPL", "XLE"):
            session.add(EtfScreenerRow(ticker=ticker, name=ticker))
        session.commit()
    env_info = {"name": "x"}
    return env_info


def _all_info_ok(env):
    for ticker in tu.ETF_SEED_TICKERS:
        env["info"][ticker] = [dict(INFO)]
        env["profile"][ticker] = [dict(PROFILE)]


def _rows(engine):
    with Session(engine) as session:
        return sorted(session.exec(select(EtfScreenerRow.ticker)).all())


def test_a_successful_run_prunes_rows_that_left_the_etf_universe(env):
    engine = env["engine"]
    _seed_universe_state(engine)
    _all_info_ok(env)

    summary = _run()

    assert summary["fetch_ok"] is True and summary["pruned"] == 3
    # QQQ and the seeds that were written stay; OLD (expired), GONE (delisted) and AAPL (not an ETF) are deleted.
    assert "OLD" not in _rows(engine) and "GONE" not in _rows(engine) and "AAPL" not in _rows(engine)
    assert "QQQ" in _rows(engine) and "XLE" in _rows(engine)


def test_no_prune_when_the_batch_bar_fetch_failed(env):
    engine = env["engine"]
    _seed_universe_state(engine)
    _all_info_ok(env)
    env["batch_error"] = RuntimeError("FMP bars down")

    summary = _run()

    assert summary["batch_failed"] is True and summary["fetch_ok"] is False and summary["pruned"] == 0
    assert {"OLD", "GONE", "AAPL"} <= set(_rows(engine))  # nothing deleted
    assert summary["written"] > 0  # the rest of the run still happened


def test_no_prune_when_most_etfs_failed_their_fetches(env):
    engine = env["engine"]
    _seed_universe_state(engine)
    for ticker in tu.ETF_SEED_TICKERS | {"QQQ"}:
        env["info"][ticker] = httpx.ConnectError("down")
        env["profile"][ticker] = httpx.ConnectError("down")
    with Session(engine) as session:  # stale caches so the fetch is attempted
        for row in session.exec(select(FundamentalsCache)).all():
            row.fetched_at = datetime.now() - timedelta(days=90)
            session.add(row)
        session.commit()

    summary = _run()

    assert summary["failed"] == summary["processed"] and summary["fetch_ok"] is False and summary["pruned"] == 0
    assert {"OLD", "GONE", "AAPL"} <= set(_rows(engine))


def test_prune_never_runs_for_an_explicit_ticker_list_cache_only_or_dry_run(env):
    engine = env["engine"]
    _seed_universe_state(engine)
    _all_info_ok(env)
    before = _rows(engine)

    _run(tickers=["QQQ"])
    _run(cache_only=True)
    dry = _run(dry_run=True)

    assert {"OLD", "GONE", "AAPL"} <= set(_rows(engine))
    assert dry["would_prune"] == 3 and dry["pruned"] == 0
    assert set(before) <= set(_rows(engine))


# --- modes ------------------------------------------------------------------------------------------------


def test_cache_only_makes_no_network_call_at_all(env, monkeypatch):
    engine = env["engine"]
    _etf(engine, "QQQ")
    _etf(engine, "TLT", info={"assetClass": "Fixed Income"})
    _bars(engine, "QQQ", _history(120.0))
    # Stale caches: a live run WOULD fetch these; cache_only must serve them as they are.
    with Session(engine) as session:
        for row in session.exec(select(FundamentalsCache)).all():
            row.fetched_at = datetime.now() - timedelta(days=90)
            session.add(row)
        session.commit()
    # Any transport use is a failure, not just the faked client methods.
    def no_network(*a, **k):
        raise AssertionError("network used in cache_only mode")

    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    monkeypatch.setattr(httpx.AsyncClient, "request", no_network)

    summary = _run(cache_only=True)

    assert env["fmp_calls"] == [] and env["batch_calls"] == []
    assert summary["failed"] == 0 and summary["written"] >= 2
    assert _row(engine, "QQQ").asset_class == "Equity" and _row(engine, "TLT").asset_class == "Fixed Income"


def test_dry_run_computes_everything_and_writes_no_screener_row(env):
    engine = env["engine"]
    _etf(engine, "QQQ")
    _bars(engine, "QQQ", _history(120.0))
    _bars(engine, "SPY", _history(110.0))

    summary = _run(tickers=["QQQ"], cache_only=True, dry_run=True)

    assert summary["written"] == 0 and summary["dry_run"] is True
    assert summary["results"]["QQQ"].fields["vs_spy_1y"] == pytest.approx(10.0)
    assert _rows(engine) == []


def test_main_skips_while_daily_prices_is_off_and_a_dry_run_never_calls_init_db(env, monkeypatch):
    monkeypatch.setattr(job, "init_db", lambda: pytest.fail("a dry run must not run init_db"))
    monkeypatch.setattr(job, "configure_logging", lambda *_: pytest.fail("a dry run must not set up the log file"))
    out = asyncio.run(job.main(["QQQ"], cache_only=True, dry_run=True))
    assert out["dry_run"] is True

    monkeypatch.setattr(job, "init_db", lambda: None)
    monkeypatch.setattr(job, "configure_logging", lambda *_: None)
    data_groups.set_group_enabled("daily_prices", False)
    skipped = asyncio.run(job.main(["QQQ"]))
    assert skipped["skipped"] is True and "daily_prices" in skipped["skip_reason"]
    assert env["fmp_calls"] == [] and env["batch_calls"] == []
    # cache_only does not need the group, so it is not skipped
    assert "skipped" not in asyncio.run(job.main(["QQQ"], cache_only=True, dry_run=True))


def test_load_etf_info_with_cache_only_never_calls_fmp(env):
    engine = env["engine"]
    _cache(engine, "QQQ", "etf_info", [dict(INFO)], age_days=30)

    stale = asyncio.run(etf_data.load_etf_info("QQQ", cache_only=True))
    missing = asyncio.run(etf_data.load_etf_info("TLT", cache_only=True))

    assert stale.payload is not None and stale.failed is False and stale.fetched_at is not None
    assert missing.payload is None and missing.failed is False
    assert env["fmp_calls"] == []


def test_the_universe_is_the_default_target_and_includes_watchlisted_etfs(env):
    engine = env["engine"]
    _etf(engine, "GLD", viewed=False)
    with Session(engine) as session:
        watchlist = Watchlist(name="ETF", created_at=datetime.now(), updated_at=datetime.now())
        session.add(watchlist)
        session.commit()
        session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker="GLD", added_at=datetime.now()))
        session.commit()

    summary = _run(cache_only=True, dry_run=True)

    assert set(summary["results"]) == set(tu.ETF_SEED_TICKERS) | {"GLD"}


def test_etf_info_name_is_only_a_fallback_for_a_missing_profile_name(env):
    engine = env["engine"]
    _etf(engine, "A", info={"name": "Info Name", "assetClass": "Equity"}, profile={"companyName": "Profile Name"})
    _etf(engine, "B", info={"name": "Info Name", "assetClass": "Equity"}, profile={"isEtf": True})  # profile has no name

    _run(tickers=["A", "B"], cache_only=True)

    assert _row(engine, "A").name == "Profile Name"
    assert _row(engine, "B").name == "Info Name"


def test_an_existing_row_has_its_ended_signal_cleared_but_a_row_is_never_created_from_signals_alone(env):
    engine = env["engine"]
    with Session(engine) as session:
        session.add(EtfScreenerRow(ticker="QQQ", bb_rsi_entry_signal=True, warren_active_signal_kind="blue_up"))
        session.commit()

    result = _run(tickers=["QQQ", "XLB"], cache_only=True)

    assert _row(engine, "QQQ").bb_rsi_entry_signal is None and _row(engine, "QQQ").warren_active_signal_kind is None
    assert _row(engine, "XLB") is None and result["results"]["XLB"].written is False
