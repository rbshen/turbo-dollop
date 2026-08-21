"""Average True Range via Wilder's smoothing -- the standard/canonical ATR
definition (a plain SMA of True Range is "N-day average true range," not
"ATR" in the sense every charting platform/trading library means). This is
a real, consequential formula choice for the flip-gate's ratio=margin/ATR
calculation, so it's called out explicitly here rather than silently
assumed.
"""

import pandas as pd

ATR_PERIOD = 14


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = ATR_PERIOD) -> pd.Series:
    """Wilder's smoothing: seeded with a plain simple average of the first
    `period` true-range values, then recursively smoothed
    atr[t] = (atr[t-1] * (period - 1) + tr[t]) / period -- equivalent to an
    EMA with alpha = 1/period, but seeded from an SMA rather than pandas'
    ewm default (which seeds from the first observation alone). The first
    `period`-1 values are NaN (no seed available yet)."""
    tr = true_range(high, low, close)
    atr = pd.Series(float("nan"), index=tr.index)
    if len(tr) < period:
        return atr

    atr.iloc[period - 1] = tr.iloc[:period].mean()
    prev = atr.iloc[period - 1]
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr.iloc[i]) / period
        atr.iloc[i] = prev
    return atr
