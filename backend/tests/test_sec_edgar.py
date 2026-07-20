import asyncio
import json
from datetime import date
from pathlib import Path

import httpx
from sqlmodel import Session, SQLModel, create_engine

import sec_edgar
from sec_edgar import (
    cross_check_cfo,
    cross_check_interest_expense,
    find_discrete_cfo_value,
    find_discrete_income_statement_value,
    get_cik,
)

FIXTURES = Path(__file__).parent / "fixtures"
PEP_FACTS = json.loads((FIXTURES / "pep_company_facts_sample.json").read_text())
OXM_FACTS = json.loads((FIXTURES / "oxm_company_facts_sample.json").read_text())

TICKER_CIK_MAP = {
    "0": {"cik_str": 77476, "ticker": "PEP", "title": "PEPSICO INC"},
    "1": {"cik_str": 75288, "ticker": "OXM", "title": "OXFORD INDUSTRIES INC"},
}


def _fresh_engine(monkeypatch=None):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


# --- find_discrete_income_statement_value (interest expense) --------------


def test_finds_discrete_quarter_value_reproducing_the_known_pep_figure():
    # The exact case this feature exists for: PEP's real Q2 2026 filed
    # interest expense was $230M, not FMP's erroneous $2,300M.
    value, tag = find_discrete_income_statement_value(
        PEP_FACTS, sec_edgar.INTEREST_EXPENSE_CANDIDATE_TAGS, date(2026, 6, 13)
    )
    assert value == 230_000_000
    assert tag == "InterestExpense"


def test_falls_back_to_a_later_candidate_tag_when_the_first_has_no_recent_data():
    # OXM stopped using InterestExpense after FY2018 (confirmed live) --
    # its current filings use InterestIncomeExpenseNonoperatingNet instead.
    # The fixture's InterestExpense tag has no entry anywhere near
    # 2026-05-02, so this must fall through past it.
    value, tag = find_discrete_income_statement_value(
        OXM_FACTS, sec_edgar.INTEREST_EXPENSE_CANDIDATE_TAGS, date(2026, 5, 2)
    )
    assert tag == "InterestIncomeExpenseNonoperatingNet"
    assert value == -2_282_000


def test_returns_none_when_no_candidate_tag_covers_the_target_period():
    result = find_discrete_income_statement_value(PEP_FACTS, sec_edgar.INTEREST_EXPENSE_CANDIDATE_TAGS, date(1999, 1, 1))
    assert result is None


def test_ignores_ytd_entries_sharing_the_same_end_date_as_a_discrete_entry():
    # PEP's InterestExpense tag has both a YTD (start 2025-12-28) and a
    # discrete (start 2026-03-22) row ending 2026-06-13 -- must pick the
    # ~3-month one, not the ~6-month YTD one.
    value, tag = find_discrete_income_statement_value(
        PEP_FACTS, sec_edgar.INTEREST_EXPENSE_CANDIDATE_TAGS, date(2026, 6, 13)
    )
    assert value == 230_000_000  # not 531_000_000, the YTD figure for the same end date


# --- find_discrete_cfo_value (YTD subtraction) -----------------------------


def test_cfo_ytd_subtraction_matches_fmp_quarterly_figure():
    # YTD-through-Q2 ($2,365M) - YTD-through-Q1 ($41M) = $2,324M, confirmed
    # live against FMP's own quarterly CFO for the same period.
    value, tag = find_discrete_cfo_value(PEP_FACTS, sec_edgar.CFO_CANDIDATE_TAGS, date(2026, 6, 13))
    assert value == 2_365_000_000 - 41_000_000
    assert tag == "NetCashProvidedByUsedInOperatingActivities"


def test_cfo_q1_needs_no_subtraction_since_ytd_through_q1_is_the_discrete_value():
    # Fiscal-year-boundary case: Q1's YTD figure IS the discrete figure,
    # since there's no earlier same-fiscal-year entry to subtract.
    value, tag = find_discrete_cfo_value(PEP_FACTS, sec_edgar.CFO_CANDIDATE_TAGS, date(2026, 3, 21))
    assert value == 41_000_000


def test_cfo_subtraction_uses_same_fiscal_year_start_not_just_second_most_recent():
    # OXM fixture: target Q1 2026 (start 2026-02-01, end 2026-05-02) has no
    # earlier same-fiscal-year entry (FY2025 entries all start 2025-02-02,
    # a different start date) -- must read as "no subtraction needed", not
    # naively subtract the FY2025 Q4/FY total just because it's chronologically
    # the second-most-recent row.
    value, tag = find_discrete_cfo_value(OXM_FACTS, sec_edgar.CFO_CANDIDATE_TAGS, date(2026, 5, 2))
    assert value == 7_902_000  # the YTD/discrete Q1 value itself, not e.g. 7_902_000 - 119_646_000


def test_cfo_returns_none_when_target_period_not_present():
    result = find_discrete_cfo_value(PEP_FACTS, sec_edgar.CFO_CANDIDATE_TAGS, date(1999, 1, 1))
    assert result is None


# --- get_cik ----------------------------------------------------------------


