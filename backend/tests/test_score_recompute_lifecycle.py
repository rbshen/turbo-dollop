"""Recompute worker lifecycle (cleanup batch 2026-10-13): a reaped run's still-alive worker is terminated (SIGTERM, then SIGKILL after a
grace) only when /proc proves the pid still runs THAT run's worker; an overall time limit; a heartbeat every 10 s or 10 tickers.

The worker is a real process: a stand-in `pipeline/score_recompute_job.py` in a temp directory, started with exactly the real command line
(`python -m pipeline.score_recompute_job <run_id>`), that either dies on SIGTERM or ignores it."""

import asyncio
import os
import signal
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
import data.score_recompute as sr
import data.ticker_score as ticker_score
import pipeline.score_recompute_job as job
from core.config import settings
from core.models import ScoreRecomputeRun

FAKE_WORKER = """
import os, signal, sys, time
if os.environ.get("FAKE_IGNORE_TERM") == "1":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
open(os.environ["FAKE_READY"], "w").write("ready")
time.sleep(60)
"""


@pytest.fixture
def engine(monkeypatch, tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'recompute.db'}", connect_args={"check_same_thread": False, "timeout": 15})
    SQLModel.metadata.create_all(eng)
    for module in (main, sr, job, ticker_score):
        monkeypatch.setattr(module, "engine", eng)
    return eng


@pytest.fixture
def start_worker(tmp_path):
    """start_worker(run_id, ignore_term=False) -> Popen of the stand-in worker, ready (signal handlers installed)."""
    package = tmp_path / "pipeline"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "score_recompute_job.py").write_text(textwrap.dedent(FAKE_WORKER))
    started: list[subprocess.Popen] = []

    def start(run_id: int, ignore_term: bool = False) -> subprocess.Popen:
        ready = tmp_path / f"ready-{run_id}-{len(started)}"
        env = {**os.environ, "FAKE_READY": str(ready), "FAKE_IGNORE_TERM": "1" if ignore_term else "0", "PYTHONPATH": str(tmp_path)}
        proc = subprocess.Popen([sys.executable, "-m", "pipeline.score_recompute_job", str(run_id)], cwd=tmp_path, env=env)
        started.append(proc)
        deadline = time.monotonic() + 20
        while not ready.exists():
            assert time.monotonic() < deadline and proc.poll() is None, "the stand-in worker did not start"
            time.sleep(0.02)
        return proc

    yield start
    for proc in started:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


@pytest.fixture
def unrelated(tmp_path):
    proc = subprocess.Popen(["sleep", "60"])
    yield proc
    if proc.poll() is None:
        proc.kill()
    proc.wait()


def _row(engine, run_id):
    with Session(engine) as session:
        run = session.get(ScoreRecomputeRun, run_id)
        session.expunge(run)
        return run


def _age(engine, run_id, *, heartbeat_age=None, started_age=None, pid=None):
    with Session(engine) as session:
        run = session.get(ScoreRecomputeRun, run_id)
        if heartbeat_age is not None:
            run.heartbeat_at = datetime.now() - timedelta(seconds=heartbeat_age)
        if started_age is not None:
            run.started_at = datetime.now() - timedelta(seconds=started_age)
        if pid is not None:
            run.pid = pid
        session.add(run)
        session.commit()


# ---- the identity check ----------------------------------------------------------------------------------------------------------


def test_is_recompute_worker_matches_only_this_runs_worker(start_worker, unrelated):
    proc = start_worker(7)
    assert sr.is_recompute_worker(proc.pid, 7)
    assert not sr.is_recompute_worker(proc.pid, 8)  # another run's id
    assert not sr.is_recompute_worker(proc.pid, 70)
    assert not sr.is_recompute_worker(unrelated.pid, 7)  # a reused pid: some other program
    assert not sr.is_recompute_worker(os.getpid(), 7)  # this very test process


def test_a_dead_or_unknown_pid_is_not_a_worker(start_worker):
    proc = start_worker(7)
    proc.kill()
    proc.wait()
    assert not sr.is_recompute_worker(proc.pid, 7)
    assert not sr.is_recompute_worker(2**22 + 12345, 7)


