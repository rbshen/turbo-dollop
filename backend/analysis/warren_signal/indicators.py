"""Warren RSI/ADX/WVF indicator math, ported from the "ANY TICKER" reference
Pine script (execution/alert/plot code discarded -- see CLAUDE.md's Warren
signal section). Deliberately NOT reusing analysis/entry_signal/indicators.py::
compute_rsi: that RSI is EWM-seeded (pandas' ewm default, seeded from the
first observation), while Pine's built-in `RSI(14)` uses `ta.rma` internally
-- Wilder-seeded (SMA over the first `length` bars, then recursive), matching
analysis/trend_structure/atr.py::compute_atr's own convention. Warren's state
machine depends on exact-value threshold crossings (12, 30, 70, 80.81, 84.75),
so this divergence is deliberate, not an oversight -- see wilder_rma below,
shared by RSI, DMI, and ADX, all of which use the identical Wilder smoothing.

pivotLow (plain, not pivotLowMajor), adxBetween, wvfBetween, and
paraHighestHigh/paraDrop from the reference script are dead code -- like
scanOverSold1/scanOverSold2, none of them gate any arrow or state transition
in the ported logic below. Confirmed with the user before this file was
written; not ported.
"""

import numpy as np
import pandas as pd

RSI_LENGTH = 14
DI_LENGTH = 14
ADX_LENGTH = 14
WVF_LOOKBACK = 22  # `pd` in the reference script
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
SCAN_BLUE_RSI_THRESHOLD = 12  # scanOverSold4


def wilder_rma(s: pd.Series, length: int) -> pd.Series:
    """Wilder's smoothing (aka Pine's ta.rma): seeded with a plain simple
    average of the first `length` values, then recursively smoothed
    out[t] = (out[t-1] * (length - 1) + s[t]) / length -- same seeding
    convention as analysis/trend_structure/atr.py::compute_atr, extracted
    here since RSI/DMI's DI-smoothing/ADX's DX-smoothing all need the exact
    same recursion. The seed uses nanmean, not a plain mean: RSI's own
    gain/loss series has a structurally-NaN first element (close.diff()'s
    first row has no prior bar to diff against), which atr.py's own
    true_range never hits (its row-wise max(axis=1) already drops the same
    kind of leading NaN before atr.py's seed ever sees it) -- a plain
    .mean() would propagate that one NaN through the whole seed instead of
    just skipping it. The first `length` - 1 values are NaN (no seed yet)."""
    out = pd.Series(np.nan, index=s.index, dtype=float)
    if len(s) < length:
        return out
    vals = s.to_numpy()
    out_vals = out.to_numpy().copy()
    out_vals[length - 1] = np.nanmean(vals[:length])
    prev = out_vals[length - 1]
    for i in range(length, len(s)):
        prev = (prev * (length - 1) + vals[i]) / length
        out_vals[i] = prev
    return pd.Series(out_vals, index=s.index)


def compute_rsi_wilder(close: pd.Series, length: int = RSI_LENGTH) -> pd.Series:
    """RSI via wilder_rma -- matches Pine's built-in ta.rsi, NOT
    entry_signal.indicators.compute_rsi's EWM-seeded version (see module
    docstring)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = wilder_rma(gain, length)
    avg_loss = wilder_rma(loss, length)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)


def compute_dmi_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, di_length: int = DI_LENGTH, adx_length: int = ADX_LENGTH
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Standard Wilder DMI(di_length, adx_length) -- returns (+DI, -DI, ADX).
    Only ADX is actually consumed by the state machine (via anySell's
    `adxValue<40`), but +DI/-DI are real, necessary intermediates (DX needs
    both), not unused dead code the way adxBetween is -- kept in the return
    tuple for completeness/testability, matching the reference script's own
    `[plus, minus, adxValue] = DMI(14,14)` shape."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)

    tr = _true_range(high, low, close)
    tr_smooth = wilder_rma(tr, di_length)
    plus_dm_smooth = wilder_rma(plus_dm, di_length)
    minus_dm_smooth = wilder_rma(minus_dm, di_length)

    plus_di = 100 * plus_dm_smooth / tr_smooth.replace(0, np.nan)
    minus_di = 100 * minus_dm_smooth / tr_smooth.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = wilder_rma(dx, adx_length)
    return plus_di, minus_di, adx


def compute_wvf_buy(close: pd.Series, low: pd.Series, lookback: int = WVF_LOOKBACK) -> pd.Series:
    """wvfBuy = (highest(close, pd) - low) / highest(close, pd) * 100."""
    highest_close = close.rolling(lookback).max()
    return (highest_close - low) / highest_close.replace(0, np.nan) * 100


def compute_wvf_sell(close: pd.Series, high: pd.Series, lookback: int = WVF_LOOKBACK) -> pd.Series:
    """wvfSell = (lowest(close, pd) - high) / lowest(close, pd) * 100."""
    lowest_close = close.rolling(lookback).min()
    return (lowest_close - high) / lowest_close.replace(0, np.nan) * 100


def compute_pivot_high(rsi: pd.Series) -> pd.Series:
    """rsiOverbought: rsi[3]>70 AND rsi[3]<rsi[2] AND rsi[2]<rsi[1] AND
    rsi[1]>rsi AND rsi>70 -- three bars rising through overbought, then
    turning down while still above 70. NaN comparisons (warmup) already
    read False; fillna makes the dtype a clean bool for the state-machine
    loop's own iloc access."""
    r1, r2, r3 = rsi.shift(1), rsi.shift(2), rsi.shift(3)
    cond = (r3 > RSI_OVERBOUGHT) & (r3 < r2) & (r2 < r1) & (r1 > rsi) & (rsi > RSI_OVERBOUGHT)
    return cond.fillna(False).astype(bool)


def compute_pivot_low_major(rsi: pd.Series) -> pd.Series:
    """scanOverSold3: rsi[3]<30 AND rsi[2]<30 AND rsi[1]<30 AND rsi[1]<rsi
    AND rsi>30 -- three consecutive oversold bars recovering back above 30."""
    r1, r2, r3 = rsi.shift(1), rsi.shift(2), rsi.shift(3)
    cond = (r3 < RSI_OVERSOLD) & (r2 < RSI_OVERSOLD) & (r1 < RSI_OVERSOLD) & (r1 < rsi) & (rsi > RSI_OVERSOLD)
    return cond.fillna(False).astype(bool)


def compute_scan_blue(rsi: pd.Series, threshold: float = SCAN_BLUE_RSI_THRESHOLD) -> pd.Series:
    """scanOverSold4: rsi[1] <= 12 -- the Blue trigger."""
    cond = rsi.shift(1) <= threshold
    return cond.fillna(False).astype(bool)
