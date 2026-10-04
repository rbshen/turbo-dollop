"""The Chart tab's 2H_90D range (data/chart_data.py::_get_chart_data_2h): last 90 calendar days of 2h session
candles, with Warren/BB+RSI/LP all computed on demand from one full-history candle series.

Isolation: every module this range reads from gets its own fresh in-memory engine (chart_data for the LP
settings row, shared_bars_cache for the cached-ticker check) -- see CLAUDE.md, "Ad-hoc reproduction scripts
must not touch the real database". The bar sources themselves are monkeypatched, so no test makes an FMP call."""

from datetime import date, datetime, timedelta, timezone

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import clients.shared_bars_cache as shared_bars_cache
import core.main as main
import data.chart_data as chart_data
from analysis.entry_signal.indicators import check_buy_signal, compute_bollinger_bands, compute_rsi
from analysis.entry_signal.resample import build_2h_session_candles_fast, drop_forming_candles, index_by_window_start
from analysis.warren_signal import indicators as wi
from analysis.warren_signal.state_machine import replay_with_series, warren_reference_levels
from core.models import SharedBarsCache
from data.liquidity_zone_data import compute_liquidity_zones_2h
from helpers.liquidity_zone_config import get_liquidity_zone_settings, to_engine_settings

_NY = "America/New_York"
KEY = "2H_90D"


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(autouse=True)
def _isolated_engines(monkeypatch):
    monkeypatch.setattr(chart_data, "engine", _engine())
    monkeypatch.setattr(shared_bars_cache, "engine", _engine())


def _bars_60m(end_day: str, sessions: int = 520, seed: int = 1) -> pd.DataFrame:
    """Synthetic regular-session 60m bars (09:30..15:30, tz-aware ET), `sessions` weekdays ending at end_day. A
    slow wave plus noise: long enough for every indicator to settle and rich enough to fire Warren arrows
    of several kinds and BB+RSI in the last 90 days."""
    rng = np.random.default_rng(seed)
    rows, price, k = [], 100.0, 0
    for d in pd.bdate_range(end=end_day, periods=sessions):
        for h in range(7):
            k += 1
            o = price
            c = max(5.0, o * (1 + rng.normal(0, 0.004) + 0.003 * np.sin(k / 55)))
            rows.append((pd.Timestamp(f"{d:%Y-%m-%d} {9 + h}:30", tz=_NY), o, max(o, c) * 1.001, min(o, c) * 0.999, c, 1000))
            price = c
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")


NOW = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)  # Fri 10:00 ET, before the session's first 2h candle completes
LAST_SESSION = "2026-10-01"


def _patch_source(monkeypatch, raw: pd.DataFrame):
    async def fake(ticker, now):
        return raw

    monkeypatch.setattr(chart_data, "_fetch_intraday_bars", fake)


def _full_candles(raw: pd.DataFrame, now: datetime = NOW) -> pd.DataFrame:
    return index_by_window_start(drop_forming_candles(build_2h_session_candles_fast(raw), now))


def _run(coro_fn, *args, **kw):
    import asyncio

    return asyncio.run(coro_fn(*args, **kw))


@pytest.fixture
def raw():
    return _bars_60m(LAST_SESSION)


# --- config / wiring -----------------------------------------------------------------------------------------


def test_range_config_and_nightly_window_stay_in_lockstep():
    import pipeline.nightly_warren_signal_calculation as nightly

    cfg = chart_data.RANGE_CONFIG[KEY]
    assert cfg["timeframe"] == "2h" and cfg["visible_days"] == 90
    assert cfg["lookback_days"] == nightly.LOOKBACK_DAYS == 730  # on-demand Warren replays the nightly job's window


# --- candles ---------------------------------------------------------------------------------------------------


def test_bars_are_the_last_90_days_of_candles_stamped_with_the_window_start(monkeypatch, raw):
    _patch_source(monkeypatch, raw)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW)

    assert out.range == KEY and out.timeframe == "2h" and out.source == "fmp" and out.chart_available is True
    times = [b.time for b in out.bars]
    assert all(len(t) == 19 and t[10] == "T" for t in times)  # naive-ET ISO, no offset
    assert {t[11:] for t in times} == {"09:30:00", "11:30:00", "13:30:00", "15:30:00"}
    assert times == sorted(times) and len(set(times)) == len(times)
    visible_start = pd.Timestamp("2026-10-02") - pd.Timedelta(days=90)
    assert pd.Timestamp(times[0]) >= visible_start and pd.Timestamp(times[0]) < visible_start + pd.Timedelta(days=4)
    assert times[-1] == f"{LAST_SESSION}T15:30:00"
    assert 240 <= len(times) <= 260  # ~63 sessions x 4 candles


def test_ohlc_values_match_the_vectorised_builder(monkeypatch, raw):
    _patch_source(monkeypatch, raw)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW)
    candles = _full_candles(raw).set_index(pd.DatetimeIndex(_full_candles(raw).index))
    last = out.bars[-1]
    row = candles.loc[pd.Timestamp(last.time)]
    assert (last.open, last.high, last.low, last.close) == (row["open"], row["high"], row["low"], row["close"])


