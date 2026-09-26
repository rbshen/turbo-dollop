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

# The only regions this app maintains a distinct discount rate for --
# deliberately capped, not auto-expanding to every FMP profile `country`
# value seen (an ADR's domicile, e.g. CN/CA/TW, must not seed its own
# un-researched row). Any ticker whose country isn't in this set is treated
# as US_REGION at the get_discount_rate_config call site below -- it uses
# the US row's live rate directly and never seeds its own region row. HK/FR
# were removed with non-US ticker support; add a region here to reintroduce
# a per-country rate.
SUPPORTED_REGIONS = {"US"}


def get_discount_rate_config(session: Session, region: str = US_REGION) -> DiscountRateConfig:
    """Get-or-create -- this app has no migration tooling (db.init_db() is
    a plain SQLModel.metadata.create_all), so a first-boot default row is
    seeded lazily on first read rather than via a separate seed script.

    A region outside SUPPORTED_REGIONS is redirected to US_REGION before
    the get-or-create below ever runs, so it's never seeded its own row --
    it simply uses the US row's live rate. US_REGION itself seeds from the
    hardcoded DEFAULT_* constants above, unchanged from before per-country
    support existed. Any OTHER supported region (none today) seeds instead from
    the CURRENT live US row's own values, recursively get-or-creating US
    first, including a value the user has already edited away from
    DEFAULT_RISK_FREE_RATE_US/DEFAULT_MARKET_RISK_PREMIUM_US."""
    if region not in SUPPORTED_REGIONS:
        region = US_REGION

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
