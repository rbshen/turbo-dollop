"""The one-time watch-row rebuild (pipeline/backfills/rebuild_warren_watch.py): the field diff, the kinds of change, the 12-month start,
the mismatch guard (the rules WITHOUT trailing must reproduce a stored row, the stop-age fields excluded), the dry run that writes
nothing (even on a database without the stop-age columns) and --apply that fills the stop age and touches nothing else."""

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

import data.warren_watch_data as wwd
from core.models import LiquidityZoneSettings, WarrenWatchCursor, WarrenWatchRow
from data.warren_watch_data import SEED_MONTHS
from pipeline.backfills import rebuild_warren_watch as rb
from pipeline.backfills.rebuild_warren_watch import GUARD_FIELDS, WatchState, classify, diff
from test_warren_watch_data import NOW, bars, canned

T = datetime(2026, 9, 16, 9, 30)
STORED = WatchState("any", "gray_up", datetime(2026, 10, 15, 15, 30), 3, "yellow", T, 425.0, 376.254, "10%", "breached",
                    datetime(2026, 10, 13, 9, 30), datetime(2026, 10, 15, 15, 30))


def test_an_identical_replay_has_no_differences():
    assert diff(STORED, replace(STORED)) == {}


def test_every_field_is_compared_including_the_stop_age():
    assert diff(STORED, replace(STORED, last_signal_at=T)) == {"last_signal_at": (STORED.last_signal_at, T)}
    assert set(diff(STORED, replace(STORED, last_signal_at=T, stop_price=300.0))) == {"last_signal_at", "stop_price"}
    assert set(diff(STORED, replace(STORED, stop_moved_at=T, stop_moved_by="trail"))) == {"stop_moved_at", "stop_moved_by"}


def test_the_guard_fields_exclude_the_stop_age():
    fresh = replace(STORED, stop_moved_at=T, stop_moved_by="trail")
    assert diff(STORED, fresh, GUARD_FIELDS) == {} and "stop_moved_at" not in GUARD_FIELDS and len(GUARD_FIELDS) == 12


def test_a_replay_that_builds_no_row_is_a_difference():
    assert set(diff(STORED, None)) == {"<replay>"}


def test_the_replay_start_is_twelve_months_before_the_first_seeds_as_of():
    assert SEED_MONTHS == 12 and rb.REBUILD_START == datetime(2025, 10, 15, 15, 30)


def test_classify_names_the_kinds_of_change():
    assert classify({"entry_price": (1, 2), "entry_at": (1, 2)}) == ["entry changed"]
    assert classify({"stop_price": (1, 2), "status": ("breached", "active"), "breached_at": (T, None)}) == ["stop changed", "status breached -> active"]
    assert classify({"stop_basis": ("10%", "LP")}) == ["basis changed"]
    assert classify({"instruction_type": (1, 3)}) == ["instruction/latest arrow changed"]
    assert classify({"last_signal_at": (T, T)}) == ["dates only"]
    assert classify({"stop_moved_at": (None, T), "stop_moved_by": (None, "trail")}) == ["stop age fill only"]


# --- the run itself, on an in-memory database -------------------------------------------------------------------

LAST = datetime(2026, 10, 16, 15, 30)
ARROWS = {
    "A": [("yellow_up", "2026-09-01 09:30"), ("blue_down", "2026-09-10 09:30")],  # an LP stop of 80 that the 10-15 session's LP trails to 85
    "B": [("yellow_up", "2026-09-01 09:30"), ("blue_down", "2026-09-10 09:30")],  # removed: must be skipped
    "C": [("yellow_up", "2026-09-01 09:30"), ("blue_down", "2026-09-10 09:30")],  # stored stop the old rules cannot reproduce: must be skipped
    "D": [("yellow_up", "2026-09-01 09:30")],  # a 10% stop: nothing to trail, only the stop age to fill
}


