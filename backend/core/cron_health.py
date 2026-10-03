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
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterator, Literal, NamedTuple

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
# configure_logging so it has no plain log, and nightly_price_target_snapshot
# hasn't fired on a real schedule yet, but both are real cron jobs that need
# the same monitoring as every other one here.
CRON_JOB_NAMES: list[str] = [
    "pipeline.nightly_fundamentals_fetch",
    "pipeline.nightly_score_recompute",
    "pipeline.nightly_trend_calculation",
    "pipeline.nightly_corporate_events",
    "pipeline.nightly_last_close_snapshot",
    "pipeline.nightly_entry_signal_calculation",
    "pipeline.nightly_warren_signal_calculation",
    "pipeline.nightly_liquidity_zone_calculation",
    "pipeline.nightly_sector_heatmap",
    "pipeline.nightly_market_breadth",
    "pipeline.nightly_etf_screener",
    "scrapers.refresh_sp500_list",
    "scrapers.refresh_nasdaq_list",
    "scrapers.refresh_dow_list",
    "pipeline.prune_cache",
    "pipeline.rotate_logs",
    "pipeline.audit_fixture_contamination",
    "pipeline.stale_data_health_check",
    "pipeline.purge_invalid_tickers",
    "pipeline.nightly_price_target_snapshot",
    "pipeline.monthly_momentum_snapshot",
    "pipeline.backup_db",
]

# Expected cadence per job, with slack -- daily jobs (1:00 AM through 3:30 AM)
# flagged overdue past ~36h (tolerates one missed run without a false
# alarm the next morning); weekly-Sunday jobs (12:00-12:35 AM) past ~8 days;
# the one monthly job (momentum) past ~35 days (safely past any month length). First-
# pass, judgment-call values -- easy to retune per job if a real false
# alarm shows up.
_DAILY_HOURS = 36
_WEEKLY_HOURS = 24 * 8
_MONTHLY_HOURS = 24 * 35

_EXPECTED_CADENCE_HOURS: dict[str, int] = {
    "pipeline.nightly_fundamentals_fetch": _DAILY_HOURS,
    "pipeline.nightly_score_recompute": _DAILY_HOURS,
    "pipeline.nightly_trend_calculation": _DAILY_HOURS,
    "pipeline.nightly_corporate_events": _DAILY_HOURS,
    "pipeline.nightly_last_close_snapshot": _DAILY_HOURS,
    "pipeline.nightly_entry_signal_calculation": _DAILY_HOURS,
    "pipeline.nightly_warren_signal_calculation": _DAILY_HOURS,
    "pipeline.nightly_liquidity_zone_calculation": _DAILY_HOURS,
    "pipeline.nightly_sector_heatmap": _DAILY_HOURS,
    "pipeline.nightly_market_breadth": _DAILY_HOURS,
    "pipeline.nightly_etf_screener": _DAILY_HOURS,
    "pipeline.backup_db": _DAILY_HOURS,
    "scrapers.refresh_sp500_list": _WEEKLY_HOURS,
    "scrapers.refresh_nasdaq_list": _WEEKLY_HOURS,
    "scrapers.refresh_dow_list": _WEEKLY_HOURS,
    "pipeline.prune_cache": _WEEKLY_HOURS,
    "pipeline.rotate_logs": _WEEKLY_HOURS,
    "pipeline.audit_fixture_contamination": _WEEKLY_HOURS,
    "pipeline.stale_data_health_check": _WEEKLY_HOURS,
    "pipeline.purge_invalid_tickers": _WEEKLY_HOURS,
    "pipeline.nightly_price_target_snapshot": _DAILY_HOURS,
    "pipeline.monthly_momentum_snapshot": _MONTHLY_HOURS,
}


class JobMetadata(NamedTuple):
    """Static display metadata for one cron job -- description, cadence
    group, and a human time-of-day label -- sourced by hand from
    crontab.txt, since nothing queryable holds this today (crontab.txt
    itself isn't readable at runtime the way CronRunLog is). Backs the
    Settings "Status" section's Scheduled Jobs table, grouped by
    cadence_group and sorted by sort_minutes within each group."""

    description: str
    cadence_group: Literal["daily", "weekly", "monthly"]
    time_label: str
    sort_minutes: int  # minutes past midnight, for within-group ordering


