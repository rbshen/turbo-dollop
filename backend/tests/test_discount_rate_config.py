from sqlmodel import Session, SQLModel, create_engine

from helpers.discount_rate_config import (
    DEFAULT_MARKET_RISK_PREMIUM_US,
    DEFAULT_RISK_FREE_RATE_US,
    US_REGION,
    get_discount_rate_config,
    list_discount_rate_configs,
    update_discount_rate_config,
)


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_us_seeds_from_the_hardcoded_defaults():
    engine = _fresh_engine()
    with Session(engine) as session:
        row = get_discount_rate_config(session)

    assert row.region == US_REGION
    assert row.risk_free_rate == DEFAULT_RISK_FREE_RATE_US
    assert row.market_risk_premium == DEFAULT_MARKET_RISK_PREMIUM_US


def test_a_new_region_seeds_from_the_current_us_row_not_the_hardcoded_defaults():
    # The HK market support round's explicit seeding rule: a newly-
    # introduced country's row defaults to whatever the CURRENT global
    # (US) rate is today -- including a value the user has already edited
    # away from the hardcoded DEFAULT_* constants -- never a fresh,
    # un-researched HK-specific number.
    engine = _fresh_engine()
    with Session(engine) as session:
        update_discount_rate_config(session, risk_free_rate=0.05, market_risk_premium=0.04, region=US_REGION)

        hk_row = get_discount_rate_config(session, region="HK")

    assert hk_row.region == "HK"
    assert hk_row.risk_free_rate == 0.05
    assert hk_row.market_risk_premium == 0.04
    # Confirms it copied the edited US value, not the hardcoded constant.
    assert hk_row.risk_free_rate != DEFAULT_RISK_FREE_RATE_US


def test_a_new_region_seeds_from_us_defaults_when_us_itself_was_never_touched():
    # US doesn't need to be explicitly read/edited first -- get_discount_
    # rate_config recursively get-or-creates US itself when seeding HK.
    engine = _fresh_engine()
    with Session(engine) as session:
        hk_row = get_discount_rate_config(session, region="HK")

    assert hk_row.risk_free_rate == DEFAULT_RISK_FREE_RATE_US
    assert hk_row.market_risk_premium == DEFAULT_MARKET_RISK_PREMIUM_US


def test_get_or_create_is_idempotent_a_second_read_returns_the_same_row_unchanged():
    engine = _fresh_engine()
    with Session(engine) as session:
        first = get_discount_rate_config(session, region="HK")
        second = get_discount_rate_config(session, region="HK")

    assert first.updated_at == second.updated_at
    assert first.risk_free_rate == second.risk_free_rate


def test_list_returns_only_regions_actually_seeded_so_far():
    engine = _fresh_engine()
    with Session(engine) as session:
        # No region read/created yet -- list must not fabricate one.
        assert list_discount_rate_configs(session) == []

        get_discount_rate_config(session, region=US_REGION)
        regions_after_us = [row.region for row in list_discount_rate_configs(session)]
        assert regions_after_us == ["US"]

        get_discount_rate_config(session, region="HK")
        regions_after_hk = sorted(row.region for row in list_discount_rate_configs(session))
        assert regions_after_hk == ["HK", "US"]


def test_updating_hk_never_touches_the_us_row():
    engine = _fresh_engine()
    with Session(engine) as session:
        get_discount_rate_config(session, region=US_REGION)
        update_discount_rate_config(session, risk_free_rate=0.06, market_risk_premium=0.05, region="HK")

        us_row = get_discount_rate_config(session, region=US_REGION)

    assert us_row.risk_free_rate == DEFAULT_RISK_FREE_RATE_US
    assert us_row.market_risk_premium == DEFAULT_MARKET_RISK_PREMIUM_US
