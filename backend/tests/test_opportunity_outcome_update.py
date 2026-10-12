"""data/opportunity_outcome_data.py + pipeline/opportunity_outcome_update.py: the updater over a throwaway database and synthetic cached
bars -- seeding, idempotent reruns, frozen complete rows, pending -> complete, one ticker failing, the SPY no-op rule, dry runs, chunking,
benchmarks (including an ETF with no sector ETF), the completed-bars-only rule and the heartbeat-style log."""

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import data.opportunity_outcome_data as ou
import pipeline.opportunity_outcome_update as job
from core.models import (
    OpportunityOutcome,
    OpportunityOutcomeRun,
    OpportunityRun,
    OpportunitySnapshotRow,
    SharedBarsCache,
    TickerScore,
)
from scoring import opportunity_outcomes as eng

AS_OF = date(2026, 10, 9)
CREATED = datetime(2026, 10, 10, 4, 0)


def sessions_after(as_of: date, n: int) -> list[date]:
    out, d = [], as_of
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def series(dates: list[date], start: float, drift: float = 0.0, lows: dict[date, float] | None = None) -> pd.DataFrame:
    rows, p = [], start
    for d in dates:
        o, c = p, p * (1 + drift)
        low = (lows or {}).get(d, min(o, c) * 0.995)
        rows.append((o, max(o, c) * 1.005, low, c, 1e6))
        p = c
    return pd.DataFrame(rows, index=pd.DatetimeIndex(dates), columns=["open", "high", "low", "close", "volume"])


def now_after(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 0, tzinfo=timezone.utc) + timedelta(days=1)


class World:
    def __init__(self, engine):
        self.engine = engine
        self.frames: dict[str, pd.DataFrame] = {}
        self.reads: list[list[str]] = []

    def set_bars(self, n_sessions: int, **drifts):
        dates = sessions_after(AS_OF, n_sessions)
        self.dates = dates
        self.frames["SPY"] = series(dates, 400.0, 0.001)
        self.frames["XLK"] = series(dates, 200.0, 0.002)
        self.frames["XLE"] = series(dates, 80.0, -0.001)
        self.frames["AAA"] = series(dates, 100.0, 0.003)  # Technology stock
        self.frames["CCC"] = series(dates, 50.0, 0.0, lows={dates[2]: 40.0} if n_sessions > 2 else None)  # Energy stock, stops out on day 3
        self.frames["QQQX"] = series(dates, 30.0, 0.001)  # an ETF: no sector
        self.now = now_after(dates[-1])

    def rows(self) -> dict[tuple[str, int], OpportunityOutcome]:
        with Session(self.engine) as s:
            return {(o.ticker, o.horizon): o for o in s.exec(select(OpportunityOutcome)).all()}


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(ou, "engine", engine)
    w = World(engine)

    with Session(engine) as s:
        s.add(OpportunityRun(
            id=1, kind="weekly", as_of_date=AS_OF, last_bar_date=AS_OF, universe_size=3, rules_hash="h", rules_version="2",
            score_formula_version=6, created_at=CREATED,
        ))
        for order, (ticker, tier, sector, close) in enumerate([("AAA", "quality", "Technology", 100.0), ("CCC", "momentum_only", "Energy", 50.0), ("QQQX", "etf", None, 30.0)], 1):
            s.add(OpportunitySnapshotRow(run_id=1, list_name="momentum", ticker=ticker, tier=tier, list_order=order, rule_ids_json="[]", sector=sector, close=close))
        s.commit()

    def fake_read(tickers, lookback_days, reference=None):
        w.reads.append(list(tickers))
        return {t: w.frames[t] for t in tickers if t in w.frames}

    monkeypatch.setattr(ou, "read_cached_daily_bars_batch", fake_read)
    monkeypatch.setattr(ou, "load_tracked_universe", lambda session: ["AAA", "CCC"])
    monkeypatch.setattr(ou, "load_etf_universe", lambda session: ["QQQX"])
    w.set_bars(8)
    return w


