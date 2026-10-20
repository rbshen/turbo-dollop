"""Pure aggregation behind the Weekly Routine Scorecard: no DB, no I/O, no clock, nothing is ever written. The data layer
(data/opportunity_scorecard_data.py) hands it one weekly cohort at a time as lightweight `Rec` tuples and it keeps only running totals plus
one small summary per cohort, so memory does not grow with the number of rows. Spec: docs/specs/opportunities.md, "Scorecard".

What a cell is. One group (a list, a tier within a list, a rule cut, or leveraged ETFs) at one horizon (5/10/20/60 sessions) against one
benchmark (SPY or the ticker's sector ETF). Every row falls in exactly ONE bucket, checked in this order: `entry_gap` (the entry open was
more than 25% from the frozen close, whatever the status), `pending`, `censored`, `complete` (with no benchmark return: counted apart as
`no_benchmark`, e.g. an ETF against its sector). Only `complete` rows with a benchmark return enter any statistic.

Statistics are taken PER COHORT first (a cohort is one weekly list; its names overlap the next cohort's and repeat), then summarised
across cohorts: the headline is the median of the cohort medians, the mean is over all rows, "k of m cohorts positive" counts cohorts
whose own median excess is above zero. The cohort count is the effective n, so it is the binding condition of the gate.

The gate (docs/decisions.md, 2026-10-12): values only with at least MIN_ROWS complete rows AND at least MIN_COHORTS cohorts; "early" until
EARLY_ROWS rows AND EARLY_COHORTS cohorts; below the gate the cell carries counts only.

Never produced here: a p-value, a ranking, a "best" marker, a total across groups that overlap, an annualised figure or a pooled horizon
or tier. Rule cuts overlap each other and the lists, so each is computed on its own and never summed."""

from __future__ import annotations

from statistics import median as _median
from typing import Iterable, NamedTuple

HORIZONS: tuple[int, ...] = (5, 10, 20, 60)
SPY, SECTOR = "spy", "sector"
BENCHMARKS: tuple[str, ...] = (SPY, SECTOR)

MIN_ROWS = 20
MIN_COHORTS = 3
EARLY_ROWS = 60
EARLY_COHORTS = 8

TOO_EARLY, EARLY, OK = "too_early", "early", "ok"

PENDING, COMPLETE, CENSORED = "pending", "complete", "censored"

LISTS: tuple[str, ...] = ("momentum", "reversal")
TIERS: tuple[str, ...] = ("quality", "momentum_only", "etf")
RULE_CUTS: tuple[str, ...] = ("B1", "B2", "B3", "deep_pullback")

KIND_LIST, KIND_TIER, KIND_LEVERAGED, KIND_RULE = "list", "tier", "leveraged", "rule"


class Rec(NamedTuple):
    """One outcome row (a listed name, an unlisted pool name or a flag) as the aggregation needs it. Returns are fractions (0.05 = 5%)."""

    cohort: str  # the weekly list's as-of date, ISO
    ticker: str
    horizon: int
    status: str
    tier: str
    list_name: str | None  # listed: the list it is on; pool: the list its trend stage allowed (assigned_list)
    leveraged: bool
    entry_gap: bool
    ret: float | None  # forward_return (buy and hold)
    spy_ret: float | None
    ex_spy: float | None
    sector_ret: float | None
    ex_sector: float | None
    stop_hit: bool | None  # None for pool rows (the slim table has no stop)
    stop_fill: float | None
    worst: float | None
    drawdown: float | None
    rules: tuple[str, ...] = ()  # short rule ids on the row (B1/B2/B3) plus "deep_pullback"


def median(values: Iterable[float]) -> float | None:
    xs = [v for v in values if v is not None]
    return float(_median(xs)) if xs else None


def gate_state(n_rows: int, n_cohorts: int) -> str:
    """too_early below the gate; early above it until 60 rows and 8 cohorts; ok after."""
    if n_rows < MIN_ROWS or n_cohorts < MIN_COHORTS:
        return TOO_EARLY
    if n_rows < EARLY_ROWS or n_cohorts < EARLY_COHORTS:
        return EARLY
    return OK


def with_stop_return(r: Rec) -> float | None:
    """Derived, never stored: the stop's fill return when the 10% stop was hit inside the window, else the buy-and-hold return."""
    if r.stop_hit is None:
        return None
    return r.stop_fill if r.stop_hit and r.stop_fill is not None else r.ret


