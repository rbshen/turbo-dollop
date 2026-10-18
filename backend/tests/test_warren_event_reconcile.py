"""The Warren event-log reconcile (data/warren_signal_data.py::reconcile_events, docs/specs/warren-signals-page.md, "Event log reconcile"):
stale events at or after the write gate are deleted, missing replay arrows inserted, matching events left untouched (created_at and
stop_price as written), events before the gate never read or changed, a second run changes nothing, and a replay that yields nothing or
fails deletes nothing. Also the dry run, the denormalized Warren fields following the log, and the one-time cleanup script."""

from datetime import datetime, timedelta

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.warren_signal_data as wsd
import pipeline.backfills.reconcile_warren_events as rec
from analysis.warren_signal.types import WarrenReplayResult, WarrenSignalEvent as EngineEvent
from core.models import EtfScreenerRow, TechnicalEntrySignal, TickerScore, WarrenSignalEvent
from data.warren_signal_data import (
    EventReconcile,
    apply_warren_event_reconcile,
    compute_and_store_warren_signal,
    compute_and_store_warren_signal_with_events,
    plan_event_reconcile,
    plan_warren_event_reconcile,
    refresh_warren_score_fields,
)

T0 = datetime(2026, 1, 5, 9, 30)  # the one candle _tiny_ohlcv builds, so the write gate is T0 + EVENT_WRITE_WARMUP_DAYS


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(wsd, "engine", eng)
    monkeypatch.setattr(rec, "engine", eng)
    monkeypatch.setattr(wsd, "EVENT_WRITE_WARMUP_DAYS", 0)  # the gate is the first candle unless a test sets it
    return eng


def _bars() -> pd.DataFrame:
    idx = pd.DatetimeIndex(["2026-01-05 09:30"], tz="America/New_York")
    return pd.DataFrame({"open": [10.0], "high": [10.5], "low": [9.5], "close": [10.0], "volume": [1000]}, index=idx)


def _ev(kind: str, day: int, hour: int = 12, stop: float | None = 90.0) -> EngineEvent:
    return EngineEvent(kind=kind, fired_at=datetime(2026, 2, day, hour, 30), close=100.0, rsi=30.0, stop_price=stop)


def _stub(monkeypatch, events: list[EngineEvent], as_of: datetime = datetime(2026, 2, 28, 15, 30)):
    result = WarrenReplayResult(as_of=as_of, events=events, gray_suppressed=False, stop_count=0, live_stop_price=90.0)
    monkeypatch.setattr(wsd, "replay", lambda candles, profile=None: result)


def _store(engine, kind: str, day: int, hour: int = 12, created: datetime = datetime(2026, 1, 1, 1, 1), stop: float = 1.0, ticker: str = "AAA", month: int = 2):
    with Session(engine) as s:
        s.add(WarrenSignalEvent(ticker=ticker, timeframe="2h", signal_kind=kind, fired_at=datetime(2026, month, day, hour, 30), stop_price=stop, created_at=created))
        s.commit()


def _log(engine, ticker: str = "AAA"):
    with Session(engine) as s:
        rows = s.exec(select(WarrenSignalEvent).where(WarrenSignalEvent.ticker == ticker).order_by(WarrenSignalEvent.fired_at, WarrenSignalEvent.signal_kind)).all()
    return [(r.signal_kind, r.fired_at, r.stop_price, r.created_at) for r in rows]


def test_a_stored_event_the_replay_no_longer_produces_is_deleted(monkeypatch, engine):
    _store(engine, "yellow_up", 10, hour=12)  # the phantom: the arrow now fires a candle later
    _store(engine, "gray_down", 20)
    _stub(monkeypatch, [_ev("yellow_up", 10, hour=14), _ev("gray_down", 20)])
    _, plan = compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    assert plan.deleted == (("yellow_up", datetime(2026, 2, 10, 12, 30)),) and plan.added == (("yellow_up", datetime(2026, 2, 10, 14, 30)),)
    assert [(k, f.hour) for k, f, _, _ in _log(engine)] == [("yellow_up", 14), ("gray_down", 12)]


