"""Cron job heartbeat and health-monitoring, built after the 2026-08-16 cron
log audit found a real blind spot: an uncaught exception in a cron script
(e.g. sp500_list_refresh's sqlite3.IntegrityError, backup_db's disk-full
error) bypasses the script's own logging.FileHandler entirely -- Python's
default excepthook prints it straight to stderr, which only lands in
backend/logs/<job>_cron.log via crontab's `>> ... 2>&1` redirect, invisible
to anyone checking application state via the UI or the plain .log files.

CRON_JOB_NAMES is the single source of truth for job identity -- shared by
cron_heartbeat() (called from each script's own entry point),
get_cron_health() (backing GET /api/config/cron-health), and
tests/test_cron_wiring.py (which asserts this list, crontab.txt, and every
script's actual wiring all agree)."""

import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterator

from sqlmodel import Session, SQLModel, select

from core.config import settings
from core.db import engine
from core.logging_config import redact_apikey
from core.models import CronRunLog
from core.schemas import CronHealthOut, CronJobHealthOut, CronRunOut

_ERROR_SUMMARY_MAX_CHARS = 500

# Dotted module paths, copied verbatim from crontab.txt's `-m` invocations --
# this is every job actually scheduled there, not just the ones with a
# plain (non-_cron) log file: audit_fixture_contamination never calls
# configure_logging so it has no plain log, and monthly_price_target_snapshot
# hasn't fired on a real schedule yet, but both are real cron jobs that need
# the same monitoring as every other one here.
CRON_JOB_NAMES: list[str] = [
    "pipeline.nightly_fundamentals_fetch",
    "pipeline.nightly_score_recompute",
    "scrapers.refresh_sp500_list",
    "scrapers.refresh_dow_list",
    "pipeline.prune_cache",
    "pipeline.rotate_logs",
    "pipeline.audit_fixture_contamination",
    "pipeline.stale_data_health_check",
    "pipeline.purge_invalid_tickers",
    "pipeline.monthly_price_target_snapshot",
    "pipeline.backup_db",
]

# Expected cadence per job, with slack -- daily jobs (2:00/2:50/3:30 AM)
# flagged overdue past ~36h (tolerates one missed run without a false
# alarm the next morning); weekly-Sunday jobs (1:00-1:30 AM) past ~8 days;
# the one monthly job past ~35 days (safely past any month length). First-
# pass, judgment-call values -- easy to retune per job if a real false
# alarm shows up.
_DAILY_HOURS = 36
_WEEKLY_HOURS = 24 * 8
_MONTHLY_HOURS = 24 * 35

_EXPECTED_CADENCE_HOURS: dict[str, int] = {
    "pipeline.nightly_fundamentals_fetch": _DAILY_HOURS,
    "pipeline.nightly_score_recompute": _DAILY_HOURS,
    "pipeline.backup_db": _DAILY_HOURS,
    "scrapers.refresh_sp500_list": _WEEKLY_HOURS,
    "scrapers.refresh_dow_list": _WEEKLY_HOURS,
    "pipeline.prune_cache": _WEEKLY_HOURS,
    "pipeline.rotate_logs": _WEEKLY_HOURS,
    "pipeline.audit_fixture_contamination": _WEEKLY_HOURS,
    "pipeline.stale_data_health_check": _WEEKLY_HOURS,
    "pipeline.purge_invalid_tickers": _WEEKLY_HOURS,
    "pipeline.monthly_price_target_snapshot": _MONTHLY_HOURS,
}


def _truncated_error_summary(exc: Exception) -> str:
    summary = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return redact_apikey(summary)[:_ERROR_SUMMARY_MAX_CHARS]


