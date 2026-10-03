"""Resamples raw intraday OHLCV bars into custom 2-hour session candles --
ported from the reference bot's `build_2h_candles`, the one piece of its
custom-candle construction this feature keeps. Shared by the BB+RSI engine
(analysis/entry_signal/engine.py) and the Warren replay
(data/warren_signal_data.py), so both signal engines stay independent of
where the 60m bars come from (today only the shared bars cache,
clients/shared_bars_cache.py).
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

_ET = ZoneInfo("America/New_York")

# Fixed session windows, matching the reference bot exactly -- NOT even
# splits of the trading day (the last window is only 30 minutes), since
# they're anchored to the actual 9:30-16:00 ET session boundaries.
SESSION_WINDOWS: list[tuple[str, str]] = [
    ("09:30", "11:30"),
    ("11:30", "13:30"),
    ("13:30", "15:30"),
    ("15:30", "16:00"),
]


def build_2h_session_candles(df: pd.DataFrame) -> pd.DataFrame:
    """df must have a tz-aware datetime index and lowercase
    open/high/low/close/volume columns. Returns one row per session window
    per trading day actually present in `df`, indexed by that window's last
    bar's own timestamp (not the window boundary) -- same convention the
    reference bot uses, so a downstream check_buy_signal-style evaluation on
    "the latest candle" reads the real timestamp of the data behind it, not
    a synthetic 2h-aligned boundary."""
    df = df.copy()
    df.index = df.index.tz_convert("America/New_York")
    df = df.between_time("09:30", "16:00")
    df["date"] = df.index.date

    rows = []
    for _, group in df.groupby("date"):
        group = group.sort_index()
        for start, end in SESSION_WINDOWS:
            chunk = group.between_time(start, end, inclusive="left")
            if len(chunk) == 0:
                continue
            rows.append(
                {
                    "timestamp": chunk.index[-1],
                    "open": chunk["open"].iloc[0],
                    "high": chunk["high"].max(),
                    "low": chunk["low"].min(),
                    "close": chunk["close"].iloc[-1],
                    "volume": chunk["volume"].sum(),
                }
            )

    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    return pd.DataFrame(rows).set_index("timestamp")


# ---------------------------------------------------------------------------
# Vectorised builder + display helpers (2H.90D Chart range). The function above
# stays untouched -- BB+RSI's and Warren's nightly jobs depend on it.
# ---------------------------------------------------------------------------

_SESSION_OPEN_MIN = 9 * 60 + 30
_SESSION_CLOSE_MIN = 16 * 60
_WINDOW_START_MIN = (570, 690, 810, 930)  # 09:30, 11:30, 13:30, 15:30
_WINDOW_END_MIN = {570: 690, 690: 810, 810: 930, 930: 960}
# The 60m bar (labelled by its start) that completes each window. The 15:30 bar is the window's only bar and
# really lasts 30 minutes (the session closes at 16:00).
_WINDOW_LAST_BAR_START_MIN = {570: 630, 690: 750, 810: 870, 930: 930}
_HALF_DAY_CLOSE_MIN = 13 * 60
_OHLCV = ["open", "high", "low", "close", "volume"]


def _tod_seconds(index: pd.DatetimeIndex) -> np.ndarray:
    return (index.hour * 3600 + index.minute * 60 + index.second).to_numpy()


def build_2h_session_candles_fast(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorised equivalent of build_2h_session_candles: the same input contract (tz-aware datetime
    index, lowercase open/high/low/close/volume), the same output (one row per session window per
    trading day present, indexed by the window's last bar's own timestamp, America/New_York,
    index name "timestamp") -- bit-identical on real data (see test_resample.py), ~100x faster (the
    original loops per day in Python, ~0.85s for 2 years of 60m bars).

    Regular session only: 09:30-11:30, 11:30-13:30, 13:30-15:30, 15:30-16:00 (the short last window is
    kept); pre/post-market bars, and a bar stamped exactly 16:00, belong to no window."""
    df = df.copy()
    df.index = df.index.tz_convert("America/New_York")
    df = df.sort_index(kind="stable")
    tod = _tod_seconds(df.index)
    in_session = (tod >= _SESSION_OPEN_MIN * 60) & (tod < _SESSION_CLOSE_MIN * 60)
    df, tod = df[in_session], tod[in_session]
    if df.empty:
        return pd.DataFrame(columns=_OHLCV)

    window = np.select([tod < 690 * 60, tod < 810 * 60, tod < 930 * 60], [0, 1, 2], 3)
    keys = pd.MultiIndex.from_arrays([df.index.date, window])
    ts = pd.Series(df.index, index=df.index)
    g = df.groupby(keys, sort=True)
    # skipna=False keeps the original's iloc[0]/iloc[-1] semantics (first/last would skip a NaN).
    out = pd.DataFrame(
        {
            "timestamp": ts.groupby(keys, sort=True).last(skipna=False),
            "open": g["open"].first(skipna=False),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(skipna=False),
            "volume": g["volume"].sum(),
        }
    )
    return out.set_index("timestamp")[_OHLCV]