@pytest.fixture
def world(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    frame = bars("2025-08-01", "2026-10-16")
    canned(monkeypatch, ARROWS)
    monkeypatch.setattr(rb, "watch_replay", wwd.watch_replay)
    monkeypatch.setattr(rb, "engine", eng)
    monkeypatch.setattr(rb, "_load_frames", lambda session, tickers, interval, start: {t: frame for t in tickers})
    monkeypatch.setattr(rb, "completed_candles", lambda b, now: wwd.completed_candles(b, NOW))
    monkeypatch.setattr(rb, "history_gap", lambda *a: None)

    def fake_lp(candles, settings):
        late = candles.index[-1] >= datetime(2026, 10, 15, 9, 30)
        return SimpleNamespace(support=[SimpleNamespace(price=p) for p in ([95.0, 85.0, 75.0] if late else [90.0, 80.0, 70.0])])

    monkeypatch.setattr(wwd, "compute_liquidity_zones_2h", fake_lp)
    with Session(eng) as s:
        s.add(LiquidityZoneSettings(key="default", swing_bars_each_side=2, cluster_pct=0.0, max_lps_per_side=3, over_cap_priority="nearest_price",
                                    keep_last_breached_support=True, keep_last_breached_resistance=True, only_keep_if_breached_recently=True,
                                    breach_recency_bars=5, updated_at=datetime(2026, 1, 1)))
        s.commit()
    candles = wwd.completed_candles(frame, NOW)
    settings = SimpleNamespace(max_lps_per_side=3)
    for ticker in ARROWS:
        old = rb.replay_state(ticker, frame, settings, LAST, trail=False).state  # what the stored rows hold: the rules without trailing
        values = wwd._row_values(old)
        values.update(stop_moved_at=None, stop_moved_by=None)  # stored rows have no stop age yet
        if ticker == "C":
            values["stop_price"] = 77.0
        with Session(eng) as s:
            s.add(WarrenWatchRow(ticker=ticker, last_updated_at=datetime(2026, 10, 16, 5, 25), removed_at=datetime(2026, 10, 1) if ticker == "B" else None,
                                 as_of=LAST, **values))
            s.add(WarrenWatchCursor(ticker=ticker, processed_through=LAST, updated_at=datetime(2026, 10, 16, 5, 25)))
            s.commit()
    return eng, candles


def snapshot(eng):
    with Session(eng) as s:
        return [r.model_dump() for r in s.exec(select(WarrenWatchRow).order_by(WarrenWatchRow.ticker)).all()], [
            c.model_dump() for c in s.exec(select(WarrenWatchCursor).order_by(WarrenWatchCursor.ticker)).all()
        ]


def test_a_dry_run_writes_nothing_and_reports_the_trailed_and_filled_rows(world, capsys):
    eng, _ = world
    before = snapshot(eng)
    out = rb.main(apply=False)
    assert snapshot(eng) == before
    # A (trails 80 -> 85) and D (stop age only) change; B is removed (not read); C fails the guard.
    assert (out["changing"], out["same"], out["skipped"]) == (2, 0, 1)
    assert out["kinds"]["stop changed"] == 1 and out["kinds"]["stop age fill only"] == 1 and out["kinds"]["stop only"] == 1
    assert out["trail_moves"] >= 1 and out["lp_calls"] > 0 and out["flips"] == []
    printed = capsys.readouterr().out
    assert "SKIPPED C" in printed and "the rules without trailing do not reproduce the stored row" in printed


def test_apply_fills_the_stop_age_and_touches_nothing_else_and_a_rerun_is_identical(world):
    eng, _ = world
    before_rows, before_cursors = snapshot(eng)
    rb.main(apply=True)
    after_rows, after_cursors = snapshot(eng)
    assert after_cursors == before_cursors
    by_ticker = lambda rows: {r["ticker"]: r for r in rows}  # noqa: E731
    b, a = by_ticker(before_rows), by_ticker(after_rows)
    assert a["B"] == b["B"] and a["C"] == b["C"]  # removed and guard-skipped rows untouched
    assert (a["A"]["stop_price"], a["A"]["stop_basis"], a["A"]["stop_moved_by"]) == (85.0, "LP", "trail")
    assert (a["D"]["stop_price"], a["D"]["stop_moved_by"], a["D"]["stop_moved_at"]) == (b["D"]["stop_price"], "yellow_up_entry", datetime(2026, 9, 1, 9, 30))
    for ticker in ("A", "D"):
        for untouched in ("removed_at", "as_of", "last_updated_at"):
            assert a[ticker][untouched] == b[ticker][untouched]
    again = rb.main(apply=False)
    assert (again["changing"], again["same"], again["skipped"]) == (0, 2, 1)


def test_a_dry_run_reads_a_database_without_the_stop_age_columns_and_apply_refuses(world):
    eng, _ = world
    with eng.begin() as conn:
        conn.execute(text("ALTER TABLE warrenwatchrow DROP COLUMN stop_moved_at"))
        conn.execute(text("ALTER TABLE warrenwatchrow DROP COLUMN stop_moved_by"))
    out = rb.main(apply=False)
    assert (out["changing"], out["skipped"]) == (2, 1)
    with pytest.raises(SystemExit, match="stop_moved_at"):
        rb.main(apply=True)
