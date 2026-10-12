"""data/opportunity_daily_data.py + pipeline/opportunity_daily_flags.py over a throwaway database and synthetic cached bars: each trigger
(fires, does not fire, not covered, incomplete), the cohort rule including Saturday handling, the lookahead guards (created_at, same-session
events excluded), the no-op / failure heartbeat, idempotent reruns, the dry run, the catch-up and the gaps, and the wiring (registered,
unscheduled, planned slot between the outcome updater and the Saturday job)."""

import argparse
import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import data.opportunity_daily_data as od
import data.opportunity_outcome_data as ou
import pipeline.opportunity_daily_flags as job
from core.models import (
    CronRunLog,
    OpportunityDailyFlag,
    OpportunityDailyRun,
    OpportunityOutcomeRun,
    OpportunityRun,
    OpportunitySnapshotRow,
    TechnicalEntrySignalEvent,
    TrendAnalysis,
    WarrenSignalEvent,
)
from scoring import opportunity_triggers as trig

R1, R2 = date(2026, 10, 2), date(2026, 10, 9)  # two weekly lists (Fridays)
FRI, MON = date(2026, 10, 9), date(2026, 10, 12)
NOW = datetime(2026, 10, 13, 3, 45, tzinfo=timezone.utc)  # Tuesday 03:45 UTC: Monday's session is complete
SESSIONS = [d.date() for d in pd.bdate_range("2026-09-28", "2026-10-12")]
D1, D2, D3 = trig.TRIGGER_D1, trig.TRIGGER_D2, trig.TRIGGER_D3
UP = ("pipeline.nightly_trend_calculation", "pipeline.nightly_entry_signal_calculation", "pipeline.nightly_warren_signal_calculation")


def bars(start: float = 100.0) -> pd.DataFrame:
    rows = [(start, start * 1.01, start * 0.99, start * 1.001, 1e6)] * len(SESSIONS)
    return pd.DataFrame(rows, index=pd.DatetimeIndex(SESSIONS), columns=["open", "high", "low", "close", "volume"])


class World:
    def __init__(self, engine):
        self.engine = engine
        self.frames: dict[str, pd.DataFrame] = {}
        self.monitored: list[str] = []

    # --- fixtures of the stored world ---
    def add_run(self, run_id: int, as_of: date, rows: list[dict]) -> None:
        with Session(self.engine) as s:
            s.add(OpportunityRun(id=run_id, kind="weekly", as_of_date=as_of, last_bar_date=as_of, universe_size=len(rows), rules_hash="h", rules_version="2",
                                 score_formula_version=6, created_at=datetime.combine(as_of + timedelta(days=1), datetime.min.time())))
            for order, r in enumerate(rows, 1):
                r = dict(r)
                tags, inputs = r.pop("tags", {}), r.pop("inputs", {})
                s.add(OpportunitySnapshotRow(run_id=run_id, list_order=order, rule_ids_json="[]", tags_json=json.dumps(tags), inputs_json=json.dumps(inputs),
                                             close=r.pop("close", 100.0), sector=r.pop("sector", "Technology"), **r))
                self.frames.setdefault(r["ticker"], bars())
            s.commit()

    def stage(self, ticker: str, stage: str, vs: float = 10.0, slope: float = 1.0, rs: float = 1.0, pending: str | None = None, bars_as_of: date = MON) -> None:
        with Session(self.engine) as s:
            s.merge(TrendAnalysis(ticker=ticker, computed_at=datetime(2026, 10, 13, 1, 5), weinstein_stage=stage, weinstein_vs_ma_pct=vs,
                                  weinstein_ma_slope_pct=slope, weinstein_mansfield_rs=rs, weinstein_pending_direction=pending, bars_as_of=bars_as_of))
            s.commit()

    def warren(self, ticker: str, fired: datetime, created: datetime, kind: str = "yellow_up") -> None:
        with Session(self.engine) as s:
            s.add(WarrenSignalEvent(ticker=ticker, timeframe="2h", signal_kind=kind, fired_at=fired, created_at=created))
            s.commit()

    def bb(self, ticker: str, fired: datetime, created: datetime) -> None:
        with Session(self.engine) as s:
            s.add(TechnicalEntrySignalEvent(ticker=ticker, signal_type="bb_rsi", timeframe="2h", fired_at=fired, created_at=created))
            s.commit()

    def cron(self, job_name: str, started: datetime, status: str = "success") -> None:
        with Session(self.engine) as s:
            s.add(CronRunLog(job_name=job_name, started_at=started, finished_at=started + timedelta(minutes=1), status=status))
            s.commit()

    def night(self, night: date, status: str = "success", skip: tuple[str, ...] = ()) -> None:
        """The three upstream jobs of the night starting at 00:00 UTC on `night`."""
        for name, hhmm in zip(UP, ((1, 5), (1, 20), (1, 25))):
            if name not in skip:
                self.cron(name, datetime(night.year, night.month, night.day, *hhmm), status)

    def last_run(self, spy_date: date) -> None:
        with Session(self.engine) as s:
            s.add(OpportunityDailyRun(started_at=datetime(2026, 10, 9, 3, 45), status="success", spy_last_bar_date=spy_date))
            s.commit()

    # --- reads ---
    def flags(self) -> dict[tuple[date, str, str], OpportunityDailyFlag]:
        with Session(self.engine) as s:
            return {(f.list_as_of_date, f.ticker, f.trigger_id): f for f in s.exec(select(OpportunityDailyFlag)).all()}

    def runs(self) -> list[OpportunityDailyRun]:
        with Session(self.engine) as s:
            return list(s.exec(select(OpportunityDailyRun).order_by(OpportunityDailyRun.id)).all())

    def go(self, **kw):
        return od.run_daily(now=NOW, **kw)


