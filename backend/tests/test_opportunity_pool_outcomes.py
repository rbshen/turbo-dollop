"""data/opportunity_pool_outcome_data.py + the third step of pipeline/opportunity_outcome_update.py: the slim outcomes of the UNLISTED pool names,
priced by the same updater with the same engine over a throwaway database and synthetic cached bars -- schema and key, listed names excluded, idempotent
reruns, pending -> complete, the 14-day censor grace, the entry-gap flag, tier / assigned list / leveraged carried, existing outcome rows byte-identical,
the registry and backup, and the message / heartbeat conventions."""

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import data.opportunity_flag_outcome_data as fo
import data.opportunity_outcome_data as ou
import data.opportunity_pool_outcome_data as po
import pipeline.opportunity_outcome_update as job
from core.models import (
    OpportunityOutcome,
    OpportunityOutcomeRun,
    OpportunityPoolOutcome,
    OpportunityPoolRow,
    OpportunityRun,
    OpportunitySnapshotRow,
)
from scoring import opportunity_outcomes as eng
from scoring import opportunity_pool_outcomes as slim

AS_OF = date(2026, 10, 9)
CREATED = datetime(2026, 10, 10, 4, 0)


def sessions_after(as_of: date, n: int) -> list[date]:
    out, d = [], as_of
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def series(dates: list[date], start: float, drift: float = 0.0) -> pd.DataFrame:
    rows, p = [], start
    for d in dates:
        o, c = p, p * (1 + drift)
        rows.append((o, max(o, c) * 1.005, min(o, c) * 0.995, c, 1e6))
        p = c
    return pd.DataFrame(rows, index=pd.DatetimeIndex(dates), columns=["open", "high", "low", "close", "volume"])


def now_after(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 0, tzinfo=timezone.utc) + timedelta(days=1)


class World:
    def __init__(self, engine):
        self.engine = engine
        self.frames: dict[str, pd.DataFrame] = {}
        self.reads: list[list[str]] = []

    def set_bars(self, n_sessions: int):
        dates = sessions_after(AS_OF, n_sessions)
        self.dates = dates
        self.frames["SPY"] = series(dates, 400.0, 0.001)
        self.frames["XLK"] = series(dates, 200.0, 0.002)
        self.frames["LIST"] = series(dates, 100.0, 0.003)  # the listed name
        self.frames["AAA"] = series(dates, 100.0, 0.003)  # an unlisted Technology stock
        self.frames["BBB"] = series(dates, 50.0, -0.002)  # an unlisted momentum_only stock, Technology
        self.frames["QQQX"] = series(dates, 30.0, 0.001)  # an unlisted ETF: no sector
        self.frames["SOXL"] = series(dates, 20.0, 0.004)  # an unlisted leveraged ETF
        self.now = now_after(dates[-1])

    def pool_outcomes(self) -> dict[tuple[str, int], OpportunityPoolOutcome]:
        with Session(self.engine) as s:
            return {(o.ticker, o.horizon): o for o in s.exec(select(OpportunityPoolOutcome)).all()}

    def listed_outcomes(self) -> list[dict]:
        with Session(self.engine) as s:
            return [o.model_dump() for o in s.exec(select(OpportunityOutcome).order_by(OpportunityOutcome.ticker, OpportunityOutcome.horizon)).all()]