def test_skipped_pieces_are_empty_and_existing_fields_are_not_overloaded(monkeypatch, raw):
    _patch_source(monkeypatch, raw)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW)
    assert out.ema21 == out.sma50 == out.sma200 == out.bollinger == out.stochastic == out.rsi == []
    assert out.earnings_markers == [] and out.dividend_markers == [] and out.events_source is None
    assert out.weinstein_ma == [] and out.weinstein_stages == []
    assert out.entry_signal_available and out.warren_signal_available and out.zones_available  # true whenever bars exist


# --- Warren: same engine, same series, full-history replay then slice -----------------------------------------


def test_warren_series_are_the_engines_own_sliced_to_the_window(monkeypatch, raw):
    _patch_source(monkeypatch, raw)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW)
    candles = _full_candles(raw)
    _, series = replay_with_series(candles)
    start = pd.Timestamp(out.bars[0].time)

    for field, expected in [
        ("warren_rsi", series.rsi),
        ("warren_adx", series.adx),
        ("warren_plus_di", series.plus_di),
        ("warren_minus_di", series.minus_di),
        ("warren_wvf", series.wvf),
    ]:
        pts = getattr(out, field)
        exp = expected[candles.index >= start].dropna()
        assert [p.time for p in pts] == [t.strftime("%Y-%m-%dT%H:%M:%S") for t in exp.index], field
        np.testing.assert_array_equal([p.value for p in pts], exp.to_numpy())
    assert out.warren_levels is not None and out.warren_levels.model_dump() == warren_reference_levels()
    assert out.warren_levels.rsi == [12.0, 30.0, 70.0, 80.81, 84.75] and out.warren_levels.adx == [40.0] and out.warren_levels.wvf == [0.4]


def test_warren_markers_come_from_a_full_replay_not_a_90_day_one(monkeypatch, raw):
    _patch_source(monkeypatch, raw)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW)
    candles = _full_candles(raw)
    result, _ = replay_with_series(candles)
    visible_start = pd.Timestamp("2026-10-02") - pd.Timedelta(days=90)

    expected = sorted((e.fired_at.strftime("%Y-%m-%dT%H:%M:%S"), e.kind) for e in result.events if pd.Timestamp(e.fired_at) >= visible_start)
    assert expected, "fixture must fire Warren arrows in the window"
    assert [(m.time, m.kind) for m in out.warren_signal_markers] == expected
    assert {m.kind for m in out.warren_signal_markers} <= {"blue_up", "yellow_up", "gray_up", "blue_down", "yellow_down", "gray_down"}
    assert all(m.label for m in out.warren_signal_markers)

    # Replaying only the visible window would NOT give the same arrows (the state machine is warm-up sensitive) --
    # which is exactly why the endpoint replays everything and slices afterwards.
    cut = candles[candles.index >= visible_start]
    cut_result, _ = replay_with_series(cut)
    cut_events = sorted((e.fired_at.strftime("%Y-%m-%dT%H:%M:%S"), e.kind) for e in cut_result.events)
    assert cut_events != expected


def test_every_marker_sits_on_an_exact_candle_start(monkeypatch, raw):
    _patch_source(monkeypatch, raw)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW)
    bar_times = {b.time for b in out.bars}
    assert {m.time for m in out.warren_signal_markers} <= bar_times
    assert {m.time for m in out.entry_signal_markers} <= bar_times
    assert {z.formed_at for z in out.zones} <= bar_times


# --- BB+RSI: one marker per candle ----------------------------------------------------------------------------


