from datetime import datetime, timedelta

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine, select

import data.entry_signal_data as entry_signal_data
from core.models import TechnicalEntrySignal
from data.entry_signal_data import compute_and_store_entry_signal, is_entry_signal_active, sweep_stale_entry_signals


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
