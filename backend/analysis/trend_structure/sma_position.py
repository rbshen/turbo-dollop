"""Simple-moving-average position tracking (20/50/200 vs latest close) --
position_pct = (close - SMA)/SMA*100, plus a prior-day-vs-current-day cross
flag. A small, single-concern module (matching atr.py's own style), not a
reuse of analysis/ma_magnet/indicators.py::compute_mas -- ma_magnet is
documented as an unwired research script (see its own run.py docstring),
and production code deliberately never imports from it.
"""

from dataclasses import dataclass

import pandas as pd

from .types import SmaCross


@dataclass(frozen=True)
class SmaPosition:
    position_pct: float | None
    cross: SmaCross | None


def compute_sma_position(close: pd.Series, period: int) -> SmaPosition:
    """position_pct for the latest bar; None whenever fewer than `period`
    bars of history exist yet (rolling(window=period).mean()'s default
    min_periods == window already produces NaN there -- same
    degrade-gracefully convention every other trend_structure calc uses for
    thin history, e.g. a recent IPO).

    cross compares the PRIOR bar's own SMA against the PRIOR close -- not
    today's SMA reused against yesterday's close -- since the SMA itself
    moves day to day; reusing today's SMA would false-positive/miss
    crossings whenever it shifts meaningfully (see CLAUDE.md's SMA position
    tracking entry for the full tradeoff). None whenever there's no valid
    prior bar to compare against (a ticker's very first eligible bar, i.e.
    exactly `period` bars of history).

    today_sma == 0 (and, symmetrically, the prior day's SMA) is guarded
    against directly -- effectively impossible for a real equity close, but
    a 0/0 division would otherwise upsert inf/nan into SQLite, which
    Python's default JSON encoder serializes as the literal tokens
    Infinity/NaN, invalid strict JSON that would break the frontend's
    JSON.parse on that one row."""
    if len(close) == 0:
        return SmaPosition(position_pct=None, cross=None)

    sma = close.rolling(window=period).mean()
    today_sma = sma.iloc[-1]
    if pd.isna(today_sma) or today_sma == 0:
        return SmaPosition(position_pct=None, cross=None)

    today_pos = (close.iloc[-1] - today_sma) / today_sma * 100

    if len(close) < 2 or pd.isna(sma.iloc[-2]) or sma.iloc[-2] == 0:
        return SmaPosition(position_pct=today_pos, cross=None)

    prior_pos = (close.iloc[-2] - sma.iloc[-2]) / sma.iloc[-2] * 100
    cross: SmaCross | None
    if prior_pos <= 0 and today_pos > 0:
        cross = "up"
    elif prior_pos >= 0 and today_pos < 0:
        cross = "down"
    else:
        cross = None

    return SmaPosition(position_pct=today_pos, cross=cross)
