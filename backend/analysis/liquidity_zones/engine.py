"""Pure Liquidity Zone (LP) detection engine -- swing detection + any-bar
breach tracking + price clustering, entirely timeframe-agnostic (called
once per timeframe by data/liquidity_zone_data.py with one shared
LiquidityZoneSettings).

Rules follow the reference "Left Precedence" Pine script:

Breach: a swing low becomes a support LP once confirmed and stays valid
until ANY later bar's Low trades below it (not just a later swing); once
breached it stays breached. Symmetric for swing highs / resistance. See
swings.py::annotate_swings.

Clustering: consecutive valid zones within cluster_pct% collapse into one.
Support clusters take their LOWEST member as the representative,
resistance clusters their HIGHEST (see clustering.py).

Cap: after clustering, at most `max_lps_per_side` valid zones are kept per
side -- the nearest to the last close (`nearest_price`) or the most
recently formed (`most_recent`). The wrong-side-of-price filter is now
only a guard: with any-bar breach a valid support can never sit above the
last close (or a valid resistance below it).

Kept breached level (one per side, optional): threshold = the best RAW
valid swing price on that side (before clustering and the cap, as in the
reference script's findKeptBreached) -- highest support / lowest
resistance. Candidates are breached swings on the far
side of it (support: price > threshold; resistance: price < threshold; all
qualify with no threshold), optionally restricted to breaches within
`breach_recency_bars` of the last bar; the one closest to the threshold
(lowest support / highest resistance) wins. No clustering across breached
candidates."""

from datetime import date

import pandas as pd

from .clustering import cluster_prices
from .swings import SwingEvent, annotate_swings, find_swing_highs, find_swing_lows, valid_prices_at
from .types import BrokenZone, LiquidityZoneResult, LiquidityZoneSettings, Zone


def _bar_date(index: pd.Index, pos: int) -> date:
    value = index[pos]
    return value.date() if hasattr(value, "date") else value


def _select_broken_zone(
    events: list[SwingEvent],
    last_pos: int,
    settings: LiquidityZoneSettings,
    threshold: float | None,
    kind: str,
    index: pd.Index,
) -> BrokenZone | None:
    """See this module's docstring, "Kept breached level". kind="low"
    (support): candidates must sit ABOVE `threshold` (highest valid
    support), the lowest wins. kind="high" (resistance): candidates must
    sit BELOW `threshold` (lowest valid resistance), the highest wins."""
    candidates = [e for e in events if e.breach_pos is not None]
    if kind == "low":
        candidates = [e for e in candidates if threshold is None or e.price > threshold]
    else:
        candidates = [e for e in candidates if threshold is None or e.price < threshold]
    if settings.only_keep_if_breached_recently:
        candidates = [e for e in candidates if last_pos - e.breach_pos <= settings.breach_recency_bars]
    if not candidates:
        return None
    # Ties on price (same level swung twice): prefer the later breach, then later formation.
    if kind == "low":
        best = min(candidates, key=lambda e: (e.price, -e.breach_pos, -e.pos))
    else:
        best = max(candidates, key=lambda e: (e.price, e.breach_pos, e.pos))
    return BrokenZone(price=best.price, formed_at=best.date, breached_at=_bar_date(index, best.breach_pos))


def _cap_zones(zones: list[Zone], last_price: float, settings: LiquidityZoneSettings) -> list[Zone]:
    """Keeps at most max_lps_per_side zones per `over_cap_priority`; the
    result is returned in the caller's original (nearest-first) order."""
    if len(zones) <= settings.max_lps_per_side:
        return zones
    if settings.over_cap_priority == "most_recent":
        keep = sorted(zones, key=lambda z: z.formed_at, reverse=True)[: settings.max_lps_per_side]
    else:
        keep = sorted(zones, key=lambda z: abs(z.price - last_price))[: settings.max_lps_per_side]
    keep_ids = {id(z) for z in keep}
    return [z for z in zones if id(z) in keep_ids]


def compute_liquidity_zones(df: pd.DataFrame, settings: LiquidityZoneSettings) -> LiquidityZoneResult:
    """df needs lowercase open/high/low/close/volume columns and a
    DatetimeIndex, ascending by date (matching every other engine in this
    codebase). Returns up to `max_lps_per_side` clustered support zones
    (below the last close) and resistance zones (above it), nearest
    first, plus at most one kept-breached zone per side (see this module's
    docstring)."""
    if df.empty:
        raise ValueError("compute_liquidity_zones requires a non-empty OHLC frame")

    last_pos = len(df) - 1
    last_price = float(df["close"].iloc[-1])
    as_of = _bar_date(df.index, last_pos)

    is_swing_low = find_swing_lows(df["low"], settings.swing_bars_each_side)
    is_swing_high = find_swing_highs(df["high"], settings.swing_bars_each_side)

    low_events = annotate_swings(df["low"], is_swing_low, kind="low")
    high_events = annotate_swings(df["high"], is_swing_high, kind="high")

    valid_lows = valid_prices_at(low_events, last_pos)
    valid_highs = valid_prices_at(high_events, last_pos)

    # Support: highest price first (adjacency for clustering), representative = lowest member.
    support_items = sorted(((e.price, e.date) for e in valid_lows), key=lambda item: item[0], reverse=True)
    all_support_zones = cluster_prices(support_items, settings.cluster_pct, representative="min")
    support_zones = [z for z in all_support_zones if z.price <= last_price]
    support_zones.sort(key=lambda z: z.price, reverse=True)  # nearest (highest) first

    # Resistance: lowest price first (adjacency for clustering), representative = highest member.
    resistance_items = sorted(((e.price, e.date) for e in valid_highs), key=lambda item: item[0])
    all_resistance_zones = cluster_prices(resistance_items, settings.cluster_pct, representative="max")
    resistance_zones = [z for z in all_resistance_zones if z.price >= last_price]
    resistance_zones.sort(key=lambda z: z.price)  # nearest (lowest) first

    # Raw (unclustered) valid swings: a cluster's representative is its
    # LOWEST support member, which would understate the true highest valid support.
    highest_valid_support = max((e.price for e in valid_lows), default=None)
    lowest_valid_resistance = min((e.price for e in valid_highs), default=None)

    broken_support = (
        _select_broken_zone(low_events, last_pos, settings, highest_valid_support, "low", df.index)
        if settings.keep_last_breached_support
        else None
    )
    broken_resistance = (
        _select_broken_zone(high_events, last_pos, settings, lowest_valid_resistance, "high", df.index)
        if settings.keep_last_breached_resistance
        else None
    )

    return LiquidityZoneResult(
        last_price=last_price,
        as_of=as_of,
        support=_cap_zones(support_zones, last_price, settings),
        resistance=_cap_zones(resistance_zones, last_price, settings),
        broken_support=broken_support,
        broken_resistance=broken_resistance,
    )
