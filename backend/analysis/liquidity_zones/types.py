"""Shared dataclasses for the Liquidity Zone (LP) detection engine -- see
engine.py. Mirrors analysis/trend_structure's dataclass-based style. See
CLAUDE.md's "Liquidity Zone (LP) detection (Technical)" section for the
full methodology.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class SwingEvent:
    """A single fractal swing low (support candidate) or swing high
    (resistance candidate), annotated with whether/when a LATER swing of
    the SAME kind breached it. breach_pos is None if never breached as of
    the end of the series that was passed in -- see swings.py::
    annotate_swings for the exact breach rule."""

    pos: int
    date: date
    price: float
    breach_pos: int | None


@dataclass(frozen=True)
class Zone:
    """One clustered, currently-valid liquidity zone. `price` is the
    cluster's representative -- the lowest member for support, the
    highest for resistance (see clustering.py's own docstring for why the
    two sides use different extremes). `formed_at` is the date of that
    specific representative swing, not the cluster's earliest or most
    recent member -- the representative price is the one level a trader
    actually references, so its own date answers "since when has price
    respected this exact level," the decision-relevant framing here."""

    price: float
    cluster_size: int
    formed_at: date


@dataclass(frozen=True)
class BrokenZone:
    """The single most recently breached support or resistance level that
    still qualifies for display -- see engine.py's own module docstring
    for the two hard filters (recency window + positional constraint)
    this must clear. `formed_at` is the original swing's own date (same
    meaning as Zone.formed_at) -- the recency window is measured FROM
    THIS date, not from `breached_at`. `breached_at` is the date of the
    LATER, confirming swing that broke it, kept only for display/"most
    recent" tie-breaking. Never clustered with other breached candidates,
    unlike Zone -- at most one BrokenZone exists per side per timeframe."""

    price: float
    formed_at: date
    breached_at: date


@dataclass(frozen=True)
class LiquidityZoneResult:
    """One timeframe's (Daily or Weekly) complete LP read. support/
    resistance are already filtered to the side of last_price that's
    actually meaningful and capped at the caller's num_zones, nearest
    first -- see engine.py's own module docstring for why. broken_support/
    broken_resistance are None whenever no breach currently qualifies for
    display (see BrokenZone's own docstring)."""

    last_price: float
    as_of: date
    support: list[Zone]
    resistance: list[Zone]
    broken_support: BrokenZone | None = None
    broken_resistance: BrokenZone | None = None


OverCapPriority = Literal["nearest_price", "most_recent"]


@dataclass(frozen=True)
class LiquidityZoneSettings:
    """Detection settings shared by the Daily and Weekly computations --
    the "Detection" and "Last breached LP" input groups of the reference
    Pine script (cosmetic inputs deliberately not ported).
    `breach_recency_bars` is in each timeframe's own native bars."""

    swing_bars_each_side: int = 2
    cluster_pct: float = 2.0  # 0 disables clustering
    max_lps_per_side: int = 10
    over_cap_priority: OverCapPriority = "nearest_price"
    keep_last_breached_support: bool = True
    keep_last_breached_resistance: bool = True
    only_keep_if_breached_recently: bool = True
    breach_recency_bars: int = 5
