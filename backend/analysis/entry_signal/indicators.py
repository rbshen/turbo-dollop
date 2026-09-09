"""BB+RSI indicator math and signal condition, ported verbatim from the
reference trading bot (execution/backtest/notification code discarded --
see CLAUDE.md's technical entry-signal section). Deliberately NOT reusing
analysis/trend_structure/atr.py::compute_atr -- that module uses Wilder's
smoothing, while the reference bot (and this port) uses a plain rolling
mean of True Range, a different, real formula choice worth keeping
distinct rather than silently reusing the wrong one.
"""

import numpy as np
import pandas as pd

RSI_LENGTH = 14
BB_LENGTH = 20
BB_STD = 2.0
BB_LOWER_PCT = 0.05  # bottom 5% of the band
RSI_OVERSOLD = 30
ATR_LENGTH = 14
# The reference bot's own default for its initial-stop calc (close - ATR x
# ATR_MULTIPLIER) -- not its trailing/re-raise logic, which has no place
# here since there's no open position to trail a stop for.
ATR_MULTIPLIER = 2


def compute_rsi(close: pd.Series, length: int = RSI_LENGTH) -> pd.Series:
    """RSI via EWM (alpha=1/length, adjust=False) -- matches the reference
    bot's own comment: "RSI using EWM"."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_bollinger_bands(
    close: pd.Series, length: int = BB_LENGTH, std: float = BB_STD
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Standard Bollinger Bands. Returns (upper, lower, pct_b). pct_b = 0.0
    means price is at the lower band, 1.0 at the upper band; values outside
    [0, 1] are possible when price is beyond the bands."""
    mid = close.rolling(length).mean()
    sigma = close.rolling(length).std(ddof=0)
    upper = mid + std * sigma
    lower = mid - std * sigma
    band_width = upper - lower
    pct_b = (close - lower) / band_width.replace(0, np.nan)
    return upper, lower, pct_b


def compute_atr(df: pd.DataFrame, length: int = ATR_LENGTH) -> pd.Series:
    """Average True Range via a plain rolling mean of True Range (not
    Wilder's smoothing -- see module docstring). Ported for future signal
    types since the reference bot's own extraction list called it out
    explicitly; unused by check_buy_signal below, which only needs RSI/BB."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(length).mean()


def check_buy_signal(rsi: pd.Series, pct_b: pd.Series, i: int) -> bool:
    """BUY signal requires BOTH: (1) %B <= BB_LOWER_PCT (price at or below
    the bottom 5% of the band) on the CURRENT candle, and (2) RSI was
    oversold (< RSI_OVERSOLD) on the PRIOR candle -- ported exactly,
    including the prior-bar RSI offset and the i<3 warmup guard."""
    if i < 3:
        return False

    pct_b_now = pct_b.iloc[i]
    if pd.isna(pct_b_now):
        return False

    # A NaN prior RSI (still in warmup) compares False against RSI_OVERSOLD
    # with no special-casing needed, same as the reference bot relies on.
    rsi_prior = rsi.iloc[i - 1]
    return bool(pct_b_now <= BB_LOWER_PCT and rsi_prior < RSI_OVERSOLD)