class CellAcc:
    """Running totals of ONE cell (one group, horizon, benchmark, and one side: listed or pool). Feed it one cohort at a time with `add`."""

    def __init__(self, benchmark: str):
        self.spy = benchmark == SPY
        self.n_complete = self.n_pending = self.n_censored = self.n_entry_gap = self.n_no_benchmark = 0
        self.n_unpriced = 0  # flags only: a flag with no outcome row yet for this horizon (the updater seeds it at its next run)
        self.n_beat = 0
        self.sum_excess = 0.0
        self.stop_hits = self.stop_n = 0
        self.seen: set[str] = set()  # cohorts with any row in the cell (pending ones included)
        self.quality_cohorts: set[str] = set()
        self.per_cohort: dict[str, dict] = {}  # cohort -> its own medians (only cohorts with a complete row)
        self.sensitivity: dict[str, float] = {}  # cohort -> median excess over complete + censored rows

    def add(self, cohort: str, recs: Iterable[Rec]) -> None:
        ex: list[float] = []
        bench: list[float] = []
        rets: list[float] = []
        ws_ret: list[float] = []
        ws_ex: list[float] = []
        worst: list[float] = []
        dd: list[float] = []
        censored_ex: list[float] = []
        any_row = False
        for r in recs:
            any_row = True
            if r.tier == "quality":
                self.quality_cohorts.add(cohort)
            if r.entry_gap:
                self.n_entry_gap += 1
                continue
            if r.status == PENDING:
                self.n_pending += 1
                continue
            e = r.ex_spy if self.spy else r.ex_sector
            if r.status == CENSORED:
                self.n_censored += 1
                if e is not None:
                    censored_ex.append(e)
                continue
            if r.status != COMPLETE:
                continue
            if e is None:
                self.n_no_benchmark += 1
                continue
            b = r.spy_ret if self.spy else r.sector_ret
            ex.append(e)
            if b is not None:
                bench.append(b)
            if r.ret is not None:
                rets.append(r.ret)
            if r.stop_hit is not None:
                self.stop_n += 1
                self.stop_hits += 1 if r.stop_hit else 0
                w = with_stop_return(r)
                if w is not None:
                    ws_ret.append(w)
                    if b is not None:
                        ws_ex.append(w - b)
            if r.worst is not None:
                worst.append(r.worst)
            if r.drawdown is not None:
                dd.append(r.drawdown)
        if any_row:
            self.seen.add(cohort)
        if censored_ex or ex:
            self.sensitivity[cohort] = median(ex + censored_ex)
        if not ex:
            return
        self.n_complete += len(ex)
        self.sum_excess += sum(ex)
        self.n_beat += sum(1 for x in ex if x > 0)
        self.per_cohort[cohort] = {
            "n": len(ex),
            "excess": median(ex),
            "bench": median(bench),
            "ret": median(rets),
            "with_stop_ret": median(ws_ret),
            "with_stop_excess": median(ws_ex),
            "worst": median(worst),
            "drawdown": median(dd),
        }

    # -- reading ----------------------------------------------------------------------------------------------------------

    @property
    def cohorts(self) -> int:
        return len(self.per_cohort)

    @property
    def state(self) -> str:
        return gate_state(self.n_complete, self.cohorts)

    def counts(self) -> dict:
        return {
            "n_complete": self.n_complete,
            "n_pending": self.n_pending,
            "n_censored": self.n_censored,
            "n_entry_gap": self.n_entry_gap,
            "n_no_benchmark": self.n_no_benchmark,
            "n_unpriced": self.n_unpriced,
            "cohorts": self.cohorts,
            "cohorts_total": len(self.seen),
            "state": self.state,
        }

    def values(self) -> dict | None:
        """The statistics, or None below the gate (a cell below the gate shows counts only)."""
        if self.state == TOO_EARLY:
            return None
        cohort_excess = [c["excess"] for c in self.per_cohort.values()]
        sens = list(self.sensitivity.values())
        return {
            "median_excess": median(cohort_excess),
            "mean_excess": self.sum_excess / self.n_complete,
            "share_above": self.n_beat / self.n_complete,
            "cohorts_positive": sum(1 for x in cohort_excess if x is not None and x > 0),
            "cohorts_counted": len(cohort_excess),
            "benchmark_median_return": median(c["bench"] for c in self.per_cohort.values()),
            "median_return": median(c["ret"] for c in self.per_cohort.values()),
            "stop_hit_rate": (self.stop_hits / self.stop_n) if self.stop_n else None,
            "stop_n": self.stop_n,
            "median_with_stop_return": median(c["with_stop_ret"] for c in self.per_cohort.values()),
            "median_with_stop_excess": median(c["with_stop_excess"] for c in self.per_cohort.values()),
            "median_worst_move": median(c["worst"] for c in self.per_cohort.values()),
            "median_drawdown": median(c["drawdown"] for c in self.per_cohort.values()),
            "including_censored": {
                "n": self.n_complete + self.n_censored,
                "median_excess": median(sens),
            },
        }


