"""Top-level composition: resample -> RSI/BB/ATR -> scan today's candles
for check_buy_signal -> EntrySignalResult. The single function
data/entry_signal_data.py calls; everything below it stays pure (no DB, no
HTTP), matching analysis/trend_structure/engine.py's own composition style.
"""

from datetime import date as date_

import pandas as pd

from .indicators import ATR_MULTIPLIER, check_buy_signal, compute_atr, compute_bollinger_bands, compute_rsi
from .resample import build_2h_session_candles
from .types import EntrySignalResult


def compute_entry_signal(ohlcv: pd.DataFrame) -> EntrySignalResult:
    """ohlcv must be raw intraday bars (tz-aware datetime index, lowercase
    open/high/low/close/volume columns) -- resampling into 2h session
    candles happens here, not in the caller, so both source adapters can
    hand this the same raw shape (see clients/technical_sources.py).

    Evaluates check_buy_signal against every candle for the most recent
    trading day present in the data, not just the very last one -- a fire
    that happened mid-day and no longer qualifies by the session's final
    candle would otherwise never be seen at all. Since this only ever runs
    once nightly, "the most recent trading day present" IS "since the last
    run" in practice; re-running against the same day's data (a skipped or
    re-run job) is harmless -- see data/entry_signal_data.py::_upsert's own
    strict-newer-than check, which this function has no need to duplicate.

    as_of/fired_at are returned as naive datetimes (tzinfo stripped, not
    converted -- candles are already Eastern-time throughout, see
    resample.py) to match this codebase's own naive-datetime convention
    elsewhere (e.g. `datetime.now()` for computed_at) and, concretely, so
    a freshly computed fired_at can be compared against one already
    round-tripped through SQLite -- SQLite drops tzinfo on storage, so a
    stored value read back is always naive; comparing that against a
    tz-aware fresh value raises TypeError."""
    candles = build_2h_session_candles(ohlcv)

    if candles.empty:
        raise ValueError("No 2h session candles could be built from the given OHLCV bars")

    close = candles["close"]
    rsi = compute_rsi(close)
    _, _, pct_b = compute_bollinger_bands(close)
    atr = compute_atr(candles)

    as_of = candles.index[-1].to_pydatetime().replace(tzinfo=None)
    latest_date = candles.index[-1].date()
    todays_indices = [i for i, ts in enumerate(candles.index) if ts.date() == latest_date]

    fired = False
    fired_at = None
    pct_b_fired = rsi_fired = close_fired = stop_price_fired = None

    for i in todays_indices:
        if not check_buy_signal(rsi, pct_b, i):
            continue
        fired = True
        fired_at = candles.index[i].to_pydatetime().replace(tzinfo=None)
        pct_b_i = pct_b.iloc[i]
        rsi_i = rsi.iloc[i]
        atr_i = atr.iloc[i]
        pct_b_fired = float(pct_b_i) if pd.notna(pct_b_i) else None
        rsi_fired = float(rsi_i) if pd.notna(rsi_i) else None
        close_fired = float(close.iloc[i])
        stop_price_fired = float(close_fired - atr_i * ATR_MULTIPLIER) if pd.notna(atr_i) else None
        # Keep scanning -- later indices overwrite earlier ones, so
        # whatever's left when the loop ends is the LATEST firing candle.

    return EntrySignalResult(
        as_of=as_of,
        fired=fired,
        fired_at=fired_at,
        pct_b=pct_b_fired,
        rsi=rsi_fired,
        close=close_fired,
        stop_price=stop_price_fired,
    )


def compute_historical_entry_signals(ohlcv: pd.DataFrame) -> list[EntrySignalResult]:
    """Backfill-only counterpart to compute_entry_signal above -- added
    alongside it, not a modification, since the nightly job's own
    detection logic (this function, check_buy_signal, compute_rsi, etc.)
    must stay exactly as-is (see data/entry_signal_data.py's own
    docstring for why). Computes RSI/Bollinger/ATR ONCE over the entire
    given history, so 14/20-period warmup is correct throughout, then
    scans EVERY trading day present -- not just the most recent one.

    Tie-breaking deliberately differs from compute_entry_signal:
    compute_entry_signal keeps the LAST firing candle of a day, matching
    TechnicalEntrySignal's "most recent tradeable fire" semantics --
    correct for that table's own purpose, and left unchanged here. This
    function keeps the FIRST firing candle of each day instead: a
    historical chart marker answers "when did this setup first appear,"
    not "what's still live," and confirmed real data shows the two
    answers commonly differ -- a from-scratch scan across a 6-ticker,
    2-year sample found ~56% of firing days fired 2+ times in the same
    session (RSI-oversold conditions tend to persist across consecutive
    2h bars during a single drawdown leg), so this tie-break is
    frequently load-bearing, not a rare edge case.

    Returns one EntrySignalResult per trading day that had at least one
    real fire, ordered chronologically -- unlike compute_entry_signal,
    quiet days are omitted entirely rather than represented by a
    fired=False result, since there's no "latest state" concept here to
    report a quiet day against."""
    candles = build_2h_session_candles(ohlcv)
    if candles.empty:
        raise ValueError("No 2h session candles could be built from the given OHLCV bars")

    close = candles["close"]
    rsi = compute_rsi(close)
    _, _, pct_b = compute_bollinger_bands(close)
    atr = compute_atr(candles)

    results_by_day: dict[date_, EntrySignalResult] = {}
    for i in range(len(candles)):
        if not check_buy_signal(rsi, pct_b, i):
            continue
        day = candles.index[i].date()
        if day in results_by_day:
            continue  # first fire of this day already recorded -- later same-day fires are ignored
        fired_at = candles.index[i].to_pydatetime().replace(tzinfo=None)
        pct_b_i = pct_b.iloc[i]
        rsi_i = rsi.iloc[i]
        atr_i = atr.iloc[i]
        results_by_day[day] = EntrySignalResult(
            as_of=fired_at,
            fired=True,
            fired_at=fired_at,
            pct_b=float(pct_b_i) if pd.notna(pct_b_i) else None,
            rsi=float(rsi_i) if pd.notna(rsi_i) else None,
            close=float(close.iloc[i]),
            stop_price=float(close.iloc[i] - atr_i * ATR_MULTIPLIER) if pd.notna(atr_i) else None,
        )

    return [results_by_day[d] for d in sorted(results_by_day)]
