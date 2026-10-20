"""pipeline.disk_space_check (2026-10-20): the low-disk early warning. Pure decision table, the "second night in a row" read of the job's
previous heartbeat row, and the real cron_heartbeat path against an in-memory engine (night 1 is a success whose message says so, night 2
or below the hard limit is a failure). Reads only: no network, nothing written but the heartbeat rows."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.cron_health as cron_health
import pipeline.disk_space_check as disk
from core.cron_health import cron_heartbeat
from core.models import CronRunLog

GB = 10**9


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(cron_health, "engine", eng)
    monkeypatch.setattr(disk, "configure_logging", lambda path: None)  # never write the real logs/disk_space_check.log
    return eng


def _run(monkeypatch, free_gb: float) -> None:
    """One real heartbeat-wrapped run at `free_gb` free, the way the __main__ block does it."""
    monkeypatch.setattr(disk, "free_bytes", lambda path: int(free_gb * GB))
    with cron_heartbeat("pipeline.disk_space_check") as run:
        run.message = disk.main()


def _rows(engine):
    with Session(engine) as session:
        return list(session.exec(select(CronRunLog).where(CronRunLog.job_name == "pipeline.disk_space_check").order_by(CronRunLog.id)))


def test_thresholds_are_3_5_and_2_0_gb():
    assert disk.WARN_FREE_BYTES == 3_500_000_000 and disk.HARD_FREE_BYTES == 2_000_000_000


@pytest.mark.parametrize(
    "free_gb, previous_low, level",
    [
        (6.5, False, "ok"),
        (3.5, False, "ok"),  # exactly the warn threshold is not below it
        (3.49, False, "warn"),
        (3.49, True, "red"),  # second night
        (2.0, False, "warn"),  # exactly the hard limit is not below it
        (1.99, False, "red"),  # hard, at once
        (1.99, True, "red"),
        (0.2, False, "red"),
    ],
)
def test_decision_table(free_gb, previous_low, level):
    assert disk.evaluate(int(free_gb * GB), previous_low)[0] == level


def test_every_message_states_the_free_gb_and_the_threshold():
    ok = disk.evaluate(int(6.5 * GB), False)[1]
    warn = disk.evaluate(int(3.1 * GB), False)[1]
    second = disk.evaluate(int(3.1 * GB), True)[1]
    hard = disk.evaluate(int(1.7 * GB), False)[1]
    assert "6.5 GB free" in ok and "3.5 GB" in ok and "2.0 GB" in ok
    assert "3.1 GB free" in warn and "3.5 GB warn threshold" in warn and "night 1 of 2" in warn and warn.startswith("Low disk")
    assert "3.1 GB free" in second and "second night in a row" in second and "3.5 GB warn threshold" in second
    assert "1.7 GB free" in hard and "2.0 GB hard limit" in hard
    assert "Low disk" not in ok  # the marker the next night's check reads appears only on low-space messages


def test_free_bytes_reads_a_real_volume():
    from pathlib import Path

    assert disk.free_bytes(Path("/")) > 0


def test_a_healthy_night_is_a_success_with_the_free_gb(engine, monkeypatch):
    _run(monkeypatch, 6.5)
    (row,) = _rows(engine)
    assert row.status == "success" and row.error_summary.startswith("6.5 GB free")


def test_one_night_in_warn_is_a_success_whose_message_says_so(engine, monkeypatch):
    _run(monkeypatch, 3.1)
    (row,) = _rows(engine)
    assert row.status == "success"
    assert row.error_summary.startswith("Low disk warning: 3.1 GB free") and "3.5 GB warn threshold" in row.error_summary


def test_a_second_night_in_warn_is_a_failure(engine, monkeypatch):
    _run(monkeypatch, 3.1)
    with pytest.raises(disk.LowDiskSpaceError):
        _run(monkeypatch, 3.0)
    first, second = _rows(engine)
    assert (first.status, second.status) == ("success", "failure")
    assert "second night in a row" in second.error_summary and "3.0 GB free" in second.error_summary


def test_below_the_hard_limit_is_a_failure_on_the_first_night(engine, monkeypatch):
    with pytest.raises(disk.LowDiskSpaceError):
        _run(monkeypatch, 1.6)
    (row,) = _rows(engine)
    assert row.status == "failure" and "1.6 GB free" in row.error_summary and "2.0 GB hard limit" in row.error_summary


def test_a_good_night_resets_the_streak(engine, monkeypatch):
    _run(monkeypatch, 3.1)
    _run(monkeypatch, 5.0)
    _run(monkeypatch, 3.1)  # night 1 again, not night 2
    assert [r.status for r in _rows(engine)] == ["success", "success", "success"]


def test_a_failed_hard_night_counts_as_the_night_before(engine, monkeypatch):
    with pytest.raises(disk.LowDiskSpaceError):
        _run(monkeypatch, 1.6)
    with pytest.raises(disk.LowDiskSpaceError):
        _run(monkeypatch, 3.2)  # recovering into warn, but yesterday was already low
    assert [r.status for r in _rows(engine)] == ["failure", "failure"]


def test_a_low_run_older_than_36_hours_does_not_count(engine, monkeypatch):
    with Session(engine) as session:
        session.add(
            CronRunLog(
                job_name="pipeline.disk_space_check",
                started_at=datetime.now() - timedelta(hours=40),
                finished_at=datetime.now() - timedelta(hours=40),
                status="success",
                error_summary="Low disk warning: 3.1 GB free, below the 3.5 GB warn threshold (night 1 of 2; hard limit 2.0 GB).",
            )
        )
        session.commit()
    _run(monkeypatch, 3.1)
    assert _rows(engine)[-1].status == "success"


def test_another_jobs_low_disk_text_is_ignored(engine, monkeypatch):
    with Session(engine) as session:
        session.add(
            CronRunLog(
                job_name="pipeline.backup_db",
                started_at=datetime.now() - timedelta(hours=24),
                finished_at=datetime.now() - timedelta(hours=24),
                status="failure",
                error_summary="Low disk: copied from somewhere else",
            )
        )
        session.commit()
    _run(monkeypatch, 3.1)
    assert _rows(engine)[-1].status == "success"


def test_the_job_reads_only(monkeypatch, engine):
    """No network, no table other than the heartbeat row is written: the CronRunLog row count grows by exactly one per run and nothing else
    in the database changes."""
    import inspect

    source = inspect.getsource(disk)
    assert "from clients" not in source and "import clients" not in source and "requests" not in source and "httpx" not in source
    assert "session.add" not in source.replace("db.exec", "")  # the job never adds a row itself
    before = len(_rows(engine))
    _run(monkeypatch, 6.0)
    assert len(_rows(engine)) == before + 1
