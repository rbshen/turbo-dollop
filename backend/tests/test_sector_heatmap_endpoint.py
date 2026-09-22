from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import data.sector_heatmap_data as sector_heatmap_data
from core.main import app
from core.models import SectorEtfReturn


def _fresh_engine(monkeypatch):
    # StaticPool: the TestClient runs the sync endpoint in a worker thread,
    # and a bare `sqlite://` engine would hand that thread its own empty DB
    # (same convention as test_momentum_endpoint.py).
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(sector_heatmap_data, "engine", engine)
    return engine


def test_empty_before_the_job_has_ever_run(monkeypatch):
    _fresh_engine(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/sector-heatmap")
    assert response.status_code == 200
    body = response.json()
    assert body["as_of_date"] is None and body["computed_at"] is None and body["rows"] == []
    assert body["windows"] == ["1d", "1w", "1m", "3m", "6m", "9m", "ytd", "1y"]


def test_serves_the_latest_as_of_date_with_return_pct_and_base_date(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 21, 3, 30)
    with Session(engine) as session:
        session.add(SectorEtfReturn(ticker="XLK", return_window="1m", as_of_date=date(2026, 9, 17), base_date=date(2026, 8, 17),
                                    return_pct=1.0, computed_at=now))
        session.add(SectorEtfReturn(ticker="XLK", return_window="1m", as_of_date=date(2026, 9, 18), base_date=date(2026, 8, 18),
                                    return_pct=4.25, computed_at=now))
        session.add(SectorEtfReturn(ticker="XLK", return_window="1y", as_of_date=date(2026, 9, 18), base_date=None,
                                    return_pct=None, computed_at=now))
        session.commit()

    with TestClient(app) as client:
        body = client.get("/api/sector-heatmap").json()

    assert body["as_of_date"] == "2026-09-18"
    assert len(body["rows"]) == 11
    xlk = body["rows"][0]
    assert xlk["ticker"] == "XLK" and xlk["name"] == "Technology"
    assert xlk["cells"]["1m"] == {"return_pct": 4.25, "base_date": "2026-08-18"}
    assert xlk["cells"]["1y"] == {"return_pct": None, "base_date": None}
    # A window/ETF with no stored row at all is present but blank.
    assert xlk["cells"]["3m"] == {"return_pct": None, "base_date": None}
    assert body["rows"][1]["cells"]["1m"] == {"return_pct": None, "base_date": None}
