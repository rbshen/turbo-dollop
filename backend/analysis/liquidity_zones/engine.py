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

Most-recently-breached tracking: a breached swing is, by the locked
breach rule above, no longer "valid" -- but the single most recent
breach per side is still worth surfacing (see BrokenZone's own
docstring) if it clears two hard filters, evaluated fresh every call
against `breach_recency_bars` (rule 1, recency) and against the FULL
clustered valid-zone set -- deliberately the same set used before the
wrong-side-of-price/num_zones display filters above, since a zone that's
valid but merely hidden from display is still a real obstacle for this
comparison (rule 2, positional). No clustering is applied across
breached candidates themselves -- this is a single scalar per side, not
a second zone list.

Rule 1 (recency) is measured from the last bar to the ZONE'S OWN swing
point (its original formation), NOT to the later breach bar -- a zone
formed long ago is stale even if the swing that broke it just happened.
This is strictly tighter than a breach-bar-measured window (breach_pos
is always >= the zone's own pos, so the gap to last_pos can only be
smaller when measured from the breach bar) -- confirmed via a real case
(MSFT, 2026-09-17) where a support formed 9 bars back but breached only
4 bars back incorrectly qualified under an earlier, breach-bar-measured
version of this rule."""

from datetime import date

import pandas as pd

from .clustering import cluster_prices
from .swings import SwingEvent, annotate_swings, find_swing_highs, find_swing_lows, valid_prices_at
from .types import BrokenZone, LiquidityZoneResult


def _bar_date(index: pd.Index, pos: int) -> date:
    value = index[pos]
    return value.date() if hasattr(value, "date") else value


def _select_broken_zone(
    events: list[SwingEvent],
    last_pos: int,
    breach_recency_bars: int,
    valid_zone_extreme: float | None,
    kind: str,
    index: pd.Index,
) -> BrokenZone | None:
    """Among `events` (the full swing list for one side), finds the single
    most recently breached candidate clearing both hard filters.
    Recency (rule 1) is measured from `last_pos` to the candidate's OWN
    formation (`e.pos`), not to its breach bar (`e.breach_pos`) -- see
    this module's own docstring for why. kind="low" (support): a
    candidate must sit ABOVE valid_zone_extreme (the highest still-valid
    support zone), if one exists. kind="high" (resistance): a candidate
    must sit BELOW valid_zone_extreme (the lowest still-valid resistance
    zone). "Most recent" is max(breach_pos) -- ties ARE possible (a
    single later swing can breach several earlier, higher-priced swings
    at once), broken by preferring the candidate with the later original
    formation (max pos), since that's the more current of the tied
    levels."""
    candidates = [e for e in events if e.breach_pos is not None and last_pos - e.pos <= breach_recency_bars]
    if kind == "low":
        candidates = [e for e in candidates if valid_zone_extreme is None or e.price > valid_zone_extreme]
    else:
        candidates = [e for e in candidates if valid_zone_extreme is None or e.price < valid_zone_extreme]
    if not candidates:
        return None
    best = max(candidates, key=lambda e: (e.breach_pos, e.pos))
    return BrokenZone(price=best.price, formed_at=best.date, breached_at=_bar_date(index, best.breach_pos))


def compute_liquidity_zones(
    df: pd.DataFrame, swing_bars: int, cluster_pct: float, num_zones: int, breach_recency_bars: int
) -> LiquidityZoneResult:
    """df needs lowercase open/high/low/close/volume columns and a
    DatetimeIndex, ascending by date (matching every other engine in this
    codebase). Returns the nearest `num_zones` clustered support zones
    (below the last close) and resistance zones (above it), nearest
    first, plus at most one most-recently-breached zone per side (see
    BrokenZone's own docstring and this module's docstring)."""
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
    all_support_zones = cluster_prices(support_items, cluster_pct, representative="min")
    support_zones = [z for z in all_support_zones if z.price <= last_price]
    support_zones.sort(key=lambda z: z.price, reverse=True)  # nearest (highest) first

    # Resistance: lowest price first (adjacency for clustering), representative = highest member.
    resistance_items = sorted(((e.price, e.date) for e in valid_highs), key=lambda item: item[0])
    all_resistance_zones = cluster_prices(resistance_items, cluster_pct, representative="max")
    resistance_zones = [z for z in all_resistance_zones if z.price >= last_price]
    resistance_zones.sort(key=lambda z: z.price)  # nearest (lowest) first

    highest_valid_support = max((z.price for z in all_support_zones), default=None)
    lowest_valid_resistance = min((z.price for z in all_resistance_zones), default=None)

    broken_support = _select_broken_zone(low_events, last_pos, breach_recency_bars, highest_valid_support, "low", df.index)
    broken_resistance = _select_broken_zone(high_events, last_pos, breach_recency_bars, lowest_valid_resistance, "high", df.index)

    return LiquidityZoneResult(
        last_price=last_price,
        as_of=as_of,
        support=support_zones[:num_zones],
        resistance=resistance_zones[:num_zones],
        broken_support=broken_support,
        broken_resistance=broken_resistance,
    )
