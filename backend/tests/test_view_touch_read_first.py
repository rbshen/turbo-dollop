"""The ticker "touch" (data/tracked_universe.py::touch_existing_ticker_view / record_ticker_view) is read-first:
the common case, a row already on today's date, issues only a SELECT, so no write transaction opens (SQLite takes
the write lock for an UPDATE even when it matches no row, which is what produced "database is locked" on 2026-10-03).
A lock or any other error is logged and swallowed. Also pins the busy timeout of the one writing engine."""

import logging
import sqlite3
import threading
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

import core.db as db
from conftest import real_engine as _real_core_engine  # core.db.engine itself is isolated per test (conftest._isolate_core_db_engine)
import core.main as main
import data.tracked_universe as tu
from core.models import TickerView

TODAY_NOON = datetime(2026, 11, 15, 12, 0)
YESTERDAY = datetime(2026, 11, 14, 18, 30)
WRITES = ("INSERT", "UPDATE", "DELETE", "REPLACE")


@pytest.fixture
def engine(tmp_path, monkeypatch):
    eng = create_engine(
        f"sqlite:///{tmp_path / 'views.db'}", connect_args={"check_same_thread": False, "timeout": 0.2}
    )
    SQLModel.metadata.create_all(eng)
    for module in (tu, db, main):
        monkeypatch.setattr(module, "engine", eng)
    return eng


@pytest.fixture
def statements(engine):
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement.lstrip())

    event.listen(engine, "before_cursor_execute", record)
    yield seen
    event.remove(engine, "before_cursor_execute", record)


def _writes(seen):
    return [s for s in seen if s.upper().startswith(WRITES)]


def _seed(engine, ticker, viewed, added_at=None, added_source=None):
    with Session(engine) as session:
        session.add(TickerView(ticker=ticker, last_viewed_at=viewed, added_at=added_at, added_source=added_source))
        session.commit()


def _row(engine, ticker):
    with Session(engine) as session:
        return session.get(TickerView, ticker)


@pytest.mark.parametrize("func", [tu.touch_existing_ticker_view, tu.record_ticker_view])
def test_a_row_already_touched_today_issues_no_write_statement(engine, statements, func):
    _seed(engine, "AAPL", datetime(2026, 11, 15, 0, 5))
    statements.clear()

    assert func("aapl", now=TODAY_NOON) is False

    assert statements and _writes(statements) == []  # one SELECT, nothing else
    assert _row(engine, "AAPL").last_viewed_at == datetime(2026, 11, 15, 0, 5)


@pytest.mark.parametrize("func", [tu.touch_existing_ticker_view, tu.record_ticker_view])
def test_a_row_from_yesterday_gets_exactly_one_update_of_last_viewed_at(engine, statements, func):
    _seed(engine, "AAPL", YESTERDAY, added_at=datetime(2026, 10, 3, 8, 33), added_source="grandfathered")
    statements.clear()

    assert func("AAPL", now=TODAY_NOON) is True

    writes = _writes(statements)
    assert len(writes) == 1 and writes[0].upper().startswith("UPDATE")
    assert "added_at" not in writes[0] and "added_source" not in writes[0]
    row = _row(engine, "AAPL")
    assert row.last_viewed_at == TODAY_NOON
    assert (row.added_at, row.added_source) == (datetime(2026, 10, 3, 8, 33), "grandfathered")


def test_the_day_boundary_uses_the_naive_local_calendar_date(engine, statements):
    _seed(engine, "AAPL", datetime(2026, 11, 15, 0, 0, 0))  # exactly midnight is already "today"
    statements.clear()
    assert tu.touch_existing_ticker_view("AAPL", now=datetime(2026, 11, 15, 23, 59)) is False
    assert _writes(statements) == []
    assert tu.touch_existing_ticker_view("AAPL", now=datetime(2026, 11, 16, 0, 1)) is True  # 00:01 next day: due again
    assert _row(engine, "AAPL").last_viewed_at == datetime(2026, 11, 16, 0, 1)
    assert tu.touch_existing_ticker_view("AAPL", now=datetime(2026, 11, 16, 23, 59)) is False  # same new day: no write


def test_no_row_the_touch_does_nothing_and_record_inserts_once(engine, statements):
    assert tu.touch_existing_ticker_view("NEW", now=TODAY_NOON) is False
    assert _writes(statements) == [] and _row(engine, "NEW") is None

    assert tu.record_ticker_view("new", now=TODAY_NOON) is True
    writes = _writes(statements)
    assert len(writes) == 1 and writes[0].upper().startswith("INSERT")
    assert _row(engine, "NEW").last_viewed_at == TODAY_NOON

    statements.clear()
    assert tu.record_ticker_view("NEW", now=TODAY_NOON + timedelta(hours=3)) is False  # now a read-only no-op
    assert _writes(statements) == []