def paired_difference(listed: CellAcc, pool: CellAcc) -> tuple[float | None, int]:
    """Median over cohorts of (listed cohort median excess - pool cohort median excess), over the cohorts that have both. Returns the
    figure and how many cohorts it rests on."""
    diffs = [
        c["excess"] - pool.per_cohort[k]["excess"]
        for k, c in listed.per_cohort.items()
        if k in pool.per_cohort and c["excess"] is not None and pool.per_cohort[k]["excess"] is not None
    ]
    return median(diffs), len(diffs)


# --- groups ---------------------------------------------------------------------------------------------------------------------


class GroupSpec(NamedTuple):
    key: str
    kind: str
    list_name: str | None
    tier: str | None
    rule: str | None

    def matches_listed(self, r: Rec) -> bool:
        if self.kind == KIND_RULE:
            return not r.leveraged and self.rule in r.rules
        if r.list_name != self.list_name:
            return False
        if self.kind == KIND_LEVERAGED:
            return r.leveraged
        if r.leveraged:  # leveraged ETFs are never in a list or tier statistic
            return False
        return self.kind == KIND_LIST or r.tier == self.tier

    def matches_pool(self, r: Rec) -> bool:
        """The pool names to compare with: same stage-assigned list and the same tier (and leveraged or not). A rule cut has no pool."""
        if self.kind == KIND_RULE:
            return False
        return self.matches_listed(r)

    @property
    def has_pool(self) -> bool:
        return self.kind != KIND_RULE


def group_specs() -> list[GroupSpec]:
    """List, then tier within it, then the list's leveraged ETFs; then the rule cuts (which overlap, so are never summed)."""
    specs: list[GroupSpec] = []
    for lst in LISTS:
        specs.append(GroupSpec(f"{lst}", KIND_LIST, lst, None, None))
        for tier in TIERS:
            specs.append(GroupSpec(f"{lst}:{tier}", KIND_TIER, lst, tier, None))
        specs.append(GroupSpec(f"{lst}:leveraged", KIND_LEVERAGED, lst, "etf", None))
    for rule in RULE_CUTS:
        specs.append(GroupSpec(f"rule:{rule}", KIND_RULE, None, None, rule))
    return specs


