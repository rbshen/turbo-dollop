"""data/opportunity_flag_outcome_data.py + the extended pipeline/opportunity_outcome_update.py: the daily flags' outcomes priced by the SAME
updater with the SAME engine (flag session as the as-of date, entry = next session's open, 10% intraday stop, price-only, SPY and sector
benchmarks, the 14-day censor grace), without touching the weekly outcome rows and without double-counting."""

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import data.opportunity_flag_outcome_data as fo
import data.opportunity_outcome_data as ou
import pipeline.opportunity_outcome_update as job
from core.models import (
    OpportunityDailyFlag,
    OpportunityFlagOutcome,
    OpportunityOutcome,
    OpportunityOutcomeRun,
    OpportunityRun,
    OpportunitySnapshotRow,
)
from scoring import opportunity_outcomes as eng

AS_OF = date(2026, 10, 9)  # the weekly list
FLAG_DATE = date(2026, 10, 12)  # the session the flags fired on (Monday)


def sessions_after(day: date, n: int) -> list[date]:
    out, d = [], day
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def series(dates, start, drift=0.0, lows=None) -> pd.DataFrame:
    rows, p = [], start
    for d in dates:
        o, c = p, p * (1 + drift)
        rows.append((o, max(o, c) * 1.005, (lows or {}).get(d, min(o, c) * 0.995), c, 1e6))
        p = c
    return pd.DataFrame(rows, index=pd.DatetimeIndex(dates), columns=["open", "high", "low", "close", "volume"])


def now_after(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 0, tzinfo=timezone.utc) + timedelta(days=1)


class World:
    def __init__(self, engine):
        self.engine = engine
        self.frames: dict[str, pd.DataFrame] = {}
        self.reads: list[list[str]] = []

    def set_bars(self, n: int):
        """`n` sessions AFTER the flag session (so the entry bar is dates[0])."""
        self.dates = sessions_after(FLAG_DATE, n)
        self.frames["SPY"] = series([FLAG_DATE] + self.dates, 400.0, 0.001)
        self.frames["XLK"] = series([FLAG_DATE] + self.dates, 200.0, 0.002)
        self.frames["AAA"] = series([FLAG_DATE] + self.dates, 100.0, 0.003)  # Technology
        self.frames["CCC"] = series([FLAG_DATE] + self.dates, 50.0, 0.0, lows={self.dates[2]: 40.0} if n > 2 else None)  # stops out on day 3
        self.frames["QQQX"] = series([FLAG_DATE] + self.dates, 30.0, 0.001)  # an ETF: no sector
        self.now = now_after(self.dates[-1])

    def add_flag(self, ticker: str, trigger: str = "D3.pullback_to_ma.v1", sector: str | None = "Technology", close: float = 100.0, list_as_of: date = AS_OF) -> int:
        with Session(self.engine) as s:
            f = OpportunityDailyFlag(list_as_of_date=list_as_of, ticker=ticker, trigger_id=trigger, trigger_version="1", list_name="momentum", tier="quality",
                                     flag_date=FLAG_DATE, observed_at=datetime(2026, 10, 13, 3, 45), close=close, sector=sector)
            s.add(f)
            s.commit()
            return f.id

    def flag_rows(self) -> dict[tuple[str, int], OpportunityFlagOutcome]:
        with Session(self.engine) as s:
            return {(o.ticker, o.horizon): o for o in s.exec(select(OpportunityFlagOutcome)).all()}

    def weekly_rows(self) -> dict[tuple[str, int], OpportunityOutcome]:
        with Session(self.engine) as s:
            return {(o.ticker, o.horizon): o for o in s.exec(select(OpportunityOutcome)).all()}


