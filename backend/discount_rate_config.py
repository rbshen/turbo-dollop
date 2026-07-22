from datetime import datetime

from sqlmodel import Session

from models import DiscountRateConfig

# Confirmed current values (see CLAUDE.md / step6_intrinsic_value_calculation_
# prompt.md §5) -- 5-year trailing averages from market-risk-premia.com,
# seeded here only as the row's initial value on first read. From then on
# the DB row (editable via /settings) is the source of truth, not these
# constants.
DEFAULT_RISK_FREE_RATE_US = 0.03608
DEFAULT_MARKET_RISK_PREMIUM_US = 0.02728

US_REGION = "US"


def get_discount_rate_config(session: Session, region: str = US_REGION) -> DiscountRateConfig:
    """Get-or-create -- this app has no migration tooling (db.init_db() is
    a plain SQLModel.metadata.create_all), so a first-boot default row is
    seeded lazily on first read rather than via a separate seed script."""
    row = session.get(DiscountRateConfig, region)
    if row is not None:
        return row

    row = DiscountRateConfig(
        region=region,
        risk_free_rate=DEFAULT_RISK_FREE_RATE_US,
        market_risk_premium=DEFAULT_MARKET_RISK_PREMIUM_US,
        updated_at=datetime.now(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_discount_rate_config(
    session: Session, risk_free_rate: float, market_risk_premium: float, region: str = US_REGION
) -> DiscountRateConfig:
    row = get_discount_rate_config(session, region)
    row.risk_free_rate = risk_free_rate
    row.market_risk_premium = market_risk_premium
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
