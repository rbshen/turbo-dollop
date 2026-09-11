"""Orchestration layer for the technical entry-signal feature -- same
get_stepN_data shape as data/trend_analysis_data.py: calls the pure
calculation engine (analysis/entry_signal/) and persists/reads the result
(models.py::TechnicalEntrySignal). Independent of FMP entirely.

Unlike trend_analysis_data.py, there is no live-fetch path here: this
signal is scoped to the union of every watchlist named W1 through W5
and refreshed only by the nightly cron job
(pipeline/nightly_entry_signal_calculation.py) -- get_entry_signal_data
below is a plain cache-only read, returning None for a ticker that was
never on either watchlist or hasn't been processed yet.
"""

from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import delete, or_, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from analysis.entry_signal.engine import compute_entry_signal
from analysis.entry_signal.types import EntrySignalResult
from core.db import engine
from core.models import TechnicalEntrySignal, TechnicalEntrySignalEvent
from core.schemas import TechnicalEntrySignalOut
from core.tickers import normalize_ticker

DEFAULT_SIGNAL_TYPE = "bb_rsi"
DEFAULT_TIMEFRAME = "2h"

# How long a fire stays "active" after fired_at, derived at read time --
# never stored, never cleaned up by a separate job (see
# is_entry_signal_active below and models.py::TechnicalEntrySignal.fired_at's
# own comment).
ACTIVE_WINDOW_DAYS = 7

# How long a row can go un-recomputed (e.g. its ticker dropped off every
# W1-W5 watchlist) before sweep_stale_entry_signals clears it.
STALE_AFTER_DAYS = 7

# How long a TechnicalEntrySignalEvent row is kept before
# prune_entry_signal_events deletes it -- matches Yahoo's own 730-day
# 2h-interval history limit (see the historical-backfill investigation).
# Confirmed via a real measurement (2026-09-11, isolated marker-query cost
# against a warm backfilled DB, synthetic bars to remove Yahoo/FMP network
# variance -- 5 real tickers spanning the actual event-row-count range,
# 8-42 rows each, all 4 Chart tab ranges, 30 iterations each) that keeping
# the full 730-day window adds NEGLIGIBLE load time: mean marginal cost
# 2.0ms, max 6.2ms, against a 54-188ms baseline (dominated by indicator
# computation on the fetched bar series, not this query) -- well under 1%
# to ~6% of the baseline, and completely lost in the noise floor (tens of
# ms of swing, including negative deltas) of a real end-to-end
# measurement that includes an actual live Yahoo fetch. This is well
# below any threshold that would justify the shorter 365-day alternative
# considered before this measurement -- retention stays at the full
# 730 days.
EVENT_RETENTION_DAYS = 730


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
    second conditional statement.

    Also inserts into TechnicalEntrySignalEvent whenever this run fired,
    independent of the should_advance/newer-than check above -- the event
    table accumulates every distinct fire (feeding the Chart tab's
    history), not just the single latest one TechnicalEntrySignal tracks.
    No detection-logic change: this reuses the exact same `result` already
    computed for the upsert above. on_conflict_do_nothing on the same
    unique key makes a rerun against an already-recorded fire (e.g. a
    same-day re-run evaluating the same "today" candle again) a no-op
    rather than a duplicate row or an error."""
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

        if result.fired:
            event_stmt = sqlite_insert(TechnicalEntrySignalEvent).values(
                ticker=ticker,
                signal_type=signal_type,
                timeframe=timeframe,
                fired_at=result.fired_at,
                stop_price=result.stop_price,
                created_at=computed_at,
            )
            event_stmt = event_stmt.on_conflict_do_nothing(index_elements=["ticker", "signal_type", "timeframe", "fired_at"])
            session.execute(event_stmt)

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
    been computed (not a member of any W1-W5 watchlist, or the nightly job
    hasn't reached it yet)."""
    ticker = normalize_ticker(ticker)
    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, (ticker, signal_type, timeframe))
    return _row_to_out(row) if row else None