# One entry per CRON_JOB_NAMES entry -- test_cron_wiring.py asserts the two
# sets stay identical, the same drift-prevention convention that file
# already applies to CRON_JOB_NAMES vs. crontab.txt vs. cron_heartbeat(...)
# wiring.
JOB_METADATA: dict[str, JobMetadata] = {
    "pipeline.nightly_fundamentals_fetch": JobMetadata(
        "Refetch FMP fundamentals, full tracked universe", "daily", "2:00 AM", 2 * 60
    ),
    "pipeline.nightly_score_recompute": JobMetadata(
        "Recompute 5-step scores, full universe", "daily", "3:25 AM", 3 * 60 + 25
    ),
    "pipeline.nightly_trend_calculation": JobMetadata(
        "Weinstein stage + daily-bar cache fill", "daily", "1:05 AM", 60 + 5
    ),
    "pipeline.nightly_corporate_events": JobMetadata(
        "Earnings / dividends / splits cache from FMP (Chart E/D markers)", "daily", "2:45 AM", 2 * 60 + 45
    ),
    "pipeline.nightly_last_close_snapshot": JobMetadata(
        "Last official close per ticker from FMP (header price fallback)", "daily", "1:00 AM", 60
    ),
    "pipeline.nightly_entry_signal_calculation": JobMetadata(
        "BB+RSI (2h) entry signal, E<number> and ETF watchlists", "daily", "1:20 AM", 60 + 20
    ),
    "pipeline.nightly_liquidity_zone_calculation": JobMetadata(
        "Support/resistance zone detection, E<number> and ETF watchlists", "daily", "1:15 AM", 60 + 15
    ),
    "pipeline.nightly_warren_signal_calculation": JobMetadata(
        "Warren RSI/ADX/WVF (2h) entry signal, E<number> and ETF watchlists", "daily", "1:25 AM", 60 + 25
    ),
    "pipeline.nightly_sector_heatmap": JobMetadata(
        "Sector ETF heatmap (11 SPDR sectors x 7 total-return windows)", "daily", "1:35 AM", 60 + 35
    ),
    "pipeline.nightly_market_breadth": JobMetadata(
        "Market breadth (S&P 500 % above 50/200-day SMA, net new 52-week highs)", "daily", "1:40 AM", 60 + 40
    ),
    "pipeline.nightly_etf_screener": JobMetadata(
        "ETFs screener refresh (fund facts, returns, Weinstein stage, signals per ETF)", "daily", "1:45 AM", 60 + 45
    ),
    "pipeline.backup_db": JobMetadata("Nightly SQLite backup + rotation", "daily", "3:30 AM", 3 * 60 + 30),
    "scrapers.refresh_sp500_list": JobMetadata("Keeps your S&P 500 stock list up to date", "weekly", "Sun 12:00 AM", 0),
    "scrapers.refresh_nasdaq_list": JobMetadata("Keeps your Nasdaq-100 stock list up to date", "weekly", "Sun 12:05 AM", 5),
    "scrapers.refresh_dow_list": JobMetadata("Keeps your Dow Jones stock list up to date", "weekly", "Sun 12:10 AM", 10),
    "pipeline.prune_cache": JobMetadata("Clears out old cached data to save space", "weekly", "Sun 12:15 AM", 15),
    "pipeline.rotate_logs": JobMetadata("Rotate/archive backend/logs/ files", "weekly", "Sun 12:20 AM", 20),
    "pipeline.audit_fixture_contamination": JobMetadata(
        "Checks that no test/fake data snuck into the real data", "weekly", "Sun 12:25 AM", 25
    ),
    "pipeline.stale_data_health_check": JobMetadata(
        "Flags stocks whose data hasn't been refreshed recently", "weekly", "Sun 12:30 AM", 30
    ),
    "pipeline.purge_invalid_tickers": JobMetadata(
        "Delete cache rows for confirmed-invalid tickers", "weekly", "Sun 12:35 AM", 35
    ),
    "pipeline.nightly_price_target_snapshot": JobMetadata(
        "Archive analyst price-target consensus", "daily", "3:10 AM", 3 * 60 + 10
    ),
    "pipeline.monthly_momentum_snapshot": JobMetadata(
        "3/6/12mo momentum ranking snapshot", "monthly", "1st–5th, 2:50 AM", 2 * 60 + 50
    ),
}


