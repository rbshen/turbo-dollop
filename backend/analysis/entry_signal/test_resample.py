import numpy as np
import pandas as pd
import pytest

from analysis.entry_signal.resample import build_2h_session_candles


def _bar(ts: str, o: float, h: float, l: float, c: float, v: int) -> dict:
    return {"timestamp": pd.Timestamp(ts, tz="America/New_York"), "open": o, "high": h, "low": l, "close": c, "volume": v}


def test_builds_four_windows_for_a_full_trading_day():
    # One 60m bar per hour, 9:30 -> 15:30 (7 bars), matching the reference
    # bot's own 4-window split: 09:30-11:30 | 11:30-13:30 | 13:30-15:30 | 15:30-16:00.
    rows = [
        _bar("2026-01-05 09:30", 100, 101, 99, 100.5, 1000),
        _bar("2026-01-05 10:30", 100.5, 102, 100, 101.5, 1100),
        _bar("2026-01-05 11:30", 101.5, 103, 101, 102.5, 1200),
        _bar("2026-01-05 12:30", 102.5, 104, 102, 103.5, 1300),
        _bar("2026-01-05 13:30", 103.5, 105, 103, 104.5, 1400),
        _bar("2026-01-05 14:30", 104.5, 106, 104, 105.5, 1500),
        _bar("2026-01-05 15:30", 105.5, 107, 105, 106.5, 1600),
    ]
    df = pd.DataFrame(rows).set_index("timestamp")

    candles = build_2h_session_candles(df)

    assert len(candles) == 4
    # Window 1 (09:30-11:30, left-inclusive of 11:30): bars at 09:30, 10:30
    first = candles.iloc[0]
    assert first["open"] == pytest.approx(100.0)
    assert first["close"] == pytest.approx(101.5)
    assert first["high"] == pytest.approx(102.0)
    assert first["low"] == pytest.approx(99.0)
    assert first["volume"] == 2100
    # Window 4 (15:30-16:00): just the one 15:30 bar
    last = candles.iloc[3]
    assert last["open"] == pytest.approx(105.5)
    assert last["close"] == pytest.approx(106.5)
    assert last["volume"] == 1600


def test_timestamp_index_is_the_windows_own_last_bar():
    rows = [
        _bar("2026-01-05 09:30", 100, 101, 99, 100.5, 1000),
        _bar("2026-01-05 10:30", 100.5, 102, 100, 101.5, 1100),
    ]
    df = pd.DataFrame(rows).set_index("timestamp")

    candles = build_2h_session_candles(df)

    assert len(candles) == 1
    assert candles.index[0] == pd.Timestamp("2026-01-05 10:30", tz="America/New_York")


def test_empty_input_returns_empty_frame_with_expected_columns():
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df.index = pd.DatetimeIndex([], tz="America/New_York")

    candles = build_2h_session_candles(df)

    assert candles.empty
    assert list(candles.columns) == ["open", "high", "low", "close", "volume"]


def test_bars_outside_session_hours_are_excluded():
    rows = [
        _bar("2026-01-05 08:00", 99, 99, 99, 99, 500),  # pre-market, excluded
        _bar("2026-01-05 09:30", 100, 101, 99, 100.5, 1000),
        _bar("2026-01-05 16:30", 200, 200, 200, 200, 500),  # after-hours, excluded
    ]
    df = pd.DataFrame(rows).set_index("timestamp")

    candles = build_2h_session_candles(df)

    assert len(candles) == 1
    assert candles.iloc[0]["close"] == pytest.approx(100.5)


# ---------------------------------------------------------------------------
# build_2h_session_candles_fast -- must reproduce the original exactly
# ---------------------------------------------------------------------------

from datetime import datetime, timezone

from analysis.entry_signal.resample import (
    build_2h_session_candles_fast,
    drop_forming_candles,
    index_by_window_start,
    session_window_start,
)

_NY = "America/New_York"


def _session_bars(day: str, hours: list[str], seed: int, base: float = 100.0) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows = []
    price = base
    for hhmm in hours:
        o = price
        c = o + float(rng.normal(0, 0.5))
        rows.append(
            {
                "timestamp": pd.Timestamp(f"{day} {hhmm}", tz=_NY),
                "open": o,
                "high": max(o, c) + abs(float(rng.normal(0, 0.2))),
                "low": min(o, c) - abs(float(rng.normal(0, 0.2))),
                "close": c,
                "volume": int(rng.integers(100, 5000)),
            }
        )
        price = c
    return rows


