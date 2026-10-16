"""The Technical Ideas page's API (GET /api/technical-ideas/warren, DELETE /api/technical-ideas/warren/{ticker}): the stored table read,
removed rows hidden, the roles, the ages in 2h candles and the removal that a nightly rerun does not undo. The viewer's
zero-FMP / zero-write guarantee for the GET is also covered by tests/test_viewer_rules.py (every viewer GET)."""

import os
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
import data.warren_watch_data as wwd
from core.models import WarrenWatchCursor, WarrenWatchRow
from test_warren_watch_data import NOW, bars, canned, fake_lp, run


@pytest.fixture(autouse=True)
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)  # the endpoint runs in a worker thread
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(wwd, "engine", eng)
    return eng


@pytest.fixture
def utc_server(monkeypatch):
    """The server clock is UTC in production; `last_updated_at` is converted from server-local wall clock, so pin it."""
    old = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def add_row(engine, ticker="AAA", **kw):
    values = dict(
        ticker=ticker, profile="any", latest_arrow_kind="yellow_up", latest_arrow_at=datetime(2026, 10, 15, 13, 30), instruction_type=3,
        instruction_text="Buy", entry_kind="yellow", entry_at=datetime(2026, 10, 15, 13, 30), entry_price=100.0, stop_price=90.0,
        stop_basis="10%", status="active", breached_at=None, last_signal_at=datetime(2026, 10, 15, 13, 30),
        last_updated_at=datetime(2026, 10, 16, 5, 25), removed_at=None, as_of=datetime(2026, 10, 16, 15, 30),
    )
    values.update(kw)
    with Session(engine) as s:
        s.add(WarrenWatchRow(**values))
        if s.get(WarrenWatchCursor, ticker) is None:
            s.add(WarrenWatchCursor(ticker=ticker, processed_through=values["as_of"], updated_at=values["last_updated_at"]))
        s.commit()


def test_get_returns_the_stored_rows_with_arrow_split_ages_and_et_times(engine, utc_server):
    add_row(engine, "AAA")
    add_row(engine, "BBB", latest_arrow_kind="blue_down", instruction_type=10, stop_basis="LP", stop_price=105.0, status="breached",
            breached_at=datetime(2026, 10, 16, 11, 30), last_signal_at=datetime(2026, 10, 15, 9, 30))
    body = TestClient(main.app).get("/api/technical-ideas/warren").json()
    assert body["as_of"] == "2026-10-16T15:30:00"
    a, b = body["rows"]
    assert (a["ticker"], b["ticker"]) == ("AAA", "BBB")
    # Candles after 10-15 13:30 up to 10-16 15:30: 10-15 15:30 and the four of 10-16.
    assert (a["latest_arrow_color"], a["latest_arrow_direction"], a["age_bars"], a["last_signal_age_bars"]) == ("yellow", "up", 5, 5)
    assert (b["latest_arrow_color"], b["latest_arrow_direction"], b["age_bars"], b["last_signal_age_bars"]) == ("blue", "down", 5, 7)
    assert a["last_updated_at"] == "2026-10-16T01:25:00"  # 05:25 server (UTC) -> 01:25 ET
    assert b["status"] == "breached" and b["breached_at"] == "2026-10-16T11:30:00"
    assert set(a) == {
        "ticker", "profile", "latest_arrow_color", "latest_arrow_direction", "latest_arrow_at", "instruction_type", "instruction_text",
        "entry_kind", "entry_price", "stop_price", "stop_basis", "status", "breached_at", "last_signal_at", "last_updated_at",
        "age_bars", "last_signal_age_bars",
    }


def test_age_follows_the_nyse_calendar_holiday_and_early_close(engine):
    # Thanksgiving 2026-11-26 is closed; the Friday 11-27 closes at 13:00 (windows 09:30 and 11:30 only).
    add_row(engine, "AAA", latest_arrow_at=datetime(2026, 11, 25, 15, 30), last_signal_at=datetime(2026, 11, 25, 15, 30),
            as_of=datetime(2026, 11, 30, 9, 30))
    row = TestClient(main.app).get("/api/technical-ideas/warren").json()["rows"][0]
    assert row["age_bars"] == 3  # 11-27 09:30, 11-27 11:30, 11-30 09:30
    add_row(engine, "BBB", latest_arrow_at=datetime(2026, 11, 30, 9, 30), last_signal_at=datetime(2026, 11, 30, 9, 30), as_of=datetime(2026, 11, 30, 9, 30))
    assert [r["age_bars"] for r in TestClient(main.app).get("/api/technical-ideas/warren").json()["rows"]] == [3, 0]


def test_an_empty_table_returns_no_rows_and_no_as_of():
    assert TestClient(main.app).get("/api/technical-ideas/warren").json() == {"as_of": None, "rows": []}


def test_get_excludes_removed_rows(engine):
    add_row(engine, "AAA")
    add_row(engine, "BBB", removed_at=datetime(2026, 10, 16, 9, 0))
    assert [r["ticker"] for r in TestClient(main.app).get("/api/technical-ideas/warren").json()["rows"]] == ["AAA"]


@pytest.mark.auth("viewer")
def test_a_viewer_reads_but_cannot_remove(engine):
    add_row(engine, "AAA")
    client = TestClient(main.app)
    assert client.get("/api/technical-ideas/warren").status_code == 200
    assert client.delete("/api/technical-ideas/warren/AAA").status_code == 403
    with Session(engine) as s:
        assert s.get(WarrenWatchRow, "AAA").removed_at is None


@pytest.mark.auth("anonymous")
def test_anonymous_gets_401_on_both(engine):
    add_row(engine, "AAA")
    client = TestClient(main.app)
    assert client.get("/api/technical-ideas/warren").status_code == 401
    assert client.delete("/api/technical-ideas/warren/AAA").status_code == 401


def test_an_admin_removes_a_row_once(engine):
    add_row(engine, "AAA")
    client = TestClient(main.app)
    assert client.delete("/api/technical-ideas/warren/AAA").json() == {"removed": True}
    with Session(engine) as s:
        row = s.get(WarrenWatchRow, "AAA")
        assert row is not None and row.removed_at is not None  # a soft delete: the row stays
    assert client.get("/api/technical-ideas/warren").json()["rows"] == []
    assert client.delete("/api/technical-ideas/warren/AAA").status_code == 404  # already removed
    assert client.delete("/api/technical-ideas/warren/ZZZ").status_code == 404  # never on the table
    assert client.delete("/api/technical-ideas/warren/not%20a%20ticker").status_code == 422


def test_remove_then_a_rerun_of_the_nightly_step_does_not_resurrect_the_row(monkeypatch, engine):
    canned(monkeypatch, {"A": [("yellow_up", "2026-09-10 09:30")]})
    fake_lp(monkeypatch, [])
    run("A", bars("2026-07-01", "2026-09-15"))
    client = TestClient(main.app)
    assert [r["ticker"] for r in client.get("/api/technical-ideas/warren").json()["rows"]] == ["A"]
    assert client.delete("/api/technical-ideas/warren/A").status_code == 200

    # Later sessions replay the same old arrow; the step reads past the removal and finds nothing newer.
    assert run("A", bars("2026-07-01", "2026-10-16")).outcome == "removed"
    assert client.get("/api/technical-ideas/warren").json()["rows"] == []
    with Session(engine) as s:
        assert s.exec(select(WarrenWatchRow)).one().removed_at is not None
