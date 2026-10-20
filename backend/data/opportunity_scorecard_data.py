"""Read model of the Weekly Routine Scorecard: reads the stored outcome tables and hands them to the pure aggregation
(scoring/opportunity_scorecard.py) ONE WEEKLY COHORT AT A TIME, so memory stays flat as cohorts accumulate. READ-ONLY: it never writes
a row, calls no FMP endpoint and does not touch the outcome engine, the updater or the flag job. Spec: docs/specs/opportunities.md,
"Scorecard".

Tables read: OpportunityRun (weights/rules version per cohort), OpportunitySnapshotRow (a listed row's list, tier, rule ids and tags),
OpportunityOutcome (listed rows), OpportunityPoolOutcome (the unlisted pool, the baseline), OpportunityDailyFlag / OpportunityFlagOutcome /
OpportunityDailyRun (flags, their outcomes, and the not-covered / incomplete denominators), OpportunityPick (the user's picks).

Version handling. `rules_version` (default: the current RULES_VERSION) keeps only rows written under that rule set; `triggers_version`
(default: the current TRIGGERS_VERSION) does the same for flags. Rows of another version are counted in `excluded`, never merged.
`weights_version` (default: all) keeps only the cohorts frozen under that score-weight set; the Quality tier depends on the weights, so a
Quality cell that spans more than one carries `mixed_weights` instead of being split.

The response is cached in-process, keyed on the latest outcome-updater run id, the latest daily-flag run id and the weekly run table, so
a request is a dictionary lookup until the 03:40 / 03:45 jobs write something new. `engine` is a module-level reference so tests can
monkeypatch it (the per-module convention)."""

from __future__ import annotations

import json
import threading
from collections import Counter, OrderedDict
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from core.db import engine
from core.models import (
    OpportunityDailyFlag,
    OpportunityDailyRun,
    OpportunityFlagOutcome,
    OpportunityOutcome,
    OpportunityOutcomeRun,
    OpportunityPick,
    OpportunityPoolOutcome,
    OpportunityRun,
    OpportunitySnapshotRow,
)
from scoring import opportunity_rules as rules
from scoring import opportunity_scorecard as sc
from scoring import opportunity_triggers as trig

KIND_WEEKLY = "weekly"
ENTRY_GAP_NOTE = "More than 25% between the list close and the entry open"
PICKS_LABEL = "Priced from the list date, not your add date"
FLAGS_COMPARATOR_LABEL = "Not a controlled comparison"
AUDIT_MAX_LIMIT = 20000
AUDIT_DEFAULT_LIMIT = 5000
SOURCES = ("listed", "flags", "pool")

_CACHE: "OrderedDict[tuple, tuple[tuple, Any]]" = OrderedDict()
_CACHE_MAX = 16
_LOCK = threading.Lock()  # one computation at a time: the box has little spare memory


# --- small helpers ----------------------------------------------------------------------------------------------------------


def _short_rule(rule_id: str) -> str:
    return rule_id.split(".")[0]


def _short_trigger(trigger_id: str) -> str:
    return trigger_id.split(".")[0]


def _loads(text: str | None, default):
    try:
        return json.loads(text) if text else default
    except (TypeError, ValueError):
        return default


class SnapInfo:
    """What the aggregation needs of one listed snapshot row."""

    __slots__ = ("list_name", "tier", "leveraged", "rules", "triggers")

    def __init__(self, list_name: str, tier: str, rule_ids_json: str, tags_json: str):
        tags = _loads(tags_json, {})
        self.list_name = list_name
        self.tier = tier
        self.leveraged = bool(tags.get("leveraged"))
        short = [_short_rule(r) for r in _loads(rule_ids_json, [])]
        self.rules = tuple(r for r in short if r in sc.RULE_CUTS) + (("deep_pullback",) if tags.get("deep_pullback") else ())
        self.triggers = tuple(_short_trigger(t) for t in trig.applicable_triggers(list_name, tags))


def fingerprint(session: Session) -> tuple:
    """What a cached answer depends on: the latest outcome-updater run, the latest daily-flag run and the weekly run table."""
    return (
        session.exec(select(func.max(OpportunityOutcomeRun.id))).one(),
        session.exec(select(func.max(OpportunityDailyRun.id))).one(),
        session.exec(select(func.max(OpportunityRun.id))).one(),
        session.exec(select(func.count()).select_from(OpportunityRun)).one(),
    )