@contextmanager
def cron_heartbeat(job_name: str) -> Iterator[None]:
    """Wrap a cron script's job-execution call with this: writes a
    "running" CronRunLog row at start, "success"/"failure" at exit.

    Purely additive -- on failure the original exception is always
    re-raised unchanged, so stderr/_cron.log capture and the process's
    exit code are completely unaffected. The heartbeat's own DB writes are
    each wrapped in their own narrow try/except-and-swallow, so a
    heartbeat write failure (e.g. the exact disk-full case this system
    exists to catch) can never mask or alter the job's real outcome -- a
    missing CronRunLog row just reads as "unknown" in the health endpoint,
    which is itself informative.

    Creates the table defensively on every invocation (SQLModel's own
    create_all, idempotent) rather than relying on the calling script's own
    init_db() -- two of the eleven wired scripts (rotate_logs, backup_db)
    never call init_db() themselves today, so this is what guarantees the
    CronRunLog table exists for them regardless. Deliberately uses this
    module's own `engine` reference (not core.db.init_db(), which is bound
    to core.db's own engine) so a test monkeypatching cron_health.engine
    gets fully isolated behavior, matching this codebase's per-module
    engine-patching convention."""
    row_id: int | None = None
    try:
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            row = CronRunLog(job_name=job_name, started_at=datetime.now(), status="running")
            session.add(row)
            session.commit()
            row_id = row.id
    except Exception:
        row_id = None

    try:
        yield
    except Exception as exc:
        if row_id is not None:
            try:
                with Session(engine) as session:
                    row = session.get(CronRunLog, row_id)
                    if row is not None:
                        row.status = "failure"
                        row.finished_at = datetime.now()
                        row.error_summary = _truncated_error_summary(exc)
                        session.add(row)
                        session.commit()
            except Exception:
                pass
        raise
    else:
        if row_id is not None:
            try:
                with Session(engine) as session:
                    row = session.get(CronRunLog, row_id)
                    if row is not None:
                        row.status = "success"
                        row.finished_at = datetime.now()
                        session.add(row)
                        session.commit()
            except Exception:
                pass


def _run_out(row: CronRunLog) -> CronRunOut:
    return CronRunOut(
        job_name=row.job_name,
        started_at=row.started_at,
        finished_at=row.finished_at,
        status=row.status,
        error_summary=row.error_summary,
    )


def _job_health(job_name: str, session: Session, now: datetime) -> CronJobHealthOut:
    most_recent = session.exec(
        select(CronRunLog).where(CronRunLog.job_name == job_name).order_by(CronRunLog.started_at.desc()).limit(1)
    ).first()
    most_recent_success = session.exec(
        select(CronRunLog)
        .where(CronRunLog.job_name == job_name, CronRunLog.status == "success")
        .order_by(CronRunLog.started_at.desc())
        .limit(1)
    ).first()
    last_success_at = most_recent_success.finished_at if most_recent_success else None

    if most_recent is None:
        return CronJobHealthOut(
            job_name=job_name,
            health_status="unknown",
            message="No run recorded yet.",
            last_run=None,
            last_success_at=None,
        )

    last_run = _run_out(most_recent)

    if most_recent.status == "failure":
        return CronJobHealthOut(
            job_name=job_name,
            health_status="failed",
            message=most_recent.error_summary or "Job failed.",
            last_run=last_run,
            last_success_at=last_success_at,
        )

    cadence_hours = _EXPECTED_CADENCE_HOURS[job_name]
    if last_success_at is not None and (now - last_success_at) <= timedelta(hours=cadence_hours):
        return CronJobHealthOut(
            job_name=job_name,
            health_status="ok",
            message=None,
            last_run=last_run,
            last_success_at=last_success_at,
        )

    if most_recent.status == "running" and last_success_at is None:
        message = f"Still running since {most_recent.started_at.isoformat(sep=' ', timespec='minutes')} -- may be stuck."
    elif last_success_at is not None:
        days = (now - last_success_at).days
        message = f"Last success was {days} day(s) ago; expected roughly every {cadence_hours // 24} day(s)."
    else:
        message = "No successful run recorded yet."

    return CronJobHealthOut(
        job_name=job_name,
        health_status="overdue",
        message=message,
        last_run=last_run,
        last_success_at=last_success_at,
    )


def get_cron_health() -> CronHealthOut:
    # Gates reporting only -- cron_heartbeat() above writes CronRunLog rows
    # unconditionally, regardless of this flag, so history is preserved and
    # flipping it back on (requires a backend restart, same as every other
    # Settings field) picks up right where it left off.
    if not settings.cron_health_enabled:
        return CronHealthOut(enabled=False, jobs=[])
    now = datetime.now()
    with Session(engine) as session:
        return CronHealthOut(enabled=True, jobs=[_job_health(job_name, session, now) for job_name in CRON_JOB_NAMES])
