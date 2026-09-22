from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import data.market_breadth_data as market_breadth_data
from core.main import app
from core.models import MarketBreadthSnapshot


def _fresh_engine(monkeypatch):
    # StaticPool: the TestClient runs the sync endpoint in a worker thread,
    # and a bare `sqlite://` engine would hand that thread its own empty DB.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(market_breadth_data, "engine", engine)
    return engine


def _row(as_of: date, universe="sp500", **overrides) -> MarketBreadthSnapshot:
    fields = dict(
        universe=universe, as_of_date=as_of, computed_at=datetime(2026, 9, 21, 3, 35), constituents=503, stale_excluded=1,
        sma20_eligible=503, sma20_above=90, pct_above_sma20=17.9, sma50_eligible=502, sma50_above=140, pct_above_sma50=27.9, sma200_eligible=501, sma200_above=247, pct_above_sma200=49.3,
        hl_eligible=499, new_highs=5, new_lows=29, net_new_highs=-24, is_backfilled=False,
    )
    fields.update(overrides)
    return MarketBreadthSnapshot(**fields)


def test_empty_before_any_row_exists(monkeypatch):
    _fresh_engine(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/market-breadth")
    assert response.status_code == 200
    assert response.json() == {"universe": "sp500", "as_of_date": None, "computed_at": None, "latest": None, "series": []}


def test_serves_the_whole_series_oldest_first_with_latest_and_flags(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        # Inserted out of order on purpose; another universe must not leak in.
        session.add(_row(date(2026, 9, 18)))
        session.add(_row(date(2026, 9, 16), is_backfilled=True, pct_above_sma50=None, net_new_highs=3))
        session.add(_row(date(2026, 9, 17), is_backfilled=True))
        # A row from before the 20-day metric existed, not yet backfilled.
        session.add(_row(date(2026, 9, 15), is_backfilled=True, sma20_eligible=None, sma20_above=None, pct_above_sma20=None))
        session.add(_row(date(2026, 9, 18), universe="dow", pct_above_sma50=99.0))
        session.commit()

    with TestClient(app) as client:
        body = client.get("/api/market-breadth").json()

    assert body["universe"] == "sp500" and body["as_of_date"] == "2026-09-18"
    assert [p["as_of_date"] for p in body["series"]] == ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]
    assert [p["is_backfilled"] for p in body["series"]] == [True, True, True, False]
    # Both history and latest carry the 20-day fields; a not-yet-backfilled row reads null, not 0.
    assert [p["pct_above_sma20"] for p in body["series"]] == [None, 17.9, 17.9, 17.9]
    assert body["series"][0]["sma20_above"] is None and body["series"][0]["sma20_eligible"] is None
    assert body["series"][1]["sma20_above"] == 90 and body["series"][1]["sma20_eligible"] == 503
    assert body["series"][1]["pct_above_sma50"] is None and body["series"][1]["net_new_highs"] == 3
    latest = body["latest"]
    assert latest == body["series"][-1]
    assert latest["pct_above_sma20"] == 17.9 and latest["sma20_above"] == 90 and latest["sma20_eligible"] == 503
    assert latest["pct_above_sma50"] == 27.9 and latest["pct_above_sma200"] == 49.3
    assert latest["sma50_above"] == 140 and latest["sma200_above"] == 247
    assert latest["new_highs"] == 5 and latest["new_lows"] == 29 and latest["net_new_highs"] == -24
    assert latest["constituents"] == 503 and latest["stale_excluded"] == 1 and latest["hl_eligible"] == 499
    assert body["computed_at"] == "2026-09-21T03:35:00"


def test_universe_query_param_scopes_to_a_sector_and_never_leaks_sp500(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(_row(date(2026, 9, 18), universe="sp500", pct_above_sma50=27.9))
        session.add(_row(date(2026, 9, 17), universe="sector:XLK", constituents=85, pct_above_sma50=61.2))
        session.add(_row(date(2026, 9, 18), universe="sector:XLK", constituents=85, pct_above_sma50=63.4))
        session.commit()

    with TestClient(app) as client:
        default_body = client.get("/api/market-breadth").json()
        sector_body = client.get("/api/market-breadth", params={"universe": "sector:XLK"}).json()
        unknown_body = client.get("/api/market-breadth", params={"universe": "sector:ZZZZ"}).json()

    assert default_body["universe"] == "sp500" and len(default_body["series"]) == 1
    assert sector_body["universe"] == "sector:XLK"
    assert [p["as_of_date"] for p in sector_body["series"]] == ["2026-09-17", "2026-09-18"]
    assert all(p["constituents"] == 85 for p in sector_body["series"])
    assert sector_body["latest"]["pct_above_sma50"] == 63.4
    # An unrecognized universe reads empty, never a 404 or an error.
    assert unknown_body == {"universe": "sector:ZZZZ", "as_of_date": None, "computed_at": None, "latest": None, "series": []}