def test_bb_rsi_marks_every_firing_candle_without_per_day_dedup(monkeypatch):
    # A sharp, sustained selloff over the last three sessions: RSI stays oversold and %B stays at the lower
    # band, so consecutive candles of the SAME day all satisfy the condition.
    base = _bars_60m("2026-09-28", sessions=519)
    last_close = float(base["close"].iloc[-1])
    rows, price = [], last_close
    for d in pd.bdate_range("2026-09-29", "2026-10-01"):
        for h in range(7):
            o, c = price, price * 0.985
            rows.append((pd.Timestamp(f"{d:%Y-%m-%d} {9 + h}:30", tz=_NY), o, o * 1.001, c * 0.999, c, 1000))
            price = c
    raw = pd.concat([base, pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")])
    _patch_source(monkeypatch, raw)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW)

    candles = _full_candles(raw)
    rsi = compute_rsi(candles["close"])
    _, _, pct_b = compute_bollinger_bands(candles["close"])
    visible_start = pd.Timestamp("2026-10-02") - pd.Timedelta(days=90)
    expected = [candles.index[i].strftime("%Y-%m-%dT%H:%M:%S") for i in range(len(candles)) if candles.index[i] >= visible_start and check_buy_signal(rsi, pct_b, i)]
    assert [m.time for m in out.entry_signal_markers] == expected
    assert all(m.kind == "bb_rsi" and m.label == "BB+RSI" for m in out.entry_signal_markers)
    days = [t[:10] for t in expected]
    assert len(days) > len(set(days)), "several firing candles share a day and each keeps its own marker"


# --- LP: full-history compute, cap then filter, window rule --------------------------------------------------


def test_zones_are_the_full_history_read_filtered_to_swings_inside_the_window(monkeypatch, raw):
    _patch_source(monkeypatch, raw)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW)
    candles = _full_candles(raw)
    with Session(chart_data.engine) as session:
        settings = to_engine_settings(get_liquidity_zone_settings(session))
    result = compute_liquidity_zones_2h(candles, settings)
    start = pd.Timestamp(out.bars[0].time)
    visible_start = pd.Timestamp("2026-10-02") - pd.Timedelta(days=90)

    expect = [(s, z.price, z.formed_ts.strftime("%Y-%m-%dT%H:%M:%S"), False) for s, zs in (("support", result.support), ("resistance", result.resistance)) for z in zs if z.formed_ts >= visible_start]
    expect += [(s, b.price, b.formed_ts.strftime("%Y-%m-%dT%H:%M:%S"), True) for s, b in (("support", result.broken_support), ("resistance", result.broken_resistance)) if b is not None and b.formed_ts >= visible_start]
    assert expect
    assert sorted((z.side, z.price, z.formed_at, z.broken) for z in out.zones) == sorted(expect)
    assert all(pd.Timestamp(z.formed_at) >= start - pd.Timedelta(days=4) for z in out.zones)


def test_zone_window_filter_drops_swings_before_the_window_and_keeps_boundary_candle():
    from analysis.liquidity_zones.types import BrokenZone, LiquidityZoneResult, Zone

    vs = pd.Timestamp("2026-07-04")
    z = lambda p, ts: Zone(price=p, cluster_size=1, formed_at=ts.date(), formed_ts=ts.to_pydatetime())  # noqa: E731
    result = LiquidityZoneResult(
        last_price=100.0,
        as_of=date(2026, 10, 1),
        support=[z(99.0, pd.Timestamp("2026-07-03 15:30")), z(98.0, pd.Timestamp("2026-07-04 09:30"))],
        resistance=[z(101.0, pd.Timestamp("2026-09-01 11:30"))],
        broken_support=BrokenZone(price=97.0, formed_at=date(2026, 6, 1), breached_at=date(2026, 9, 30), formed_ts=datetime(2026, 6, 1, 9, 30)),
        broken_resistance=BrokenZone(price=102.0, formed_at=date(2026, 8, 1), breached_at=date(2026, 9, 30), formed_ts=datetime(2026, 8, 1, 13, 30)),
    )
    zones = chart_data._zones_2h(result, vs)
    assert [(x.side, x.price, x.formed_at, x.broken) for x in zones] == [
        ("support", 98.0, "2026-07-04T09:30:00", False),
        ("resistance", 101.0, "2026-09-01T11:30:00", False),
        ("resistance", 102.0, "2026-08-01T13:30:00", True),
    ]


# --- forming candle ------------------------------------------------------------------------------------------


def _with_today(raw: pd.DataFrame, bars: list[str], close: float = 500.0) -> pd.DataFrame:
    rows = [(pd.Timestamp(f"2026-10-01 {b}", tz=_NY), close, close * 1.01, close * 0.99, close, 1000) for b in bars]
    return pd.concat([raw, pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")])


@pytest.mark.parametrize(
    "now_et,bars,expect_last",
    [
        ("10:45", ["09:30"], "2026-09-30T15:30:00"),  # the 09:30 candle is still forming
        ("11:29", ["09:30", "10:30"], "2026-09-30T15:30:00"),  # both bars in, but the window has not ended
        ("11:35", ["09:30", "10:30"], "2026-10-01T09:30:00"),  # complete
        ("11:35", ["09:30"], "2026-09-30T15:30:00"),  # clock done, provider has not delivered the 10:30 bar
        ("13:45", ["09:30", "10:30", "11:30", "12:30", "13:30"], "2026-10-01T11:30:00"),  # 13:30 candle forming
    ],
)
def test_forming_candle_is_dropped_from_display_and_from_every_computation(monkeypatch, now_et, bars, expect_last):
    base = _bars_60m("2026-09-30")
    raw_today = _with_today(base, bars)
    now = pd.Timestamp(f"2026-10-01 {now_et}", tz=_NY).to_pydatetime().astimezone(timezone.utc)
    _patch_source(monkeypatch, raw_today)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, now)
    assert out.bars[-1].time == expect_last

    # Dropping the forming candle must make the response identical to one computed with the extreme bars absent
    # entirely: no indicator, arrow or zone saw it.
    complete = drop_forming_candles(build_2h_session_candles_fast(raw_today), now)
    reference_raw = raw_today[raw_today.index <= pd.Timestamp(complete.index[-1]).tz_convert(_NY)]
    _patch_source(monkeypatch, reference_raw)
    ref = _run(chart_data._get_chart_data_2h, "AAPL", KEY, now)
    assert out.model_dump() == ref.model_dump()


def test_a_completed_candle_with_a_wild_close_is_kept_and_does_move_the_indicators(monkeypatch):
    raw_today = _with_today(_bars_60m("2026-09-30"), ["09:30", "10:30"], close=500.0)
    now = pd.Timestamp("2026-10-01 11:35", tz=_NY).to_pydatetime().astimezone(timezone.utc)
    _patch_source(monkeypatch, raw_today)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, now)
    assert out.bars[-1].close == 500.0 and out.warren_rsi[-1].time == "2026-10-01T09:30:00"