def row(ticker: str, list_name: str, stage: str, tier: str = "quality", vs: float | None = 12.0, **kw) -> dict:
    return {"ticker": ticker, "list_name": list_name, "tier": tier, "weinstein_stage": stage, "vs_ma_pct": vs, "ma_slope_pct": 1.0, "mansfield_rs": 1.0, **kw}


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(od, "engine", engine)
    monkeypatch.setattr(ou, "engine", engine)
    w = World(engine)
    w.frames["SPY"] = bars(400.0)
    monkeypatch.setattr(ou, "read_cached_daily_bars_batch", lambda tickers, lookback_days, reference=None: {t: w.frames[t] for t in tickers if t in w.frames})
    monkeypatch.setattr(od, "list_monitored_tickers", lambda session: (list(w.monitored), []))
    w.night(date(2026, 10, 13))  # the night after Monday's session: all three upstream jobs succeeded
    return w


def standard(w: World) -> None:
    """Reversal: RA covered + stage up + warren event (fires D1 and D2); RB not covered + base -> advance (D2 only); RC covered, nothing happens;
    RD covered with a LATE event. Momentum: MA pulls back (D3); MB is a deep_pullback with a BB+RSI event (D1) but no pullback; MC has an event
    but no deep_pullback tag (D1 does not apply)."""
    w.monitored = ["RA", "RC", "RD", "MB", "MC"]
    w.add_run(2, R2, [
        row("RA", "reversal", "decline"),
        row("RB", "reversal", "base", tier="momentum_only"),
        row("RC", "reversal", "decline"),
        row("RD", "reversal", "decline"),
        row("MA", "momentum", "advance", vs=12.0),
        row("MB", "momentum", "advance", vs=9.0, tags={"deep_pullback": True}),
        row("MC", "momentum", "advance", vs=10.0),
    ])
    w.stage("RA", "base"); w.stage("RB", "advance"); w.stage("RC", "decline"); w.stage("RD", "decline")
    w.stage("MA", "advance", vs=3.0); w.stage("MB", "advance", vs=8.0); w.stage("MC", "advance", vs=9.0)
    mon_close = datetime(2026, 10, 12, 15, 30)
    w.warren("RA", mon_close, datetime(2026, 10, 13, 1, 25))
    w.bb("MB", datetime(2026, 10, 12, 11, 30), datetime(2026, 10, 13, 1, 20))
    w.bb("MC", datetime(2026, 10, 12, 11, 30), datetime(2026, 10, 13, 1, 20))
    w.warren("RD", datetime(2026, 10, 12, 10, 30), datetime(2026, 10, 13, 14, 0))  # written after Tuesday's open


# --- each trigger: fires, does not fire, not covered ---------------------------------------------------------------------------------


