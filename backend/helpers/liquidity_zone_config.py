from datetime import datetime

from sqlmodel import Session

from core.models import LiquidityZoneConfig

# swing_bars=2 (5-bar window) and cluster_pct=2.0 match the reference
# lp_detector_polygon_clustered.py's own defaults; num_zones=3 matches
# this app's existing 3-item bar-indicator convention (see
# frontend/components/watchlist/SignalBars.tsx's default maxBars).
DEFAULT_SWING_BARS = 2
DEFAULT_CLUSTER_PCT = 2.0
DEFAULT_NUM_ZONES = 3
# Default recency window (in bars native to each timeframe) for the
# most-recently-breached-zone tracking feature -- see
# analysis/liquidity_zones/engine.py's own module docstring.
DEFAULT_BREACH_RECENCY_BARS = 6

_CONFIG_KEY = "default"


def get_liquidity_zone_config(session: Session) -> LiquidityZoneConfig:
    """Get-or-create -- this app has no migration tooling (see
    DiscountRateConfig's own comment), so a first-boot default row is
    seeded lazily on first read rather than via a separate seed script.
    Also coalesces a NULL daily_breach_recency_bars/weekly_breach_recency_bars
    (an existing row from before this feature shipped, only ever added via
    _add_missing_columns with no backfill) back to
    DEFAULT_BREACH_RECENCY_BARS, so a stale row never silently passes None
    into the engine."""
    row = session.get(LiquidityZoneConfig, _CONFIG_KEY)
    if row is None:
        row = LiquidityZoneConfig(
            key=_CONFIG_KEY,
            daily_swing_bars=DEFAULT_SWING_BARS,
            daily_cluster_pct=DEFAULT_CLUSTER_PCT,
            daily_num_zones=DEFAULT_NUM_ZONES,
            weekly_swing_bars=DEFAULT_SWING_BARS,
            weekly_cluster_pct=DEFAULT_CLUSTER_PCT,
            weekly_num_zones=DEFAULT_NUM_ZONES,
            daily_breach_recency_bars=DEFAULT_BREACH_RECENCY_BARS,
            weekly_breach_recency_bars=DEFAULT_BREACH_RECENCY_BARS,
            updated_at=datetime.now(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    if row.daily_breach_recency_bars is None or row.weekly_breach_recency_bars is None:
        row.daily_breach_recency_bars = row.daily_breach_recency_bars or DEFAULT_BREACH_RECENCY_BARS
        row.weekly_breach_recency_bars = row.weekly_breach_recency_bars or DEFAULT_BREACH_RECENCY_BARS
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def update_liquidity_zone_config(
    session: Session,
    daily_swing_bars: int,
    daily_cluster_pct: float,
    daily_num_zones: int,
    weekly_swing_bars: int,
    weekly_cluster_pct: float,
    weekly_num_zones: int,
    daily_breach_recency_bars: int,
    weekly_breach_recency_bars: int,
) -> LiquidityZoneConfig:
    row = get_liquidity_zone_config(session)
    row.daily_swing_bars = daily_swing_bars
    row.daily_cluster_pct = daily_cluster_pct
    row.daily_num_zones = daily_num_zones
    row.weekly_swing_bars = weekly_swing_bars
    row.weekly_cluster_pct = weekly_cluster_pct
    row.weekly_num_zones = weekly_num_zones
    row.daily_breach_recency_bars = daily_breach_recency_bars
    row.weekly_breach_recency_bars = weekly_breach_recency_bars
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
