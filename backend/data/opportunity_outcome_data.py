"""Orchestration of the opportunity outcome updater: read the listed snapshot rows of the stored weekly runs, price them against the
cached daily bars with the pure engine (scoring/opportunity_outcomes.py), and upsert OpportunityOutcome rows. Spec:
docs/specs/opportunities.md, "Outcome tracking". Entry point: pipeline/opportunity_outcome_update.py (manual; NOT a registered cron job).

STORED DATA ONLY: no FMP call (the bars cache is read, never fetched). Writes only OpportunityOutcome and the OpportunityOutcomeRun log.
Memory stays flat: SPY and the (at most 11) sector ETFs are loaded once, every other ticker's bars in chunks of CHUNK_SIZE.

Rules of the update:
- Idempotent. Only open rows are recomputed: `pending`, and a `censored` row still inside its grace period (CENSOR_REVIVE_DAYS from
  `first_censored_at`, so a price-data hole is not frozen as if it were a delisting). A `complete` row, and a censored row past its
  grace, are frozen and never touched. A row is written only when its values changed. A stop already recorded on a pending row is kept even if the bars that showed it vanish.
- A censored row whose missing bars have appeared goes back to `pending` / `complete` with `censor_reason` and `first_censored_at`
  cleared. One that is still censored keeps its original `first_censored_at` (the clock never restarts).
- Every listed snapshot row has four outcome rows (5/10/20/60) after the first update, seeded `pending` when it cannot be priced yet.
- A ticker whose bars fail to read or price leaves its rows as they were (seeded `pending` if new) and does not stop the others.
- Only COMPLETED bars are used: a bar after the last completed session, or a last bar written before its own session's close (the bars
  cache's provisional-bar test), is dropped, SPY's included.
- A normal run is a no-op unless SPY has a bar newer than the one the last run saw (or a listed row still has no outcome rows). A run
  targeted with run_id / as_of skips that check.

`engine` is a module-level reference so tests can monkeypatch it (the per-module convention)."""

import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlmodel import Session, select

from clients.shared_bars_cache import (
    _cache_span,
    _eastern_today,
    _most_recent_completed_trading_date,
    _provisional_last_bar_tickers,
    read_cached_daily_bars_batch,
)
from core.db import engine
from core.models import OpportunityOutcome, OpportunityOutcomeRun, OpportunityRun, OpportunitySnapshotRow, TickerScore
from data.market_breadth_data import SECTOR_TO_ETF
from data.tracked_universe import load_etf_universe, load_tracked_universe
from scoring import opportunity_outcomes as eng

logger = logging.getLogger(__name__)

KIND_WEEKLY = "weekly"
SPY = "SPY"
CHUNK_SIZE = 60  # tickers of bars held in memory at a time (the server has ~1 GB)
LOOKBACK_SLACK_DAYS = 10  # calendar days read before the earliest as-of date, so its neighbours are in the frame
PROVENANCE_LIVE = "live"

# The OpportunityOutcome fields the engine decides (everything else on the row is identity or bookkeeping).
_VALUE_FIELDS = (
    "status", "censor_reason", "entry_date", "entry_open", "exit_date", "exit_close", "forward_return", "spy_return", "excess_vs_spy",
    "sector_etf", "sector_return", "excess_vs_sector", "worst_move", "best_move", "max_drawdown", "stop_hit", "stop_date",
    "stop_fill_return", "entry_gap_pct", "entry_gap_flag",
)
_STOP_FIELDS = ("stop_hit", "stop_date", "stop_fill_return")


def _naive_utc(moment: datetime) -> datetime:
    """The stored datetimes are naive (the server clock is UTC); compare like with like."""
    return moment.astimezone(timezone.utc).replace(tzinfo=None) if moment.tzinfo is not None else moment


def is_final(row: OpportunityOutcome, now: datetime) -> bool:
    """True when the updater must leave the row alone: complete, or censored and past its grace period. A censored row with no
    `first_censored_at` (written before the column existed) is still open; the next evaluation stamps it."""
    if row.status == eng.COMPLETE:
        return True
    if row.status != eng.CENSORED or row.first_censored_at is None:
        return False
    return _naive_utc(now) >= row.first_censored_at + timedelta(days=eng.CENSOR_REVIVE_DAYS)


