"""Real "skipped" cron status: a job that intentionally no-ops (its data group
is off) must not read as a healthy green success, however long it stays off."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.cron_health as cron_health
from core.cron_health import cron_heartbeat
from core.main import app
from core.models import CronRunLog

JOB = "pipeline.nightly_fundamentals_fetch"


def _engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(cron_health, "engine", engine)
    return engine


def _add(engine, status, when, msg=None):
    with Session(engine) as s:
        s.add(CronRunLog(job_name=JOB, started_at=when, finished_at=when, status=status, error_summary=msg))
        s.commit()


def _health(monkeypatch_engine=None):
    with TestClient(app) as client:
        jobs = client.get("/api/config/cron-health").json()["jobs"]
    return next(j for j in jobs if j["job_name"] == JOB)


def test_heartbeat_records_skipped_status_and_reason(monkeypatch):
    engine = _engine(monkeypatch)
    with cron_heartbeat(JOB) as run:
        run.skip("skipped (group fundamentals disabled)")
    with Session(engine) as s:
        row = s.exec(select(CronRunLog)).one()
    assert row.status == "skipped"
    assert row.error_summary == "skipped (group fundamentals disabled)"


def test_a_normal_run_is_still_success(monkeypatch):
    engine = _engine(monkeypatch)
    with cron_heartbeat(JOB) as run:
        run.message = "ok"
    with Session(engine) as s:
        assert s.exec(select(CronRunLog)).one().status == "success"


def test_skipped_run_is_never_counted_as_a_success_for_ok_health(monkeypatch):
    engine = _engine(monkeypatch)
    _add(engine, "skipped", datetime.now() - timedelta(hours=2), "skipped (group fundamentals disabled)")
    job = _health()
    assert job["health_status"] == "skipped"
    assert job["last_success_at"] is None  # a skip is not a success


def test_skipped_since_is_the_start_of_the_current_streak(monkeypatch):
    engine = _engine(monkeypatch)
    now = datetime.now()
    _add(engine, "success", now - timedelta(days=40))
    _add(engine, "skipped", now - timedelta(days=30), "skipped (x)")
    _add(engine, "skipped", now - timedelta(days=2), "skipped (x)")
    _add(engine, "skipped", now - timedelta(hours=1), "skipped (x)")
    job = _health()
    assert job["health_status"] == "skipped"  # 40 days on, still not "ok"/"overdue"
    since = datetime.fromisoformat(job["skipped_since"])
    assert abs(since - (now - timedelta(days=30))) < timedelta(seconds=5)
    assert (now - timedelta(days=30)).date().isoformat() in job["message"]
    # last real success stays visible
    assert job["last_success_at"] is not None


def test_streak_restarts_after_a_real_run(monkeypatch):
    engine = _engine(monkeypatch)
    now = datetime.now()
    _add(engine, "skipped", now - timedelta(days=9), "skipped (x)")
    _add(engine, "success", now - timedelta(days=5))
    _add(engine, "skipped", now - timedelta(days=1), "skipped (x)")
    job = _health()
    since = datetime.fromisoformat(job["skipped_since"])
    assert abs(since - (now - timedelta(days=1))) < timedelta(seconds=5)


def test_recovered_job_goes_back_to_ok(monkeypatch):
    engine = _engine(monkeypatch)
    now = datetime.now()
    _add(engine, "skipped", now - timedelta(days=3), "skipped (x)")
    _add(engine, "success", now - timedelta(hours=1))
    job = _health()
    assert job["health_status"] == "ok"
    assert job["skipped_since"] is None


@pytest.mark.parametrize(
    "module,attr",
    [("pipeline.nightly_fundamentals_fetch", "cron_heartbeat"), ("pipeline.monthly_price_target_snapshot", "cron_heartbeat")],
)
def test_guarded_jobs_report_skip_through_run_skip(module, attr):
    """The jobs call run.skip(...) (not run.message) on a gated no-op."""
    import importlib
    import inspect

    src = inspect.getsource(importlib.import_module(module))
    assert "run.skip(" in src