def test_two_first_views_racing_do_not_collide(engine):
    # The row appears between the SELECT and the INSERT: the conflict-safe upsert must absorb it.
    real = tu._last_viewed_at

    def stale_read(session, ticker):
        value = real(session, ticker)
        _seed(engine, ticker, TODAY_NOON)  # the "other request" inserts after our read saw no row
        return value

    tu._last_viewed_at = stale_read
    try:
        assert tu.record_ticker_view("RACE", now=TODAY_NOON) is False  # conflict, and the stored day is today: untouched
    finally:
        tu._last_viewed_at = real
    with Session(engine) as session:
        assert len(session.exec(select(TickerView)).all()) == 1


def test_an_error_in_the_select_is_swallowed_and_logged(engine, monkeypatch, caplog):
    def boom(session, ticker):
        raise OperationalError("SELECT", {}, sqlite3.OperationalError("database is locked"))

    monkeypatch.setattr(tu, "_last_viewed_at", boom)
    with caplog.at_level(logging.WARNING, logger=tu.logger.name):
        assert tu.touch_existing_ticker_view("AAPL", now=TODAY_NOON) is False
        assert tu.record_ticker_view("AAPL", now=TODAY_NOON) is False
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "touch_existing_ticker_view failed for AAPL" in messages and "record_ticker_view failed for AAPL" in messages
    assert "database is locked" in messages


@pytest.mark.parametrize("func", [tu.touch_existing_ticker_view, tu.record_ticker_view])
def test_a_locked_database_on_the_update_is_swallowed_logged_and_leaves_the_row_alone(engine, caplog, func):
    _seed(engine, "AAPL", YESTERDAY)
    holder = sqlite3.connect(engine.url.database, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")  # another writer holds the write lock for the whole call
    try:
        with caplog.at_level(logging.WARNING, logger=tu.logger.name):
            assert func("AAPL", now=TODAY_NOON) is False  # the SELECT passes, the UPDATE times out after 0.2 s
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert "database is locked" in " ".join(r.getMessage() for r in caplog.records)
    assert _row(engine, "AAPL").last_viewed_at == YESTERDAY  # still the earlier date, and the next call can retry
    assert func("AAPL", now=TODAY_NOON) is True


def test_an_already_touched_ticker_is_not_blocked_by_another_writer(engine):
    _seed(engine, "AAPL", TODAY_NOON)
    holder = sqlite3.connect(engine.url.database, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        started = datetime.now()
        assert tu.touch_existing_ticker_view("AAPL", now=TODAY_NOON) is False
        assert tu.record_ticker_view("AAPL", now=TODAY_NOON) is False
        assert (datetime.now() - started).total_seconds() < 0.15  # no write attempt, so no lock wait
    finally:
        holder.execute("ROLLBACK")
        holder.close()


def test_the_summary_route_on_a_ticker_touched_today_issues_no_tickerview_write(engine, statements, monkeypatch):
    from core.schemas import TickerSummaryOut

    async def ok(ticker):
        return TickerSummaryOut(company_name="Apple", ticker=ticker)

    monkeypatch.setattr(main, "get_summary", ok)
    _seed(engine, "AAPL", datetime.now())
    with TestClient(main.app) as client:  # the lifespan's init_db runs here, before the counted request
        statements.clear()
        assert client.get("/api/tickers/AAPL/summary").status_code == 200
    assert [s for s in _writes(statements) if "tickerview" in s.lower()] == []


def test_the_summary_route_on_a_ticker_from_yesterday_writes_the_view_exactly_once(engine, statements, monkeypatch):
    from core.schemas import TickerSummaryOut

    async def ok(ticker):
        return TickerSummaryOut(company_name="Apple", ticker=ticker)

    monkeypatch.setattr(main, "get_summary", ok)
    _seed(engine, "AAPL", datetime.now() - timedelta(days=1, minutes=1))
    with TestClient(main.app) as client:
        statements.clear()
        assert client.get("/api/tickers/AAPL/summary").status_code == 200
    assert len([s for s in _writes(statements) if "tickerview" in s.lower()]) == 1  # the touch; record then reads today


# --- the busy timeout of the one engine that writes ----------------------------------------------------------------


def test_the_real_engine_waits_the_named_constant_for_a_lock():
    assert db.SQLITE_BUSY_TIMEOUT_SECONDS == 15
    raw = _real_core_engine.raw_connection()  # a pure read of the connection setting; the write guard allows it
    try:
        assert raw.execute("PRAGMA busy_timeout").fetchone()[0] == db.SQLITE_BUSY_TIMEOUT_SECONDS * 1000
    finally:
        raw.close()


def test_the_only_engines_the_app_builds_for_writing_use_the_constant():
    """core.db.engine is the single writing engine (every module imports it); the two other create_engine calls
    open mode=ro and the backup job's raw connections copy the file (see backend/OPS_RUNBOOK.md, "Database locking")."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        if any(part in {".venv", "tests", "scripts", "node_modules"} for part in path.parts):
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"\bcreate_engine\(", line) and "mode=ro" not in line and path.name != "db.py":
                offenders.append(f"{path.relative_to(root)}:{number}")
    assert offenders == []
    assert "SQLITE_BUSY_TIMEOUT_SECONDS" in (root / "core" / "db.py").read_text()