# --- bar sources ---------------------------------------------------------------------------------------------


def _rows_for(raw: pd.DataFrame, a: str, b: str) -> list[dict]:
    sel = raw[(raw.index.date >= date.fromisoformat(a)) & (raw.index.date <= date.fromisoformat(b))]
    return [
        {"date": ts.strftime("%Y-%m-%d %H:%M:%S"), "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume}
        for ts, r in sel.iloc[::-1].iterrows()
    ]


def test_cached_ticker_reads_through_the_shared_cache_and_never_fetches_directly(monkeypatch, raw):
    calls = []

    async def fake_batch(tickers, interval, lookback_days, auto_adjust=False, reference=None, **kw):
        calls.append((tickers, interval, lookback_days, auto_adjust))
        return {"AAPL": raw}

    async def no_direct(*a, **k):
        raise AssertionError("a cached ticker must not use the direct fetch")

    monkeypatch.setattr(chart_data, "has_cached_bars", lambda t, i: True)
    monkeypatch.setattr(chart_data, "get_or_fetch_bars_batch", fake_batch)
    monkeypatch.setattr(chart_data.fmp_client, "get_historical_chart_1hour", no_direct)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW)
    assert calls == [(["AAPL"], "60m", 730, False)] and out.chart_available


def test_uncached_ticker_fetches_parallel_90_day_windows_and_writes_nothing(monkeypatch, raw):
    calls = []

    async def fake_hour(ticker, a, b):
        calls.append((ticker, a, b))
        return _rows_for(raw, a, b)

    monkeypatch.setattr(chart_data.fmp_client, "get_historical_chart_1hour", fake_hour)
    out = _run(chart_data._get_chart_data_2h, "KO", KEY, NOW)

    assert out.chart_available and out.bars[-1].time == f"{LAST_SESSION}T15:30:00"
    today = date(2026, 10, 2)
    assert calls[0][1] == (today - timedelta(days=729)).isoformat() and calls[-1][2] == today.isoformat()
    assert len(calls) == 9  # 730 days / 90-day windows
    assert all(date.fromisoformat(b) - date.fromisoformat(a) <= timedelta(days=90) for _, a, b in calls)
    assert all(calls[i][2] == calls[i + 1][1] for i in range(len(calls) - 1))  # contiguous, boundary date shared
    with Session(shared_bars_cache.engine) as session:
        assert session.exec(select(SharedBarsCache)).all() == []  # nothing persisted for a viewed-only ticker

    # Boundary-day duplicates collapse: the result equals the cached-path result on the same bars.
    _patch_source(monkeypatch, raw)
    same = _run(chart_data._get_chart_data_2h, "KO", KEY, NOW)
    assert out.model_dump() == same.model_dump()


def test_uncached_fetch_is_all_or_nothing(monkeypatch, raw):
    async def flaky(ticker, a, b):
        if a >= "2025-12-01" and a < "2026-02-01":
            raise httpx.ReadTimeout("boom")
        return _rows_for(raw, a, b)

    monkeypatch.setattr(chart_data.fmp_client, "get_historical_chart_1hour", flaky)
    out = _run(chart_data._get_chart_data_2h, "KO", KEY, NOW)
    assert out.chart_available is False and out.bars == []
    assert not (out.entry_signal_available or out.warren_signal_available or out.zones_available)


def test_uncached_non_list_or_empty_answers_are_unavailable(monkeypatch):
    async def err(ticker, a, b):
        return {"Error Message": "x"}

    monkeypatch.setattr(chart_data.fmp_client, "get_historical_chart_1hour", err)
    assert _run(chart_data._get_chart_data_2h, "KO", KEY, NOW).chart_available is False

    async def empty(ticker, a, b):
        return []

    monkeypatch.setattr(chart_data.fmp_client, "get_historical_chart_1hour", empty)
    assert _run(chart_data._get_chart_data_2h, "KO", KEY, NOW).chart_available is False


def test_intraday_group_off_uncached_is_unavailable_with_no_fmp_call(monkeypatch, raw):
    from core import data_groups

    async def no_call(*a, **k):
        raise AssertionError("group off: no FMP call")

    data_groups.set_group_enabled("intraday_bars", False)
    monkeypatch.setattr(chart_data.fmp_client, "get_historical_chart_1hour", no_call)
    out = _run(chart_data._get_chart_data_2h, "KO", KEY, NOW)
    assert out.chart_available is False


