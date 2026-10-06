"""The background score recompute: the single-run claim, the worker body, the endpoints that start it and the status they show
(data/score_recompute.py, pipeline/score_recompute_job.py, core/main.py)."""

import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
import data.score_recompute as sr
import data.score_weights as score_weights
import data.ticker_score as ticker_score
import pipeline.score_recompute_job as job
from core.models import ScoreRecomputeRun, ScoreWeightSettings
from data.score_weights import load_score_weights
from scoring.weights import DEFAULT_WEIGHTS, weights_to_dict


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    for module in (main, sr, job, ticker_score):
        monkeypatch.setattr(module, "engine", eng)
    return eng


def _row(engine, run_id):
    with Session(engine) as session:
        run = session.get(ScoreRecomputeRun, run_id)
        session.expunge(run)
        return run


def _body(**overall):
    body = weights_to_dict(DEFAULT_WEIGHTS)
    body["overall"] = {"financials": 17, "growth": 17, "profitability": 17, "debt": 18, **overall}
    return body


# --- the single-run claim --------------------------------------------------------------------------------------------------


def test_claim_reserves_the_one_running_slot(engine):
    run_id = sr.claim_run("weights", engine)
    run = _row(engine, run_id)
    assert (run.state, run.trigger, run.processed, run.failed, run.weights_version) == ("running", "weights", 0, 0, 1)
    assert run.finished_at is None and run.started_at == run.heartbeat_at


def test_a_second_claim_is_refused_not_queued(engine):
    first = sr.claim_run("weights", engine)
    with Session(engine) as session:
        run = session.get(ScoreRecomputeRun, first)
        run.processed, run.total = 40, 582
        session.add(run)
        session.commit()
    with pytest.raises(sr.RecomputeAlreadyRunning) as raised:
        sr.claim_run("moat", engine)
    assert "already running (40 of 582)" in str(raised.value)
    with Session(engine) as session:
        assert len(session.exec(ScoreRecomputeRun.__table__.select()).all()) == 1  # nothing queued


def test_a_finished_run_frees_the_slot(engine):
    first = sr.claim_run("weights", engine)
    sr.fail_run(first, "boom", engine)
    second = sr.claim_run("reset", engine)
    assert second != first and _row(engine, second).state == "running"


def test_a_worker_that_stopped_reporting_is_failed_so_it_cannot_block_the_next_run(engine):
    stale = sr.claim_run("weights", engine)
    with Session(engine) as session:
        run = session.get(ScoreRecomputeRun, stale)
        run.heartbeat_at = datetime.now() - timedelta(seconds=sr.HEARTBEAT_STALE_SECONDS + 5)
        session.add(run)
        session.commit()
    fresh = sr.claim_run("reset", engine)  # reaps the dead one first
    dead = _row(engine, stale)
    assert dead.state == "failed" and "stopped responding" in dead.error and dead.finished_at is not None
    assert _row(engine, fresh).state == "running"


def test_a_recent_heartbeat_is_not_reaped(engine):
    sr.claim_run("weights", engine)
    with Session(engine) as session:
        assert sr.reap_stale_runs(session) == 0