def test_an_exited_but_not_yet_reaped_worker_is_not_signalled(start_worker):
    proc = start_worker(7)
    os.kill(proc.pid, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while sr.is_recompute_worker(proc.pid, 7) and time.monotonic() < deadline:
        time.sleep(0.02)  # a zombie (not yet waited for) has an empty cmdline
    assert not sr.is_recompute_worker(proc.pid, 7)
    assert sr.terminate_worker(proc.pid, 7, grace_seconds=0.2) == "not-ours"


# ---- terminate_worker --------------------------------------------------------------------------------------------------------------


def test_sigterm_stops_a_worker_that_honours_it(start_worker):
    proc = start_worker(7)
    assert sr.terminate_worker(proc.pid, 7, grace_seconds=5) == "terminated"
    assert proc.wait(timeout=5) == -signal.SIGTERM


def test_sigkill_follows_after_the_grace_for_a_worker_that_ignores_sigterm(start_worker):
    proc = start_worker(7, ignore_term=True)
    started = time.monotonic()
    assert sr.terminate_worker(proc.pid, 7, grace_seconds=0.5) == "killed"
    assert time.monotonic() - started >= 0.5  # the grace was given
    assert proc.wait(timeout=5) == -signal.SIGKILL


def test_a_reused_pid_is_never_signalled(unrelated):
    assert sr.terminate_worker(unrelated.pid, 7, grace_seconds=0.2) == "not-ours"
    assert unrelated.poll() is None  # still running


def test_another_runs_worker_is_never_signalled(start_worker):
    proc = start_worker(8)
    assert sr.terminate_worker(proc.pid, 7, grace_seconds=0.2) == "not-ours"
    assert proc.poll() is None


# ---- the reaper ----------------------------------------------------------------------------------------------------------------------


def test_reaping_a_stale_run_stops_its_live_worker(engine, start_worker, monkeypatch):
    run_id = sr.claim_run("weights", engine)
    proc = start_worker(run_id, ignore_term=True)
    _age(engine, run_id, heartbeat_age=sr.HEARTBEAT_STALE_SECONDS + 5, pid=proc.pid)
    monkeypatch.setattr(sr, "terminator", lambda pid, rid: sr.terminate_worker(pid, rid, grace_seconds=0.3))
    with Session(engine) as session:
        assert sr.reap_stale_runs(session) == 1
    assert _row(engine, run_id).state == "failed"
    assert proc.wait(timeout=10) == -signal.SIGKILL


def test_the_default_terminator_does_not_block_the_caller(engine, start_worker):
    run_id = sr.claim_run("weights", engine)
    proc = start_worker(run_id)
    _age(engine, run_id, heartbeat_age=sr.HEARTBEAT_STALE_SECONDS + 5, pid=proc.pid)
    started = time.monotonic()
    with Session(engine) as session:
        assert sr.reap_stale_runs(session) == 1
    assert time.monotonic() - started < sr.TERMINATE_GRACE_SECONDS  # the sequence runs on a daemon thread
    assert proc.wait(timeout=10) == -signal.SIGTERM


def test_reaping_never_touches_a_recycled_pid(engine, unrelated, monkeypatch):
    run_id = sr.claim_run("weights", engine)
    _age(engine, run_id, heartbeat_age=sr.HEARTBEAT_STALE_SECONDS + 5, pid=unrelated.pid)
    monkeypatch.setattr(sr, "terminator", lambda pid, rid: sr.terminate_worker(pid, rid, grace_seconds=0.2))
    with Session(engine) as session:
        assert sr.reap_stale_runs(session) == 1
    assert unrelated.poll() is None


def test_only_reaped_runs_with_a_pid_are_terminated(engine, monkeypatch):
    stopped = []
    monkeypatch.setattr(sr, "terminator", lambda pid, rid: stopped.append((pid, rid)))
    healthy = sr.claim_run("weights", engine)
    _age(engine, healthy, pid=4242)
    with Session(engine) as session:
        assert sr.reap_stale_runs(session) == 0
    assert stopped == []
    _age(engine, healthy, heartbeat_age=sr.HEARTBEAT_STALE_SECONDS + 5)
    with Session(engine) as session:
        assert sr.reap_stale_runs(session) == 1
    assert stopped == [(4242, healthy)]
    pidless = sr.claim_run("reset", engine)
    _age(engine, pidless, heartbeat_age=sr.HEARTBEAT_STALE_SECONDS + 5)
    with Session(engine) as session:
        assert sr.reap_stale_runs(session) == 1
    assert stopped == [(4242, healthy)]  # no pid, nothing to stop


def test_a_run_past_the_time_limit_is_reaped_even_with_a_fresh_heartbeat(engine, monkeypatch):
    stopped = []
    monkeypatch.setattr(sr, "terminator", lambda pid, rid: stopped.append((pid, rid)))
    monkeypatch.setattr(settings, "score_recompute_timeout_seconds", 600)
    run_id = sr.claim_run("weights", engine)
    _age(engine, run_id, started_age=601, pid=999)
    with Session(engine) as session:
        assert sr.reap_stale_runs(session) == 1
    run = _row(engine, run_id)
    assert run.state == "failed" and "time limit" in run.error
    assert stopped == [(999, run_id)]


def test_a_run_inside_the_time_limit_is_left_alone(engine, monkeypatch):
    monkeypatch.setattr(settings, "score_recompute_timeout_seconds", 600)
    run_id = sr.claim_run("weights", engine)
    _age(engine, run_id, started_age=300)
    with Session(engine) as session:
        assert sr.reap_stale_runs(session) == 0


def test_a_zero_limit_means_no_limit(engine, monkeypatch):
    monkeypatch.setattr(settings, "score_recompute_timeout_seconds", 0)
    run_id = sr.claim_run("weights", engine)
    _age(engine, run_id, started_age=10**6)
    with Session(engine) as session:
        assert sr.reap_stale_runs(session) == 0


def test_the_default_limit_is_generous():
    assert settings.score_recompute_timeout_seconds == 3600


def test_the_claim_gate_is_unchanged_by_the_lifecycle(engine):
    first = sr.claim_run("weights", engine)
    with pytest.raises(sr.RecomputeAlreadyRunning):
        sr.claim_run("moat", engine)
    sr.fail_run(first, "x", engine)
    assert sr.claim_run("moat", engine) != first


# ---- the worker body --------------------------------------------------------------------------------------------------------------------


def test_the_heartbeat_is_written_by_time_when_the_ticker_count_is_far_away(engine, monkeypatch):
    monkeypatch.setattr(job, "PROGRESS_EVERY", 1000)
    monkeypatch.setattr(job, "HEARTBEAT_EVERY_SECONDS", 0.05)
    run_id = sr.claim_run("weights", engine)
    beats = []

    async def compute(ticker, cache_only=False, **kwargs):
        beats.append(_row(engine, run_id).heartbeat_at)
        await asyncio.sleep(0.06)
        return object()

    asyncio.run(job.run_job(run_id, list("ABCDEF"), compute=compute))
    assert len(set(beats)) >= 4  # the heartbeat moved while no 1000-ticker boundary was anywhere near


def test_the_heartbeat_by_count_still_applies(engine, monkeypatch):
    monkeypatch.setattr(job, "PROGRESS_EVERY", 2)
    monkeypatch.setattr(job, "HEARTBEAT_EVERY_SECONDS", 3600)
    run_id = sr.claim_run("weights", engine)
    seen = []

    async def compute(ticker, cache_only=False, **kwargs):
        seen.append(_row(engine, run_id).processed)
        return object()

    asyncio.run(job.run_job(run_id, list("ABCDE"), compute=compute))
    assert seen == [0, 0, 2, 2, 4]


def test_the_worker_stops_itself_at_the_time_limit(engine, monkeypatch):
    monkeypatch.setattr(sr.settings, "score_recompute_timeout_seconds", 0.1)
    run_id = sr.claim_run("weights", engine)
    done = []

    async def compute(ticker, cache_only=False, **kwargs):
        done.append(ticker)
        await asyncio.sleep(0.04)
        return object()

    with pytest.raises(TimeoutError):
        asyncio.run(job.run_job(run_id, [f"T{i}" for i in range(50)], compute=compute))
    run = _row(engine, run_id)
    assert run.state == "failed" and "time limit" in run.error and run.finished_at is not None
    assert 0 < len(done) < 50


def test_a_worker_whose_run_was_reaped_stops_and_does_not_write_done(engine):
    run_id = sr.claim_run("weights", engine)
    calls = []

    async def compute(ticker, cache_only=False, **kwargs):
        calls.append(ticker)
        if len(calls) == 2:
            sr.fail_run(run_id, "reaped by the API", engine)  # what reap_stale_runs does to a run that went quiet
        return object()

    result = asyncio.run(job.run_job(run_id, list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), compute=compute))
    assert result.get("superseded") is True
    run = _row(engine, run_id)
    assert run.state == "failed" and run.error == "reaped by the API"
    assert len(calls) < 26  # it stopped at the next write, not at the end