def update(w: World, **kw):
    return ou.update_outcomes(now=w.now, **kw)


# --- seeding and the first compute ---------------------------------------------------------------------------------------------


def test_every_listed_row_gets_four_outcome_rows(world):
    result = update(world)
    rows = world.rows()
    assert len(rows) == 3 * 4 and {h for (_t, h) in rows} == {5, 10, 20, 60}
    assert result.status == "success" and result.seeded == 12 and result.runs == 1 and result.listed_rows == 3
    assert all(o.provenance == "live" and o.rules_version == "2" for o in rows.values())


def test_horizon_5_completes_and_longer_ones_stay_pending_with_the_path_so_far(world):
    update(world)
    rows = world.rows()
    aaa5, aaa10 = rows[("AAA", 5)], rows[("AAA", 10)]
    assert aaa5.status == "complete" and aaa5.exit_date == world.dates[5] and aaa5.forward_return == pytest.approx(1.003**6 - 1)
    assert aaa10.status == "pending" and aaa10.forward_return is None and aaa10.entry_open == pytest.approx(100.0)
    assert aaa10.worst_move is not None and aaa10.entry_date == world.dates[0]


def test_stop_hits_are_recorded_even_on_pending_rows(world):
    result = update(world)
    rows = world.rows()
    assert rows[("CCC", 5)].stop_hit and rows[("CCC", 5)].stop_date == world.dates[2]
    assert rows[("CCC", 10)].status == "pending" and rows[("CCC", 10)].stop_hit  # the stop is final before the horizon
    assert not rows[("AAA", 5)].stop_hit
    assert result.stops == 4  # CCC at all four horizons


def test_sector_benchmark_for_a_stock_and_spy_only_for_an_etf(world):
    update(world)
    rows = world.rows()
    aaa, cc, etf = rows[("AAA", 5)], rows[("CCC", 5)], rows[("QQQX", 5)]
    assert aaa.sector_etf == "XLK" and aaa.sector_return == pytest.approx(1.002**6 - 1) and aaa.excess_vs_sector == pytest.approx(aaa.forward_return - aaa.sector_return)
    assert cc.sector_etf == "XLE" and cc.sector_return == pytest.approx(0.999**6 - 1)
    assert etf.sector_etf is None and etf.sector_return is None and etf.excess_vs_sector is None
    assert etf.spy_return == pytest.approx(1.001**6 - 1) and etf.excess_vs_spy == pytest.approx(etf.forward_return - etf.spy_return)


# --- idempotence, frozen rows, transitions -------------------------------------------------------------------------------------------


def test_a_rerun_with_the_same_bars_changes_nothing(world):
    update(world)
    before = {k: (o.id, o.computed_at, o.forward_return, o.status) for k, o in world.rows().items()}
    again = update(world, as_of=AS_OF)  # targeted, so the new-SPY-bar check does not short-circuit it
    assert (again.seeded, again.updated) == (0, 0)
    assert {k: (o.id, o.computed_at, o.forward_return, o.status) for k, o in world.rows().items()} == before


def test_a_normal_rerun_is_a_no_op_until_spy_has_a_new_bar(world):
    first = update(world)
    log_id = ou.start_log()
    ou.finish_log(log_id, first.status, first.message(), first.spy_last_bar_date)
    n_reads = len(world.reads)
    second = update(world)
    assert second.status == "noop" and "no bar newer" in second.reason
    assert len(world.reads) == n_reads + 1  # only SPY was read to decide
    n_reads = len(world.reads)
    # SPY gets two new bars: the normal run goes ahead and extends the pending rows
    world.set_bars(13)
    third = update(world)
    assert third.status == "success" and len(world.reads) > n_reads
    rows = world.rows()
    assert rows[("AAA", 10)].status == "complete" and rows[("AAA", 10)].exit_date == world.dates[10]