def _cached(key: tuple, session: Session, extra: tuple, compute):
    fp = fingerprint(session) + extra
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == fp:
            _CACHE.move_to_end(key)
            return hit[1]
        value = compute()
        _CACHE[key] = (fp, value)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
        return value


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


class RunRow:
    __slots__ = ("id", "as_of", "rules_version", "weights_version")

    def __init__(self, id: int, as_of: date, rules_version: str, weights_version: int | None):
        self.id, self.as_of, self.rules_version, self.weights_version = id, as_of, rules_version, weights_version


def _weekly_runs(session: Session) -> list[RunRow]:
    rows = session.exec(
        select(OpportunityRun.id, OpportunityRun.as_of_date, OpportunityRun.rules_version, OpportunityRun.weights_version)
        .where(OpportunityRun.kind == KIND_WEEKLY)
        .order_by(OpportunityRun.as_of_date)
    ).all()
    return [RunRow(r[0], r[1], r[2], r[3]) for r in rows]


def _snapshot_info(session: Session, run_id: int) -> dict[str, SnapInfo]:
    rows = session.exec(
        select(
            OpportunitySnapshotRow.ticker,
            OpportunitySnapshotRow.list_name,
            OpportunitySnapshotRow.tier,
            OpportunitySnapshotRow.rule_ids_json,
            OpportunitySnapshotRow.tags_json,
        ).where(OpportunitySnapshotRow.run_id == run_id)
    ).all()
    return {t: SnapInfo(ln, tier, rj, tj) for t, ln, tier, rj, tj in rows}


def _with_stop(stop_hit, stop_fill, ret):
    if stop_hit is None:
        return None
    return stop_fill if stop_hit and stop_fill is not None else ret


@lru_cache(maxsize=64)
def expected_data_dates(as_of: date) -> dict[int, str | None]:
    """The session whose bar completes each horizon of a list built as of `as_of`: the entry bar is the first session after the as-of
    date and horizon N exits at the Nth bar after it (so the (N+1)th session). The bar is stored the next morning and priced by the
    03:40 UTC updater. Lazy import: the calendar library costs about a second to load."""
    try:
        from helpers.trading_calendar import xnys_sessions

        days = [d for d, _o, _c in xnys_sessions(as_of + timedelta(days=1), as_of + timedelta(days=150))]
        return {h: (days[h].isoformat() if len(days) > h else None) for h in sc.HORIZONS}
    except Exception:  # noqa: BLE001 - a calendar failure only removes the expected dates
        return {h: None for h in sc.HORIZONS}


# --- the listed and pool rows of one cohort -----------------------------------------------------------------------------------


def _listed_cols():
    O = OpportunityOutcome
    return (
        O.ticker, O.horizon, O.status, O.entry_gap_flag, O.forward_return, O.spy_return, O.excess_vs_spy, O.sector_return,
        O.excess_vs_sector, O.stop_hit, O.stop_fill_return, O.worst_move, O.max_drawdown, O.rules_version,
    )


def _listed_recs(session: Session, run: RunRow, snaps: dict[str, SnapInfo], rules_version: str, counter: Counter | None = None) -> list[sc.Rec]:
    """The cohort's listed outcome rows of ONE rules version as Rec tuples. Rows of another version are counted in `counter`."""
    out: list[sc.Rec] = []
    cohort = run.as_of.isoformat()
    for t, h, status, gap, ret, sret, sex, secret, secex, sh, sf, worst, dd, rv in session.exec(
        select(*_listed_cols()).where(OpportunityOutcome.run_id == run.id)
    ):
        s = snaps.get(t)
        if s is None:
            continue
        if rv != rules_version:
            if counter is not None:
                counter["other_rules_version"] += 1
            continue
        out.append(sc.Rec(cohort, t, h, status, s.tier, s.list_name, s.leveraged, bool(gap), ret, sret, sex, secret, secex, bool(sh), sf, worst, dd, s.rules))
    return out