def pool_row(run_id, ticker, tier, assigned, listed, sector, close, leverage=None, name=None):
    return OpportunityPoolRow(
        run_id=run_id, ticker=ticker, tier=tier, assigned_list=assigned, listed=listed, list_name=("momentum" if listed else None), sector=sector,
        close=close, inputs_json=json.dumps({"is_etf": tier == "etf", "leverage": leverage}),
    )


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(ou, "engine", engine)
    w = World(engine)
    with Session(engine) as s:
        s.add(OpportunityRun(id=1, kind="weekly", as_of_date=AS_OF, last_bar_date=AS_OF, universe_size=5, rules_hash="h", rules_version="2",
                             score_formula_version=6, created_at=CREATED))
        s.add(OpportunitySnapshotRow(run_id=1, list_name="momentum", ticker="LIST", tier="quality", list_order=1, rule_ids_json="[]", sector="Technology", close=100.0))
        s.add(pool_row(1, "LIST", "quality", "momentum", True, "Technology", 100.0))
        s.add(pool_row(1, "AAA", "quality", "momentum", False, "Technology", 100.0))
        s.add(pool_row(1, "BBB", "momentum_only", "reversal", False, "Technology", 50.0))
        s.add(pool_row(1, "QQQX", "etf", None, False, None, 30.0))
        s.add(pool_row(1, "SOXL", "etf", "momentum", False, None, 20.0, leverage=3))
        s.commit()

    def fake_read(tickers, lookback_days, reference=None):
        w.reads.append(list(tickers))
        return {t: w.frames[t] for t in tickers if t in w.frames}

    monkeypatch.setattr(ou, "read_cached_daily_bars_batch", fake_read)
    monkeypatch.setattr(ou, "load_tracked_universe", lambda session: ["LIST", "AAA", "BBB"])
    monkeypatch.setattr(ou, "load_etf_universe", lambda session: ["QQQX", "SOXL"])
    w.set_bars(8)
    return w


def update(w: World, **kw):
    return po.update_pool_outcomes(now=w.now, **kw)


# --- the schema ---------------------------------------------------------------------------------------------------------------------


def test_the_table_has_the_proposed_columns_and_the_unique_key(world):
    insp = inspect(world.engine)
    cols = {c["name"]: str(c["type"]) for c in insp.get_columns("opportunitypooloutcome")}
    assert set(cols) == {
        "id", "run_id", "ticker", "horizon", "status", "censor_reason", "tier", "assigned_list", "leveraged", "entry_date", "entry_open",
        "entry_gap_pct", "entry_gap_flag", "exit_date", "forward_return", "spy_return", "excess_vs_spy", "sector_etf", "sector_return",
        "excess_vs_sector", "rules_version", "provenance", "computed_at", "first_censored_at",
    }
    # slim: none of the lists' stop / path fields, no exit close
    assert not {"stop_hit", "stop_date", "stop_fill_return", "worst_move", "best_move", "max_drawdown", "exit_close"} & set(cols)
    uniques = [u["column_names"] for u in insp.get_unique_constraints("opportunitypooloutcome")]
    assert ["run_id", "ticker", "horizon"] in uniques


def test_the_unique_key_rejects_a_duplicate(world):
    update(world)
    with Session(world.engine) as s:
        s.add(OpportunityPoolOutcome(run_id=1, ticker="AAA", horizon=5, status="pending", tier="quality", rules_version="2", computed_at=CREATED))
        with pytest.raises(Exception):
            s.commit()


# --- which names, and what is carried ------------------------------------------------------------------------------------------------


def test_only_unlisted_pool_names_get_rows_four_horizons_each(world):
    result = update(world)
    rows = world.pool_outcomes()
    assert {t for (t, _h) in rows} == {"AAA", "BBB", "QQQX", "SOXL"}  # LIST is listed: it has OpportunityOutcome, not a pool row
    assert len(rows) == 4 * 4 and {h for (_t, h) in rows} == {5, 10, 20, 60}
    assert result.pool_rows == 4 and result.pool_seeded == 16 and result.status == "success"
    assert all(o.provenance == "live" and o.rules_version == "2" and o.computed_at == ou._naive_utc(world.now) for o in rows.values())


