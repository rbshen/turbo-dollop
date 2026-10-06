"""Every consumer of cleaned statement rows reads them through helpers/statement_view.py: each test spies on
`build_statement_view` while the real consumer runs against mocked FMP + an in-memory engine, and checks the view's
decisions reach the consumer's output. (The rules themselves are pinned in test_statement_view.py.)"""

import asyncio

import pytest

import helpers.statement_view as statement_view
from data.step1_data import get_step1_data
from data.step5_data import get_step5_data
from test_step1_data import _fresh_engine as step1_engine
from test_step1_data import _patch_fmp as patch_step1_fmp
from test_step5_data import _fresh_engine as step5_engine
from test_step5_data import _gate_bs, _patch_gate


@pytest.fixture
def views(monkeypatch):
    """Records every StatementView `build_statement_view` produces."""
    built = []
    real = statement_view.build_statement_view

    def spy(raw, company_type, **kwargs):
        view = real(raw, company_type, **kwargs)
        built.append((view, kwargs))
        return view

    monkeypatch.setattr(statement_view, "build_statement_view", spy)
    return built


def test_step5_reads_its_statements_through_the_loader(monkeypatch, views):
    step5_engine(monkeypatch)
    _patch_gate(
        monkeypatch,
        [
            _gate_bs("2026-06-30", long_term_debt=190, total_liabilities=11_929),
            _gate_bs("2026-03-31", long_term_debt=9_045, total_liabilities=11_921),
        ],
    )

    result = asyncio.run(get_step5_data("zts"))

    assert len(views) == 1
    view, _ = views[0]
    assert view.balance_sheet_fallback == result.balance_sheet_fallback and result.balance_sheet_fallback is not None
    assert result.ratios["debt_to_ebitda"].value == view.debt_metrics.total_debt / view.debt_metrics.ebitda_ttm


def test_step1_reads_its_statements_through_the_loader_without_a_balance_sheet(monkeypatch, views):
    step1_engine(monkeypatch)
    patch_step1_fmp(monkeypatch, {"profile": 0, "income_annual": 0, "income_quarter": 0, "cash_flow_annual": 0, "cash_flow_quarter": 0})

    result = asyncio.run(get_step1_data("aapl"))

    assert len(views) == 1
    view, kwargs = views[0]
    assert kwargs == {"use_balance_sheet": False}
    assert view.balance_sheet_row == {}
    assert result.cfo[-1] == view.ttm("cash_flow", "netCashProvidedByOperatingActivities").total


# ---- ticker header (data/ticker_summary.py) ------------------------------------------------------------------


def _gated_balance_rows():
    # newest quarter: long-term debt 1,000 -> 100 with total liabilities flat (a remap); prior quarter is the real one
    def row(date, long_term_debt):
        return {
            "date": date,
            "shortTermDebt": 0,
            "longTermDebt": long_term_debt,
            "totalDebt": long_term_debt,
            "totalLiabilities": 10_000,
            "totalAssets": 20_000,
            "totalCurrentAssets": 5_000,
            "totalCurrentLiabilities": 2_000,
        }

    return [row("2026-06-30", 100), row("2026-03-31", 1_000), row("2025-12-31", 1_000)]


def _ebitda_quarters():
    ends = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
    return [{"date": d, "ebitda": 1_000 if i == 0 else 100} for i, d in enumerate(ends)]


def test_header_debt_and_ebitda_read_the_gated_balance_sheet_and_aligned_income(monkeypatch, views):
    import test_ticker_summary as tts
    from data.ticker_summary import get_summary

    tts._fresh_summary_engine(monkeypatch)
    requested = []

    async def quote(ticker):
        return tts.FAKE_QUOTE

    tts._patch_all_but_quote(monkeypatch, quote)

    async def balance_sheet(ticker, period, limit):
        return _gated_balance_rows()

    async def income(ticker, period, limit):
        requested.append(period)
        return _ebitda_quarters() if period == "quarter" else []

    monkeypatch.setattr(tts.ticker_summary.fmp_client, "get_balance_sheet_statement", balance_sheet)
    monkeypatch.setattr(tts.ticker_summary.fmp_client, "get_income_statement", income)

    summary = asyncio.run(get_summary("aapl"))

    assert summary.total_debt == 1_000  # the prior quarter, not the partly filled newest one
    assert summary.ebitda_ttm == 400  # four quarters ending 2026-03-31, not 1,000 + 3 x 100
    assert "annual" in requested  # the annual income rows are loaded, so the Defect-B correction applies
    assert any(kwargs.get("use_balance_sheet", True) for _, kwargs in views)
    assert [v.balance_sheet_fallback.reason for v, _ in views if v.balance_sheet_fallback] == ["debt_remap"]