def _pool_recs(session: Session, run: RunRow, rules_version: str, counter: Counter | None = None) -> list[sc.Rec]:
    P = OpportunityPoolOutcome
    cohort = run.as_of.isoformat()
    out: list[sc.Rec] = []
    for t, h, status, tier, al, lev, gap, sret, sex, secret, secex, ret, rv in session.exec(
        select(P.ticker, P.horizon, P.status, P.tier, P.assigned_list, P.leveraged, P.entry_gap_flag, P.spy_return, P.excess_vs_spy,
               P.sector_return, P.excess_vs_sector, P.forward_return, P.rules_version).where(P.run_id == run.id)
    ):
        if rv != rules_version:
            if counter is not None:
                counter["pool_other_rules_version"] += 1
            continue
        out.append(sc.Rec(cohort, t, h, status, tier, al, bool(lev), bool(gap), ret, sret, sex, secret, secex, None, None, None, None, ()))
    return out


def _bucket(r: sc.Rec) -> str:
    if r.leveraged:
        return "leveraged"
    if r.entry_gap:
        return "entry_gap"
    return r.status


def _available_versions(session: Session) -> dict:
    return {
        "rules": sorted(v for v in session.exec(select(OpportunityOutcome.rules_version).distinct()).all() if v),
        "triggers": sorted(v for v in session.exec(select(OpportunityDailyFlag.trigger_version).distinct()).all() if v),
        "weights": sorted(v for v in session.exec(select(OpportunityRun.weights_version).where(OpportunityRun.kind == KIND_WEEKLY).distinct()).all() if v is not None),
    }


def _latest_dates(session: Session) -> dict:
    spy = session.exec(select(func.max(OpportunityOutcomeRun.spy_last_bar_date))).one()
    sess = session.exec(select(func.max(OpportunityDailyRun.session_date))).one()
    return {
        "outcomes_spy_bar": spy.isoformat() if spy else None,
        "flags_session": sess.isoformat() if sess else None,
        "latest_outcome_run_id": session.exec(select(func.max(OpportunityOutcomeRun.id))).one(),
        "latest_daily_run_id": session.exec(select(func.max(OpportunityDailyRun.id))).one(),
    }


def _selected(rules_version: str | None, triggers_version: str | None, weights_version: int | None) -> dict:
    return {
        "rules": rules_version or rules.RULES_VERSION,
        "triggers": triggers_version or trig.TRIGGERS_VERSION,
        "weights": weights_version,
        "current_rules": rules.RULES_VERSION,
        "current_triggers": trig.TRIGGERS_VERSION,
    }


# --- /scorecard ---------------------------------------------------------------------------------------------------------------


def get_scorecard(rules_version: str | None = None, triggers_version: str | None = None, weights_version: int | None = None) -> dict:
    sel = _selected(rules_version, triggers_version, weights_version)
    with Session(engine) as session:
        return _cached(("scorecard", sel["rules"], sel["triggers"], weights_version), session, (), lambda: _compute_scorecard(session, sel))


def _compute_scorecard(session: Session, sel: dict) -> dict:
    runs = _weekly_runs(session)
    card = sc.Scorecard()
    counter: Counter = Counter()
    buckets: Counter = Counter()
    cohorts_meta = []
    skipped_weights = 0
    next_expected: dict[int, str] = {}
    for run in runs:
        if sel["weights"] is not None and run.weights_version != sel["weights"]:
            skipped_weights += 1
            continue
        snaps = _snapshot_info(session, run.id)
        listed = _listed_recs(session, run, snaps, sel["rules"], counter)
        pool = _pool_recs(session, run, sel["rules"], counter)
        if run.rules_version != sel["rules"] and not listed:
            counter["cohorts_other_rules_version"] += 1
            continue
        card.add_cohort(run.as_of.isoformat(), run.weights_version, listed, pool)
        for r in listed:
            buckets[(r.horizon, _bucket(r))] += 1
        horizons = {}
        exp = expected_data_dates(run.as_of) if any(r.status == sc.PENDING for r in listed) else {}
        for h in sc.HORIZONS:
            hs = [r for r in listed if r.horizon == h]
            c = Counter(r.status for r in hs)
            pending = c.get(sc.PENDING, 0)
            entry = {
                "complete": c.get(sc.COMPLETE, 0),
                "pending": pending,
                "censored": c.get(sc.CENSORED, 0),
                "expected_data_date": exp.get(h) if pending else None,
            }
            horizons[str(h)] = entry
            if pending and exp.get(h):
                cur = next_expected.get(h)
                if cur is None or exp[h] < cur:
                    next_expected[h] = exp[h]
        cohorts_meta.append(
            {
                "as_of_date": run.as_of.isoformat(),
                "run_id": run.id,
                "rules_version": run.rules_version,
                "weights_version": run.weights_version,
                "listed_rows": len({r.ticker for r in listed}),
                "pool_names": len({r.ticker for r in pool}),
                "horizons": horizons,
            }
        )
    horizons_summary = {
        str(h): {k: buckets.get((h, k), 0) for k in ("complete", "pending", "censored", "entry_gap", "leveraged")} for h in sc.HORIZONS
    }
    return {
        "has_data": bool(cohorts_meta),
        "versions": {"selected": sel, "available": _available_versions(session)},
        "latest": _latest_dates(session),
        "thresholds": {"min_rows": sc.MIN_ROWS, "min_cohorts": sc.MIN_COHORTS, "early_rows": sc.EARLY_ROWS, "early_cohorts": sc.EARLY_COHORTS},
        "horizons": list(sc.HORIZONS),
        "benchmarks": list(sc.BENCHMARKS),
        "excluded": {
            "other_rules_version_rows": counter["other_rules_version"],
            "other_rules_version_pool_rows": counter["pool_other_rules_version"],
            "cohorts_other_weights_version": skipped_weights,
            "by_horizon": horizons_summary,
            "note": "Per cell: pending, censored and entry-gap rows are counted and left out of every statistic; leveraged ETFs have their own row.",
        },
        "next_expected": {str(h): d for h, d in sorted(next_expected.items())},
        "cohorts": cohorts_meta,
        "groups": card.result(),
    }


