import asyncio
from datetime import date, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine

import step2_data
from models import GrowthCatalystNote
from step2_data import get_step2_data

TODAY = date.today()
BASE_YEAR = TODAY.year + 1  # nearest future fiscal year


def _row(years_from_base: int, **fields) -> dict:
    year = BASE_YEAR + years_from_base
    return {"date": f"{year}-06-30", **fields}


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step2_data, "engine", test_engine)
    return test_engine


def _patch_estimates(monkeypatch, rows: list[dict]):
    async def fake_get_analyst_estimates(ticker):
        return rows

    monkeypatch.setattr(step2_data.fmp_client, "get_analyst_estimates", fake_get_analyst_estimates)


def test_target_year_picks_row_closest_to_four_years_out_within_window(monkeypatch):
    _fresh_engine(monkeypatch)
    rows = [
        _row(0, revenueAvg=100, revenueLow=90, revenueHigh=110, epsAvg=1, epsLow=0.9, epsHigh=1.1),
        _row(1, revenueAvg=110, revenueLow=100, revenueHigh=120, epsAvg=1.1, epsLow=1.0, epsHigh=1.2),
        _row(2, revenueAvg=120, revenueLow=110, revenueHigh=130, epsAvg=1.2, epsLow=1.1, epsHigh=1.3),
        _row(3, revenueAvg=140, revenueLow=130, revenueHigh=150, epsAvg=1.4, epsLow=1.3, epsHigh=1.5),
        _row(4, revenueAvg=160, revenueLow=140, revenueHigh=180, epsAvg=1.6, epsLow=1.4, epsHigh=1.8),
        _row(5, revenueAvg=180, revenueLow=160, revenueHigh=200, epsAvg=1.8, epsLow=1.6, epsHigh=2.0),
    ]
    _patch_estimates(monkeypatch, rows)

    result = asyncio.run(get_step2_data("TEST"))

    assert result.basis == "revenue"
    assert result.base_fiscal_year == str(BASE_YEAR)
    # Offset 4 (BASE_YEAR + 4) is exactly 4 years out -- closest to the
    # window's 4yr center, beating offsets 3 and 5 which are both in-window
    # but farther from the center.
    assert result.target_fiscal_year == str(BASE_YEAR + 4)
    expected_cagr = ((160 / 100) ** (1 / 4) - 1) * 100
    assert result.growth_rate == pytest.approx(expected_cagr)
    expected_spread = (180 - 140) / 160 * 100
    assert result.estimate_spread == pytest.approx(expected_spread)


def test_target_falls_back_to_furthest_row_when_none_in_window(monkeypatch):
    _fresh_engine(monkeypatch)
    # Only offsets 0, 1, 2 available -- none reach the 3-5yr window, so the
    # target should fall back to whatever's furthest out (offset 2).
    rows = [
        _row(0, revenueAvg=100, revenueLow=90, revenueHigh=110),
        _row(1, revenueAvg=110, revenueLow=100, revenueHigh=120),
        _row(2, revenueAvg=120, revenueLow=110, revenueHigh=130),
    ]
    _patch_estimates(monkeypatch, rows)

    result = asyncio.run(get_step2_data("TEST"))

    assert result.target_fiscal_year == str(BASE_YEAR + 2)


def test_past_dated_rows_are_excluded_from_base_selection(monkeypatch):
    _fresh_engine(monkeypatch)
    rows = [
        # Dated in the past -- must not become the base row, even though
        # it's the "nearest" by raw date order in the unsorted list.
        {"date": f"{TODAY.year - 1}-01-01", "revenueAvg": 999, "revenueLow": 999, "revenueHigh": 999},
        _row(0, revenueAvg=100, revenueLow=90, revenueHigh=110),
        _row(1, revenueAvg=110, revenueLow=100, revenueHigh=120),
        _row(4, revenueAvg=160, revenueLow=140, revenueHigh=180),
    ]
    _patch_estimates(monkeypatch, rows)

    result = asyncio.run(get_step2_data("TEST"))

    assert result.base_fiscal_year == str(BASE_YEAR)


def test_falls_back_to_eps_when_revenue_estimates_are_missing(monkeypatch):
    _fresh_engine(monkeypatch)
    rows = [
        _row(0, revenueAvg=None, revenueLow=None, revenueHigh=None, epsAvg=1.0, epsLow=0.9, epsHigh=1.1),
        _row(1, revenueAvg=None, revenueLow=None, revenueHigh=None, epsAvg=1.1, epsLow=1.0, epsHigh=1.2),
        _row(4, revenueAvg=None, revenueLow=None, revenueHigh=None, epsAvg=1.6, epsLow=1.4, epsHigh=1.8),
    ]
    _patch_estimates(monkeypatch, rows)

    result = asyncio.run(get_step2_data("TEST"))

    assert result.basis == "eps"
    expected_cagr = ((1.6 / 1.0) ** (1 / 4) - 1) * 100
    assert result.growth_rate == pytest.approx(expected_cagr)


def test_growth_catalysts_returned_when_present_and_null_when_absent(monkeypatch):
    test_engine = _fresh_engine(monkeypatch)
    rows = [
        _row(0, revenueAvg=100, revenueLow=90, revenueHigh=110),
        _row(4, revenueAvg=160, revenueLow=140, revenueHigh=180),
    ]
    _patch_estimates(monkeypatch, rows)

    result = asyncio.run(get_step2_data("TEST"))
    assert result.growth_catalysts is None

    with Session(test_engine) as session:
        session.add(GrowthCatalystNote(ticker="TEST", notes="Expanding into new markets.", updated_at=datetime.now()))
        session.commit()

    result = asyncio.run(get_step2_data("TEST"))
    assert result.growth_catalysts == "Expanding into new markets."


def test_insufficient_data_when_fewer_than_two_future_rows(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_estimates(monkeypatch, [_row(0, revenueAvg=100, revenueLow=90, revenueHigh=110)])

    result = asyncio.run(get_step2_data("TEST"))

    assert result.basis is None
    assert result.components["insufficient_data"] is True
    assert 0 <= result.score <= 100
