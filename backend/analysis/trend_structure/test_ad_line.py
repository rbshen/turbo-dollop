import pandas as pd
import pytest

from analysis.trend_structure.ad_line import compute_ad_line, compute_chaikin_oscillator


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="B"))


def test_ad_line_money_flow_multiplier_and_cumulative_sum_hand_computed():
    high = _series([10.0, 12.0, 11.0])
    low = _series([8.0, 9.0, 9.0])
    close = _series([9.0, 11.0, 10.0])
    volume = _series([100.0, 200.0, 300.0])

    ad = compute_ad_line(high, low, close, volume)

    # bar0: MFM = ((9-8)-(10-9))/(10-8) = 0/2 = 0.0 -> MFV = 0.0
    # bar1: MFM = ((11-9)-(12-11))/(12-9) = (2-1)/3 = 0.3333... -> MFV = 66.667
    # bar2: MFM = ((10-9)-(11-10))/(11-9) = (1-1)/2 = 0.0 -> MFV = 0.0
    assert ad.iloc[0] == pytest.approx(0.0)
    assert ad.iloc[1] == pytest.approx(0.0 + (200.0 * (1.0 / 3.0)))
    assert ad.iloc[2] == pytest.approx(ad.iloc[1] + 0.0)  # cumulative, bar2 adds 0


def test_ad_line_zero_range_bar_treated_as_zero_multiplier_not_nan():
    high = _series([10.0, 10.0])
    low = _series([8.0, 10.0])  # bar1: high == low, zero range
    close = _series([9.0, 10.0])
    volume = _series([100.0, 500.0])

    ad = compute_ad_line(high, low, close, volume)

    assert not ad.isna().any()
    assert ad.iloc[1] == ad.iloc[0]  # zero-range bar contributes exactly 0.0, not NaN


def test_chaikin_oscillator_is_ema3_minus_ema10_of_the_ad_line():
    ad_line = _series([0.0, 10.0, 5.0, 20.0, 15.0, 30.0, 25.0, 40.0, 35.0, 50.0, 45.0, 60.0])

    osc = compute_chaikin_oscillator(ad_line)

    expected = ad_line.ewm(span=3, adjust=False).mean() - ad_line.ewm(span=10, adjust=False).mean()
    pd.testing.assert_series_equal(osc, expected)


def test_chaikin_oscillator_seeds_directly_from_the_first_value_adjust_false():
    ad_line = _series([100.0, 100.0, 100.0])

    osc = compute_chaikin_oscillator(ad_line)

    # A flat A/D line has EMA3 == EMA10 == 100.0 at every bar -> oscillator is exactly 0.0 throughout.
    assert (osc == 0.0).all()