FULL_DAY = ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]
HALF_DAY = ["09:30", "10:30", "11:30", "12:30"]


def _assert_equivalent(df: pd.DataFrame) -> pd.DataFrame:
    old = build_2h_session_candles(df)
    new = build_2h_session_candles_fast(df)
    pd.testing.assert_frame_equal(new, old, check_exact=True)
    assert new.index.name == old.index.name
    return new


def test_fast_builder_matches_original_on_normal_days():
    rows = []
    for i, day in enumerate(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]):
        rows += _session_bars(day, FULL_DAY, seed=i)
    _assert_equivalent(pd.DataFrame(rows).set_index("timestamp"))


def test_fast_builder_matches_original_on_early_close_half_days():
    # The day after Thanksgiving 2026 (11-27) closes at 13:00 -> only 09:30..12:30 bars exist; Dec 24 likewise.
    rows = _session_bars("2026-11-25", FULL_DAY, 1) + _session_bars("2026-11-27", HALF_DAY, 2) + _session_bars("2026-12-24", HALF_DAY, 3)
    new = _assert_equivalent(pd.DataFrame(rows).set_index("timestamp"))
    assert len(new[new.index.date == pd.Timestamp("2026-11-27").date()]) == 2  # two windows, no 13:30/15:30


@pytest.mark.parametrize("day", ["2026-03-06", "2026-03-09", "2026-11-02"])
def test_fast_builder_matches_original_around_dst_switch_dates(day):
    # 2026-03-08 (spring forward) and 2026-11-01 (fall back) are Sundays: build the sessions either side,
    # and feed them as UTC (what a UTC-stored provider would hand over) to exercise the tz_convert path.
    days = {"2026-03-06": ["2026-03-05", "2026-03-06"], "2026-03-09": ["2026-03-09", "2026-03-10"], "2026-11-02": ["2026-10-30", "2026-11-02"]}[day]
    rows = []
    for i, d in enumerate(days):
        rows += _session_bars(d, FULL_DAY, seed=10 + i)
    df = pd.DataFrame(rows).set_index("timestamp")
    df.index = df.index.tz_convert("UTC")
    new = _assert_equivalent(df)
    assert (new.index.hour * 60 + new.index.minute).isin([630, 750, 870, 930]).all()  # ET wall-clock, not shifted by DST


def test_fast_builder_matches_original_with_extended_hours_gaps_16h_bar_and_nan_open():
    rows = _session_bars("2026-01-05", ["04:00", "08:30", "09:30", "10:30", "12:30", "13:30", "15:30", "16:00", "17:30"], seed=7)
    rows += _session_bars("2026-01-06", ["10:30", "14:30"], seed=8)  # windows with a missing first bar
    df = pd.DataFrame(rows).set_index("timestamp")
    df.loc[df.index[2], "open"] = np.nan  # a NaN first open must stay NaN (iloc[0] semantics), not be skipped
    _assert_equivalent(df)


def test_fast_builder_empty_and_no_session_inputs():
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=pd.DatetimeIndex([], tz=_NY))
    out = build_2h_session_candles_fast(empty)
    assert out.empty and list(out.columns) == ["open", "high", "low", "close", "volume"]
    pre = pd.DataFrame(_session_bars("2026-01-05", ["04:00", "17:00"], 1)).set_index("timestamp")
    assert build_2h_session_candles_fast(pre).empty


def test_session_window_start_maps_every_bar_and_survives_dst_dates():
    for day in ["2026-01-05", "2026-03-09", "2026-11-02"]:
        for bar, start in [("09:30", "09:30"), ("10:30", "09:30"), ("11:30", "11:30"), ("12:30", "11:30"), ("13:30", "13:30"), ("14:30", "13:30"), ("15:30", "15:30")]:
            assert session_window_start(pd.Timestamp(f"{day} {bar}", tz=_NY)) == pd.Timestamp(f"{day} {start}", tz=_NY)
    # The two actual switch dates (Sundays, but the arithmetic must still be wall-clock).
    assert session_window_start(pd.Timestamp("2026-03-08 14:30", tz=_NY)) == pd.Timestamp("2026-03-08 13:30", tz=_NY)
    assert session_window_start(pd.Timestamp("2026-11-01 10:30", tz=_NY)) == pd.Timestamp("2026-11-01 09:30", tz=_NY)