@dataclass
class UpdateResult:
    status: str  # "noop" | "success" | "partial" | "dry_run"
    spy_last_bar_date: date | None = None
    runs: int = 0
    listed_rows: int = 0
    seeded: int = 0  # outcome rows created
    updated: int = 0  # pending rows rewritten with new values
    frozen_untouched: int = 0  # complete/censored rows left alone
    failed: dict[str, str] = field(default_factory=dict)  # ticker -> why
    by_status: dict[str, dict[int, int]] = field(default_factory=dict)  # status -> horizon -> rows (state after the run)
    stops: int = 0  # rows with a stop recorded (state after the run)
    reason: str = ""  # why a no-op

    def message(self) -> str:
        if self.status == "noop":
            return f"no-op: {self.reason}"
        counts = {s: sum(h.values()) for s, h in self.by_status.items()}
        tail = f", {len(self.failed)} ticker(s) failed" if self.failed else ""
        return (
            f"{self.status}: {self.runs} run(s), {self.listed_rows} listed rows; complete {counts.get(eng.COMPLETE, 0)}, "
            f"pending {counts.get(eng.PENDING, 0)}, censored {counts.get(eng.CENSORED, 0)}, stops {self.stops}; "
            f"{self.seeded} created, {self.updated} updated{tail} (SPY bar {self.spy_last_bar_date})"
        )


# --- bars -------------------------------------------------------------------------------------------------------------------


def _completed_only(frames: dict[str, pd.DataFrame], now: datetime) -> dict[str, pd.DataFrame]:
    """Drops what is not a final bar, the same rule as clients/shared_bars_cache.py::read_cached_completed_daily_bars: bars after the
    last completed session, and a last bar written before its own session's close."""
    if not frames:
        return frames
    completed = pd.Timestamp(_most_recent_completed_trading_date(now))
    tickers = list(frames)
    with Session(engine) as session:
        span = _cache_span(session, tickers, "1d")
        provisional = _provisional_last_bar_tickers(session, tickers, span, now)
    out = {}
    for ticker, frame in frames.items():
        live_dropped = bool((frame.index.normalize() > completed).any())
        frame = frame[frame.index.normalize() <= completed]
        if ticker in provisional and not live_dropped and not frame.empty:
            frame = frame.iloc[:-1]
        out[ticker] = frame
    return out


def _read_bars(tickers: list[str], lookback_days: int, now: datetime) -> dict[str, pd.DataFrame]:
    return _completed_only(read_cached_daily_bars_batch(tickers, lookback_days, now), now)


# --- the update -------------------------------------------------------------------------------------------------------------


def _target_runs(session: Session, run_id: int | None, as_of: date | None) -> list[OpportunityRun]:
    stmt = select(OpportunityRun).where(OpportunityRun.kind == KIND_WEEKLY).order_by(OpportunityRun.as_of_date)
    if run_id is not None:
        stmt = stmt.where(OpportunityRun.id == run_id)
    if as_of is not None:
        stmt = stmt.where(OpportunityRun.as_of_date == as_of)
    return list(session.exec(stmt).all())


def _last_seen_spy_bar(session: Session) -> date | None:
    """The SPY bar date the most recent finished run saw (a no-op run carries it forward; a failed or partial run stores none)."""
    row = session.exec(
        select(OpportunityOutcomeRun)
        .where(OpportunityOutcomeRun.spy_last_bar_date.is_not(None))
        .order_by(OpportunityOutcomeRun.id.desc())
        .limit(1)
    ).first()
    return row.spy_last_bar_date if row is not None else None


def _values(outcome: eng.HorizonOutcome) -> dict:
    d = outcome.as_dict()
    return {k: d[k] for k in _VALUE_FIELDS}


def _same(row: OpportunityOutcome, values: dict) -> bool:
    return all(getattr(row, k) == v for k, v in values.items())


