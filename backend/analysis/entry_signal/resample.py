"""Resamples raw intraday OHLCV bars into custom 2-hour session candles --
ported from the reference bot's `build_2h_candles`, the one piece of its
custom-candle construction this feature keeps. Deliberately shared by both
source adapters (see clients/technical_sources.py) so the signal engine
below stays source-agnostic, per this feature's own requirement.
"""

import pandas as pd

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