def test_the_standard_night_fires_each_trigger_where_it_should(world):
    standard(world)
    result = world.go()
    assert result.status == "success" and result.session_date == MON and result.list_as_of_date == R2 and result.watched == 7
    assert set(world.flags()) == {(R2, "RA", D1), (R2, "RA", D2), (R2, "RB", D2), (R2, "MA", D3), (R2, "MB", D1)}
    assert result.flags_created == 5
    assert {t: c.flagged for t, c in result.counts.items()} == {D1: 2, D2: 2, D3: 1}


def test_d1_fires_on_a_warren_or_bb_rsi_event_and_freezes_the_evidence(world):
    standard(world)
    world.go()
    ra, mb = world.flags()[(R2, "RA", D1)], world.flags()[(R2, "MB", D1)]
    assert ra.flag_date == MON and ra.trigger_version == "1" and ra.list_name == "reversal" and ra.tier == "quality" and ra.close == pytest.approx(100.1)
    assert json.loads(ra.inputs_json)["evidence"]["events"][0]["source"] == "warren"
    assert json.loads(mb.inputs_json)["evidence"]["events"][0]["source"] == "bb_rsi"
    assert json.loads(mb.inputs_json)["list_row"]["deep_pullback"] is True
    assert ra.observed_at == NOW.replace(tzinfo=None)


def test_d1_ignores_gray_and_down_events(world):
    standard(world)
    world.warren("RC", datetime(2026, 10, 12, 10, 30), datetime(2026, 10, 13, 1, 25), kind="gray_up")
    world.warren("RC", datetime(2026, 10, 12, 12, 30), datetime(2026, 10, 13, 1, 25), kind="yellow_down")
    world.go()
    assert (R2, "RC", D1) not in world.flags()


def test_d1_does_not_apply_to_a_plain_momentum_name(world):
    standard(world)
    result = world.go()
    assert (R2, "MC", D1) not in world.flags() and "MC" not in result.not_covered.get(D1, [])


def test_d2_covers_every_upgrade_and_only_reversal_names(world):
    standard(world)
    world.go()
    flags = world.flags()
    assert json.loads(flags[(R2, "RA", D2)].inputs_json)["evidence"]["upgrade"] == trig.UPGRADE_STAGE
    assert json.loads(flags[(R2, "RB", D2)].inputs_json)["evidence"]["observed"]["stage"] == "advance"
    assert (R2, "RC", D2) not in flags  # still Decline
    assert not any(k[2] == D2 and k[1].startswith("M") for k in flags)


def test_d2_flags_a_new_pending_advance(world):
    standard(world)
    world.stage("RC", "decline", pending="advance")
    world.go()
    assert json.loads(world.flags()[(R2, "RC", D2)].inputs_json)["evidence"]["upgrade"] == trig.UPGRADE_PENDING


def test_d3_fires_inside_five_percent_and_not_above_it(world):
    standard(world)
    world.go()
    flags = world.flags()
    assert (R2, "MA", D3) in flags and (R2, "MB", D3) not in flags and (R2, "MC", D3) not in flags  # 8% and 9% are above the ceiling
    evidence = json.loads(flags[(R2, "MA", D3)].inputs_json)
    assert evidence["evidence"]["observed"]["vs_ma_pct"] == 3.0 and evidence["list_row"]["vs_ma_pct"] == 12.0 and evidence["list_row"]["already_at_ma_on_list"] is False


def test_d3_needs_a_rising_ma_positive_rs_and_an_advance(world):
    standard(world)
    world.stage("MB", "advance", vs=2.0, slope=-0.1)
    world.stage("MC", "advance", vs=2.0, rs=-1.0)
    world.go()
    assert (R2, "MB", D3) not in world.flags() and (R2, "MC", D3) not in world.flags()


def test_a_name_already_at_the_ma_on_the_list_date_is_marked_in_the_frozen_inputs(world):
    world.monitored = []
    world.add_run(2, R2, [row("MA", "momentum", "advance", vs=4.0)])
    world.stage("MA", "advance", vs=3.5)
    world.go()
    assert json.loads(world.flags()[(R2, "MA", D3)].inputs_json)["list_row"]["already_at_ma_on_list"] is True


