import pandas as pd
import pytest

from analysis.entry_signal.engine import compute_entry_signal, compute_historical_entry_signals
from analysis.entry_signal.indicators import ATR_MULTIPLIER, check_buy_signal, compute_atr, compute_bollinger_bands, compute_rsi
from analysis.entry_signal.resample import build_2h_session_candles


def _synthetic_intraday_bars(closes: list[float]) -> pd.DataFrame:
    """One bar per 2h session window (09:30/11:30/13:30/15:30 ET each day),
    so `closes` maps 1:1 onto the resulting resampled candles -- lets a test
    fully control the close-price series the engine sees without needing
    many bars per window."""
    days = pd.bdate_range("2026-01-05", periods=(len(closes) + 3) // 4 + 1, tz="America/New_York")
    times = ["09:30", "11:30", "13:30", "15:30"]
    rows = []
    i = 0
    for day in days:
        for t in times:
            if i >= len(closes):
                break
            hour, minute = (int(x) for x in t.split(":"))
            ts = day.replace(hour=hour, minute=minute)
            c = closes[i]
            rows.append({"timestamp": ts, "open": c, "high": c, "low": c, "close": c, "volume": 1000})
            i += 1
    return pd.DataFrame(rows).set_index("timestamp")


def test_fires_on_a_mid_day_bar_even_though_the_final_bar_of_the_day_does_not():
    # The exact bug this feature fixes: a decline crosses into oversold
    # territory on the FIRST bar of the most recent trading day, then
    # recovers sharply for the rest of that same day -- the OLD
    # last-bar-only engine would have reported no signal at all here.
    # (Sequence hand-verified: index 24 -- the last day's first bar --
    # fires; indices 25-27, including the day's final bar, do not.)
    closes = [100.0] * 20 + [95.0, 85.0, 78.0, 74.0] + [70.0, 120.0, 122.0, 124.0]
    bars = _synthetic_intraday_bars(closes)

    result = compute_entry_signal(bars)

    candles = build_2h_session_candles(bars)
    close = candles["close"]
    rsi = compute_rsi(close)
    _, _, pct_b = compute_bollinger_bands(close)
    atr = compute_atr(candles)

    fired_index = 24
    assert check_buy_signal(rsi, pct_b, fired_index) is True
    assert check_buy_signal(rsi, pct_b, len(candles) - 1) is False  # the final bar alone would have missed this

    assert result.fired is True
    assert result.fired_at == candles.index[fired_index].to_pydatetime().replace(tzinfo=None)
    assert result.pct_b == pytest.approx(pct_b.iloc[fired_index])
    assert result.rsi == pytest.approx(rsi.iloc[fired_index])
    assert result.close == pytest.approx(closes[fired_index])
    expected_stop = closes[fired_index] - atr.iloc[fired_index] * ATR_MULTIPLIER
    assert result.stop_price == pytest.approx(expected_stop)
    # as_of always reflects the last candle evaluated this run, regardless
    # of which bar (if any) actually fired.
    assert result.as_of == candles.index[-1].to_pydatetime().replace(tzinfo=None)


def test_picks_the_latest_firing_bar_when_multiple_bars_fire_the_same_day():
    # Day 6 (indices 20-23) has THREE consecutive firing bars (21, 22, 23)
    # -- confirms the engine reports the LATEST one, not the first.
    closes = [100.0] * 20 + [95.0, 85.0, 78.0, 74.0]
    bars = _synthetic_intraday_bars(closes)

    result = compute_entry_signal(bars)

    candles = build_2h_session_candles(bars)
    rsi = compute_rsi(candles["close"])
    _, _, pct_b = compute_bollinger_bands(candles["close"])
    assert [check_buy_signal(rsi, pct_b, i) for i in (20, 21, 22, 23)] == [False, True, True, True]

    assert result.fired is True
    assert result.fired_at == candles.index[23].to_pydatetime().replace(tzinfo=None)
    assert result.close == pytest.approx(74.0)


def test_no_fire_today_leaves_every_fired_field_none_but_as_of_still_populated():
    # A calm, unbroken run -- nothing in check_buy_signal's territory at
    # any point in the most recent day.
    closes = [100.0 + i * 0.1 for i in range(28)]
    bars = _synthetic_intraday_bars(closes)

    result = compute_entry_signal(bars)

    candles = build_2h_session_candles(bars)
    assert result.fired is False
    assert result.fired_at is None
    assert result.pct_b is None
    assert result.rsi is None
    assert result.close is None
    assert result.stop_price is None
    assert result.as_of == candles.index[-1].to_pydatetime().replace(tzinfo=None)


def test_only_the_most_recent_trading_days_bars_are_scanned():
    # Day 6 (indices 20-23) has real firing bars, but day 7 (the most
    # recent) is calm throughout -- confirms an OLDER day's fire is never
    # resurrected once a newer, quiet day exists on top of it.
    closes = [100.0] * 20 + [95.0, 85.0, 78.0, 74.0] + [90.0, 91.0, 92.0, 93.0]
    bars = _synthetic_intraday_bars(closes)

    result = compute_entry_signal(bars)

    assert result.fired is False
    assert result.fired_at is None


def test_compute_entry_signal_raises_on_no_session_bars():
    df = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]},
        index=pd.DatetimeIndex(["2026-01-05 20:00"], tz="America/New_York"),
    )
    with pytest.raises(ValueError):
        compute_entry_signal(df)


