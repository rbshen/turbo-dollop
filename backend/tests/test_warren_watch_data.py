"""The Warren Signals watch table's data layer (data/warren_watch_data.py): the 3-month seed, idempotent reruns, the
incremental cursor, removal, the 2nd-LP lookup and the nightly job's final step. The replay is stubbed with canned
arrows (its arrows are pinned against the ThinkScript in analysis/warren_signal/test_thinkscript_parity.py); the bars
are real 60m frames so the candles, the forming-candle drop and the window-start times are the production ones."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.warren_watch_data as wwd
import pipeline.nightly_warren_signal_calculation as nightly
from analysis.liquidity_zones.types import LiquidityZoneSettings
from analysis.warren_signal.types import WarrenReplayResult, WarrenSignalEvent
from core.cron_health import CronRunContext
from core.models import WarrenWatchCursor, WarrenWatchRow

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)  # a Saturday morning: every 2h candle through Friday is complete
SETTINGS = LiquidityZoneSettings(
    swing_bars_each_side=2, cluster_pct=0.0, max_lps_per_side=3, over_cap_priority="nearest_price",
    keep_last_breached_support=True, keep_last_breached_resistance=True, only_keep_if_breached_recently=True, breach_recency_bars=5,
)


@pytest.fixture(autouse=True)
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(wwd, "engine", eng)
    return eng


def bars(start: str, end: str, lows: dict[str, float] | None = None) -> pd.DataFrame:
    """Flat 60m bars (close 100, low 99) on every weekday from start to end, 09:30..15:30. `lows` lowers the low of a
    date's 09:30 bar."""
    lows = lows or {}
    rows, index = [], []
    for d in pd.bdate_range(start, end):
        for h, m in [(9, 30), (10, 30), (11, 30), (12, 30), (13, 30), (14, 30), (15, 30)]:
            index.append(pd.Timestamp(d.year, d.month, d.day, h, m, tz="America/New_York"))
            low = lows.get(d.strftime("%Y-%m-%d"), 99.0) if (h, m) == (9, 30) else 99.0
            rows.append({"open": 100.0, "high": 101.0, "low": low, "close": 100.0, "volume": 1000})
    return pd.DataFrame(rows, index=pd.DatetimeIndex(index))


def canned(monkeypatch, by_ticker: dict[str, list[tuple[str, str]]], first_yellow: dict[str, list[str]] | None = None):
    """Stub the replay: {ticker: [(kind, "YYYY-MM-DD HH:MM"), ...]} become its arrows (window-start stamps)."""
    first_yellow = first_yellow or {}

    def fake(ticker, candles, daily_volume=None):
        events = [WarrenSignalEvent(kind=k, fired_at=datetime.fromisoformat(t), close=0.0, rsi=None, stop_price=None) for k, t in by_ticker.get(ticker, [])]
        return WarrenReplayResult(
            as_of=candles.index[-1].to_pydatetime(), events=events, gray_suppressed=False, stop_count=0, live_stop_price=None,
            first_yellow_after_blue_at=[datetime.fromisoformat(t) for t in first_yellow.get(ticker, [])],
        )

    monkeypatch.setattr(wwd, "watch_replay", fake)


def fake_lp(monkeypatch, supports: list[float]):
    seen: list[int] = []

    def fake(candles, settings):
        seen.append(len(candles))
        return SimpleNamespace(support=[SimpleNamespace(price=p) for p in supports])

    monkeypatch.setattr(wwd, "compute_liquidity_zones_2h", fake)
    return seen


def rows(engine) -> dict[str, WarrenWatchRow]:
    with Session(engine) as s:
        return {r.ticker: r for r in s.exec(select(WarrenWatchRow)).all()}


def run(ticker, frame, **kw):
    return wwd.update_warren_watch(ticker, frame, SETTINGS, now=NOW, **kw)


# --- seed -------------------------------------------------------------------------------------------------------


