import asyncio
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

import data.chart_data as chart_data
from core.models import TechnicalEntrySignalEvent
from core.schemas import LiquidityZoneOut, LiquidityZonesOut, TechnicalEntrySignalOut, ZoneOut


def _daily_df(n: int, *, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """n business-day bars ending at `end` (default: today). Closes oscillate
    (rising trend + a sine wiggle) rather than moving in one direction every
    single bar -- a strictly monotonic series never has a single down day,
    which makes RSI's avg_loss zero for the whole series and so, correctly,
    all-NaN (see compute_rsi's own avg_loss.replace(0, nan) guard) -- not a
    bug, just not a realistic fixture for exercising RSI here."""
    import math

    end = end or pd.Timestamp.today().normalize()
    index = pd.bdate_range(end=end, periods=n)
    closes = pd.Series([100.0 + i * 0.1 + 5.0 * math.sin(i / 3.0) for i in range(n)], index=index)
    return pd.DataFrame(
        {
            "open": closes - 0.5,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": 1000,
        },
        index=index,
    )


def _entry_signal(*, active: bool, fired_at: datetime | None) -> TechnicalEntrySignalOut:
    now = datetime.now()
    return TechnicalEntrySignalOut(
        ticker="TEST",
        signal_type="bb_rsi",
        timeframe="2h",
        active=active,
        fired_at=fired_at,
        pct_b=0.02,
        rsi=25.0,
        close=101.5,
        stop_price=98.0,
        source="yahoo",
        as_of=now,
        computed_at=now,
    )


async def _no_entry_signal(ticker: str):
    return None


def _events(ticker: str, fired_ats: list[datetime]) -> list[TechnicalEntrySignalEvent]:
    return [
        TechnicalEntrySignalEvent(ticker=ticker, signal_type="bb_rsi", timeframe="2h", fired_at=fa, stop_price=95.0, created_at=fa)
        for fa in sorted(fired_ats)
    ]


def _no_zones(ticker: str):
    return None


def _zone_out(price: float, formed_at: str) -> ZoneOut:
    return ZoneOut(price=price, distance_pct=0.0, cluster_size=1, formed_at=date.fromisoformat(formed_at))


def _lp_out(*, support: list[ZoneOut], resistance: list[ZoneOut]) -> LiquidityZoneOut:
    now = datetime.now()
    return LiquidityZoneOut(
        timeframe="daily",
        last_price=100.0,
        as_of=now.date(),
        computed_at=now,
        source="yahoo",
        support_zones=support,
        resistance_zones=resistance,
    )


def test_chart_available_false_when_fetch_returns_no_bars(monkeypatch):
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {}

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("BADTICKER", "D_1Y"))

    assert out.chart_available is False
    assert out.bars == []
    assert out.ema21 == out.sma50 == out.sma200 == []
    assert out.entry_signal_available is False
    assert out.entry_signal_markers == []
    assert out.source == "fmp"


def test_daily_range_computes_full_warmup_then_slices_to_visible_window(monkeypatch):
    # 600 business days (~2.4y) fetched, of which D_1Y only shows the
    # trailing ~365 calendar days -- plenty of warm-up headroom before the
    # visible window starts, so every visible bar should have a real
    # (non-NaN) SMA200 once sliced.
    df = _daily_df(600)

    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("AAPL", "D_1Y"))

    assert out.chart_available is True
    assert out.timeframe == "daily"
    assert 0 < len(out.bars) < 600  # sliced down from the full fetched history
    # Every visible bar has a real SMA200 -- confirms the warm-up (fetched
    # but not visible) portion of the series was included in the rolling
    # computation before slicing, not computed on the visible slice alone.
    assert len(out.sma200) == len(out.bars)
    assert len(out.ema21) == len(out.bars)
    assert len(out.bollinger) == len(out.bars)
    assert len(out.rsi) > 0
    assert len(out.stochastic) > 0


def test_d6m_range_computes_full_warmup_then_slices_to_visible_window(monkeypatch):
    # Same shape as the D_1Y warm-up test above, at D_6M's own (shorter)
    # visible window -- 600 business days (~2.4y) fetched, of which D_6M
    # only shows the trailing ~182 calendar days.
    df = _daily_df(600)

    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("AAPL", "D_6M"))

    assert out.chart_available is True
    assert out.timeframe == "daily"
    assert 0 < len(out.bars) < 600
    # Every visible bar has a real SMA200 -- confirms the warm-up (fetched
    # but not visible) portion of the series was included in the rolling
    # computation before slicing, not computed on the visible slice alone.
    assert len(out.sma200) == len(out.bars)
    assert len(out.ema21) == len(out.bars)
    assert len(out.bollinger) == len(out.bars)


