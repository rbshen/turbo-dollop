from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.cron_health as cron_health
from core.main import app
from core.models import CronRunLog


def _fresh_engine(monkeypatch):
    # StaticPool, not the default per-thread pool -- TestClient runs sync
    # endpoint functions in a worker thread, and a bare `sqlite://` engine
    # would hand that thread its own separate (empty) in-memory database
    # otherwise. Matches the existing convention in test_ticker_score_endpoint.py.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(cron_health, "engine", engine)
    return engine


def _job(response_json, job_name):
    (job,) = [j for j in response_json["jobs"] if j["job_name"] == job_name]
    return job


def test_cron_health_returns_all_known_jobs(monkeypatch):
    _fresh_engine(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/config/cron-health")
    assert response.status_code == 200
    body = response.json()
    assert {j["job_name"] for j in body["jobs"]} == set(cron_health.CRON_JOB_NAMES)


def test_job_with_no_rows_is_unknown(monkeypatch):
    _fresh_engine(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/config/cron-health")
    job = _job(response.json(), "pipeline.prune_cache")
    assert job["health_status"] == "unknown"
    assert job["last_run"] is None


def test_recent_success_is_ok(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            CronRunLog(
                job_name="pipeline.prune_cache",
                started_at=datetime.now() - timedelta(days=1),
                finished_at=datetime.now() - timedelta(days=1),
                status="success",
            )
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get("/api/config/cron-health")
    job = _job(response.json(), "pipeline.prune_cache")
    assert job["health_status"] == "ok"


def test_stale_success_is_overdue(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    # pipeline.prune_cache is a weekly job (~8 day cadence window) -- a
    # success 20 days ago is well past that.
    with Session(engine) as session:
        session.add(
            CronRunLog(
                job_name="pipeline.prune_cache",
                started_at=datetime.now() - timedelta(days=20),
                finished_at=datetime.now() - timedelta(days=20),
                status="success",
            )
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get("/api/config/cron-health")
    job = _job(response.json(), "pipeline.prune_cache")
    assert job["health_status"] == "overdue"
    assert job["message"] is not None


def test_most_recent_failure_is_failed_even_with_older_success(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            CronRunLog(
                job_name="pipeline.backup_db",
                started_at=datetime.now() - timedelta(days=1),
                finished_at=datetime.now() - timedelta(days=1),
                status="success",
            )
        )
        session.add(
            CronRunLog(
                job_name="pipeline.backup_db",
                started_at=datetime.now(),
                finished_at=datetime.now(),
                status="failure",
                error_summary="OperationalError: database or disk is full",
            )
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get("/api/config/cron-health")
    job = _job(response.json(), "pipeline.backup_db")
    assert job["health_status"] == "failed"
    assert job["message"] == "OperationalError: database or disk is full"


def test_stuck_running_job_with_no_success_is_overdue(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            CronRunLog(
                job_name="pipeline.backup_db",
                started_at=datetime.now() - timedelta(days=5),
                status="running",
            )
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get("/api/config/cron-health")
    job = _job(response.json(), "pipeline.backup_db")
    assert job["health_status"] == "overdue"
    assert "may be stuck" in job["message"]
