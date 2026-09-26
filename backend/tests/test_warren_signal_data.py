from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlmodel import Session, SQLModel, create_engine, select

import data.warren_signal_data as warren_signal_data
from analysis.entry_signal.resample import build_2h_session_candles
from analysis.warren_signal.types import WarrenReplayResult, WarrenSignalEvent as EngineEvent
from core.models import TechnicalEntrySignal, WarrenSignalEvent
from data.warren_signal_data import (
    compute_and_store_warren_signal,
    is_warren_signal_active,
    last_buy_signal_fired_at,
    prune_warren_signal_events,
    sweep_stale_warren_signals,
    warren_active_up_kind,
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


def _disable_warmup_buffer(monkeypatch):
    # For tests of plain event-write mechanics: their canned events sit days
    # after _tiny_ohlcv()'s single bar, i.e. deep inside the real 180-day
    # buffer. Every other test here runs under the real default on purpose.
    monkeypatch.setattr(warren_signal_data, "EVENT_WRITE_WARMUP_DAYS", 0)


def test_last_event_drives_latest_state_whichever_direction_it_is(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    e1 = EngineEvent(kind="yellow_up", fired_at=datetime(2026, 1, 5, 11, 30), close=100.0, rsi=32.0, stop_price=90.0)
    e2 = EngineEvent(kind="blue_down", fired_at=datetime(2026, 1, 6, 13, 30), close=120.0, rsi=85.0, stop_price=95.0)
    result = WarrenReplayResult(as_of=datetime(2026, 1, 6, 15, 30), events=[e1, e2], gray_suppressed=False, stop_count=1, live_stop_price=42.0)
    _stub_replay(monkeypatch, result)

    out = compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")

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

    out = compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")

    assert out.active is True
    assert out.gray_suppressed is True
    assert out.stop_count == 2


def test_no_events_still_writes_heartbeat_and_suppression_state(monkeypatch):
    _fresh_engine(monkeypatch)
    result = WarrenReplayResult(as_of=datetime(2026, 1, 5, 15, 30), events=[], gray_suppressed=True, stop_count=2, live_stop_price=None)
    _stub_replay(monkeypatch, result)

    out = compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")

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
    first = compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")
    assert first.fired_at is not None

    second_result = WarrenReplayResult(as_of=datetime(2026, 1, 6, 15, 30), events=[], gray_suppressed=False, stop_count=0, live_stop_price=None)
    _stub_replay(monkeypatch, second_result)
    second = compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")

    assert second.fired_at is None
    assert second.as_of == second_result.as_of


def test_events_are_bulk_written_into_warrensignalevent(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _disable_warmup_buffer(monkeypatch)
    e1 = EngineEvent(kind="yellow_up", fired_at=datetime(2026, 1, 5, 11, 30), close=100.0, rsi=32.0, stop_price=90.0)
    e2 = EngineEvent(kind="blue_down", fired_at=datetime(2026, 1, 6, 13, 30), close=120.0, rsi=85.0, stop_price=95.0)
    result = WarrenReplayResult(as_of=datetime(2026, 1, 6, 15, 30), events=[e1, e2], gray_suppressed=False, stop_count=1, live_stop_price=42.0)
    _stub_replay(monkeypatch, result)

    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")

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
    _disable_warmup_buffer(monkeypatch)
    same_bar = datetime(2026, 1, 5, 11, 30)
    e1 = EngineEvent(kind="blue_up", fired_at=same_bar, close=100.0, rsi=10.0, stop_price=90.0)
    e2 = EngineEvent(kind="yellow_up", fired_at=same_bar, close=100.0, rsi=10.0, stop_price=90.0)
    result = WarrenReplayResult(as_of=same_bar, events=[e1, e2], gray_suppressed=False, stop_count=0, live_stop_price=90.0)
    _stub_replay(monkeypatch, result)

    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")

    with Session(engine) as session:
        rows = session.exec(select(WarrenSignalEvent).where(WarrenSignalEvent.ticker == "AAPL")).all()
    assert len(rows) == 2
    assert {r.signal_kind for r in rows} == {"blue_up", "yellow_up"}
    assert {r.fired_at for r in rows} == {same_bar}


def test_rerunning_the_same_replay_result_does_not_duplicate_events(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _disable_warmup_buffer(monkeypatch)
    e = EngineEvent(kind="yellow_up", fired_at=datetime(2026, 1, 5, 11, 30), close=100.0, rsi=32.0, stop_price=90.0)
    result = WarrenReplayResult(as_of=datetime(2026, 1, 5, 15, 30), events=[e], gray_suppressed=False, stop_count=0, live_stop_price=90.0)
    _stub_replay(monkeypatch, result)

    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")
    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")

    with Session(engine) as session:
        rows = session.exec(select(WarrenSignalEvent).where(WarrenSignalEvent.ticker == "AAPL")).all()
    assert len(rows) == 1


def test_is_warren_signal_active_only_true_for_up_kinds():
    for kind in ("blue_up", "yellow_up", "gray_up"):
        assert is_warren_signal_active(kind) is True
    for kind in ("blue_down", "yellow_down", "gray_down", None):
        assert is_warren_signal_active(kind) is False


def test_warren_active_up_kind_returns_the_kind_itself_for_all_three_up_kinds():
    # Unlike an earlier, narrower Blue+Yellow-only predicate, this
    # Screener-filter helper treats Gray Up as equally well-defined an
    # "active" state as Blue/Yellow Up -- it's a fully-formed, distinct
    # event, not a derived/inferred state.
    for kind in ("blue_up", "yellow_up", "gray_up"):
        assert warren_active_up_kind(kind) == kind
    for kind in ("blue_down", "yellow_down", "gray_down", None):
        assert warren_active_up_kind(kind) is None


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
                # gray_up counts toward recency (UP_KINDS) exactly the
                # same as blue_up/yellow_up.
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
                source="fmp",
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
    assert row.source == "fmp"
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
            TechnicalEntrySignal(ticker="AAPL", signal_type="bb_rsi", timeframe="2h", fired_at=stale, pct_b=0.01, source="fmp", as_of=stale, computed_at=stale)
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
            TechnicalEntrySignal(ticker="AAPL", signal_type="warren", timeframe="2h", fired_at=fresh, signal_kind="blue_up", source="fmp", as_of=fresh, computed_at=fresh)
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


def test_default_retention_is_four_years_and_comfortably_exceeds_the_warmup_buffer():
    assert warren_signal_data.EVENT_RETENTION_DAYS == 1460
    # Retention is only safe to raise because of the write-side buffer; the two must
    # never be tuned into an overlap where kept history is mostly buffer-zone.
    assert warren_signal_data.EVENT_RETENTION_DAYS > 2 * warren_signal_data.EVENT_WRITE_WARMUP_DAYS


def test_default_prune_keeps_events_past_the_old_730_day_mark_and_only_deletes_past_1460(monkeypatch):
    # No retention_days argument: exercises the default the nightly job actually uses.
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    ages = {"just_past_old_cutoff": 731, "a_year_and_a_half": 550 + 400, "just_inside_new": 1459, "just_past_new": 1461, "ancient": 2000}
    with Session(engine) as session:
        for name, days in ages.items():
            fired = now - timedelta(days=days)
            session.add(WarrenSignalEvent(ticker=name, timeframe="2h", signal_kind="blue_up", fired_at=fired, stop_price=10.0, created_at=fired))
        session.commit()

    deleted = prune_warren_signal_events(now=now)

    assert deleted == 2
    with Session(engine) as session:
        kept = {r.ticker for r in session.exec(select(WarrenSignalEvent)).all()}
    assert kept == {"just_past_old_cutoff", "a_year_and_a_half", "just_inside_new"}


def test_prune_warren_signal_events_is_idempotent_on_an_already_pruned_table(monkeypatch):
    _fresh_engine(monkeypatch)
    assert prune_warren_signal_events(retention_days=730, now=datetime(2026, 9, 9, 12, 0)) == 0


# --- Write-side warm-up buffer (EVENT_WRITE_WARMUP_DAYS) --------------------
# Warren replays its whole window every night from a blank state, so events near
# the window's start are unreliable; only events past the buffer are persisted.
# The replay itself and the latest-state row are untouched.

# _tiny_ohlcv()'s single bar is 2026-01-05 09:30, so that is the first (and only)
# 2h candle -- the replay start every stub-based test below measures from.
_REPLAY_START = datetime(2026, 1, 5, 9, 30)


def _buffer_edge() -> datetime:
    return _REPLAY_START + timedelta(days=warren_signal_data.EVENT_WRITE_WARMUP_DAYS)


def _event(kind: str, fired_at: datetime) -> EngineEvent:
    return EngineEvent(kind=kind, fired_at=fired_at, close=100.0, rsi=32.0, stop_price=90.0)


def _result(events: list[EngineEvent]) -> WarrenReplayResult:
    return WarrenReplayResult(as_of=datetime(2026, 12, 31, 15, 30), events=events, gray_suppressed=False, stop_count=0, live_stop_price=90.0)


def _stored_events(engine, ticker: str = "AAPL") -> list[WarrenSignalEvent]:
    with Session(engine) as session:
        return list(session.exec(select(WarrenSignalEvent).where(WarrenSignalEvent.ticker == ticker)).all())


def test_warmup_buffer_is_a_named_module_constant_with_the_agreed_default():
    # (c) A named, tunable constant rather than a magic number in the write path.
    # Pinned so a change to the width is a deliberate edit to this assertion too.
    assert warren_signal_data.EVENT_WRITE_WARMUP_DAYS == 180
    # It is a separate knob from retention: the buffer is the prerequisite for ever
    # raising retention, so it must always fit inside it.
    assert warren_signal_data.EVENT_WRITE_WARMUP_DAYS < warren_signal_data.EVENT_RETENTION_DAYS


def test_event_inside_the_buffer_is_never_written_even_though_the_state_machine_produced_it(monkeypatch):
    # (a)
    engine = _fresh_engine(monkeypatch)
    inside = [
        _event("yellow_up", _REPLAY_START + timedelta(days=1)),
        _event("blue_down", _buffer_edge() - timedelta(minutes=1)),  # the last instant inside
    ]
    _stub_replay(monkeypatch, _result(inside))

    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")
    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")  # nor on a re-run

    assert _stored_events(engine) == []


def test_event_at_or_past_the_buffer_edge_is_written_normally(monkeypatch):
    # (b) The edge itself is inclusive (`fired_at >= replay_start + buffer`).
    engine = _fresh_engine(monkeypatch)
    events = [
        _event("yellow_up", _buffer_edge() - timedelta(minutes=1)),  # inside: dropped
        _event("blue_up", _buffer_edge()),  # exactly at the edge: written
        _event("blue_down", _buffer_edge() + timedelta(days=30)),  # well past it: written
    ]
    _stub_replay(monkeypatch, _result(events))

    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")

    assert {(r.signal_kind, r.fired_at) for r in _stored_events(engine)} == {
        ("blue_up", _buffer_edge()),
        ("blue_down", _buffer_edge() + timedelta(days=30)),
    }


def test_buffer_width_is_driven_by_the_constant(monkeypatch):
    # (c) Retuning the constant moves the edge; nothing else hardcodes 180.
    engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(warren_signal_data, "EVENT_WRITE_WARMUP_DAYS", 30)
    events = [_event("yellow_up", _REPLAY_START + timedelta(days=20)), _event("blue_up", _REPLAY_START + timedelta(days=45))]
    _stub_replay(monkeypatch, _result(events))

    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")

    assert [r.signal_kind for r in _stored_events(engine)] == ["blue_up"]


def test_buffer_is_measured_from_the_first_replayed_candle_not_from_a_fixed_date(monkeypatch):
    # A ticker with less history than the fetch window (a recent IPO) replays from
    # its own first candle, and its buffer starts there.
    engine = _fresh_engine(monkeypatch)
    later_start = pd.DatetimeIndex(["2026-03-02 09:30"], tz="America/New_York")
    ohlcv = pd.DataFrame({"open": [10.0], "high": [10.5], "low": [9.5], "close": [10.0], "volume": [1000]}, index=later_start)
    edge = datetime(2026, 3, 2, 9, 30) + timedelta(days=warren_signal_data.EVENT_WRITE_WARMUP_DAYS)
    _stub_replay(monkeypatch, _result([_event("yellow_up", edge - timedelta(days=1)), _event("blue_up", edge)]))

    compute_and_store_warren_signal("AAPL", ohlcv, source="fmp")

    assert [r.signal_kind for r in _stored_events(engine)] == ["blue_up"]


def test_latest_state_row_is_identical_with_and_without_the_buffer(monkeypatch):
    # Confirms the buffer gates ONLY the event-table writes. The latest-state row
    # (what the Technical card, Screener's warren_active_signal_kind and
    # warren_entry_signal read) comes from the full, unfiltered replay -- including
    # when the last event itself sits inside the buffer.
    events = [
        _event("yellow_up", _REPLAY_START + timedelta(days=10)),
        _event("blue_down", _REPLAY_START + timedelta(days=20)),  # last event, inside the buffer
    ]
    result = WarrenReplayResult(as_of=datetime(2026, 2, 1, 15, 30), events=events, gray_suppressed=True, stop_count=2, live_stop_price=42.0)

    def latest_state(warmup_days: int):
        engine = _fresh_engine(monkeypatch)
        monkeypatch.setattr(warren_signal_data, "EVENT_WRITE_WARMUP_DAYS", warmup_days)
        _stub_replay(monkeypatch, result)
        out = compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")
        return out.model_dump(exclude={"computed_at"}), _stored_events(engine)

    without_buffer, events_without = latest_state(0)
    with_buffer, events_with = latest_state(180)

    assert with_buffer == without_buffer
    assert with_buffer["signal_kind"] == "blue_down" and with_buffer["fired_at"] == events[-1].fired_at
    assert with_buffer["active"] is False and with_buffer["stop_price"] == 42.0
    assert (with_buffer["gray_suppressed"], with_buffer["stop_count"]) == (True, 2)
    # ...while the event table itself did change, which is the whole point.
    assert len(events_without) == 2 and events_with == []


def test_last_buy_signal_fired_at_reads_the_events_that_were_written(monkeypatch):
    # warren_last_buy_fired_at (Screener) is read off the event table, so it follows
    # the buffer: a buy past the edge is found, one inside it is not.
    engine = _fresh_engine(monkeypatch)
    past_edge = _buffer_edge() + timedelta(days=3)
    _stub_replay(monkeypatch, _result([_event("yellow_up", _REPLAY_START + timedelta(days=5)), _event("blue_up", past_edge)]))
    compute_and_store_warren_signal("AAPL", _tiny_ohlcv(), source="fmp")
    _stub_replay(monkeypatch, _result([_event("yellow_up", _REPLAY_START + timedelta(days=5))]))  # buy inside the buffer only
    compute_and_store_warren_signal("MSFT", _tiny_ohlcv(), source="fmp")

    with Session(engine) as session:
        assert last_buy_signal_fired_at(session, "AAPL") == past_edge
        assert last_buy_signal_fired_at(session, "MSFT") is None


def _synthetic_bars(days: int, seed: int) -> pd.DataFrame:
    """Regime-switching random-walk 60m bars (7 per session, 09:30-15:30), enough to make
    the real state machine fire a realistic mix of arrows. Seeded, so deterministic."""
    rng = np.random.default_rng(seed)
    idx = [pd.Timestamp(d.year, d.month, d.day, 9, 30) + pd.Timedelta(hours=h) for d in pd.bdate_range("2025-01-02", periods=days) for h in range(7)]
    idx = pd.DatetimeIndex(idx).tz_localize("America/New_York")
    n = len(idx)
    drift = np.zeros(n)
    i = 0
    while i < n:
        span = int(rng.integers(150, 320))
        drift[i : i + span] = rng.normal(0, 0.0012)
        i += span
    vol = 0.006
    close = pd.Series(100 * np.exp(np.cumsum(drift + vol * rng.standard_t(4, n) / np.sqrt(2))), index=idx)
    open_ = close.shift(1).fillna(close.iloc[0])
    spread = np.abs(rng.normal(0, vol * 0.5, n)) * close
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) + spread, "low": np.minimum(open_, close) - spread, "close": close, "volume": rng.integers(100_000, 1_000_000, n)},
        index=idx,
    )


def test_buffer_removes_leading_edge_events_across_consecutive_nightly_replays(monkeypatch):
    # (d) End to end through the real state machine (no stub), over two consecutive
    # "nights" whose windows differ by a few weeks of slide. Without the buffer, night
    # one persists events computed right at its window start and night two persists
    # NEW variants at its own (later) start -- the accumulation the buffer exists to
    # stop. With it, neither night writes anything inside its own buffer.
    buffer_days, window_days, slide_days = 60, 330, 15  # buffer narrowed to fit a short synthetic window
    bars = _synthetic_bars(window_days + slide_days, seed=3)
    sessions = sorted({t.date() for t in bars.index})
    night1 = bars[bars.index.date <= sessions[window_days - 1]]
    night2 = bars[bars.index.date >= sessions[slide_days]]

    def first_candle(df: pd.DataFrame) -> datetime:
        return build_2h_session_candles(df).index[0].to_pydatetime().replace(tzinfo=None)

    def two_nights(warmup_days: int):
        engine = _fresh_engine(monkeypatch)
        monkeypatch.setattr(warren_signal_data, "EVENT_WRITE_WARMUP_DAYS", warmup_days)

        compute_and_store_warren_signal("AAPL", night1, source="fmp")
        after_night1 = {(r.signal_kind, r.fired_at) for r in _stored_events(engine)}
        compute_and_store_warren_signal("AAPL", night2, source="fmp")
        after_night2 = {(r.signal_kind, r.fired_at) for r in _stored_events(engine)}

        edge1 = first_candle(night1) + timedelta(days=buffer_days)
        edge2 = first_candle(night2) + timedelta(days=buffer_days)
        written_in_zone_1 = [e for e in after_night1 if e[1] < edge1]
        newly_written_in_zone_2 = [e for e in after_night2 - after_night1 if e[1] < edge2]
        return written_in_zone_1, newly_written_in_zone_2

    control_zone_1, control_zone_2 = two_nights(0)  # the old, unbuffered behaviour
    buffered_zone_1, buffered_zone_2 = two_nights(buffer_days)

    # Non-vacuous: the unbuffered control really does persist leading-edge events, on
    # the first night and again as new variants on the second...
    assert len(control_zone_1) > 0
    assert len(control_zone_2) > 0
    # ...and with the buffer, neither night persists a single one.
    assert buffered_zone_1 == []
    assert buffered_zone_2 == []
