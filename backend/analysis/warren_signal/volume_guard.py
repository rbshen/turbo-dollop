"""Candle-level volume guard for the per-ticker Warren Blue Up profiles.

FMP's intraday volume has episodes (measured 2026-10-04 over 730 days, SPY/QQQ/TQQQ/TECL) where a few single
1-minute prints carry more shares than the whole day's official volume, so the volume-gated Blue branches
(SOS1 `volume <= cap`, SOS2 `volume > Volume_Num`) fire on bars TOS shows no arrow for (QQQ: Nov 2025, Dec 2025,
Feb 2026). The episodes are per symbol and per period, and the day's summed intraday volume against FMP's own daily
(EOD) volume separates them cleanly: normal days sit at 0.6-1.3, the bad ones at 1.5-7.

The guard, applied to the replay's INPUT only (never to the candles a chart displays):

  ratio(day) = sum of that day's 2h-candle volume / that day's daily (EOD) volume
  ratio > DAILY_VOLUME_RATIO_LIMIT, or the day's EOD volume missing / zero / NaN  ->  every candle that day gets
  volume = NaN.

NaN fails both `>` and `<=`, so every volume term in the Blue rules is off that day, while the branches without a
volume term (SOS2 branch c, QQQ's `RSI[1] < 16.3` and `WVF_Buy >= 17` ORs) keep working. Fail-closed: no EOD volume
(the current session, a fetch failure, nothing cached) means no volume-gated Blue. The guard can therefore only
remove a Blue, never add one, and it changes no Yellow/Gray/down-arrow input.

Pure and ticker-agnostic like the rest of this package. It applies only to a profile with volume rules
(`guard_for_profile`); the ANY-TICKER rule reads no volume, so those candles are returned untouched (the same
object). Known limits: the limit was calibrated on four tickers over two years, and the low side (intraday volume
running well below EOD, seen in Mar-Sep 2026) is deliberately not addressed.
"""

import numpy as np
import pandas as pd

from .types import WarrenProfile

# Day is flagged when its summed 2h-candle volume is MORE than this multiple of its EOD volume (equal is kept).
DAILY_VOLUME_RATIO_LIMIT = 1.5


def _naive_days(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Midnight of each timestamp's own (exchange-local) date, naive: the chart's candles are naive ET, the nightly
    job's tz-aware ET, and daily bars are naive midnights -- all reduce to the same calendar date here."""
    if index.tz is not None:
        index = index.tz_localize(None)
    return index.normalize()


def guard_candle_volume(
    candles: pd.DataFrame, daily_volume: pd.Series | None, limit: float = DAILY_VOLUME_RATIO_LIMIT
) -> pd.DataFrame:
    """A copy of `candles` whose `volume` is NaN on every day that fails the check described in the module
    docstring. `daily_volume` is the EOD volume indexed by date (naive midnights or tz-aware); None / empty means
    no day can be verified, so every day is NaN. The input frame is never modified."""
    if "volume" not in candles.columns or candles.empty:
        return candles
    out = candles.copy()
    out["volume"] = out["volume"].astype(float)
    days = _naive_days(out.index)

    day_sum = out["volume"].groupby(days).sum()  # NaN-skipping: a day of all-NaN candles sums to 0
    if daily_volume is None or len(daily_volume) == 0:
        eod = pd.Series(np.nan, index=day_sum.index)
    else:
        dv = daily_volume.copy()
        dv.index = _naive_days(pd.DatetimeIndex(dv.index))
        dv = dv[~dv.index.duplicated(keep="last")]
        eod = dv.reindex(day_sum.index).astype(float)

    verifiable = eod.notna() & (eod > 0)
    ratio = day_sum / eod.where(verifiable)  # NaN where unverifiable
    keep = verifiable & ~(ratio > limit)  # `~(ratio > limit)`, so exactly `limit` is kept
    keep_by_candle = keep.reindex(days).to_numpy()
    out.loc[~keep_by_candle, "volume"] = np.nan
    return out


def guard_for_profile(candles: pd.DataFrame, daily_volume: pd.Series | None, profile: WarrenProfile) -> pd.DataFrame:
    """The guard for a profile that has volume rules; for the ANY-TICKER profile (no volume terms) `candles` is
    returned as the very same object, so those tickers' replay input -- and output -- cannot change."""
    if profile.rules is None:
        return candles
    return guard_candle_volume(candles, daily_volume)