def test_historical_keeps_the_first_firing_bar_of_a_day_not_the_last():
    # Same fixture as test_picks_the_latest_firing_bar_when_multiple_bars_fire_the_same_day
    # above (day 6, indices 20-23, has THREE consecutive firing bars: 21,
    # 22, 23) -- compute_entry_signal (the nightly job's own function,
    # unchanged) picks the LAST (23); compute_historical_entry_signals
    # must pick the FIRST (21) instead, per the confirmed dedup rule for
    # historical chart markers (see its own docstring for why the two
    # deliberately differ).
    closes = [100.0] * 20 + [95.0, 85.0, 78.0, 74.0]
    bars = _synthetic_intraday_bars(closes)

    candles = build_2h_session_candles(bars)
    rsi = compute_rsi(candles["close"])
    _, _, pct_b = compute_bollinger_bands(candles["close"])
    assert [check_buy_signal(rsi, pct_b, i) for i in (20, 21, 22, 23)] == [False, True, True, True]

    results = compute_historical_entry_signals(bars)

    assert len(results) == 1  # one distinct firing day
    assert results[0].fired_at == candles.index[21].to_pydatetime().replace(tzinfo=None)
    assert results[0].close == pytest.approx(85.0)  # index 21's close, not index 23's (74.0)


def test_historical_returns_one_result_per_firing_day_quiet_days_omitted():
    # Day 6 (indices 20-23) fires; day 7 (24-27) is quiet; day 8 (28-31)
    # fires again -- confirms quiet days produce no result at all (not a
    # fired=False placeholder, unlike compute_entry_signal's own "latest
    # state" contract) and each distinct firing day contributes exactly
    # one result, in chronological order.
    firing_day = [95.0, 85.0, 78.0, 74.0]
    quiet_day = [90.0, 120.0, 122.0, 124.0]
    second_firing_day = [80.0, 60.0, 40.0, 20.0]
    closes = [100.0] * 20 + firing_day + quiet_day + second_firing_day
    bars = _synthetic_intraday_bars(closes)
    candles = build_2h_session_candles(bars)

    results = compute_historical_entry_signals(bars)

    assert len(results) == 2
    assert results[0].fired_at < results[1].fired_at
    assert results[0].fired_at == candles.index[21].to_pydatetime().replace(tzinfo=None)
    # Both results are real fires (never a fired=False placeholder).
    assert all(r.fired for r in results)


def test_historical_last_result_matches_compute_entry_signal_on_the_same_data():
    # Sanity cross-check using the exact fixture from
    # test_fires_on_a_mid_day_bar_even_though_the_final_bar_of_the_day_does_not
    # above: day 6 (indices 20-23) fires on 3 consecutive bars, day 7
    # (24-27) fires on ONLY its first bar (24). compute_entry_signal only
    # ever looks at the MOST RECENT day (day 7), so it should agree
    # exactly with compute_historical_entry_signals' own LAST result --
    # day 7 has just one firing bar, so first-vs-last tie-breaking can't
    # cause a mismatch there. This confirms the two functions share the
    # same underlying RSI/BB/check_buy_signal math and genuinely only
    # differ in cross-day scope and same-day tie-breaking, not in the
    # signal condition itself.
    closes = [100.0] * 20 + [95.0, 85.0, 78.0, 74.0] + [70.0, 120.0, 122.0, 124.0]
    bars = _synthetic_intraday_bars(closes)

    latest_day_result = compute_entry_signal(bars)
    historical_results = compute_historical_entry_signals(bars)

    assert latest_day_result.fired is True
    assert len(historical_results) == 2  # day 6 and day 7 each fired
    assert historical_results[-1].fired_at == latest_day_result.fired_at
    assert historical_results[-1].close == pytest.approx(latest_day_result.close)
    assert historical_results[-1].stop_price == pytest.approx(latest_day_result.stop_price)
    # And day 6's own result (not exercised by compute_entry_signal at all,
    # since it only scans the latest day) is the FIRST of its 3 firing bars.
    candles = build_2h_session_candles(bars)
    assert historical_results[0].fired_at == candles.index[21].to_pydatetime().replace(tzinfo=None)


def test_compute_historical_entry_signals_raises_on_no_session_bars():
    df = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]},
        index=pd.DatetimeIndex(["2026-01-05 20:00"], tz="America/New_York"),
    )
    with pytest.raises(ValueError):
        compute_historical_entry_signals(df)
