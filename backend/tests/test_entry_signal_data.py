from datetime import datetime, timedelta

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine, select

import data.entry_signal_data as entry_signal_data
from analysis.entry_signal.types import EntrySignalResult
from core.models import TechnicalEntrySignal, TechnicalEntrySignalEvent
from data.entry_signal_data import (
    compute_and_store_entry_signal,
    is_entry_signal_active,
    prune_entry_signal_events,
    record_historical_entry_signal_events,
    sweep_stale_entry_signals,
)


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(entry_signal_data, "engine", engine)
    return engine


def _bars(closes: list[float]) -> pd.DataFrame:
    # Fixed START anchor (5 business days before "today"), not `end=` --
    # `bdate_range(end=..., periods=n)` shifts EARLIER days backward as n
    # grows, so a shared closes-list prefix (e.g. _WARMUP + _FIRING_DAY)
    # would land on a DIFFERENT calendar date depending on how many days a
    # given test appends after it. A fixed start means _FIRING_DAY (always
    # day-index 5, since every test builds on the same 20-close/5-day
    # _WARMUP prefix) always lands on the same calendar day -- "today" --
    # regardless of what's appended afterward, so a freshly computed
    # fired_at from it genuinely falls inside the 7-day active window.
    n_days = (len(closes) + 3) // 4 + 1
    start = pd.Timestamp.now(tz="America/New_York").normalize() - pd.tseries.offsets.BDay(5)
    days = pd.bdate_range(start=start, periods=n_days, tz="America/New_York")
    times = ["09:30", "11:30", "13:30", "15:30"]
    rows = []
    i = 0
    for day in days:
        for t in times:
            if i >= len(closes):
                break
            hour, minute = (int(x) for x in t.split(":"))
            ts = day.replace(hour=hour, minute=minute)
            c = closes[i]
            rows.append({"timestamp": ts, "open": c, "high": c, "low": c, "close": c, "volume": 1000})
            i += 1
    return pd.DataFrame(rows).set_index("timestamp")


_WARMUP = [100.0] * 20
_FIRING_DAY = [95.0, 85.0, 78.0, 74.0]  # indices 21-23 fire, see test_engine.py
_CALM_DAY = [90.0, 91.0, 92.0, 93.0]  # never fires


