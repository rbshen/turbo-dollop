import asyncio
from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine

import data.step2_data as step2_data
from core.models import FundamentalsCache, GrowthCatalystNote
from data.step2_data import get_step2_data

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


def _patch_estimates(
    monkeypatch,
    rows: list[dict],
    sector: str = "Technology",
    industry: str = "Consumer Electronics",
    ratios_annual: list[dict] | None = None,
):
    """Patches every fmp_client call step2_data.py can make -- analyst
    estimates, profile (for company-type classification), and ratios (REIT
    DPU note only, never actually called unless sector/industry resolve to
    REIT) -- same all-in-one convention test_step4_data.py's own _patch_fmp
    uses, so no test accidentally leaves an fmp_client method unmocked and
    reaches a real network call. Defaults to a Standard-classifying
    sector/industry, matching every existing test's assumed company type."""

    async def fake_get_analyst_estimates(ticker):
        return rows

    async def fake_profile(ticker):
        return [{"sector": sector, "industry": industry}]

    async def fake_get_ratios(ticker, period, limit):
        return ratios_annual if ratios_annual is not None else []

    monkeypatch.setattr(step2_data.fmp_client, "get_analyst_estimates", fake_get_analyst_estimates)
    monkeypatch.setattr(step2_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step2_data.fmp_client, "get_ratios", fake_get_ratios)


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

    assert result.basis == "eps"
    assert result.base_fiscal_year == str(BASE_YEAR)
    # Offset 4 (BASE_YEAR + 4) is exactly 4 years out -- closest to the
    # window's 4yr center, beating offsets 3 and 5 which are both in-window
    # but farther from the center.
    assert result.target_fiscal_year == str(BASE_YEAR + 4)
    expected_cagr = ((1.6 / 1) ** (1 / 4) - 1) * 100
    assert result.growth_rate == pytest.approx(expected_cagr)
    expected_spread = (1.8 - 1.4) / 1.6 * 100
    assert result.estimate_spread == pytest.approx(expected_spread)


def test_target_year_skips_zero_value_row_for_a_usable_one_in_the_same_pool(monkeypatch):
    _fresh_engine(monkeypatch)
    # Offset 4 is exactly the window center but has revenueAvg=0 -- a real
    # FMP artifact for sparsely-covered far-out years. Offset 3 is also
    # in-window and has a real value, so it should be picked instead of
    # falling through to "insufficient data".
    rows = [
        _row(0, revenueAvg=100, revenueLow=90, revenueHigh=110),
        _row(1, revenueAvg=110, revenueLow=100, revenueHigh=120),
        _row(2, revenueAvg=120, revenueLow=110, revenueHigh=130),
        _row(3, revenueAvg=140, revenueLow=130, revenueHigh=150),
        _row(4, revenueAvg=0, revenueLow=0, revenueHigh=0),
    ]
    _patch_estimates(monkeypatch, rows)

    result = asyncio.run(get_step2_data("TEST"))

    assert result.basis == "revenue"
    assert result.target_fiscal_year == str(BASE_YEAR + 3)
    expected_cagr = ((140 / 100) ** (1 / 3) - 1) * 100
    assert result.growth_rate == pytest.approx(expected_cagr)


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


def test_falls_back_to_revenue_when_eps_estimates_are_missing(monkeypatch):
    _fresh_engine(monkeypatch)
    rows = [
        _row(0, epsAvg=None, epsLow=None, epsHigh=None, revenueAvg=100, revenueLow=90, revenueHigh=110),
        _row(1, epsAvg=None, epsLow=None, epsHigh=None, revenueAvg=110, revenueLow=100, revenueHigh=120),
        _row(4, epsAvg=None, epsLow=None, epsHigh=None, revenueAvg=160, revenueLow=140, revenueHigh=180),
    ]
    _patch_estimates(monkeypatch, rows)

    result = asyncio.run(get_step2_data("TEST"))

    assert result.basis == "revenue"
    expected_cagr = ((160 / 100) ** (1 / 4) - 1) * 100
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

    # A data gap, not a scored Fail -- score=None/verdict="insufficient_data"
    # (Step4Out/Step5Out's own convention), not a fabricated 0/100 number
    # that would silently drag down Overall Assessment's 22%-weighted blend.
    assert result.basis is None
    assert result.score is None
    assert result.verdict == "insufficient_data"
    assert result.components == {}


def test_insufficient_data_when_no_estimates_at_all(monkeypatch):
    # Mirrors ECHO/HONA's real cached shape: FMP responds successfully but
    # with zero analyst estimate rows -- not a fetch failure, just no
    # coverage. Must land on the same insufficient_data state as the
    # too-few-rows case above, not a scored Fail.
    _fresh_engine(monkeypatch)
    _patch_estimates(monkeypatch, [])

    result = asyncio.run(get_step2_data("TEST"))

    assert result.basis is None
    assert result.score is None
    assert result.verdict == "insufficient_data"
    assert result.growth_rate is None
    assert result.components == {}


