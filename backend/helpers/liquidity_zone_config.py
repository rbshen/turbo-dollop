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

_CONFIG_KEY = "default"


def get_liquidity_zone_config(session: Session) -> LiquidityZoneConfig:
    """Get-or-create -- this app has no migration tooling (see
    DiscountRateConfig's own comment), so a first-boot default row is
    seeded lazily on first read rather than via a separate seed script."""
    row = session.get(LiquidityZoneConfig, _CONFIG_KEY)
    if row is not None:
        return row

    row = LiquidityZoneConfig(
        key=_CONFIG_KEY,
        daily_swing_bars=DEFAULT_SWING_BARS,
        daily_cluster_pct=DEFAULT_CLUSTER_PCT,
        daily_num_zones=DEFAULT_NUM_ZONES,
        weekly_swing_bars=DEFAULT_SWING_BARS,
        weekly_cluster_pct=DEFAULT_CLUSTER_PCT,
        weekly_num_zones=DEFAULT_NUM_ZONES,
        updated_at=datetime.now(),
    )
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
) -> LiquidityZoneConfig:
    row = get_liquidity_zone_config(session)
    row.daily_swing_bars = daily_swing_bars
    row.daily_cluster_pct = daily_cluster_pct
    row.daily_num_zones = daily_num_zones
    row.weekly_swing_bars = weekly_swing_bars
    row.weekly_cluster_pct = weekly_cluster_pct
    row.weekly_num_zones = weekly_num_zones
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
