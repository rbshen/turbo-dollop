"""Accumulation/Distribution line and Chaikin Oscillator -- feeds the A/D
Bullish Divergence signal (see classification.py). Chaikin Oscillator's
canonical definition uses standard EMA smoothing (span=3, span=10), unlike
ATR's Wilder smoothing (atr.py) -- a real, deliberate formula choice, called
out explicitly the same way atr.py calls out its own smoothing convention.
"""

import pandas as pd

AD_FAST_SPAN = 3
AD_SLOW_SPAN = 10


def compute_ad_line(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Money Flow Multiplier * Volume, cumulatively summed. MFM is defined as
    0.0 (not NaN) on a zero-range bar (high == low) -- the standard
    convention, avoiding a division-by-zero NaN that would otherwise
    propagate through the cumulative sum for every subsequent bar."""
    range_ = high - low
    mfm = ((close - low) - (high - close)) / range_
    mfm = mfm.where(range_ != 0, 0.0)
    money_flow_volume = mfm * volume
    return money_flow_volume.cumsum()


def compute_chaikin_oscillator(ad_line: pd.Series) -> pd.Series:
    """EMA(3) - EMA(10) of the A/D line, standard (non-Wilder) EMA with
    adjust=False so each bar seeds directly from the recursive formula
    rather than pandas' default weighted-by-all-history convention -- same
    "not the pandas default" carefulness atr.py documents for its own
    smoothing, just a different (standard EMA, not Wilder's) target
    formula."""
    fast = ad_line.ewm(span=AD_FAST_SPAN, adjust=False).mean()
    slow = ad_line.ewm(span=AD_SLOW_SPAN, adjust=False).mean()
    return fast - slow
