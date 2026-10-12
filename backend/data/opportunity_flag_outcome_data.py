"""Pricing of the daily flags' outcomes: for every OpportunityDailyFlag, four OpportunityFlagOutcome rows (5 / 10 / 20 / 60 sessions),
computed by the SAME pure engine as the weekly lists' outcomes (scoring/opportunity_outcomes.py::compute_outcomes) with the FLAG SESSION
as the as-of date and the flag's frozen close as the as-of close. So the conventions are identical: entry is the next session's OPEN, exit
the Nth bar's CLOSE, price-only, a 10% intraday stop recorded beside the buy-and-hold return, SPY and sector-ETF benchmarks, a censored row
revivable for 14 days. Spec: docs/specs/opportunities.md, "Daily flags (Phase 2b v1)".

It is called by pipeline/opportunity_outcome_update.py (`update_outcomes_and_flags`) right after the weekly update, in the same invocation:
that updater is the ONLY writer of OpportunityOutcome AND OpportunityFlagOutcome, the daily flag job writes flags only, so the two jobs
cannot collide or double-count. The weekly `update_outcomes` is not changed: this module is a parallel path that shares its helpers
(`is_final`, the completed-bars read, the value fields), and a database with no flags behaves exactly as before (no read, no write, no extra
text in the message).

STORED DATA ONLY: no FMP call. Rules of the update are those of the weekly outcomes: idempotent; only open rows are recomputed (`pending`,
and a `censored` row inside its grace); `complete` rows are frozen; a stop already recorded is kept; a ticker that fails leaves its rows as
they were. A normal run is a no-op unless SPY has a bar newer than the last run's (the caller passes that date) or a flag has no outcome
rows yet; `list_as_of` / `run_id` target the flags of one weekly list and skip that check.

This module reads and writes through `ou.engine` (the weekly outcome module's engine reference, looked up at call time) rather than binding its
own: the two paths run in one updater invocation, so a test that points `data.opportunity_outcome_data.engine` at a throwaway database covers both."""

import logging
import traceback
from datetime import date, datetime, timezone

import pandas as pd
from sqlmodel import Session, select

from clients.shared_bars_cache import _eastern_today
from core.models import OpportunityDailyFlag, OpportunityFlagOutcome, OpportunityRun, TickerScore
from data import opportunity_outcome_data as ou
from data.market_breadth_data import SECTOR_TO_ETF
from scoring import opportunity_outcomes as eng

logger = logging.getLogger(__name__)

SPY = "SPY"
CHUNK_SIZE = ou.CHUNK_SIZE
LOOKBACK_SLACK_DAYS = ou.LOOKBACK_SLACK_DAYS
PROVENANCE_LIVE = ou.PROVENANCE_LIVE