class Scorecard:
    """Accumulates cohorts for every group x horizon x benchmark. `add_cohort` is called once per weekly cohort, in any order."""

    def __init__(self):
        self.specs = group_specs()
        self.listed: dict[tuple[str, int, str], CellAcc] = {}
        self.pool: dict[tuple[str, int, str], CellAcc] = {}
        self.weights: dict[str, int | None] = {}
        self.cohort_ids: list[str] = []
        for spec in self.specs:
            for h in HORIZONS:
                for b in BENCHMARKS:
                    self.listed[(spec.key, h, b)] = CellAcc(b)
                    if spec.has_pool:
                        self.pool[(spec.key, h, b)] = CellAcc(b)

    def add_cohort(self, cohort: str, weights_version: int | None, listed: list[Rec], pool: list[Rec]) -> None:
        self.weights[cohort] = weights_version
        self.cohort_ids.append(cohort)
        by_h_listed = {h: [r for r in listed if r.horizon == h] for h in HORIZONS}
        by_h_pool = {h: [r for r in pool if r.horizon == h] for h in HORIZONS}
        for spec in self.specs:
            for h in HORIZONS:
                lrecs = [r for r in by_h_listed[h] if spec.matches_listed(r)]
                prec = [r for r in by_h_pool[h] if spec.matches_pool(r)] if spec.has_pool else []
                for b in BENCHMARKS:
                    if lrecs:
                        self.listed[(spec.key, h, b)].add(cohort, lrecs)
                    if prec:
                        self.pool[(spec.key, h, b)].add(cohort, prec)

    def _weights_note(self, *accs: CellAcc | None) -> dict:
        cohorts: set[str] = set()
        for a in accs:
            if a is not None:
                cohorts |= a.quality_cohorts
        versions = sorted({self.weights[c] for c in cohorts if self.weights.get(c) is not None})
        return {"weights_versions": versions, "mixed_weights": len(versions) > 1}

    def cell(self, spec: GroupSpec, horizon: int, benchmark: str) -> dict:
        la = self.listed[(spec.key, horizon, benchmark)]
        pa = self.pool.get((spec.key, horizon, benchmark))
        out = {**la.counts(), "values": la.values(), **self._weights_note(la, pa)}
        if pa is None:
            out["pool"] = None
            out["listed_minus_pool"] = None
            return out
        pool = {**pa.counts(), "values": pa.values() if la.state != TOO_EARLY else None}
        out["pool"] = pool
        diff, paired = paired_difference(la, pa)
        shown = la.state != TOO_EARLY and pa.state != TOO_EARLY and diff is not None
        out["listed_minus_pool"] = {"median_excess": diff if shown else None, "cohorts": paired}
        return out

    def result(self) -> list[dict]:
        groups = []
        for spec in self.specs:
            seen_any = any(self.listed[(spec.key, h, b)].seen for h in HORIZONS for b in BENCHMARKS)
            if spec.kind == KIND_LEVERAGED and not seen_any:
                continue  # a leveraged row appears only when a leveraged fund was actually listed
            groups.append(
                {
                    "key": spec.key,
                    "kind": spec.kind,
                    "list_name": spec.list_name,
                    "tier": spec.tier,
                    "rule": spec.rule,
                    "has_pool": spec.has_pool,
                    "cells": {str(h): {b: self.cell(spec, h, b) for b in BENCHMARKS} for h in HORIZONS},
                }
            )
        return groups


# --- flags ------------------------------------------------------------------------------------------------------------------------

TRIGGER_ORDER = ("D1", "D2", "D3")


class FlagInfo(NamedTuple):
    flag_id: int
    cohort: str
    ticker: str
    trigger: str  # "D1" | "D2" | "D3" (the id without its version)
    list_name: str
    tier: str
    flag_date: str
    already_at_ma: bool | None  # D3 only: already within 5% of the MA on the list date


class FlagCohort(NamedTuple):
    cohort: str
    window_open: bool
    weights_version: int | None
    eligible: dict[str, set[str]]  # trigger -> tickers the trigger could apply to (leveraged funds already removed)
    not_covered: dict[str, set[str]]  # D1 only
    incomplete: dict[str, set[str]]  # trigger -> tickers that could not be judged on some night
    flags: list[FlagInfo]  # leveraged funds already removed
    flag_recs: dict[int, list[Rec]]  # flag_id -> its outcome rows (priced from the flag date)
    listed_recs: dict[str, list[Rec]]  # ticker -> its LIST-priced outcome rows (the comparator's source)


def cohort_counts(c: FlagCohort, trigger: str) -> dict:
    elig = c.eligible.get(trigger, set())
    flagged = {f.ticker for f in c.flags if f.trigger == trigger}
    not_cov = (c.not_covered.get(trigger, set()) & elig) - flagged
    inc = ((c.incomplete.get(trigger, set()) & elig) - flagged) - not_cov
    unflagged = elig - flagged - not_cov - inc
    return {
        "eligible": len(elig),
        "flagged": len(flagged),
        "not_covered": len(not_cov),
        "incomplete": len(inc),
        "unflagged": len(unflagged),
        "_unflagged": unflagged,
    }


def _first_flags(flags: list[FlagInfo]) -> list[FlagInfo]:
    """The "any flag" view: one flag per (cohort, ticker), the earliest by date, ties broken in trigger order."""
    best: dict[tuple[str, str], FlagInfo] = {}
    for f in flags:
        k = (f.cohort, f.ticker)
        cur = best.get(k)
        if cur is None or (f.flag_date, TRIGGER_ORDER.index(f.trigger)) < (cur.flag_date, TRIGGER_ORDER.index(cur.trigger)):
            best[k] = f
    return list(best.values())


