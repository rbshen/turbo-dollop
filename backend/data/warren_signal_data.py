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
- Since 2026-10-18 the event log at or after that write gate is RECONCILED with the replay every night (reconcile_events below): a stored
  event the replay no longer produces is deleted, a replay arrow with no stored event is inserted, a matching event is left alone.
  Before, events were insert-only, so an arrow that moved (a provisional newest session corrected the next night, a bar-source change)
  left its old row behind for good. Events before the gate are never touched.
"""

import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from analysis.entry_signal.resample import build_2h_session_candles
from analysis.warren_signal.profiles import QQQ, SPY, TECL, TQQQ
from analysis.warren_signal.state_machine import UP_KINDS, replay
from analysis.warren_signal.types import ANY_TICKER, WarrenProfile, WarrenReplayResult
from analysis.warren_signal.volume_guard import guard_for_profile
from clients.shared_bars_cache import read_cached_completed_daily_bars
from core.db import engine
from core.models import EtfScreenerRow, TechnicalEntrySignal, TickerScore, WarrenSignalEvent
from core.schemas import TechnicalEntrySignalOut
from core.tickers import normalize_ticker
from pandas import DataFrame, Series

logger = logging.getLogger(__name__)

DEFAULT_SIGNAL_TYPE = "warren"
DEFAULT_TIMEFRAME = "2h"

# Tickers with their own Blue Up definition (analysis/warren_signal/profiles.py, from the ThinkScripts); every
# other ticker uses ANY_TICKER. The ONE place a symbol selects a profile: the nightly job
# (compute_and_store_warren_signal) and the Chart tab's on-demand 2H range both go through profile_for, so the
# stored signal and the chart can never use different definitions. The engine itself never sees a symbol.
TICKER_PROFILES: dict[str, WarrenProfile] = {"SPY": SPY, "QQQ": QQQ, "TQQQ": TQQQ, "TECL": TECL}


def profile_for(ticker: str) -> WarrenProfile:
    """The Blue Up profile for `ticker` (normalized like every other lookup here): its own if it has one in
    TICKER_PROFILES, else ANY_TICKER."""
    return TICKER_PROFILES.get(normalize_ticker(ticker), ANY_TICKER)


# Calendar days of cached daily bars read for the volume guard: comfortably wider than the 730-day replay window.
DAILY_VOLUME_LOOKBACK_DAYS = 740


def volume_guard_applies(ticker: str) -> bool:
    """True when the ticker's profile has volume rules (SPY/QQQ/TQQQ/TECL) -- the only tickers the volume guard
    touches, and so the only ones for which a caller needs to look up daily volume at all."""
    return profile_for(ticker).rules is not None


def read_cached_daily_volume(ticker: str, now: datetime | None = None) -> Series:
    """The ticker's EOD volume per date from the cached 1d bars (SharedBarsCache), through the most recent COMPLETED
    session only: a pure read -- no fetch, no write -- that already drops a live in-progress bar and a last bar
    written before its own session's close, so the current session reads as "no EOD volume" and the guard fails
    closed on it. Empty when nothing is cached. (The cached 1d volume is FMP historical-price-eod/full's own
    volume: checked equal, 1,255 of 1,255 rows each for SPY, QQQ and TECL, 2026-10-04.)"""
    frame = read_cached_completed_daily_bars(normalize_ticker(ticker), DAILY_VOLUME_LOOKBACK_DAYS, reference=now)
    return frame["volume"] if "volume" in frame.columns and not frame.empty else Series(dtype=float)


def signal_candles(ticker: str, candles: DataFrame, daily_volume: Series | None) -> DataFrame:
    """The candles the Blue Up replay should read for `ticker`: for a profiled ticker, `candles` with the volume of
    every day failing the daily-volume check set to NaN (analysis/warren_signal/volume_guard.py); for any other
    ticker, `candles` itself, untouched. THE shared step between the candle build and the replay -- the nightly
    store and the Chart tab's 2H range both call it, so the stored signal and the chart cannot diverge. It feeds
    the replay only: the volume a chart displays comes from the original candles."""
    return guard_for_profile(candles, daily_volume, profile_for(ticker))

# How long a row can go un-recomputed (e.g. its ticker dropped off every
# monitored watchlist) before sweep_stale_warren_signals clears it -- same
# value/reasoning as entry_signal_data.py::STALE_AFTER_DAYS.
STALE_AFTER_DAYS = 7

# How long a WarrenSignalEvent row is kept before prune_warren_signal_events
# deletes it (4 years; raised from 730 on 2026-09-19). This is only a ceiling
# on STORED history, not a fetch limit: the app fetches 730 days of 60m bars (our own
# choice, carried over from the Yahoo era; FMP's published Starter limit is 5 years), so
# nothing older than that is recomputed or backfilled -- retention above 730
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


# A reconcile that would delete at least this many stored events AND more than this share of the ticker's stored window is not applied (the
# bars or the replay are suspect, not the log): logged and skipped, nothing written for that ticker.
RECONCILE_MAX_DELETE_FRACTION = 0.5
RECONCILE_MIN_DELETES_TO_GUARD = 5


@dataclass(frozen=True)
class EventReconcile:
    """What one ticker's reconcile did (or, in a dry run, would do). `added` / `deleted` are (kind, fired_at) keys; `unchanged` counts the
    matching events left untouched. `skipped` is a reason when the reconcile was refused (nothing is deleted or inserted then)."""

    ticker: str
    added: tuple = ()
    deleted: tuple = ()
    unchanged: int = 0
    skipped: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.added or self.deleted)


def plan_event_reconcile(
    ticker: str,
    stored: Collection[tuple[str, datetime]],
    replay_events: Sequence,
    write_events_from: datetime,
    as_of: datetime,
) -> EventReconcile:
    """The pure plan: `stored` = the keys of the ticker's stored events at or after `write_events_from`; `replay_events` = the engine's
    events for the same bars. Deletes the stored keys the replay does not produce (only up to `as_of`, the last replayed candle, so a
    short or stale bar series can never delete an event it did not cover); adds the replay keys that are not stored. Refuses (skipped, no
    changes) when the replay yields nothing at all for a window that holds events, or would delete most of the window."""
    wanted = {(e.kind, e.fired_at) for e in replay_events if e.fired_at >= write_events_from}
    have = set(stored)
    deleted = sorted((k for k in have - wanted if k[1] <= as_of), key=lambda k: (k[1], k[0]))
    added = sorted(wanted - have, key=lambda k: (k[1], k[0]))
    unchanged = len(have & wanted)
    if have and not wanted:
        return EventReconcile(ticker, unchanged=len(have), skipped=f"the replay yields no event at or after {write_events_from:%Y-%m-%d} but {len(have)} are stored")
    if len(deleted) >= RECONCILE_MIN_DELETES_TO_GUARD and len(deleted) > RECONCILE_MAX_DELETE_FRACTION * len(have):
        return EventReconcile(ticker, unchanged=len(have & wanted), skipped=f"would delete {len(deleted)} of {len(have)} stored events")
    return EventReconcile(ticker, tuple(added), tuple(deleted), unchanged)


def _stored_window_keys(session: Session, ticker: str, timeframe: str, write_events_from: datetime) -> set[tuple[str, datetime]]:
    rows = session.exec(
        select(WarrenSignalEvent.signal_kind, WarrenSignalEvent.fired_at).where(
            WarrenSignalEvent.ticker == ticker, WarrenSignalEvent.timeframe == timeframe, WarrenSignalEvent.fired_at >= write_events_from
        )
    ).all()
    return {(k, f) for k, f in rows}


def reconcile_events(
    session: Session,
    ticker: str,
    timeframe: str,
    result: WarrenReplayResult,
    write_events_from: datetime,
    computed_at: datetime,
    dry_run: bool = False,
) -> EventReconcile:
    """Bring the ticker's stored WarrenSignalEvent rows at or after `write_events_from` in line with `result` (the full replay of the bars
    the caller holds): delete a stored event the replay does not reproduce, insert a replay arrow that has no stored event (created_at =
    `computed_at`), leave a matching event untouched (its created_at and stop_price stay as written). Events before the gate are never read
    or changed. Idempotent: a second call with the same result changes nothing. The caller commits. `dry_run` plans without writing."""
    plan = plan_event_reconcile(ticker, _stored_window_keys(session, ticker, timeframe, write_events_from), result.events, write_events_from, result.as_of)
    if plan.skipped:
        logger.warning("Warren events %s: reconcile skipped - %s", ticker, plan.skipped)
        return plan
    if dry_run or not plan.changed:
        return plan
    for kind, fired_at in plan.deleted:
        session.execute(
            delete(WarrenSignalEvent).where(
                WarrenSignalEvent.ticker == ticker, WarrenSignalEvent.timeframe == timeframe,
                WarrenSignalEvent.signal_kind == kind, WarrenSignalEvent.fired_at == fired_at,
            )
        )
    stops = {(e.kind, e.fired_at): e.stop_price for e in result.events}
    for kind, fired_at in plan.added:
        stmt = sqlite_insert(WarrenSignalEvent).values(
            ticker=ticker, timeframe=timeframe, signal_kind=kind, fired_at=fired_at, stop_price=stops[(kind, fired_at)], created_at=computed_at
        )
        session.execute(stmt.on_conflict_do_nothing(index_elements=["ticker", "timeframe", "fired_at", "signal_kind"]))
    logger.info("Warren events %s: reconciled - %d deleted, %d added, %d unchanged.", ticker, len(plan.deleted), len(plan.added), plan.unchanged)
    return plan


def refresh_warren_score_fields(tickers: Collection[str]) -> int:
    """Rewrite the Warren fields of the denormalized read-models (TickerScore for the Screener, EtfScreenerRow for the ETFs screener) for
    `tickers` straight from the event log and the latest-state row, so they cannot disagree with the log after a reconcile (otherwise they
    wait for the 03:25 score recompute / the ETF job). Only `warren_last_buy_fired_at` reads the event table (last_buy_signal_fired_at);
    `warren_active_signal_kind` reads the latest-state row. A ticker with no such row is skipped. Returns the number of rows changed."""
    changed = 0
    with Session(engine) as session:
        for ticker in tickers:
            last_buy = last_buy_signal_fired_at(session, ticker)
            signal = session.get(TechnicalEntrySignal, (ticker, DEFAULT_SIGNAL_TYPE, DEFAULT_TIMEFRAME))
            kind = warren_active_up_kind(signal.signal_kind) if signal else None
            for model in (TickerScore, EtfScreenerRow):
                row = session.get(model, ticker)
                if row is None or (row.warren_last_buy_fired_at == last_buy and row.warren_active_signal_kind == kind):
                    continue
                row.warren_last_buy_fired_at = last_buy
                row.warren_active_signal_kind = kind
                session.add(row)
                changed += 1
        session.commit()
    return changed


def _upsert(
    ticker: str,
    signal_type: str,
    timeframe: str,
    result: WarrenReplayResult,
    source: str,
    computed_at: datetime,
    write_events_from: datetime,
) -> EventReconcile:
    """Unlike entry_signal_data.py::_upsert, there is no should_advance
    guard here -- `result` is always the true, complete current state (a
    full replay from scratch), so every field is always written, not just
    conditionally advanced. See module docstring.

    `write_events_from` gates only the WarrenSignalEvent log (see
    EVENT_WRITE_WARMUP_DAYS): the latest-state row is deliberately derived
    from the full, unfiltered `result`. Returns the event reconcile that was applied."""
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

        # The event log at or after the warm-up gate is reconciled with this full replay (see reconcile_events): stale rows deleted, missing
        # arrows inserted, matching rows untouched. Anything earlier than write_events_from is never read or changed.
        plan = reconcile_events(session, ticker, timeframe, result, write_events_from, computed_at)

        session.commit()
    return plan


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
    daily_volume: Series | None = None,
) -> TechnicalEntrySignalOut:
    """compute_and_store_warren_signal_with_events, returning only the latest-state row (the shape most callers want)."""
    return compute_and_store_warren_signal_with_events(ticker, ohlcv, source, signal_type, timeframe, daily_volume)[0]


def compute_and_store_warren_signal_with_events(
    ticker: str,
    ohlcv: DataFrame,
    source: str,
    signal_type: str = DEFAULT_SIGNAL_TYPE,
    timeframe: str = DEFAULT_TIMEFRAME,
    daily_volume: Series | None = None,
) -> tuple[TechnicalEntrySignalOut, EventReconcile]:
    """Runs the pure state-machine replay against already-fetched raw
    intraday OHLCV bars (the full available history -- see
    pipeline/nightly_warren_signal_calculation.py's own 2-year fetch) and
    upserts. Resampling into 2h session candles happens here (reusing
    analysis/entry_signal/resample.py::build_2h_session_candles directly),
    one level above where BB+RSI's own engine does the equivalent call --
    replay() itself stays a pure function of already-built candles, kept
    unit-testable without needing real intraday bars (see
    analysis/warren_signal/test_state_machine.py).

    A profiled ticker's replay input has the volume of every day failing the daily-volume check blanked first (see
    signal_candles); `daily_volume` overrides the cached-1d-bars lookup (tests, callers that already hold it).

    Only events fired at or after (first replayed candle + EVENT_WRITE_WARMUP_
    DAYS) are kept in WarrenSignalEvent, and that part of the log is reconciled with this replay (reconcile_events) -- see that constant
    for why the gate exists. Returns the latest-state row and the event reconcile. The
    first replayed candle is the start of the data actually handed in, so a
    ticker with less history than the fetch window (a recent IPO) has its
    buffer measured from its own first candle, same as any other.

    Raises ValueError (propagated from replay()) if no 2h session candles
    could be built at all -- callers (the nightly job's per-ticker loop)
    treat this like any other per-ticker failure, same convention as
    entry_signal_data.py::compute_and_store_entry_signal."""
    ticker, result, write_events_from = _replay_for_events(ticker, ohlcv, daily_volume)  # a guarded ticker with no daily volume given reads the cached 1d bars; none cached -> the guard fails closed
    computed_at = datetime.now()
    plan = _upsert(ticker, signal_type, timeframe, result, source, computed_at, write_events_from)

    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, (ticker, signal_type, timeframe))
    return _row_to_out(row), plan


def _replay_for_events(ticker: str, ohlcv: DataFrame, daily_volume: Series | None) -> tuple[str, WarrenReplayResult, datetime]:
    """The nightly's own candle build, volume guard, replay and write gate for these bars: (normalized ticker, result, write_events_from)."""
    ticker = normalize_ticker(ticker)
    candles = build_2h_session_candles(ohlcv)
    if volume_guard_applies(ticker) and daily_volume is None:
        daily_volume = read_cached_daily_volume(ticker)
    result = replay(signal_candles(ticker, candles, daily_volume), profile_for(ticker))
    return ticker, result, candles.index[0].to_pydatetime().replace(tzinfo=None) + timedelta(days=EVENT_WRITE_WARMUP_DAYS)


def plan_warren_event_reconcile(ticker: str, ohlcv: DataFrame, daily_volume: Series | None = None, timeframe: str = DEFAULT_TIMEFRAME) -> EventReconcile:
    """A pure READ of what the nightly reconcile would do for `ticker` on these bars: the same candle build, replay, write gate and plan
    as compute_and_store_warren_signal, but nothing is written (not even the latest-state row). Raises ValueError (from replay) when no
    candles can be built -- the caller treats that like a failed ticker, and nothing is deleted."""
    ticker, result, write_events_from = _replay_for_events(ticker, ohlcv, daily_volume)
    with Session(engine) as session:
        return reconcile_events(session, ticker, timeframe, result, write_events_from, datetime.now(), dry_run=True)


def apply_warren_event_reconcile(ticker: str, ohlcv: DataFrame, daily_volume: Series | None = None, timeframe: str = DEFAULT_TIMEFRAME) -> EventReconcile:
    """The reconcile alone (what the one-time cleanup runs): the same plan as plan_warren_event_reconcile, applied and committed. It does not
    touch the latest-state row (the nightly does). Raises like plan_warren_event_reconcile, with nothing written."""
    ticker, result, write_events_from = _replay_for_events(ticker, ohlcv, daily_volume)
    with Session(engine) as session:
        plan = reconcile_events(session, ticker, timeframe, result, write_events_from, datetime.now())
        session.commit()
    return plan


async def get_warren_signal_data(
    ticker: str, signal_type: str = DEFAULT_SIGNAL_TYPE, timeframe: str = DEFAULT_TIMEFRAME
) -> TechnicalEntrySignalOut | None:
    """Cache-only read -- never triggers a live fetch. Returns None if this
    ticker/signal_type/timeframe has never been computed (not a member of
    any monitored watchlist, or the nightly job hasn't reached it yet)."""
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