def test_tier_assigned_list_and_leveraged_are_carried_from_the_pool_row(world):
    update(world)
    rows = world.pool_outcomes()
    assert (rows[("AAA", 5)].tier, rows[("AAA", 5)].assigned_list, rows[("AAA", 5)].leveraged) == ("quality", "momentum", False)
    assert (rows[("BBB", 20)].tier, rows[("BBB", 20)].assigned_list) == ("momentum_only", "reversal")
    assert (rows[("QQQX", 5)].tier, rows[("QQQX", 5)].assigned_list, rows[("QQQX", 5)].leveraged) == ("etf", None, False)  # stage allows neither list
    assert (rows[("SOXL", 5)].tier, rows[("SOXL", 5)].leveraged) == ("etf", True)


def test_returns_match_the_lists_engine_and_the_slim_fields_are_exactly_its_subset(world):
    update(world)
    r5 = world.pool_outcomes()[("AAA", 5)]
    full = {o.horizon: o for o in eng.compute_outcomes(as_of=AS_OF, as_of_close=100.0, ticker_bars=world.frames["AAA"], spy_bars=world.frames["SPY"],
                                                       sector_bars=world.frames["XLK"], sector_etf="XLK")}[5]
    for field in slim.POOL_VALUE_FIELDS:
        assert getattr(r5, field) == getattr(full, field), field
    assert r5.status == "complete" and r5.entry_date == world.dates[0] and r5.exit_date == world.dates[5]
    assert r5.forward_return == pytest.approx(1.003**6 - 1) and r5.sector_etf == "XLK" and r5.excess_vs_sector is not None
    etf = world.pool_outcomes()[("QQQX", 5)]
    assert etf.sector_etf is None and etf.sector_return is None and etf.excess_vs_sector is None and etf.excess_vs_spy is not None  # SPY only


def test_horizon_5_completes_and_longer_ones_stay_pending(world):
    update(world)
    rows = world.pool_outcomes()
    assert rows[("AAA", 5)].status == "complete"
    pending = rows[("AAA", 10)]
    assert pending.status == "pending" and pending.forward_return is None and pending.entry_date == world.dates[0]


def test_the_entry_gap_and_its_flag_against_the_frozen_close(world):
    with Session(world.engine) as s:
        row = s.exec(select(OpportunityPoolRow).where(OpportunityPoolRow.ticker == "AAA")).one()
        row.close = 70.0  # the entry open (100) is a +42.9% gap
        s.add(row)
        s.commit()
    update(world)
    rows = world.pool_outcomes()
    assert rows[("AAA", 5)].entry_gap_flag is True and rows[("AAA", 5)].entry_gap_pct == pytest.approx(100.0 / 70.0 - 1)
    assert rows[("BBB", 5)].entry_gap_flag is False


# --- idempotence, transitions, failures ---------------------------------------------------------------------------------------------


def test_a_second_run_with_nothing_new_is_a_noop_and_changes_nothing(world):
    update(world)
    before = {k: o.model_dump() for k, o in world.pool_outcomes().items()}
    second = update(world, last_seen_spy=world.dates[-1])
    assert second.status == "noop" and "SPY has no bar newer" in second.reason
    forced = update(world, as_of=AS_OF)  # targeted: skips the SPY check, recomputes the open rows, finds the same values
    assert forced.pool_seeded == 0 and forced.pool_updated == 0
    assert {k: o.model_dump() for k, o in world.pool_outcomes().items()} == before


def test_pending_rows_complete_when_more_bars_arrive_and_complete_rows_are_frozen(world):
    update(world)
    frozen = world.pool_outcomes()[("AAA", 5)].model_dump()
    world.set_bars(13)  # horizon 10 now reachable
    later = update(world)
    rows = world.pool_outcomes()
    assert rows[("AAA", 10)].status == "complete" and rows[("AAA", 20)].status == "pending"
    assert later.pool_updated == 4 and later.pool_seeded == 0  # the four names' horizon-10 rows
    assert rows[("AAA", 5)].model_dump() == frozen  # a complete row is never rewritten
    assert later.by_status == {} and later.pool_by_status["complete"] == {5: 4, 10: 4}


