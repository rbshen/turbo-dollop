from datetime import datetime, timedelta

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine, select

import data.warren_signal_data as warren_signal_data
from analysis.warren_signal.types import WarrenReplayResult, WarrenSignalEvent as EngineEvent
from core.models import TechnicalEntrySignal, WarrenSignalEvent
from data.warren_signal_data import (
    compute_and_store_warren_signal,
    is_warren_entry_signal_active,
    is_warren_signal_active,
    last_buy_signal_fired_at,
    prune_warren_signal_events,
    sweep_stale_warren_signals,
)


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(warren_signal_data, "engine", engine)
    return engine


def _tiny_ohlcv() -> pd.DataFrame:
    # Content is irrelevant to every test below (replay() is monkeypatched
    # to return a canned result) -- just needs to be a real session bar so
    # build_2h_session_candles doesn't matter either way.
    idx = pd.DatetimeIndex(["2026-01-05 09:30"], tz="America/New_York")
    return pd.DataFrame({"open": [10.0], "high": [10.5], "low": [9.5], "close": [10.0], "volume": [1000]}, index=idx)


def _stub_replay(monkeypatch, result: WarrenReplayResult):
    monkeypatch.setattr(warren_signal_data, "replay", lambda candles: result)


def test_last_event_drives_latest_state_whichever_direction_it_is(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    e1 = EngineEvent(kind="yellow_up", fired_at=datetime(2026, 1, 5, 11, 30), close=100.0, rsi=32.0, stop_price=90.0)
    e2 = EngineEvent(kind="blue_down", fired_at=datetime(2026, 1, 6, 13, 30), close=120.0, rsi=85.0, stop_price=95.0)
    result = WarrenReplayResult(as_of=datetime(2026, 1, 6, 15, 30), events=[e1, e2], gray_suppressed=False, stop_count=1, live_stop_price=42.0)
    _stub_replay(monkeypatch, result)

    out = compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="yahoo")

    assert out.signal_kind == "blue_down"
    assert out.fired_at == e2.fired_at
    assert out.close == e2.close
    assert out.rsi == e2.rsi
    assert out.active is False  # a sell arrow was the last event
    # stop_price on the latest-state row is the LIVE stop, not e2's own --
    # a deliberate distinction (see models.py::TechnicalEntrySignal's comment).
    assert out.stop_price == 42.0
    assert out.gray_suppressed is False
    assert out.stop_count == 1
    assert out.pct_b is None
    assert out.signal_type == "warren"
    assert out.timeframe == "2h"

    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, ("AAPL", "warren", "2h"))
    assert row.signal_kind == "blue_down"


def test_active_true_when_last_event_is_a_buy_arrow(monkeypatch):
    _fresh_engine(monkeypatch)
    e = EngineEvent(kind="gray_up", fired_at=datetime(2026, 1, 5, 11, 30), close=100.0, rsi=32.0, stop_price=90.0)
    result = WarrenReplayResult(as_of=datetime(2026, 1, 5, 15, 30), events=[e], gray_suppressed=True, stop_count=2, live_stop_price=90.0)
    _stub_replay(monkeypatch, result)

    out = compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="yahoo")

    assert out.active is True
    assert out.gray_suppressed is True
    assert out.stop_count == 2


def test_no_events_still_writes_heartbeat_and_suppression_state(monkeypatch):
    _fresh_engine(monkeypatch)
    result = WarrenReplayResult(as_of=datetime(2026, 1, 5, 15, 30), events=[], gray_suppressed=True, stop_count=2, live_stop_price=None)
    _stub_replay(monkeypatch, result)

    out = compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="yahoo")

    assert out.fired_at is None
    assert out.signal_kind is None
    assert out.close is None
    assert out.rsi is None
    assert out.active is False
    assert out.gray_suppressed is True
    assert out.stop_count == 2
    assert out.stop_price is None
    assert out.as_of == result.as_of


def test_a_full_replay_always_overwrites_the_prior_state_never_conditionally_advances(monkeypatch):
    # Unlike BB+RSI's should_advance guard, Warren has none -- every run's
    # result IS the complete current truth (see module docstring). This
    # deliberately exercises an artificial "events disappear" case to prove
    # _upsert trusts the replay result unconditionally, not because that
    # could happen with a real causal replay.
    _fresh_engine(monkeypatch)
    e = EngineEvent(kind="yellow_up", fired_at=datetime(2026, 1, 5, 11, 30), close=100.0, rsi=32.0, stop_price=90.0)
    first_result = WarrenReplayResult(as_of=datetime(2026, 1, 5, 15, 30), events=[e], gray_suppressed=False, stop_count=0, live_stop_price=90.0)
    _stub_replay(monkeypatch, first_result)
    first = compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="yahoo")
    assert first.fired_at is not None

    second_result = WarrenReplayResult(as_of=datetime(2026, 1, 6, 15, 30), events=[], gray_suppressed=False, stop_count=0, live_stop_price=None)
    _stub_replay(monkeypatch, second_result)
    second = compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="yahoo")

    assert second.fired_at is None
    assert second.as_of == second_result.as_of