def test_insufficient_data_when_fetch_fails(monkeypatch):
    # A genuine FMP fetch failure (cache.py::safe_fetch catches
    # httpx.HTTPError and returns {}) must collapse to the same
    # insufficient_data state as a genuinely-thin real response -- not a
    # scored Fail. The two are indistinguishable by the time _project sees
    # them (see CLAUDE.md's Step 2 deviations); this test confirms the
    # *outcome* is still correct even though the specific cause can't be
    # recovered downstream.
    _fresh_engine(monkeypatch)

    async def fake_get_analyst_estimates(ticker):
        raise httpx.ConnectError("boom")

    async def fake_profile(ticker):
        return [{"sector": "Technology", "industry": "Consumer Electronics"}]

    monkeypatch.setattr(step2_data.fmp_client, "get_analyst_estimates", fake_get_analyst_estimates)
    monkeypatch.setattr(step2_data.fmp_client, "get_profile", fake_profile)

    result = asyncio.run(get_step2_data("TEST"))

    assert result.basis is None
    assert result.score is None
    assert result.verdict == "insufficient_data"


def test_reit_skips_eps_and_uses_revenue_basis_even_when_eps_is_favorable(monkeypatch):
    # EPS growth here is deliberately much stronger than Revenue growth --
    # if REITs still fell back to EPS-preferred-then-revenue like every
    # other company type, this would score on the (higher) EPS figure. A
    # REIT must use Revenue regardless, since EPS is depreciation-heavy and
    # doesn't reflect REIT economics (see CLAUDE.md's REIT framework
    # investigation).
    _fresh_engine(monkeypatch)
    rows = [
        _row(0, revenueAvg=100, revenueLow=90, revenueHigh=110, epsAvg=1.0, epsLow=0.9, epsHigh=1.1),
        _row(4, revenueAvg=120, revenueLow=110, revenueHigh=130, epsAvg=3.0, epsLow=2.8, epsHigh=3.2),
    ]
    _patch_estimates(monkeypatch, rows, sector="Real Estate", industry="REIT - Retail")

    result = asyncio.run(get_step2_data("TEST"))

    assert result.basis == "revenue"
    expected_cagr = ((120 / 100) ** (1 / 4) - 1) * 100
    assert result.growth_rate == pytest.approx(expected_cagr)


def test_growth_basis_note_present_for_reit_and_absent_for_standard(monkeypatch):
    _fresh_engine(monkeypatch)
    rows = [
        _row(0, revenueAvg=100, revenueLow=90, revenueHigh=110, epsAvg=1.0, epsLow=0.9, epsHigh=1.1),
        _row(4, revenueAvg=160, revenueLow=140, revenueHigh=180, epsAvg=1.6, epsLow=1.4, epsHigh=1.8),
    ]

    # Different tickers -- same ticker would hit the cached "profile" row
    # from the first call instead of re-fetching under the second mock.
    _patch_estimates(monkeypatch, rows, sector="Real Estate", industry="REIT - Retail")
    reit_result = asyncio.run(get_step2_data("REIT_TEST"))
    assert reit_result.growth_basis_note is not None
    assert "revenue (rental income)" in reit_result.growth_basis_note

    _patch_estimates(monkeypatch, rows, sector="Technology", industry="Consumer Electronics")
    standard_result = asyncio.run(get_step2_data("STANDARD_TEST"))
    assert standard_result.growth_basis_note is None


def test_dpu_growth_note_populated_for_reit_with_dividend_history(monkeypatch):
    _fresh_engine(monkeypatch)
    rows = [
        _row(0, revenueAvg=100, revenueLow=90, revenueHigh=110),
        _row(4, revenueAvg=160, revenueLow=140, revenueHigh=180),
    ]
    # ratios rows are newest-first (matching FMP's real ordering); step2_data
    # reverses them to chronological before computing the note, same as
    # step3_data.py's own dpu_series construction.
    ratios_annual = [
        {"dividendPerShare": 3.20},
        {"dividendPerShare": 3.00},
        {"dividendPerShare": 2.50},
    ]
    _patch_estimates(monkeypatch, rows, sector="Real Estate", industry="REIT - Retail", ratios_annual=ratios_annual)

    result = asyncio.run(get_step2_data("TEST"))

    assert result.dpu_growth_note is not None
    assert "2.50" in result.dpu_growth_note
    assert "3.20" in result.dpu_growth_note


def test_dpu_growth_note_none_when_ratios_data_absent(monkeypatch):
    _fresh_engine(monkeypatch)
    rows = [
        _row(0, revenueAvg=100, revenueLow=90, revenueHigh=110),
        _row(4, revenueAvg=160, revenueLow=140, revenueHigh=180),
    ]
    _patch_estimates(monkeypatch, rows, sector="Real Estate", industry="REIT - Retail")

    result = asyncio.run(get_step2_data("TEST"))

    assert result.dpu_growth_note is None