def test_intraday_group_off_cached_ticker_still_serves_the_cached_bars(monkeypatch, raw):
    from core import data_groups

    data_groups.set_group_enabled("intraday_bars", False)
    seen = []

    async def fake_batch(tickers, interval, lookback_days, **kw):  # the cache itself serves rows as they are while the group is off
        seen.append(tickers)
        return {"AAPL": raw}

    monkeypatch.setattr(chart_data, "has_cached_bars", lambda t, i: True)
    monkeypatch.setattr(chart_data, "get_or_fetch_bars_batch", fake_batch)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW)
    assert seen == [["AAPL"]] and out.chart_available


def test_has_cached_bars_reflects_the_shared_cache():
    assert shared_bars_cache.has_cached_bars("AAPL", "60m") is False
    with Session(shared_bars_cache.engine) as session:
        session.add(SharedBarsCache(ticker="AAPL", interval="60m", bar_time=datetime(2026, 10, 1, 15, 30), open=1, high=1, low=1, close=1, volume=1, fetched_at=datetime(2026, 10, 2), source="fmp"))
        session.commit()
    assert shared_bars_cache.has_cached_bars("AAPL", "60m") is True
    assert shared_bars_cache.has_cached_bars("AAPL", "1d") is False and shared_bars_cache.has_cached_bars("MSFT", "60m") is False


def test_source_failure_degrades_to_unavailable_not_an_exception(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db gone")

    monkeypatch.setattr(chart_data, "has_cached_bars", lambda t, i: True)
    monkeypatch.setattr(chart_data, "get_or_fetch_bars_batch", boom)
    assert _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW).chart_available is False


# --- endpoint ------------------------------------------------------------------------------------------------


def test_endpoint_serves_the_2h_range(monkeypatch):
    # The endpoint uses the real clock, so the fixture ends on the last weekday before today (ET): the window is never empty.
    today_et = datetime.now(timezone.utc).astimezone(pd.Timestamp("2026-01-05", tz=_NY).tz).date()
    live_raw = _bars_60m((pd.Timestamp(today_et) - pd.offsets.BDay(1)).strftime("%Y-%m-%d"))

    async def fake_fetch(ticker, now):
        return live_raw

    monkeypatch.setattr(chart_data, "_fetch_intraday_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/chart", params={"range": KEY})
    assert response.status_code == 200
    body = response.json()
    assert body["range"] == KEY and body["timeframe"] == "2h" and body["chart_available"] is True
    assert body["bars"][0]["time"][10] == "T" and len(body["warren_rsi"]) > 0 and len(body["warren_adx"]) > 0
    assert set(body["warren_levels"]) == {"rsi", "adx", "wvf"}
    assert body["rsi"] == [] and body["stochastic"] == [] and body["ema21"] == []
    assert body["entry_signal_available"] and body["warren_signal_available"] and body["zones_available"]


def test_endpoint_reports_unavailable_for_a_ticker_with_no_bars(monkeypatch):
    async def fake_fetch(ticker, now):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    monkeypatch.setattr(chart_data, "_fetch_intraday_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/tickers/ZZZZ/chart", params={"range": KEY})
    assert response.status_code == 200
    body = response.json()
    assert body["chart_available"] is False and body["timeframe"] == "2h" and body["warren_levels"] is None


def test_other_ranges_are_unaffected_by_the_new_fields(monkeypatch):
    # The daily path never populates the 2H-only fields.
    out = chart_data.ChartOut(range="D_1Y", timeframe="daily", bars=[], ema21=[], sma50=[], sma200=[], bollinger=[], stochastic=[], rsi=[], entry_signal_available=False, warren_signal_available=False, zones_available=False, source="fmp", chart_available=False)
    assert out.warren_rsi == [] and out.warren_levels is None


# --- per-ticker Blue Up profiles: the chart and the nightly job use the same lookup -----------------------------


def _with_panic_volume(raw: pd.DataFrame, count: int = 3) -> pd.DataFrame:
    """Raw 60m bars whose volume is 80M on the underlying bars of `count` candles inside the visible window where
    RSI < 40 and ADX <= 29.66 -- exactly where QQQ's scanOverSold2 branch a (volume > 70M) fires while ANY_TICKER
    (price-only, RSI[1] <= 12) does not. Prices are untouched, so ANY_TICKER's arrows are identical either way."""
    candles = build_2h_session_candles_fast(raw)
    rsi = wi.compute_rsi_wilder(candles["close"])
    _, _, adx = wi.compute_dmi_adx(candles["high"], candles["low"], candles["close"])
    visible_start = pd.Timestamp("2026-10-02", tz=_NY) - pd.Timedelta(days=90)
    hit = candles.index[((rsi < 40) & (adx <= 29.66) & (candles.index >= visible_start)).to_numpy()][:count]
    assert len(hit) == count, "fixture must contain RSI<40 / ADX<=29.66 candles in the window"
    out = raw.copy()
    for t in hit:
        out.loc[(out.index > t - pd.Timedelta(hours=2)) & (out.index <= t), "volume"] = 80_000_000
    return out


