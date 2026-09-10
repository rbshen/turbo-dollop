import pandas as pd
import pytest

from analysis.trend_structure.stochastic import compute_stochastic


def test_full_k_and_full_d_nan_during_warmup_then_matches_hand_computed_value():
    # k_period=5 -> raw_k first valid at index 4. smooth=3 -> full_k first
    # valid at index 6 (4+3-1). full_d needs 3 more full_k values, so with
    # only 7 bars (indices 0-6) full_d never gets a first valid value here --
    # asserted explicitly below, not just left unchecked.
    high = pd.Series([12.0, 14.0, 11.0, 15.0, 13.0, 16.0, 10.0])
    low = pd.Series([10.0, 11.0, 9.0, 12.0, 11.0, 13.0, 8.0])
    close = pd.Series([11.0, 13.0, 10.0, 14.0, 12.0, 15.0, 9.0])

    full_k, full_d = compute_stochastic(high, low, close)

    assert full_k.iloc[:6].isna().all()
    assert full_d.isna().all()

    # Hand-computed raw %K for indices 4, 5, 6 (window = [i-4, i]):
    #   i=4: lowest_low=9  (min of low[0:5]),  highest_high=15 (max of high[0:5])
    #        raw_k = 100*(close[4]-9)/(15-9) = 100*(12-9)/6  = 50.0
    #   i=5: lowest_low=9  (min of low[1:6]),  highest_high=16 (max of high[1:6])
    #        raw_k = 100*(close[5]-9)/(16-9) = 100*(15-9)/7  = 600/7
    #   i=6: lowest_low=8  (min of low[2:7]),  highest_high=16 (max of high[2:7])
    #        raw_k = 100*(close[6]-8)/(16-8) = 100*(9-8)/8   = 12.5
    # full_k[6] = mean(raw_k[4], raw_k[5], raw_k[6])
    expected_full_k_6 = (50.0 + 600.0 / 7 + 12.5) / 3
    assert full_k.iloc[6] == pytest.approx(expected_full_k_6)


def test_constant_raw_k_on_a_linear_series_settles_full_k_and_full_d_to_the_same_value():
    # A perfectly linear close (step 1) with high=close+1, low=close-1 makes
    # every 5-bar raw %K window identical by construction (both the window's
    # range and the close's offset within it are constant), giving a
    # trivially hand-verifiable constant target for both smoothing stages.
    n = 12
    close = pd.Series([10.0 + i for i in range(n)])
    high = close + 1
    low = close - 1

    full_k, full_d = compute_stochastic(high, low, close)

    expected = 100 * 5 / 6  # (close[i] - (close[i-4]-1)) / ((close[i]+1) - (close[i-4]-1)) = 5/6, for every i>=4
    assert full_k.iloc[:6].isna().all()
    assert full_k.iloc[6:].apply(lambda v: v == pytest.approx(expected)).all()
    assert full_d.iloc[:8].isna().all()
    assert full_d.iloc[8:].apply(lambda v: v == pytest.approx(expected)).all()


def test_custom_k_period_and_smooth_are_honored():
    close = pd.Series([float(i) for i in range(10)])
    high = close + 1
    low = close - 1

    full_k, full_d = compute_stochastic(high, low, close, k_period=3, smooth=2)

    # raw_k first valid at index 2 (k_period-1); full_k first valid at
    # index 3 (2+2-1); full_d first valid at index 4 (3+2-1).
    assert full_k.iloc[:3].isna().all()
    assert full_k.iloc[3:].notna().all()
    assert full_d.iloc[:4].isna().all()
    assert full_d.iloc[4:].notna().all()