def test_a_replay_arrow_with_no_stored_event_is_inserted_with_its_stop_and_a_fresh_created_at(monkeypatch, engine):
    _stub(monkeypatch, [_ev("blue_up", 3, stop=88.5)])
    before = datetime.now()
    _, plan = compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    assert plan.added == (("blue_up", datetime(2026, 2, 3, 12, 30)),) and plan.deleted == ()
    ((kind, fired, stop, created),) = _log(engine)
    assert (kind, stop) == ("blue_up", 88.5) and created >= before


def test_a_matching_event_is_left_untouched_created_at_and_stop_as_written(monkeypatch, engine):
    old_created = datetime(2026, 1, 2, 3, 4, 5)
    _store(engine, "yellow_up", 10, created=old_created, stop=77.7)
    _stub(monkeypatch, [_ev("yellow_up", 10, stop=90.0)])  # the replay's stop differs slightly; the key matches
    _, plan = compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    assert not plan.changed and plan.unchanged == 1
    assert _log(engine) == [("yellow_up", datetime(2026, 2, 10, 12, 30), 77.7, old_created)]


def test_events_before_the_write_gate_are_never_read_or_changed(monkeypatch, engine):
    monkeypatch.setattr(wsd, "EVENT_WRITE_WARMUP_DAYS", 30)  # the gate: 2026-02-04 09:30
    _store(engine, "yellow_up", 2, created=datetime(2026, 1, 1))  # before the gate, not in the replay: stays
    _store(engine, "gray_down", 1, created=datetime(2026, 1, 1), month=3)  # after the gate, not in the replay: goes
    _stub(monkeypatch, [_ev("yellow_up", 2), _ev("blue_down", 8)], as_of=datetime(2026, 3, 31, 15, 30))  # the replay's own pre-gate arrow is not written
    _, plan = compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    assert plan.deleted == (("gray_down", datetime(2026, 3, 1, 12, 30)),) and plan.added == (("blue_down", datetime(2026, 2, 8, 12, 30)),)
    assert [(k, f.month, f.day) for k, f, _, _ in _log(engine)] == [("yellow_up", 2, 2), ("blue_down", 2, 8)]


def test_a_second_run_changes_nothing(monkeypatch, engine):
    _store(engine, "yellow_up", 10, hour=12)
    _stub(monkeypatch, [_ev("yellow_up", 10, hour=14), _ev("gray_down", 20)])
    compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    first = _log(engine)
    _, plan = compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    assert not plan.changed and plan.unchanged == 2 and _log(engine) == first  # created_at included


def test_a_replay_that_yields_nothing_deletes_nothing(monkeypatch, engine):
    _store(engine, "yellow_up", 10)
    _stub(monkeypatch, [])
    _, plan = compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    assert plan.skipped and "yields no event" in plan.skipped and not plan.changed
    assert len(_log(engine)) == 1


def test_a_failed_replay_raises_before_any_event_is_touched(monkeypatch, engine):
    _store(engine, "yellow_up", 10)

    def boom(candles, profile=None):
        raise ValueError("No candles given to replay against")

    monkeypatch.setattr(wsd, "replay", boom)
    with pytest.raises(ValueError):
        compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    with pytest.raises(ValueError):
        plan_warren_event_reconcile("AAA", _bars())
    assert len(_log(engine)) == 1


def test_a_reconcile_that_would_delete_most_of_the_window_is_refused(monkeypatch, engine):
    for day in range(1, 7):
        _store(engine, "yellow_up", day)  # six stored, none reproduced
    _stub(monkeypatch, [_ev("gray_down", 20)])
    _, plan = compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    assert plan.skipped and "would delete 6 of 6" in plan.skipped
    assert len(_log(engine)) == 6  # nothing deleted, nothing inserted


def test_an_event_after_the_last_replayed_candle_is_never_deleted(monkeypatch, engine):
    _store(engine, "yellow_up", 25)  # newer than the bars the replay covered
    _stub(monkeypatch, [_ev("yellow_up", 10)], as_of=datetime(2026, 2, 20, 15, 30))
    _, plan = compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    assert plan.deleted == () and plan.added == (("yellow_up", datetime(2026, 2, 10, 12, 30)),)
    assert len(_log(engine)) == 2


