"""GET /api/opportunities/{dates,latest,<date>}: read-only, the stored run as written (docs/specs/opportunities.md)."""

import json
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import data.opportunity_data as od
from core.main import app
from core.models import OpportunityRun, OpportunitySnapshotRow
from scoring import opportunity_rules as rules

NOW = datetime(2026, 10, 10, 4, 0)


@pytest.fixture
def engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(od, "engine", engine)
    return engine


def seed_run(engine, as_of: date, momentum=("AAA", "BBB"), reversal=("CCC",)):
    with Session(engine) as s:
        run = OpportunityRun(
            kind="weekly", as_of_date=as_of, last_bar_date=as_of, universe_size=600, rules_hash=rules.rules_hash(),
            rules_version=rules.RULES_VERSION, score_formula_version=6, weights_version=2, created_at=NOW,
            summary_json=json.dumps({"list_totals": {"momentum": len(momentum), "reversal": len(reversal)}, "market": {"breadth": None}}),
        )
        s.add(run)
        s.flush()
        for list_name, tickers, rule in (("momentum", momentum, rules.RULE_A), ("reversal", reversal, rules.RULE_B2)):
            for i, ticker in enumerate(tickers, start=1):
                s.add(OpportunitySnapshotRow(
                    run_id=run.id, list_name=list_name, ticker=ticker, tier="quality", list_order=i, rule_ids_json=json.dumps([rule]),
                    tags_json=json.dumps({"late_trend": True}), overall_score=80, steps_score=81.5, overall_verdict="Pass",
                    weinstein_stage="advance", vs_ma_pct=7.5, ma_slope_pct=1.1, mansfield_rs=2.2, momentum_rank=i, close=100.0, atr=2.5,
                    adv_usd=5e7, sector="Technology", inputs_json=json.dumps({"company_name": f"{ticker} Inc", "exchange": "NASDAQ", "weeks_in_advance": 12}),
                ))
        s.commit()


def test_dates_is_empty_before_any_run(engine):
    with TestClient(app) as client:
        assert client.get("/api/opportunities/dates").json() == []
        assert client.get("/api/opportunities/latest").status_code == 404
        assert client.get("/api/opportunities/2026-10-09").status_code == 404


def test_latest_returns_the_newest_run_with_both_lists_in_order(engine):
    seed_run(engine, date(2026, 10, 2), momentum=("OLD",), reversal=())
    seed_run(engine, date(2026, 10, 9))
    with TestClient(app) as client:
        body = client.get("/api/opportunities/latest").json()
    assert body["as_of_date"] == "2026-10-09" and body["kind"] == "weekly" and body["universe_size"] == 600
    assert body["rules_hash"] == rules.rules_hash() and body["rules_version"] == "1"
    assert body["score_formula_version"] == 6 and body["weights_version"] == 2
    assert [r["ticker"] for r in body["momentum"]] == ["AAA", "BBB"] and [r["ticker"] for r in body["reversal"]] == ["CCC"]
    assert body["rule_labels"][rules.RULE_B2] == "Price structure"
    assert body["summary"]["list_totals"] == {"momentum": 2, "reversal": 1}


def test_a_row_has_the_frozen_inputs_the_page_needs(engine):
    seed_run(engine, date(2026, 10, 9))
    with TestClient(app) as client:
        row = client.get("/api/opportunities/2026-10-09").json()["momentum"][0]
    assert row == {
        "ticker": "AAA", "company_name": "AAA Inc", "list_name": "momentum", "tier": "quality", "list_order": 1,
        "rule_ids": [rules.RULE_A], "tags": {"late_trend": True}, "overall_score": 80, "steps_score": 81.5, "overall_verdict": "Pass",
        "weinstein_stage": "advance", "vs_ma_pct": 7.5, "ma_slope_pct": 1.1, "mansfield_rs": 2.2, "momentum_rank": 1, "close": 100.0,
        "atr": 2.5, "adv_usd": 5e7, "sector": "Technology", "exchange": "NASDAQ", "weeks_in_advance": 12,
        "inputs": {"company_name": "AAA Inc", "exchange": "NASDAQ", "weeks_in_advance": 12},
    }


def test_by_date_picks_that_run_and_dates_lists_newest_first(engine):
    seed_run(engine, date(2026, 10, 2), momentum=("OLD",), reversal=())
    seed_run(engine, date(2026, 10, 9))
    with TestClient(app) as client:
        assert [r["ticker"] for r in client.get("/api/opportunities/2026-10-02").json()["momentum"]] == ["OLD"]
        dates = client.get("/api/opportunities/dates").json()
    assert [d["as_of_date"] for d in dates] == ["2026-10-09", "2026-10-02"]
    assert dates[0]["momentum_count"] == 2 and dates[0]["reversal_count"] == 1 and dates[1]["reversal_count"] == 0


def test_a_malformed_date_is_a_422_and_an_unknown_one_a_404(engine):
    seed_run(engine, date(2026, 10, 9))
    with TestClient(app) as client:
        assert client.get("/api/opportunities/not-a-date").status_code == 422
        assert client.get("/api/opportunities/2026-01-02").status_code == 404


def test_the_opportunity_routes_are_get_only():
    methods = {}
    for route in app.routes:
        if getattr(route, "path", "").startswith("/api/opportunities"):
            methods[route.path] = set(route.methods)
    assert set(methods) == {"/api/opportunities/dates", "/api/opportunities/latest", "/api/opportunities/{as_of_date}"}
    assert all(m <= {"GET", "HEAD"} for m in methods.values())


@pytest.mark.parametrize("verb", ["post", "put", "patch", "delete"])
def test_no_mutating_verb_is_accepted(engine, verb):
    seed_run(engine, date(2026, 10, 9))
    with TestClient(app) as client:
        for path in ("/api/opportunities/latest", "/api/opportunities/2026-10-09", "/api/opportunities/dates", "/api/opportunities"):
            assert getattr(client, verb)(path).status_code in (404, 405)


def test_reading_writes_nothing(engine):
    seed_run(engine, date(2026, 10, 9))
    with Session(engine) as s:
        before = [(r.id, r.inputs_json) for r in s.exec(select(OpportunitySnapshotRow)).all()]
    with TestClient(app) as client:
        for path in ("/api/opportunities/dates", "/api/opportunities/latest", "/api/opportunities/2026-10-09"):
            client.get(path)
    with Session(engine) as s:
        assert [(r.id, r.inputs_json) for r in s.exec(select(OpportunitySnapshotRow)).all()] == before
