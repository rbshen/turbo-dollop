import asyncio
from datetime import datetime, timedelta

import pandas as pd
import pytest

import data.chart_data as chart_data
from core.schemas import TechnicalEntrySignalOut


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


def test_chart_available_false_when_fetch_returns_no_bars(monkeypatch):
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {}

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)

    out = asyncio.run(chart_data.get_chart_data("BADTICKER", "D_1Y"))

    assert out.chart_available is False
    assert out.bars == []
    assert out.ema21 == out.sma50 == out.sma200 == []
    assert out.entry_signal_available is False
    assert out.entry_signal_marker is None
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

    out = asyncio.run(chart_data.get_chart_data("NOTTRACKED", "D_1Y"))

    assert out.entry_signal_available is False
    assert out.entry_signal_marker is None


def test_entry_signal_tracked_but_not_active_has_no_marker(monkeypatch):
    df = _daily_df(300)
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    async def fake_entry_signal(ticker):
        return _entry_signal(active=False, fired_at=datetime.now() - timedelta(days=10))

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert out.entry_signal_available is True
    assert out.entry_signal_marker is None


def test_entry_signal_tracked_and_active_places_marker_on_correct_bar(monkeypatch):
    df = _daily_df(300)
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    # A recent fired_at, landing on a real bdate in df's index (or the
    # nearest earlier one if it lands on a weekend).
    fired_at = (pd.Timestamp.today().normalize() - pd.Timedelta(days=2)).to_pydatetime()

    async def fake_entry_signal(ticker):
        return _entry_signal(active=True, fired_at=fired_at)

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert out.entry_signal_available is True
    assert out.entry_signal_marker is not None
    assert out.entry_signal_marker.label == "BB+RSI"
    marker_date = datetime.strptime(out.entry_signal_marker.time, "%Y-%m-%d").date()
    assert marker_date <= fired_at.date()
    assert (fired_at.date() - marker_date).days <= 3  # nearest trading bar on/before a weekday fired_at