def test_a_provisional_bar_arrow_is_corrected_on_the_next_run(monkeypatch, engine):
    # night 1: the newest session's bars are provisional and the arrow fires on the 14:30 stamp
    _stub(monkeypatch, [_ev("yellow_up", 10, hour=14)])
    compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    assert [(k, f.hour) for k, f, _, _ in _log(engine)] == [("yellow_up", 14)]
    # night 2: the final bars move it one candle earlier (and add nothing else)
    _stub(monkeypatch, [_ev("yellow_up", 10, hour=12)])
    _, plan = compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    assert plan.deleted == (("yellow_up", datetime(2026, 2, 10, 14, 30)),) and plan.added == (("yellow_up", datetime(2026, 2, 10, 12, 30)),)
    assert [(k, f.hour) for k, f, _, _ in _log(engine)] == [("yellow_up", 12)]


def test_the_plan_is_pure_and_the_dry_run_writes_nothing(monkeypatch, engine):
    _store(engine, "yellow_up", 10, hour=12)
    _stub(monkeypatch, [_ev("yellow_up", 10, hour=14)])
    before = _log(engine)
    plan = plan_warren_event_reconcile("AAA", _bars())
    assert plan.deleted and plan.added
    assert _log(engine) == before
    with Session(engine) as s:
        assert s.get(TechnicalEntrySignal, ("AAA", "warren", "2h")) is None  # not even the latest-state row


def test_apply_reconcile_alone_rewrites_events_but_not_the_latest_state_row(monkeypatch, engine):
    _store(engine, "yellow_up", 10, hour=12)
    _stub(monkeypatch, [_ev("yellow_up", 10, hour=14)])
    plan = apply_warren_event_reconcile("AAA", _bars())
    assert plan.changed and [(k, f.hour) for k, f, _, _ in _log(engine)] == [("yellow_up", 14)]
    with Session(engine) as s:
        assert s.get(TechnicalEntrySignal, ("AAA", "warren", "2h")) is None


def test_the_pure_plan_function_orders_and_counts():
    stored = {("yellow_up", datetime(2026, 2, 1)), ("gray_down", datetime(2026, 2, 2))}
    replay_events = [EngineEvent(kind="gray_down", fired_at=datetime(2026, 2, 2), close=1.0, rsi=1.0, stop_price=None), _ev("blue_up", 3)]
    plan = plan_event_reconcile("AAA", stored, replay_events, datetime(2026, 1, 1), datetime(2026, 2, 28))
    assert plan.deleted == (("yellow_up", datetime(2026, 2, 1)),) and plan.added == (("blue_up", datetime(2026, 2, 3, 12, 30)),) and plan.unchanged == 1


def test_the_score_fields_follow_the_log_after_a_reconcile(monkeypatch, engine):
    phantom = datetime(2026, 2, 10, 12, 30)
    _store(engine, "yellow_up", 10, hour=12)  # the phantom: it is the newest buy in the log
    with Session(engine) as s:
        s.add(TickerScore(ticker="AAA", overall_score=60, computed_at=datetime(2026, 2, 1), warren_last_buy_fired_at=phantom, warren_active_signal_kind="yellow_up"))
        s.add(EtfScreenerRow(ticker="AAA", warren_last_buy_fired_at=phantom))
        s.commit()
    _stub(monkeypatch, [_ev("yellow_up", 4), _ev("gray_down", 6)])  # the replay has an earlier buy and a later sell: nothing is active
    _, plan = compute_and_store_warren_signal_with_events("AAA", _bars(), source="fmp")
    assert plan.changed
    assert refresh_warren_score_fields(["AAA"]) == 2
    with Session(engine) as s:
        score, etf = s.get(TickerScore, "AAA"), s.get(EtfScreenerRow, "AAA")
    assert score.warren_last_buy_fired_at == datetime(2026, 2, 4, 12, 30) == etf.warren_last_buy_fired_at
    assert score.warren_active_signal_kind is None and etf.warren_active_signal_kind is None
    assert refresh_warren_score_fields(["AAA", "ZZZ"]) == 0  # idempotent; a ticker with no rows is skipped