def sweep_stale_entry_signals(now: datetime | None = None) -> int:
    """Clears (never deletes) any row whose computed_at is more than
    STALE_AFTER_DAYS old -- the case where a ticker has fallen off every
    W1-W5 watchlist and so is no longer reached by the nightly
    job's per-ticker loop at all. Nulls fired_at/pct_b/rsi/close/
    stop_price (all already-Optional fields, so no schema change) so a
    stale fire/reading is never displayed as if current -- `active` reads
    False automatically once fired_at is None. source/as_of/computed_at
    are deliberately left untouched, standing as a "last known" breadcrumb
    (computed_at in particular is what the ticker-page card uses to show
    "computed on X, no longer tracked") rather than deleting the row
    outright, which would lose that breadcrumb for no real storage-cost
    benefit (this table is one row per ticker/signal_type/timeframe, not
    an accumulating time series).

    Only rewrites rows that actually still have something to clear, so
    re-running this against an already-swept row is a cheap no-op, not a
    repeated write. Returns the number of rows cleared."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=STALE_AFTER_DAYS)
    with Session(engine) as session:
        stmt = (
            update(TechnicalEntrySignal)
            .where(
                TechnicalEntrySignal.computed_at < cutoff,
                or_(
                    TechnicalEntrySignal.fired_at.is_not(None),
                    TechnicalEntrySignal.pct_b.is_not(None),
                    TechnicalEntrySignal.rsi.is_not(None),
                    TechnicalEntrySignal.close.is_not(None),
                    TechnicalEntrySignal.stop_price.is_not(None),
                ),
            )
            .values(fired_at=None, pct_b=None, rsi=None, close=None, stop_price=None)
        )
        result = session.execute(stmt)
        session.commit()
        return result.rowcount


def record_historical_entry_signal_events(
    ticker: str,
    results: list[EntrySignalResult],
    signal_type: str = DEFAULT_SIGNAL_TYPE,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> int:
    """Bulk counterpart to _upsert's single-event insert, for
    pipeline/backfills/backfill_entry_signal_events.py -- one row per
    result (typically the output of analysis.entry_signal.engine.
    compute_historical_entry_signals), same on_conflict_do_nothing
    idempotency guarantee so re-running the backfill is safe. Deliberately
    touches ONLY TechnicalEntrySignalEvent, never TechnicalEntrySignal --
    a backfill populates history, it must never overwrite the single
    "latest fire" row the nightly job's own _upsert owns.

    Returns the number of rows actually inserted (SQLite's
    on_conflict_do_nothing reports 0 rowcount for a skipped conflict, so
    a rerun against already-recorded events returns 0 without erroring)."""
    ticker = normalize_ticker(ticker)
    if not results:
        return 0
    created_at = datetime.now()
    inserted = 0
    with Session(engine) as session:
        for result in results:
            stmt = sqlite_insert(TechnicalEntrySignalEvent).values(
                ticker=ticker,
                signal_type=signal_type,
                timeframe=timeframe,
                fired_at=result.fired_at,
                stop_price=result.stop_price,
                created_at=created_at,
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=["ticker", "signal_type", "timeframe", "fired_at"])
            exec_result = session.execute(stmt)
            inserted += exec_result.rowcount
        session.commit()
    return inserted


def prune_entry_signal_events(retention_days: int = EVENT_RETENTION_DAYS, now: datetime | None = None) -> int:
    """Deletes (genuinely -- not cleared, unlike sweep_stale_entry_signals
    above) TechnicalEntrySignalEvent rows older than retention_days. Unlike
    TechnicalEntrySignal's one-row-per-key "latest state," this table is a
    real accumulating time series with no "last known" breadcrumb value to
    preserve once a row falls outside every Chart tab range that could ever
    display it -- deleting outright is the correct behavior here, not a
    storage-cost shortcut.

    retention_days defaults to EVENT_RETENTION_DAYS (730, matching Yahoo's
    own 2h-interval history limit -- see the historical-backfill
    investigation and that constant's own comment for the measured
    Chart-tab latency numbers behind this choice) rather than being
    hardcoded here, so a call site (or a test) can override it without
    reaching into module internals.

    Returns the number of rows deleted."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=retention_days)
    with Session(engine) as session:
        stmt = delete(TechnicalEntrySignalEvent).where(TechnicalEntrySignalEvent.fired_at < cutoff)
        result = session.execute(stmt)
        session.commit()
        return result.rowcount