# --- not covered, incomplete, no flag: three different things ------------------------------------------------------------------------


def test_a_name_off_the_monitored_lists_is_not_covered_for_d1_and_never_no_flag(jobbed):
    world = jobbed
    standard(world)
    world.warren("RB", datetime(2026, 10, 12, 10, 30), datetime(2026, 10, 13, 1, 25))  # an event exists, but nobody watches RB
    result = beat()
    assert result.not_covered == {D1: ["RB"]} and result.counts[D1].not_covered == 1
    assert (R2, "RB", D1) not in world.flags()
    (run,) = world.runs()
    assert json.loads(run.not_covered_json) == {D1: ["RB"]}
    assert "RB" not in json.dumps(json.loads(run.incomplete_json))


def test_an_upstream_job_that_did_not_succeed_makes_its_triggers_incomplete_not_no_flag(jobbed):
    world = jobbed
    standard(world)
    with Session(world.engine) as s:
        for r in s.exec(select(CronRunLog).where(CronRunLog.job_name == "pipeline.nightly_warren_signal_calculation")).all():
            r.status = "failure"
            s.add(r)
        s.commit()
    result = beat()
    assert set(result.incomplete) == {D1}
    assert set(result.incomplete[D1]) == {"RA", "RC", "RD", "MB"}  # the covered D1 names; RB is not covered
    assert all(reason.startswith(trig.INCOMPLETE_UPSTREAM) and "nightly_warren_signal_calculation=failure" in reason for reason in result.incomplete[D1].values())
    assert (R2, "RA", D1) not in world.flags() and (R2, "RA", D2) in world.flags()  # D2 reads the stage job, which succeeded
    (run,) = world.runs()
    assert json.loads(run.upstream_json)[MON.isoformat()]["pipeline.nightly_warren_signal_calculation"] == "failure"


def test_a_missing_trend_job_makes_d2_and_d3_incomplete(world):
    standard(world)
    with Session(world.engine) as s:
        for r in s.exec(select(CronRunLog).where(CronRunLog.job_name == "pipeline.nightly_trend_calculation")).all():
            s.delete(r)
        s.commit()
    result = world.go()
    assert set(result.incomplete) == {D2, D3} and "nightly_trend_calculation=missing" in result.incomplete[D3]["MA"]
    assert {k[2] for k in world.flags()} == {D1}


def test_a_skipped_job_is_not_a_success(world):
    standard(world)
    with Session(world.engine) as s:
        for r in s.exec(select(CronRunLog).where(CronRunLog.job_name == "pipeline.nightly_entry_signal_calculation")).all():
            r.status = "skipped"
            s.add(r)
        s.commit()
    assert set(world.go().incomplete) == {D1}


def test_a_name_with_no_final_bar_for_the_session_is_incomplete(world):
    standard(world)
    world.frames["RA"] = world.frames["RA"].iloc[:-1]  # no Monday bar (or only a provisional one, which the bars read drops)
    result = world.go()
    assert result.incomplete[D1]["RA"] == trig.INCOMPLETE_NO_BAR and result.incomplete[D2]["RA"] == trig.INCOMPLETE_NO_BAR
    assert not any(k[1] == "RA" for k in world.flags())


def test_a_provisional_last_bar_is_not_used(world, monkeypatch):
    standard(world)
    monkeypatch.setattr(ou, "_provisional_last_bar_tickers", lambda session, tickers, span, now: {"RA"})
    result = world.go()
    assert result.incomplete[D1]["RA"] == trig.INCOMPLETE_NO_BAR and (R2, "RA", D1) not in world.flags()


def test_a_stale_stage_row_is_incomplete_not_no_flag(world):
    standard(world)
    world.stage("MA", "advance", vs=3.0, bars_as_of=FRI)
    result = world.go()
    assert result.incomplete[D3]["MA"].startswith(trig.INCOMPLETE_STALE_STAGE) and (R2, "MA", D3) not in world.flags()


def test_a_bars_read_failure_is_incomplete_and_reported_as_failed(world, monkeypatch):
    standard(world)
    real = ou._read_bars
    monkeypatch.setattr(ou, "_read_bars", lambda tickers, lookback, now: real(tickers, lookback, now) if tickers == ["SPY"] else (_ for _ in ()).throw(OSError("disk")))
    result = world.go()
    assert len(result.failed) == 7 and result.attempted == 7 and set(result.incomplete[D1]) == {"RA", "RC", "RD", "MB"}
    assert world.flags() == {}


