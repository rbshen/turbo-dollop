"""60-day Kaufman Efficiency Ratio regime overlay -- informational context
alongside the flip-gate state, feeding conviction.py's regime multiplier.
"""

import pandas as pd

ER_WINDOW = 60
TRENDING_THRESHOLD = 0.15


def efficiency_ratio(close: pd.Series, window: int = ER_WINDOW) -> pd.Series:
    """ER[t] = |close[t] - close[t-window]| / sum(|close[i]-close[i-1]| for
    the trailing `window` days)."""
    direction = (close - close.shift(window)).abs()
    volatility = close.diff().abs().rolling(window=window).sum()
    return direction / volatility


def latest_regime(close: pd.Series, window: int = ER_WINDOW) -> tuple[float | None, str | None]:
    """Returns (efficiency_ratio, regime) as of the most recent bar --
    (None, None) if there isn't enough history yet for a real ER value."""
    er_series = efficiency_ratio(close, window)
    valid = er_series.dropna()
    if valid.empty:
        return None, None
    er = float(valid.iloc[-1])
    regime = "trending" if er >= TRENDING_THRESHOLD else "range-bound"
    return er, regime