def test_one_ticker_failing_leaves_its_rows_pending_and_the_others_computed(world, monkeypatch):
    real = eng.compute_outcomes
    monkeypatch.setattr(slim.eng, "compute_outcomes", lambda **kw: (_ for _ in ()).throw(ValueError("boom")) if kw["as_of_close"] == 50.0 else real(**kw))
    result = update(world)
    rows = world.pool_outcomes()
    assert result.status == "partial" and list(result.failed) == ["BBB"]
    assert rows[("BBB", 5)].status == "pending" and rows[("BBB", 5)].forward_return is None  # seeded pending, not lost
    assert rows[("AAA", 5)].status == "complete"
    monkeypatch.setattr(slim.eng, "compute_outcomes", real)
    retry = update(world, as_of=AS_OF)
    assert retry.status == "success" and world.pool_outcomes()[("BBB", 5)].status == "complete"


def test_a_failed_bars_read_for_one_chunk_does_not_stop_the_other_chunks(world, monkeypatch):
    monkeypatch.setattr(po, "CHUNK_SIZE", 1)
    calls = []

    def read(tickers, lookback_days, reference=None):
        calls.append(list(tickers))
        if tickers == ["BBB"]:
            raise RuntimeError("disk")
        return {t: world.frames[t] for t in tickers if t in world.frames}

    monkeypatch.setattr(ou, "read_cached_daily_bars_batch", read)
    result = update(world)
    assert result.status == "partial" and "BBB" in result.failed and "disk" in result.failed["BBB"]
    rows = world.pool_outcomes()
    assert rows[("AAA", 5)].status == "complete" and rows[("BBB", 5)].status == "pending"
    assert [c for c in calls if c not in (["SPY"], ["XLK"])] == [["AAA"], ["BBB"], ["QQQX"], ["SOXL"]]  # chunked, one at a time


def test_chunking_gives_the_same_rows(world, monkeypatch):
    update(world)
    whole = {k: o.model_dump(exclude={"id"}) for k, o in world.pool_outcomes().items()}
    with Session(world.engine) as s:
        for o in s.exec(select(OpportunityPoolOutcome)).all():
            s.delete(o)
        s.commit()
    monkeypatch.setattr(po, "CHUNK_SIZE", 1)
    update(world)
    assert {k: o.model_dump(exclude={"id"}) for k, o in world.pool_outcomes().items()} == whole


# --- censoring and the grace period -----------------------------------------------------------------------------------------------


def test_a_ticker_that_stops_getting_bars_is_censored_and_the_reason_follows_the_universe(world, monkeypatch):
    monkeypatch.setattr(ou, "load_tracked_universe", lambda session: ["LIST", "AAA"])  # BBB left the universe
    world.set_bars(20)
    world.frames["BBB"] = world.frames["BBB"].iloc[:4]
    world.frames["AAA"] = world.frames["AAA"].iloc[:4]
    with Session(world.engine) as s:
        from core.models import TickerScore
        s.add(TickerScore(ticker="AAA", overall_score=50, computed_at=CREATED, delisted_at=CREATED))  # AAA is delisted-flagged
        s.commit()
    update(world)
    rows = world.pool_outcomes()
    assert rows[("AAA", 5)].status == "censored" and rows[("AAA", 5)].censor_reason == "delisted"
    assert rows[("BBB", 5)].status == "censored" and rows[("BBB", 5)].censor_reason == "left_universe"
    assert rows[("BBB", 5)].forward_return is not None and rows[("BBB", 5)].exit_date == world.dates[3]  # the sensitivity line
    assert rows[("BBB", 5)].first_censored_at == ou._naive_utc(world.now)