def session_window_start(ts: pd.Timestamp) -> pd.Timestamp:
    """The 09:30/11:30/13:30/15:30 window start (same date, same tz) of the window `ts` falls in --
    for a candle indexed by its last bar's timestamp, that candle's display time."""
    minutes = ts.hour * 60 + ts.minute
    start = max((m for m in _WINDOW_START_MIN if m <= minutes), default=_SESSION_OPEN_MIN)
    # Wall-clock arithmetic on the naive time, then re-localised: adding a Timedelta to a tz-aware midnight
    # is ABSOLUTE time and lands an hour off on a DST-switch date.
    naive = ts.tz_localize(None).normalize() + pd.Timedelta(minutes=start)
    return naive.tz_localize(ts.tz) if ts.tz is not None else naive


def index_by_window_start(candles: pd.DataFrame) -> pd.DataFrame:
    """Re-indexes candles (indexed by last-bar timestamp, tz-aware ET) by their window START as a naive
    America/New_York wall-clock DatetimeIndex -- the chart's candle time. One candle per window, so unique.
    Vectorised (same mapping as session_window_start, wall-clock arithmetic on the naive time)."""
    out = candles.copy()
    naive = candles.index.tz_localize(None)
    minutes = naive.hour * 60 + naive.minute
    start = np.select([minutes >= m for m in reversed(_WINDOW_START_MIN)], list(reversed(_WINDOW_START_MIN)), default=_SESSION_OPEN_MIN)
    out.index = pd.DatetimeIndex(naive.normalize() + pd.to_timedelta(start, unit="m"), name="window_start")
    return out


def drop_forming_candles(candles: pd.DataFrame, now: datetime, is_half_day=None) -> pd.DataFrame:
    """Drops candles whose window is still forming as of `now`, so neither the chart nor any signal
    ever evaluates a partial candle (the state machine would fire arrows that vanish once the candle
    completes). `candles` is indexed by last-bar timestamp (tz-aware ET), as the builders return.

    Only candles dated TODAY (US/Eastern) can be forming; earlier ones are kept even if a bar is
    missing (the nightly jobs keep those too). A today-candle is complete only when BOTH hold:
    - clock: `now` is at/after the window's end (11:30, 13:30, 15:30, 16:00; capped at 13:00 on an
      early-close day when `is_half_day(date)` says so), and
    - data: its last bar is the window's final 60m bar (10:30, 12:30, 14:30, 15:30) -- guards a
      provider that has not delivered the window's last bar yet."""
    if candles.empty:
        return candles
    now_et = now.astimezone(_ET) if now.tzinfo else now.replace(tzinfo=timezone.utc).astimezone(_ET)
    today = now_et.date()
    now_min = now_et.hour * 60 + now_et.minute + now_et.second / 60
    keep = []
    for ts in candles.index:
        d = ts.date()
        if d != today:
            keep.append(d < today)
            continue
        start_ts = session_window_start(ts)
        start = start_ts.hour * 60 + start_ts.minute
        end = _WINDOW_END_MIN[start]
        if is_half_day is not None and is_half_day(d):
            end = min(end, _HALF_DAY_CLOSE_MIN)
        keep.append(now_min >= end and ts.hour * 60 + ts.minute >= _WINDOW_LAST_BAR_START_MIN[start])
    return candles[np.array(keep, dtype=bool)]