# --- the cohort rule, Saturday handling, lookahead guards ----------------------------------------------------------------------------


def test_friday_signals_count_against_the_previous_list_never_the_one_built_as_of_friday(world):
    """Saturday 03:45 UTC, before the 04:00 weekly job: Friday's session is judged against the list of the Friday before. A name that is only
    on the list built as of Friday is not watched for Friday's own signals (its B3 rule already read them)."""
    world.monitored = ["OLD", "NEW"]
    world.add_run(1, R1, [row("OLD", "reversal", "decline")])
    world.add_run(2, R2, [row("OLD", "reversal", "decline"), row("NEW", "reversal", "decline")])
    for name in ("OLD", "NEW"):
        world.stage(name, "decline", bars_as_of=FRI)
    world.warren("OLD", datetime(2026, 10, 9, 15, 30), datetime(2026, 10, 10, 1, 25))
    world.warren("NEW", datetime(2026, 10, 9, 15, 30), datetime(2026, 10, 10, 1, 25))
    world.night(date(2026, 10, 10))
    now = datetime(2026, 10, 10, 3, 45, tzinfo=timezone.utc)  # Saturday
    result = od.run_daily(now=now)
    assert result.session_date == FRI and result.list_as_of_date == R1 and result.watched == 1
    assert set(world.flags()) == {(R1, "OLD", D1)}
    assert world.flags()[(R1, "OLD", D1)].flag_date == FRI


def test_the_first_session_after_the_new_list_uses_the_new_list(world):
    world.monitored = ["OLD", "NEW"]
    world.add_run(1, R1, [row("OLD", "reversal", "decline")])
    world.add_run(2, R2, [row("NEW", "reversal", "decline")])
    world.stage("NEW", "decline"); world.stage("OLD", "decline")
    world.warren("NEW", datetime(2026, 10, 12, 10, 30), datetime(2026, 10, 13, 1, 25))
    world.warren("OLD", datetime(2026, 10, 12, 10, 30), datetime(2026, 10, 13, 1, 25))  # OLD fell off the list: no longer watched
    world.go()
    assert set(world.flags()) == {(R2, "NEW", D1)}


def test_a_pool_name_that_is_not_listed_is_never_flagged(world):
    world.monitored = ["POOL"]
    world.add_run(2, R2, [row("LISTED", "reversal", "decline")])
    world.frames["POOL"] = bars()
    world.stage("POOL", "base"); world.stage("LISTED", "decline")
    world.warren("POOL", datetime(2026, 10, 12, 10, 30), datetime(2026, 10, 13, 1, 25))
    world.go()
    assert world.flags() == {}


def test_a_late_event_is_not_knowable_before_the_next_open_and_is_a_gap_not_a_flag(world):
    standard(world)
    result = world.go()
    assert (R2, "RD", D1) not in world.flags()
    assert {"type": "late_event", "ticker": "RD", "session": MON.isoformat(), "created_at": "2026-10-13T14:00:00"} in result.gaps
    assert result.counts[D1].evaluated >= 1  # RD was judged (no flag), it is not incomplete


def test_an_event_on_the_event_date_alone_is_not_enough_created_at_decides(world):
    """Same event date, one row written overnight (knowable), one written after the next open (not)."""
    world.monitored = ["EARLY", "LATE"]
    world.add_run(2, R2, [row("EARLY", "reversal", "decline"), row("LATE", "reversal", "decline")])
    world.stage("EARLY", "decline"); world.stage("LATE", "decline")
    world.warren("EARLY", datetime(2026, 10, 12, 10, 30), datetime(2026, 10, 13, 1, 25))
    world.warren("LATE", datetime(2026, 10, 12, 10, 30), datetime(2026, 10, 13, 13, 31))
    world.go()
    assert set(world.flags()) == {(R2, "EARLY", D1)}


def test_events_dated_before_the_session_do_not_count_for_it(world):
    world.monitored = ["RA"]
    world.add_run(2, R2, [row("RA", "reversal", "decline")])
    world.stage("RA", "decline")
    world.warren("RA", datetime(2026, 10, 9, 15, 30), datetime(2026, 10, 10, 1, 25))  # Friday's own signal: in the list's inputs, not a flag
    world.go()
    assert world.flags() == {}


