"""Audit-log pruning (cleanup batch 2026-10-13): core.audit.prune_audit_log, `core.auth_cli prune-audit`, the weekly pipeline job and its cron
wiring. In-memory auth database per test (conftest)."""

import io
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, select

import core.audit as audit
import core.auth as auth
import core.auth_cli as cli
from core.config import settings
from core.cron_health import CRON_JOB_NAMES, JOB_METADATA
from core.models import AuditLog, CronRunLog, User, UserSession

NOW = datetime(2026, 10, 13, 12, 0, 0)


def _add_audit(days_old: float, event="request", n=1):
    with Session(auth.engine) as s:
        for _ in range(n):
            s.add(AuditLog(ts=NOW - timedelta(days=days_old), method="POST", path="/api/x", status=200, event=event, username="a"))
        s.commit()


def _count():
    with Session(auth.engine) as s:
        return len(s.exec(select(AuditLog)).all())


def _seed_user_and_session():
    with Session(auth.engine) as s:
        user = auth.create_user(s, "alice", "correct horse battery", "admin")
        s.add(UserSession(token_hash="h" * 64, user_id=user.id, created_at=NOW - timedelta(days=400), expires_at=NOW + timedelta(days=1),
                          last_seen_at=NOW - timedelta(days=400), ip=None, user_agent=None))
        s.commit()


def test_deletes_only_rows_older_than_the_cutoff():
    _add_audit(200, n=3)
    _add_audit(181)
    _add_audit(179.9, n=2)
    _add_audit(1)
    assert audit.prune_audit_log(180, now=NOW) == 4
    assert _count() == 3


def test_the_boundary_row_exactly_at_the_cutoff_is_kept():
    _add_audit(180)
    assert audit.prune_audit_log(180, now=NOW) == 0 and _count() == 1


def test_the_default_comes_from_the_setting(monkeypatch):
    _add_audit(100, n=2)
    _add_audit(5)
    assert settings.audit_retention_days == 180
    monkeypatch.setattr(settings, "audit_retention_days", 30)
    assert audit.prune_audit_log(now=NOW) == 2 and _count() == 1


def test_users_and_sessions_are_never_touched():
    _seed_user_and_session()
    _add_audit(900, n=5)
    assert audit.prune_audit_log(1, now=NOW) == 5
    with Session(auth.engine) as s:
        assert len(s.exec(select(User)).all()) == 1 and len(s.exec(select(UserSession)).all()) == 1


@pytest.mark.parametrize("bad", [0, -5, True, 1.5, "30"])
def test_days_must_be_a_whole_number_of_at_least_one(bad):
    _add_audit(900)
    with pytest.raises(ValueError):
        audit.prune_audit_log(bad, now=NOW)
    assert _count() == 1  # nothing deleted


def test_an_empty_table_prunes_nothing():
    assert audit.prune_audit_log(180, now=NOW) == 0


# ---- the CLI ------------------------------------------------------------------------------------------------------


def test_cli_prune_audit_with_days(capsys, monkeypatch):
    monkeypatch.setattr(audit.auth, "utcnow", lambda: NOW)
    _add_audit(40, n=2)
    _add_audit(5)
    assert cli.main(["prune-audit", "--days", "30"]) == 0
    out = capsys.readouterr().out
    assert "Deleted 2 audit log row(s) older than 30 day(s)" in out and "Users and sessions were not touched" in out
    assert _count() == 1


def test_cli_prune_audit_default_is_the_setting(capsys, monkeypatch):
    monkeypatch.setattr(audit.auth, "utcnow", lambda: NOW)
    _add_audit(190)
    _add_audit(10)
    assert cli.main(["prune-audit"]) == 0
    assert "older than 180 day(s)" in capsys.readouterr().out and _count() == 1


def test_cli_prune_audit_refuses_zero_and_negative(capsys):
    _add_audit(900)
    assert cli.main(["prune-audit", "--days", "0"]) == 1
    assert "at least 1" in capsys.readouterr().err
    assert cli.main(["prune-audit", "--days", "-3"]) == 1
    assert _count() == 1


def test_cli_prune_audit_leaves_users_alone(monkeypatch, capsys):
    monkeypatch.setattr(audit.auth, "utcnow", lambda: NOW)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("correct horse battery\n"))
    assert cli.main(["create-user", "bob", "--role", "viewer"]) == 0
    _add_audit(400)
    assert cli.main(["prune-audit"]) == 0
    with Session(auth.engine) as s:
        assert [u.username for u in s.exec(select(User)).all()] == ["bob"]


# ---- the weekly job and its wiring --------------------------------------------------------------------------------


def test_the_job_prunes_with_the_setting_and_reports_the_count(monkeypatch):
    import pipeline.prune_audit_log as job

    monkeypatch.setattr(job, "configure_logging", lambda path: None)
    monkeypatch.setattr(audit.auth, "utcnow", lambda: NOW)
    _add_audit(300, n=4)
    _add_audit(2)
    assert job.main() == 4 and _count() == 1
    _add_audit(10, n=2)
    assert job.main(5) == 2


def test_the_job_is_registered_and_wrapped_in_the_heartbeat():
    from pathlib import Path

    from core.cron_health import _EXPECTED_CADENCE_HOURS, DISABLED_CRON_JOBS

    name = "pipeline.prune_audit_log"
    assert name in CRON_JOB_NAMES and name in JOB_METADATA and name not in DISABLED_CRON_JOBS
    assert JOB_METADATA[name].cadence_group == "weekly" and _EXPECTED_CADENCE_HOURS[name] == 24 * 8
    source = (Path(__file__).resolve().parent.parent / "pipeline" / "prune_audit_log.py").read_text()
    assert 'cron_heartbeat("pipeline.prune_audit_log")' in source


def test_the_cron_line_is_weekly_and_runs_under_flock():
    from pathlib import Path

    lines = [l for l in (Path(__file__).resolve().parent.parent / "crontab.txt").read_text().splitlines()
             if l.strip() and not l.lstrip().startswith("#") and "prune_audit_log" in l]
    (line,) = lines
    assert line.split()[:5] == ["40", "0", "*", "*", "0"]
    assert "/usr/bin/flock -n -E 99 logs/locks/prune_audit_log.lock " in line and "-m pipeline.prune_audit_log " in line
