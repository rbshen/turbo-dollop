import pytest
from sqlmodel import Session, SQLModel, create_engine

import helpers.discount_rate_config as drc
from helpers.discount_rate_config import (
    DEFAULT_MARKET_RISK_PREMIUM_US,
    DEFAULT_RISK_FREE_RATE_US,
    SUPPORTED_REGIONS,
    US_REGION,
    get_discount_rate_config,
    list_discount_rate_configs,
    update_discount_rate_config,
)


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(autouse=True)
def _second_region(monkeypatch):
    # Only US is supported in production; the multi-region seeding mechanics
    # are still generic, so exercise them with a synthetic second region.
    monkeypatch.setattr(drc, "SUPPORTED_REGIONS", {"US", "XX"})


def test_us_seeds_from_the_hardcoded_defaults():
    engine = _fresh_engine()
    with Session(engine) as session:
        row = get_discount_rate_config(session)

    assert row.region == US_REGION
    assert row.risk_free_rate == DEFAULT_RISK_FREE_RATE_US
    assert row.market_risk_premium == DEFAULT_MARKET_RISK_PREMIUM_US


def test_a_new_region_seeds_from_the_current_us_row_not_the_hardcoded_defaults():
    # A newly-
    # introduced country's row defaults to whatever the CURRENT global
    # (US) rate is today -- including a value the user has already edited
    # away from the hardcoded DEFAULT_* constants -- never a fresh,
    # un-researched number.
    engine = _fresh_engine()
    with Session(engine) as session:
        update_discount_rate_config(session, risk_free_rate=0.05, market_risk_premium=0.04, region=US_REGION)

        xx_row = get_discount_rate_config(session, region="XX")

    assert xx_row.region == "XX"
    assert xx_row.risk_free_rate == 0.05
    assert xx_row.market_risk_premium == 0.04
    # Confirms it copied the edited US value, not the hardcoded constant.
    assert xx_row.risk_free_rate != DEFAULT_RISK_FREE_RATE_US


def test_a_new_region_seeds_from_us_defaults_when_us_itself_was_never_touched():
    # US doesn't need to be explicitly read/edited first -- get_discount_
    # rate_config recursively get-or-creates US itself when seeding a second region.
    engine = _fresh_engine()
    with Session(engine) as session:
        xx_row = get_discount_rate_config(session, region="XX")

    assert xx_row.risk_free_rate == DEFAULT_RISK_FREE_RATE_US
    assert xx_row.market_risk_premium == DEFAULT_MARKET_RISK_PREMIUM_US


def test_get_or_create_is_idempotent_a_second_read_returns_the_same_row_unchanged():
    engine = _fresh_engine()
    with Session(engine) as session:
        first = get_discount_rate_config(session, region="XX")
        second = get_discount_rate_config(session, region="XX")

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

        get_discount_rate_config(session, region="XX")
        regions_after_xx = sorted(row.region for row in list_discount_rate_configs(session))
        assert regions_after_xx == ["US", "XX"]


def test_updating_a_second_region_never_touches_the_us_row():
    engine = _fresh_engine()
    with Session(engine) as session:
        get_discount_rate_config(session, region=US_REGION)
        update_discount_rate_config(session, risk_free_rate=0.06, market_risk_premium=0.05, region="XX")

        us_row = get_discount_rate_config(session, region=US_REGION)

    assert us_row.risk_free_rate == DEFAULT_RISK_FREE_RATE_US
    assert us_row.market_risk_premium == DEFAULT_MARKET_RISK_PREMIUM_US


def test_an_unsupported_region_is_redirected_to_us_and_never_seeds_its_own_row():
    # A ticker from a country outside SUPPORTED_REGIONS (e.g. "CA") must
    # use the US rate directly, not silently accumulate its own row the
    # way every country used to before this cap (2026-09-17 cleanup).
    engine = _fresh_engine()
    with Session(engine) as session:
        update_discount_rate_config(session, risk_free_rate=0.05, market_risk_premium=0.04, region=US_REGION)

        ca_row = get_discount_rate_config(session, region="CA")

    assert ca_row.region == US_REGION
    assert ca_row.risk_free_rate == 0.05
    assert ca_row.market_risk_premium == 0.04
    assert sorted(row.region for row in list_discount_rate_configs(session)) == [US_REGION]


def test_supported_regions_is_exactly_us():
    assert SUPPORTED_REGIONS == {"US"}  # the import-time value, before the autouse patch
