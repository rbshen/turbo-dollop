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
