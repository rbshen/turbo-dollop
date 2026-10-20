"""pipeline/weekly_opportunity_snapshot.py: the entry point's flow (no-op rerun, --force, --dry-run), its heartbeat message, and
that the job is registered but NOT scheduled."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import pipeline.weekly_opportunity_snapshot as job
from core.cron_health import CRON_JOB_NAMES, DISABLED_CRON_JOBS, JOB_METADATA
from data.opportunity_data import ComputedRun, latest_completed_session

AS_OF = date(2026, 10, 9)
BACKEND = Path(__file__).resolve().parent.parent


def computed() -> ComputedRun:
    summary = {"list_totals": {"momentum": 3, "reversal": 2}, "gate_passed": 500, "counts": {}}
    return ComputedRun(as_of=AS_OF, last_bar_date=AS_OF, universe_size=600, score_formula_version=6, weights_version=1, summary=summary, rows=[])


@pytest.fixture(autouse=True)
def _log(monkeypatch, tmp_path):
    monkeypatch.setattr(job, "LOG_PATH", tmp_path / "weekly_opportunity_snapshot.log")


def test_a_rerun_for_an_existing_date_is_a_no_op_that_never_computes(monkeypatch):
    monkeypatch.setattr(job, "existing_run_id", lambda as_of: 7)
    monkeypatch.setattr(job, "compute_run", lambda as_of: pytest.fail("must not compute when the run exists"))
    monkeypatch.setattr(job, "persist_run", lambda *a, **k: pytest.fail("must not write"))
    result = job.main(AS_OF)
    assert result == {"status": "exists", "run_id": 7, "as_of_date": "2026-10-09", "skipped": True}
    assert job.run_message(result) == "run for 2026-10-09 already exists (no-op)"


def test_a_new_date_computes_and_persists(monkeypatch):
    calls = []
    monkeypatch.setattr(job, "existing_run_id", lambda as_of: None)
    monkeypatch.setattr(job, "compute_run", lambda as_of: computed())
    monkeypatch.setattr(job, "persist_run", lambda run, force=False: calls.append(force) or {"status": "created", "run_id": 1, "as_of_date": "2026-10-09", "rows": 5})
    result = job.main(AS_OF)
    assert calls == [False] and result["status"] == "created" and result["skipped"] is False
    assert job.run_message(result) == "created 2026-10-09: Momentum 3, Reversal 2, 500 through the gate"


def test_force_skips_the_exists_check_and_passes_through(monkeypatch):
    calls = []
    monkeypatch.setattr(job, "existing_run_id", lambda as_of: pytest.fail("--force must not short-circuit"))
    monkeypatch.setattr(job, "compute_run", lambda as_of: computed())
    monkeypatch.setattr(job, "persist_run", lambda run, force=False: calls.append(force) or {"status": "replaced", "run_id": 2, "as_of_date": "2026-10-09", "rows": 5})
    assert job.main(AS_OF, force=True)["status"] == "replaced" and calls == [True]


def test_dry_run_computes_and_writes_nothing(monkeypatch):
    monkeypatch.setattr(job, "compute_run", lambda as_of: computed())
    monkeypatch.setattr(job, "persist_run", lambda *a, **k: pytest.fail("a dry run must not write"))
    monkeypatch.setattr(job, "existing_run_id", lambda as_of: pytest.fail("a dry run does not consult the stored run"))
    result = job.main(AS_OF, dry_run=True)
    assert result["status"] == "dry_run" and result["summary"]["list_totals"] == {"momentum": 3, "reversal": 2}


def test_the_default_as_of_is_the_last_completed_session(monkeypatch):
    seen = []
    monkeypatch.setattr(job, "latest_completed_session", lambda: AS_OF)
    monkeypatch.setattr(job, "existing_run_id", lambda as_of: seen.append(as_of) or 1)
    job.main()
    assert seen == [AS_OF]


def test_the_job_is_registered_enabled_and_scheduled_saturday_4am():
    from core.cron_health import _EXPECTED_CADENCE_HOURS, _WEEKLY_HOURS

    name = "pipeline.weekly_opportunity_snapshot"
    assert name in CRON_JOB_NAMES and name in JOB_METADATA and name not in DISABLED_CRON_JOBS
    assert JOB_METADATA[name].cadence_group == "weekly" and JOB_METADATA[name].sort_minutes == 4 * 60
    # a weekly job is overdue after 8 days (one missed Saturday plus a day of slack), not the 36 hours of a daily one
    assert _EXPECTED_CADENCE_HOURS[name] == _WEEKLY_HOURS == 24 * 8
    active = [l for l in (BACKEND / "crontab.txt").read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]
    (line,) = [l for l in active if "weekly_opportunity_snapshot" in l]
    assert line.split()[:5] == ["0", "4", "*", "*", "6"]
    assert "-m pipeline.weekly_opportunity_snapshot" in line
    assert '"pipeline.weekly_opportunity_snapshot"' in (BACKEND / "pipeline" / "weekly_opportunity_snapshot.py").read_text()


def test_the_weekly_run_comes_after_the_backup_and_the_nightly_chain():
    import re

    schedule = {}
    for line in (BACKEND / "crontab.txt").read_text().splitlines():
        m = re.search(r"-m ([\w.]+)", line)
        if line.strip() and not line.lstrip().startswith("#") and m:
            schedule.setdefault(m.group(1), line.split()[:5])  # first line per job: backup_db's daily 3:30 (its Saturday 4:15 line comes later)
    minute, hour, _dom, _month, dow = schedule["pipeline.weekly_opportunity_snapshot"]
    backup_minute, backup_hour, *_ = schedule["pipeline.backup_db"]
    assert dow == "6" and int(hour) * 60 + int(minute) > int(backup_hour) * 60 + int(backup_minute)


def test_the_job_makes_no_fmp_call_and_imports_no_client():
    source = (BACKEND / "data" / "opportunity_data.py").read_text() + (BACKEND / "pipeline" / "weekly_opportunity_snapshot.py").read_text()
    assert "fmp_client" not in source and "get_or_fetch" not in source and "get_or_fetch_bars_batch" not in source


# --- the as-of date on the scheduled run (Saturday 04:00 server time, which is UTC) -----------------------------------------


@pytest.mark.parametrize("run_at_utc, expected, why", [
    (datetime(2026, 10, 10, 4, 0, tzinfo=timezone.utc), date(2026, 10, 9), "an ordinary week: Saturday -> Friday's close (EDT, 00:00 ET)"),
    (datetime(2027, 1, 9, 4, 0, tzinfo=timezone.utc), date(2027, 1, 8), "winter: 23:00 ET on Friday evening, still after the close"),
    (datetime(2027, 3, 27, 4, 0, tzinfo=timezone.utc), date(2027, 3, 25), "Good Friday (NYSE closed 2027-03-26): Thursday"),
    (datetime(2026, 7, 4, 4, 0, tzinfo=timezone.utc), date(2026, 7, 2), "Friday 2026-07-03 is the observed Independence Day holiday: Thursday"),
    (datetime(2026, 11, 28, 4, 0, tzinfo=timezone.utc), date(2026, 11, 27), "day after Thanksgiving closes at 13:00: that Friday counts"),
])
def test_a_saturday_run_resolves_to_the_last_completed_session(run_at_utc, expected, why):
    assert latest_completed_session(run_at_utc) == expected, why


def test_the_default_as_of_of_the_job_is_that_same_resolution(monkeypatch):
    """main() with no --as-of asks latest_completed_session() (no reference: now); pinned here by freezing that call's clock."""
    import data.opportunity_data as od

    seen = []
    real = od._most_recent_completed_trading_date
    monkeypatch.setattr(od, "_most_recent_completed_trading_date", lambda reference=None: seen.append(reference) or real(datetime(2027, 3, 27, 4, 0, tzinfo=timezone.utc)))
    monkeypatch.setattr(job, "existing_run_id", lambda as_of: seen.append(as_of) or 1)
    job.main()
    assert seen[-1] == date(2027, 3, 25)