def test_a_complete_row_is_frozen_even_if_the_bars_change_later(world):
    update(world)
    frozen = world.rows()[("AAA", 5)]
    world.set_bars(13)
    world.frames["AAA"] = series(world.dates, 100.0, -0.01)  # a restated history
    update(world, as_of=AS_OF)
    after = world.rows()[("AAA", 5)]
    assert (after.forward_return, after.exit_close, after.computed_at) == (frozen.forward_return, frozen.exit_close, frozen.computed_at)
    assert world.rows()[("AAA", 10)].forward_return < 0  # the pending row did follow the new bars


def test_a_stop_already_recorded_survives_vanishing_bars(world):
    update(world)
    assert world.rows()[("CCC", 10)].stop_hit
    world.frames["CCC"] = series(world.dates, 50.0, 0.0)  # the flush day is gone from the bars
    update(world, as_of=AS_OF)
    again = world.rows()[("CCC", 10)]
    assert again.stop_hit and again.stop_date == world.dates[2] and again.stop_fill_return is not None


def test_the_no_op_when_everything_is_final(world):
    world.set_bars(66)
    update(world)
    assert all(o.status == "complete" for o in world.rows().values())
    again = update(world, as_of=AS_OF)
    assert again.status == "noop" and again.reason.startswith("every listed row") and again.frozen_untouched == 12


# --- failures, censoring, chunks -------------------------------------------------------------------------------------------------------


def test_one_ticker_failing_leaves_its_rows_pending_and_the_others_computed(world, monkeypatch):
    real = eng.compute_outcomes

    def flaky(**kw):
        if kw["as_of_close"] == 100.0:  # AAA
            raise ValueError("bad bar")
        return real(**kw)

    monkeypatch.setattr(ou.eng, "compute_outcomes", flaky)
    result = update(world)
    rows = world.rows()
    assert result.status == "partial" and list(result.failed) == ["AAA"]
    assert [rows[("AAA", h)].status for h in eng.HORIZONS] == ["pending"] * 4 and rows[("AAA", 5)].forward_return is None
    assert rows[("CCC", 5)].status == "complete" and rows[("QQQX", 5)].status == "complete"
    monkeypatch.setattr(ou.eng, "compute_outcomes", real)  # next time it works
    update(world, as_of=AS_OF)
    assert world.rows()[("AAA", 5)].status == "complete"


def test_a_failed_bars_read_for_one_chunk_does_not_stop_the_other_chunks(world, monkeypatch):
    monkeypatch.setattr(ou, "CHUNK_SIZE", 1)
    inner = ou.read_cached_daily_bars_batch

    def read(tickers, lookback_days, reference=None):
        if tickers == ["CCC"]:
            raise OSError("disk")
        return inner(tickers, lookback_days, reference)

    monkeypatch.setattr(ou, "read_cached_daily_bars_batch", read)
    result = update(world)
    rows = world.rows()
    assert list(result.failed) == ["CCC"] and rows[("AAA", 5)].status == "complete" and rows[("CCC", 5)].status == "pending"


def test_chunking_gives_the_same_rows(world, monkeypatch):
    update(world)
    one_shot = {k: (o.status, o.forward_return, o.stop_hit) for k, o in world.rows().items()}
    with Session(world.engine) as s:
        for o in s.exec(select(OpportunityOutcome)).all():
            s.delete(o)
        s.commit()
    monkeypatch.setattr(ou, "CHUNK_SIZE", 1)
    update(world)
    assert {k: (o.status, o.forward_return, o.stop_hit) for k, o in world.rows().items()} == one_shot


def test_a_delisted_ticker_that_stops_getting_bars_is_censored_with_its_reason(world):
    with Session(world.engine) as s:
        s.add(TickerScore(ticker="CCC", company_name="CCC", delisted_at=CREATED, computed_at=CREATED))
        s.commit()
    world.set_bars(20)
    world.frames["CCC"] = world.frames["CCC"].iloc[:4]  # last bar: the 4th session
    update(world)
    r = world.rows()[("CCC", 5)]
    assert r.status == "censored" and r.censor_reason == "delisted"
    assert r.exit_date == world.dates[3] and r.forward_return is not None  # the sensitivity line
    assert world.rows()[("AAA", 5)].status == "complete"