def _marker_set(out):
    return {(m.time, m.kind) for m in out.warren_signal_markers}


def _day_sums(raw: pd.DataFrame) -> pd.Series:
    """Summed 2h-candle volume per calendar day (what the volume guard compares to the day's EOD volume)."""
    candles = _full_candles(raw)
    return candles["volume"].groupby(candles.index.strftime("%Y-%m-%d")).sum()


def _seed_daily_volume(ticker: str, eod: dict[str, float], fetched_at: datetime = datetime(2026, 10, 2, 5, 0)) -> None:
    """Cached 1d bars (SharedBarsCache) carrying `eod` volume per date -- what a monitored ticker's guard reads. The
    default fetched_at is after the last completed session's close, so the last bar is not 'provisional'."""
    with Session(shared_bars_cache.engine) as session:
        for d, v in eod.items():
            session.add(
                SharedBarsCache(ticker=ticker, interval="1d", bar_time=datetime.fromisoformat(d), open=1.0, high=1.0, low=1.0, close=1.0,
                                volume=int(v), fetched_at=fetched_at, source=None)
            )
        session.commit()


def _unflagged_eod(raw: pd.DataFrame) -> dict[str, float]:
    """EOD volume equal to each day's summed candle volume: ratio exactly 1.0 everywhere."""
    return {d: float(v) for d, v in _day_sums(raw).items()}


def test_chart_uses_the_per_ticker_profile_and_hides_the_rsi_12_line_only_for_it(monkeypatch):
    from analysis.warren_signal.profiles import QQQ
    from analysis.warren_signal.types import ANY_TICKER

    raw = _with_panic_volume(_bars_60m(LAST_SESSION, seed=5))  # seed 5: has RSI<40 / ADX<=29.66 candles in the window
    _patch_source(monkeypatch, raw)
    _seed_daily_volume("QQQ", _unflagged_eod(raw))  # every day's ratio is 1.0, so the volume guard keeps all volume
    candles = _full_candles(raw)
    visible_start = pd.Timestamp("2026-10-02") - pd.Timedelta(days=90)

    qqq = _run(chart_data._get_chart_data_2h, "QQQ", KEY, NOW)
    aapl = _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW)

    for out, profile in ((qqq, QQQ), (aapl, ANY_TICKER)):
        expected = {(e.fired_at.strftime("%Y-%m-%dT%H:%M:%S"), e.kind) for e in replay_with_series(candles, profile)[0].events if pd.Timestamp(e.fired_at) >= visible_start}
        assert _marker_set(out) == expected
    # the profile really changes the signal: QQQ gets Blue Ups the price-only rule does not
    assert any(k == "blue_up" for _, k in _marker_set(qqq))
    assert _marker_set(qqq) != _marker_set(aapl)
    assert qqq.warren_levels.rsi == [30.0, 70.0, 80.81, 84.75] and aapl.warren_levels.rsi == [12.0, 30.0, 70.0, 80.81, 84.75]
    assert qqq.warren_levels.adx == aapl.warren_levels.adx == [40.0] and qqq.warren_levels.wvf == aapl.warren_levels.wvf == [0.4]


@pytest.mark.parametrize("ticker", ["QQQ", "AAPL"])
def test_chart_markers_match_what_the_nightly_job_would_store(monkeypatch, ticker):
    """For a profiled ticker (QQQ) and an ordinary one (AAPL): the Chart tab's on-demand 2H arrows are exactly the
    events compute_and_store_warren_signal persists for the same bars in the same window, and the latest-state row
    agrees -- same profile lookup, same candles, same engine. (Stored events are stamped with the candle's last
    60m bar, the chart with its window start, hence the mapping.)"""
    import data.warren_signal_data as wsd
    from analysis.entry_signal.resample import session_window_start

    raw = _with_panic_volume(_bars_60m(LAST_SESSION, seed=5))
    _patch_source(monkeypatch, raw)
    monkeypatch.setattr(wsd, "engine", _engine())
    if ticker == "QQQ":
        _seed_daily_volume("QQQ", _unflagged_eod(raw))
    chart = _run(chart_data._get_chart_data_2h, ticker, KEY, NOW)

    row = wsd.compute_and_store_warren_signal(ticker, raw, source="fmp")
    visible_start = pd.Timestamp("2026-10-02") - pd.Timedelta(days=90)
    with Session(wsd.engine) as session:
        stored = session.exec(select(wsd.WarrenSignalEvent).where(wsd.WarrenSignalEvent.ticker == ticker)).all()
    stored_set = {
        (session_window_start(pd.Timestamp(e.fired_at, tz=_NY)).strftime("%Y-%m-%dT%H:%M:%S"), e.signal_kind)
        for e in stored
        if pd.Timestamp(e.fired_at) >= visible_start
    }
    assert stored_set, "fixture must store arrows in the visible window"
    assert stored_set == _marker_set(chart)
    if ticker == "QQQ":
        assert any(k == "blue_up" for _, k in stored_set)

    expected_state = replay_with_series(wsd.signal_candles(ticker, _full_candles(raw), wsd.read_cached_daily_volume(ticker)), wsd.profile_for(ticker))[0]
    assert row.stop_count == expected_state.stop_count and row.gray_suppressed == expected_state.gray_suppressed
    assert row.signal_kind == expected_state.events[-1].kind


