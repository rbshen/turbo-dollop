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