class DisabledJob(NamedTuple):
    """A job deliberately removed from the live crontab (its line commented out in
    crontab.txt) but kept in CRON_JOB_NAMES/JOB_METADATA so the page still lists it."""

    since: date
    reason: str


# Jobs whose crontab line is commented out on purpose. Without this entry a disabled
# job would read "Overdue" 36 hours after its last run (its last success just ages).
# With it, the page shows the neutral "Skipped" pill and "Disabled since <date>:
# <reason>" whatever the run history says. test_cron_wiring.py requires a job here to
# be ABSENT from crontab.txt (and every other job to be present), so enabling and
# disabling are each one two-line step that cannot be half done.
# To re-enable a job: uncomment its crontab.txt line, delete its entry here, run
# `crontab crontab.txt` from backend/ and check `crontab -l`.
DISABLED_CRON_JOBS: dict[str, DisabledJob] = {
    "pipeline.nightly_corporate_events": DisabledJob(
        date(2026, 10, 1),
        "pending investigation: about 1,165 FMP calls per run at 406-527 requests/min, over Starter's 300/min. "
        "The Chart tab serves the cached E/D markers.",
    ),
}


# Failure-rate rule shared by every job that reports attempted/failed counts (see
# check_failure_threshold). Judgment-call values, easy to retune here in one place.
#   - 5%: the failed share of attempted tickers at or above which the run is marked failed.
#   - 25 attempted: below this the rate rule is off and only "everything failed" counts, so a
#     tiny run (a --tickers test, a short watchlist) cannot flip on one error. 25 is chosen so
#     that a single failure is always under 5% once the rate rule applies (1/25 = 4%), i.e. one
#     stray error never turns a run red; two do (2/25 = 8%).
FAILURE_RATE_THRESHOLD = 0.05
FAILURE_RATE_MIN_ATTEMPTED = 25


def check_failure_threshold(attempted: int, failed: int, summary: str) -> None:
    """Raise RuntimeError (which cron_heartbeat records as status "failure", the existing red
    state) when a job's run should not read as healthy: everything attempted failed, or
    failed / attempted >= FAILURE_RATE_THRESHOLD with at least FAILURE_RATE_MIN_ATTEMPTED
    attempted. `attempted` is every ticker the job actually tried (it includes tickers that
    legitimately returned no data, and excludes ones skipped up front); "no data" and
    "skipped" counts belong in `summary` only and never enter the threshold. `summary` is the
    job's normal one-line message, reused as the head of the error text so the red message
    keeps the counts."""
    if attempted <= 0 or failed <= 0:
        return
    rate = failed / attempted
    if failed >= attempted:
        raise RuntimeError(f"{summary} -- all {attempted} attempted failed")
    if attempted >= FAILURE_RATE_MIN_ATTEMPTED and rate >= FAILURE_RATE_THRESHOLD:
        raise RuntimeError(f"{summary} -- {rate:.1%} failed (limit {FAILURE_RATE_THRESHOLD:.0%})")


def _truncated_error_summary(exc: Exception) -> str:
    summary = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return redact_apikey(summary)[:_ERROR_SUMMARY_MAX_CHARS]


@dataclass
class CronRunContext:
    """Yielded by cron_heartbeat() -- a script can set `.message` on it any
    time before its own `with` block exits to have a short, human-readable
    summary (e.g. "142 stale, 3 never-fetched") stored on the success run's
    CronRunLog.error_summary row (the existing nullable column, reused --
    no schema change) and surfaced by GET /api/config/cron-health. Ignored
    on a failure exit, where error_summary is always overwritten with the
    exception summary instead."""

    message: str | None = None
    skipped: bool = False

    def skip(self, reason: str) -> None:
        """Mark this run as intentionally skipped (e.g. "skipped (group
        fundamentals disabled)") -- stored as status "skipped", never
        "success", so a job that stays skipped for weeks cannot read as
        healthy. `reason` is stored as the run's message."""
        self.skipped = True
        self.message = reason