def update_flag_outcomes(
    run_id: int | None = None,
    as_of: date | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
    last_seen_spy: date | None = None,
) -> ou.UpdateResult:
    """Prices every flag (default: all; `as_of` / `run_id` pick the flags of one weekly list) and upserts its outcome rows. `last_seen_spy`
    is the SPY bar date the previous updater run saw, for the no-op test. `dry_run` computes the same state and writes nothing."""
    now = now or ou.datetime.now(timezone.utc)  # ou.datetime: the weekly module's clock reference, so one patch covers both paths
    targeted = run_id is not None or as_of is not None
    result = ou.UpdateResult(status="dry_run" if dry_run else "success")

    with Session(ou.engine) as session:
        list_date = as_of
        if run_id is not None:
            run = session.get(OpportunityRun, run_id)
            list_date = run.as_of_date if run is not None else date.min
        stmt = select(OpportunityDailyFlag).order_by(OpportunityDailyFlag.flag_date, OpportunityDailyFlag.id)
        if list_date is not None:
            stmt = stmt.where(OpportunityDailyFlag.list_as_of_date == list_date)
        flags = list(session.exec(stmt).all())
        existing = {
            (o.flag_id, o.horizon): o
            for o in session.exec(select(OpportunityFlagOutcome).where(OpportunityFlagOutcome.flag_id.in_([f.id for f in flags]))).all()
        } if flags else {}
        session.expunge_all()
    result.flag_rows = len(flags)

    work = [f for f in flags if any((f.id, h) not in existing or not _is_final(existing[(f.id, h)], now) for h in eng.HORIZONS)]
    new_rows_missing = any((f.id, h) not in existing for f in work for h in eng.HORIZONS)
    state = {k: (o.status, o.stop_hit) for k, o in existing.items()}
    result.frozen_untouched = sum(1 for o in existing.values() if _is_final(o, now))

    def finish(status: str | None = None, reason: str = "") -> ou.UpdateResult:
        if status:
            result.status, result.reason = status, reason
        _fill(result, state)
        return result

    if not work:
        return finish("noop", "every flag already has final outcomes" if flags else "no daily flags to track")

    earliest = min(f.flag_date for f in work)
    lookback = (_eastern_today(now) - earliest).days + LOOKBACK_SLACK_DAYS
    spy_bars = ou._read_bars([SPY], lookback, now).get(SPY)
    if spy_bars is None or spy_bars.empty:
        raise RuntimeError("no completed SPY bars in the cache: cannot build the session calendar")
    result.spy_last_bar_date = spy_bars.index.max().date()
    if not targeted and not new_rows_missing and last_seen_spy is not None and result.spy_last_bar_date <= last_seen_spy:
        return finish("noop", f"SPY has no bar newer than {last_seen_spy} (the last run's)")

    with Session(ou.engine) as session:
        delisted = set(session.exec(select(TickerScore.ticker).where(TickerScore.delisted_at.is_not(None))).all())
        tracked = set(ou.load_tracked_universe(session)) | set(ou.load_etf_universe(session))

    sector_etfs = sorted({SECTOR_TO_ETF[f.sector] for f in work if f.sector in SECTOR_TO_ETF})
    sector_bars = ou._read_bars(sector_etfs, lookback, now) if sector_etfs else {}

    tickers = sorted({f.ticker for f in work})
    result.attempted = len(tickers)
    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i : i + CHUNK_SIZE]
        try:
            frames = ou._read_bars(chunk, lookback, now)
        except Exception as exc:  # noqa: BLE001 -- a bad chunk read leaves its rows as they were; the other chunks still run
            logger.exception("Flag outcome update: reading the bars of %s failed.", chunk)
            frames = {}
            for t in chunk:
                result.failed[t] = f"bars read failed: {exc}"
        with Session(ou.engine, expire_on_commit=False) as session:
            for flag in work:
                if flag.ticker not in chunk:
                    continue
                _update_one(session, result, state, existing, flag, frames.get(flag.ticker), spy_bars, sector_bars, delisted, tracked, now,
                            failed=flag.ticker in result.failed, dry_run=dry_run)
            if dry_run:
                session.rollback()
            else:
                session.commit()
        del frames

    if result.failed and not dry_run:
        result.status = "partial"
    return finish()


def _is_final(row: OpportunityFlagOutcome, now: datetime) -> bool:
    """The weekly rule (ou.is_final) on a flag outcome row: complete, or censored and past its grace period."""
    return ou.is_final(row, now)  # type: ignore[arg-type] -- same fields, a different table


