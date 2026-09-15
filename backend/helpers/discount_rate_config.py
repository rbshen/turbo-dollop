from datetime import datetime

from sqlmodel import Session, select

from core.models import DiscountRateConfig

# Confirmed current values (see CLAUDE.md / step6_intrinsic_value_calculation_
# prompt.md §5) -- 5-year trailing averages from market-risk-premia.com,
# seeded here only as the US row's initial value on first read. From then on
# the DB row (editable via /settings) is the source of truth, not these
# constants.
DEFAULT_RISK_FREE_RATE_US = 0.03608
DEFAULT_MARKET_RISK_PREMIUM_US = 0.02728

US_REGION = "US"


def get_discount_rate_config(session: Session, region: str = US_REGION) -> DiscountRateConfig:
    """Get-or-create -- this app has no migration tooling (db.init_db() is
    a plain SQLModel.metadata.create_all), so a first-boot default row is
    seeded lazily on first read rather than via a separate seed script.

    US_REGION seeds from the hardcoded DEFAULT_* constants above, unchanged
    from before per-country support existed. Any OTHER region (e.g. "HK",
    seeded the first time a Hong Kong-listed ticker's Step 3 valuation runs
    -- see step3_data.py) seeds instead from the CURRENT live US row's own
    values, recursively get-or-creating US first -- per the HK market
    support round's explicit seeding rule: "defaults to whatever the
    CURRENT single global rate is today," including a value the user has
    already edited away from DEFAULT_RISK_FREE_RATE_US/DEFAULT_MARKET_
    RISK_PREMIUM_US, not a fresh, un-researched HK-specific number."""
    row = session.get(DiscountRateConfig, region)
    if row is not None:
        return row

    if region == US_REGION:
        risk_free_rate = DEFAULT_RISK_FREE_RATE_US
        market_risk_premium = DEFAULT_MARKET_RISK_PREMIUM_US
    else:
        us_row = get_discount_rate_config(session, US_REGION)
        risk_free_rate = us_row.risk_free_rate
        market_risk_premium = us_row.market_risk_premium

    row = DiscountRateConfig(
        region=region,
        risk_free_rate=risk_free_rate,
        market_risk_premium=market_risk_premium,
        updated_at=datetime.now(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_discount_rate_configs(session: Session) -> list[DiscountRateConfig]:
    """Every region seeded so far -- lazy, same as every config in this app
    (a region's row only exists once get_discount_rate_config has been
    called for it at least once, i.e. once a ticker from that
    country/region has had its Step 3 valuation computed). US always
    exists by the time /settings is first opened in practice, since the
    US row is get-or-created eagerly by the /api/config/discount-rate
    endpoint below -- but this function itself never fabricates a region
    that hasn't been seeded."""
    return list(session.exec(select(DiscountRateConfig).order_by(DiscountRateConfig.region)))


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