def test_ema21_is_exponential_not_a_rolling_average(monkeypatch):
    # A trend-line switch, not just a rename -- confirms the series is
    # actually close.ewm(span=21, adjust=False).mean(), not SMA20 (or any
    # other rolling mean) under a new field name.
    df = _daily_df(300)

    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("AAPL", "D_1Y"))

    expected_ema21 = df["close"].ewm(span=21, adjust=False).mean()
    expected_sma20 = df["close"].rolling(20).mean()
    last = out.ema21[-1]
    last_idx = df.index[df.index.strftime("%Y-%m-%d") == last.time][0]

    assert last.value == pytest.approx(float(expected_ema21.loc[last_idx]), abs=1e-6)
    # Confirms this genuinely differs from the old SMA20 series, not just a
    # renamed field holding the same values.
    assert last.value != pytest.approx(float(expected_sma20.loc[last_idx]), abs=1e-6)


def test_bollinger_basis_is_ema20_not_sma20(monkeypatch):
    # Basis is EMA(20) now; stddev/window/multiplier are unchanged from the
    # shared BB_LENGTH/BB_STD constants -- only the basis calculation moved.
    df = _daily_df(300)

    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("AAPL", "D_1Y"))

    close = df["close"]
    expected_ema20 = close.ewm(span=20, adjust=False).mean()
    expected_sma20 = close.rolling(20).mean()
    expected_sigma = close.rolling(20).std(ddof=0)

    last = out.bollinger[-1]
    last_idx = df.index[df.index.strftime("%Y-%m-%d") == last.time][0]

    assert last.middle == pytest.approx(float(expected_ema20.loc[last_idx]), abs=1e-6)
    assert last.middle != pytest.approx(float(expected_sma20.loc[last_idx]), abs=1e-6)
    assert (last.upper - last.middle) == pytest.approx(2.0 * float(expected_sigma.loc[last_idx]), abs=1e-6)
    assert (last.middle - last.lower) == pytest.approx(2.0 * float(expected_sigma.loc[last_idx]), abs=1e-6)


def test_fmp_w4y_range_resamples_daily_to_weekly(monkeypatch):
    df = _daily_df(365 * 9)  # ~9 years of daily bars, enough for 8y lookback + resample

    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        assert lookback_years == 8
        return {tickers[0]: df}

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("AAPL", "W_4Y"))

    assert out.timeframe == "weekly"
    assert out.chart_available is True
    # Resampled weekly bars are roughly 1/5th the daily count for the same span.
    assert len(out.bars) < 300


def test_yahoo_w4y_range_fetches_weekly_directly_not_resampled(monkeypatch):
    weekly_df = _daily_df(250)  # stand-in "weekly" bars -- shape doesn't matter, only the call args do

    monkeypatch.setattr(chart_data.settings, "fmp_enabled", False)

    captured = {}

    async def fake_get_history(tickers, period, interval):
        captured["period"] = period
        captured["interval"] = interval
        renamed = weekly_df.rename(columns=str.capitalize)
        return {tickers[0]: renamed}

    def fail_if_resampled(ohlcv):
        raise AssertionError("resample_to_weekly should not be called on the Yahoo weekly-direct path")

    monkeypatch.setattr(chart_data.yahoo_client, "get_history", fake_get_history)
    monkeypatch.setattr(chart_data, "resample_to_weekly", fail_if_resampled)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("AAPL", "W_4Y"))

    assert captured["interval"] == "1wk"
    assert out.source == "yahoo"
    assert out.chart_available is True


def test_entry_signal_not_tracked(monkeypatch):
    df = _daily_df(300)
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("NOTTRACKED", "D_1Y"))

    assert out.entry_signal_available is False
    assert out.entry_signal_markers == []


def test_entry_signal_tracked_but_no_events_in_window_has_no_markers(monkeypatch):
    # "active" (TechnicalEntrySignal's own 7-day window) no longer gates
    # history at all -- what matters now is purely whether
    # TechnicalEntrySignalEvent has any rows in the visible window. Here
    # the ticker IS tracked (entry_signal_available=True) but the event
    # table has nothing for it.
    df = _daily_df(300)
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    async def fake_entry_signal(ticker):
        return _entry_signal(active=False, fired_at=datetime.now() - timedelta(days=10))

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(chart_data, "_fetch_entry_signal_events", lambda ticker, since: [])

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert out.entry_signal_available is True
    assert out.entry_signal_markers == []