def test_the_claim_survives_ten_concurrent_attempts(engine):
    outcomes = []
    import threading

    def attempt():
        try:
            outcomes.append(sr.claim_run("screener", engine))
        except sr.RecomputeAlreadyRunning:
            outcomes.append(None)

    threads = [threading.Thread(target=attempt) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(1 for o in outcomes if o is not None) == 1


# --- launching -------------------------------------------------------------------------------------------------------------


def test_launch_hands_the_run_to_the_worker(engine, recompute_launches):
    run_id = sr.start_recompute("screener", ["AAPL", "MSFT"], engine)
    assert recompute_launches == [(run_id, ["AAPL", "MSFT"])]


def test_a_worker_that_cannot_be_started_fails_the_run(engine, monkeypatch):
    def broken(run_id, tickers):
        raise OSError("no python")

    monkeypatch.setattr(sr, "launcher", broken)
    run_id = sr.claim_run("weights", engine)
    with pytest.raises(OSError):
        sr.launch_run(run_id, bind=engine)
    run = _row(engine, run_id)
    assert run.state == "failed" and "could not be started: no python" in run.error
    sr.claim_run("weights", engine)  # the slot is free again


def test_the_real_spawn_is_a_detached_module_run_of_the_job(engine, monkeypatch, tmp_path):
    seen = {}

    class FakeProc:
        pid = 4242

        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        seen["command"], seen["kwargs"] = command, kwargs
        return FakeProc()

    monkeypatch.setattr(sr.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sr, "LOG_PATH", tmp_path / "log.txt")
    run_id = sr.claim_run("weights", engine)
    sr._spawn_job(run_id, ["AAPL"])
    assert seen["command"][1:] == ["-m", "pipeline.score_recompute_job", str(run_id), "--tickers", "AAPL"]
    assert seen["kwargs"]["start_new_session"] is True  # survives an API reload
    assert seen["kwargs"]["cwd"] == sr.BACKEND_DIR
    assert _row(engine, run_id).pid == 4242


def test_a_worker_that_exits_without_finishing_fails_its_run_at_once(engine):
    run_id = sr.claim_run("weights", engine)

    class Dead:
        def wait(self):
            return 3

    sr._watch(Dead(), run_id)
    run = _row(engine, run_id)
    assert run.state == "failed" and "exit code 3" in run.error


def test_a_worker_that_finished_normally_is_left_alone_by_the_watcher(engine):
    run_id = sr.claim_run("weights", engine)
    asyncio.run(job.run_job(run_id, [], compute=_never))
    sr._watch(type("P", (), {"wait": lambda self: 0})(), run_id)
    assert _row(engine, run_id).state == "done"


async def _never(*a, **k):
    raise AssertionError("not called")


# --- the worker body -------------------------------------------------------------------------------------------------------


def test_the_job_scores_every_ticker_cache_only_and_ends_done(engine):
    run_id = sr.claim_run("weights", engine)
    calls = []

    async def compute(ticker, cache_only=False, **kwargs):
        calls.append((ticker, cache_only))
        return None if ticker == "NOPROFILE" else object()

    result = asyncio.run(job.run_job(run_id, ["AAPL", "NOPROFILE", "MSFT"], compute=compute))
    assert calls == [("AAPL", True), ("NOPROFILE", True), ("MSFT", True)]
    assert result == {"processed": 3, "skipped": 1, "failed": 0}
    run = _row(engine, run_id)
    assert (run.state, run.processed, run.skipped, run.failed, run.total) == ("done", 3, 1, 0, 3)
    assert run.finished_at is not None and run.error is None and run.weights_version == 1


def test_progress_is_written_as_the_job_goes(engine, monkeypatch):
    monkeypatch.setattr(job, "PROGRESS_EVERY", 2)
    run_id = sr.claim_run("weights", engine)
    seen = []

    async def compute(ticker, cache_only=False, **kwargs):
        run = _row(engine, run_id)
        seen.append((run.state, run.processed, run.total))
        return object()

    asyncio.run(job.run_job(run_id, list("ABCDE"), compute=compute))
    # processed counts finished tickers: written after every second one; the state stays running until the end.
    assert seen == [("running", 0, 5), ("running", 0, 5), ("running", 2, 5), ("running", 2, 5), ("running", 4, 5)]
    assert _row(engine, run_id).state == "done"


def test_a_ticker_that_raises_is_counted_and_never_stops_the_run(engine):
    run_id = sr.claim_run("weights", engine)

    async def compute(ticker, cache_only=False, **kwargs):
        if ticker == "BAD":
            raise RuntimeError("402")
        return object()

    asyncio.run(job.run_job(run_id, ["AAPL", "BAD", "MSFT"], compute=compute))
    run = _row(engine, run_id)
    assert run.state == "done" and (run.processed, run.failed) == (3, 1)
    assert json.loads(run.failures_json) == [["BAD", "402"]]


def test_a_run_where_every_ticker_failed_is_failed(engine):
    run_id = sr.claim_run("weights", engine)

    async def compute(ticker, cache_only=False, **kwargs):
        raise RuntimeError("db is down")

    asyncio.run(job.run_job(run_id, ["A", "B"], compute=compute))
    run = _row(engine, run_id)
    assert run.state == "failed" and run.error == "Every ticker failed to score." and run.finished_at is not None


def test_a_crash_in_the_job_itself_leaves_a_failed_run_with_the_reason(engine, monkeypatch):
    def broken_universe(session):
        raise RuntimeError("universe broke")

    monkeypatch.setattr(job, "load_tracked_universe", broken_universe)
    run_id = sr.claim_run("weights", engine)
    with pytest.raises(RuntimeError):
        asyncio.run(job.run_job(run_id, None, compute=_never))
    run = _row(engine, run_id)
    assert run.state == "failed" and "universe broke" in run.error


def test_the_job_scores_with_the_saved_weights_and_stamps_their_version(engine, monkeypatch):
    # The real compute path: steps are stubbed, the Overall blend and the stamped version are real.
    from tests.test_ticker_score import _step1, _step2, _step4, _step5, _summary

    def make(value):
        async def fn(ticker, cache_only=False, weights=None):
            return value

        return fn

    for name, value in (("get_step1_data", _step1()), ("get_step2_data", _step2()), ("get_step4_data", _step4()), ("get_step5_data", _step5()), ("get_summary", _summary())):
        monkeypatch.setattr(ticker_score, name, make(value))
    with Session(engine) as session:
        from scoring.weights import weights_from_dict

        score_weights.save_score_weights(session, weights_from_dict(_body(financials=17)))
    run_id = sr.claim_run("weights", engine)
    asyncio.run(job.run_job(run_id, ["AAPL"]))
    with Session(engine) as session:
        from core.models import TickerScore

        row = session.get(TickerScore, "AAPL")
    assert row.weights_version == 2
    assert row.overall_score == round((90 * 17 + 80 * 17 + 70 * 17 + 60 * 18) / 69)
    assert _row(engine, run_id).weights_version == 2


# --- the endpoints ---------------------------------------------------------------------------------------------------------


def test_saving_weights_saves_then_starts_the_job_once(engine, recompute_launches, monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("no scoring may run inside the request")

    monkeypatch.setattr(ticker_score, "compute_ticker_score", fail_if_called)
    with TestClient(main.app) as client:
        response = client.put("/api/config/score-weights", json=_body())
    assert response.status_code == 200
    body = response.json()
    assert body["weights"]["overall"]["debt"] == 18 and body["weights_version"] == 2
    assert body["recompute"]["state"] == "running" and body["recompute"]["trigger"] == "weights"
    assert len(recompute_launches) == 1  # the worker is started only after the save


def test_the_worker_is_started_after_the_new_weights_are_saved(engine, monkeypatch):
    seen = {}

    def launch(run_id, tickers):
        seen["version"] = load_score_weights(engine).version

    monkeypatch.setattr(sr, "launcher", launch)
    with TestClient(main.app) as client:
        client.put("/api/config/score-weights", json=_body())
    assert seen["version"] == 2  # the job starts against the saved set, never the old one


def test_saving_weights_while_a_run_is_in_progress_is_a_409_and_saves_nothing(engine, recompute_launches):
    sr.claim_run("screener", engine)
    with TestClient(main.app) as client:
        response = client.put("/api/config/score-weights", json=_body())
        reset = client.post("/api/config/score-weights/reset")
    assert response.status_code == reset.status_code == 409
    assert "already running" in response.json()["detail"]
    assert recompute_launches == []
    with Session(engine) as session:
        assert session.get(ScoreWeightSettings, "default") is None  # not saved (and not even seeded)


def test_an_invalid_set_starts_nothing_and_takes_no_slot(engine, recompute_launches):
    body = _body()
    body["step1"]["revenue"] += 5
    with TestClient(main.app) as client:
        assert client.put("/api/config/score-weights", json=body).status_code == 422
    assert recompute_launches == []
    sr.claim_run("weights", engine)  # the slot is free


def test_a_failed_save_frees_the_slot_and_starts_nothing(engine, recompute_launches, monkeypatch):
    def broken(session, weights):
        raise RuntimeError("disk full")

    monkeypatch.setattr(main, "save_score_weights", broken)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        assert client.put("/api/config/score-weights", json=_body()).status_code == 500
    assert recompute_launches == []
    run = _row(engine, 1)
    assert run.state == "failed" and "not saved" in run.error
    sr.claim_run("weights", engine)


def test_reset_restores_the_defaults_and_starts_the_job(engine, recompute_launches):
    with TestClient(main.app) as client:
        response = client.post("/api/config/score-weights/reset")
    assert response.status_code == 200 and response.json()["recompute"]["trigger"] == "reset"
    assert len(recompute_launches) == 1


def test_saving_moat_points_starts_the_job_and_keeps_its_response_shape(engine, recompute_launches):
    payload = {"wide_moat_score": 100.0, "narrow_moat_score": 65.0, "no_moat_score": 0.5}
    with TestClient(main.app) as client:
        response = client.put("/api/config/moat", json=payload)
    assert response.status_code == 200
    assert set(response.json()) == {"wide_moat_score", "narrow_moat_score", "no_moat_score", "updated_at"}
    assert response.json()["no_moat_score"] == 0.5
    assert len(recompute_launches) == 1
    assert _row(engine, 1).trigger == "moat"


def test_saving_moat_points_while_a_run_is_in_progress_is_a_409_and_saves_nothing(engine, recompute_launches):
    sr.claim_run("weights", engine)
    payload = {"wide_moat_score": 90.0, "narrow_moat_score": 60.0, "no_moat_score": 0.0}
    with TestClient(main.app) as client:
        assert client.put("/api/config/moat", json=payload).status_code == 409
        stored = client.get("/api/config/moat").json()
    assert stored["wide_moat_score"] == 100.0  # still the seeded defaults
    assert recompute_launches == []


def test_an_invalid_moat_save_starts_no_job(engine, recompute_launches):
    with TestClient(main.app) as client:
        response = client.put("/api/config/moat", json={"wide_moat_score": 100.0, "narrow_moat_score": 65.0, "no_moat_score": 5.0})
    assert response.status_code == 422 and recompute_launches == []


def test_the_status_is_part_of_the_settings_read(engine):
    with TestClient(main.app) as client:
        assert client.get("/api/config/score-weights").json()["recompute"] is None
        run_id = sr.claim_run("weights", engine)
        running = client.get("/api/config/score-weights").json()["recompute"]
        assert running["state"] == "running" and running["id"] == run_id
        asyncio.run(job.run_job(run_id, ["AAPL"], compute=lambda *a, **k: _async_obj()))
        done = client.get("/api/config/score-weights").json()["recompute"]
    assert done["state"] == "done" and (done["processed"], done["total"], done["failed"]) == (1, 1, 0)
    assert set(done) == {"id", "state", "trigger", "started_at", "finished_at", "processed", "skipped", "total", "failed", "weights_version", "error"}


async def _async_obj():
    return object()


def test_a_dead_workers_failed_state_is_visible_in_the_status(engine):
    run_id = sr.claim_run("weights", engine)
    with Session(engine) as session:
        run = session.get(ScoreRecomputeRun, run_id)
        run.heartbeat_at = datetime.now() - timedelta(minutes=10)
        session.add(run)
        session.commit()
    with TestClient(main.app) as client:
        status = client.get("/api/config/score-weights").json()["recompute"]
    assert status["state"] == "failed" and "stopped responding" in status["error"]