class _FlagCells:
    """The cells of one flag view: a flagged side priced from the flag date and (optionally) an unflagged side priced from the list."""

    def __init__(self, comparator: bool):
        self.flagged = {(h, b): CellAcc(b) for h in HORIZONS for b in BENCHMARKS}
        self.unflagged = {(h, b): CellAcc(b) for h in HORIZONS for b in BENCHMARKS} if comparator else None

    def add_flagged(self, cohort: str, recs: list[Rec]) -> None:
        for h in HORIZONS:
            hs = [r for r in recs if r.horizon == h]
            for b in BENCHMARKS:
                if hs:
                    self.flagged[(h, b)].add(cohort, hs)
                else:
                    self.flagged[(h, b)].n_unpriced += 1

    def add_unflagged(self, cohort: str, recs: list[Rec]) -> None:
        if self.unflagged is None:
            return
        for h in HORIZONS:
            hs = [r for r in recs if r.horizon == h]
            if hs:
                for b in BENCHMARKS:
                    self.unflagged[(h, b)].add(cohort, hs)

    def result(self) -> dict:
        out = {}
        for h in HORIZONS:
            per = {}
            for b in BENCHMARKS:
                f = self.flagged[(h, b)]
                entry = {"flagged": {**f.counts(), "values": f.values()}}
                if self.unflagged is not None:
                    u = self.unflagged[(h, b)]
                    entry["unflagged"] = {**u.counts(), "values": u.values() if f.state != TOO_EARLY else None}
                per[b] = entry
            out[str(h)] = per
        return out


def build_flag_section(cohorts: list[FlagCohort]) -> dict:
    """Trigger-level counts and cells, the D3 split and the deduped "any flag" view. Triggers are never summed with each other.

    The comparator is the SAME cohort's unflagged eligible names (eligible, minus flagged, minus not covered, minus incomplete), priced
    from the LIST (entry the open after the list date), the flagged names from their own flag date: it is NOT a controlled comparison,
    and an open cohort's unflagged side is provisional (a name can still flag)."""
    triggers = {}
    for t in TRIGGER_ORDER:
        counts = {"eligible": 0, "flagged": 0, "not_covered": 0, "incomplete": 0, "unflagged": 0}
        cells = _FlagCells(comparator=True)
        split = {True: _FlagCells(comparator=False), False: _FlagCells(comparator=False)} if t == "D3" else None
        split_counts = {True: 0, False: 0}
        open_cohorts = flagged_open = 0
        provisional = False
        per_cohort = []
        for c in cohorts:
            cc = cohort_counts(c, t)
            for k in counts:
                counts[k] += cc[k]
            flags_t = [f for f in c.flags if f.trigger == t]
            if c.window_open:
                open_cohorts += 1
                flagged_open += len(flags_t)
                if cc["unflagged"]:
                    provisional = True
            per_cohort.append({"cohort": c.cohort, "window_open": c.window_open, "weights_version": c.weights_version, **{k: cc[k] for k in counts}})
            for f in flags_t:
                recs = c.flag_recs.get(f.flag_id, [])
                cells.add_flagged(c.cohort, recs)
                if split is not None:
                    key = bool(f.already_at_ma)
                    split_counts[key] += 1
                    split[key].add_flagged(c.cohort, recs)
            unf = [r for tk in cc["_unflagged"] for r in c.listed_recs.get(tk, [])]
            cells.add_unflagged(c.cohort, unf)
        entry = {
            "trigger": t,
            **counts,
            "cohorts": len(cohorts),
            "cohorts_window_open": open_cohorts,
            "flagged_in_open_cohorts": flagged_open,
            "comparator_provisional": provisional,
            "per_cohort": per_cohort,
            "cells": cells.result(),
        }
        if split is not None:
            entry["split"] = {
                "already_at_ma_on_list": {"flagged": split_counts[True], "cells": split[True].result()},
                "not_at_ma_on_list": {"flagged": split_counts[False], "cells": split[False].result()},
            }
        triggers[t] = entry

    any_cells = _FlagCells(comparator=False)
    all_flags = [f for c in cohorts for f in c.flags]
    by_cohort = {c.cohort: c for c in cohorts}
    firsts = _first_flags(all_flags)
    open_flagged = 0
    for f in firsts:
        c = by_cohort[f.cohort]
        any_cells.add_flagged(f.cohort, c.flag_recs.get(f.flag_id, []))
        open_flagged += 1 if c.window_open else 0
    any_view = {
        "flagged_names": len(firsts),
        "flagged_in_open_cohorts": open_flagged,
        "cells": any_cells.result(),
    }
    return {"triggers": triggers, "any_flag": any_view}