def test_a_name_flags_a_trigger_once_per_list(world):
    standard(world)
    world.go()
    first = {k: f.id for k, f in world.flags().items()}
    # a later night: the pullback still holds, a new event arrives; nothing new is written for names that already flagged
    later = datetime(2026, 10, 14, 3, 45, tzinfo=timezone.utc)
    tue = date(2026, 10, 13)
    for name in ("SPY", "RA", "MA", "MB"):
        world.frames[name] = pd.concat([world.frames[name], bars().iloc[:1].set_axis(pd.DatetimeIndex([tue]))])
    world.stage("MA", "advance", vs=2.0, bars_as_of=tue)
    world.warren("RA", datetime(2026, 10, 13, 12, 30), datetime(2026, 10, 14, 1, 25))
    world.night(date(2026, 10, 14))
    again = od.run_daily(now=later)
    assert {k: f.id for k, f in world.flags().items()} == first
    assert again.flags_created == 0 and again.counts[D3].already_flagged == 1


# --- missed nights, the no-op rule, the dry run ---------------------------------------------------------------------------------------


def test_a_missed_night_catches_up_the_events_and_records_a_gap_for_the_stage_triggers(jobbed):
    world = jobbed
    world.monitored = ["N1", "N2"]
    world.add_run(1, R1, [row("N1", "reversal", "decline"), row("N2", "momentum", "advance")])
    world.add_run(2, R2, [row("N1", "reversal", "decline"), row("N2", "momentum", "advance", tags={"deep_pullback": True})])
    world.stage("N1", "decline"); world.stage("N2", "advance", vs=9.0)
    world.warren("N1", datetime(2026, 10, 9, 15, 30), datetime(2026, 10, 10, 1, 25))  # Friday: cohort R1
    world.bb("N2", datetime(2026, 10, 12, 11, 30), datetime(2026, 10, 13, 1, 20))  # Monday: cohort R2, a deep_pullback
    world.night(date(2026, 10, 10)); world.night(date(2026, 10, 11)); world.night(date(2026, 10, 12))
    world.last_run(date(2026, 10, 8))  # the last run saw Thursday: Friday and Monday were missed
    result = beat()
    assert result.sessions == [FRI, MON] and result.session_date == MON
    assert set(world.flags()) == {(R1, "N1", D1), (R2, "N2", D1)}
    assert world.flags()[(R1, "N1", D1)].flag_date == FRI and world.flags()[(R2, "N2", D1)].flag_date == MON
    gaps = [g for g in result.gaps if g["type"] == "state_trigger_gap"]
    assert {(g["trigger"], g["session"]) for g in gaps} == {(D2, FRI.isoformat()), (D3, FRI.isoformat())}  # the stage triggers cannot be rebuilt for Friday
    assert result.counts[D2].evaluated == 1 and result.counts[D3].evaluated == 1  # Monday's stage rows are judged (N1 for D2, N2 for D3); Friday's are gaps
    run = world.runs()[-1]
    assert json.loads(run.sessions_json) == [FRI.isoformat(), MON.isoformat()] and len(json.loads(run.gaps_json)) == 2


def test_an_as_of_that_is_not_the_newest_session_cannot_judge_the_stage_triggers(world):
    world.monitored = ["RA"]
    world.add_run(1, R1, [row("RA", "reversal", "decline"), row("MA", "momentum", "advance")])
    world.stage("RA", "base"); world.stage("MA", "advance", vs=2.0)  # tonight's stage rows would fire D2 and D3 ... but they are Monday's, not Friday's
    world.warren("RA", datetime(2026, 10, 9, 15, 30), datetime(2026, 10, 10, 1, 25))
    world.night(date(2026, 10, 10)); world.night(date(2026, 10, 11)); world.night(date(2026, 10, 12))
    result = world.go(as_of=FRI)
    assert result.session_date == FRI and result.list_as_of_date == R1
    assert set(world.flags()) == {(R1, "RA", D1)}
    assert {(g["trigger"], g["session"]) for g in result.gaps if g["type"] == "state_trigger_gap"} == {(D2, FRI.isoformat()), (D3, FRI.isoformat())}