def test_events_are_bulk_written_into_warrensignalevent(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    e1 = EngineEvent(kind="yellow_up", fired_at=datetime(2026, 1, 5, 11, 30), close=100.0, rsi=32.0, stop_price=90.0)
    e2 = EngineEvent(kind="blue_down", fired_at=datetime(2026, 1, 6, 13, 30), close=120.0, rsi=85.0, stop_price=95.0)
    result = WarrenReplayResult(as_of=datetime(2026, 1, 6, 15, 30), events=[e1, e2], gray_suppressed=False, stop_count=1, live_stop_price=42.0)
    _stub_replay(monkeypatch, result)

    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="yahoo")

    with Session(engine) as session:
        rows = session.exec(select(WarrenSignalEvent).where(WarrenSignalEvent.ticker == "AAPL")).all()
    assert len(rows) == 2
    kinds_and_stops = {(r.signal_kind, r.stop_price) for r in rows}
    assert kinds_and_stops == {("yellow_up", 90.0), ("blue_down", 95.0)}


def test_same_bar_co_firing_events_produce_two_distinct_rows(monkeypatch):
    # The exact scenario that ruled out reusing TechnicalEntrySignalEvent's
    # own UniqueConstraint (no signal_kind column there) -- see
    # models.py::WarrenSignalEvent's own comment.
    engine = _fresh_engine(monkeypatch)
    same_bar = datetime(2026, 1, 5, 11, 30)
    e1 = EngineEvent(kind="blue_up", fired_at=same_bar, close=100.0, rsi=10.0, stop_price=90.0)
    e2 = EngineEvent(kind="yellow_up", fired_at=same_bar, close=100.0, rsi=10.0, stop_price=90.0)
    result = WarrenReplayResult(as_of=same_bar, events=[e1, e2], gray_suppressed=False, stop_count=0, live_stop_price=90.0)
    _stub_replay(monkeypatch, result)

    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="yahoo")

    with Session(engine) as session:
        rows = session.exec(select(WarrenSignalEvent).where(WarrenSignalEvent.ticker == "AAPL")).all()
    assert len(rows) == 2
    assert {r.signal_kind for r in rows} == {"blue_up", "yellow_up"}
    assert {r.fired_at for r in rows} == {same_bar}


def test_rerunning_the_same_replay_result_does_not_duplicate_events(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    e = EngineEvent(kind="yellow_up", fired_at=datetime(2026, 1, 5, 11, 30), close=100.0, rsi=32.0, stop_price=90.0)
    result = WarrenReplayResult(as_of=datetime(2026, 1, 5, 15, 30), events=[e], gray_suppressed=False, stop_count=0, live_stop_price=90.0)
    _stub_replay(monkeypatch, result)

    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="yahoo")
    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="yahoo")

    with Session(engine) as session:
        rows = session.exec(select(WarrenSignalEvent).where(WarrenSignalEvent.ticker == "AAPL")).all()
    assert len(rows) == 1


def test_is_warren_signal_active_only_true_for_up_kinds():
    for kind in ("blue_up", "yellow_up", "gray_up"):
        assert is_warren_signal_active(kind) is True
    for kind in ("blue_down", "yellow_down", "gray_down", None):
        assert is_warren_signal_active(kind) is False


def test_is_warren_entry_signal_active_excludes_gray_up():
    # Unlike is_warren_signal_active above, the Screener-filter predicate
    # must NOT treat a gray-suppressed buy as active.
    for kind in ("blue_up", "yellow_up"):
        assert is_warren_entry_signal_active(kind) is True
    for kind in ("gray_up", "blue_down", "yellow_down", "gray_down", None):
        assert is_warren_entry_signal_active(kind) is False


