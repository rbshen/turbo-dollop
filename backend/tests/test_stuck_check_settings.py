"""The Settings > Why might it be stuck? store and endpoints: lazy seed, validation, bounds, reset, and the card reading the saved values."""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
import data.stuck_check_data as stuck_data
from core.models import FundamentalsCache, StuckCheckSettings
from core.schemas import StuckCheckSettingsIn
from data.stuck_check_settings import load_stuck_settings
from scoring.stuck_check import DEFAULT_STUCK_SETTINGS, STUCK_BOUNDS

URL = "/api/config/stuck-check"
VALID = {
    "sbc_revenue_pct": 8,
    "sbc_fcf_pct": 30,
    "cash_conversion_line": 0.7,
    "share_growth_pct": 2,
    "one_off_pct": 60,
    "sector_band_pp": 2,
    "smoothing_days": 5,
    "exemptions": [{"ticker": "IBKR", "reason": "Broker", "rows": ["1", "3"]}],
}


@pytest.fixture
def engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(stuck_data, "engine", engine)
    return engine


@pytest.fixture
def client(engine):
    return TestClient(main.app)


def test_pydantic_bounds_match_the_one_definition():
    for name, (low, high) in STUCK_BOUNDS.items():
        meta = {type(m).__name__: m for m in StuckCheckSettingsIn.model_fields[name].metadata}
        assert (meta["Ge"].ge, meta["Le"].le) == (low, high), name


def test_get_seeds_the_defaults_and_reports_bounds_and_row_options(client):
    body = client.get(URL).json()
    assert {k: body[k] for k in VALID if k != "exemptions"} == {k: v for k, v in VALID.items() if k != "exemptions"}
    assert [e["ticker"] for e in body["exemptions"]] == ["IBKR", "GM"]
    assert body["exemptions"][0]["rows"] == ["1", "2_fcf", "3", "5", "6"]
    assert body["defaults"]["sbc_revenue_pct"] == 8 and body["bounds"]["smoothing_days"] == {"min": 1, "max": 20}
    assert {"key": "2_fcf", "label": "SBC as % of free cash flow"} in body["row_options"]


def test_put_saves_and_the_loader_reads_it_back(client, engine):
    body = {**VALID, "sbc_revenue_pct": 12.5, "smoothing_days": 8, "exemptions": [{"ticker": " abc ", "reason": " Hand-checked ", "rows": ["5"]}]}
    response = client.put(URL, json=body)
    assert response.status_code == 200
    saved = response.json()
    assert saved["sbc_revenue_pct"] == 12.5 and saved["exemptions"] == [{"ticker": "ABC", "reason": "Hand-checked", "rows": ["5"]}]
    loaded = load_stuck_settings(engine)
    assert loaded.sbc_revenue_pct == 12.5 and loaded.smoothing_days == 8 and loaded.exemptions[0].ticker == "ABC"
    assert client.get(URL).json()["sbc_revenue_pct"] == 12.5


@pytest.mark.parametrize(
    "patch",
    [
        {"sbc_revenue_pct": 0.5},
        {"sbc_revenue_pct": 51},
        {"sbc_fcf_pct": 4},
        {"cash_conversion_line": 2},
        {"share_growth_pct": 0},
        {"one_off_pct": 29},
        {"one_off_pct": 96},
        {"sector_band_pp": 11},
        {"smoothing_days": 0},
        {"smoothing_days": 21},
        {"smoothing_days": 2.5},
        {"sbc_revenue_pct": "x"},
        {"exemptions": [{"ticker": "", "reason": "r", "rows": ["1"]}]},
        {"exemptions": [{"ticker": "AB CD", "reason": "r", "rows": ["1"]}]},
        {"exemptions": [{"ticker": "ABC", "reason": "  ", "rows": ["1"]}]},
        {"exemptions": [{"ticker": "ABC", "reason": "r", "rows": []}]},
        {"exemptions": [{"ticker": "ABC", "reason": "r", "rows": ["7"]}]},
        {"exemptions": [{"ticker": "ABC", "reason": "r", "rows": ["1", "1"]}]},
        {"exemptions": [{"ticker": "ABC", "reason": "r", "rows": ["1"]}, {"ticker": "abc", "reason": "r", "rows": ["3"]}]},
    ],
)
def test_invalid_values_are_rejected_and_nothing_is_saved(client, engine, patch):
    assert client.put(URL, json={**VALID, **patch}).status_code == 422
    with Session(engine) as session:
        assert session.exec(select(StuckCheckSettings)).all() == []


def test_bounds_edges_are_accepted(client):
    edges = {"sbc_revenue_pct": 1, "sbc_fcf_pct": 100, "cash_conversion_line": 1.5, "share_growth_pct": 0.5, "one_off_pct": 95, "sector_band_pp": 10, "smoothing_days": 20, "exemptions": []}
    assert client.put(URL, json={**VALID, **edges}).status_code == 200


def test_reset_restores_defaults_including_the_seeded_exemptions(client):
    client.put(URL, json={**VALID, "sbc_revenue_pct": 20, "exemptions": []})
    body = client.post(URL + "/reset").json()
    assert body["sbc_revenue_pct"] == 8 and [e["ticker"] for e in body["exemptions"]] == ["IBKR", "GM"]


def test_an_unseeded_database_or_a_missing_table_serves_the_defaults(engine):
    assert load_stuck_settings(engine) == DEFAULT_STUCK_SETTINGS
    bare = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert load_stuck_settings(bare) == DEFAULT_STUCK_SETTINGS  # no table at all


def test_a_save_changes_the_next_card_load_with_no_recompute(client, engine):
    with Session(engine) as session:
        def put(statement_type, rows):
            session.add(FundamentalsCache(ticker="ACME", statement_type=statement_type, period="annual" if statement_type != "profile" else "latest", fetched_at=datetime.now(), raw_json=json.dumps(rows)))

        years = range(2016, 2026)
        put("profile", [{"sector": "Technology", "ipoDate": "2010-01-01"}])
        put("income_statement", [{"fiscalYear": str(y), "date": f"{y}-12-31", "revenue": 1000.0, "netIncome": 100.0, "weightedAverageShsOutDil": 100.0} for y in years][::-1])
        put("cash_flow_statement", [{"fiscalYear": str(y), "date": f"{y}-12-31", "netCashProvidedByOperatingActivities": 400.0, "capitalExpenditure": -10.0, "stockBasedCompensation": 60.0} for y in years][::-1])
        session.commit()
    sbc = lambda: next(r for r in client.get("/api/tickers/ACME/stuck-check").json()["rows"] if r["key"] == "sbc")["status"]  # noqa: E731
    assert sbc() == "ok"  # 6% of revenue, 15% of FCF
    client.put(URL, json={**VALID, "sbc_revenue_pct": 5})
    assert sbc() == "flagged"
    client.put(URL, json={**VALID, "sbc_revenue_pct": 5, "exemptions": [{"ticker": "ACME", "reason": "x", "rows": ["2"]}]})
    assert sbc() == "not_applicable"
