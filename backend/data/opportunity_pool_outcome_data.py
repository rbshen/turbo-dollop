"""Pricing of the POOL's outcomes: for every UNLISTED name of a weekly opportunity run's pool (OpportunityPoolRow with `listed = false`), four slim
OpportunityPoolOutcome rows (5 / 10 / 20 / 60 sessions), computed by the SAME pure engine as the lists' outcomes
(scoring/opportunity_outcomes.py::compute_outcomes, through the slim wrapper scoring/opportunity_pool_outcomes.py) with the run's as-of date and
the pool row's frozen close. So the conventions are identical: entry is the next session's OPEN, exit the Nth bar's CLOSE, price-only, SPY and
sector-ETF benchmarks, censoring and the 14-day grace. Listed names are NOT repeated here: they have OpportunityOutcome. The baseline a
scorecard needs is "the names the rules left out"; this is its data. Spec: docs/specs/opportunities.md, "Pool outcomes".

It is called by pipeline/opportunity_outcome_update.py right after the weekly and flag-outcome steps, in the same invocation: that updater is the
ONLY writer of OpportunityOutcome, OpportunityFlagOutcome and OpportunityPoolOutcome. The weekly and flag paths are not changed: this module is a
parallel path that shares their helpers (`is_final`, the completed-bars read, the censor semantics), and a database with no pool rows behaves
exactly as before (no write, no extra text in the message).

Retroactive: the pool is frozen with its run and the bars are cached, so a run's pool can be priced at any time after its entry bar exists.

STORED DATA ONLY: no FMP call. Rules of the update are those of the weekly outcomes: idempotent; only open rows are recomputed (`pending`, and a
`censored` row inside its grace); `complete` rows are frozen; a ticker that fails leaves its rows as they were. A normal run is a no-op unless SPY has
a bar newer than the last run's or a pool name has no outcome rows yet; `run_id` / `as_of` target one run and skip that check.

Memory: only runs that still have work are loaded (a fully final run costs three small aggregate queries), complete rows are held as key tuples,
and bars are read in chunks of CHUNK_SIZE tickers, SPY and the sector ETFs once.

This module reads and writes through `ou.engine` (the weekly outcome module's engine reference, looked up at call time) rather than binding its own,
so a test that points `data.opportunity_outcome_data.engine` at a throwaway database covers all three paths."""

import json
import logging
import traceback
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import func
from sqlmodel import Session, select

from clients.shared_bars_cache import _eastern_today
from core.models import OpportunityPoolOutcome, OpportunityPoolRow, TickerScore
from data import opportunity_outcome_data as ou
from data.market_breadth_data import SECTOR_TO_ETF
from scoring import opportunity_outcomes as eng
from scoring import opportunity_pool_outcomes as slim

logger = logging.getLogger(__name__)

SPY = "SPY"
CHUNK_SIZE = ou.CHUNK_SIZE
LOOKBACK_SLACK_DAYS = ou.LOOKBACK_SLACK_DAYS
PROVENANCE_LIVE = ou.PROVENANCE_LIVE


def _leveraged(pool: OpportunityPoolRow) -> bool:
    """A 2x / 3x fund, from the `leverage` the weekly job froze in the pool row's inputs."""
    try:
        return bool(json.loads(pool.inputs_json or "{}").get("leverage"))
    except (TypeError, ValueError):
        return False


def _is_final(row: OpportunityPoolOutcome, now: datetime) -> bool:
    """The weekly rule (ou.is_final) on a pool outcome row: complete, or censored and past its grace period."""
    return ou.is_final(row, now)  # type: ignore[arg-type] -- same fields, a different table


