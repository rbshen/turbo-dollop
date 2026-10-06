"""The full score recompute as a background job (docs/specs/overview.md, "Adjustable weights").

Saving the weights, resetting them, saving the Moat points and the Screener's "Recompute all scores" all start the same job: a
cache-only `compute_ticker_score` for every tracked ticker (no FMP call). It runs in a **subprocess**
(`python -m pipeline.score_recompute_job <run_id>`), not a thread: a ~40 s CPU-bound job in a thread shares the GIL with the API's
event loop (latency spikes, a slower API), a `uvicorn --reload` restart would kill it mid-run, and a crash would take the API with
it. A subprocess is isolated, survives a reload (own session) and runs like every other pipeline job. Each ticker's score row is
written by one atomic upsert, so a run can never leave a half-written TickerScore row; rows simply sit on the old weights_version
until the job reaches them.

One run at a time: `claim_run` inserts the status row only when no run is `running` (a single INSERT ... WHERE NOT EXISTS), and a
second request gets RecomputeAlreadyRunning (HTTP 409), never queued. A running row whose worker stopped reporting (no heartbeat
for HEARTBEAT_STALE_SECONDS) or whose process exited without finishing is marked failed, so a dead worker never blocks the next run.
"""

import asyncio
import logging
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import exists, insert, literal, select
from sqlalchemy.engine import Engine
from sqlmodel import Session, select as sql_select

from core.db import engine
from core.models import ScoreRecomputeRun
from core.schemas import RecomputeRunOut
from data.score_weights import load_score_weights
from data.tracked_universe import load_tracked_universe

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
LOG_PATH = BACKEND_DIR / "logs" / "score_recompute_job_cron.log"
HEARTBEAT_STALE_SECONDS = 120
TRIGGERS = ("weights", "reset", "moat", "screener")


class RecomputeAlreadyRunning(Exception):
    """A run is already in progress (the API answers 409). `run` is its RecomputeRunOut."""

    def __init__(self, run: RecomputeRunOut):
        self.run = run
        super().__init__(
            f"A score recompute is already running ({run.processed} of {run.total}); try again when it finishes."
        )


def _out(run: ScoreRecomputeRun) -> RecomputeRunOut:
    return RecomputeRunOut(
        id=run.id,
        state=run.state,
        trigger=run.trigger,
        started_at=run.started_at,
        finished_at=run.finished_at,
        processed=run.processed,
        skipped=run.skipped,
        total=run.total,
        failed=run.failed,
        weights_version=run.weights_version,
        error=run.error,
    )


def reap_stale_runs(session: Session, *, now: datetime | None = None) -> int:
    """Marks every `running` row whose worker has gone quiet as failed; returns how many."""
    now = now or datetime.now()
    cutoff = now - timedelta(seconds=HEARTBEAT_STALE_SECONDS)
    reaped = 0
    for run in session.exec(sql_select(ScoreRecomputeRun).where(ScoreRecomputeRun.state == "running")).all():
        if run.heartbeat_at < cutoff:
            run.state, run.finished_at = "failed", now
            run.error = "The recompute worker stopped responding. Run it again with Recompute all scores."
            session.add(run)
            reaped += 1
    if reaped:
        session.commit()
    return reaped


def latest_run(session: Session) -> ScoreRecomputeRun | None:
    return session.exec(sql_select(ScoreRecomputeRun).order_by(ScoreRecomputeRun.id.desc())).first()


def latest_run_out(session: Session) -> RecomputeRunOut | None:
    """The newest run (any state) for the status payload, after noticing a dead worker."""
    reap_stale_runs(session)
    run = latest_run(session)
    return _out(run) if run is not None else None


def claim_run(trigger: str, bind: Engine | None = None) -> int:
    """Reserves the single running slot and returns the run id, or raises RecomputeAlreadyRunning. The job is NOT started yet: the
    caller saves whatever must be saved first (the weights, the Moat points), then calls launch_run, so the job always reads the
    new values."""
    assert trigger in TRIGGERS, trigger
    bind = bind or engine
    now = datetime.now()
    with Session(bind) as session:
        reap_stale_runs(session, now=now)
        try:
            total = len(load_tracked_universe(session))
        except Exception:  # noqa: BLE001 -- the job re-resolves it; this is only the figure shown before it starts
            total = 0
        version = load_score_weights(bind).version
        values = select(
            literal("running"), literal(trigger), literal(now), literal(now), literal(0), literal(0), literal(total), literal(0), literal(version)
        ).where(~exists().where(ScoreRecomputeRun.state == "running"))
        result = session.execute(
            insert(ScoreRecomputeRun).from_select(
                ["state", "trigger", "started_at", "heartbeat_at", "processed", "skipped", "total", "failed", "weights_version"],
                values,
            )
        )
        session.commit()
        if result.rowcount == 0:
            running = session.exec(sql_select(ScoreRecomputeRun).where(ScoreRecomputeRun.state == "running")).first()
            raise RecomputeAlreadyRunning(_out(running))
        return latest_run(session).id  # the slot is ours, so the newest row is the one just inserted