def test_a_censored_row_revives_inside_the_grace(world):
    world.set_bars(20)
    full = world.frames["AAA"]
    world.frames["AAA"] = full.iloc[:4]  # a data hole
    update(world)
    assert world.pool_outcomes()[("AAA", 5)].status == "censored"
    first = world.pool_outcomes()[("AAA", 5)].first_censored_at
    # still holed a day later: still censored, the clock does not restart
    po.update_pool_outcomes(now=world.now + timedelta(days=1), as_of=AS_OF)
    assert world.pool_outcomes()[("AAA", 5)].status == "censored" and world.pool_outcomes()[("AAA", 5)].first_censored_at == first
    # the bars come back inside the 14 days: revived to complete, censor fields cleared
    world.frames["AAA"] = full
    po.update_pool_outcomes(now=world.now + timedelta(days=5), as_of=AS_OF)
    revived = world.pool_outcomes()[("AAA", 5)]
    assert revived.status == "complete" and revived.censor_reason is None and revived.first_censored_at is None


def test_a_censored_row_freezes_after_the_grace_even_if_the_data_returns(world):
    world.set_bars(20)
    full = world.frames["BBB"]
    world.frames["BBB"] = full.iloc[:4]
    update(world)
    assert world.pool_outcomes()[("BBB", 5)].status == "censored"
    world.frames["BBB"] = full
    po.update_pool_outcomes(now=world.now + timedelta(days=eng.CENSOR_REVIVE_DAYS + 1), as_of=AS_OF)
    assert world.pool_outcomes()[("BBB", 5)].status == "censored"  # past its grace: frozen like a complete row


# --- the existing outcome rows are untouched ---------------------------------------------------------------------------------------------


def test_listed_outcome_rows_are_identical_whether_or_not_the_pool_is_priced(world):
    ou.update_outcomes(now=world.now)
    before = world.listed_outcomes()
    assert before  # the listed name has its four rows
    po.update_pool_outcomes(now=world.now)
    ou.update_outcomes(now=world.now)
    assert world.listed_outcomes() == before
    assert "LIST" not in {t for (t, _h) in world.pool_outcomes()}


def test_the_weekly_and_flag_result_and_message_are_unchanged_when_no_pool_is_added(world):
    with Session(world.engine) as s:
        for p in s.exec(select(OpportunityPoolRow)).all():
            s.delete(p)
        s.commit()
    base = fo.update_outcomes_and_flags(now=world.now)
    with Session(world.engine) as s:  # the same starting state again
        for o in s.exec(select(OpportunityOutcome)).all():
            s.delete(o)
        s.commit()
    merged = po.update_pool_into(fo.update_outcomes_and_flags(now=world.now), now=world.now)
    assert merged.message() == base.message() and merged.detail() == base.detail() and "pool outcomes" not in merged.detail()
    assert merged.status == base.status and world.pool_outcomes() == {}


# --- the combined updater, its message and the no-op rule -------------------------------------------------------------------------------


@pytest.fixture
def jobbed(world, monkeypatch, tmp_path):
    monkeypatch.setattr(job, "LOG_PATH", tmp_path / "opportunity_outcome_update.log")
    monkeypatch.setattr(job, "init_db", lambda: None)
    monkeypatch.setattr(ou, "datetime", type("DT", (datetime,), {"now": classmethod(lambda cls, tz=None: world.now if tz else world.now.replace(tzinfo=None))}))
    return world


def test_the_job_prices_the_pool_after_the_lists_and_the_message_gains_a_pool_segment(jobbed):
    result = job.main()
    assert result.status == "success"
    assert "complete 1, pending 3" in result.detail()  # the weekly part, unchanged wording (one listed name)
    assert "pool outcomes: 4 name(s), complete 4, pending 12, censored 0; 16 created, 0 updated" in result.detail()
    assert len(jobbed.pool_outcomes()) == 16
    with Session(jobbed.engine) as s:
        (row,) = s.exec(select(OpportunityOutcomeRun)).all()
    assert row.status == "success" and json.loads(row.summary_json)["pool"]["seeded"] == 16


