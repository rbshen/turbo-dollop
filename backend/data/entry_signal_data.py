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

from datetime import datetime, timedelta

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

# How long a fire stays "active" after fired_at, derived at read time --
# never stored, never cleaned up by a separate job (see
# is_entry_signal_active below and models.py::TechnicalEntrySignal.fired_at's
# own comment).
ACTIVE_WINDOW_DAYS = 7


def is_entry_signal_active(fired_at: datetime | None, now: datetime | None = None) -> bool:
    """`now` exists purely so tests can pin a deterministic clock -- every
    real call site omits it and gets the live wall-clock time."""
    now = now or datetime.now()
    return fired_at is not None and (now - fired_at) < timedelta(days=ACTIVE_WINDOW_DAYS)


def _upsert(ticker: str, signal_type: str, timeframe: str, result: EntrySignalResult, source: str, computed_at: datetime) -> None:
    """Always advances the heartbeat fields (source/as_of/computed_at) --
    but only advances fired_at/pct_b/rsi/close/stop_price together, and
    only when this run's fire is genuinely newer than whatever's already
    stored. A quiet night (or a re-evaluation of an already-recorded fire)
    must never erase a still-relevant prior fire -- omitting these keys
    from `fields` when they shouldn't advance means the UPDATE's SET
    clause simply never touches those columns, rather than needing a
    second conditional statement."""
    with Session(engine) as session:
        previous = session.get(TechnicalEntrySignal, (ticker, signal_type, timeframe))
        should_advance = result.fired and (previous is None or previous.fired_at is None or result.fired_at > previous.fired_at)

        fields: dict = {"source": source, "as_of": result.as_of, "computed_at": computed_at}
        if should_advance:
            fields.update(
                fired_at=result.fired_at,
                pct_b=result.pct_b,
                rsi=result.rsi,
                close=result.close,
                stop_price=result.stop_price,
            )

        stmt = sqlite_insert(TechnicalEntrySignal).values(ticker=ticker, signal_type=signal_type, timeframe=timeframe, **fields)
        stmt = stmt.on_conflict_do_update(index_elements=["ticker", "signal_type", "timeframe"], set_=fields)
        session.execute(stmt)
        session.commit()


def _row_to_out(row: TechnicalEntrySignal) -> TechnicalEntrySignalOut:
    return TechnicalEntrySignalOut(
        ticker=row.ticker,
        signal_type=row.signal_type,
        timeframe=row.timeframe,
        active=is_entry_signal_active(row.fired_at),
        fired_at=row.fired_at,
        pct_b=row.pct_b,
        rsi=row.rsi,
        close=row.close,
        stop_price=row.stop_price,
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
    loop) treat this like any other per-ticker failure.

    Re-reads the row after upserting rather than building the return value
    from `result` alone: result.fired_at can be None on a quiet night even
    though a real prior fire is still on record (and still active) --
    the caller must see what's actually persisted, not just this run's
    own delta."""
    ticker = normalize_ticker(ticker)
    result = compute_entry_signal(ohlcv)
    computed_at = datetime.now()
    _upsert(ticker, signal_type, timeframe, result, source, computed_at)

    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, (ticker, signal_type, timeframe))
    return _row_to_out(row)


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