def test_a_fire_creates_a_row_with_all_five_fired_fields_populated(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    out = compute_and_store_entry_signal("AAPL", _bars(_WARMUP + _FIRING_DAY), source="yahoo")

    assert out.active is True
    assert out.fired_at is not None
    assert out.pct_b is not None
    assert out.rsi is not None
    assert out.close == 74.0
    assert out.stop_price is not None

    with Session(engine) as session:
        row = session.exec(select(TechnicalEntrySignal).where(TechnicalEntrySignal.ticker == "AAPL")).first()
    assert row is not None
    assert row.fired_at == out.fired_at


def test_a_quiet_run_leaves_a_prior_fire_untouched_but_still_advances_the_heartbeat(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    compute_and_store_entry_signal("AAPL", _bars(_WARMUP + _FIRING_DAY), source="yahoo")

    with Session(engine) as session:
        before = session.exec(select(TechnicalEntrySignal).where(TechnicalEntrySignal.ticker == "AAPL")).first()
    assert before.fired_at is not None

    # A second, later run whose OWN newest day never fires -- must not wipe
    # out the still-relevant prior fire.
    out = compute_and_store_entry_signal("AAPL", _bars(_WARMUP + _FIRING_DAY + _CALM_DAY), source="yahoo")

    assert out.fired_at == before.fired_at
    assert out.pct_b == before.pct_b
    assert out.stop_price == before.stop_price
    assert out.active is True  # the prior fire is still within the window
    # the heartbeat fields DO advance, even though nothing fired this run
    assert out.as_of > before.as_of

    with Session(engine) as session:
        after = session.exec(select(TechnicalEntrySignal).where(TechnicalEntrySignal.ticker == "AAPL")).first()
    assert after.fired_at == before.fired_at
    assert after.as_of > before.as_of


def test_a_newer_fire_advances_all_five_fired_fields_together(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    compute_and_store_entry_signal("AAPL", _bars(_WARMUP + _FIRING_DAY), source="yahoo")
    with Session(engine) as session:
        before = session.exec(select(TechnicalEntrySignal).where(TechnicalEntrySignal.ticker == "AAPL")).first()

    # A later run whose newest day fires again, with a different price --
    # must replace the old fired-bar snapshot, not merge with it.
    second_firing_day = [80.0, 60.0, 40.0, 20.0]
    out = compute_and_store_entry_signal("AAPL", _bars(_WARMUP + _FIRING_DAY + _CALM_DAY + second_firing_day), source="yahoo")

    assert out.fired_at > before.fired_at
    assert out.close != before.close


def test_re_evaluating_an_already_recorded_fire_does_not_regress(monkeypatch):
    # Same bars fed twice (simulating a re-run) -- fired_at must not move
    # backward or duplicate.
    engine = _fresh_engine(monkeypatch)
    bars = _bars(_WARMUP + _FIRING_DAY)
    first = compute_and_store_entry_signal("AAPL", bars, source="yahoo")
    second = compute_and_store_entry_signal("AAPL", bars, source="yahoo")

    assert second.fired_at == first.fired_at
    assert second.close == first.close

    with Session(engine) as session:
        rows = session.exec(select(TechnicalEntrySignal).where(TechnicalEntrySignal.ticker == "AAPL")).all()
    assert len(rows) == 1  # upsert, never a duplicate row


def test_a_fire_also_creates_a_technicalentrysignalevent_row(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    out = compute_and_store_entry_signal("AAPL", _bars(_WARMUP + _FIRING_DAY), source="yahoo")

    with Session(engine) as session:
        events = session.exec(select(TechnicalEntrySignalEvent).where(TechnicalEntrySignalEvent.ticker == "AAPL")).all()
    assert len(events) == 1
    assert events[0].fired_at == out.fired_at
    assert events[0].stop_price == out.stop_price
    assert events[0].signal_type == "bb_rsi"
    assert events[0].timeframe == "2h"


def test_a_quiet_run_does_not_create_an_event_row(monkeypatch):
    # A genuinely non-firing day straight off the flat _WARMUP baseline --
    # unlike _CALM_DAY (90-93), which is only "calm" RELATIVE to a prior
    # crash (see test_a_quiet_run_leaves_a_prior_fire_untouched... above);
    # on its own, straight after a flat 100.0 warmup, 90-93 is itself a
    # real ~10% drop and correctly fires (confirmed directly against
    # compute_entry_signal before writing this test) -- a tiny, non-eventful
    # move is what "quiet" actually needs here.
    engine = _fresh_engine(monkeypatch)

    compute_and_store_entry_signal("AAPL", _bars(_WARMUP + [100.0, 100.1, 100.2, 100.3]), source="yahoo")

    with Session(engine) as session:
        events = session.exec(select(TechnicalEntrySignalEvent).where(TechnicalEntrySignalEvent.ticker == "AAPL")).all()
    assert events == []


def test_rerunning_the_same_fire_does_not_duplicate_the_event_row(monkeypatch):
    # The idempotency case a cron rerun (or a re-run against the same
    # "today" data) must hit -- on_conflict_do_nothing on
    # (ticker, signal_type, timeframe, fired_at) must keep this at exactly
    # one row, never a duplicate, even though _upsert's own
    # should_advance/TechnicalEntrySignal logic has nothing to do with the
    # event table's own insert.
    engine = _fresh_engine(monkeypatch)
    bars = _bars(_WARMUP + _FIRING_DAY)

    compute_and_store_entry_signal("AAPL", bars, source="yahoo")
    compute_and_store_entry_signal("AAPL", bars, source="yahoo")

    with Session(engine) as session:
        events = session.exec(select(TechnicalEntrySignalEvent).where(TechnicalEntrySignalEvent.ticker == "AAPL")).all()
    assert len(events) == 1


def test_a_new_fire_on_a_later_run_adds_a_second_distinct_event_row(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    compute_and_store_entry_signal("AAPL", _bars(_WARMUP + _FIRING_DAY), source="yahoo")

    second_firing_day = [80.0, 60.0, 40.0, 20.0]
    compute_and_store_entry_signal("AAPL", _bars(_WARMUP + _FIRING_DAY + _CALM_DAY + second_firing_day), source="yahoo")

    with Session(engine) as session:
        events = session.exec(select(TechnicalEntrySignalEvent).where(TechnicalEntrySignalEvent.ticker == "AAPL")).all()
    assert len(events) == 2
    assert len({e.fired_at for e in events}) == 2


def test_record_historical_entry_signal_events_inserts_one_row_per_result(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    results = [
        EntrySignalResult(as_of=datetime(2025, 1, 6, 15, 30), fired=True, fired_at=datetime(2025, 1, 6, 11, 30), pct_b=0.01, rsi=20.0, close=50.0, stop_price=45.0),
        EntrySignalResult(as_of=datetime(2025, 2, 3, 15, 30), fired=True, fired_at=datetime(2025, 2, 3, 13, 30), pct_b=0.02, rsi=22.0, close=60.0, stop_price=55.0),
    ]

    inserted = record_historical_entry_signal_events("AAPL", results)

    assert inserted == 2
    with Session(engine) as session:
        events = session.exec(select(TechnicalEntrySignalEvent).where(TechnicalEntrySignalEvent.ticker == "AAPL")).all()
    assert {e.fired_at for e in events} == {datetime(2025, 1, 6, 11, 30), datetime(2025, 2, 3, 13, 30)}


def test_record_historical_entry_signal_events_is_idempotent(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    results = [
        EntrySignalResult(as_of=datetime(2025, 1, 6, 15, 30), fired=True, fired_at=datetime(2025, 1, 6, 11, 30), pct_b=0.01, rsi=20.0, close=50.0, stop_price=45.0),
    ]

    first = record_historical_entry_signal_events("AAPL", results)
    second = record_historical_entry_signal_events("AAPL", results)

    assert first == 1
    assert second == 0  # the conflict is silently skipped, not re-inserted
    with Session(engine) as session:
        events = session.exec(select(TechnicalEntrySignalEvent).where(TechnicalEntrySignalEvent.ticker == "AAPL")).all()
    assert len(events) == 1


def test_record_historical_entry_signal_events_never_touches_technicalentrysignal(monkeypatch):
    # A backfill populates history only -- it must never create or modify
    # the single "latest fire" row the nightly job's own _upsert owns.
    engine = _fresh_engine(monkeypatch)
    results = [
        EntrySignalResult(as_of=datetime(2025, 1, 6, 15, 30), fired=True, fired_at=datetime(2025, 1, 6, 11, 30), pct_b=0.01, rsi=20.0, close=50.0, stop_price=45.0),
    ]

    record_historical_entry_signal_events("AAPL", results)

    with Session(engine) as session:
        rows = session.exec(select(TechnicalEntrySignal).where(TechnicalEntrySignal.ticker == "AAPL")).all()
    assert rows == []


def test_prune_entry_signal_events_deletes_old_rows_and_keeps_recent_ones(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    old_fired_at = now - timedelta(days=731)
    recent_fired_at = now - timedelta(days=10)
    with Session(engine) as session:
        session.add_all(
            [
                TechnicalEntrySignalEvent(ticker="AAPL", signal_type="bb_rsi", timeframe="2h", fired_at=old_fired_at, stop_price=10.0, created_at=old_fired_at),
                TechnicalEntrySignalEvent(ticker="AAPL", signal_type="bb_rsi", timeframe="2h", fired_at=recent_fired_at, stop_price=20.0, created_at=recent_fired_at),
            ]
        )
        session.commit()

    deleted = prune_entry_signal_events(retention_days=730, now=now)

    assert deleted == 1
    with Session(engine) as session:
        remaining = session.exec(select(TechnicalEntrySignalEvent).where(TechnicalEntrySignalEvent.ticker == "AAPL")).all()
    assert len(remaining) == 1
    assert remaining[0].fired_at == recent_fired_at


def test_prune_entry_signal_events_respects_a_custom_retention_window(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    fired_400_days_ago = now - timedelta(days=400)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignalEvent(ticker="AAPL", signal_type="bb_rsi", timeframe="2h", fired_at=fired_400_days_ago, stop_price=10.0, created_at=fired_400_days_ago)
        )
        session.commit()

    # Under the default (730-day) retention this row would survive; a
    # shorter, explicit 365-day retention_days must delete it -- confirms
    # the parameter is genuinely honored, not just defaulted.
    deleted = prune_entry_signal_events(retention_days=365, now=now)

    assert deleted == 1


def test_prune_entry_signal_events_is_idempotent_on_an_already_pruned_table(monkeypatch):
    _fresh_engine(monkeypatch)
    assert prune_entry_signal_events(retention_days=730, now=datetime(2026, 9, 9, 12, 0)) == 0


def test_is_entry_signal_active_respects_the_seven_day_window():
    now = datetime(2026, 9, 9, 12, 0)
    assert is_entry_signal_active(now - timedelta(days=6, hours=23), now=now) is True
    assert is_entry_signal_active(now - timedelta(days=7), now=now) is False
    assert is_entry_signal_active(now - timedelta(days=8), now=now) is False
    assert is_entry_signal_active(None, now=now) is False


def test_sweep_clears_a_stale_row_but_leaves_as_of_source_computed_at_alone(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    stale_computed_at = now - timedelta(days=8)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(
                ticker="AAPL",
                signal_type="bb_rsi",
                timeframe="2h",
                fired_at=stale_computed_at,
                pct_b=0.01,
                rsi=25.0,
                close=100.0,
                stop_price=95.0,
                source="yahoo",
                as_of=stale_computed_at,
                computed_at=stale_computed_at,
            )
        )
        session.commit()

    cleared = sweep_stale_entry_signals(now=now)

    assert cleared == 1
    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, ("AAPL", "bb_rsi", "2h"))
    assert row.fired_at is None
    assert row.pct_b is None
    assert row.rsi is None
    assert row.close is None
    assert row.stop_price is None
    assert row.source == "yahoo"
    assert row.as_of == stale_computed_at
    assert row.computed_at == stale_computed_at


def test_sweep_leaves_a_fresh_row_untouched(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    fresh_computed_at = now - timedelta(days=6)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(
                ticker="AAPL",
                signal_type="bb_rsi",
                timeframe="2h",
                fired_at=fresh_computed_at,
                pct_b=0.01,
                rsi=25.0,
                close=100.0,
                stop_price=95.0,
                source="yahoo",
                as_of=fresh_computed_at,
                computed_at=fresh_computed_at,
            )
        )
        session.commit()

    cleared = sweep_stale_entry_signals(now=now)

    assert cleared == 0
    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, ("AAPL", "bb_rsi", "2h"))
    assert row.fired_at == fresh_computed_at
    assert row.pct_b == 0.01


def test_sweep_is_idempotent_on_an_already_cleared_row(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    stale_computed_at = now - timedelta(days=8)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(
                ticker="AAPL",
                signal_type="bb_rsi",
                timeframe="2h",
                source="yahoo",
                as_of=stale_computed_at,
                computed_at=stale_computed_at,
            )
        )
        session.commit()

    assert sweep_stale_entry_signals(now=now) == 0  # nothing to clear -- already all-None
