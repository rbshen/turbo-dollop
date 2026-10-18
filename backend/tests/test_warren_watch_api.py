"""The Technical Ideas page's API (GET /api/technical-ideas/warren, DELETE /api/technical-ideas/warren/{ticker}): the stored table read,
removed rows hidden, the roles, the ages in 2h candles and the removal that a nightly rerun does not undo. The viewer's
zero-FMP / zero-write guarantee for the GET is also covered by tests/test_viewer_rules.py (every viewer GET)."""

import os
import time
from datetime import datetime, timedelta, timezone
from datetime import time as dtime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import clients.shared_bars_cache as sbc
import core.main as main
import data.warren_watch_data as wwd
from core.models import SharedBarsCache, WarrenWatchCursor, WarrenWatchRow
from test_warren_watch_data import NOW, bars, canned, fake_lp, run


@pytest.fixture(autouse=True)
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)  # the endpoint runs in a worker thread
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(wwd, "engine", eng)
    monkeypatch.setattr(sbc, "engine", eng)  # the page's Last price reads the shared daily-bar cache
    return eng


@pytest.fixture(autouse=True)
def fixed_headroom(monkeypatch):
    """The banner data is clock-dependent (data/warren_watch_data.py::anchor_headroom): pin it to 2026-10-18, headroom 361, level none
    (the banner's own tests are tests/test_anchor_headroom.py)."""
    monkeypatch.setattr(main, "anchor_headroom", lambda: wwd.anchor_headroom(now=datetime(2026, 10, 18, 17, 0, tzinfo=timezone.utc)))


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
        "entry_kind", "entry_at", "entry_price", "stop_price", "stop_basis", "stop_moved_at", "stop_moved_by", "stop_trailed_since_arrow", "last_price", "last_price_date", "pl_pct",
        "stop_distance_pct", "status", "breached_at", "last_signal_at", "last_updated_at", "age_bars", "last_signal_age_bars",
    }
    assert a["entry_at"] == "2026-10-15T13:30:00" and a["entry_kind"] == "yellow" and a["entry_price"] == 100.0
    assert a["stop_moved_at"] is None and a["stop_moved_by"] is None  # a row not yet rebuilt shows no stop age


def test_get_returns_the_stop_age_as_an_et_stamp_and_the_rule(engine, utc_server):
    add_row(engine, "AAA", stop_basis="LP", stop_price=95.0, stop_moved_at=datetime(2026, 10, 16, 13, 30), stop_moved_by="trail")
    add_row(engine, "BBB", stop_price=None, stop_basis="none", entry_kind="blue")
    a, b = TestClient(main.app).get("/api/technical-ideas/warren").json()["rows"]
    assert (a["stop_moved_at"], a["stop_moved_by"]) == ("2026-10-16T13:30:00", "trail")
    assert (b["stop_moved_at"], b["stop_moved_by"]) == (None, None)


def test_get_flags_a_stop_trailed_since_the_last_arrow(engine, utc_server):
    lp = dict(stop_basis="LP", stop_price=95.0, stop_moved_by="trail")
    add_row(engine, "TRL", stop_moved_at=datetime(2026, 10, 16, 9, 30), **lp)  # arrow 10-15 13:30, trail after it
    add_row(engine, "SAM", stop_moved_at=datetime(2026, 10, 15, 13, 30), **lp)  # arrow and trail on the same candle
    add_row(engine, "ARW", stop_moved_at=datetime(2026, 10, 14, 9, 30), **lp)  # an arrow (left the stop alone) came after the trail
    add_row(engine, "BDN", stop_basis="LP", stop_price=95.0, stop_moved_at=datetime(2026, 10, 16, 9, 30), stop_moved_by="blue_down")
    add_row(engine, "BRC", stop_moved_at=datetime(2026, 10, 16, 9, 30), status="breached", breached_at=datetime(2026, 10, 16, 11, 30), **lp)
    add_row(engine, "PCT", stop_basis="10%", stop_moved_at=datetime(2026, 10, 16, 9, 30), stop_moved_by="trail")
    add_row(engine, "OLD", stop_basis="LP", stop_price=95.0)  # not yet rebuilt: no stop age
    add_row(engine, "NON", stop_price=None, stop_basis="none", entry_kind="blue")
    rows = {r["ticker"]: r for r in TestClient(main.app).get("/api/technical-ideas/warren").json()["rows"]}
    assert {t: r["stop_trailed_since_arrow"] for t, r in rows.items()} == {
        "TRL": True, "SAM": True, "ARW": False, "BDN": False, "BRC": False, "PCT": False, "OLD": False, "NON": False,
    }


