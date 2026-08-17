import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import core.cron_health as cron_health
from core.models import CronRunLog


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(cron_health, "engine", engine)
    return engine


def test_success_path_writes_running_then_success(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    with cron_health.cron_heartbeat("pipeline.prune_cache"):
        with Session(engine) as session:
            mid_run = session.exec(select(CronRunLog)).one()
            assert mid_run.status == "running"
            assert mid_run.finished_at is None

    with Session(engine) as session:
        row = session.exec(select(CronRunLog)).one()
    assert row.status == "success"
    assert row.finished_at is not None
    assert row.error_summary is None


def test_failure_path_reraises_and_records_failure(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    with pytest.raises(ValueError, match="boom"):
        with cron_health.cron_heartbeat("pipeline.backup_db"):
            raise ValueError("boom")

    with Session(engine) as session:
        row = session.exec(select(CronRunLog)).one()
    assert row.status == "failure"
    assert row.finished_at is not None
    assert row.error_summary is not None
    assert "boom" in row.error_summary


def test_error_summary_is_truncated(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    long_message = "x" * 1000

    with pytest.raises(RuntimeError):
        with cron_health.cron_heartbeat("pipeline.backup_db"):
            raise RuntimeError(long_message)

    with Session(engine) as session:
        row = session.exec(select(CronRunLog)).one()
    assert len(row.error_summary) <= 500


def test_error_summary_redacts_apikey(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    with pytest.raises(RuntimeError):
        with cron_health.cron_heartbeat("pipeline.backup_db"):
            raise RuntimeError("fetch failed: https://x/api?apikey=SUPERSECRET123&ticker=AAPL")

    with Session(engine) as session:
        row = session.exec(select(CronRunLog)).one()
    assert "SUPERSECRET123" not in row.error_summary
    assert "apikey=REDACTED" in row.error_summary


def test_heartbeat_write_failure_does_not_mask_the_real_exception(monkeypatch):
    """Simulates the exact scenario this system is built to catch (e.g.
    backup_db's disk-full failure): if the heartbeat's own DB write is
    broken, the job's real exception must still propagate unchanged, and a
    healthy job must still complete unchanged -- the heartbeat is never
    allowed to become a new point of failure."""

    class _ExplodingEngine:
        def connect(self, *args, **kwargs):
            raise OSError("disk is full")

    monkeypatch.setattr(cron_health, "engine", _ExplodingEngine())

    # The real exception still propagates, byte-for-byte, despite the
    # heartbeat itself being unable to write anything at all.
    with pytest.raises(ValueError, match="real job failure"):
        with cron_health.cron_heartbeat("pipeline.backup_db"):
            raise ValueError("real job failure")

    # A job that succeeds still completes normally even though the
    # heartbeat can't record it.
    ran = False
    with cron_health.cron_heartbeat("pipeline.backup_db"):
        ran = True
    assert ran is True


def test_heartbeat_still_writes_when_cron_health_reporting_is_disabled(monkeypatch):
    """CRON_HEALTH_ENABLED gates GET /api/config/cron-health's reporting
    only -- CronRunLog rows must keep being written regardless, so history
    isn't lost while the flag is off."""
    engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(cron_health.settings, "cron_health_enabled", False)

    with cron_health.cron_heartbeat("pipeline.prune_cache"):
        pass

    with Session(engine) as session:
        row = session.exec(select(CronRunLog)).one()
    assert row.status == "success"


def test_get_cron_health_reports_unknown_for_a_job_with_no_rows(monkeypatch):
    _fresh_engine(monkeypatch)

    health = cron_health.get_cron_health()

    statuses = {job.job_name: job.health_status for job in health.jobs}
    assert statuses["pipeline.prune_cache"] == "unknown"
    assert len(health.jobs) == len(cron_health.CRON_JOB_NAMES)
