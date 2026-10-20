"""CronJobHealthOut.last_failure (2026-10-20): the Scheduled Jobs page showed only each job's latest run, so Monday's backup success hid
Sunday's InsufficientDiskSpaceError. The field is display only: it must never change health_status, message, last_run, last_success_at or the
overdue rule, and it is empty for a job with no failure in the last 14 days."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.cron_health as cron_health
from core.main import app
from core.models import CronRunLog

DISK_FULL = "InsufficientDiskSpaceError: Refusing to start backup: 1.58 GB free on the volume holding /home/shen/fathom/backend/backups"


def _engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(cron_health, "engine", engine)
    return engine


def _add(engine, job, days_ago, status, summary=None, hours_ago=0.0):
    when = datetime.now() - timedelta(days=days_ago, hours=hours_ago)
    with Session(engine) as session:
        session.add(CronRunLog(job_name=job, started_at=when, finished_at=when, status=status, error_summary=summary))
        session.commit()
    return when


def _get(job_name):
    with TestClient(app) as client:
        body = client.get("/api/config/cron-health").json()
    (job,) = [j for j in body["jobs"] if j["job_name"] == job_name]
    return job


def test_a_success_after_a_failure_still_shows_the_failure_and_stays_ok(monkeypatch):
    engine = _engine(monkeypatch)
    failed_at = _add(engine, "pipeline.backup_db", 2, "failure", DISK_FULL)
    _add(engine, "pipeline.backup_db", 1, "success", "158.1 MB, 1 old backup(s) pruned")
    _add(engine, "pipeline.backup_db", 0.0, "success", "158.2 MB, 1 old backup(s) pruned")

    job = _get("pipeline.backup_db")

    assert job["health_status"] == "ok"
    assert job["message"] == "158.2 MB, 1 old backup(s) pruned"  # the success message, untouched
    assert job["last_failure"]["status"] == "failure"
    assert job["last_failure"]["error_summary"] == DISK_FULL
    assert job["last_failure"]["started_at"].startswith(failed_at.isoformat()[:19])


def test_the_most_recent_of_several_failures_is_the_one_shown(monkeypatch):
    engine = _engine(monkeypatch)
    _add(engine, "pipeline.backup_db", 9, "failure", "RuntimeError: old")
    _add(engine, "pipeline.backup_db", 3, "failure", "RuntimeError: newer")
    _add(engine, "pipeline.backup_db", 1, "success")

    assert _get("pipeline.backup_db")["last_failure"]["error_summary"] == "RuntimeError: newer"


def test_a_job_with_no_failure_shows_nothing_extra(monkeypatch):
    engine = _engine(monkeypatch)
    _add(engine, "pipeline.backup_db", 1, "success", "158.1 MB, 0 old backup(s) pruned")

    job = _get("pipeline.backup_db")

    assert job["last_failure"] is None
    assert job["health_status"] == "ok"


def test_a_job_with_no_runs_has_no_last_failure(monkeypatch):
    _engine(monkeypatch)
    job = _get("pipeline.prune_cache")
    assert job["health_status"] == "unknown" and job["last_failure"] is None


def test_the_window_is_14_days(monkeypatch):
    engine = _engine(monkeypatch)
    _add(engine, "pipeline.backup_db", 13, "failure", "RuntimeError: inside", hours_ago=20)  # 13 days 20 h ago
    _add(engine, "pipeline.prune_cache", 14, "failure", "RuntimeError: outside", hours_ago=2)  # 14 days 2 h ago
    assert cron_health.LAST_FAILURE_WINDOW_DAYS == 14

    assert _get("pipeline.backup_db")["last_failure"]["error_summary"] == "RuntimeError: inside"
    assert _get("pipeline.prune_cache")["last_failure"] is None


def test_a_job_whose_latest_run_is_the_failure_reports_the_same_run_in_both_places(monkeypatch):
    engine = _engine(monkeypatch)
    _add(engine, "pipeline.backup_db", 1, "success")
    _add(engine, "pipeline.backup_db", 0.0, "failure", DISK_FULL)

    job = _get("pipeline.backup_db")

    assert job["health_status"] == "failed" and job["message"] == DISK_FULL
    assert job["last_failure"]["started_at"] == job["last_run"]["started_at"]


def test_only_failures_count_not_skipped_or_running_rows(monkeypatch):
    engine = _engine(monkeypatch)
    _add(engine, "pipeline.backup_db", 2, "skipped", "group off")
    _add(engine, "pipeline.backup_db", 1, "running")
    _add(engine, "pipeline.backup_db", 0.5, "success")

    assert _get("pipeline.backup_db")["last_failure"] is None


def test_each_job_gets_its_own_failure_and_other_jobs_are_unaffected(monkeypatch):
    engine = _engine(monkeypatch)
    _add(engine, "pipeline.backup_db", 2, "failure", "RuntimeError: backup")
    _add(engine, "pipeline.prune_cache", 1, "failure", "RuntimeError: prune")
    _add(engine, "pipeline.rotate_logs", 1, "success")

    assert _get("pipeline.backup_db")["last_failure"]["error_summary"] == "RuntimeError: backup"
    assert _get("pipeline.prune_cache")["last_failure"]["error_summary"] == "RuntimeError: prune"
    assert _get("pipeline.rotate_logs")["last_failure"] is None


def test_the_status_logic_is_identical_with_and_without_the_extra_failure_rows(monkeypatch):
    """The same success history, with and without an old failure beside it: every field other than last_failure is equal, for an ok job and
    for an overdue one (a stale success must still read overdue; the remembered failure must not turn it ok or failed)."""
    engine = _engine(monkeypatch)
    _add(engine, "pipeline.backup_db", 0.5, "success", "158 MB")  # ok
    _add(engine, "pipeline.prune_cache", 9, "success")  # weekly job (8-day window), 9 days stale -> overdue
    before = {n: _get(n) for n in ("pipeline.backup_db", "pipeline.prune_cache")}

    _add(engine, "pipeline.backup_db", 5, "failure", "RuntimeError: x")
    _add(engine, "pipeline.prune_cache", 12, "failure", "RuntimeError: y")  # older than the latest run, inside 14 days
    after = {n: _get(n) for n in ("pipeline.backup_db", "pipeline.prune_cache")}

    for name in before:
        b, a = dict(before[name]), dict(after[name])
        assert b.pop("last_failure") is None and a.pop("last_failure") is not None
        assert a == b, name
    assert after["pipeline.backup_db"]["health_status"] == "ok"
    assert after["pipeline.prune_cache"]["health_status"] == "overdue"


def test_the_disabled_list_is_unaffected(monkeypatch):
    engine = _engine(monkeypatch)
    monkeypatch.setattr(cron_health, "DISABLED_CRON_JOBS", {"pipeline.prune_cache": cron_health.DisabledJob(datetime.now().date(), "test")})
    _add(engine, "pipeline.prune_cache", 3, "failure", "RuntimeError: before disabling")

    job = _get("pipeline.prune_cache")

    assert job["health_status"] == "skipped" and job["message"].startswith("Disabled since")
    assert job["last_failure"]["error_summary"] == "RuntimeError: before disabling"


def test_the_job_never_writes_to_the_log_table(monkeypatch):
    engine = _engine(monkeypatch)
    _add(engine, "pipeline.backup_db", 2, "failure", "RuntimeError: x")
    with Session(engine) as session:
        before = len(session.exec(CronRunLog.__table__.select()).all())
    _get("pipeline.backup_db")
    with Session(engine) as session:
        assert len(session.exec(CronRunLog.__table__.select()).all()) == before
