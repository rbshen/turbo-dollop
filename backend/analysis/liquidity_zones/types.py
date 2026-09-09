"""Shared dataclasses for the Liquidity Zone (LP) detection engine -- see
engine.py. Mirrors analysis/trend_structure's dataclass-based style. See
CLAUDE.md's "Liquidity Zone (LP) detection (Technical)" section for the
full methodology.
"""

from dataclasses import dataclass
from datetime import date


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
class LiquidityZoneResult:
    """One timeframe's (Daily or Weekly) complete LP read. support/
    resistance are already filtered to the side of last_price that's
    actually meaningful and capped at the caller's num_zones, nearest
    first -- see engine.py's own module docstring for why."""

    last_price: float
    as_of: date
    support: list[Zone]
    resistance: list[Zone]