def update_outcomes(
    run_id: int | None = None, as_of: date | None = None, dry_run: bool = False, now: datetime | None = None
) -> UpdateResult:
    """Prices every listed snapshot row of the targeted weekly runs (default: all) and upserts its outcome rows. `dry_run` computes
    the same state and reports it, writing nothing (no outcome row, no log row). Returns what was done."""
    now = now or datetime.now(timezone.utc)
    targeted = run_id is not None or as_of is not None
    result = UpdateResult(status="dry_run" if dry_run else "success")

    with Session(engine) as session:
        runs = _target_runs(session, run_id, as_of)
        last_seen = None if targeted else _last_seen_spy_bar(session)
        listed = {
            run.id: session.exec(select(OpportunitySnapshotRow).where(OpportunitySnapshotRow.run_id == run.id)).all() for run in runs
        }
        existing = {
            (o.run_id, o.ticker, o.horizon): o
            for o in session.exec(select(OpportunityOutcome).where(OpportunityOutcome.run_id.in_([r.id for r in runs]))).all()
        } if runs else {}
        # detach what we keep reading after the session closes
        session.expunge_all()
    result.runs = len(runs)
    result.listed_rows = sum(len(v) for v in listed.values())

    def has_work(run: OpportunityRun, rows: list[OpportunitySnapshotRow]) -> bool:
        return any(
            (run.id, r.ticker, h) not in existing or not is_final(existing[(run.id, r.ticker, h)], now)
            for r in rows
            for h in eng.HORIZONS
        )

    work = [(run, listed[run.id]) for run in runs if listed[run.id] and has_work(run, listed[run.id])]
    new_rows_missing = any((run.id, r.ticker, h) not in existing for run, rows in work for r in rows for h in eng.HORIZONS)

    # state of every targeted outcome row after this run, for the report: (run, ticker, horizon) -> (status, stop_hit)
    state = {k: (o.status, o.stop_hit) for k, o in existing.items()}
    result.frozen_untouched = sum(1 for o in existing.values() if is_final(o, now))

    if not work:
        result.status, result.reason = "noop", "every listed row already has final outcomes" if runs else "no opportunity run to track"
        _fill_counts(result, state)
        return result

    earliest = min(run.as_of_date for run, _ in work)
    lookback = (_eastern_today(now) - earliest).days + LOOKBACK_SLACK_DAYS
    spy_bars = _read_bars([SPY], lookback, now).get(SPY)
    if spy_bars is None or spy_bars.empty:
        raise RuntimeError("no completed SPY bars in the cache: cannot build the session calendar")
    result.spy_last_bar_date = spy_bars.index.max().date()
    if not targeted and not new_rows_missing and last_seen is not None and result.spy_last_bar_date <= last_seen:
        result.status, result.reason = "noop", f"SPY has no bar newer than {last_seen} (the last run's)"
        _fill_counts(result, state)
        return result

    # who is delisted / still tracked decides the reason on a censored row; only needed when something is pending
    with Session(engine) as session:
        delisted = set(session.exec(select(TickerScore.ticker).where(TickerScore.delisted_at.is_not(None))).all())
        tracked = set(load_tracked_universe(session)) | set(load_etf_universe(session))

    sector_etfs = sorted({SECTOR_TO_ETF[r.sector] for _, rows in work for r in rows if r.sector in SECTOR_TO_ETF})
    sector_bars = _read_bars(sector_etfs, lookback, now) if sector_etfs else {}

    tickers = sorted({r.ticker for _, rows in work for r in rows})
    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i : i + CHUNK_SIZE]
        try:
            frames = _read_bars(chunk, lookback, now)
        except Exception as exc:  # noqa: BLE001 -- a bad chunk read leaves its rows as they were; the other chunks still run
            logger.exception("Outcome update: reading the bars of %s failed.", chunk)
            frames = {}
            for t in chunk:
                result.failed[t] = f"bars read failed: {exc}"
        with Session(engine, expire_on_commit=False) as session:
            for run, rows in work:
                for snap in rows:
                    if snap.ticker not in chunk:
                        continue
                    _update_one(
                        session, result, state, existing, run, snap, frames.get(snap.ticker), spy_bars, sector_bars, delisted, tracked, now,
                        failed=snap.ticker in result.failed, dry_run=dry_run,
                    )
            if dry_run:
                session.rollback()
            else:
                session.commit()
        del frames

    if result.failed and not dry_run:
        result.status = "partial"
    _fill_counts(result, state)
    return result