def _update_one(
    session: Session,
    result: ou.UpdateResult,
    state: dict,
    existing: dict,
    flag: OpportunityDailyFlag,
    frame: pd.DataFrame | None,
    spy_bars: pd.DataFrame,
    sector_bars: dict[str, pd.DataFrame],
    delisted: set[str],
    tracked: set[str],
    now: datetime,
    failed: bool,
    dry_run: bool,
) -> None:
    keys = [(flag.id, h) for h in eng.HORIZONS]
    pending_keys = [k for k in keys if k not in existing or not _is_final(existing[k], now)]
    if not pending_keys:
        return
    outcomes: dict[int, eng.HorizonOutcome] = {}
    if not failed:
        sector_etf = SECTOR_TO_ETF.get(flag.sector) if flag.sector else None
        try:
            computed = eng.compute_outcomes(
                as_of=flag.flag_date,
                as_of_close=flag.close,
                ticker_bars=frame,
                spy_bars=spy_bars,
                sector_bars=sector_bars.get(sector_etf) if sector_etf else None,
                sector_etf=sector_etf,
                delisted=flag.ticker in delisted,
                in_universe=flag.ticker in tracked,
            )
            outcomes = {o.horizon: o for o in computed}
        except Exception as exc:  # noqa: BLE001 -- one ticker never stops the others
            logger.error("Flag outcome update: %s (flag %s) failed: %s\n%s", flag.ticker, flag.id, exc, traceback.format_exc())
            result.failed[flag.ticker] = str(exc)
    for key in pending_keys:
        _, horizon = key
        row = existing.get(key)
        outcome = outcomes.get(horizon)
        if row is None:
            values = ou._values(outcome) if outcome is not None else {"status": eng.PENDING}
            new = OpportunityFlagOutcome(
                flag_id=flag.id, ticker=flag.ticker, trigger_id=flag.trigger_id, flag_date=flag.flag_date, horizon=horizon,
                provenance=PROVENANCE_LIVE, trigger_version=flag.trigger_version, computed_at=now,
                first_censored_at=ou._naive_utc(now) if values["status"] == eng.CENSORED else None, **values,
            )
            if not dry_run:
                session.add(new)
            existing[key] = new
            result.flag_seeded += 1
            state[key] = (new.status, new.stop_hit)
            continue
        if outcome is None:
            continue  # the ticker failed: the pending row stays as it was
        values = ou._values(outcome)
        if row.stop_hit and not values["stop_hit"]:  # a stop is final: keep it even if the bars that showed it are gone
            for k in ou._STOP_FIELDS:
                values[k] = getattr(row, k)
        if values["status"] != eng.CENSORED:
            first_censored = None
        else:
            first_censored = row.first_censored_at if row.status == eng.CENSORED and row.first_censored_at is not None else ou._naive_utc(now)
        if ou._same(row, values) and row.first_censored_at == first_censored:
            state[key] = (row.status, row.stop_hit)
            continue
        if not dry_run:
            for k, v in values.items():
                setattr(row, k, v)
            row.first_censored_at = first_censored
            row.computed_at = now
            session.add(row)
        result.flag_updated += 1
        state[key] = (values["status"], values["stop_hit"])


def _fill(result: ou.UpdateResult, state: dict) -> None:
    by_status: dict[str, dict[int, int]] = {}
    for (_flag, horizon), (status, _stop) in state.items():
        by_status.setdefault(status, {})
        by_status[status][horizon] = by_status[status].get(horizon, 0) + 1
    result.flag_by_status = {s: dict(sorted(h.items())) for s, h in by_status.items()}
    result.flag_stops = sum(1 for _status, stop in state.values() if stop)


def update_outcomes_and_flags(
    run_id: int | None = None, as_of: date | None = None, dry_run: bool = False, now: datetime | None = None
) -> ou.UpdateResult:
    """One updater invocation: the weekly lists' outcomes (unchanged) and then the daily flags' outcomes, merged into one UpdateResult.

    The flag path gets the SPY bar date the PREVIOUS run saw (read before the weekly update runs), so its no-op test is the same as the weekly
    one and does not depend on which of the two ran first. The overall status is a no-op only if both parts were; `partial` if either was."""
    now = now or ou.datetime.now(timezone.utc)  # ou.datetime: the weekly module's clock reference, so one patch covers both paths
    targeted = run_id is not None or as_of is not None
    with Session(ou.engine) as session:
        last_seen = None if targeted else ou._last_seen_spy_bar(session)
    result = ou.update_outcomes(run_id=run_id, as_of=as_of, dry_run=dry_run, now=now)
    flags = update_flag_outcomes(run_id=run_id, as_of=as_of, dry_run=dry_run, now=now, last_seen_spy=last_seen)

    result.flag_rows, result.flag_seeded, result.flag_updated = flags.flag_rows, flags.flag_seeded, flags.flag_updated
    result.flag_by_status, result.flag_stops = flags.flag_by_status, flags.flag_stops
    result.frozen_untouched += flags.frozen_untouched
    result.failed.update(flags.failed)
    result.attempted += flags.attempted
    if result.spy_last_bar_date is None:
        result.spy_last_bar_date = flags.spy_last_bar_date
    if flags.status == "noop":
        return result
    if result.status == "noop":
        result.status, result.reason = flags.status, ""
    elif flags.status == "partial" and result.status == "success":
        result.status = "partial"
    return result