# --- the volume guard: one shared step for the chart and the nightly store -----------------------------------------


def _blue_times(out) -> set[str]:
    return {t for t, k in _marker_set(out) if k == "blue_up"}


def _panic_candles(raw: pd.DataFrame) -> list[str]:
    """Window-start times of the candles `_with_panic_volume` gave > 70M shares (QQQ's Volume_Num)."""
    c = _full_candles(raw)
    return [t.strftime("%Y-%m-%dT%H:%M:%S") for t in c.index[(c["volume"] > 70_000_000).to_numpy()]]


def _capture_replay_input(monkeypatch) -> dict:
    """Records the candle frame the chart hands to the Warren replay (after the guard)."""
    seen: dict = {}
    real = chart_data.replay_with_series

    def spy(candles, profile):
        seen["frame"] = candles.copy()
        return real(candles, profile)

    monkeypatch.setattr(chart_data, "replay_with_series", spy)
    return seen


def _nan_volume_days(frame: pd.DataFrame) -> set[str]:
    return set(frame.index[frame["volume"].isna().to_numpy()].strftime("%Y-%m-%d"))


@pytest.mark.parametrize("flagged", [False, True])
def test_chart_and_nightly_agree_with_the_guard_on_a_flagged_and_an_unflagged_qqq_day(monkeypatch, flagged):
    import data.warren_signal_data as wsd
    from analysis.entry_signal.resample import session_window_start

    raw = _with_panic_volume(_bars_60m(LAST_SESSION, seed=5))
    _patch_source(monkeypatch, raw)
    monkeypatch.setattr(wsd, "engine", _engine())
    panic = _panic_candles(raw)
    assert panic
    eod = _unflagged_eod(raw)
    if flagged:  # the panic days' EOD volume is a third of the summed intraday volume: ratio 3.0 > 1.5
        for t in panic:
            eod[t[:10]] = eod[t[:10]] / 3
    _seed_daily_volume("QQQ", eod)

    chart = _run(chart_data._get_chart_data_2h, "QQQ", KEY, NOW)
    wsd.compute_and_store_warren_signal("QQQ", raw, source="fmp")
    visible_start = pd.Timestamp("2026-10-02") - pd.Timedelta(days=90)
    with Session(wsd.engine) as session:
        stored = session.exec(select(wsd.WarrenSignalEvent).where(wsd.WarrenSignalEvent.ticker == "QQQ")).all()
    stored_set = {
        (session_window_start(pd.Timestamp(e.fired_at, tz=_NY)).strftime("%Y-%m-%dT%H:%M:%S"), e.signal_kind)
        for e in stored
        if pd.Timestamp(e.fired_at) >= visible_start
    }
    assert stored_set == _marker_set(chart)  # same guard, same candles, same engine
    if flagged:
        assert not (set(panic) & _blue_times(chart))  # the false volume Blues are gone...
    else:
        assert set(panic) <= _blue_times(chart)  # ...and an unflagged day keeps its volume Blue


def test_flagging_days_only_removes_blue_ups_and_leaves_bars_and_bb_rsi_alone(monkeypatch):
    raw = _with_panic_volume(_bars_60m(LAST_SESSION, seed=5))
    _patch_source(monkeypatch, raw)
    panic = _panic_candles(raw)
    eod = _unflagged_eod(raw)
    _seed_daily_volume("QQQ", eod)
    keep = _run(chart_data._get_chart_data_2h, "QQQ", KEY, NOW)

    monkeypatch.setattr(shared_bars_cache, "engine", _engine())
    for t in panic:
        eod[t[:10]] /= 3
    _seed_daily_volume("QQQ", eod)
    flag = _run(chart_data._get_chart_data_2h, "QQQ", KEY, NOW)

    assert _blue_times(flag) < _blue_times(keep)  # a strict subset: Blue Ups only ever disappear
    assert flag.bars == keep.bars and flag.entry_signal_markers == keep.entry_signal_markers