def test_a_ticker_out_of_the_universe_is_censored_left_universe(world, monkeypatch):
    monkeypatch.setattr(ou, "load_tracked_universe", lambda session: ["AAA"])
    world.set_bars(20)
    world.frames["CCC"] = world.frames["CCC"].iloc[:4]
    update(world)
    assert world.rows()[("CCC", 5)].censor_reason == "left_universe"


def test_the_run_counts_by_status_and_horizon(world):
    result = update(world)
    assert result.by_status["complete"] == {5: 3} and result.by_status["pending"] == {10: 3, 20: 3, 60: 3}
    assert "complete 3, pending 9, censored 0, stops 4" in result.message()


# --- dry run -----------------------------------------------------------------------------------------------------------------------


def test_a_dry_run_reports_the_same_state_and_writes_nothing(world):
    result = ou.update_outcomes(dry_run=True, now=world.now)
    assert result.status == "dry_run" and result.seeded == 12 and result.by_status["complete"] == {5: 3} and result.stops == 4
    assert world.rows() == {}
    with Session(world.engine) as s:
        assert s.exec(select(OpportunityOutcomeRun)).all() == []


def test_a_dry_run_after_a_real_run_leaves_the_rows_alone(world):
    update(world)
    before = {k: (o.computed_at, o.forward_return) for k, o in world.rows().items()}
    world.set_bars(13)
    dry = ou.update_outcomes(dry_run=True, now=world.now, as_of=AS_OF)
    assert dry.updated > 0
    assert {k: (o.computed_at, o.forward_return) for k, o in world.rows().items()} == before


# --- completed bars only ----------------------------------------------------------------------------------------------------------------


def test_a_bar_after_the_last_completed_session_or_written_before_its_close_is_dropped(world):
    dates = sessions_after(AS_OF, 6)
    frame = series(dates, 100.0)
    with Session(world.engine) as s:  # the last bar was written at 12:00 ET on its own day, before the 16:00 close
        last = dates[-1]
        s.add(SharedBarsCache(ticker="AAA", interval="1d", bar_time=datetime.combine(last, datetime.min.time()), open=1, high=1, low=1, close=1, volume=1,
                              fetched_at=datetime.combine(last, datetime.min.time()) + timedelta(hours=12) + timedelta(hours=4)))
        s.commit()
    ref = datetime.combine(last, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=18)  # 14:00 ET the same day
    out = ou._completed_only({"AAA": frame}, ref)["AAA"]
    assert out.index.max().date() == dates[-2]  # the live session's bar is out
    # after that day's close the session is "completed", but the last bar was written at 12:00 ET: still a partial bar
    after_close = datetime.combine(last, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1, hours=2)
    assert ou._completed_only({"AAA": frame}, after_close)["AAA"].index.max().date() == dates[-2]
    with Session(world.engine) as s:  # re-fetched after the close: now final
        row = s.exec(select(SharedBarsCache)).one()
        row.fetched_at = datetime.combine(last, datetime.min.time()) + timedelta(hours=22)
        s.add(row)
        s.commit()
    assert ou._completed_only({"AAA": frame}, after_close)["AAA"].index.max().date() == last


# --- the job and its heartbeat-style log -----------------------------------------------------------------------------------------------


@pytest.fixture
def jobbed(world, monkeypatch, tmp_path):
    monkeypatch.setattr(job, "LOG_PATH", tmp_path / "opportunity_outcome_update.log")
    monkeypatch.setattr(job, "init_db", lambda: None)
    monkeypatch.setattr(ou, "datetime", type("DT", (datetime,), {"now": classmethod(lambda cls, tz=None: world.now if tz else world.now.replace(tzinfo=None))}))
    return world


def logs(w: World):
    with Session(w.engine) as s:
        return s.exec(select(OpportunityOutcomeRun).order_by(OpportunityOutcomeRun.id)).all()


