"""Full Stochastic Oscillator (5, 3, 3) -- no prior implementation of any
stochastic variant exists anywhere in this codebase (confirmed via project-
wide grep during the Chart tab design investigation), so this is greenfield,
not a port of an existing convention. Explicitly "Full" (SMA-smoothed %K),
not "Fast" (raw %K) -- the two are easy to conflate and there's no other
implementation in this codebase to cross-check against, so the distinction
is spelled out here rather than assumed.
"""

import pandas as pd

STOCH_K_PERIOD = 5
STOCH_SMOOTH = 3


def compute_stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = STOCH_K_PERIOD, smooth: int = STOCH_SMOOTH
) -> tuple[pd.Series, pd.Series]:
    """Returns (full_k, full_d).

    raw_k = 100 * (close - lowest_low_over_k_period) / (highest_high_over_k_period - lowest_low_over_k_period)
    full_k ("Full %K", the displayed line) = SMA(smooth) of raw_k -- this is
    the "slowing" step that distinguishes Full from Fast stochastic.
    full_d ("%D") = SMA(smooth) of full_k.

    A flat raw window (highest_high == lowest_low, e.g. a halted/illiquid
    name with an unchanged price) divides by zero -- left as the resulting
    NaN/inf rather than special-cased, same "let pandas produce NaN, don't
    fabricate a value" convention as compute_bollinger_bands' band_width
    guard and sma_position.py's own 0-guard (both explicitly checked there
    only because their NaN/inf would otherwise reach SQLite/JSON; this
    output is never persisted, only sliced and returned in an API response,
    so no such guard is needed here)."""
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    raw_k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    full_k = raw_k.rolling(smooth).mean()
    full_d = full_k.rolling(smooth).mean()
    return full_k, full_d