# --- /scorecard/flags ---------------------------------------------------------------------------------------------------------


def get_flags(rules_version: str | None = None, triggers_version: str | None = None, weights_version: int | None = None) -> dict:
    sel = _selected(rules_version, triggers_version, weights_version)
    with Session(engine) as session:
        return _cached(("flags", sel["rules"], sel["triggers"], weights_version), session, (), lambda: _compute_flags(session, sel))


def _flag_outcome_recs(session: Session, flag_ids: list[int], flags_by_id: dict[int, Any]) -> dict[int, list[sc.Rec]]:
    F = OpportunityFlagOutcome
    out: dict[int, list[sc.Rec]] = {}
    if not flag_ids:
        return out
    for fid, h, status, gap, ret, sret, sex, secret, secex, sh, sf, worst, dd in session.exec(
        select(F.flag_id, F.horizon, F.status, F.entry_gap_flag, F.forward_return, F.spy_return, F.excess_vs_spy, F.sector_return, F.excess_vs_sector,
               F.stop_hit, F.stop_fill_return, F.worst_move, F.max_drawdown).where(F.flag_id.in_(flag_ids))
    ):
        fl = flags_by_id[fid]
        out.setdefault(fid, []).append(
            sc.Rec(fl.cohort, fl.ticker, h, status, fl.tier, fl.list_name, False, bool(gap), ret, sret, sex, secret, secex, bool(sh), sf, worst, dd, ())
        )
    return out


