"""Pure Liquidity Zone (LP) detection engine -- swing detection + same-kind
breach tracking + price clustering, entirely timeframe-agnostic (called
once per timeframe by data/liquidity_zone_data.py, with that timeframe's
own swing_bars/cluster_pct/num_zones settings).

Breach semantics (LOCKED, deliberately different from the reference
lp_detector_polygon_clustered.py this was adapted from): a swing low
becomes a support LP the moment it's confirmed, and stays valid until a
LATER SWING LOW's Low trades below it -- an ordinary non-swing bar
breaching the level does NOT invalidate it. Symmetric for swing highs /
resistance. See swings.py::annotate_swings for where this is enforced.

Clustering representative direction (see clustering.py's own docstring
for the full reasoning): support clusters collapse to their LOWEST
member (the true "last line of defense"); resistance clusters collapse
to their HIGHEST member (the true ceiling that must be cleared).

Nearest-N filtering: currently-valid zones can, in principle, sit on the
"wrong" side of the last price (e.g. a still-unbreached old swing low
that price has since fallen below without a later swing low confirming
that breach yet) -- these are filtered out before taking the nearest N,
since a support level above today's price (or a resistance level below
it) isn't a meaningful "nearest support/resistance" for the card this
feeds. This is a display refinement on top of the locked breach rule, not
a change to it.
"""

from datetime import date

import pandas as pd

from .clustering import cluster_prices
from .swings import annotate_swings, find_swing_highs, find_swing_lows, valid_prices_at
from .types import LiquidityZoneResult


def _bar_date(index: pd.Index, pos: int) -> date:
    value = index[pos]
    return value.date() if hasattr(value, "date") else value


def compute_liquidity_zones(df: pd.DataFrame, swing_bars: int, cluster_pct: float, num_zones: int) -> LiquidityZoneResult:
    """df needs lowercase open/high/low/close/volume columns and a
    DatetimeIndex, ascending by date (matching every other engine in this
    codebase). Returns the nearest `num_zones` clustered support zones
    (below the last close) and resistance zones (above it), nearest
    first."""
    if df.empty:
        raise ValueError("compute_liquidity_zones requires a non-empty OHLC frame")

    last_pos = len(df) - 1
    last_price = float(df["close"].iloc[-1])
    as_of = _bar_date(df.index, last_pos)

    is_swing_low = find_swing_lows(df["low"], swing_bars)
    is_swing_high = find_swing_highs(df["high"], swing_bars)

    low_events = annotate_swings(df["low"], is_swing_low, kind="low")
    high_events = annotate_swings(df["high"], is_swing_high, kind="high")

    valid_lows = valid_prices_at(low_events, last_pos)
    valid_highs = valid_prices_at(high_events, last_pos)

    # Support: highest price first (adjacency for clustering), representative = lowest member.
    support_items = sorted(((e.price, e.date) for e in valid_lows), key=lambda item: item[0], reverse=True)
    support_zones = cluster_prices(support_items, cluster_pct, representative="min")
    support_zones = [z for z in support_zones if z.price <= last_price]
    support_zones.sort(key=lambda z: z.price, reverse=True)  # nearest (highest) first

    # Resistance: lowest price first (adjacency for clustering), representative = highest member.
    resistance_items = sorted(((e.price, e.date) for e in valid_highs), key=lambda item: item[0])
    resistance_zones = cluster_prices(resistance_items, cluster_pct, representative="max")
    resistance_zones = [z for z in resistance_zones if z.price >= last_price]
    resistance_zones.sort(key=lambda z: z.price)  # nearest (lowest) first

    return LiquidityZoneResult(
        last_price=last_price,
        as_of=as_of,
        support=support_zones[:num_zones],
        resistance=resistance_zones[:num_zones],
    )