def test_the_job_writes_one_log_row_per_real_run_and_the_next_run_reads_its_spy_date(jobbed):
    first = job.main()
    assert first.status == "success"
    (row,) = logs(jobbed)
    assert row.status == "success" and row.finished_at is not None and row.spy_last_bar_date == jobbed.dates[-1]
    assert "complete 3" in row.message and json.loads(row.summary_json)["stops"] == 4
    second = job.main()
    assert second.status == "noop"
    rows = logs(jobbed)
    assert [r.status for r in rows] == ["success", "noop"] and rows[1].spy_last_bar_date == jobbed.dates[-1]


def test_a_partial_run_stores_no_spy_date_so_the_next_run_retries(jobbed, monkeypatch):
    real = eng.compute_outcomes
    monkeypatch.setattr(ou.eng, "compute_outcomes", lambda **kw: (_ for _ in ()).throw(ValueError("x")) if kw["as_of_close"] == 100.0 else real(**kw))
    assert job.main().status == "partial"
    assert logs(jobbed)[0].status == "partial" and logs(jobbed)[0].spy_last_bar_date is None
    monkeypatch.setattr(ou.eng, "compute_outcomes", real)
    retry = job.main()  # no new SPY bar, but the failed ticker's rows are still pending and the last run stored no date
    assert retry.status == "success" and world_status(jobbed, "AAA", 5) == "complete"


def world_status(w: World, ticker: str, horizon: int) -> str:
    return w.rows()[(ticker, horizon)].status


def test_a_failure_is_logged_and_re_raised(jobbed):
    jobbed.frames.pop("SPY")
    with pytest.raises(RuntimeError, match="SPY"):
        job.main()
    (row,) = logs(jobbed)
    assert row.status == "failure" and "SPY" in row.message and row.spy_last_bar_date is None


def test_the_job_dry_run_writes_no_log_row(jobbed):
    result = job.main(dry_run=True)
    assert result.status == "dry_run" and logs(jobbed) == [] and jobbed.rows() == {}


# --- the scheduled run: cron heartbeat -------------------------------------------------------------------------------------------


@pytest.fixture
def beat(jobbed, monkeypatch):
    """The job's command-line entry (run_scheduled) with the cron heartbeat writing into the same throwaway database."""
    import argparse

    import core.cron_health as ch

    monkeypatch.setattr(ch, "engine", jobbed.engine)

    def go(**kw):
        ns = argparse.Namespace(once=True, dry_run=False, run_id=None, as_of=None)
        for k, v in kw.items():
            setattr(ns, k, v)
        return job.run_scheduled(ns)

    return go


def beats(w: World):
    from core.models import CronRunLog

    with Session(w.engine) as s:
        return [(r.status, r.error_summary) for r in s.exec(select(CronRunLog).where(CronRunLog.job_name == "pipeline.opportunity_outcome_update").order_by(CronRunLog.id)).all()]


def test_a_real_run_is_a_green_heartbeat_with_the_result_as_its_message(beat, jobbed):
    result = beat()
    assert result.status == "success"
    ((status, message),) = beats(jobbed)
    assert status == "success" and message == result.message() and "complete 3" in message


def test_a_no_op_run_is_a_green_heartbeat_not_a_failure_or_a_skip(beat, jobbed):
    beat()
    again = beat()  # same SPY bar: a weekend, a holiday, a night the bars did not move
    assert again.status == "noop"
    rows = beats(jobbed)
    assert [s for s, _ in rows] == ["success", "success"]
    assert rows[1][1].startswith("no-op: SPY has no bar newer than")


def test_an_exception_is_a_red_heartbeat_and_is_re_raised(beat, jobbed):
    jobbed.frames.pop("SPY")
    with pytest.raises(RuntimeError, match="SPY"):
        beat()
    ((status, message),) = beats(jobbed)
    assert status == "failure" and "SPY" in message