def test_index_by_window_start_is_naive_et_wall_clock_and_unique():
    rows = _session_bars("2026-01-05", FULL_DAY, 1) + _session_bars("2026-01-06", HALF_DAY, 2)
    candles = index_by_window_start(build_2h_session_candles_fast(pd.DataFrame(rows).set_index("timestamp")))
    assert candles.index.tz is None and candles.index.is_unique
    assert [t.strftime("%H:%M") for t in candles.index[:4]] == ["09:30", "11:30", "13:30", "15:30"]
    assert [t.strftime("%H:%M") for t in candles.index[4:]] == ["09:30", "11:30"]


# ---------------------------------------------------------------------------
# drop_forming_candles
# ---------------------------------------------------------------------------


def _candles_for(day: str, hours: list[str]) -> pd.DataFrame:
    return build_2h_session_candles_fast(pd.DataFrame(_session_bars(day, hours, 5)).set_index("timestamp"))


def _now(day: str, hhmm: str) -> datetime:
    return pd.Timestamp(f"{day} {hhmm}", tz=_NY).to_pydatetime().astimezone(timezone.utc)


def test_drop_forming_keeps_all_candles_of_past_days():
    candles = _candles_for("2026-01-05", FULL_DAY)
    assert len(drop_forming_candles(candles, _now("2026-01-06", "09:31"))) == 4


@pytest.mark.parametrize(
    "hhmm,bars,kept",
    [
        ("10:00", ["09:30"], 0),  # first window still forming (its 10:30 bar not complete)
        ("11:29", ["09:30", "10:30"], 0),  # 10:30 bar delivered early but the window ends at 11:30
        ("11:31", ["09:30", "10:30"], 1),
        ("11:31", ["09:30"], 0),  # clock says done but the provider has not delivered the 10:30 bar yet
        ("13:45", ["09:30", "10:30", "11:30", "12:30", "13:30"], 2),  # 13:30 window forming
        ("15:45", ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"], 3),  # 15:30 (short) window forming
        ("16:01", ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"], 4),
    ],
)
def test_drop_forming_today_candle_rule(hhmm, bars, kept):
    candles = _candles_for("2026-01-05", bars)
    assert len(drop_forming_candles(candles, _now("2026-01-05", hhmm))) == kept


def test_drop_forming_respects_early_close_day():
    from clients.daily_bar_sources import _is_half_day

    candles = _candles_for("2026-11-27", HALF_DAY)
    # Window 11:30-13:30 completes at the 13:00 close on a half-day, not 13:30.
    assert len(drop_forming_candles(candles, _now("2026-11-27", "13:05"), is_half_day=_is_half_day)) == 2
    assert len(drop_forming_candles(candles, _now("2026-11-27", "13:05"))) == 1  # without the hint it is still forming


def test_drop_forming_accepts_naive_now_as_utc_and_empty_input():
    candles = _candles_for("2026-01-05", FULL_DAY)
    now_utc_naive = pd.Timestamp("2026-01-05 21:30").to_pydatetime()  # 16:30 ET
    assert len(drop_forming_candles(candles, now_utc_naive)) == 4
    assert drop_forming_candles(candles.iloc[0:0], now_utc_naive).empty


def test_index_by_window_start_vectorised_matches_the_scalar_mapping_including_dst_dates():
    rows = []
    for i, d in enumerate(["2026-03-06", "2026-03-09", "2026-11-02", "2026-11-27"]):
        rows += _session_bars(d, HALF_DAY if d == "2026-11-27" else FULL_DAY, seed=i)
    candles = build_2h_session_candles_fast(pd.DataFrame(rows).set_index("timestamp"))
    got = index_by_window_start(candles).index
    expected = [session_window_start(ts).tz_localize(None) for ts in candles.index]
    assert list(got) == expected and got.tz is None
