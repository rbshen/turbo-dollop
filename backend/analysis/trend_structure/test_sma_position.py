import pandas as pd
import pytest

from analysis.trend_structure.sma_position import compute_sma_position


def test_insufficient_history_returns_both_none():
    close = pd.Series([100.0 + i for i in range(10)])  # only 10 bars, period=20

    result = compute_sma_position(close, period=20)

    assert result.position_pct is None
    assert result.cross is None


def test_exactly_period_bars_has_position_pct_but_no_prior_sma_for_cross():
    close = pd.Series([100.0] * 19 + [110.0])  # exactly `period` bars -- no bar before the first eligible one

    result = compute_sma_position(close, period=len(close))

    assert result.position_pct is not None
    assert result.cross is None


def test_no_cross_when_position_stays_the_same_sign():
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 110.0])  # steadily above a rising SMA

    result = compute_sma_position(close, period=3)

    assert result.position_pct is not None and result.position_pct > 0
    assert result.cross is None


def test_genuine_up_cross():
    # SMA(3) at t-1 (mean of 100,90,90=93.33) sits above the prior close
    # (90) -- prior_pos negative; today's jump to 130 clears the new SMA
    # (mean of 90,90,130=103.33) -- today_pos positive.
    close = pd.Series([100.0, 100.0, 90.0, 90.0, 130.0])

    result = compute_sma_position(close, period=3)

    assert result.cross == "up"
    assert result.position_pct > 0


def test_genuine_down_cross():
    close = pd.Series([100.0, 100.0, 110.0, 110.0, 70.0])

    result = compute_sma_position(close, period=3)

    assert result.cross == "down"
    assert result.position_pct < 0


def test_boundary_prior_position_exactly_zero_counts_as_crossable_up():
    # Prior close == prior SMA exactly (prior_pos == 0), today strictly above -> "up".
    close = pd.Series([100.0, 100.0, 100.0, 105.0])  # SMA(3) at t-1 = mean(100,100,100)=100, prior close=100 -> prior_pos=0

    result = compute_sma_position(close, period=3)

    assert result.cross == "up"


def test_boundary_prior_position_exactly_zero_counts_as_crossable_down():
    close = pd.Series([100.0, 100.0, 100.0, 95.0])

    result = compute_sma_position(close, period=3)

    assert result.cross == "down"


def test_empty_series_returns_both_none():
    result = compute_sma_position(pd.Series([], dtype=float), period=20)

    assert result.position_pct is None
    assert result.cross is None


def test_zero_sma_guarded_against_division_by_zero():
    close = pd.Series([0.0, 0.0, 0.0])

    result = compute_sma_position(close, period=3)

    assert result.position_pct is None
    assert result.cross is None