def test_get_cik_finds_ticker_in_the_cached_map(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    async def fake_fetch():
        return TICKER_CIK_MAP

    monkeypatch.setattr(sec_edgar, "_fetch_ticker_cik_map", fake_fetch)

    with Session(engine) as session:
        cik = asyncio.run(get_cik(session, "pep", 7))  # lowercase input
    assert cik == 77476


def test_get_cik_returns_none_when_ticker_not_found(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    async def fake_fetch():
        return TICKER_CIK_MAP

    monkeypatch.setattr(sec_edgar, "_fetch_ticker_cik_map", fake_fetch)

    with Session(engine) as session:
        cik = asyncio.run(get_cik(session, "ZZZZINVALID", 7))
    assert cik is None


def test_cik_map_is_cached_not_refetched_on_second_call(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    call_count = {"n": 0}

    async def fake_fetch():
        call_count["n"] += 1
        return TICKER_CIK_MAP

    monkeypatch.setattr(sec_edgar, "_fetch_ticker_cik_map", fake_fetch)

    with Session(engine) as session:
        asyncio.run(get_cik(session, "PEP", 7))
        asyncio.run(get_cik(session, "OXM", 7))
    assert call_count["n"] == 1


# --- cross_check_interest_expense / cross_check_cfo (end-to-end, mocked) --


def test_cross_check_interest_expense_reports_discrepancy_for_pep(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    async def fake_cik_map():
        return TICKER_CIK_MAP

    async def fake_company_facts(cik):
        return PEP_FACTS

    monkeypatch.setattr(sec_edgar, "_fetch_ticker_cik_map", fake_cik_map)
    monkeypatch.setattr(sec_edgar, "_fetch_company_facts", fake_company_facts)

    with Session(engine) as session:
        result = asyncio.run(cross_check_interest_expense(session, "PEP", date(2026, 6, 13), 2_300_000_000.0, 7))

    assert result.available is True
    assert result.sec_value == 230_000_000
    assert result.tag_used == "InterestExpense"
    assert result.matches_fmp is False
    assert "data error" in result.note


def test_cross_check_cfo_confirms_fmp_figure_when_they_match(monkeypatch):
    # The Q1 CFO case: FMP's $41M was correct all along (genuine seasonal
    # low, not a data error) -- the cross-check must say so plainly, not
    # only ever report problems.
    engine = _fresh_engine(monkeypatch)

    async def fake_cik_map():
        return TICKER_CIK_MAP

    async def fake_company_facts(cik):
        return PEP_FACTS

    monkeypatch.setattr(sec_edgar, "_fetch_ticker_cik_map", fake_cik_map)
    monkeypatch.setattr(sec_edgar, "_fetch_company_facts", fake_company_facts)

    with Session(engine) as session:
        result = asyncio.run(cross_check_cfo(session, "PEP", date(2026, 3, 21), 41_000_000.0, 7))

    assert result.available is True
    assert result.sec_value == 41_000_000
    assert result.matches_fmp is True
    assert result.note == "SEC EDGAR confirms FMP's figure."


def test_cross_check_degrades_gracefully_when_cik_not_found(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    async def fake_cik_map():
        return TICKER_CIK_MAP

    monkeypatch.setattr(sec_edgar, "_fetch_ticker_cik_map", fake_cik_map)

    with Session(engine) as session:
        result = asyncio.run(cross_check_interest_expense(session, "ZZZZINVALID", date(2026, 6, 13), 100.0, 7))

    assert result.available is False
    assert result.sec_value is None
    assert result.matches_fmp is None
    assert "no CIK found" in result.note


def test_cross_check_degrades_gracefully_on_network_error(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    async def fake_cik_map():
        return TICKER_CIK_MAP

    async def failing_company_facts(cik):
        raise httpx.HTTPError("simulated network failure")

    monkeypatch.setattr(sec_edgar, "_fetch_ticker_cik_map", fake_cik_map)
    monkeypatch.setattr(sec_edgar, "_fetch_company_facts", failing_company_facts)

    with Session(engine) as session:
        result = asyncio.run(cross_check_cfo(session, "PEP", date(2026, 3, 21), 41_000_000.0, 7))

    assert result.available is False
    assert "network error" in result.note


def test_cross_check_degrades_gracefully_when_no_matching_tag_or_period(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    async def fake_cik_map():
        return TICKER_CIK_MAP

    async def fake_company_facts(cik):
        return PEP_FACTS

    monkeypatch.setattr(sec_edgar, "_fetch_ticker_cik_map", fake_cik_map)
    monkeypatch.setattr(sec_edgar, "_fetch_company_facts", fake_company_facts)

    with Session(engine) as session:
        result = asyncio.run(cross_check_interest_expense(session, "PEP", date(1999, 1, 1), 100.0, 7))

    assert result.available is False
    assert "no matching interest expense figure" in result.note


def test_company_facts_cached_not_refetched_on_second_call(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    call_count = {"n": 0}

    async def fake_cik_map():
        return TICKER_CIK_MAP

    async def fake_company_facts(cik):
        call_count["n"] += 1
        return PEP_FACTS

    monkeypatch.setattr(sec_edgar, "_fetch_ticker_cik_map", fake_cik_map)
    monkeypatch.setattr(sec_edgar, "_fetch_company_facts", fake_company_facts)

    with Session(engine) as session:
        asyncio.run(cross_check_interest_expense(session, "PEP", date(2026, 6, 13), 2_300_000_000.0, 7))
        asyncio.run(cross_check_cfo(session, "PEP", date(2026, 3, 21), 41_000_000.0, 7))

    assert call_count["n"] == 1