def test_seed_reads_three_months_and_creates_rows_only_for_tickers_with_an_up_arrow_in_the_window(monkeypatch, engine):
    frame = bars("2026-04-01", "2026-10-16")
    # as_of is 2026-10-16 15:30, so the seed reads candles after 2026-07-16 15:30.
    canned(monkeypatch, {
        "OLD": [("yellow_up", "2026-05-04 09:30")],  # before the window
        "DOWN": [("blue_down", "2026-08-03 09:30")],  # a down arrow with no earlier up arrow in the window
        "NEW": [("yellow_up", "2026-05-04 09:30"), ("blue_up", "2026-09-01 09:30")],
        "EDGE": [("blue_up", "2026-07-16 15:30"), ("blue_up", "2026-07-17 09:30")],  # at `after`: ignored; the next is read
    })
    outcomes = {t: run(t, frame).outcome for t in ("OLD", "DOWN", "NEW", "EDGE")}
    assert outcomes == {"OLD": "no_row", "DOWN": "no_row", "NEW": "created", "EDGE": "created"}
    got = rows(engine)
    assert set(got) == {"NEW", "EDGE"}
    assert got["NEW"].entry_kind == "blue" and got["NEW"].entry_at == datetime(2026, 9, 1, 9, 30)  # the pre-window yellow is not applied
    assert got["EDGE"].entry_at == datetime(2026, 7, 17, 9, 30)
    with Session(engine) as s:
        cursors = {c.ticker: c.processed_through for c in s.exec(select(WarrenWatchCursor)).all()}
    assert set(cursors) == {"OLD", "DOWN", "NEW", "EDGE"}  # every ticker is seeded once, row or not
    assert set(cursors.values()) == {datetime(2026, 10, 16, 15, 30)}
    assert got["NEW"].as_of == datetime(2026, 10, 16, 15, 30)


def test_row_fields_after_a_seed(monkeypatch, engine):
    frame = bars("2026-07-01", "2026-10-16")
    canned(monkeypatch, {"TECL": [("yellow_up", "2026-09-01 11:30")]})
    run("TECL", frame)
    r = rows(engine)["TECL"]
    assert (r.profile, r.latest_arrow_kind, r.latest_arrow_at, r.last_signal_at) == ("tecl", "yellow_up", datetime(2026, 9, 1, 11, 30), datetime(2026, 9, 1, 11, 30))
    assert (r.instruction_type, r.entry_kind, r.entry_price) == (3, "yellow", 100.0)
    assert r.instruction_text.startswith("YELLOW UP: new entry = 10% stop")
    assert (r.stop_price, r.stop_basis, r.status, r.breached_at, r.removed_at) == (pytest.approx(89.1), "10%", "active", None, None)
    assert r.last_updated_at is not None


def test_a_young_ticker_with_less_history_than_the_window_is_seeded_from_what_it_has(monkeypatch, engine):
    frame = bars("2026-09-28", "2026-10-16")
    canned(monkeypatch, {"IPO": [("blue_up", "2026-10-01 09:30")]})
    assert run("IPO", frame).outcome == "created"


# --- idempotence and the cursor ---------------------------------------------------------------------------------


def test_a_rerun_for_the_same_session_changes_nothing(monkeypatch, engine):
    frame = bars("2026-07-01", "2026-10-16")
    canned(monkeypatch, {"A": [("yellow_up", "2026-09-01 09:30"), ("blue_down", "2026-09-10 09:30")], "B": [("blue_up", "2026-09-02 09:30")]})
    fake_lp(monkeypatch, [95.0, 90.0, 85.0])
    for t in ("A", "B"):
        run(t, frame)
    with Session(engine) as s:
        before = [r.model_dump() for r in s.exec(select(WarrenWatchRow).order_by(WarrenWatchRow.ticker)).all()]
        cursors_before = [c.model_dump() for c in s.exec(select(WarrenWatchCursor).order_by(WarrenWatchCursor.ticker)).all()]
    seen = fake_lp(monkeypatch, [95.0, 90.0, 85.0])
    second = [run(t, frame) for t in ("A", "B")]
    assert [u.outcome for u in second] == ["unchanged", "unchanged"]
    assert [u.candles_read for u in second] == [0, 0] and [u.lp_calls for u in second] == [0, 0] and seen == []
    with Session(engine) as s:
        after = [r.model_dump() for r in s.exec(select(WarrenWatchRow).order_by(WarrenWatchRow.ticker)).all()]
        cursors_after = [c.model_dump() for c in s.exec(select(WarrenWatchCursor).order_by(WarrenWatchCursor.ticker)).all()]
    assert after == before and cursors_after == cursors_before