def _update_one(
    session: Session,
    result: UpdateResult,
    state: dict,
    existing: dict,
    run: OpportunityRun,
    snap: OpportunitySnapshotRow,
    frame: pd.DataFrame | None,
    spy_bars: pd.DataFrame,
    sector_bars: dict[str, pd.DataFrame],
    delisted: set[str],
    tracked: set[str],
    now: datetime,
    failed: bool,
    dry_run: bool,
) -> None:
    keys = [(run.id, snap.ticker, h) for h in eng.HORIZONS]
    pending_keys = [k for k in keys if k not in existing or not is_final(existing[k], now)]
    if not pending_keys:
        return
    outcomes: dict[int, eng.HorizonOutcome] = {}
    if not failed:
        sector_etf = SECTOR_TO_ETF.get(snap.sector) if snap.sector else None
        try:
            computed = eng.compute_outcomes(
                as_of=run.as_of_date,
                as_of_close=snap.close,
                ticker_bars=frame,
                spy_bars=spy_bars,
                sector_bars=sector_bars.get(sector_etf) if sector_etf else None,
                sector_etf=sector_etf,
                delisted=snap.ticker in delisted,
                in_universe=snap.ticker in tracked,
            )
            outcomes = {o.horizon: o for o in computed}
        except Exception as exc:  # noqa: BLE001 -- one ticker never stops the others
            logger.error("Outcome update: %s (run %s) failed: %s\n%s", snap.ticker, run.id, exc, traceback.format_exc())
            result.failed[snap.ticker] = str(exc)
    for key in pending_keys:
        _, ticker, horizon = key
        row = existing.get(key)
        outcome = outcomes.get(horizon)
        if row is None:
            values = _values(outcome) if outcome is not None else {"status": eng.PENDING}
            new = OpportunityOutcome(
                run_id=run.id, ticker=ticker, horizon=horizon, provenance=PROVENANCE_LIVE, rules_version=run.rules_version, computed_at=now,
                first_censored_at=_naive_utc(now) if values["status"] == eng.CENSORED else None, **values
            )
            if not dry_run:
                session.add(new)
            existing[key] = new
            result.seeded += 1
            state[key] = (new.status, new.stop_hit)
            continue
        if outcome is None:
            continue  # the ticker failed: the pending row stays as it was
        values = _values(outcome)
        if row.stop_hit and not values["stop_hit"]:  # a stop is final: keep it even if the bars that showed it are gone
            for k in _STOP_FIELDS:
                values[k] = getattr(row, k)
        # the grace clock starts when a row is FIRST censored, never restarts, and is cleared on revival
        if values["status"] != eng.CENSORED:
            first_censored = None
        else:
            first_censored = row.first_censored_at if row.status == eng.CENSORED and row.first_censored_at is not None else _naive_utc(now)
        if _same(row, values) and row.first_censored_at == first_censored:
            state[key] = (row.status, row.stop_hit)
            continue
        if not dry_run:
            for k, v in values.items():
                setattr(row, k, v)
            row.first_censored_at = first_censored
            row.computed_at = now
            session.add(row)
        result.updated += 1
        state[key] = (values["status"], values["stop_hit"])


def _fill_counts(result: UpdateResult, state: dict) -> None:
    by_status: dict[str, dict[int, int]] = {}
    for (_run, _ticker, horizon), (status, _stop) in state.items():
        by_status.setdefault(status, {})
        by_status[status][horizon] = by_status[status].get(horizon, 0) + 1
    result.by_status = {s: dict(sorted(h.items())) for s, h in by_status.items()}
    result.stops = sum(1 for _status, stop in state.values() if stop)


# --- the heartbeat-style log -----------------------------------------------------------------------------------------------------


def start_log(now: datetime | None = None) -> int | None:
    """Opens an OpportunityOutcomeRun row ("running"); None if the log write itself fails (it must never stop the update)."""
    try:
        with Session(engine) as session:
            row = OpportunityOutcomeRun(started_at=now or datetime.now(), status="running")
            session.add(row)
            session.commit()
            return row.id
    except Exception:  # noqa: BLE001
        logger.warning("Outcome update: could not write the start of the log row.", exc_info=True)
        return None


def finish_log(log_id: int | None, status: str, message: str, spy_last_bar_date: date | None = None, summary: dict | None = None) -> None:
    if log_id is None:
        return
    try:
        with Session(engine) as session:
            row = session.get(OpportunityOutcomeRun, log_id)
            if row is None:
                return
            row.finished_at, row.status, row.message = datetime.now(), status, message[:1000]
            row.spy_last_bar_date = spy_last_bar_date
            row.summary_json = json.dumps(summary or {})
            session.add(row)
            session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("Outcome update: could not write the end of the log row.", exc_info=True)


def summary_of(result: UpdateResult) -> dict:
    return {
        "runs": result.runs,
        "listed_rows": result.listed_rows,
        "by_status": {s: {str(h): n for h, n in hs.items()} for s, hs in result.by_status.items()},
        "stops": result.stops,
        "seeded": result.seeded,
        "updated": result.updated,
        "failed": result.failed,
    }