@pytest.fixture
def world(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(ou, "engine", engine)
    w = World(engine)
    with Session(engine) as s:
        s.add(OpportunityRun(id=1, kind="weekly", as_of_date=AS_OF, last_bar_date=AS_OF, universe_size=1, rules_hash="h", rules_version="2",
                             score_formula_version=6, created_at=datetime(2026, 10, 10, 4, 0)))
        s.add(OpportunitySnapshotRow(run_id=1, list_name="momentum", ticker="AAA", tier="quality", list_order=1, rule_ids_json="[]", sector="Technology", close=100.0))
        s.commit()

    def fake_read(tickers, lookback_days, reference=None):
        w.reads.append(list(tickers))
        return {t: w.frames[t] for t in tickers if t in w.frames}

    monkeypatch.setattr(ou, "read_cached_daily_bars_batch", fake_read)
    monkeypatch.setattr(ou, "load_tracked_universe", lambda session: ["AAA", "CCC"])
    monkeypatch.setattr(ou, "load_etf_universe", lambda session: ["QQQX"])
    monkeypatch.setattr(job, "LOG_PATH", tmp_path / "opportunity_outcome_update.log")
    monkeypatch.setattr(job, "init_db", lambda: None)
    monkeypatch.setattr(ou, "datetime", type("DT", (datetime,), {"now": classmethod(lambda cls, tz=None: w.now if tz else w.now.replace(tzinfo=None))}))
    w.set_bars(8)
    return w


def update(w: World, **kw):
    return fo.update_outcomes_and_flags(now=w.now, **kw)


# --- the pricing: same engine, flag session as the as-of date ---------------------------------------------------------------------------


def test_every_flag_gets_four_outcome_rows_priced_from_the_flag_session(world):
    world.add_flag("AAA")
    result = update(world)
    rows = world.flag_rows()
    assert len(rows) == 4 and {h for (_t, h) in rows} == {5, 10, 20, 60}
    assert result.flag_rows == 1 and result.flag_seeded == 4 and result.status == "success"
    r5, r10 = rows[("AAA", 5)], rows[("AAA", 10)]
    assert r5.status == "complete" and r5.entry_date == world.dates[0] and r5.entry_open == pytest.approx(world.frames["AAA"].loc[pd.Timestamp(world.dates[0]), "open"])
    assert r5.exit_date == world.dates[5] and r5.forward_return == pytest.approx(r5.exit_close / r5.entry_open - 1)
    assert r10.status == "pending" and r10.forward_return is None and r10.entry_date == world.dates[0]  # the path so far, no return yet
    assert r5.trigger_id == "D3.pullback_to_ma.v1" and r5.flag_date == FLAG_DATE and r5.trigger_version == "1" and r5.provenance == "live"


def test_the_entry_gap_is_measured_against_the_flags_frozen_close(world):
    world.add_flag("AAA", close=80.0)
    update(world)
    gap = world.flag_rows()[("AAA", 5)]
    assert gap.entry_gap_pct == pytest.approx(world.frames["AAA"].loc[pd.Timestamp(world.dates[0]), "open"] / 80.0 - 1) and gap.entry_gap_flag is True  # a 25%+ gap


def test_the_stop_is_recorded_on_pending_rows_and_a_buy_and_hold_return_is_untouched(world):
    world.add_flag("CCC", sector="Energy", close=50.0)
    update(world)
    rows = world.flag_rows()
    assert rows[("CCC", 5)].stop_hit and rows[("CCC", 5)].stop_date == world.dates[2]
    assert rows[("CCC", 10)].status == "pending" and rows[("CCC", 10)].stop_hit
    assert rows[("CCC", 5)].forward_return == pytest.approx(0.0, abs=1e-9)  # the stop never changes the buy-and-hold return


def test_sector_and_spy_benchmarks_and_an_etf_with_none(world):
    world.add_flag("AAA")
    world.add_flag("QQQX", sector=None)
    update(world)
    rows = world.flag_rows()
    a, e = rows[("AAA", 5)], rows[("QQQX", 5)]
    assert a.sector_etf == "XLK" and a.excess_vs_sector == pytest.approx(a.forward_return - a.sector_return) and a.excess_vs_spy == pytest.approx(a.forward_return - a.spy_return)
    assert e.sector_etf is None and e.sector_return is None and e.spy_return is not None


def test_one_flag_per_trigger_is_priced_separately(world):
    world.add_flag("AAA", trigger="D1.entry_event.v1")
    world.add_flag("AAA", trigger="D3.pullback_to_ma.v1")
    update(world)
    with Session(world.engine) as s:
        rows = s.exec(select(OpportunityFlagOutcome)).all()
    assert len(rows) == 8 and len({(r.flag_id, r.horizon) for r in rows}) == 8


# --- the weekly outcomes are untouched, nothing is double-counted ----------------------------------------------------------------------


def snapshot(rows: dict) -> dict:
    return {k: {c: getattr(o, c) for c in o.__table__.columns.keys()} for k, o in rows.items()}


def test_pricing_flags_changes_no_weekly_outcome_row_and_adds_none(world):
    first = update(world)  # no flags yet: the weekly rows are seeded and priced
    before = snapshot(world.weekly_rows())
    assert len(before) == 4 and "flag outcomes" not in first.detail()
    world.add_flag("AAA")
    after_result = update(world)
    assert snapshot(world.weekly_rows()) == before  # byte-for-byte the same rows
    assert len(world.flag_rows()) == 4 and "flag outcomes: 1 flag(s)" in after_result.detail()


def test_a_flag_is_priced_even_when_the_weekly_outcomes_are_all_final_or_spy_has_no_new_bar(world):
    job.main()  # through the job, so the run log carries the SPY bar date the next run compares with
    again = job.main()
    assert again.status == "noop"  # nothing new anywhere
    world.add_flag("AAA")
    third = job.main()  # SPY has no newer bar, but the new flag has no outcome rows yet
    assert third.status == "success" and len(world.flag_rows()) == 4 and third.flag_seeded == 4


def test_the_weekly_message_is_unchanged_when_there_are_no_flags(world):
    result = update(world)
    assert "flag" not in result.detail() and result.flag_rows == 0
    assert "flags" not in ou.summary_of(result)


def test_a_rerun_creates_no_duplicates_and_changes_nothing(world):
    world.add_flag("AAA")
    update(world)
    before = snapshot(world.flag_rows())
    ids = {k: o.id for k, o in world.flag_rows().items()}
    again = update(world, as_of=AS_OF)  # targeted: skips the new-SPY-bar check
    assert snapshot(world.flag_rows()) == before and {k: o.id for k, o in world.flag_rows().items()} == ids
    assert again.flag_seeded == 0 and again.flag_updated == 0
    assert len(world.flag_rows()) == 4


def test_complete_rows_are_frozen_and_pending_ones_move_forward(world):
    world.add_flag("AAA")
    world.set_bars(6)
    update(world)
    done = world.flag_rows()[("AAA", 5)]
    assert done.status == "complete" and world.flag_rows()[("AAA", 10)].status == "pending"
    frozen = (done.id, done.computed_at, done.forward_return)
    world.set_bars(12)
    result = update(world)
    rows = world.flag_rows()
    assert (rows[("AAA", 5)].id, rows[("AAA", 5)].computed_at, rows[("AAA", 5)].forward_return) == frozen  # never recomputed
    assert rows[("AAA", 10)].status == "complete" and result.flag_updated == 3  # 10 completes; 20 and 60 move their path


def test_targeting_a_weekly_list_prices_only_its_flags(world):
    world.add_flag("AAA", list_as_of=AS_OF)
    world.add_flag("QQQX", sector=None, list_as_of=date(2026, 10, 2))
    result = update(world, as_of=AS_OF)
    assert {t for (t, _h) in world.flag_rows()} == {"AAA"} and result.flag_rows == 1
    by_run = update(world, run_id=1)
    assert by_run.flag_rows == 1 and by_run.flag_seeded == 0


# --- censoring, failures, dry run ----------------------------------------------------------------------------------------------------------


def test_a_flag_whose_ticker_stops_getting_bars_is_censored_then_revived_inside_the_grace(world):
    world.set_bars(20)
    full = world.frames["CCC"]
    world.frames["CCC"] = full.iloc[:5]  # entry bar and three more, then nothing while SPY runs on
    world.add_flag("CCC", sector="Energy", close=50.0)
    update(world)
    row = world.flag_rows()[("CCC", 5)]
    assert row.status == "censored" and row.censor_reason == "stale" and row.first_censored_at is not None and row.forward_return is not None
    first_censored = row.first_censored_at
    world.frames["CCC"] = full  # the missing bars arrive within the 14 days
    update(world, as_of=AS_OF)
    revived = world.flag_rows()[("CCC", 5)]
    assert revived.status == "complete" and revived.censor_reason is None and revived.first_censored_at is None and first_censored is not None


def test_a_censored_flag_row_is_frozen_after_the_grace_period(world):
    world.set_bars(20)
    full = world.frames["CCC"]
    world.frames["CCC"] = full.iloc[:5]
    world.add_flag("CCC", sector="Energy", close=50.0)
    update(world)
    world.frames["CCC"] = full
    world.now = world.now + timedelta(days=eng.CENSOR_REVIVE_DAYS + 1)
    update(world, as_of=AS_OF)
    assert world.flag_rows()[("CCC", 5)].status == "censored"  # past the 14 days it stays frozen even though the data returned


def test_one_failing_ticker_leaves_its_rows_pending_and_makes_the_run_partial(world, monkeypatch):
    world.add_flag("AAA")
    world.add_flag("QQQX", sector=None)
    real = eng.compute_outcomes
    monkeypatch.setattr(ou.eng, "compute_outcomes", lambda **kw: (_ for _ in ()).throw(ValueError("x")) if kw["as_of_close"] == 100.0 and kw["sector_etf"] is None else real(**kw))
    result = update(world)
    assert result.status == "partial" and list(result.failed) == ["QQQX"]
    rows = world.flag_rows()
    assert rows[("AAA", 5)].status == "complete" and rows[("QQQX", 5)].status == "pending" and rows[("QQQX", 5)].entry_open is None


def test_a_dry_run_writes_nothing(world):
    world.add_flag("AAA")
    result = update(world, dry_run=True)
    assert result.status == "dry_run" and result.flag_rows == 1 and result.flag_seeded == 4
    assert world.flag_rows() == {} and world.weekly_rows() == {}


# --- through the job: one invocation, one log row ------------------------------------------------------------------------------------------


def test_the_job_prices_weekly_and_flag_outcomes_in_one_invocation_and_logs_both(world):
    world.add_flag("AAA")
    result = job.main()
    assert result.status == "success"
    with Session(world.engine) as s:
        (log,) = s.exec(select(OpportunityOutcomeRun)).all()
    assert log.status == "success" and log.spy_last_bar_date == world.dates[-1]
    summary = json.loads(log.summary_json)
    assert summary["stops"] == 0 and summary["flags"]["flag_rows"] == 1 and summary["flags"]["seeded"] == 4
    assert log.message == result.message() and "flag" not in log.message  # the quiet message; the flag part is in detail()
    assert len(world.weekly_rows()) == 4 and len(world.flag_rows()) == 4
    assert job.main().status == "noop"  # the next run: nothing new anywhere


def test_the_flag_pricing_makes_no_fmp_call():
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "data" / "opportunity_flag_outcome_data.py").read_text()
    assert "fmp_client" not in source and "get_or_fetch" not in source