def _daily_run_sets(session: Session, cohort: date) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(not_covered, incomplete) for one cohort: the union over every night judged against it. A name incomplete on ANY night stays out of
    the denominator (it was not fully judged), unless it flagged."""
    not_cov: dict[str, set[str]] = {}
    inc: dict[str, set[str]] = {}
    for nc_json, inc_json in session.exec(
        select(OpportunityDailyRun.not_covered_json, OpportunityDailyRun.incomplete_json).where(
            OpportunityDailyRun.list_as_of_date == cohort, OpportunityDailyRun.status == "success"
        )
    ):
        for tid, tickers in _loads(nc_json, {}).items():
            not_cov.setdefault(_short_trigger(tid), set()).update(tickers)
        for tid, per in _loads(inc_json, {}).items():
            inc.setdefault(_short_trigger(tid), set()).update(per.keys() if isinstance(per, dict) else per)
    return not_cov, inc


def _compute_flags(session: Session, sel: dict) -> dict:
    runs = _weekly_runs(session)
    latest_run = runs[-1].as_of if runs else None
    cohorts: list[sc.FlagCohort] = []
    ledger = []
    counter: Counter = Counter()
    skipped_weights = 0
    for run in runs:
        if sel["weights"] is not None and run.weights_version != sel["weights"]:
            skipped_weights += 1
            continue
        flag_rows = session.exec(
            select(OpportunityDailyFlag).where(
                OpportunityDailyFlag.list_as_of_date == run.as_of, OpportunityDailyFlag.trigger_version == sel["triggers"]
            ).order_by(OpportunityDailyFlag.flag_date, OpportunityDailyFlag.ticker)
        ).all()
        counter["other_trigger_version_flags"] += session.exec(
            select(func.count()).select_from(OpportunityDailyFlag).where(
                OpportunityDailyFlag.list_as_of_date == run.as_of, OpportunityDailyFlag.trigger_version != sel["triggers"]
            )
        ).one()
        snaps = _snapshot_info(session, run.id)
        leveraged = {t for t, s in snaps.items() if s.leveraged}
        window_open = run.as_of == latest_run
        cohort = run.as_of.isoformat()
        eligible: dict[str, set[str]] = {t: set() for t in sc.TRIGGER_ORDER}
        for t, s in snaps.items():
            if s.leveraged:
                continue
            for tr in s.triggers:
                eligible.setdefault(tr, set()).add(t)
        not_cov, inc = _daily_run_sets(session, run.as_of)
        infos: list[sc.FlagInfo] = []
        by_id: dict[int, sc.FlagInfo] = {}
        for f in flag_rows:
            at_ma = _loads(f.inputs_json, {}).get("list_row", {}).get("already_at_ma_on_list")
            info = sc.FlagInfo(f.id, cohort, f.ticker, _short_trigger(f.trigger_id), f.list_name, f.tier, f.flag_date.isoformat(), at_ma if isinstance(at_ma, bool) else None)
            by_id[f.id] = info
            if f.ticker not in leveraged:
                infos.append(info)
        recs_by_flag = _flag_outcome_recs(session, list(by_id), by_id)
        listed = _listed_recs(session, run, snaps, sel["rules"], None)
        listed_by_ticker: dict[str, list[sc.Rec]] = {}
        for r in listed:
            if not r.leveraged:
                listed_by_ticker.setdefault(r.ticker, []).append(r)
        cohorts.append(
            sc.FlagCohort(
                cohort, window_open, run.weights_version, eligible, not_cov, inc, infos,
                {i.flag_id: recs_by_flag.get(i.flag_id, []) for i in infos}, listed_by_ticker,
            )
        )
        for f in flag_rows:
            info = by_id[f.id]
            recs = recs_by_flag.get(f.id, [])
            by_h = {r.horizon: r for r in recs}
            ledger.append(
                {
                    "flag_id": f.id,
                    "ticker": f.ticker,
                    "trigger": info.trigger,
                    "trigger_id": f.trigger_id,
                    "list_name": f.list_name,
                    "tier": f.tier,
                    "leveraged": f.ticker in leveraged,
                    "list_as_of_date": cohort,
                    "flag_date": f.flag_date.isoformat(),
                    "window_open": window_open,
                    "already_at_ma_on_list": info.already_at_ma,
                    "horizons": {
                        str(h): (
                            {
                                "status": by_h[h].status,
                                "forward_return": by_h[h].ret,
                                "excess_vs_spy": by_h[h].ex_spy,
                                "excess_vs_sector": by_h[h].ex_sector,
                                "stop_hit": by_h[h].stop_hit,
                                "stop_fill_return": by_h[h].stop_fill,
                                "with_stop_return": sc.with_stop_return(by_h[h]),
                                "entry_gap_flag": by_h[h].entry_gap,
                            }
                            if h in by_h
                            else None
                        )
                        for h in sc.HORIZONS
                    },
                }
            )
    section = sc.build_flag_section(cohorts)
    ledger.sort(key=lambda r: (r["flag_date"], r["ticker"], r["trigger"]), reverse=True)
    return {
        "has_data": bool(ledger) or any(c.flags for c in cohorts),
        "versions": {"selected": sel, "available": _available_versions(session)},
        "latest": _latest_dates(session),
        "thresholds": {"min_rows": sc.MIN_ROWS, "min_cohorts": sc.MIN_COHORTS, "early_rows": sc.EARLY_ROWS, "early_cohorts": sc.EARLY_COHORTS},
        "comparator_label": FLAGS_COMPARATOR_LABEL,
        "pricing_note": "Flagged names are priced from the flag date (entry the next session's open); the comparison group is priced from the list date.",
        "excluded": {"other_trigger_version_flags": counter["other_trigger_version_flags"], "cohorts_other_weights_version": skipped_weights},
        "triggers": section["triggers"],
        "any_flag": section["any_flag"],
        "ledger": ledger,
    }


# --- /scorecard/picks ---------------------------------------------------------------------------------------------------------


def get_picks(rules_version: str | None = None) -> dict:
    sel = _selected(rules_version, None, None)
    with Session(engine) as session:
        extra = (session.exec(select(func.count()).select_from(OpportunityPick)).one(), session.exec(select(func.max(OpportunityPick.id))).one())
        return _cached(("picks", sel["rules"]), session, extra, lambda: _compute_picks(session, sel))


def _compute_picks(session: Session, sel: dict) -> dict:
    picks = session.exec(select(OpportunityPick.as_of_date, OpportunityPick.ticker)).all()
    base = {"label": PICKS_LABEL, "count": len(picks), "empty": not picks}
    if not picks:
        return {**base, "cohorts": 0, "cells": None, "unmatched": 0, "message": "No picks yet. Picks are the names you add to a watchlist from the Weekly Routine page."}
    by_date: dict[date, set[str]] = {}
    for d, t in picks:
        by_date.setdefault(d, set()).add(t)
    runs = {r.as_of: r for r in _weekly_runs(session)}
    accs = {(h, b): sc.CellAcc(b) for h in sc.HORIZONS for b in sc.BENCHMARKS}
    matched = 0
    cohort_rows = []
    for d, tickers in sorted(by_date.items()):
        run = runs.get(d)
        if run is None:
            continue
        snaps = _snapshot_info(session, run.id)
        recs = [r for r in _listed_recs(session, run, snaps, sel["rules"]) if r.ticker in tickers]
        matched += len({r.ticker for r in recs})
        cohort_rows.append({"as_of_date": d.isoformat(), "picks": len(tickers), "priced": len({r.ticker for r in recs})})
        for h in sc.HORIZONS:
            hs = [r for r in recs if r.horizon == h]
            if hs:
                for b in sc.BENCHMARKS:
                    accs[(h, b)].add(d.isoformat(), hs)
    cells = {str(h): {b: {**accs[(h, b)].counts(), "values": accs[(h, b)].values()} for b in sc.BENCHMARKS} for h in sc.HORIZONS}
    return {**base, "cohorts": len(cohort_rows), "by_cohort": cohort_rows, "cells": cells, "unmatched": len(picks) - matched, "message": None}


# --- /scorecard/outcomes (row-level audit) --------------------------------------------------------------------------------------


def get_outcomes(source: str = "listed", horizon: int | None = None, rules_version: str | None = None, limit: int = AUDIT_DEFAULT_LIMIT, offset: int = 0) -> dict:
    """Row-level audit of what the aggregates are built from. One row per outcome row, with the bucket it falls in (complete / pending /
    censored / entry_gap / leveraged / other_version). Not cached (it pages), but bounded by `limit`."""
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    limit = max(1, min(int(limit), AUDIT_MAX_LIMIT))
    offset = max(0, int(offset))
    rv = rules_version or rules.RULES_VERSION
    with Session(engine) as session:
        runs = {r.id: r for r in _weekly_runs(session)}
        if source == "flags":
            return _audit_flags(session, horizon, limit, offset, runs)
        return _audit_outcomes(session, source, horizon, rv, limit, offset, runs)


def _audit_outcomes(session: Session, source: str, horizon: int | None, rv: str, limit: int, offset: int, runs: dict[int, RunRow]) -> dict:
    Model = OpportunityOutcome if source == "listed" else OpportunityPoolOutcome
    cond = [Model.horizon == horizon] if horizon else []
    total = session.exec(select(func.count()).select_from(Model).where(*cond)).one()
    q = select(Model).where(*cond).order_by(Model.run_id, Model.ticker, Model.horizon).offset(offset).limit(limit)
    rows = []
    snap_cache: dict[int, dict[str, SnapInfo]] = {}
    for m in session.exec(q).all():
        run = runs.get(m.run_id)
        if source == "listed":
            snaps = snap_cache.get(m.run_id)
            if snaps is None:
                snap_cache.clear()  # one cohort at a time, rows are ordered by run
                snaps = snap_cache[m.run_id] = _snapshot_info(session, m.run_id)
            s = snaps.get(m.ticker)
            lst, tier, lev, rule_cuts = (s.list_name, s.tier, s.leveraged, list(s.rules)) if s else (None, None, False, [])
        else:
            lst, tier, lev, rule_cuts = m.assigned_list, m.tier, bool(m.leveraged), []
        if m.rules_version != rv:
            bucket = "other_version"
        elif lev:
            bucket = "leveraged"
        elif m.entry_gap_flag:
            bucket = "entry_gap"
        else:
            bucket = m.status
        row = {
            "source": source,
            "cohort": run.as_of.isoformat() if run else None,
            "weights_version": run.weights_version if run else None,
            "ticker": m.ticker,
            "list_name": lst,
            "tier": tier,
            "leveraged": lev,
            "rules": rule_cuts,
            "horizon": m.horizon,
            "status": m.status,
            "censor_reason": m.censor_reason,
            "bucket": bucket,
            "entry_date": m.entry_date.isoformat() if m.entry_date else None,
            "exit_date": m.exit_date.isoformat() if m.exit_date else None,
            "entry_gap_pct": m.entry_gap_pct,
            "entry_gap_flag": bool(m.entry_gap_flag),
            "forward_return": m.forward_return,
            "spy_return": m.spy_return,
            "excess_vs_spy": m.excess_vs_spy,
            "sector_etf": m.sector_etf,
            "sector_return": m.sector_return,
            "excess_vs_sector": m.excess_vs_sector,
            "rules_version": m.rules_version,
        }
        if source == "listed":
            row.update(
                worst_move=m.worst_move, max_drawdown=m.max_drawdown, stop_hit=bool(m.stop_hit),
                stop_date=m.stop_date.isoformat() if m.stop_date else None, stop_fill_return=m.stop_fill_return,
                with_stop_return=_with_stop(bool(m.stop_hit), m.stop_fill_return, m.forward_return),
            )
        rows.append(row)
    return {"source": source, "total": total, "offset": offset, "limit": limit, "truncated": offset + len(rows) < total, "rows": rows}


def _audit_flags(session: Session, horizon: int | None, limit: int, offset: int, runs: dict[int, RunRow]) -> dict:
    F = OpportunityFlagOutcome
    cond = [F.horizon == horizon] if horizon else []
    total = session.exec(select(func.count()).select_from(F).where(*cond)).one()
    flags = {f.id: f for f in session.exec(select(OpportunityDailyFlag)).all()}
    run_by_date = {r.as_of: r for r in runs.values()}
    rows = []
    for m in session.exec(select(F).where(*cond).order_by(F.flag_date, F.ticker, F.trigger_id, F.horizon).offset(offset).limit(limit)).all():
        fl = flags.get(m.flag_id)
        run = run_by_date.get(fl.list_as_of_date) if fl else None
        rows.append(
            {
                "source": "flags", "cohort": fl.list_as_of_date.isoformat() if fl else None, "weights_version": run.weights_version if run else None,
                "ticker": m.ticker, "trigger_id": m.trigger_id, "list_name": fl.list_name if fl else None, "tier": fl.tier if fl else None,
                "flag_date": m.flag_date.isoformat(), "horizon": m.horizon, "status": m.status, "censor_reason": m.censor_reason,
                "bucket": "entry_gap" if m.entry_gap_flag else m.status,
                "entry_date": m.entry_date.isoformat() if m.entry_date else None, "exit_date": m.exit_date.isoformat() if m.exit_date else None,
                "entry_gap_pct": m.entry_gap_pct, "entry_gap_flag": bool(m.entry_gap_flag), "forward_return": m.forward_return,
                "spy_return": m.spy_return, "excess_vs_spy": m.excess_vs_spy, "sector_etf": m.sector_etf, "sector_return": m.sector_return,
                "excess_vs_sector": m.excess_vs_sector, "worst_move": m.worst_move, "max_drawdown": m.max_drawdown, "stop_hit": bool(m.stop_hit),
                "stop_date": m.stop_date.isoformat() if m.stop_date else None, "stop_fill_return": m.stop_fill_return,
                "with_stop_return": _with_stop(bool(m.stop_hit), m.stop_fill_return, m.forward_return), "trigger_version": m.trigger_version,
            }
        )
    return {"source": "flags", "total": total, "offset": offset, "limit": limit, "truncated": offset + len(rows) < total, "rows": rows}