def test_as_of_must_be_a_cached_session(world):
    standard(world)
    with pytest.raises(ValueError, match="not a completed session"):
        world.go(as_of=date(2026, 10, 11))


def test_no_new_spy_bar_is_a_noop_using_this_jobs_own_last_seen_date(jobbed):
    standard(jobbed)
    beat()
    again = beat()
    assert again.status == "noop" and "no bar newer than" in again.reason and again.flags_created == 0


def test_the_outcome_updaters_spy_date_does_not_count(jobbed):
    standard(jobbed)
    with Session(jobbed.engine) as s:
        s.add(OpportunityOutcomeRun(started_at=datetime(2026, 10, 13, 3, 40), status="success", spy_last_bar_date=MON))
        s.commit()
    assert beat().status == "success" and len(jobbed.flags()) == 5


def test_no_list_before_the_session_is_a_noop(world):
    world.add_run(5, date(2026, 10, 12), [row("RA", "reversal", "decline")])  # a list dated the session itself judges nothing
    result = world.go()
    assert result.status == "noop" and "no weekly opportunity list dated before" in result.reason


def test_a_dry_run_computes_and_writes_nothing(world):
    standard(world)
    result = world.go(dry_run=True)
    assert result.status == "dry_run" and result.flags_created == 5 and len(result.new_flags) == 5
    assert world.flags() == {} and world.runs() == []


def test_a_rerun_for_a_targeted_session_adds_no_duplicate_flags(world):
    standard(world)
    world.go()
    before = {k: f.id for k, f in world.flags().items()}
    again = world.go(as_of=MON)
    assert {k: f.id for k, f in world.flags().items()} == before and again.flags_created == 0
    assert all(c.already_flagged >= 1 for c in again.counts.values())


# --- the job, its log row and the heartbeat ------------------------------------------------------------------------------------------


@pytest.fixture
def jobbed(world, monkeypatch, tmp_path):
    import core.cron_health as ch

    monkeypatch.setattr(job, "LOG_PATH", tmp_path / "opportunity_daily_flags.log")
    monkeypatch.setattr(job, "init_db", lambda: None)
    monkeypatch.setattr(ch, "engine", world.engine)
    real_run = od.run_daily
    monkeypatch.setattr(job, "run_daily", lambda **kw: real_run(now=NOW, **kw))
    return world


def beat(**kw):
    ns = argparse.Namespace(once=True, dry_run=False, as_of=None)
    for k, v in kw.items():
        setattr(ns, k, v)
    return job.run_scheduled(ns)


def beats(w: World):
    with Session(w.engine) as s:
        return [(r.status, r.error_summary) for r in s.exec(select(CronRunLog).where(CronRunLog.job_name == "pipeline.opportunity_daily_flags").order_by(CronRunLog.id)).all()]


def test_a_real_run_writes_one_log_row_and_a_green_heartbeat(jobbed):
    standard(jobbed)
    result = beat()
    assert result.status == "success"
    (log,) = jobbed.runs()
    assert log.status == "success" and log.session_date == MON and log.spy_last_bar_date == MON and log.list_as_of_date == R2 and log.flags_created == 5 and log.watched == 7
    assert json.loads(log.summary_json)["counts"][D1]["flagged"] == 2
    ((status, message),) = beats(jobbed)
    assert status == "success" and message == result.message() and "5 flag(s)" in message


def test_a_no_op_night_is_a_green_heartbeat_not_a_failure_or_a_skip(jobbed):
    standard(jobbed)
    beat()
    again = beat()
    assert again.status == "noop"
    rows = beats(jobbed)
    assert [s for s, _ in rows] == ["success", "success"] and rows[1][1].startswith("no-op: SPY has no bar newer than")
    assert [r.status for r in jobbed.runs()] == ["success", "noop"]


def test_an_exception_is_a_red_heartbeat_and_is_re_raised(jobbed):
    standard(jobbed)
    jobbed.frames.pop("SPY")
    with pytest.raises(RuntimeError, match="SPY"):
        beat()
    ((status, message),) = beats(jobbed)
    assert status == "failure" and "SPY" in message
    (log,) = jobbed.runs()
    assert log.status == "failure" and log.spy_last_bar_date is None  # a failed run stores no date, so the next run is not short-circuited