def test_last_buy_signal_fired_at_returns_max_across_up_kinds_only(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add_all(
            [
                WarrenSignalEvent(
                    ticker="AAPL", timeframe="2h", signal_kind="blue_up",
                    fired_at=datetime(2026, 1, 5, 11, 30), created_at=datetime(2026, 1, 5, 11, 30),
                ),
                # A later sell arrow must not win over an earlier buy arrow.
                WarrenSignalEvent(
                    ticker="AAPL", timeframe="2h", signal_kind="blue_down",
                    fired_at=datetime(2026, 1, 7, 9, 30), created_at=datetime(2026, 1, 7, 9, 30),
                ),
                # gray_up counts toward recency (UP_KINDS), unlike the
                # narrower ACTIVE_BUY_KINDS the filter predicate above uses.
                WarrenSignalEvent(
                    ticker="AAPL", timeframe="2h", signal_kind="gray_up",
                    fired_at=datetime(2026, 1, 6, 13, 30), created_at=datetime(2026, 1, 6, 13, 30),
                ),
            ]
        )
        session.commit()

    with Session(engine) as session:
        result = last_buy_signal_fired_at(session, "AAPL")

    assert result == datetime(2026, 1, 6, 13, 30)


def test_last_buy_signal_fired_at_is_none_when_no_buy_event_exists(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            WarrenSignalEvent(
                ticker="AAPL", timeframe="2h", signal_kind="blue_down",
                fired_at=datetime(2026, 1, 7, 9, 30), created_at=datetime(2026, 1, 7, 9, 30),
            )
        )
        session.commit()

    with Session(engine) as session:
        assert last_buy_signal_fired_at(session, "AAPL") is None

    # Ticker with no rows at all reads the same way.
    with Session(engine) as session:
        assert last_buy_signal_fired_at(session, "MSFT") is None


def test_sweep_clears_a_stale_warren_row_including_its_own_three_columns(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    stale = now - timedelta(days=8)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(
                ticker="AAPL",
                signal_type="warren",
                timeframe="2h",
                fired_at=stale,
                rsi=25.0,
                close=100.0,
                stop_price=95.0,
                signal_kind="yellow_up",
                gray_suppressed=True,
                stop_count=1,
                source="yahoo",
                as_of=stale,
                computed_at=stale,
            )
        )
        session.commit()

    cleared = sweep_stale_warren_signals(now=now)

    assert cleared == 1
    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, ("AAPL", "warren", "2h"))
    assert row.fired_at is None
    assert row.signal_kind is None
    assert row.gray_suppressed is None
    assert row.stop_count is None
    assert row.stop_price is None
    assert row.source == "yahoo"
    assert row.as_of == stale
    assert row.computed_at == stale


def test_sweep_never_touches_a_bb_rsi_row(monkeypatch):
    # sweep_stale_warren_signals must be scoped to signal_type="warren"
    # only -- entry_signal_data.py's own sweep owns "bb_rsi" rows.
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    stale = now - timedelta(days=8)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(ticker="AAPL", signal_type="bb_rsi", timeframe="2h", fired_at=stale, pct_b=0.01, source="yahoo", as_of=stale, computed_at=stale)
        )
        session.commit()

    cleared = sweep_stale_warren_signals(now=now)

    assert cleared == 0
    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, ("AAPL", "bb_rsi", "2h"))
    assert row.fired_at == stale


def test_sweep_leaves_a_fresh_warren_row_untouched(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    fresh = now - timedelta(days=6)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(ticker="AAPL", signal_type="warren", timeframe="2h", fired_at=fresh, signal_kind="blue_up", source="yahoo", as_of=fresh, computed_at=fresh)
        )
        session.commit()

    assert sweep_stale_warren_signals(now=now) == 0
    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, ("AAPL", "warren", "2h"))
    assert row.signal_kind == "blue_up"


def test_prune_warren_signal_events_deletes_old_rows_and_keeps_recent_ones(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    old = now - timedelta(days=731)
    recent = now - timedelta(days=10)
    with Session(engine) as session:
        session.add_all(
            [
                WarrenSignalEvent(ticker="AAPL", timeframe="2h", signal_kind="blue_up", fired_at=old, stop_price=10.0, created_at=old),
                WarrenSignalEvent(ticker="AAPL", timeframe="2h", signal_kind="blue_up", fired_at=recent, stop_price=20.0, created_at=recent),
            ]
        )
        session.commit()

    deleted = prune_warren_signal_events(retention_days=730, now=now)

    assert deleted == 1
    with Session(engine) as session:
        remaining = session.exec(select(WarrenSignalEvent).where(WarrenSignalEvent.ticker == "AAPL")).all()
    assert len(remaining) == 1
    assert remaining[0].fired_at == recent


def test_prune_warren_signal_events_is_idempotent_on_an_already_pruned_table(monkeypatch):
    _fresh_engine(monkeypatch)
    assert prune_warren_signal_events(retention_days=730, now=datetime(2026, 9, 9, 12, 0)) == 0