def test_compute_and_store_still_returns_only_the_latest_state_row(monkeypatch, engine):
    _stub(monkeypatch, [_ev("yellow_up", 10)])
    out = compute_and_store_warren_signal("AAA", _bars(), source="fmp")
    assert out.signal_kind == "yellow_up" and out.ticker == "AAA"


# --- the one-time cleanup / dry-run script -------------------------------------------------------------------------


@pytest.fixture
def script(monkeypatch, engine):
    monkeypatch.setattr(rec, "list_monitored_tickers", lambda session: (["AAA", "BBB", "NOBARS"], ["E1"]))
    monkeypatch.setattr(rec, "_load_frames", lambda session, tickers, interval, start: {"AAA": _bars(), "BBB": _bars()})
    return engine


def test_the_script_dry_run_reports_deletes_adds_and_consumer_changes_and_writes_nothing(monkeypatch, script, capsys):
    _store(script, "yellow_up", 10, hour=12, ticker="AAA")  # phantom, the newest buy
    _store(script, "yellow_up", 4, ticker="BBB")  # BBB already matches the replay
    _store(script, "yellow_up", 9, hour=14, ticker="BBB")
    with Session(script) as s:
        s.add(TickerScore(ticker="AAA", overall_score=60, computed_at=datetime(2026, 2, 1), warren_last_buy_fired_at=datetime(2026, 2, 10, 12, 30)))
        s.commit()
    _stub(monkeypatch, [_ev("yellow_up", 4), _ev("yellow_up", 9, hour=14)])
    before = _log(script, "AAA") + _log(script, "BBB")
    out = rec.main(apply=False)
    assert _log(script, "AAA") + _log(script, "BBB") == before
    assert out["changed"] == ["AAA"] and out["deleted"] == 1 and out["added"] == 2 and out["no_bars"] == ["NOBARS"] and out["refreshed"] == 0
    (change,) = [c for c in out["consumer_changes"] if c["ticker"] == "AAA"]
    assert change["last_buy_now"] == datetime(2026, 2, 10, 12, 30) and change["last_buy_after"] == datetime(2026, 2, 9, 14, 30)
    assert change["score_row"] == datetime(2026, 2, 10, 12, 30) and change["etf_row"] == "no row"
    printed = capsys.readouterr().out
    assert "DRY RUN" in printed and "delete yellow_up" in printed and "add    yellow_up" in printed and "NO BARS NOBARS" in printed


def test_the_script_apply_reconciles_every_ticker_and_refreshes_the_score_rows(monkeypatch, script):
    _store(script, "yellow_up", 10, hour=12, ticker="AAA")
    with Session(script) as s:
        s.add(TickerScore(ticker="AAA", overall_score=60, computed_at=datetime(2026, 2, 1), warren_last_buy_fired_at=datetime(2026, 2, 10, 12, 30)))
        s.commit()
    _stub(monkeypatch, [_ev("yellow_up", 9, hour=14)])
    out = rec.main(apply=True)
    assert out["changed"] == ["AAA", "BBB"] and out["refreshed"] == 1
    assert [(k, f.day, f.hour) for k, f, _, _ in _log(script, "AAA")] == [("yellow_up", 9, 14)]
    with Session(script) as s:
        assert s.get(TickerScore, "AAA").warren_last_buy_fired_at == datetime(2026, 2, 9, 14, 30)
    assert rec.main(apply=False)["changed"] == []  # a rerun finds nothing to do


def test_a_ticker_whose_replay_fails_is_reported_and_keeps_its_events(monkeypatch, script):
    _store(script, "yellow_up", 10, hour=12, ticker="AAA")

    def boom(candles, profile=None):
        raise ValueError("No candles given to replay against")

    monkeypatch.setattr(wsd, "replay", boom)
    out = rec.main(apply=True)
    assert [t for t, _ in out["failed"]] == ["AAA", "BBB"] and len(_log(script, "AAA")) == 1


def test_nightly_bars_start_is_the_shared_cache_trim():
    now = datetime(2026, 10, 18, 6, 0).astimezone()
    assert (rec._eastern_today(now) - rec.nightly_bars_start(now)).days == rec.LOOKBACK_DAYS - 1
