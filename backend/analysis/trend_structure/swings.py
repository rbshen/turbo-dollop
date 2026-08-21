"""Fractal swing-high/low detection on daily CLOSE prices, N=5 bars each
side -- generalizes analysis/ma_magnet/swings.py's swing-low-only, N=2
convention to both highs and lows at N=5, per this feature's spec. See
CLAUDE.md's "Trend structure analysis (Technical)" section.
"""

import pandas as pd

from .types import SwingPoint

FRACTAL_N = 5

_OFFSETS = list(range(-FRACTAL_N, 0)) + list(range(1, FRACTAL_N + 1))


def find_swing_highs(close: pd.Series) -> pd.Series:
    """A bar is a swing high if its close is strictly greater than the
    close of the FRACTAL_N bars immediately before it AND the FRACTAL_N bars
    immediately after it. The first/last FRACTAL_N bars can never be
    confirmed (no full window on both sides) -- False, not NaN, mirroring
    ma_magnet/swings.py's own convention."""
    is_high = pd.Series(True, index=close.index)
    for offset in _OFFSETS:
        is_high &= close > close.shift(offset)
    return is_high.fillna(False)


def find_swing_lows(close: pd.Series) -> pd.Series:
    """Mirror of find_swing_highs for swing lows."""
    is_low = pd.Series(True, index=close.index)
    for offset in _OFFSETS:
        is_low &= close < close.shift(offset)
    return is_low.fillna(False)


def extract_swing_points(close: pd.Series) -> list[SwingPoint]:
    """Ordered chronologically, mixing highs and lows as they actually
    occur -- a single bar can never be both (a bar can't be strictly
    greater than AND strictly less than the same neighbors)."""
    highs = find_swing_highs(close)
    lows = find_swing_lows(close)
    points: list[SwingPoint] = []
    for idx in close.index:
        bar_date = idx.date() if hasattr(idx, "date") else idx
        if bool(highs.loc[idx]):
            points.append(SwingPoint(date=bar_date, price=float(close.loc[idx]), kind="high"))
        if bool(lows.loc[idx]):
            points.append(SwingPoint(date=bar_date, price=float(close.loc[idx]), kind="low"))
    points.sort(key=lambda p: p.date)
    return points
