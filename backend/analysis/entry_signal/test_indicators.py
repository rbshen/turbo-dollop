import numpy as np
import pandas as pd
import pytest

from analysis.entry_signal.indicators import (
    BB_LENGTH,
    BB_LOWER_PCT,
    RSI_OVERSOLD,
    check_buy_signal,
    compute_atr,
    compute_bollinger_bands,
    compute_rsi,
)


def test_compute_rsi_is_very_high_for_a_near_unbroken_uptrend():
    # One tiny early dip (so avg_loss is nonzero, not exactly 0 -- an
    # all-gains series makes avg_loss.replace(0, np.nan) divide by NaN,
    # which is RSI's genuine "undefined" reading, not 100) followed by a
    # long unbroken climb.
    close = pd.Series([100.0, 99.5] + [99.5 + i for i in range(1, 29)])
    rsi = compute_rsi(close)
    assert rsi.iloc[-1] > 90.0


def test_compute_rsi_is_nan_when_the_whole_series_never_declines():
    # avg_loss stays exactly 0 the whole way -> RSI is undefined (NaN), the
    # reference bot's own `avg_loss.replace(0, np.nan)` behavior -- not a
    # fabricated 100.
    close = pd.Series([float(i) for i in range(1, 30)])
    rsi = compute_rsi(close)
    assert pd.isna(rsi.iloc[-1])


def test_compute_rsi_is_0_for_an_unbroken_downtrend():
    close = pd.Series([float(30 - i) for i in range(1, 30)])
    rsi = compute_rsi(close)
    assert rsi.iloc[-1] == pytest.approx(0.0)


def test_compute_bollinger_bands_pct_b_is_0_5_for_flat_series():
    # Zero variance -> band_width is 0 -> pct_b divides by NaN-guarded 0 -> NaN,
    # not a divide-by-zero error.
    close = pd.Series([100.0] * (BB_LENGTH + 5))
    _, _, pct_b = compute_bollinger_bands(close)
    assert pct_b.iloc[-1] != pct_b.iloc[-1]  # NaN != NaN


def test_compute_bollinger_bands_pct_b_at_extremes():
    # A clear downward spike below a flat baseline should read pct_b well below 0.
    values = [100.0] * BB_LENGTH + [80.0]
    close = pd.Series(values)
    upper, lower, pct_b = compute_bollinger_bands(close)
    assert pct_b.iloc[-1] < 0


def test_compute_atr_is_a_plain_rolling_mean_not_wilder():
    n = 20
    high = pd.Series([100.0 + i for i in range(n)])
    low = pd.Series([99.0 + i for i in range(n)])
    close = pd.Series([99.5 + i for i in range(n)])
    df = pd.DataFrame({"high": high, "low": low, "close": close})

    atr = compute_atr(df, length=14)

    # First 13 values NaN (rolling window not full yet), 14th is the plain mean
    # of the first 14 True Range values -- no Wilder recursive smoothing.
    assert atr.iloc[:13].isna().all()
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    assert atr.iloc[13] == pytest.approx(tr.iloc[:14].mean())


def test_check_buy_signal_requires_both_conditions():
    rsi = pd.Series([50.0, 50.0, 20.0, 50.0])  # prior bar (i-1=2) is oversold
    pct_b = pd.Series([0.5, 0.5, 0.5, 0.02])  # current bar (i=3) is at bottom of band
    assert check_buy_signal(rsi, pct_b, 3) is True


def test_check_buy_signal_false_when_pct_b_not_at_bottom():
    rsi = pd.Series([50.0, 50.0, 20.0, 50.0])
    pct_b = pd.Series([0.5, 0.5, 0.5, 0.5])
    assert check_buy_signal(rsi, pct_b, 3) is False


def test_check_buy_signal_false_when_prior_rsi_not_oversold():
    rsi = pd.Series([50.0, 50.0, 50.0, 50.0])
    pct_b = pd.Series([0.5, 0.5, 0.5, 0.02])
    assert check_buy_signal(rsi, pct_b, 3) is False


def test_check_buy_signal_false_before_warmup():
    rsi = pd.Series([20.0, 20.0])
    pct_b = pd.Series([0.01, 0.01])
    assert check_buy_signal(rsi, pct_b, 1) is False  # i < 3


def test_check_buy_signal_false_when_pct_b_is_nan():
    rsi = pd.Series([50.0, 50.0, 20.0, 50.0])
    pct_b = pd.Series([0.5, 0.5, 0.5, np.nan])
    assert check_buy_signal(rsi, pct_b, 3) is False
