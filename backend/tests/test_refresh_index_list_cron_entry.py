"""Regression tests for the 2026-09-11 fix: refresh_dow_list.py/
refresh_sp500_list.py's main() must raise when the underlying scrape
returns a failed SyncResult, so cron_heartbeat (which only distinguishes
success/failure by whether an exception escapes the `with` block) actually
records a "failure" CronRunLog row instead of a false "success" -- the
confirmed root cause of the Dow constituent list silently going stale for
weeks while GET /api/config/cron-health kept reporting it as healthy."""

import asyncio

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import core.cron_health as cron_health
import scrapers.refresh_dow_list as refresh_dow_list
import scrapers.refresh_sp500_list as refresh_sp500_list
from core.models import CronRunLog
from scrapers.index_scraper import SyncResult


def _fresh_engine(monkeypatch, *modules):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for module in modules:
        monkeypatch.setattr(module, "engine", engine)
    return engine


@pytest.mark.parametrize(
    "module, refresh_attr, job_name",
    [
        (refresh_dow_list, "refresh_dow_constituents", "scrapers.refresh_dow_list"),
        (refresh_sp500_list, "refresh_sp500_constituents", "scrapers.refresh_sp500_list"),
    ],
)
def test_main_raises_when_sync_result_is_failure(monkeypatch, module, refresh_attr, job_name):
    _fresh_engine(monkeypatch, module)

    async def fake_refresh(session):
        return SyncResult(success=False, constituent_count=0, error="parsed only 3 rows, expected at least 28")

    monkeypatch.setattr(module, refresh_attr, fake_refresh)

    with pytest.raises(RuntimeError, match="parsed only 3 rows"):
        asyncio.run(module.main())


@pytest.mark.parametrize(
    "module, refresh_attr, job_name",
    [
        (refresh_dow_list, "refresh_dow_constituents", "scrapers.refresh_dow_list"),
        (refresh_sp500_list, "refresh_sp500_constituents", "scrapers.refresh_sp500_list"),
    ],
)
def test_cron_heartbeat_records_failure_when_sync_result_is_failure(monkeypatch, module, refresh_attr, job_name):
    _fresh_engine(monkeypatch, module)
    cron_engine = _fresh_engine(monkeypatch, cron_health)

    async def fake_refresh(session):
        return SyncResult(success=False, constituent_count=0, error="Could not find the constituents table")

    monkeypatch.setattr(module, refresh_attr, fake_refresh)

    with pytest.raises(RuntimeError):
        with cron_health.cron_heartbeat(job_name):
            asyncio.run(module.main())

    with Session(cron_engine) as session:
        row = session.exec(select(CronRunLog).where(CronRunLog.job_name == job_name)).one()
    assert row.status == "failure"
    assert row.error_summary is not None and "constituents table" in row.error_summary


@pytest.mark.parametrize(
    "module, refresh_attr, job_name",
    [
        (refresh_dow_list, "refresh_dow_constituents", "scrapers.refresh_dow_list"),
        (refresh_sp500_list, "refresh_sp500_constituents", "scrapers.refresh_sp500_list"),
    ],
)
def test_cron_heartbeat_records_success_when_sync_result_is_success(monkeypatch, module, refresh_attr, job_name):
    """Confirms the fix doesn't change behavior for a normal successful run."""
    _fresh_engine(monkeypatch, module)
    cron_engine = _fresh_engine(monkeypatch, cron_health)

    async def fake_refresh(session):
        return SyncResult(success=True, constituent_count=30, error=None)

    monkeypatch.setattr(module, refresh_attr, fake_refresh)

    with cron_health.cron_heartbeat(job_name):
        asyncio.run(module.main())  # must not raise

    with Session(cron_engine) as session:
        row = session.exec(select(CronRunLog).where(CronRunLog.job_name == job_name)).one()
    assert row.status == "success"