def update_pool_outcomes(
    run_id: int | None = None,
    as_of: date | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
    last_seen_spy: date | None = None,
) -> ou.UpdateResult:
    """Prices the unlisted pool names of the targeted weekly runs (default: all) and upserts their slim outcome rows. `last_seen_spy` is the SPY bar
    date the previous updater run saw, for the no-op test (read here when not given and the run is not targeted). `dry_run` computes the same
    state and writes nothing. The pool fields of the returned UpdateResult are filled; the weekly fields are not."""
    now = now or ou.datetime.now(timezone.utc)  # ou.datetime: the weekly module's clock reference, so one patch covers every path
    targeted = run_id is not None or as_of is not None
    result = ou.UpdateResult(status="dry_run" if dry_run else "success")
    horizons = eng.HORIZONS

    with Session(ou.engine) as session:
        runs = ou._target_runs(session, run_id, as_of)
        run_ids = [r.id for r in runs]
        if last_seen_spy is None and not targeted:
            last_seen_spy = ou._last_seen_spy_bar(session)
        unlisted: dict[int, int] = {}
        outcome_counts: dict[int, int] = {}
        open_rows: list[OpportunityPoolOutcome] = []
        if run_ids:
            unlisted = dict(
                session.exec(
                    select(OpportunityPoolRow.run_id, func.count()).where(OpportunityPoolRow.run_id.in_(run_ids), OpportunityPoolRow.listed == False)  # noqa: E712
                    .group_by(OpportunityPoolRow.run_id)
                ).all()
            )
            outcome_counts = dict(
                session.exec(
                    select(OpportunityPoolOutcome.run_id, func.count()).where(OpportunityPoolOutcome.run_id.in_(run_ids))
                    .group_by(OpportunityPoolOutcome.run_id)
                ).all()
            )
            open_rows = list(
                session.exec(
                    select(OpportunityPoolOutcome).where(OpportunityPoolOutcome.run_id.in_(run_ids), OpportunityPoolOutcome.status != eng.COMPLETE)
                ).all()
            )
        open_by_run: dict[int, list[OpportunityPoolOutcome]] = {}
        for row in open_rows:
            open_by_run.setdefault(row.run_id, []).append(row)
        # a run has work when a name has no outcome rows yet, or a row is still open (pending, or censored inside its grace)
        candidates = [
            r for r in runs
            if unlisted.get(r.id, 0) > 0
            and (outcome_counts.get(r.id, 0) < len(horizons) * unlisted[r.id] or any(not _is_final(o, now) for o in open_by_run.get(r.id, [])))
        ]
        candidate_ids = [r.id for r in candidates]
        complete_keys: set[tuple[int, str, int]] = set()
        pool_rows: dict[int, list[OpportunityPoolRow]] = {}
        base_counts: list[tuple[str, int, int]] = []
        if candidate_ids:
            complete_keys = {
                (rid, t, h)
                for rid, t, h in session.exec(
                    select(OpportunityPoolOutcome.run_id, OpportunityPoolOutcome.ticker, OpportunityPoolOutcome.horizon).where(
                        OpportunityPoolOutcome.run_id.in_(candidate_ids), OpportunityPoolOutcome.status == eng.COMPLETE
                    )
                ).all()
            }
            for p in session.exec(
                select(OpportunityPoolRow).where(OpportunityPoolRow.run_id.in_(candidate_ids), OpportunityPoolRow.listed == False)  # noqa: E712
            ).all():
                pool_rows.setdefault(p.run_id, []).append(p)
        other_ids = [rid for rid in run_ids if rid not in set(candidate_ids)]
        if other_ids:  # runs with nothing left to do: their rows are all final, only the counts are needed for the report
            base_counts = list(
                session.exec(
                    select(OpportunityPoolOutcome.status, OpportunityPoolOutcome.horizon, func.count()).where(OpportunityPoolOutcome.run_id.in_(other_ids))
                    .group_by(OpportunityPoolOutcome.status, OpportunityPoolOutcome.horizon)
                ).all()
            )
        session.expunge_all()

    result.runs = len(runs)
    result.pool_rows = sum(unlisted.values())
    existing: dict[tuple[int, str, int], OpportunityPoolOutcome] = {
        (o.run_id, o.ticker, o.horizon): o for rid in candidate_ids for o in open_by_run.get(rid, [])
    }
    # state of every pool outcome row after this run, for the report: (run, ticker, horizon) -> status
    state: dict[tuple[int, str, int], str] = {k: o.status for k, o in existing.items()}
    state.update({k: eng.COMPLETE for k in complete_keys})
    result.frozen_untouched = len(complete_keys) + sum(1 for o in existing.values() if _is_final(o, now))

    def finish(status: str | None = None, reason: str = "") -> ou.UpdateResult:
        if status:
            result.status, result.reason = status, reason
        _fill(result, state, base_counts)
        return result

    work: list[tuple] = []  # (run, pool row)
    for run in candidates:
        for pool in pool_rows.get(run.id, []):
            keys = [(run.id, pool.ticker, h) for h in horizons]
            if any(k not in complete_keys and (k not in existing or not _is_final(existing[k], now)) for k in keys):
                work.append((run, pool))
    if not work:
        return finish("noop", "every unlisted pool name already has final outcomes" if result.pool_rows else "no unlisted pool names to track")
    new_rows_missing = any((run.id, p.ticker, h) not in complete_keys and (run.id, p.ticker, h) not in existing for run, p in work for h in horizons)

    earliest = min(run.as_of_date for run, _ in work)
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

    sector_etfs = sorted({SECTOR_TO_ETF[p.sector] for _, p in work if p.sector in SECTOR_TO_ETF})
    sector_bars = ou._read_bars(sector_etfs, lookback, now) if sector_etfs else {}

    tickers = sorted({p.ticker for _, p in work})
    result.attempted = len(tickers)
    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = set(tickers[i : i + CHUNK_SIZE])
        try:
            frames = ou._read_bars(sorted(chunk), lookback, now)
        except Exception as exc:  # noqa: BLE001 -- a bad chunk read leaves its rows as they were; the other chunks still run
            logger.exception("Pool outcome update: reading the bars of %s failed.", sorted(chunk))
            frames = {}
            for t in chunk:
                result.failed[t] = f"bars read failed: {exc}"
        with Session(ou.engine, expire_on_commit=False) as session:
            for run, pool in work:
                if pool.ticker not in chunk:
                    continue
                _update_one(session, result, state, existing, complete_keys, run, pool, frames.get(pool.ticker), spy_bars, sector_bars, delisted, tracked, now,
                            failed=pool.ticker in result.failed, dry_run=dry_run)
            if dry_run:
                session.rollback()
            else:
                session.commit()
        del frames

    if result.failed and not dry_run:
        result.status = "partial"
    return finish()