def test_a_later_session_reads_only_the_new_candles_and_does_not_reapply_old_arrows(monkeypatch, engine):
    canned(monkeypatch, {"A": [("yellow_up", "2026-09-01 09:30"), ("yellow_up", "2026-10-15 09:30")]})
    seen = fake_lp(monkeypatch, [80.0, 70.0, 60.0])
    run("A", bars("2026-07-01", "2026-10-14"))  # the second yellow does not exist yet in the bars
    first = rows(engine)["A"]
    assert first.stop_price == pytest.approx(89.1) and seen == []
    update = run("A", bars("2026-07-01", "2026-10-16"))
    second = rows(engine)["A"]
    assert update.outcome == "changed" and update.lp_calls == 1
    assert second.last_signal_at == datetime(2026, 10, 15, 9, 30)
    assert second.entry_at == datetime(2026, 9, 1, 9, 30)  # unchanged
    assert (second.stop_price, second.stop_basis) == (70.0, "LP")  # the 2nd of [80, 70, 60]
    assert seen[-1] == len(wwd.completed_candles(bars("2026-07-01", "2026-10-16"), NOW)) - 7  # sliced as of the arrow candle (2026-10-15 09:30: seven candles remain after it)


def test_a_missed_night_catches_up_over_every_candle_since_the_cursor(monkeypatch, engine):
    canned(monkeypatch, {"A": [("yellow_up", "2026-09-01 09:30")]})
    run("A", bars("2026-07-01", "2026-10-12", lows={}))
    assert rows(engine)["A"].status == "active"
    run("A", bars("2026-07-01", "2026-10-16", lows={"2026-10-14": 80.0}))  # three sessions later, one traded under the stop (89.1)
    r = rows(engine)["A"]
    assert (r.status, r.breached_at) == ("breached", datetime(2026, 10, 14, 9, 30))


# --- LP, down arrows, breach ------------------------------------------------------------------------------------


def test_lp_is_asked_only_where_an_instruction_needs_it_and_uses_the_second_nearest_support(monkeypatch, engine):
    canned(monkeypatch, {
        "Y": [("yellow_up", "2026-09-01 09:30"), ("gray_down", "2026-09-03 09:30")],  # fresh yellow + gray down: entry price, no LP
        "B": [("blue_up", "2026-09-01 09:30"), ("yellow_down", "2026-09-03 09:30")],  # yellow down on a blue entry: no action, no LP
        "D": [("yellow_up", "2026-09-01 09:30"), ("blue_down", "2026-09-03 09:30")],  # blue down: LP
    })
    seen = fake_lp(monkeypatch, [96.0, 92.5, 90.0])
    frame = bars("2026-07-01", "2026-10-16")
    assert [run(t, frame).lp_calls for t in ("Y", "B", "D")] == [0, 0, 1]
    got = rows(engine)
    assert (got["Y"].stop_price, got["Y"].stop_basis, got["Y"].instruction_type) == (100.0, "entry", 30)
    assert (got["B"].stop_price, got["B"].stop_basis, got["B"].instruction_type) == (None, "none", 20)
    assert (got["D"].stop_price, got["D"].stop_basis, got["D"].instruction_type) == (92.5, "LP", 10)
    assert len(seen) == 1


def test_fewer_than_two_supports_leaves_the_stop_alone(monkeypatch, engine):
    canned(monkeypatch, {"D": [("yellow_up", "2026-09-01 09:30"), ("blue_down", "2026-09-03 09:30")]})
    fake_lp(monkeypatch, [96.0])
    run("D", bars("2026-07-01", "2026-10-16"))
    r = rows(engine)["D"]
    assert (r.stop_price, r.stop_basis, r.instruction_type) == (pytest.approx(89.1), "10%", 10)