def test_the_next_night_is_a_green_noop_when_spy_has_not_moved(jobbed):
    job.main()
    again = job.main()
    assert again.status == "noop" and again.message().startswith("no-op: SPY has no bar newer")


def test_pool_rows_missing_force_a_run_even_when_spy_has_not_moved(jobbed):
    job.main()
    with Session(jobbed.engine) as s:  # a new run's pool appears (an old one priced later, say) with no new SPY bar
        s.add(OpportunityRun(id=2, kind="weekly", as_of_date=date(2026, 10, 2), last_bar_date=date(2026, 10, 2), universe_size=1, rules_hash="h",
                             rules_version="2", score_formula_version=6, created_at=CREATED))
        s.add(pool_row(2, "AAA", "quality", "momentum", False, "Technology", 95.0))
        s.commit()
    result = job.main()
    assert result.status == "success" and result.pool_seeded == 4
    with Session(jobbed.engine) as s:
        assert len(s.exec(select(OpportunityPoolOutcome).where(OpportunityPoolOutcome.run_id == 2)).all()) == 4


def test_a_pool_failure_makes_the_run_partial_and_counts_toward_the_threshold(jobbed, monkeypatch):
    real = eng.compute_outcomes
    monkeypatch.setattr(slim.eng, "compute_outcomes", lambda **kw: (_ for _ in ()).throw(ValueError("x")) if kw["as_of_close"] == 50.0 else real(**kw))
    result = job.main()
    assert result.status == "partial" and "BBB" in result.failed and "but failed 1 (BBB)" in result.message()
    # the weekly part still ran
    with Session(jobbed.engine) as s:
        assert len(s.exec(select(OpportunityOutcome)).all()) == 4
        (row,) = s.exec(select(OpportunityOutcomeRun)).all()
    assert row.status == "partial" and row.spy_last_bar_date is None  # so the next normal run retries


def test_a_dry_run_prices_nothing_for_the_pool(jobbed):
    result = job.main(dry_run=True)
    assert result.status == "dry_run" and result.pool_seeded == 16 and jobbed.pool_outcomes() == {}


# --- force, registry, backup, wiring --------------------------------------------------------------------------------------------------


def test_the_table_is_keep_in_the_registry(world):
    from data import ticker_data_registry as reg

    assert reg.REGISTRY["opportunitypooloutcome"].table_class is reg.TableClass.KEEP
    assert reg.REGISTRY["opportunitypooloutcome"].key_column == "ticker"


def test_the_nightly_backup_carries_the_table_and_its_rows(world, tmp_path):
    """pipeline/backup_db.py has no table list (sqlite's backup API copies the whole file): a real file database holding a pool outcome row,
    backed up and restored, still has the table and the row."""
    import gzip
    import sqlite3

    import pipeline.backup_db as backup_db

    path = tmp_path / "fathom.db"
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(OpportunityPoolOutcome(run_id=1, ticker="AAA", horizon=5, status="pending", tier="quality", rules_version="2", computed_at=CREATED))
        s.commit()
    engine.dispose()
    result = backup_db.create_backup(db_path=path, backup_dir=tmp_path / "backups")
    restored = tmp_path / "restored.db"
    with gzip.open(result, "rb") as src, open(restored, "wb") as dst:
        dst.write(src.read())
    conn = sqlite3.connect(str(restored))
    assert conn.execute("SELECT ticker, horizon FROM opportunitypooloutcome").fetchall() == [("AAA", 5)]
    conn.close()


def test_the_job_is_still_one_cron_entry_with_the_same_schedule():
    import core.cron_health as ch

    assert "pipeline.opportunity_outcome_update" in ch.CRON_JOB_NAMES
    cron = open("crontab.txt").read()
    assert cron.count("-m pipeline.opportunity_outcome_update --once") == 1 and "\n40 3 * * * cd " in cron
    assert "opportunity_pool" not in cron