def _update_one(
    session: Session,
    result: ou.UpdateResult,
    state: dict,
    existing: dict,
    complete_keys: set,
    run,
    pool: OpportunityPoolRow,
    frame: pd.DataFrame | None,
    spy_bars: pd.DataFrame,
    sector_bars: dict[str, pd.DataFrame],
    delisted: set[str],
    tracked: set[str],
    now: datetime,
    failed: bool,
    dry_run: bool,
) -> None:
    keys = [(run.id, pool.ticker, h) for h in eng.HORIZONS]
    pending_keys = [k for k in keys if k not in complete_keys and (k not in existing or not _is_final(existing[k], now))]
    if not pending_keys:
        return
    outcomes: dict[int, dict] = {}
    if not failed:
        sector_etf = SECTOR_TO_ETF.get(pool.sector) if pool.sector else None
        try:
            outcomes = slim.slim_outcomes(
                as_of=run.as_of_date,
                as_of_close=pool.close,
                ticker_bars=frame,
                spy_bars=spy_bars,
                sector_bars=sector_bars.get(sector_etf) if sector_etf else None,
                sector_etf=sector_etf,
                delisted=pool.ticker in delisted,
                in_universe=pool.ticker in tracked,
            )
        except Exception as exc:  # noqa: BLE001 -- one ticker never stops the others
            logger.error("Pool outcome update: %s (run %s) failed: %s\n%s", pool.ticker, run.id, exc, traceback.format_exc())
            result.failed[pool.ticker] = str(exc)
    for key in pending_keys:
        _, ticker, horizon = key
        row = existing.get(key)
        values = outcomes.get(horizon)
        if row is None:
            values = values if values is not None else {"status": eng.PENDING}
            new = OpportunityPoolOutcome(
                run_id=run.id, ticker=ticker, horizon=horizon, tier=pool.tier, assigned_list=pool.assigned_list, leveraged=_leveraged(pool),
                provenance=PROVENANCE_LIVE, rules_version=run.rules_version, computed_at=now,
                first_censored_at=ou._naive_utc(now) if values["status"] == eng.CENSORED else None, **values,
            )
            if not dry_run:
                session.add(new)
            existing[key] = new
            result.pool_seeded += 1
            state[key] = new.status
            continue
        if values is None:
            continue  # the ticker failed: the pending row stays as it was
        # the grace clock starts when a row is FIRST censored, never restarts, and is cleared on revival
        if values["status"] != eng.CENSORED:
            first_censored = None
        else:
            first_censored = row.first_censored_at if row.status == eng.CENSORED and row.first_censored_at is not None else ou._naive_utc(now)
        if all(getattr(row, k) == v for k, v in values.items()) and row.first_censored_at == first_censored:
            state[key] = row.status
            continue
        if not dry_run:
            for k, v in values.items():
                setattr(row, k, v)
            row.first_censored_at = first_censored
            row.computed_at = now
            session.add(row)
        result.pool_updated += 1
        state[key] = values["status"]


def _fill(result: ou.UpdateResult, state: dict, base_counts: list[tuple[str, int, int]]) -> None:
    by_status: dict[str, dict[int, int]] = {}
    for (_run, _ticker, horizon), status in state.items():
        by_status.setdefault(status, {})
        by_status[status][horizon] = by_status[status].get(horizon, 0) + 1
    for status, horizon, n in base_counts:  # runs with nothing left to do
        by_status.setdefault(status, {})
        by_status[status][horizon] = by_status[status].get(horizon, 0) + n
    result.pool_by_status = {s: dict(sorted(h.items())) for s, h in by_status.items()}


def update_pool_into(
    result: ou.UpdateResult, run_id: int | None = None, as_of: date | None = None, dry_run: bool = False, now: datetime | None = None
) -> ou.UpdateResult:
    """Prices the pool and merges it into the weekly/flag `result` (the third step of one updater invocation), the way the flag part is merged:
    the pool counters are copied over, failures and attempted tickers add up, and the overall status is a no-op only if every part was one;
    `partial` if any part was. A database with no unlisted pool rows leaves `result` exactly as it was."""
    pool = update_pool_outcomes(run_id=run_id, as_of=as_of, dry_run=dry_run, now=now)
    result.pool_rows, result.pool_seeded, result.pool_updated, result.pool_by_status = pool.pool_rows, pool.pool_seeded, pool.pool_updated, pool.pool_by_status
    result.frozen_untouched += pool.frozen_untouched
    result.failed.update(pool.failed)
    result.attempted += pool.attempted
    if result.spy_last_bar_date is None:
        result.spy_last_bar_date = pool.spy_last_bar_date
    if pool.status == "noop":
        return result
    if result.status == "noop":
        result.status, result.reason = pool.status, ""
    elif pool.status == "partial" and result.status == "success":
        result.status = "partial"
    return result