def test_a_breach_through_the_data_layer_then_a_fresh_yellow_resets(monkeypatch, engine):
    canned(monkeypatch, {"A": [("yellow_up", "2026-09-01 09:30"), ("yellow_up", "2026-09-21 09:30")]})
    fake_lp(monkeypatch, [50.0, 40.0])
    run("A", bars("2026-07-01", "2026-09-18", lows={"2026-09-10": 85.0}))
    r = rows(engine)["A"]
    assert (r.status, r.breached_at, r.stop_price, r.instruction_type) == ("breached", datetime(2026, 9, 10, 9, 30), pytest.approx(89.1), 3)
    run("A", bars("2026-07-01", "2026-10-16", lows={"2026-09-10": 85.0}))
    r = rows(engine)["A"]
    assert (r.status, r.breached_at, r.entry_at) == ("active", None, datetime(2026, 9, 21, 9, 30))
    assert (r.stop_price, r.stop_basis) == (pytest.approx(89.1), "10%")  # fresh entry, not min(LP 40, ...)


# --- removal ----------------------------------------------------------------------------------------------------


def test_a_removed_ticker_stays_removed_until_a_genuinely_newer_arrow(monkeypatch, engine):
    canned(monkeypatch, {"A": [("blue_up", "2026-09-01 09:30"), ("yellow_up", "2026-09-10 09:30")]})
    run("A", bars("2026-07-01", "2026-09-15"))
    assert wwd.remove_watch_row("A", now_et=datetime(2026, 9, 16, 10, 0)) is True
    assert wwd.remove_watch_row("A") is False and wwd.remove_watch_row("ZZZ") is False
    assert [r.ticker for r in wwd.list_watch_rows()] == [] and [r.ticker for r in wwd.list_watch_rows(include_removed=True)] == ["A"]

    # Later sessions, the same old arrows in the replay: nothing resurrects the row, and its frozen content is untouched.
    frozen = rows(engine)["A"].model_dump()
    assert run("A", bars("2026-07-01", "2026-10-01")).outcome == "removed"
    assert rows(engine)["A"].model_dump() == frozen

    # A newer arrow wakes it as a fresh row: removed_at cleared, the old state not carried over.
    canned(monkeypatch, {"A": [("blue_up", "2026-09-01 09:30"), ("yellow_up", "2026-09-10 09:30"), ("blue_up", "2026-10-05 09:30")]})
    assert run("A", bars("2026-07-01", "2026-10-16")).outcome == "created"
    r = rows(engine)["A"]
    assert (r.removed_at, r.entry_kind, r.entry_at, r.stop_price, r.instruction_type) == (None, "blue", datetime(2026, 10, 5, 9, 30), None, 2)
    assert [x.ticker for x in wwd.list_watch_rows()] == ["A"]


def test_arrows_at_or_before_removed_at_are_ignored_even_if_the_cursor_is_older(monkeypatch, engine):
    canned(monkeypatch, {"A": [("blue_up", "2026-09-01 09:30")]})
    run("A", bars("2026-07-01", "2026-09-02"))
    wwd.remove_watch_row("A", now_et=datetime(2026, 10, 1, 12, 0))
    canned(monkeypatch, {"A": [("blue_up", "2026-09-20 09:30"), ("yellow_up", "2026-10-01 11:30"), ("yellow_up", "2026-10-02 09:30")]})
    run("A", bars("2026-07-01", "2026-10-16"))  # 09-20 and 10-01 11:30 are at or before the removal (10-01 12:00)
    r = rows(engine)["A"]
    assert r.entry_at == datetime(2026, 10, 2, 9, 30) and r.removed_at is None


