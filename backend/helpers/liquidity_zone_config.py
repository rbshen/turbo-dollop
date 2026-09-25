from datetime import datetime

from sqlmodel import Session

from analysis.liquidity_zones.types import LiquidityZoneSettings as EngineSettings
from core.models import LiquidityZoneSettings

# Defaults match the reference Pine script's own input defaults.
DEFAULT_SWING_BARS = 2
DEFAULT_CLUSTER_PCT = 2.0
DEFAULT_MAX_LPS_PER_SIDE = 10
DEFAULT_OVER_CAP_PRIORITY = "nearest_price"
DEFAULT_BREACH_RECENCY_BARS = 5

OVER_CAP_PRIORITIES = ("nearest_price", "most_recent")

_CONFIG_KEY = "default"


def get_liquidity_zone_settings(session: Session) -> LiquidityZoneSettings:
    """Get-or-create -- this app has no migration tooling (see
    DiscountRateConfig's own comment), so a first-boot default row is
    seeded lazily on first read rather than via a separate seed script."""
    row = session.get(LiquidityZoneSettings, _CONFIG_KEY)
    if row is None:
        row = LiquidityZoneSettings(
            key=_CONFIG_KEY,
            swing_bars_each_side=DEFAULT_SWING_BARS,
            cluster_pct=DEFAULT_CLUSTER_PCT,
            max_lps_per_side=DEFAULT_MAX_LPS_PER_SIDE,
            over_cap_priority=DEFAULT_OVER_CAP_PRIORITY,
            keep_last_breached_support=True,
            keep_last_breached_resistance=True,
            only_keep_if_breached_recently=True,
            breach_recency_bars=DEFAULT_BREACH_RECENCY_BARS,
            updated_at=datetime.now(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def update_liquidity_zone_settings(
    session: Session,
    swing_bars_each_side: int,
    cluster_pct: float,
    max_lps_per_side: int,
    over_cap_priority: str,
    keep_last_breached_support: bool,
    keep_last_breached_resistance: bool,
    only_keep_if_breached_recently: bool,
    breach_recency_bars: int,
) -> LiquidityZoneSettings:
    row = get_liquidity_zone_settings(session)
    row.swing_bars_each_side = swing_bars_each_side
    row.cluster_pct = cluster_pct
    row.max_lps_per_side = max_lps_per_side
    row.over_cap_priority = over_cap_priority
    row.keep_last_breached_support = keep_last_breached_support
    row.keep_last_breached_resistance = keep_last_breached_resistance
    row.only_keep_if_breached_recently = only_keep_if_breached_recently
    row.breach_recency_bars = breach_recency_bars
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def to_engine_settings(row: LiquidityZoneSettings) -> EngineSettings:
    """Row -> the pure engine's frozen dataclass (the engine never sees a
    SQLModel table)."""
    return EngineSettings(
        swing_bars_each_side=row.swing_bars_each_side,
        cluster_pct=row.cluster_pct,
        max_lps_per_side=row.max_lps_per_side,
        over_cap_priority=row.over_cap_priority,  # type: ignore[arg-type]
        keep_last_breached_support=row.keep_last_breached_support,
        keep_last_breached_resistance=row.keep_last_breached_resistance,
        only_keep_if_breached_recently=row.only_keep_if_breached_recently,
        breach_recency_bars=row.breach_recency_bars,
    )