def test_get_exposes_the_gray_entry_kind_and_its_stop_age_rule(engine, utc_server):
    add_row(engine, "GRY", entry_kind="gray", latest_arrow_kind="gray_up", instruction_type=1, stop_moved_at=datetime(2026, 10, 15, 13, 30), stop_moved_by="gray_up_entry")
    response = TestClient(main.app).get("/api/technical-ideas/warren")
    assert response.status_code == 200
    (row,) = response.json()["rows"]
    assert (row["entry_kind"], row["stop_moved_by"], row["latest_arrow_color"], row["latest_arrow_direction"]) == ("gray", "gray_up_entry", "gray", "up")


def test_age_follows_the_nyse_calendar_holiday_and_early_close(engine):
    # Thanksgiving 2026-11-26 is closed; the Friday 11-27 closes at 13:00 (windows 09:30 and 11:30 only).
    add_row(engine, "AAA", latest_arrow_at=datetime(2026, 11, 25, 15, 30), last_signal_at=datetime(2026, 11, 25, 15, 30),
            as_of=datetime(2026, 11, 30, 9, 30))
    row = TestClient(main.app).get("/api/technical-ideas/warren").json()["rows"][0]
    assert row["age_bars"] == 3  # 11-27 09:30, 11-27 11:30, 11-30 09:30
    add_row(engine, "BBB", latest_arrow_at=datetime(2026, 11, 30, 9, 30), last_signal_at=datetime(2026, 11, 30, 9, 30), as_of=datetime(2026, 11, 30, 9, 30))
    assert [r["age_bars"] for r in TestClient(main.app).get("/api/technical-ideas/warren").json()["rows"]] == [3, 0]


def test_an_empty_table_returns_no_rows_and_no_as_of():
    assert TestClient(main.app).get("/api/technical-ideas/warren").json() == {"as_of": None, "rows": [], "anchor_headroom": None}


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


def add_daily_bars(engine, ticker, closes_by_age, now=None):
    """Cached 1d bars: {days_ago: close}, counted from `now` (default: the real clock). Dated well before the last completed session, so the provisional-bar rule never applies."""
    now = now or datetime.now()
    with Session(engine) as s:
        for days_ago, close in closes_by_age.items():
            s.add(SharedBarsCache(ticker=ticker, interval="1d", bar_time=datetime.combine(now.date() - timedelta(days=days_ago), dtime.min),
                                  open=close, high=close, low=close, close=close, volume=1000, fetched_at=now, source="fmp"))
        s.commit()


def test_last_price_pl_and_stop_distance_come_from_the_latest_cached_daily_close(engine):
    add_row(engine, "AAA", entry_price=100.0, stop_price=90.0)
    add_daily_bars(engine, "AAA", {9: 111.0, 8: 120.0})
    row = TestClient(main.app).get("/api/technical-ideas/warren").json()["rows"][0]
    assert row["last_price"] == 120.0
    assert row["last_price_date"] == (datetime.now().date() - timedelta(days=8)).isoformat()
    assert row["pl_pct"] == pytest.approx(0.20)  # (120 - 100) / 100
    assert row["stop_distance_pct"] == pytest.approx(0.25)  # (120 - 90) / 120


def test_stop_distance_is_negative_when_the_price_is_below_the_stop_and_pl_negative_below_entry(engine):
    add_row(engine, "AAA", entry_price=100.0, stop_price=90.0)
    add_daily_bars(engine, "AAA", {8: 80.0})
    row = TestClient(main.app).get("/api/technical-ideas/warren").json()["rows"][0]
    assert row["pl_pct"] == pytest.approx(-0.20)
    assert row["stop_distance_pct"] == pytest.approx(-0.125)  # (80 - 90) / 80


def test_no_cached_daily_bar_gives_null_price_fields(engine):
    add_row(engine, "AAA")
    row = TestClient(main.app).get("/api/technical-ideas/warren").json()["rows"][0]
    assert (row["last_price"], row["last_price_date"], row["pl_pct"], row["stop_distance_pct"]) == (None, None, None, None)
    assert row["entry_price"] == 100.0 and row["stop_price"] == 90.0  # the stored fields are unaffected


def test_a_row_without_an_entry_or_a_stop_has_null_pl_and_stop_distance(engine):
    add_row(engine, "AAA", entry_kind=None, entry_at=None, entry_price=None, stop_price=None, stop_basis="none")
    add_daily_bars(engine, "AAA", {8: 50.0})
    row = TestClient(main.app).get("/api/technical-ideas/warren").json()["rows"][0]
    assert row["last_price"] == 50.0
    assert (row["entry_at"], row["pl_pct"], row["stop_distance_pct"]) == (None, None, None)


def session_before_the_last_completed_one_days_ago(now):
    """How many days before `now` the trading day before the most recent COMPLETED session falls (the code's own calendar helper, so a
    bar placed there is never dropped as live or provisional, whatever the weekday). Always newer than the 8-days-ago bars these tests use."""
    completed = sbc._most_recent_completed_trading_date(now.replace(tzinfo=timezone.utc))
    day = completed - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    days_ago = (now.date() - day).days
    assert 1 <= days_ago < 8
    return days_ago