def test_a_removed_row_is_not_breached_or_refreshed_by_later_candles(monkeypatch, engine):
    canned(monkeypatch, {"A": [("yellow_up", "2026-09-01 09:30")]})
    run("A", bars("2026-07-01", "2026-09-04"))
    wwd.remove_watch_row("A", now_et=datetime(2026, 9, 5, 10, 0))
    run("A", bars("2026-07-01", "2026-10-16", lows={"2026-09-20": 10.0}))
    r = rows(engine)["A"]
    assert r.status == "active" and r.as_of == datetime(2026, 9, 4, 15, 30)


def test_an_empty_frame_raises(engine):
    with pytest.raises(ValueError):
        run("A", bars("2026-07-01", "2026-07-01").iloc[0:0])


# --- the nightly job's final step -------------------------------------------------------------------------------


def test_the_job_step_counts_created_changed_failed_and_lp_calls(monkeypatch, engine):
    monkeypatch.setattr(nightly, "engine", engine)
    canned(monkeypatch, {"A": [("blue_up", "2026-09-01 09:30")], "B": []})
    frame = bars("2026-07-01", "2026-10-16")
    monkeypatch.setattr(nightly, "update_warren_watch", lambda t, b, s: wwd.update_warren_watch(t, b, s, now=NOW))
    summary = nightly.update_watch_table(["A", "B", "C"], {"A": frame, "B": frame})  # C has no bars
    assert (summary["watch_attempted"], summary["watch_created"], summary["watch_changed"], summary["watch_failed"]) == (3, 1, 0, 1)
    assert summary["watch_failures"] == [("C", "No intraday bars returned")]
    again = nightly.update_watch_table(["A", "B"], {"A": frame, "B": frame})
    assert (again["watch_created"], again["watch_changed"], again["watch_failed"]) == (0, 0, 0)


def test_record_outcome_reports_the_watch_step_and_fails_a_broken_one():
    base = {"processed": 105, "failed": 0, "swept": 0, "pruned": 0, "stale_count": 0}
    run_ = CronRunContext()
    nightly.record_outcome({**base, "watch_attempted": 105, "watch_failed": 1, "watch_created": 3, "watch_changed": 2}, run_)
    assert run_.message.endswith("; watch table: 3 created, 2 changed, 1 failed")
    with pytest.raises(RuntimeError, match="watch table"):
        nightly.record_outcome({**base, "watch_attempted": 105, "watch_failed": 105, "watch_created": 0, "watch_changed": 0}, CronRunContext())


# --- the arrows the table acts on are the chart's ---------------------------------------------------------------


@pytest.mark.parametrize("ticker", ["AAPL", "QQQ"])
def test_the_watch_reads_the_same_candles_and_arrows_as_the_chart_range(ticker):
    import numpy as np

    from analysis.entry_signal.resample import build_2h_session_candles_fast, drop_forming_candles, index_by_window_start
    from analysis.warren_signal.state_machine import replay_with_series
    from clients.daily_bar_sources import _is_half_day
    from data.warren_signal_data import profile_for, signal_candles

    rng = np.random.default_rng(3)
    frame = bars("2025-11-03", "2026-10-16")
    steps = rng.normal(-0.0006, 0.004, len(frame))
    close = 100 * np.exp(np.cumsum(steps))
    frame["close"], frame["open"] = close, close
    frame["high"], frame["low"] = close * 1.002, close * 0.998

    # The Chart tab's 2H·90D path, step for step (data/chart_data.py::_get_chart_data_2h).
    chart_candles = index_by_window_start(drop_forming_candles(build_2h_session_candles_fast(frame), NOW, is_half_day=_is_half_day))
    chart_result, _ = replay_with_series(signal_candles(ticker, chart_candles, pd.Series(dtype=float)), profile_for(ticker))

    watch_candles = wwd.completed_candles(frame, NOW)
    pd.testing.assert_frame_equal(watch_candles, chart_candles)
    watch_result = wwd.watch_replay(ticker, watch_candles, pd.Series(dtype=float))
    assert watch_result.events == chart_result.events
    assert watch_result.first_yellow_after_blue_at == chart_result.first_yellow_after_blue_at
    assert chart_result.events  # the walk fires arrows, so this compares something