# ---- Speculative Growth (data/speculative_growth_data.py) --------------------------------------------------------


def test_speculative_growth_cash_and_cfo_direction_read_the_cleaned_rows(monkeypatch, views):
    import test_speculative_growth_data as tsg
    from data.speculative_growth_data import get_speculative_growth_data
    from scoring.speculative_growth import cfo_recent_direction

    tsg._fresh_engine(monkeypatch)
    ends = ["2026-03-28", "2025-12-27", "2025-09-27", "2025-06-28"] + [f"2024-{q:02d}-01" for q in range(1, 9)]
    income_rows = [{**tsg._income_quarter(d)} for d in ends]
    zero_cash_flow = {
        key: 0
        for key in (
            "netCashProvidedByOperatingActivities",
            "freeCashFlow",
            "capitalExpenditure",
            "netCashProvidedByInvestingActivities",
            "netCashProvidedByFinancingActivities",
        )
    }
    cash_flow = [{"date": ends[0], **zero_cash_flow}] + [
        {"date": d, "netCashProvidedByOperatingActivities": cfo} for d, cfo in zip(ends[1:], [15.0, -30.0] + [-30.0] * 9)
    ]
    balance_sheet = [
        {  # newest quarter: debt remapped (1,000 -> 100), cash looks fine but the row is the incomplete one
            "date": ends[0], "cashAndShortTermInvestments": 5.0, "shortTermDebt": 0, "longTermDebt": 100, "totalDebt": 100,
            "totalLiabilities": 10_000, "totalAssets": 20_000, "totalCurrentAssets": 5_000, "totalCurrentLiabilities": 2_000,
        },
        {
            "date": ends[1], "cashAndShortTermInvestments": 850.0, "shortTermDebt": 0, "longTermDebt": 1_000, "totalDebt": 1_000,
            "totalLiabilities": 10_000, "totalAssets": 20_000, "totalCurrentAssets": 5_000, "totalCurrentLiabilities": 2_000,
        },
    ]
    tsg._patch_fmp(monkeypatch, tsg.PROFILE_STANDARD, estimates=tsg.ESTIMATES_STRONG_GROWTH, income_quarterly=income_rows)

    async def fake_cash_flow(ticker, period, limit):
        return cash_flow if period == "quarter" else []

    async def fake_balance_sheet(ticker, period, limit):
        return balance_sheet

    monkeypatch.setattr(tsg.speculative_growth_data.fmp_client, "get_cash_flow_statement", fake_cash_flow)
    monkeypatch.setattr(tsg.speculative_growth_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet)

    result = asyncio.run(get_speculative_growth_data("TEST"))

    assert result.cash_and_st_investments == 850.0  # the prior quarter's cash
    # newest cash-flow quarter is a placeholder (all zeros beside a real net loss): the direction compares the last two
    # valid quarters (AZO-shaped), not 0 against +15
    assert result.cfo_recent_direction == cfo_recent_direction(15.0, -30.0) == "turning_positive"
    assert cfo_recent_direction(0.0, 15.0) == "mixed"  # what the raw rows read
    assert any(v.balance_sheet_fallback for v, _ in views)


# ---- Step 3 Valuation (data/step3_data.py) -------------------------------------------------------------------


def test_step3_reads_its_statements_through_the_loader_with_the_annual_balance_sheet(monkeypatch, views):
    import test_step3_data as t3
    from data.step3_data import get_step3_data

    t3._fresh_engine(monkeypatch)
    t3._patch_gated_data(monkeypatch)

    result = asyncio.run(get_step3_data("TEST"))

    assert len(views) == 1
    view, _ = views[0]
    assert view.balance_sheet_fallback is not None and view.balance_sheet_fallback.reason == "debt_remap"
    assert result.inputs.total_debt == view.debt_metrics.total_debt == 1_000
    assert result.inputs.cash_and_st_investments == view.balance_sheet_row["cashAndShortTermInvestments"]


# ---- Step 4 (data/step4_data.py) -----------------------------------------------------------------------------


def test_step4_reads_its_statements_through_the_loader(monkeypatch, views):
    import test_step4_data as t4
    from data.step4_data import get_step4_data

    t4._fresh_engine(monkeypatch)
    t4._patch_gated_quarters(monkeypatch)

    result = asyncio.run(get_step4_data("TEST"))

    assert len(views) == 1
    view, _ = views[0]
    assert view.balance_sheet_fallback.reason == "debt_remap"
    assert result.accounts_receivable[-1] == view.balance_sheet_row["accountsReceivables"] == 80.5255