def test_entry_signal_places_a_marker_per_event_even_when_inactive(monkeypatch):
    # A single old, long-INACTIVE fire (TechnicalEntrySignal.active would
    # read False -- outside its own 7-day window) must still produce a
    # historical marker: the active gate is a TechnicalEntrySignal-only
    # concept and deliberately does not apply to entry_signal_markers.
    df = _daily_df(300)
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    fired_at = (pd.Timestamp.today().normalize() - pd.Timedelta(days=60)).to_pydatetime()

    async def fake_entry_signal(ticker):
        return _entry_signal(active=False, fired_at=fired_at)

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(chart_data, "_fetch_entry_signal_events", lambda ticker, since: _events(ticker, [fired_at]))

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert out.entry_signal_available is True
    assert len(out.entry_signal_markers) == 1
    assert out.entry_signal_markers[0].label == "BB+RSI"
    marker_date = datetime.strptime(out.entry_signal_markers[0].time, "%Y-%m-%d").date()
    assert marker_date <= fired_at.date()
    assert (fired_at.date() - marker_date).days <= 3  # nearest trading bar on/before a weekday fired_at


def test_entry_signal_multiple_fires_same_day_collapse_to_one_marker_keeping_first(monkeypatch):
    # The confirmed real-world shape from the historical-backfill
    # investigation: ~56% of firing days fire 2+ times in the same
    # session. Three events land on the exact same calendar day here --
    # they must collapse to ONE marker, anchored to the FIRST
    # chronological fire, not the last.
    df = _daily_df(300)
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    day = pd.Timestamp.today().normalize() - pd.Timedelta(days=5)
    first_fire = (day + pd.Timedelta(hours=11, minutes=30)).to_pydatetime()
    second_fire = (day + pd.Timedelta(hours=13, minutes=30)).to_pydatetime()
    third_fire = (day + pd.Timedelta(hours=15, minutes=30)).to_pydatetime()

    async def fake_entry_signal(ticker):
        return _entry_signal(active=True, fired_at=third_fire)

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(
        chart_data, "_fetch_entry_signal_events", lambda ticker, since: _events(ticker, [first_fire, second_fire, third_fire])
    )

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert len(out.entry_signal_markers) == 1  # not 3
    marker_date = datetime.strptime(out.entry_signal_markers[0].time, "%Y-%m-%d").date()
    assert marker_date <= first_fire.date()
    assert (first_fire.date() - marker_date).days <= 3


def test_entry_signal_distinct_days_each_get_their_own_marker(monkeypatch):
    df = _daily_df(300)
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    today = pd.Timestamp.today().normalize()
    fired_1 = (today - pd.Timedelta(days=30)).to_pydatetime()
    fired_2 = (today - pd.Timedelta(days=10)).to_pydatetime()

    async def fake_entry_signal(ticker):
        return _entry_signal(active=True, fired_at=fired_2)

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(chart_data, "_fetch_entry_signal_events", lambda ticker, since: _events(ticker, [fired_1, fired_2]))

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert len(out.entry_signal_markers) == 2
    times = sorted(out.entry_signal_markers, key=lambda m: m.time)
    assert times[0].time < times[1].time


def test_entry_signal_weekly_view_collapses_same_week_fires_keeping_first(monkeypatch):
    # Same multi-fire-per-bucket shape as the daily test above, but for
    # the W_4Y (weekly) view -- two fires in the same Monday-anchored
    # week must collapse to one marker on that week's bar, keeping the
    # earlier of the two.
    df = _daily_df(365 * 5)  # enough history for W_4Y's warm-up + 4y visible window
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    # Two fires in the same calendar week (a Tuesday and a Thursday),
    # comfortably inside the visible window.
    monday = pd.Timestamp.today().normalize() - pd.Timedelta(days=180)
    monday = monday - pd.Timedelta(days=monday.weekday())  # snap to that week's Monday
    tuesday_fire = (monday + pd.Timedelta(days=1, hours=11, minutes=30)).to_pydatetime()
    thursday_fire = (monday + pd.Timedelta(days=3, hours=13, minutes=30)).to_pydatetime()

    async def fake_entry_signal(ticker):
        return _entry_signal(active=True, fired_at=thursday_fire)

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(
        chart_data, "_fetch_entry_signal_events", lambda ticker, since: _events(ticker, [tuesday_fire, thursday_fire])
    )

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "W_4Y"))

    assert out.timeframe == "weekly"
    assert len(out.entry_signal_markers) == 1  # both fires collapse onto the same week's bar
    marker_date = date.fromisoformat(out.entry_signal_markers[0].time)
    assert marker_date == monday.date()  # anchored to the week's Monday, matching resample_to_weekly


