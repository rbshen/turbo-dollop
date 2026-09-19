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
- Because it replays from a blank state every night, events near the START of
  the replay window are unreliable (BB+RSI, being stateless per bar, has no
  equivalent exposure). Only events past EVENT_WRITE_WARMUP_DAYS from the
  first replayed candle are persisted to WarrenSignalEvent; the latest-state
  row is unaffected. See that constant for the measurements behind the value.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

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
# deletes it (4 years; raised from 730 on 2026-09-19). This is only a ceiling
# on STORED history, not a fetch limit: Yahoo serves ~730 days of 60m bars, so
# nothing older than that can be recomputed or backfilled -- retention above 730
# just stops deleting events once they age past the old cutoff, and depth grows
# by a day per day until it reaches this value. Safe to raise only because of
# EVENT_WRITE_WARMUP_DAYS below: before that buffer, the unreliable leading-edge
# events every night wrote would have been frozen here permanently instead of
# aging out. Keep this comfortably above EVENT_WRITE_WARMUP_DAYS (test-pinned).
EVENT_RETENTION_DAYS = 1460

# Write-side warm-up buffer. Every nightly run replays the whole fetched
# window, but the state machine starts blank at the window's first candle, so
# events computed near that left edge are unreliable -- RSI/ADX seeds settle
# in ~2 weeks, but the gray-suppression memory (`yellow_armed`/`stop_count`,
# mostly showing up as gray_up <-> yellow_up mislabels) takes months. Events
# are written insert-if-absent and never revised, and the window's start slides
# forward a day every night, so every night used to persist a fresh crop of
# leading-edge variants that no earlier (longer-context) night had produced.
#
# Measured 2026-09-19 (105 tickers, replay from a later start vs. a full-
# context replay; error = missed + phantom events as % of correct ones), by
# days from the replay's first candle: 0-7d ~240%, 8-14d ~134%, 15-30d ~51%,
# 31-60d ~15-27%, 61-120d ~7-16%, 121-180d ~4-8%, 181-300d ~2-4%, 300d+ ~0%.
# Events that clear a 180d buffer sit at ~2-4% error (181-300d) falling to ~0%,
# ~1.3-1.6% averaged over everything written -- the point where the curve
# flattens; a longer buffer buys little and costs stored history, a shorter
# one (e.g. 90d, ~7-16% error) keeps a visible error rate. Tunable here; see
# compute_and_store_warren_signal for how it is applied. Only WRITES are gated:
# the replay still runs over the full window (that is what builds the state),
# and the latest-state row is still derived from the full replay's tail,
# untouched by this (its events sit at the right edge, with the whole window as
# context).
#
# Independent of EVENT_RETENTION_DAYS: this buffer is what made raising that
# (730 -> 1460) safe, but neither value is derived from the other.
EVENT_WRITE_WARMUP_DAYS = 180


def is_warren_signal_active(signal_kind: str | None) -> bool:
    """The literal `inTrade` mapping: active means the latest recorded
    event (of either direction) was a buy-side arrow (Blue/Yellow/Gray Up)
    -- i.e. no sell arrow has fired since. Unlike BB+RSI's time-windowed
    is_entry_signal_active, this has no notion of "expiring" on its own; it
    only changes when a newer event of either direction is recorded."""
    return signal_kind in UP_KINDS


def warren_active_up_kind(signal_kind: str | None) -> str | None:
    """The specific Up-kind (blue_up/yellow_up/gray_up) the ticker's
    current state is actively in, or None if the latest recorded event
    (if any) was a sell arrow, or nothing has ever fired. All three
    Up-kinds are symmetric here -- gray_up is emitted as a fully-formed,
    distinct WarrenSignalEvent at exactly the same point in the replay
    loop as blue_up/yellow_up (state_machine.py::_replay_from_signals'
    `gray_up = is_scan3 and yellow_is_gray`), so "the latest recorded
    event is specifically gray_up, with no sell since" is exactly as
    well-defined a notion of "currently active" as it already is for
    blue_up/yellow_up via is_warren_signal_active above -- no separate
    query or additional state is needed. Powers the Screener's per-kind
    multi-select filter (TickerScore.warren_active_signal_kind), which
    replaced an earlier Blue+Yellow-only combined checkbox that excluded
    Gray Up as a selectable option entirely."""
    return signal_kind if signal_kind in UP_KINDS else None


def last_buy_signal_fired_at(session: Session, ticker: str) -> datetime | None:
    """Max fired_at across every WarrenSignalEvent buy-side arrow (Blue/
    Yellow/Gray Up, i.e. UP_KINDS) ever recorded for this ticker.
    Deliberately NOT read off TechnicalEntrySignal.fired_at -- that
    snapshot holds the latest event of EITHER direction (buy or sell), so
    once a ticker's most recent event is a sell arrow, that field no
    longer answers "when did a buy last fire" at all; it would silently
    read as the sell's own timestamp instead. Used to denormalize
    TickerScore.warren_last_buy_fired_at in ticker_score.py."""
    return session.exec(
        select(func.max(WarrenSignalEvent.fired_at)).where(
            WarrenSignalEvent.ticker == ticker,
            WarrenSignalEvent.signal_kind.in_(UP_KINDS),
        )
    ).one()


def _upsert(
    ticker: str,
    signal_type: str,
    timeframe: str,
    result: WarrenReplayResult,
    source: str,
    computed_at: datetime,
    write_events_from: datetime,
) -> None:
    """Unlike entry_signal_data.py::_upsert, there is no should_advance
    guard here -- `result` is always the true, complete current state (a
    full replay from scratch), so every field is always written, not just
    conditionally advanced. See module docstring.

    `write_events_from` gates only the WarrenSignalEvent inserts below (see
    EVENT_WRITE_WARMUP_DAYS): the latest-state row is deliberately derived
    from the full, unfiltered `result`."""
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

        # Every event from this full replay that clears the warm-up buffer
        # gets (re-)inserted -- on_conflict_do_nothing makes re-inserting an
        # already-recorded event (the overwhelming majority, every night) a
        # cheap no-op rather than an error or a duplicate row. Anything
        # earlier than write_events_from is dropped, whatever the state
        # machine produced there.
        for event in result.events:
            if event.fired_at < write_events_from:
                continue
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

    Only events fired at or after (first replayed candle + EVENT_WRITE_WARMUP_
    DAYS) are persisted to WarrenSignalEvent -- see that constant for why. The
    first replayed candle is the start of the data actually handed in, so a
    ticker with less history than the fetch window (a recent IPO) has its
    buffer measured from its own first candle, same as any other.

    Raises ValueError (propagated from replay()) if no 2h session candles
    could be built at all -- callers (the nightly job's per-ticker loop)
    treat this like any other per-ticker failure, same convention as
    entry_signal_data.py::compute_and_store_entry_signal."""
    ticker = normalize_ticker(ticker)
    candles = build_2h_session_candles(ohlcv)
    result = replay(candles)
    computed_at = datetime.now()
    replay_start = candles.index[0].to_pydatetime().replace(tzinfo=None)
    write_events_from = replay_start + timedelta(days=EVENT_WRITE_WARMUP_DAYS)
    _upsert(ticker, signal_type, timeframe, result, source, computed_at, write_events_from)

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
