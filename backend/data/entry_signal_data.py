"""Orchestration layer for the technical entry-signal feature -- same
get_stepN_data shape as data/trend_analysis_data.py: calls the pure
calculation engine (analysis/entry_signal/) and persists/reads the result
(models.py::TechnicalEntrySignal). Independent of FMP entirely.

Unlike trend_analysis_data.py, there is no live-fetch path here: this
signal is scoped to the single named "Watchlist" watchlist and refreshed
only by the nightly cron job (pipeline/nightly_entry_signal_calculation.py)
-- get_entry_signal_data below is a plain cache-only read, returning None
for a ticker that was never in that watchlist or hasn't been processed yet.
"""

from datetime import datetime

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from analysis.entry_signal.engine import compute_entry_signal
from analysis.entry_signal.types import EntrySignalResult
from core.db import engine
from core.models import TechnicalEntrySignal
from core.schemas import TechnicalEntrySignalOut
from core.tickers import normalize_ticker

DEFAULT_SIGNAL_TYPE = "bb_rsi"
DEFAULT_TIMEFRAME = "2h"


def _upsert(ticker: str, signal_type: str, timeframe: str, result: EntrySignalResult, source: str, computed_at: datetime) -> None:
    fields = {
        "fired": result.fired,
        "pct_b": result.pct_b,
        "rsi": result.rsi,
        "close": result.close,
        "source": source,
        "as_of": result.as_of,
        "computed_at": computed_at,
    }
    with Session(engine) as session:
        stmt = sqlite_insert(TechnicalEntrySignal).values(ticker=ticker, signal_type=signal_type, timeframe=timeframe, **fields)
        stmt = stmt.on_conflict_do_update(index_elements=["ticker", "signal_type", "timeframe"], set_=fields)
        session.execute(stmt)
        session.commit()


def _row_to_out(row: TechnicalEntrySignal) -> TechnicalEntrySignalOut:
    return TechnicalEntrySignalOut(
        ticker=row.ticker,
        signal_type=row.signal_type,
        timeframe=row.timeframe,
        fired=row.fired,
        pct_b=row.pct_b,
        rsi=row.rsi,
        close=row.close,
        source=row.source,
        as_of=row.as_of,
        computed_at=row.computed_at,
    )


def compute_and_store_entry_signal(
    ticker: str,
    ohlcv: pd.DataFrame,
    source: str,
    signal_type: str = DEFAULT_SIGNAL_TYPE,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> TechnicalEntrySignalOut:
    """Runs the pure calculation engine against already-fetched raw
    intraday OHLCV bars and upserts -- no fetch of its own, so the nightly
    job's one batch fetch (see clients/technical_sources.py) is shared
    across every ticker's compute, not re-fetched per ticker. Raises
    ValueError if the engine can't build any 2h candles at all (e.g. no
    bars within session hours) -- callers (the nightly job's per-ticker
    loop) treat this like any other per-ticker failure."""
    ticker = normalize_ticker(ticker)
    result = compute_entry_signal(ohlcv)
    computed_at = datetime.now()
    _upsert(ticker, signal_type, timeframe, result, source, computed_at)

    return TechnicalEntrySignalOut(
        ticker=ticker,
        signal_type=signal_type,
        timeframe=timeframe,
        fired=result.fired,
        pct_b=result.pct_b,
        rsi=result.rsi,
        close=result.close,
        source=source,
        as_of=result.as_of,
        computed_at=computed_at,
    )


async def get_entry_signal_data(
    ticker: str, signal_type: str = DEFAULT_SIGNAL_TYPE, timeframe: str = DEFAULT_TIMEFRAME
) -> TechnicalEntrySignalOut | None:
    """Cache-only read -- never triggers a live fetch (see module
    docstring). Returns None if this ticker/signal_type/timeframe has never
    been computed (not a Watchlist member, or the nightly job hasn't
    reached it yet)."""
    ticker = normalize_ticker(ticker)
    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, (ticker, signal_type, timeframe))
    return _row_to_out(row) if row else None
