"""Fractal swing-low/swing-high detection + same-kind-only breach
annotation for Liquidity Zone (LP) detection.

Deliberately NOT analysis/trend_structure/swings.py: that module detects
swings on CLOSE only, with a hardcoded N=5 window, for the BOS/trend-state
machine's own purposes. This feature's locked spec needs swings on
LOW/HIGH (not Close) with a caller-configurable window, so this is a
small, independent implementation using the same vectorized shift
technique.

See engine.py's own module docstring for the breach-semantics
clarification versus the reference lp_detector_polygon_clustered.py this
was adapted from.
"""

import numpy as np
import pandas as pd

from .types import SwingEvent


def find_swing_lows(low: pd.Series, k: int) -> pd.Series:
    """A bar is a swing low if its Low is strictly less than the Low of
    the k bars immediately before AND after it. The first/last k bars can
    never be confirmed (no full window on both sides) -- False, not NaN,
    matching trend_structure/swings.py's own convention."""
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


def annotate_swings(prices: pd.Series, is_swing: pd.Series, kind: str) -> list[SwingEvent]:
    """Builds the ordered list of swing events and, for each, the position
    of the first LATER SWING of the SAME kind that breaches it -- for
    kind="low" (support), a later swing low with a strictly lower price;
    for kind="high" (resistance), a later swing high with a strictly
    higher price.

    This is the one deliberate divergence from the reference script
    (lp_detector_polygon_clustered.py's annotate_swing_lows), which
    actually checks every later BAR, not just later swings -- the locked
    spec here is explicit that an ordinary non-swing bar must never
    invalidate a level, only a later swing can.
    """
    positions = np.where(is_swing.values)[0]
    swing_prices = prices.values[positions]
    index = prices.index

    events: list[SwingEvent] = []
    for i, pos in enumerate(positions):
        price = swing_prices[i]
        later = swing_prices[i + 1 :]
        breaches = np.where(later < price)[0] if kind == "low" else np.where(later > price)[0]
        breach_pos = int(positions[i + 1 + breaches[0]]) if len(breaches) else None
        bar_date = index[pos].date() if hasattr(index[pos], "date") else index[pos]
        events.append(SwingEvent(pos=int(pos), date=bar_date, price=float(price), breach_pos=breach_pos))
    return events


def valid_prices_at(events: list[SwingEvent], as_of_pos: int) -> list[SwingEvent]:
    """Currently-valid (confirmed by, and unbreached as of, `as_of_pos`)
    swing events, in their original chronological order."""
    return [e for e in events if e.pos <= as_of_pos and (e.breach_pos is None or e.breach_pos > as_of_pos)]
