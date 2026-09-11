"""Orchestration layer for the Warren RSI/ADX/WVF technical entry-signal
feature -- same overall shape as data/entry_signal_data.py, but a distinct
module (not a branch inside that one) since Warren's persistence and
"active" semantics genuinely differ from BB+RSI's:

- BB+RSI's nightly job only evaluates the LATEST trading day and
  conditionally advances fired_at/pct_b/rsi/close/stop_price (only when a
  newer fire is found) -- see entry_signal_data.py::_upsert's own
  should_advance guard. Warren's nightly job instead REPLAYS THE FULL
  available history every run (analysis/warren_signal/state_machine.py's
  own module docstring explains why this is safe/idempotent) and always
  overwrites the latest-state row with that replay's true current state --
  there's no "quiet night, don't erase a still-relevant prior fire" case to
  guard against, because every run recomputes the truth from scratch.
- BB+RSI's `active` is a flat 7-day window off fired_at
  (is_entry_signal_active). Warren's `active` is the literal `inTrade`
  mapping the request asked for: whether the LATEST event (buy or sell,
  whichever is more recent) was a buy-side arrow -- see
  is_warren_signal_active below.
- BB+RSI's history (TechnicalEntrySignalEvent) needed a separate one-time
  backfill script for pre-existing history, since its nightly job never
  looks further back than "today". Warren's nightly job already replays
  everything every night, so simply running it once IS the backfill --
  no separate script exists for this signal.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, or_, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from analysis.entry_signal.resample import build_2h_session_candles
from analysis.warren_signal.state_machine import UP_KINDS, replay
from analysis.warren_signal.types import WarrenReplayResult
from core.db import engine
from core.models import TechnicalEntrySignal, WarrenSignalEvent
from core.schemas import TechnicalEntrySignalOut
from core.tickers import normalize_ticker
from pandas import DataFrame

DEFAULT_SIGNAL_TYPE = "warren"
DEFAULT_TIMEFRAME = "2h"

# How long a row can go un-recomputed (e.g. its ticker dropped off every
# W1-W5 watchlist) before sweep_stale_warren_signals clears it -- same
# value/reasoning as entry_signal_data.py::STALE_AFTER_DAYS.
STALE_AFTER_DAYS = 7

# How long a WarrenSignalEvent row is kept before prune_warren_signal_events
# deletes it -- same 730-day Yahoo 2h-interval history limit
# entry_signal_data.py::EVENT_RETENTION_DAYS is based on.
EVENT_RETENTION_DAYS = 730


def is_warren_signal_active(signal_kind: str | None) -> bool:
    """The literal `inTrade` mapping: active means the latest recorded
    event (of either direction) was a buy-side arrow (Blue/Yellow/Gray Up)
    -- i.e. no sell arrow has fired since. Unlike BB+RSI's time-windowed
    is_entry_signal_active, this has no notion of "expiring" on its own; it
    only changes when a newer event of either direction is recorded."""
    return signal_kind in UP_KINDS


def _upsert(ticker: str, signal_type: str, timeframe: str, result: WarrenReplayResult, source: str, computed_at: datetime) -> None:
    """Unlike entry_signal_data.py::_upsert, there is no should_advance
    guard here -- `result` is always the true, complete current state (a
    full replay from scratch), so every field is always written, not just
    conditionally advanced. See module docstring."""
    with Session(engine) as session:
        last_event = result.events[-1] if result.events else None

        # Every field is explicitly set every run (None when there's no
        # last_event) -- unlike entry_signal_data.py's conditional
        # should_advance guard, there is nothing here to protect: a full
        # replay's result already IS the complete truth, so a genuinely
        # quiet ticker (no events at all, ever) must read back as quiet,
        # not silently retain a stale value the SET clause happened not to
        # mention.
        fields: dict = {
            "source": source,
            "as_of": result.as_of,
            "computed_at": computed_at,
            "stop_price": result.live_stop_price,
            "gray_suppressed": result.gray_suppressed,
            "stop_count": result.stop_count,
            "fired_at": last_event.fired_at if last_event else None,
            "rsi": last_event.rsi if last_event else None,
            "close": last_event.close if last_event else None,
            "signal_kind": last_event.kind if last_event else None,
        }

        stmt = sqlite_insert(TechnicalEntrySignal).values(ticker=ticker, signal_type=signal_type, timeframe=timeframe, **fields)
        stmt = stmt.on_conflict_do_update(index_elements=["ticker", "signal_type", "timeframe"], set_=fields)
        session.execute(stmt)

        # Every event from this full replay gets (re-)inserted --
        # on_conflict_do_nothing makes re-inserting an already-recorded
        # event (the overwhelming majority, every night) a cheap no-op
        # rather than an error or a duplicate row.
        for event in result.events:
            event_stmt = sqlite_insert(WarrenSignalEvent).values(
                ticker=ticker,
                timeframe=timeframe,
                signal_kind=event.kind,
                fired_at=event.fired_at,
                stop_price=event.stop_price,
                created_at=computed_at,
            )
            event_stmt = event_stmt.on_conflict_do_nothing(index_elements=["ticker", "timeframe", "fired_at", "signal_kind"])
            session.execute(event_stmt)

        session.commit()


def _row_to_out(row: TechnicalEntrySignal) -> TechnicalEntrySignalOut:
    return TechnicalEntrySignalOut(
        ticker=row.ticker,
        signal_type=row.signal_type,
        timeframe=row.timeframe,
        active=is_warren_signal_active(row.signal_kind),
        fired_at=row.fired_at,
        pct_b=None,  # not applicable to Warren
        rsi=row.rsi,
        close=row.close,
        stop_price=row.stop_price,
        signal_kind=row.signal_kind,
        gray_suppressed=row.gray_suppressed,
        stop_count=row.stop_count,
        source=row.source,
        as_of=row.as_of,
        computed_at=row.computed_at,
    )


def compute_and_store_warren_signal(
    ticker: str,
    ohlcv: DataFrame,
    source: str,
    signal_type: str = DEFAULT_SIGNAL_TYPE,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> TechnicalEntrySignalOut:
    """Runs the pure state-machine replay against already-fetched raw
    intraday OHLCV bars (the full available history -- see
    pipeline/nightly_warren_signal_calculation.py's own 2-year fetch) and
    upserts. Resampling into 2h session candles happens here (reusing
    analysis/entry_signal/resample.py::build_2h_session_candles directly),
    one level above where BB+RSI's own engine does the equivalent call --
    replay() itself stays a pure function of already-built candles, kept
    unit-testable without needing real intraday bars (see
    analysis/warren_signal/test_state_machine.py).

    Raises ValueError (propagated from replay()) if no 2h session candles
    could be built at all -- callers (the nightly job's per-ticker loop)
    treat this like any other per-ticker failure, same convention as
    entry_signal_data.py::compute_and_store_entry_signal."""
    ticker = normalize_ticker(ticker)
    candles = build_2h_session_candles(ohlcv)
    result = replay(candles)
    computed_at = datetime.now()
    _upsert(ticker, signal_type, timeframe, result, source, computed_at)

    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, (ticker, signal_type, timeframe))
    return _row_to_out(row)


async def get_warren_signal_data(
    ticker: str, signal_type: str = DEFAULT_SIGNAL_TYPE, timeframe: str = DEFAULT_TIMEFRAME
) -> TechnicalEntrySignalOut | None:
    """Cache-only read -- never triggers a live fetch. Returns None if this
    ticker/signal_type/timeframe has never been computed (not a member of
    any W1-W5 watchlist, or the nightly job hasn't reached it yet)."""
    ticker = normalize_ticker(ticker)
    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, (ticker, signal_type, timeframe))
    return _row_to_out(row) if row else None


def sweep_stale_warren_signals(now: datetime | None = None) -> int:
    """Clears (never deletes) any signal_type="warren" row whose
    computed_at is more than STALE_AFTER_DAYS old -- same shape/reasoning
    as entry_signal_data.py::sweep_stale_entry_signals, extended to the
    three Warren-only columns. source/as_of/computed_at are left untouched
    as the "last known" breadcrumb. Returns the number of rows cleared."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=STALE_AFTER_DAYS)
    with Session(engine) as session:
        stmt = (
            update(TechnicalEntrySignal)
            .where(
                TechnicalEntrySignal.signal_type == DEFAULT_SIGNAL_TYPE,
                TechnicalEntrySignal.computed_at < cutoff,
                or_(
                    TechnicalEntrySignal.fired_at.is_not(None),
                    TechnicalEntrySignal.rsi.is_not(None),
                    TechnicalEntrySignal.close.is_not(None),
                    TechnicalEntrySignal.stop_price.is_not(None),
                    TechnicalEntrySignal.signal_kind.is_not(None),
                    TechnicalEntrySignal.gray_suppressed.is_not(None),
                    TechnicalEntrySignal.stop_count.is_not(None),
                ),
            )
            .values(fired_at=None, rsi=None, close=None, stop_price=None, signal_kind=None, gray_suppressed=None, stop_count=None)
        )
        result = session.execute(stmt)
        session.commit()
        return result.rowcount


def prune_warren_signal_events(retention_days: int = EVENT_RETENTION_DAYS, now: datetime | None = None) -> int:
    """Deletes (genuinely -- not cleared) WarrenSignalEvent rows older than
    retention_days. Same reasoning as entry_signal_data.py::
    prune_entry_signal_events: this is a real accumulating time series with
    no "last known" breadcrumb value worth preserving past every Chart-tab
    range that could display it. Returns the number of rows deleted."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=retention_days)
    with Session(engine) as session:
        stmt = delete(WarrenSignalEvent).where(WarrenSignalEvent.fired_at < cutoff)
        result = session.execute(stmt)
        session.commit()
        return result.rowcount
