"""Fractal swing-low/swing-high detection + any-later-bar breach
annotation for Liquidity Zone (LP) detection.

Swings are detected on
LOW/HIGH (not Close) with a caller-configurable window, so this is a
small, independent implementation using the same vectorized shift
technique.

Breach semantics follow the reference "Left Precedence" Pine script: any
later bar crossing the level breaches it (see annotate_swings).
"""

import numpy as np
import pandas as pd

from .types import SwingEvent


def find_swing_lows(low: pd.Series, k: int) -> pd.Series:
    """A bar is a swing low if its Low is strictly less than the Low of
    the k bars immediately before AND after it. The first/last k bars can
    never be confirmed (no full window on both sides) -- False, not NaN,
    the usual fractal convention."""
    is_low = pd.Series(True, index=low.index)
    for offset in list(range(-k, 0)) + list(range(1, k + 1)):
        is_low &= low < low.shift(offset)
    return is_low.fillna(False)


def find_swing_highs(high: pd.Series, k: int) -> pd.Series:
    """Mirror of find_swing_lows for swing highs."""
    is_high = pd.Series(True, index=high.index)
    for offset in list(range(-k, 0)) + list(range(1, k + 1)):
        is_high &= high > high.shift(offset)
    return is_high.fillna(False)


def annotate_swings(prices: pd.Series, is_swing: pd.Series, kind: str, with_ts: bool = False) -> list[SwingEvent]:
    """Builds the ordered list of swing events and, for each, the position
    of the first LATER BAR (swing or not) that breaches it -- for
    kind="low" (support), a bar whose Low is strictly below the level; for
    kind="high" (resistance), a bar whose High is strictly above it.
    `prices` is the Low series for "low" and the High series for "high".
    `with_ts` additionally records each swing bar's exact timestamp (intraday callers).
    Once breached, a level stays breached (only the first breach is
    recorded). Matches the reference Pine script's per-bar
    `if not breached and low < price` check.
    """
    positions = np.where(is_swing.values)[0]
    values = prices.values
    index = prices.index

    events: list[SwingEvent] = []
    for pos in positions:
        price = values[pos]
        later = values[pos + 1 :]
        hits = np.flatnonzero(later < price) if kind == "low" else np.flatnonzero(later > price)
        breach_pos = int(pos + 1 + hits[0]) if len(hits) else None
        bar_date = index[pos].date() if hasattr(index[pos], "date") else index[pos]
        ts = index[pos].to_pydatetime() if with_ts else None
        events.append(SwingEvent(pos=int(pos), date=bar_date, price=float(price), breach_pos=breach_pos, ts=ts))
    return events


def valid_prices_at(events: list[SwingEvent], as_of_pos: int) -> list[SwingEvent]:
    """Currently-valid (confirmed by, and unbreached as of, `as_of_pos`)
    swing events, in their original chronological order."""
    return [e for e in events if e.pos <= as_of_pos and (e.breach_pos is None or e.breach_pos > as_of_pos)]