def ensure_not_running(bind: Engine | None = None) -> None:
    """Raises RecomputeAlreadyRunning when a run is in progress (checked before anything is saved)."""
    with Session(bind or engine) as session:
        reap_stale_runs(session)
        running = session.exec(sql_select(ScoreRecomputeRun).where(ScoreRecomputeRun.state == "running")).first()
        if running is not None:
            raise RecomputeAlreadyRunning(_out(running))


def fail_run(run_id: int, error: str, bind: Engine | None = None) -> None:
    with Session(bind or engine) as session:
        run = session.get(ScoreRecomputeRun, run_id)
        if run is not None and run.state == "running":
            run.state, run.error, run.finished_at = "failed", error, datetime.now()
            session.add(run)
            session.commit()


def _watch(proc: subprocess.Popen, run_id: int) -> None:
    """Reaps the child (no zombie) and, if it exited without finishing its run, marks the run failed at once."""
    code = proc.wait()
    try:
        fail_run(run_id, f"The recompute worker exited unexpectedly (exit code {code}). See logs/score_recompute_job_cron.log.")
    except Exception:  # noqa: BLE001
        logger.exception("could not record the end of recompute run %s", run_id)


def _spawn_job(run_id: int, tickers: list[str] | None) -> None:
    command = [sys.executable, "-m", "pipeline.score_recompute_job", str(run_id)]
    if tickers:
        command += ["--tickers", ",".join(tickers)]
    LOG_PATH.parent.mkdir(exist_ok=True)
    log = open(LOG_PATH, "ab")  # noqa: SIM115 -- handed to the child, closed in this process right after the spawn
    try:
        proc = subprocess.Popen(
            command, cwd=BACKEND_DIR, start_new_session=True, stdin=subprocess.DEVNULL, stdout=log, stderr=log
        )
    finally:
        log.close()
    with Session(engine) as session:
        run = session.get(ScoreRecomputeRun, run_id)
        if run is not None:
            run.pid = proc.pid
            session.add(run)
            session.commit()
    threading.Thread(target=_watch, args=(proc, run_id), daemon=True).start()


# Replaceable in tests (they assert what would be launched without starting a process).
launcher: Callable[[int, list[str] | None], None] = _spawn_job


def launch_run(run_id: int, tickers: list[str] | None = None, bind: Engine | None = None) -> None:
    """Starts the worker for a claimed run; a failure to even start it fails the run (it never stays `running`)."""
    try:
        launcher(run_id, tickers)
    except Exception as exc:  # noqa: BLE001
        fail_run(run_id, f"The recompute worker could not be started: {exc}", bind)
        raise


def start_recompute(trigger: str, tickers: list[str] | None = None, bind: Engine | None = None) -> int:
    """Claim the slot and launch the job; for callers with nothing to save first (the Screener button)."""
    run_id = claim_run(trigger, bind)
    launch_run(run_id, tickers, bind)
    return run_id


def summary_for(run_id: int, bind: Engine | None = None) -> dict:
    """The Screener endpoint's RecomputeSummary shape (processed, failed, duration_seconds, failures) from a finished run."""
    import json

    with Session(bind or engine) as session:
        run = session.get(ScoreRecomputeRun, run_id)
        end = run.finished_at or datetime.now()
        return {
            "processed": run.processed,
            "failed": run.failed,
            "duration_seconds": (end - run.started_at).total_seconds(),
            "failures": [tuple(item) for item in json.loads(run.failures_json or "[]")],
        }


async def wait_for_run(run_id: int, bind: Engine | None = None, *, poll_seconds: float = 0.5) -> RecomputeRunOut:
    """Awaits a run without holding the event loop: sleeps between status reads (the worker is another process)."""
    while True:
        with Session(bind or engine) as session:
            reap_stale_runs(session)
            run = session.get(ScoreRecomputeRun, run_id)
            if run.state != "running":
                return _out(run)
        await asyncio.sleep(poll_seconds)
