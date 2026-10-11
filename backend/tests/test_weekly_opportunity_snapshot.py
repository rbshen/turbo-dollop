"""pipeline/weekly_opportunity_snapshot.py: the entry point's flow (no-op rerun, --force, --dry-run), its heartbeat message, and
that the job is registered but NOT scheduled."""

from datetime import date, datetime
from pathlib import Path

import pytest

import pipeline.weekly_opportunity_snapshot as job
from core.cron_health import CRON_JOB_NAMES, DISABLED_CRON_JOBS, JOB_METADATA
from data.opportunity_data import ComputedRun

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


def test_the_job_is_registered_but_disabled_and_not_in_the_crontab():
    name = "pipeline.weekly_opportunity_snapshot"
    assert name in CRON_JOB_NAMES and name in JOB_METADATA and name in DISABLED_CRON_JOBS
    active = [l for l in (BACKEND / "crontab.txt").read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]
    assert not [l for l in active if "weekly_opportunity_snapshot" in l]
    assert '"pipeline.weekly_opportunity_snapshot"' in (BACKEND / "pipeline" / "weekly_opportunity_snapshot.py").read_text()


def test_the_job_makes_no_fmp_call_and_imports_no_client():
    source = (BACKEND / "data" / "opportunity_data.py").read_text() + (BACKEND / "pipeline" / "weekly_opportunity_snapshot.py").read_text()
    assert "fmp_client" not in source and "get_or_fetch" not in source and "get_or_fetch_bars_batch" not in source