def test_entry_signal_w4y_shows_no_markers_for_the_older_two_years_not_an_error(monkeypatch):
    # The documented, accepted asymmetry: W_4Y shows 4 years of price but
    # TechnicalEntrySignalEvent only ever retains ~2 years (see
    # entry_signal_data.EVENT_RETENTION_DAYS and chart_data's own module
    # docstring). Simulates that by only returning events within the most
    # recent ~2 years -- the older ~2 years of the visible window must
    # simply have no markers, not raise or degrade the rest of the chart.
    df = _daily_df(365 * 5)
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    recent_fire = (pd.Timestamp.today().normalize() - pd.Timedelta(days=200)).to_pydatetime()  # well within 2y

    async def fake_entry_signal(ticker):
        return _entry_signal(active=True, fired_at=recent_fire)

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    # Simulates the real query already having nothing older than ~2 years
    # to return (pruned/never backfilled that far back) -- only the one
    # recent event exists at all.
    monkeypatch.setattr(chart_data, "_fetch_entry_signal_events", lambda ticker, since: _events(ticker, [recent_fire]))

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "W_4Y"))

    assert out.chart_available is True  # the rest of the chart renders normally
    assert out.timeframe == "weekly"
    assert len(out.entry_signal_markers) == 1  # only the one recent fire -- no error, no fabricated old markers
    marker_date = date.fromisoformat(out.entry_signal_markers[0].time)
    assert marker_date <= recent_fire.date()


def test_zones_not_tracked(monkeypatch):
    df = _daily_df(300)
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("NOTTRACKED", "D_1Y"))

    assert out.zones_available is False
    assert out.zones == []


def test_zones_within_visible_window_included_outside_excluded(monkeypatch):
    df = _daily_df(600)
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    today = pd.Timestamp.today().normalize()
    within = (today - pd.Timedelta(days=300)).strftime("%Y-%m-%d")  # inside D_1Y's 365-day window
    outside = (today - pd.Timedelta(days=400)).strftime("%Y-%m-%d")  # older than the window

    support = [_zone_out(90.0, within), _zone_out(80.0, outside)]
    resistance = [_zone_out(110.0, within)]
    lp = LiquidityZonesOut(daily=_lp_out(support=support, resistance=resistance), weekly=None)

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", lambda ticker: lp)

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert out.zones_available is True
    got = {(z.side, z.price) for z in out.zones}
    assert got == {("support", 90.0), ("resistance", 110.0)}  # the outside-window support zone is dropped


def test_zones_use_weekly_read_for_w4y_range_not_daily(monkeypatch):
    # ~9y of daily bars, matching the existing W_4Y resample test's own
    # fixture size -- enough warm-up + 4y visible window once resampled.
    df = _daily_df(365 * 9)
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    recent = (pd.Timestamp.today().normalize() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    daily_read = _lp_out(support=[_zone_out(90.0, recent)], resistance=[])
    weekly_read = _lp_out(support=[], resistance=[_zone_out(120.0, recent)])
    lp = LiquidityZonesOut(daily=daily_read, weekly=weekly_read)

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", lambda ticker: lp)

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "W_4Y"))

    # Only the weekly read's zone shows up -- the daily read's own zone
    # (90.0/support) is never consulted for a W_4Y request.
    assert [(z.side, z.price) for z in out.zones] == [("resistance", 120.0)]


def test_zones_absent_when_bars_empty(monkeypatch):
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {}

    recent = (pd.Timestamp.today().normalize() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    lp = LiquidityZonesOut(daily=_lp_out(support=[_zone_out(90.0, recent)], resistance=[]), weekly=None)

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", lambda ticker: lp)

    out = asyncio.run(chart_data.get_chart_data("BADTICKER", "D_1Y"))

    # zones_available still reflects the real (independent) cache-only
    # read, but the zones list itself is empty -- no chart to anchor
    # price lines onto, same convention entry_signal_markers uses here.
    assert out.chart_available is False
    assert out.zones_available is True
    assert out.zones == []
