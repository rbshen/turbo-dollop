import numpy as np
import pandas as pd
import pytest

from analysis.entry_signal.indicators import compute_rsi as compute_rsi_ewm
from analysis.warren_signal.indicators import (
    adx_between,
    compute_dmi_adx,
    compute_para_drop,
    compute_pivot_high,
    compute_pivot_low,
    compute_pivot_low_major,
    compute_rsi_wilder,
    compute_scan_blue,
    compute_wvf_buy,
    compute_wvf_sell,
    wilder_rma,
    wvf_between,
)


def test_wilder_rma_seeds_with_sma_then_recurses():
    s = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    out = wilder_rma(s, length=3)

    assert out.iloc[:2].isna().all()
    assert out.iloc[2] == pytest.approx(20.0)  # mean(10, 20, 30)
    assert out.iloc[3] == pytest.approx((20.0 * 2 + 40.0) / 3)
    assert out.iloc[4] == pytest.approx(((20.0 * 2 + 40.0) / 3 * 2 + 50.0) / 3)


def test_wilder_rma_all_nan_when_series_shorter_than_length():
    s = pd.Series([1.0, 2.0])
    out = wilder_rma(s, length=5)
    assert out.isna().all()


def test_compute_rsi_wilder_diverges_from_entry_signals_ewm_rsi():
    # Same fixture shape as entry_signal's own near-unbroken-uptrend test --
    # the two RSI implementations use different seeding (Wilder/SMA-seed vs.
    # pandas EWM's first-observation seed), so they must NOT agree exactly,
    # confirming Warren genuinely gets its own RSI rather than accidentally
    # reusing entry_signal's.
    close = pd.Series([100.0, 99.5] + [99.5 + i for i in range(1, 29)])
    wilder = compute_rsi_wilder(close)
    ewm = compute_rsi_ewm(close)
    assert wilder.iloc[-1] != pytest.approx(ewm.iloc[-1])
    # Both should still agree on the qualitative reading (strongly bullish).
    assert wilder.iloc[-1] > 90.0


def test_compute_rsi_wilder_is_0_for_unbroken_downtrend():
    close = pd.Series([float(30 - i) for i in range(1, 30)])
    rsi = compute_rsi_wilder(close)
    assert rsi.iloc[-1] == pytest.approx(0.0)


def test_compute_dmi_adx_reads_strongly_bullish_for_a_clean_uptrend():
    n = 40
    close = pd.Series([100.0 + i for i in range(n)])
    high = close + 1.0
    low = close - 1.0

    plus_di, minus_di, adx = compute_dmi_adx(high, low, close)

    assert plus_di.iloc[-1] > minus_di.iloc[-1]
    assert not pd.isna(adx.iloc[-1])
    assert 0.0 <= adx.iloc[-1] <= 100.0
    assert adx.iloc[-1] > 20.0  # a clean, unbroken trend should read as trending


def test_compute_wvf_buy_matches_hand_computed_value():
    close = pd.Series([100.0] * 21 + [110.0])
    low = pd.Series([100.0] * 21 + [90.0])
    wvf = compute_wvf_buy(close, low, lookback=22)
    # highest(close, 22) at the last bar = 110 (itself); (110-90)/110*100
    assert wvf.iloc[-1] == pytest.approx((110.0 - 90.0) / 110.0 * 100)


def test_compute_wvf_sell_matches_hand_computed_value():
    close = pd.Series([100.0] * 21 + [90.0])
    high = pd.Series([100.0] * 21 + [110.0])
    wvf = compute_wvf_sell(close, high, lookback=22)
    # lowest(close, 22) at the last bar = 90 (itself); (90-110)/90*100
    assert wvf.iloc[-1] == pytest.approx((90.0 - 110.0) / 90.0 * 100)


def test_compute_pivot_high_fires_on_a_three_bar_overbought_turn_down():
    # index: 0    1    2    3    4
    rsi = pd.Series([0.0, 75.0, 78.0, 82.0, 79.0])
    pivot = compute_pivot_high(rsi)
    assert bool(pivot.iloc[4]) is True
    assert bool(pivot.iloc[3]) is False


def test_compute_pivot_high_false_when_current_bar_not_above_70():
    rsi = pd.Series([0.0, 75.0, 78.0, 82.0, 65.0])
    pivot = compute_pivot_high(rsi)
    assert bool(pivot.iloc[4]) is False


def test_compute_pivot_low_major_fires_on_three_oversold_bars_recovering():
    rsi = pd.Series([100.0, 25.0, 22.0, 20.0, 35.0])
    pivot = compute_pivot_low_major(rsi)
    assert bool(pivot.iloc[4]) is True


