import asyncio
from datetime import date, datetime

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine

import data.last_close_data as lc
import pipeline.nightly_last_close_snapshot as job
from core.models import TickerLastClose

SESSION = date(2026, 9, 25)  # a Friday


@pytest.fixture
def engine(monkeypatch):
    e = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(e)
    monkeypatch.setattr(lc, "engine", e)
    return e


def _rows(*pairs):
    """FMP-shaped rows, newest first."""
    return [{"date": d, "open": c, "high": c, "low": c, "close": c, "volume": 10} for d, c in pairs]


def test_pick_last_close_takes_the_newest_bar_on_or_before_the_completed_session():
    rows = _rows(("2026-09-26", 999.0), ("2026-09-25", 101.5), ("2026-09-24", 100.0))  # Saturday bar is partial/bogus
    assert lc.pick_last_close(rows, SESSION) == (101.5, SESSION)


def test_pick_last_close_ignores_a_bar_after_the_session_and_junk():
    assert lc.pick_last_close(_rows(("2026-09-28", 5.0)), SESSION) is None
    assert lc.pick_last_close([], SESSION) is None
    assert lc.pick_last_close({"Error Message": "x"}, SESSION) is None
    assert lc.pick_last_close(_rows(("2026-09-25", 0.0)), SESSION) is None  # a zero close is not a price


def test_refresh_writes_upserts_and_reports_failures(monkeypatch, engine):
    async def fake(ticker, start, end, group="daily_prices"):
        if ticker == "BAD":
            raise httpx.ConnectError("boom")
        if ticker == "EMPTY":
            return []
        return _rows(("2026-09-25", 50.0 if ticker == "AAA" else 60.0))

    monkeypatch.setattr(lc.fmp_client, "get_historical_price_eod", fake)

    out = asyncio.run(lc.refresh_last_closes(["AAA", "BBB", "BAD", "EMPTY"], completed_session=SESSION))

    assert (out["processed"], out["written"], out["failed"]) == (4, 2, 2)
    assert dict(out["failures"]) == {"BAD": "ConnectError", "EMPTY": "no usable bar"}
    assert lc.get_cached_last_close("AAA") == (50.0, SESSION) and lc.get_cached_last_close("BAD") is None

    # A later run overwrites in place (latest-only) and a failed ticker keeps its old close.
    async def fake2(ticker, start, end, group="daily_prices"):
        if ticker == "AAA":
            return _rows(("2026-09-25", 51.0))
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(lc.fmp_client, "get_historical_price_eod", fake2)
    asyncio.run(lc.refresh_last_closes(["AAA", "BBB"], completed_session=SESSION))
    assert lc.get_cached_last_close("AAA")[0] == 51.0 and lc.get_cached_last_close("BBB")[0] == 60.0
    with Session(engine) as session:
        assert len(session.exec(__import__("sqlmodel").select(TickerLastClose)).all()) == 2


def test_the_job_is_skipped_while_daily_prices_is_off(monkeypatch, tmp_path):
    import core.data_groups as dg

    monkeypatch.setattr(job, "LOG_PATH", tmp_path / "x.log")
    monkeypatch.setattr(job, "init_db", lambda: None)
    dg.set_group_enabled("daily_prices", False)
    called = []

    async def boom(tickers):
        called.append(tickers)

    monkeypatch.setattr(job, "refresh_last_closes", boom)

    result = asyncio.run(job.main(["AAPL"]))

    assert result["skipped"] is True and called == []


def test_record_outcome_success_skipped_and_all_failed():
    class Run:
        message = None
        skipped = None

        def skip(self, reason):
            self.skipped = reason

    run = Run()
    job.record_outcome({"skipped": True, "skip_reason": "skipped (x)"}, run)
    assert run.skipped == "skipped (x)"
    run = Run()
    job.record_outcome({"processed": 3, "written": 2, "failed": 1}, run)
    assert run.message == "2 written, 1 failed"
    with pytest.raises(RuntimeError):
        job.record_outcome({"processed": 3, "written": 0, "failed": 3}, Run())
