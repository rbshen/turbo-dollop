"""Fair value gap (FVG) detection for the Chart tab's D·6M overlay (docs/specs/fvg.md).

A three-candle pattern (c1, c2, c3; c4 is the candle after c3):
  bullish: low(c3) > high(c1)   -> zone bottom = high(c1), top = low(c3)
  bearish: high(c3) < low(c1)   -> zone top = low(c1), bottom = high(c3)
Strict inequalities, so a zero-height gap is not a gap. A gap is kept only if its height is strictly greater than
`mult` x ATR(14, Wilder) at c3 (a missing or non-positive ATR keeps nothing: fail closed). The zone ends at the
first candle AFTER c3 whose CLOSE is beyond the far side (bullish: close < bottom; bearish: close > top), strict;
wicks never end it. The ATR filter affects detection only, never the ending.

Pure and index-based: no dates, no windowing (the caller applies the visible-window rule and turns indexes into times).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

# A gap must be taller than this many ATRs to be drawn. Deliberately a constant, not a Setting.
FVG_ATR_MULTIPLIER = 0.5


@dataclass(frozen=True)
class Fvg:
    side: str  # "bullish" | "bearish"
    top: float
    bottom: float
    c3_index: int  # position of the third candle in the frame
    start_index: int  # c4's position; == len(frame) when c3 is the last bar (no c4 yet)
    end_index: int | None  # position of the first candle that closes beyond the far side; None = still open


def detect_fvgs(bars: pd.DataFrame, atr: pd.Series, mult: float = FVG_ATR_MULTIPLIER) -> list[Fvg]:
    """All filtered gaps in `bars` (high/low/close columns, oldest first), in c3 order. `atr` aligns with `bars`."""
    n = len(bars)
    if n < 3:
        return []
    high = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    atr_v = atr.to_numpy(dtype=float)

    # Index i is c3; c1 is i-2.
    c1_high, c1_low = high[:-2], low[:-2]
    c3_high, c3_low = high[2:], low[2:]
    c3_atr = atr_v[2:]
    bull_height = c3_low - c1_high
    bear_height = c1_low - c3_high
    atr_ok = np.isfinite(c3_atr) & (c3_atr > 0)
    with np.errstate(invalid="ignore"):
        threshold = mult * c3_atr
        bull = atr_ok & (bull_height > 0) & (bull_height > threshold)
        bear = atr_ok & (bear_height > 0) & (bear_height > threshold)

    out: list[Fvg] = []
    for k in np.flatnonzero(bull | bear):
        i = int(k) + 2
        if bull[k]:
            side, bottom, top = "bullish", float(c1_high[k]), float(c3_low[k])
        else:
            side, bottom, top = "bearish", float(c3_high[k]), float(c1_low[k])
        after = close[i + 1 :]
        with np.errstate(invalid="ignore"):
            broken = after < bottom if side == "bullish" else after > top
        hit = np.flatnonzero(broken)
        end = i + 1 + int(hit[0]) if hit.size else None
        out.append(Fvg(side=side, top=top, bottom=bottom, c3_index=i, start_index=i + 1, end_index=end))
    return out
