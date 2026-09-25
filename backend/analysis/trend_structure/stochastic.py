"""Full Stochastic Oscillator (5, 3, 3, EMA) -- thinkScript `StochasticFull` parity.

Matches ThinkOrSwim / the user's TradingView "Stoch" indicator at K=5, slowing=3,
D=3, averageType=EXPONENTIAL (2026-09-25; see docs/stochastic_divergence_
investigation_2026-09-25.md). Originally SMA-smoothed, which differed from the
reference by ~5-7 points on average. Explicitly "Full" (smoothed %K), not "Fast"
(raw %K).
"""

import numpy as np
import pandas as pd

STOCH_K_PERIOD = 5
STOCH_SMOOTH = 3


def compute_stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = STOCH_K_PERIOD, smooth: int = STOCH_SMOOTH
) -> tuple[pd.Series, pd.Series]:
    """Returns (full_k, full_d).

    fast_k = 100 * (close - lowest_low) / (highest_high - lowest_low), over a
    k_period window that INCLUDES the current bar. A zero-range window
    (highest_high == lowest_low) reads 0, not NaN (thinkScript's
    `if c2 != 0 then c1/c2*100 else 0`), so a NaN never enters the EMA; only the
    k_period-1 warm-up bars stay NaN.
    full_k = EMA(fast_k, smooth); full_d = EMA(full_k, smooth) -- the ratio is
    smoothed (not numerator/denominator separately), classic recursive form
    ema[t] = ema[t-1] + alpha*(x[t] - ema[t-1]), alpha = 2/(n+1), seeded with the
    first valid value (pandas ewm(adjust=False)). Seeding is immaterial: at
    alpha 0.5 a different seed changes bars 40+ later by < 1e-14."""
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    rng = highest_high - lowest_low
    fast_k = pd.Series(np.where(rng != 0, 100 * (close - lowest_low) / rng.where(rng != 0), 0.0), index=close.index).where(
        lowest_low.notna()
    )
    alpha = 2 / (smooth + 1)
    full_k = fast_k.ewm(alpha=alpha, adjust=False).mean()
    full_d = full_k.ewm(alpha=alpha, adjust=False).mean()
    return full_k, full_d