def test_incomplete_triggers_do_not_turn_the_heartbeat_red(jobbed):
    standard(jobbed)
    with Session(jobbed.engine) as s:
        for r in s.exec(select(CronRunLog).where(CronRunLog.job_name == "pipeline.nightly_warren_signal_calculation")).all():
            s.delete(r)
        s.commit()
    result = beat()
    assert result.incomplete and beats(jobbed)[-1][0] == "success"


def test_every_ticker_failing_to_read_is_a_red_heartbeat(jobbed, monkeypatch):
    standard(jobbed)
    real = ou._read_bars
    monkeypatch.setattr(ou, "_read_bars", lambda tickers, lookback, now: real(tickers, lookback, now) if tickers == ["SPY"] else (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(RuntimeError, match="all 7 attempted failed"):
        beat()
    assert beats(jobbed)[-1][0] == "failure"


def test_a_dry_run_writes_no_heartbeat_row_and_no_log_row(jobbed):
    standard(jobbed)
    result = beat(dry_run=True, once=False)
    assert result.status == "dry_run" and beats(jobbed) == [] and jobbed.runs() == [] and jobbed.flags() == {}


# --- tables, backup, registry, wiring ---------------------------------------------------------------------------------------------------


def test_the_flag_tables_are_in_the_nightly_backup(tmp_path):
    import gzip
    import sqlite3

    import pipeline.backup_db as backup_db

    db_path = tmp_path / "fathom.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(OpportunityDailyFlag(list_as_of_date=R2, ticker="RA", trigger_id=D1, trigger_version="1", list_name="reversal", tier="quality",
                                   flag_date=MON, observed_at=datetime(2026, 10, 13, 3, 45)))
        s.commit()
    engine.dispose()
    backup = backup_db.create_backup(db_path=db_path, backup_dir=tmp_path / "backups")
    restored = tmp_path / "restored.db"
    with gzip.open(backup, "rb") as src, open(restored, "wb") as dst:
        dst.write(src.read())
    conn = sqlite3.connect(str(restored))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"opportunitydailyflag", "opportunitydailyrun", "opportunityflagoutcome"} <= tables
    assert conn.execute("SELECT ticker FROM opportunitydailyflag").fetchone() == ("RA",)
    conn.close()


def test_the_job_is_registered_unscheduled_and_planned_between_the_updater_and_the_saturday_job():
    from pathlib import Path

    from core.cron_health import _EXPECTED_CADENCE_HOURS, CRON_JOB_NAMES, DISABLED_CRON_JOBS, JOB_METADATA

    backend = Path(__file__).resolve().parent.parent
    name = "pipeline.opportunity_daily_flags"
    assert name in CRON_JOB_NAMES and name in JOB_METADATA
    assert _EXPECTED_CADENCE_HOURS[name] == 36 and JOB_METADATA[name].cadence_group == "daily" and "no FMP calls" in JOB_METADATA[name].description
    updater = JOB_METADATA["pipeline.opportunity_outcome_update"].sort_minutes
    weekly = JOB_METADATA["pipeline.weekly_opportunity_snapshot"].sort_minutes
    assert JOB_METADATA[name].sort_minutes == 3 * 60 + 45 and updater + 5 <= JOB_METADATA[name].sort_minutes and JOB_METADATA[name].sort_minutes + 15 <= weekly
    # built and run by hand: listed as disabled and absent from crontab.txt (the wiring test requires both together)
    assert name in DISABLED_CRON_JOBS
    assert name not in (backend / "crontab.txt").read_text()
    assert 'cron_heartbeat("pipeline.opportunity_daily_flags")' in (backend / "pipeline" / "opportunity_daily_flags.py").read_text()


def test_the_daily_job_makes_no_fmp_call_and_does_not_touch_the_existing_outcome_or_pick_tables():
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent
    source = (backend / "data" / "opportunity_daily_data.py").read_text() + (backend / "scoring" / "opportunity_triggers.py").read_text()
    assert "fmp_client" not in source and "get_or_fetch" not in source
    assert "OpportunityOutcome," not in source and "OpportunityPick" not in source and "OpportunityPoolRow" not in source