def test_every_ticker_failing_is_a_red_heartbeat_but_one_failed_ticker_is_not(beat, jobbed, monkeypatch):
    real = eng.compute_outcomes
    monkeypatch.setattr(ou.eng, "compute_outcomes", lambda **kw: (_ for _ in ()).throw(ValueError("x")) if kw["as_of_close"] == 100.0 else real(**kw))
    one = beat()  # 1 of 3 attempted failed: below the threshold, green, but named in the message
    assert one.status == "partial" and one.attempted == 3
    assert beats(jobbed)[-1][0] == "success" and "1 ticker(s) failed" in beats(jobbed)[-1][1]

    monkeypatch.setattr(ou.eng, "compute_outcomes", lambda **kw: (_ for _ in ()).throw(ValueError("x")))
    with pytest.raises(RuntimeError, match="all 3 attempted failed"):
        beat(as_of="2026-10-09")  # targeted, so the new-SPY-bar check does not short-circuit it
    assert beats(jobbed)[-1][0] == "failure"
    monkeypatch.setattr(ou.eng, "compute_outcomes", real)


def test_the_last_seen_spy_date_advances_only_on_real_runs(beat, jobbed, monkeypatch):
    def spy_dates():
        return [(r.status, r.spy_last_bar_date) for r in logs(jobbed)]

    jobbed.frames["SPY"] = jobbed.frames["SPY"].iloc[:5]  # SPY has 5 sessions after the as-of date
    jobbed.now = now_after(jobbed.dates[4])
    beat()
    day5 = jobbed.dates[4]
    assert spy_dates() == [("success", day5)]
    beat()  # nothing new: a no-op carries the date, it does not move it
    assert spy_dates()[-1] == ("noop", day5)

    jobbed.set_bars(8)  # three newer SPY bars: a real run, the date advances
    beat()
    assert spy_dates()[-1] == ("success", jobbed.dates[7])

    jobbed.frames.pop("SPY")
    with pytest.raises(RuntimeError):
        beat()
    assert spy_dates()[-1] == ("failure", None)  # a failure stores none, so the next run is not short-circuited by a stale date

    real = eng.compute_outcomes
    jobbed.set_bars(9)
    monkeypatch.setattr(ou.eng, "compute_outcomes", lambda **kw: (_ for _ in ()).throw(ValueError("x")) if kw["as_of_close"] == 100.0 else real(**kw))
    beat()
    assert spy_dates()[-1] == ("partial", None)  # partial stores none: the failed ticker is retried by the next run


def test_a_dry_run_writes_no_heartbeat_row(beat, jobbed):
    beat(dry_run=True)
    assert beats(jobbed) == [] and logs(jobbed) == []


def test_the_updater_is_scheduled_and_makes_no_fmp_call():
    from pathlib import Path

    from core.cron_health import _EXPECTED_CADENCE_HOURS, CRON_JOB_NAMES, DISABLED_CRON_JOBS, JOB_METADATA

    backend = Path(__file__).resolve().parent.parent
    name = "pipeline.opportunity_outcome_update"
    assert name in CRON_JOB_NAMES and name in JOB_METADATA and name not in DISABLED_CRON_JOBS
    assert _EXPECTED_CADENCE_HOURS[name] == 36 and JOB_METADATA[name].cadence_group == "daily" and JOB_METADATA[name].sort_minutes == 3 * 60 + 40
    assert "no FMP calls" in JOB_METADATA[name].description
    active = [l for l in (backend / "crontab.txt").read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]
    (line,) = [l for l in active if name in l]
    assert line.split()[:5] == ["40", "3", "*", "*", "*"] and f"-m {name} --once" in line
    assert 'cron_heartbeat("pipeline.opportunity_outcome_update")' in (backend / "pipeline" / "opportunity_outcome_update.py").read_text()
    source = (backend / "data" / "opportunity_outcome_data.py").read_text() + (backend / "scoring" / "opportunity_outcomes.py").read_text()
    assert "fmp_client" not in source and "get_or_fetch" not in source