def test_dpu_growth_note_and_basis_note_are_none_for_non_reit(monkeypatch):
    _fresh_engine(monkeypatch)
    rows = [
        _row(0, revenueAvg=100, revenueLow=90, revenueHigh=110, epsAvg=1.0, epsLow=0.9, epsHigh=1.1),
        _row(4, revenueAvg=160, revenueLow=140, revenueHigh=180, epsAvg=1.6, epsLow=1.4, epsHigh=1.8),
    ]
    _patch_estimates(monkeypatch, rows, sector="Technology", industry="Consumer Electronics")

    result = asyncio.run(get_step2_data("TEST"))

    assert result.growth_basis_note is None
    assert result.dpu_growth_note is None


# --- analyst_estimates earnings-aware staleness (2026-08-16 cron thundering- --
# --- herd follow-up) -----------------------------------------------------


def test_analyst_estimates_not_stale_when_no_new_earnings_since_fetch(monkeypatch):
    # analyst_estimates used to sit on the flat 7-day window (get_or_fetch)
    # for every ticker, REIT or not -- same flat-window synchronization
    # mechanism 4498c33 already fixed for income/balance/cash-flow/etc, just
    # missed for this one. A row 20 days stale but fetched AFTER the
    # ticker's last real earnings date must still read as a cache hit.
    test_engine = _fresh_engine(monkeypatch)
    rows = [
        _row(0, revenueAvg=100, revenueLow=90, revenueHigh=110, epsAvg=1.0, epsLow=0.9, epsHigh=1.1),
        _row(4, revenueAvg=160, revenueLow=140, revenueHigh=180, epsAvg=1.6, epsLow=1.4, epsHigh=1.8),
    ]

    fetched_at = datetime.now() - timedelta(days=20)
    last_earnings_date = date.today() - timedelta(days=60)  # well before fetched_at -- no new report since
    with Session(test_engine) as session:
        session.add(
            FundamentalsCache(
                ticker="TEST",
                statement_type="analyst_estimates",
                period="latest",
                fetched_at=fetched_at,
                raw_json='[{"stale": true}]',
            )
        )
        session.commit()

    async def fake_get_analyst_estimates(ticker):
        raise AssertionError("get_analyst_estimates must not be called -- row is fresh under earnings-aware staleness")

    async def fake_profile(ticker):
        return [{"sector": "Technology", "industry": "Consumer Electronics"}]

    async def fake_get_earnings(ticker):
        return [{"date": last_earnings_date.isoformat(), "epsActual": 1.5, "epsEstimated": 1.4}]

    monkeypatch.setattr(step2_data.fmp_client, "get_analyst_estimates", fake_get_analyst_estimates)
    monkeypatch.setattr(step2_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step2_data.fmp_client, "get_earnings", fake_get_earnings)

    result = asyncio.run(get_step2_data("TEST"))

    # Falls back to insufficient_data since the stale fixture row isn't a
    # real estimates shape -- the point of this test is that get_analyst_
    # estimates was never called at all (the AssertionError above), not
    # what the resulting score looks like.
    assert result.verdict == "insufficient_data"


def test_analyst_estimates_refetches_once_new_earnings_have_actually_passed(monkeypatch):
    # Companion case: a real new earnings date HAS passed since the row was
    # fetched -- must genuinely refetch, not just always skip.
    test_engine = _fresh_engine(monkeypatch)
    rows = [
        _row(0, revenueAvg=100, revenueLow=90, revenueHigh=110, epsAvg=1.0, epsLow=0.9, epsHigh=1.1),
        _row(4, revenueAvg=160, revenueLow=140, revenueHigh=180, epsAvg=1.6, epsLow=1.4, epsHigh=1.8),
    ]

    fetched_at = datetime.now() - timedelta(days=20)
    new_earnings_date = date.today() - timedelta(days=5)  # reported AFTER the row was fetched
    with Session(test_engine) as session:
        session.add(
            FundamentalsCache(
                ticker="TEST",
                statement_type="analyst_estimates",
                period="latest",
                fetched_at=fetched_at,
                raw_json='[{"stale": true}]',
            )
        )
        session.commit()

    call_count = {"n": 0}

    async def fake_get_analyst_estimates(ticker):
        call_count["n"] += 1
        return rows

    async def fake_profile(ticker):
        return [{"sector": "Technology", "industry": "Consumer Electronics"}]

    async def fake_get_earnings(ticker):
        return [{"date": new_earnings_date.isoformat(), "epsActual": 1.5, "epsEstimated": 1.4}]

    monkeypatch.setattr(step2_data.fmp_client, "get_analyst_estimates", fake_get_analyst_estimates)
    monkeypatch.setattr(step2_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step2_data.fmp_client, "get_earnings", fake_get_earnings)

    result = asyncio.run(get_step2_data("TEST"))

    assert call_count["n"] == 1
    assert result.basis == "eps"  # confirms the freshly-fetched rows were actually used