# The real clock, then fixed instants (UTC): a Wednesday midday, the Saturday and the Sunday of a weekend, a Monday morning before the open.
SIMULATED_NOWS = [
    pytest.param(None, id="real-clock"),
    pytest.param(datetime(2026, 10, 14, 12, 0), id="wednesday"),
    pytest.param(datetime(2026, 10, 17, 12, 0), id="saturday"),
    pytest.param(datetime(2026, 10, 18, 12, 0), id="sunday"),
    pytest.param(datetime(2026, 10, 12, 8, 0), id="monday-before-the-open"),
]


@pytest.mark.parametrize("simulated_now", SIMULATED_NOWS)
def test_a_breached_rows_pl_is_frozen_at_the_stop_and_ignores_the_last_price(engine, monkeypatch, simulated_now):
    now = simulated_now or datetime.now()
    if simulated_now is not None:  # the page reads the cache through this function; give it the simulated clock (no production change)
        real_read = wwd.read_cached_completed_daily_bars
        monkeypatch.setattr(wwd, "read_cached_completed_daily_bars", lambda t, n: real_read(t, n, reference=simulated_now.replace(tzinfo=timezone.utc)))
    add_row(engine, "AAA", status="breached", breached_at=datetime(2026, 10, 13, 9, 30), entry_price=100.0, stop_price=90.0)
    add_daily_bars(engine, "AAA", {8: 60.0}, now)
    client = TestClient(main.app)
    row = client.get("/api/technical-ideas/warren").json()["rows"][0]
    assert row["pl_pct"] == pytest.approx(-0.10)  # (90 - 100) / 100, not (60 - 100) / 100
    assert row["stop_distance_pct"] == pytest.approx(-0.50)  # (60 - 90) / 60: still follows the price
    add_daily_bars(engine, "AAA", {session_before_the_last_completed_one_days_ago(now): 150.0}, now)  # the price recovers (a bar on the previous session, never a weekend)
    row = client.get("/api/technical-ideas/warren").json()["rows"][0]
    assert row["last_price"] == 150.0 and row["pl_pct"] == pytest.approx(-0.10)
    assert row["stop_distance_pct"] == pytest.approx(0.40)  # (150 - 90) / 150


def test_a_breached_row_without_an_entry_or_a_stop_has_null_pl(engine):
    add_row(engine, "AAA", status="breached", breached_at=datetime(2026, 10, 13, 9, 30), entry_kind=None, entry_at=None, entry_price=None)
    add_row(engine, "BBB", status="breached", breached_at=datetime(2026, 10, 13, 9, 30), stop_price=None, stop_basis="none")
    add_daily_bars(engine, "AAA", {8: 80.0})
    add_daily_bars(engine, "BBB", {8: 80.0})
    a, b = TestClient(main.app).get("/api/technical-ideas/warren").json()["rows"]
    assert (a["pl_pct"], b["pl_pct"]) == (None, None)


def test_a_breached_row_that_returns_to_active_goes_back_to_the_last_price(monkeypatch, engine):
    canned(monkeypatch, {"A": [("yellow_up", "2026-09-01 09:30"), ("yellow_up", "2026-09-21 09:30")]})
    fake_lp(monkeypatch, [50.0, 40.0])
    add_daily_bars(engine, "A", {8: 120.0})
    client = TestClient(main.app)
    run("A", bars("2026-07-01", "2026-09-18", lows={"2026-09-10": 85.0}))
    row = client.get("/api/technical-ideas/warren").json()["rows"][0]
    assert row["status"] == "breached" and row["pl_pct"] == pytest.approx((89.1 - 100.0) / 100.0)
    run("A", bars("2026-07-01", "2026-10-16", lows={"2026-09-10": 85.0}))  # a fresh Yellow Up restarts the row
    row = client.get("/api/technical-ideas/warren").json()["rows"][0]
    assert row["status"] == "active" and row["pl_pct"] == pytest.approx(0.20)  # (120 - 100) / 100


def test_get_is_cache_only_and_writes_nothing(engine, monkeypatch):
    add_row(engine, "AAA")
    add_daily_bars(engine, "AAA", {8: 120.0})

    def dump():
        with Session(engine) as s:
            return ([r.model_dump() for r in s.exec(select(WarrenWatchRow)).all()], [r.model_dump() for r in s.exec(select(SharedBarsCache)).all()])

    from clients.fmp_client import fmp_client

    def no_http(*a, **k):
        raise AssertionError("the Technical Ideas GET must not call FMP")

    monkeypatch.setattr(fmp_client, "get", no_http)
    before = dump()
    assert TestClient(main.app).get("/api/technical-ideas/warren").status_code == 200
    assert dump() == before
