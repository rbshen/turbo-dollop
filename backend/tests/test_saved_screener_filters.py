from sqlmodel import Session, SQLModel, create_engine

from data.saved_screener_filters import get_saved_filter, upsert_saved_filter


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _upsert(session, **overrides):
    values = dict(
        name="View",
        universe="all",
        sort_field="overall_score",
        sort_direction="desc",
        filters_json="{}",
        watchlist_id=None,
    )
    values.update(overrides)
    return upsert_saved_filter(session, **values)


def test_upsert_round_trips_a_saved_view():
    engine = _fresh_engine()
    with Session(engine) as session:
        _upsert(session, sort_field="step1_score")
        row = get_saved_filter(session, "View")

    assert row is not None
    assert row.sort_field == "step1_score"
    assert row.watchlist_id is None


def test_upsert_updates_on_conflict_by_name():
    engine = _fresh_engine()
    with Session(engine) as session:
        _upsert(session, sort_direction="desc")
        _upsert(session, sort_direction="asc")
        row = get_saved_filter(session, "View")

    assert row is not None
    assert row.sort_direction == "asc"


# --- kind: "stock" (default) vs "etf" (2026-10-02) ---------------------------------------------------------

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

import core.main as main
from core.models import SavedScreenerFilter
from data.saved_screener_filters import delete_saved_filter, list_saved_filters


def test_a_saved_view_defaults_to_the_stock_kind_everywhere():
    engine = _fresh_engine()
    with Session(engine) as session:
        row = _upsert(session)
        assert row.kind == "stock"
        assert get_saved_filter(session, "View").kind == "stock"
        assert [r.name for r in list_saved_filters(session)] == ["View"]
        assert delete_saved_filter(session, "View") is True


def test_a_stock_and_an_etf_view_can_share_a_name_and_stay_separate():
    engine = _fresh_engine()
    with Session(engine) as session:
        _upsert(session, sort_field="overall_score")
        _upsert(session, sort_field="aum", kind="etf")
        _upsert(session, sort_field="step1_score")  # updates the stock one only

        assert get_saved_filter(session, "View").sort_field == "step1_score"
        assert get_saved_filter(session, "View", "etf").sort_field == "aum"
        assert [r.sort_field for r in list_saved_filters(session)] == ["step1_score"]
        assert [r.sort_field for r in list_saved_filters(session, "etf")] == ["aum"]

        assert delete_saved_filter(session, "View", "etf") is True
        assert get_saved_filter(session, "View", "etf") is None
        assert get_saved_filter(session, "View") is not None  # the stock view survived
        assert delete_saved_filter(session, "View", "etf") is False


def test_the_database_itself_enforces_one_name_per_kind():
    engine = _fresh_engine()
    with Session(engine) as session:
        now = datetime.now()
        base = dict(name="Dup", universe="all", sort_field="a", sort_direction="asc", filters_json="{}", created_at=now, updated_at=now)
        session.add(SavedScreenerFilter(kind="etf", **base))
        session.add(SavedScreenerFilter(kind="stock", **base))
        session.commit()
        session.add(SavedScreenerFilter(kind="etf", **base))
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return TestClient(main.app)


BODY = {"universe": "all", "sort_field": "overall_score", "sort_direction": "desc", "filters": {"a": 1}, "watchlist_id": None}


def test_the_stock_endpoints_behave_as_before_when_no_kind_is_given(client):
    put = client.put("/api/screener/filters/My view", json=BODY)
    assert put.status_code == 200
    assert put.json()["name"] == "My view" and put.json()["filters"] == {"a": 1} and put.json()["kind"] == "stock"

    assert [r["name"] for r in client.get("/api/screener/filters").json()] == ["My view"]
    assert client.get("/api/screener/filters?kind=etf").json() == []
    assert client.delete("/api/screener/filters/My view").status_code == 204
    assert client.get("/api/screener/filters").json() == []
    assert client.delete("/api/screener/filters/My view").status_code == 404


def test_an_etf_view_and_a_stock_view_can_share_a_name_through_the_api(client):
    client.put("/api/screener/filters/Shared", json=BODY)
    etf_body = {**BODY, "sort_field": "aum", "filters": {"b": 2}}
    put = client.put("/api/screener/filters/Shared?kind=etf", json=etf_body)
    assert put.status_code == 200 and put.json()["kind"] == "etf"

    stock = client.get("/api/screener/filters").json()
    etf = client.get("/api/screener/filters?kind=etf").json()
    assert [(r["name"], r["sort_field"], r["kind"]) for r in stock] == [("Shared", "overall_score", "stock")]
    assert [(r["name"], r["sort_field"], r["kind"]) for r in etf] == [("Shared", "aum", "etf")]

    assert client.delete("/api/screener/filters/Shared?kind=etf").status_code == 204
    assert [r["name"] for r in client.get("/api/screener/filters").json()] == ["Shared"]
    assert client.delete("/api/screener/filters/Shared?kind=etf").status_code == 404


def test_an_unknown_kind_is_rejected(client):
    assert client.get("/api/screener/filters?kind=bond").status_code == 422
    assert client.put("/api/screener/filters/X?kind=bond", json=BODY).status_code == 422
    assert client.delete("/api/screener/filters/X?kind=bond").status_code == 422
