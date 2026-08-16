from fastapi.testclient import TestClient

import core.main as main
from clients.sec_edgar import CrossCheckResult


def test_cash_flow_cell_check_endpoint_returns_sec_cross_check_shape(monkeypatch):
    received = {}

    async def fake_get_cash_flow_cell_sec_check(ticker, field, period_end):
        received["ticker"] = ticker
        received["field"] = field
        received["period_end"] = period_end
        return CrossCheckResult(True, 28_700_000_000.0, "IncomeTaxesPaidNet", False, "FMP's figure appears to be a data error -- SEC EDGAR's filed value differs significantly.")

    monkeypatch.setattr(main, "get_cash_flow_cell_sec_check", fake_get_cash_flow_cell_sec_check)

    with TestClient(main.app) as client:
        response = client.get(
            "/api/tickers/msft/financials/cash-flow-cell-check",
            params={"field": "incomeTaxesPaid", "period_end": "2025-06-30"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "sec_value": 28_700_000_000.0,
        "tag_used": "IncomeTaxesPaidNet",
        "matches_fmp": False,
        "note": "FMP's figure appears to be a data error -- SEC EDGAR's filed value differs significantly.",
    }
    assert received == {"ticker": "msft", "field": "incomeTaxesPaid", "period_end": "2025-06-30"}


def test_cash_flow_cell_check_endpoint_returns_400_for_unsupported_field(monkeypatch):
    async def fake_get_cash_flow_cell_sec_check(ticker, field, period_end):
        raise ValueError(f"Unsupported field {field!r} -- only ['incomeTaxesPaid', 'interestPaid'] are supported.")

    monkeypatch.setattr(main, "get_cash_flow_cell_sec_check", fake_get_cash_flow_cell_sec_check)

    with TestClient(main.app) as client:
        response = client.get(
            "/api/tickers/msft/financials/cash-flow-cell-check",
            params={"field": "netIncome", "period_end": "2025-06-30"},
        )

    assert response.status_code == 400
    assert "Unsupported field" in response.json()["detail"]


def test_cash_flow_cell_check_endpoint_returns_400_for_malformed_period_end(monkeypatch):
    async def fake_get_cash_flow_cell_sec_check(ticker, field, period_end):
        raise ValueError("period_end must be an ISO date (YYYY-MM-DD).")

    monkeypatch.setattr(main, "get_cash_flow_cell_sec_check", fake_get_cash_flow_cell_sec_check)

    with TestClient(main.app) as client:
        response = client.get(
            "/api/tickers/msft/financials/cash-flow-cell-check",
            params={"field": "incomeTaxesPaid", "period_end": "not-a-date"},
        )

    assert response.status_code == 400
    assert "period_end must be an ISO date" in response.json()["detail"]


def test_cash_flow_cell_check_endpoint_requires_field_and_period_end_query_params():
    # Rate-limit-safety shape check: no batch/list parameter is accepted at
    # all -- a request missing either required single-value query param must
    # be rejected outright (422), not silently default to "check everything".
    with TestClient(main.app) as client:
        response = client.get("/api/tickers/msft/financials/cash-flow-cell-check")

    assert response.status_code == 422
