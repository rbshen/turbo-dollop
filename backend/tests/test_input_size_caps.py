"""Request size caps (core/schemas.py MAX_* / ShortText / DateText, core/main.py SavedViewNamePath and the Query caps)."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
from core.models import Watchlist
from core.schemas import (
    MAX_BULK_TICKERS,
    MAX_FILTERS_DEPTH,
    MAX_FILTERS_JSON_BYTES,
    MAX_FILTERS_KEYS,
    MAX_SAVED_VIEW_NAME,
    SavedScreenerFilterIn,
    TickerBankCapitalMetricsIn,
    WatchlistBulkAddIn,
    WatchlistIn,
    WatchlistUpdateIn,
)

# The largest saved view in the real DB today (678 bytes, depth 2, 20 keys) shaped like the Screener writes it.
REAL_SHAPED_FILTERS = {
    "overallVerdicts": ["Strong Pass", "Pass", "Pass with caution"],
    "step1Score": {"min": 70, "max": None},
    "sectors": [],
    "speculativeGrowth": False,
}


def _view(**overrides):
    return SavedScreenerFilterIn(
        **{"universe": "sp500", "sort_field": "overall_score", "sort_direction": "desc", "filters": REAL_SHAPED_FILTERS, **overrides}
    )


def _nested(depth: int):
    node: object = "leaf"
    for _ in range(depth):
        node = {"k": node}
    return node


def test_real_shaped_view_is_accepted():
    assert _view().filters == REAL_SHAPED_FILTERS


def test_filters_depth_is_bounded():
    assert _view(filters={"a": _nested(MAX_FILTERS_DEPTH - 1)})
    with pytest.raises(ValidationError):
        _view(filters={"a": _nested(MAX_FILTERS_DEPTH)})
    with pytest.raises(ValidationError):
        _view(filters={"a": [[[[[[[1]]]]]]]})


def test_extreme_nesting_is_rejected_without_a_recursion_error():
    with pytest.raises(ValidationError):
        _view(filters={"a": _nested(5000)})


def test_filters_size_and_key_count_are_bounded():
    with pytest.raises(ValidationError):
        _view(filters={"a": "x" * MAX_FILTERS_JSON_BYTES})
    with pytest.raises(ValidationError):
        _view(filters={f"k{i}": 1 for i in range(MAX_FILTERS_KEYS + 1)})
    assert _view(filters={f"k{i}": 1 for i in range(MAX_FILTERS_KEYS)})


def test_filters_must_serialise():
    with pytest.raises(ValidationError):
        _view(filters={"a": object()})


def test_saved_view_text_fields_are_capped():
    with pytest.raises(ValidationError):
        _view(universe="u" * 65)
    with pytest.raises(ValidationError):
        _view(sort_field="s" * 65)
    with pytest.raises(ValidationError):
        _view(sort_direction="d" * 65)


def test_bulk_add_item_count_is_capped():
    assert len(WatchlistBulkAddIn(tickers=["AAPL"] * MAX_BULK_TICKERS).tickers) == MAX_BULK_TICKERS
    with pytest.raises(ValidationError):
        WatchlistBulkAddIn(tickers=["AAPL"] * (MAX_BULK_TICKERS + 1))


def test_watchlist_name_and_update_fields_are_capped():
    assert WatchlistIn(name="n" * 100)
    with pytest.raises(ValidationError):
        WatchlistIn(name="n" * 101)
    with pytest.raises(ValidationError):
        WatchlistUpdateIn(sort_field="s" * 65)


def test_bank_metric_dates_are_capped():
    assert TickerBankCapitalMetricsIn(cet1_as_of="2026-06-30")
    with pytest.raises(ValidationError):
        TickerBankCapitalMetricsIn(npl_as_of="2" * 33)


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    with Session(engine) as session:
        session.add(Watchlist(name="Test", created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1)))
        session.commit()
    with TestClient(main.app) as c:
        yield c


def test_saved_view_name_path_is_capped(client):
    body = {"universe": "sp500", "sort_field": "overall_score", "sort_direction": "desc", "filters": REAL_SHAPED_FILTERS}
    assert client.put("/api/screener/filters/" + "n" * MAX_SAVED_VIEW_NAME, json=body).status_code == 200
    assert client.put("/api/screener/filters/" + "n" * (MAX_SAVED_VIEW_NAME + 1), json=body).status_code == 422
    assert client.delete("/api/screener/filters/" + "n" * (MAX_SAVED_VIEW_NAME + 1)).status_code == 422


def test_oversized_saved_view_body_is_a_422_and_stores_nothing(client):
    body = {"universe": "sp500", "sort_field": "x", "sort_direction": "desc", "filters": {"a": "x" * 30_000}}
    assert client.put("/api/screener/filters/big", json=body).status_code == 422
    assert client.get("/api/screener/filters").json() == []


def test_query_caps(client):
    assert client.get("/api/tickers/search", params={"q": "q" * 101}).status_code == 422
    assert client.get("/api/watchlists/export-data", params=[("ids", 1)] * 101).status_code == 422
    assert client.get("/api/watchlists/export-data", params=[("ids", 1)] * 100).status_code == 200
