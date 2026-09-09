"""Top-level composition: resample -> RSI/BB -> check_buy_signal ->
EntrySignalResult. The single function data/entry_signal_data.py calls;
everything below it stays pure (no DB, no HTTP), matching
analysis/trend_structure/engine.py's own composition style.
"""

import pandas as pd

from .indicators import check_buy_signal, compute_bollinger_bands, compute_rsi
from .resample import build_2h_session_candles
from .types import EntrySignalResult


def compute_entry_signal(ohlcv: pd.DataFrame) -> EntrySignalResult:
    """ohlcv must be raw intraday bars (tz-aware datetime index, lowercase
    open/high/low/close/volume columns) -- resampling into 2h session
    candles happens here, not in the caller, so both source adapters can
    hand this the same raw shape (see clients/technical_sources.py)."""
    candles = build_2h_session_candles(ohlcv)

    if candles.empty:
        raise ValueError("No 2h session candles could be built from the given OHLCV bars")

    close = candles["close"]
    rsi = compute_rsi(close)
    _, _, pct_b = compute_bollinger_bands(close)

    i = len(candles) - 1
    fired = check_buy_signal(rsi, pct_b, i)

    pct_b_now = pct_b.iloc[i]
    rsi_now = rsi.iloc[i]

    return EntrySignalResult(
        fired=fired,
        pct_b=float(pct_b_now) if pd.notna(pct_b_now) else None,
        rsi=float(rsi_now) if pd.notna(rsi_now) else None,
        close=float(close.iloc[i]),
        as_of=candles.index[i].to_pydatetime(),
    )