@contextmanager
def cron_heartbeat(job_name: str) -> Iterator[CronRunContext]:
    """Wrap a cron script's job-execution call with this: writes a
    "running" CronRunLog row at start, "success"/"failure"/"skipped" at exit
    ("skipped" only if the script called run.skip(reason)).

    Yields a CronRunContext the wrapped script can write a short summary
    message into (see CronRunContext's own docstring) -- e.g.:

        with cron_heartbeat("pipeline.stale_data_health_check") as run:
            result = main()
            run.message = f"{result.stale_count} stale, {result.never_fetched_count} never-fetched"

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
    init_db() -- two of the twelve wired scripts (rotate_logs, backup_db)
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

    run_context = CronRunContext()

    try:
        yield run_context
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
                        row.status = "skipped" if run_context.skipped else "success"
                        row.finished_at = datetime.now()
                        row.error_summary = run_context.message
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


def _skipped_since(job_name: str, session: Session, most_recent: CronRunLog) -> datetime:
    """Start of the current uninterrupted streak of skipped runs: the first
    "skipped" run after the most recent run that was not skipped (or the
    earliest skipped run on record if nothing else ever ran)."""
    last_real = session.exec(
        select(CronRunLog)
        .where(CronRunLog.job_name == job_name, CronRunLog.status != "skipped")
        .order_by(CronRunLog.started_at.desc())
        .limit(1)
    ).first()
    query = select(CronRunLog).where(CronRunLog.job_name == job_name, CronRunLog.status == "skipped")
    if last_real is not None:
        query = query.where(CronRunLog.started_at > last_real.started_at)
    first = session.exec(query.order_by(CronRunLog.started_at.asc()).limit(1)).first()
    return (first or most_recent).started_at


def _job_health(job_name: str, session: Session, now: datetime) -> CronJobHealthOut:
    metadata = JOB_METADATA[job_name]
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

    disabled = DISABLED_CRON_JOBS.get(job_name)
    if disabled is not None:
        # Same neutral "skipped" state a group-off job gets: nothing is wrong, nothing is
        # running. Takes precedence over run history, so an old success never ages into
        # "overdue" and a stray manual run never flips it to ok/failed.
        return CronJobHealthOut(
            job_name=job_name,
            health_status="skipped",
            message=f"Disabled since {disabled.since.isoformat()}: {disabled.reason}",
            last_run=_run_out(most_recent) if most_recent is not None else None,
            last_success_at=last_success_at,
            skipped_since=datetime.combine(disabled.since, time.min),
            description=metadata.description,
            cadence_group=metadata.cadence_group,
            time_label=metadata.time_label,
            sort_minutes=metadata.sort_minutes,
        )

    if most_recent is None:
        return CronJobHealthOut(
            job_name=job_name,
            health_status="unknown",
            message="No run recorded yet.",
            last_run=None,
            last_success_at=None,
            description=metadata.description,
            cadence_group=metadata.cadence_group,
            time_label=metadata.time_label,
            sort_minutes=metadata.sort_minutes,
        )

    last_run = _run_out(most_recent)

    if most_recent.status == "skipped":
        since = _skipped_since(job_name, session, most_recent)
        return CronJobHealthOut(
            job_name=job_name,
            health_status="skipped",
            message=f"Skipped since {since.date().isoformat()}: {most_recent.error_summary or 'group not live'}",
            last_run=last_run,
            last_success_at=last_success_at,
            skipped_since=since,
            description=metadata.description,
            cadence_group=metadata.cadence_group,
            time_label=metadata.time_label,
            sort_minutes=metadata.sort_minutes,
        )

    if most_recent.status == "failure":
        return CronJobHealthOut(
            job_name=job_name,
            health_status="failed",
            message=most_recent.error_summary or "Job failed.",
            last_run=last_run,
            last_success_at=last_success_at,
            description=metadata.description,
            cadence_group=metadata.cadence_group,
            time_label=metadata.time_label,
            sort_minutes=metadata.sort_minutes,
        )

    cadence_hours = _EXPECTED_CADENCE_HOURS[job_name]
    if last_success_at is not None and (now - last_success_at) <= timedelta(hours=cadence_hours):
        return CronJobHealthOut(
            job_name=job_name,
            health_status="ok",
            message=most_recent_success.error_summary if most_recent_success is not None else None,
            last_run=last_run,
            last_success_at=last_success_at,
            description=metadata.description,
            cadence_group=metadata.cadence_group,
            time_label=metadata.time_label,
            sort_minutes=metadata.sort_minutes,
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
        description=metadata.description,
        cadence_group=metadata.cadence_group,
        time_label=metadata.time_label,
        sort_minutes=metadata.sort_minutes,
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