def test_displayed_candles_are_unchanged_by_the_guard_only_the_replay_input_is_blanked(monkeypatch):
    raw = _with_panic_volume(_bars_60m(LAST_SESSION, seed=5))
    _patch_source(monkeypatch, raw)
    panic = _panic_candles(raw)
    eod = _unflagged_eod(raw)
    for t in panic:
        eod[t[:10]] /= 3
    _seed_daily_volume("QQQ", eod)
    seen = _capture_replay_input(monkeypatch)

    out = _run(chart_data._get_chart_data_2h, "QQQ", KEY, NOW)

    assert _nan_volume_days(seen["frame"]) == {t[:10] for t in panic}  # blanked on exactly the flagged days
    full = _full_candles(raw)
    assert not full["volume"].isna().any()  # the frame everything else is built from is never touched
    # The response carries OHLC only (ChartBarOut has no volume field), built from the untouched candles.
    visible = full[full.index >= pd.Timestamp("2026-10-02") - pd.Timedelta(days=90)]
    assert [b.close for b in out.bars] == visible["close"].tolist()
    assert "volume" not in chart_data.ChartBarOut.model_fields


def test_current_session_without_eod_fails_closed(monkeypatch):
    raw = _with_panic_volume(_bars_60m(LAST_SESSION, seed=5))
    _patch_source(monkeypatch, raw)
    eod = _unflagged_eod(raw)
    del eod[LAST_SESSION]  # the newest session's EOD is not cached yet
    _seed_daily_volume("QQQ", eod)
    seen = _capture_replay_input(monkeypatch)
    _run(chart_data._get_chart_data_2h, "QQQ", KEY, NOW)
    assert _nan_volume_days(seen["frame"]) == {LAST_SESSION}


def test_an_in_progress_cached_daily_bar_is_not_trusted(monkeypatch):
    # The newest cached 1d bar was written BEFORE its own session's close (provisional): it reads as "no EOD
    # volume", so the guard fails closed on that day.
    raw = _with_panic_volume(_bars_60m(LAST_SESSION, seed=5))
    _patch_source(monkeypatch, raw)
    _seed_daily_volume("QQQ", _unflagged_eod(raw), fetched_at=datetime(2026, 10, 1, 12, 0))  # written mid-session
    seen = _capture_replay_input(monkeypatch)
    _run(chart_data._get_chart_data_2h, "QQQ", KEY, NOW)
    assert _nan_volume_days(seen["frame"]) == {LAST_SESSION}


def test_non_profiled_ticker_never_touches_daily_volume_and_is_unaffected(monkeypatch):
    raw = _with_panic_volume(_bars_60m(LAST_SESSION, seed=5))
    _patch_source(monkeypatch, raw)

    def boom(*a, **k):
        raise AssertionError("daily volume must not be read for a ticker without volume rules")

    monkeypatch.setattr(chart_data, "read_cached_daily_volume", boom)
    monkeypatch.setattr(chart_data, "_fetch_daily_volume_uncached", boom)
    seen = _capture_replay_input(monkeypatch)
    out = _run(chart_data._get_chart_data_2h, "AAPL", KEY, NOW)
    visible_start = pd.Timestamp("2026-10-02") - pd.Timedelta(days=90)
    expected = {
        (e.fired_at.strftime("%Y-%m-%dT%H:%M:%S"), e.kind)
        for e in replay_with_series(_full_candles(raw))[0].events
        if pd.Timestamp(e.fired_at) >= visible_start
    }
    assert _marker_set(out) == expected
    assert not seen["frame"]["volume"].isna().any()  # the replay input is the very candle frame, volume intact


def test_unlisted_profiled_ticker_gets_one_uncached_daily_fetch_of_completed_sessions_only(monkeypatch):
    raw = _with_panic_volume(_bars_60m(LAST_SESSION, seed=5))
    _patch_source(monkeypatch, raw)
    calls = []
    rows = [{"date": d, "open": 1, "high": 1, "low": 1, "close": 1, "volume": v} for d, v in _unflagged_eod(raw).items()]
    rows.append({"date": "2026-10-02", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 5})  # the session in progress at NOW

    async def fake_eod(ticker, a, b, group="daily_prices"):
        calls.append((ticker, a, b))
        return list(reversed(rows))  # FMP answers newest first

    monkeypatch.setattr(chart_data.fmp_client, "get_historical_price_eod", fake_eod)
    seen = _capture_replay_input(monkeypatch)
    _run(chart_data._get_chart_data_2h, "QQQ", KEY, NOW)

    assert len(calls) == 1 and calls[0][0] == "QQQ"
    assert not seen["frame"]["volume"].isna().any()  # every completed session verified; nothing blanked
    with Session(shared_bars_cache.engine) as session:
        assert session.exec(select(SharedBarsCache).where(SharedBarsCache.interval == "1d")).all() == []  # nothing written


def test_unlisted_profiled_ticker_whose_daily_fetch_fails_fails_closed_without_error(monkeypatch):
    raw = _with_panic_volume(_bars_60m(LAST_SESSION, seed=5))
    _patch_source(monkeypatch, raw)

    async def fail(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(chart_data.fmp_client, "get_historical_price_eod", fail)
    seen = _capture_replay_input(monkeypatch)
    out = _run(chart_data._get_chart_data_2h, "QQQ", KEY, NOW)
    assert out.chart_available and seen["frame"]["volume"].isna().all()