def test_compute_pivot_low_major_false_when_recovery_bar_not_above_30():
    rsi = pd.Series([100.0, 25.0, 22.0, 20.0, 29.0])
    pivot = compute_pivot_low_major(rsi)
    assert bool(pivot.iloc[4]) is False


def test_compute_scan_blue_reads_the_prior_bars_rsi():
    rsi = pd.Series([50.0, 10.0, 60.0])
    scan = compute_scan_blue(rsi)
    assert bool(scan.iloc[2]) is True  # prior bar (index1) is 10 <= 12
    assert bool(scan.iloc[1]) is False  # prior bar (index0) is 50


def test_pivot_functions_return_clean_bool_dtype_during_warmup():
    rsi = pd.Series([np.nan, np.nan, np.nan, 50.0])
    assert compute_pivot_high(rsi).dtype == bool
    assert compute_pivot_low_major(rsi).dtype == bool
    assert compute_scan_blue(rsi).dtype == bool


def test_compute_pivot_low_fires_on_one_oversold_bar_turning_up_below_50():
    #                 0     1     2
    rsi = pd.Series([50.0, 25.0, 40.0])
    pivot = compute_pivot_low(rsi)
    assert bool(pivot.iloc[2]) is True
    assert bool(pivot.iloc[1]) is False


def test_compute_pivot_low_edges_are_exclusive_and_read_the_prior_bar():
    # prior bar must be strictly below 30; current bar strictly below 50 and strictly above the prior bar
    assert bool(compute_pivot_low(pd.Series([50.0, 30.0, 40.0])).iloc[2]) is False  # rsi[1] == 30
    assert bool(compute_pivot_low(pd.Series([50.0, 29.99, 40.0])).iloc[2]) is True
    assert bool(compute_pivot_low(pd.Series([50.0, 25.0, 50.0])).iloc[2]) is False  # rsi == 50
    assert bool(compute_pivot_low(pd.Series([50.0, 25.0, 49.99])).iloc[2]) is True
    assert bool(compute_pivot_low(pd.Series([50.0, 25.0, 25.0])).iloc[2]) is False  # not strictly rising
    assert bool(compute_pivot_low(pd.Series([50.0, 25.0, 20.0])).iloc[2]) is False  # falling


def test_compute_pivot_low_is_not_pivot_low_major():
    # One oversold bar only: pivotLow fires, pivotLowMajor (needs three bars under 30 and a recovery above 30) does not.
    rsi = pd.Series([60.0, 55.0, 50.0, 25.0, 40.0])
    assert bool(compute_pivot_low(rsi).iloc[4]) is True
    assert bool(compute_pivot_low_major(rsi).iloc[4]) is False


def test_compute_para_drop_is_close_over_the_35_bar_highest_high_including_the_current_bar():
    n = 40
    high = pd.Series([100.0] * n)
    close = pd.Series([90.0] * n)
    high.iloc[10] = 120.0  # inside the window at index 39 (bars 5..39)
    close.iloc[39] = 60.0
    drop = compute_para_drop(close, high)
    assert drop.iloc[39] == pytest.approx(60.0 / 120.0)
    # the 120 high ages out of the window at index 45; with n=40 check the window boundary directly
    assert drop.iloc[:34].isna().all()  # window of 35 not yet full before index 34
    assert not pd.isna(drop.iloc[34])
    # a bar's own high counts: a new high on the current bar makes the ratio close/that high
    high.iloc[39] = 200.0
    assert compute_para_drop(close, high).iloc[39] == pytest.approx(60.0 / 200.0)


def test_compute_para_drop_window_drops_the_high_after_35_bars():
    high = pd.Series([150.0] + [100.0] * 40)
    close = pd.Series([100.0] * 41)
    drop = compute_para_drop(close, high)
    assert drop.iloc[34] == pytest.approx(100.0 / 150.0)  # bars 0..34 still include the 150
    assert drop.iloc[35] == pytest.approx(1.0)  # bar 0 has rolled out


def test_adx_between_is_inclusive_at_both_ends_and_false_on_nan():
    adx = pd.Series([39.19, 39.2, 42.0, 46.0, 46.01, np.nan])
    out = adx_between(adx, 39.2, 46.0)
    assert out.tolist() == [False, True, True, True, False, False]
    assert out.dtype == bool


def test_wvf_between_is_inclusive_at_25_and_27_and_false_on_nan():
    wvf = pd.Series([24.99, 25.0, 26.0, 27.0, 27.01, np.nan])
    out = wvf_between(wvf)
    assert out.tolist() == [False, True, True, True, False, False]
    assert out.dtype == bool
