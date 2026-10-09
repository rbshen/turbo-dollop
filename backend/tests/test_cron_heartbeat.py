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


def test_success_path_stores_run_context_message(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    with cron_health.cron_heartbeat("pipeline.prune_cache") as run:
        run.message = "12 row(s) deleted"

    with Session(engine) as session:
        row = session.exec(select(CronRunLog)).one()
    assert row.status == "success"
    assert row.error_summary == "12 row(s) deleted"


def test_success_path_with_no_message_set_leaves_error_summary_none(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    with cron_health.cron_heartbeat("pipeline.prune_cache"):
        pass

    with Session(engine) as session:
        row = session.exec(select(CronRunLog)).one()
    assert row.status == "success"
    assert row.error_summary is None


def test_failure_path_overwrites_any_message_already_set(monkeypatch):
    """A script that sets run.message and then goes on to raise must not
    have that message linger in error_summary -- the exception summary is
    always what gets recorded on a failure exit."""
    engine = _fresh_engine(monkeypatch)

    with pytest.raises(ValueError, match="boom"):
        with cron_health.cron_heartbeat("pipeline.prune_cache") as run:
            run.message = "this should never be stored"
            raise ValueError("boom")

    with Session(engine) as session:
        row = session.exec(select(CronRunLog)).one()
    assert row.status == "failure"
    assert row.error_summary is not None
    assert "boom" in row.error_summary
    assert "this should never be stored" not in row.error_summary


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


# ---------------------------------------------------------------------------
# Interrupted runs (2026-10-09): BaseException, SystemExit, SIGTERM
# ---------------------------------------------------------------------------

import logging
import os
import signal
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _only_row(engine) -> CronRunLog:
    with Session(engine) as session:
        return session.exec(select(CronRunLog)).one()


@pytest.fixture
def default_sigterm():
    """SIGTERM at its default action for the test, whatever the runner had, and restored afterwards."""
    saved = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, saved)


def test_keyboard_interrupt_writes_failure_row_and_reraises(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    with pytest.raises(KeyboardInterrupt):
        with cron_health.cron_heartbeat("pipeline.nightly_market_breadth") as run:
            run.message = "must not be stored"
            raise KeyboardInterrupt()

    row = _only_row(engine)
    assert row.status == "failure"
    assert row.finished_at is not None
    assert row.error_summary == "interrupted: KeyboardInterrupt"


@pytest.mark.parametrize("code", [0, None])
def test_clean_system_exit_stays_success_and_reraises(monkeypatch, code):
    engine = _fresh_engine(monkeypatch)

    with pytest.raises(SystemExit) as info:
        with cron_health.cron_heartbeat("pipeline.prune_cache") as run:
            run.message = "done"
            raise SystemExit(code)

    assert info.value.code == code
    row = _only_row(engine)
    assert row.status == "success"
    assert row.error_summary == "done"
    assert row.finished_at is not None


def test_clean_system_exit_after_skip_stays_skipped(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    with pytest.raises(SystemExit):
        with cron_health.cron_heartbeat("pipeline.prune_cache") as run:
            run.skip("group off")
            raise SystemExit(0)

    row = _only_row(engine)
    assert row.status == "skipped"
    assert row.error_summary == "group off"


def test_nonzero_system_exit_is_failure_and_reraised(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    with pytest.raises(SystemExit) as info:
        with cron_health.cron_heartbeat("pipeline.prune_cache"):
            raise SystemExit(1)

    assert info.value.code == 1
    row = _only_row(engine)
    assert row.status == "failure"
    assert row.error_summary == "exited with code 1"


def test_system_exit_with_a_message_is_failure(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    with pytest.raises(SystemExit):
        with cron_health.cron_heartbeat("pipeline.prune_cache"):
            raise SystemExit("bad config")

    row = _only_row(engine)
    assert row.status == "failure"
    assert row.error_summary == "exited with code bad config"


def test_ordinary_exception_format_is_unchanged(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    with pytest.raises(ValueError, match="boom"):
        with cron_health.cron_heartbeat("pipeline.prune_cache"):
            raise ValueError("boom")

    row = _only_row(engine)
    assert row.status == "failure"
    assert row.error_summary == "ValueError: boom"


def test_sigterm_handler_installed_inside_and_restored_after(monkeypatch, default_sigterm):
    _fresh_engine(monkeypatch)

    with cron_health.cron_heartbeat("pipeline.prune_cache"):
        inside = signal.getsignal(signal.SIGTERM)
        assert inside not in (signal.SIG_DFL, signal.SIG_IGN, None)

    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL


def test_sigterm_handler_restored_after_a_failure(monkeypatch, default_sigterm):
    _fresh_engine(monkeypatch)

    with pytest.raises(RuntimeError):
        with cron_health.cron_heartbeat("pipeline.prune_cache"):
            raise RuntimeError("x")

    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL


def test_sigterm_handler_raises_system_exit_143_and_records_failure(monkeypatch, default_sigterm):
    engine = _fresh_engine(monkeypatch)

    with pytest.raises(SystemExit) as info:
        with cron_health.cron_heartbeat("pipeline.prune_cache"):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

    assert info.value.code == 143
    row = _only_row(engine)
    assert row.status == "failure"
    assert row.error_summary == "interrupted: SIGTERM (exit code 143)"


def test_second_sigterm_during_exit_is_ignored(monkeypatch, default_sigterm):
    engine = _fresh_engine(monkeypatch)

    with pytest.raises(SystemExit):
        with cron_health.cron_heartbeat("pipeline.prune_cache"):
            handler = signal.getsignal(signal.SIGTERM)
            try:
                handler(signal.SIGTERM, None)
            finally:
                handler(signal.SIGTERM, None)  # returns quietly instead of raising again

    assert _only_row(engine).status == "failure"


def test_existing_custom_sigterm_handler_is_not_replaced(monkeypatch):
    _fresh_engine(monkeypatch)
    saved = signal.getsignal(signal.SIGTERM)

    def custom(signum, frame):  # pragma: no cover - never delivered
        pass

    signal.signal(signal.SIGTERM, custom)
    try:
        with cron_health.cron_heartbeat("pipeline.prune_cache"):
            assert signal.getsignal(signal.SIGTERM) is custom
        assert signal.getsignal(signal.SIGTERM) is custom
    finally:
        signal.signal(signal.SIGTERM, saved)


def test_handler_replaced_by_the_job_is_not_clobbered_on_exit(monkeypatch, default_sigterm):
    _fresh_engine(monkeypatch)

    def job_handler(signum, frame):  # pragma: no cover - never delivered
        pass

    with cron_health.cron_heartbeat("pipeline.prune_cache"):
        signal.signal(signal.SIGTERM, job_handler)

    assert signal.getsignal(signal.SIGTERM) is job_handler


def test_no_handler_is_installed_when_the_start_row_could_not_be_written(monkeypatch, default_sigterm):
    class _ExplodingEngine:
        def connect(self, *args, **kwargs):
            raise OSError("disk is full")

    monkeypatch.setattr(cron_health, "engine", _ExplodingEngine())

    with cron_health.cron_heartbeat("pipeline.prune_cache"):
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL


def test_non_main_thread_run_does_not_crash_and_logs_success(monkeypatch, tmp_path):
    # A file database: an in-memory one is private to the connection, and the worker thread opens its own.
    engine = create_engine(f"sqlite:///{tmp_path / 'thread.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(cron_health, "engine", engine)
    errors: list[BaseException] = []
    seen: list[object] = []

    def work():
        try:
            before = signal.getsignal(signal.SIGTERM)
            with cron_health.cron_heartbeat("pipeline.prune_cache") as run:
                seen.append(signal.getsignal(signal.SIGTERM) is before)
                run.message = "from a thread"
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()

    assert errors == []
    assert seen == [True]  # handler untouched off the main thread
    row = _only_row(engine)
    assert row.status == "success"
    assert row.error_summary == "from a thread"


def test_failing_finish_write_is_swallowed_with_a_warning_and_original_exception_propagates(monkeypatch, caplog):
    engine = _fresh_engine(monkeypatch)

    class _ExplodingEngine:
        def connect(self, *args, **kwargs):
            raise OSError("database is locked")

    with caplog.at_level(logging.WARNING, logger="core.cron_health"):
        with pytest.raises(KeyboardInterrupt):
            with cron_health.cron_heartbeat("pipeline.nightly_market_breadth"):
                monkeypatch.setattr(cron_health, "engine", _ExplodingEngine())
                raise KeyboardInterrupt()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "pipeline.nightly_market_breadth" in r.getMessage()]
    assert len(warnings) == 1
    assert "could not write the failure row" in warnings[0].getMessage()
    # The start row is untouched ("running"): the best-effort close failed, nothing else changed.
    with Session(engine) as session:
        assert session.exec(select(CronRunLog)).one().status == "running"


def test_sigterm_delivered_to_a_real_process_writes_failure_row_and_exits_143(tmp_path):
    db = tmp_path / "heartbeat.db"
    script = tmp_path / "run_job.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import os, signal, sys, time
            sys.path.insert(0, {str(BACKEND_DIR)!r})
            from sqlmodel import SQLModel, create_engine
            import core.cron_health as ch

            eng = create_engine("sqlite:///{db}")
            SQLModel.metadata.create_all(eng)
            ch.engine = eng
            with ch.cron_heartbeat("pipeline.prune_cache"):
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(30)
            """
        )
    )

    result = subprocess.run([sys.executable, str(script)], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=60)

    assert result.returncode == 143, result.stderr
    from sqlalchemy import create_engine as sa_create_engine

    engine = sa_create_engine(f"sqlite:///{db}")
    row = _only_row(engine)
    assert row.status == "failure"
    assert row.finished_at is not None
    assert row.error_summary == "interrupted: SIGTERM (exit code 143)"
