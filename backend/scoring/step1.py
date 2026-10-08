from scoring.step1_engine import DECLINE, DOLLAR, INSUFFICIENT, RATIO, assess_series
from scoring.trend import (
    THIN_HISTORY_MIN_POINTS,
    THIN_HISTORY_SCORE_CAP,
    TrendResult,
    most_recent_real_dip_age,
)
from scoring.weights import DEFAULT_WEIGHTS, Step1Weights, step1_tables

# Step 1 (Financials) scores five metrics with ONE neutral engine (scoring/step1_engine.py::assess_series; docs/specs/financials.md):
# Revenue, Net Income, Operating Income, CFO and FCF as DOLLAR series, gross / operating / net margin as RATIO series. Every series
# is COMPLETED FISCAL YEARS ONLY -- no TTM point anywhere in Step 1. This module is the wrapper around the engine: the positivity gate,
# the Net Income Operating Income backup, the Margins combination and carve-out, the CFO/FCF and Margins exemptions, the blend and the
# thin-history cap.
#
# The weight tables are not constants: score_step1 takes a Step1Weights (scoring/weights.py, default DEFAULT_WEIGHTS.step1) and derives the
# three tables below from it with scoring/weights.py::step1_tables. Since 2026-10-08 (docs/decisions.md) every exempt type (Bank,
# Insurance, REIT/Property Developer, Commodity Company) skips CFO, FCF AND Margins and is blended on the third table alone: CFO/FCF/
# Margins weight spread proportionally over Revenue and Net Income (the "Bank" table, 59.57 / 40.43 at the defaults). The middle table
# (CFO-exempt, Margins kept) is no longer reached by any company type; it stays only for a direct caller that exempts CFO alone.
# The three names below are the DEFAULT tables, kept for readers and tests.
WEIGHTS_STANDARD, WEIGHTS_CFO_EXEMPT, WEIGHTS_CFO_MARGINS_EXEMPT = step1_tables(DEFAULT_WEIGHTS.step1)

# --- Net Income Operating Income backup (a wrapper, unchanged except that it reads completed fiscal years, not TTM) ---------------
# When the Net Income score is at or below NET_INCOME_BACKUP_THRESHOLD (CAP - 1: every score the backup could still improve is
# eligible, 80+ is left alone) and its most recent real dip (the old `most_recent_real_dip_age` helper, with its own -5% line) was
# within NET_INCOME_BACKUP_RECENCY_YEARS fiscal years of the latest one -- or Net Income has too few points to have a "recency" at
# all -- the engine is also run on Operating Income, and the Net Income score becomes min(CAP, max(NI, OI)) only if the business is
# genuinely and durably operating-profitable, ALL of: latest completed-fiscal-year OI > 0; that OI >= NET_INCOME_BACKUP_MIN_OI_MARGIN
# of that year's real revenue; OI positive in >= NET_INCOME_BACKUP_MIN_POSITIVE_PERIODS of the last NET_INCOME_BACKUP_OI_WINDOW
# fiscal years (a series shorter than the window is judged on what it has).
NET_INCOME_BACKUP_THRESHOLD = 79
NET_INCOME_BACKUP_CAP = 80
NET_INCOME_BACKUP_RECENCY_YEARS = 2
NET_INCOME_BACKUP_MIN_OI_MARGIN = 0.05
NET_INCOME_BACKUP_OI_WINDOW = 5
NET_INCOME_BACKUP_MIN_POSITIVE_PERIODS = 4
# "No explicit latest-fiscal-year figure supplied": score_step1 then reads it as the last point of the cleaned series it was handed.
# step1_data.py always passes the real latest-fiscal-year values (None when missing), because a None-filtered series can't tell
# "missing" from "present".
_LATEST_FROM_SERIES = object()

# The engine is purely relative/directional -- it never asks whether the values themselves are positive. Revenue, Net Income and CFO
# must be positive AND growing: a latest completed fiscal year at or below zero is `not_yet_positive` whatever the shape. FCF is
# deliberately NOT gated (the engine alone: a negative value is a dip).
NOT_YET_POSITIVE_SCORE = 0  # kept as the fallback when no revenue scale is available (see below)
# --- `not_yet_positive` graduated display (2026-08-13) ----------------------
# A currently-non-positive value used to score a flat 0 regardless of depth -- a company one dollar from breakeven scored identically
# to one deep in genuine structural loss. Points graduate from NOT_YET_POSITIVE_CEILING_SCORE (15) at 0% margin down to 0 at
# NOT_YET_POSITIVE_FLOOR_MARGIN (-20%, chosen from the real distribution of hits, not guessed). Margin is measured against REAL
# revenue (the Revenue series itself, real revenue for every company type since the Net-Interest-Income substitution was removed).
# Revenue's own not_yet_positive case (vanishingly rare) has nothing to normalize against and stays a flat 0.
NOT_YET_POSITIVE_CEILING_SCORE = 15
NOT_YET_POSITIVE_FLOOR_MARGIN = -20.0


def _not_yet_positive_result(value: float, revenue_for_scale: float | None) -> TrendResult:
    if not revenue_for_scale or revenue_for_scale <= 0:
        return TrendResult("not_yet_positive", NOT_YET_POSITIVE_SCORE)
    margin = value / revenue_for_scale * 100
    if margin <= NOT_YET_POSITIVE_FLOOR_MARGIN:
        return TrendResult("not_yet_positive", 0)
    fraction = (margin - NOT_YET_POSITIVE_FLOOR_MARGIN) / abs(NOT_YET_POSITIVE_FLOOR_MARGIN)
    return TrendResult("not_yet_positive", round(NOT_YET_POSITIVE_CEILING_SCORE * fraction))


def _classify_positive_trend(values: list[float], revenue_for_scale: list[float] | None = None) -> TrendResult:
    trend = assess_series(values, DOLLAR)
    if trend.pattern == INSUFFICIENT:
        return trend
    if values[-1] <= 0:
        return _not_yet_positive_result(values[-1], revenue_for_scale[-1] if revenue_for_scale else None)
    return trend


# --- Margins: min(G, max(N, O)) ----------------------------------------------------------------------------------------------------
# Utility: a margin series labelled `decline` / `decline_dips` is never scored below this (applied per series, after the engine's
# positivity ceiling and before the combination). Its margins carry structurally noisier severity than a typical company's. Insurance
# and REIT/Property Developer had it too until 2026-10-08, when they stopped scoring Margins at all.
MARGINS_SEVERITY_CARVEOUT_TYPES = {"Utility"}
MARGINS_CARVEOUT_FLOOR = 60

VERDICT_BANDS = [
    (91, 100, "Strong Pass"),
    (70, 90, "Pass"),
    (0, 69, "Fail"),
]


def _margin_input(values: list[float], carveout: bool) -> TrendResult | None:
    """One margin series through the RATIO engine, then the carve-out. None = missing (fewer than 2 years): the input drops out."""
    result = assess_series(values, RATIO)
    if result.pattern == INSUFFICIENT:
        return None
    if carveout and result.pattern.startswith(DECLINE):
        return TrendResult(result.pattern, max(result.score, MARGINS_CARVEOUT_FLOOR))
    return result


def _classify_margins(
    gross_margin: list[float], operating_margin: list[float], net_margin: list[float], carveout: bool = False
) -> tuple[TrendResult, dict]:
    """Margins = min(G, max(N, O)) of the three per-series RATIO scores (no averaging, no threshold). A missing input drops out: no
    gross margin gives max(N, O); no operating margin gives min(G, N); no net margin gives min(G, O); N and O both missing makes
    Margins `insufficient_data` whatever G is. Returns the result (the pattern is the deciding input's) and the display detail:
    each present input's score/pattern under `inputs`, and which one decides under `binding`."""
    inputs = {
        "gross": _margin_input(gross_margin, carveout),
        "operating": _margin_input(operating_margin, carveout),
        "net": _margin_input(net_margin, carveout),
    }
    gross, operating, net = inputs["gross"], inputs["operating"], inputs["net"]
    detail: dict = {"inputs": {key: {"score": r.score, "pattern": r.pattern} for key, r in inputs.items() if r is not None}}
    if operating is None and net is None:
        return TrendResult(INSUFFICIENT, 0), detail

    present = {key: r for key, r in (("net", net), ("operating", operating)) if r is not None}
    binding_key = max(present, key=lambda key: present[key].score)  # a tie between N and O goes to net margin (listed first)
    if gross is not None and gross.score <= present[binding_key].score:
        binding_key = "gross"
    binding = inputs[binding_key]
    detail["binding"] = binding_key
    return TrendResult(binding.pattern, binding.score), detail


def _classify_fcf(fcf: list[float]) -> TrendResult:
    """FCF through the DOLLAR engine alone: no positivity gate, a negative value is a dip."""
    return assess_series(fcf, DOLLAR)


def _verdict_for(score: int) -> str:
    for low, high, label in VERDICT_BANDS:
        if low <= score <= high:
            return label
    return "Fail"


def _operating_income_backup_allowed(
    operating_income: list[float], latest_operating_income: float | None, latest_revenue: float | None
) -> bool:
    """The K2 gates (see NET_INCOME_BACKUP_MIN_OI_MARGIN's comment), on the latest completed fiscal year. A missing latest Operating
    Income or revenue fails its gate: no lift."""
    if latest_operating_income is None or latest_revenue is None:
        return False
    if latest_operating_income <= 0 or latest_revenue <= 0:
        return False
    if latest_operating_income < NET_INCOME_BACKUP_MIN_OI_MARGIN * latest_revenue:
        return False
    recent = operating_income[-NET_INCOME_BACKUP_OI_WINDOW:]
    return sum(1 for v in recent if v > 0) >= NET_INCOME_BACKUP_MIN_POSITIVE_PERIODS


def _operating_income_backup_gates(
    operating_income: list[float], latest_operating_income: float | None, latest_revenue: float | None
) -> dict:
    """The two measured K2 gate values the Step 1 card quotes when the backup lifted Net Income (display only; the
    pass/fail decision is _operating_income_backup_allowed's)."""
    recent = operating_income[-NET_INCOME_BACKUP_OI_WINDOW:]
    margin = (
        round(latest_operating_income / latest_revenue * 100, 1)
        if latest_operating_income is not None and latest_revenue
        else None
    )
    return {
        "oi_margin_pct": margin,
        "min_oi_margin_pct": NET_INCOME_BACKUP_MIN_OI_MARGIN * 100,
        "positive_periods": sum(1 for v in recent if v > 0),
        "min_positive_periods": NET_INCOME_BACKUP_MIN_POSITIVE_PERIODS,
        "window": len(recent),
    }


def operating_health_gate_passes(
    operating_income: list[float], latest_operating_income: float | None, latest_revenue: float | None
) -> bool:
    """Public name for the K2 operating-health gate (scoring/review.py reads it for the Step 1 evidence string)."""
    return _operating_income_backup_allowed(operating_income, latest_operating_income, latest_revenue)


def score_step1(
    revenue: list[float],
    net_income: list[float],
    operating_income: list[float],
    cfo: list[float] | None,
    gross_margin: list[float],
    net_margin: list[float],
    cfo_exempt: bool,
    fcf: list[float] | None = None,
    margins_exempt: bool = False,
    margins_severity_carveout: bool = False,
    latest_revenue: float | None | object = _LATEST_FROM_SERIES,
    latest_operating_income: float | None | object = _LATEST_FROM_SERIES,
    weights: Step1Weights = DEFAULT_WEIGHTS.step1,
    operating_margin: list[float] | None = None,
) -> dict:
    """Pure scoring function per docs/specs/financials.md: takes parsed metric series (chronological, oldest -> latest COMPLETED
    fiscal year; no TTM point, no missing values) and returns {score, verdict, components}. No I/O, no FMP/DB dependency.

    `operating_margin` is the operating-income-over-revenue series (percent); None or too short is a missing input of the Margins
    combination (it drops out).

    `margins_exempt` (Bank / Insurance / Property Developer / Commodity Company -- see MARGINS_EXEMPT_TYPES in step1_data.py) skips
    Margins entirely, same mechanism as `cfo_exempt` skipping CFO/FCF -- `components["margins"]` comes back `None` and the
    Revenue / Net Income table is used.

    `margins_severity_carveout` (Utility -- see MARGINS_SEVERITY_CARVEOUT_TYPES) keeps a declining margin series at 60 or above.

    `weights` is the Step 1 weight set (default DEFAULT_WEIGHTS.step1); a component weighted 0 is not counted in the blend, but
    its data-gap check below still runs (a missing input can still null the step).

    `latest_revenue` / `latest_operating_income` feed the Operating-Income backup's gates: the last completed fiscal year's REAL
    revenue and Operating Income. `None` means "missing" (the gate fails, no lift); omitted, they default to the
    last point of the (cleaned) series passed in -- a convenience for direct scoring-function callers."""
    growth_reference = revenue  # real revenue for every company type: scales the not_yet_positive graduation and the OI backup's margin gate

    revenue_result = _classify_positive_trend(revenue)
    net_income_pos_result = _classify_positive_trend(net_income, growth_reference)

    net_income_result = net_income_pos_result
    net_income_backup_used = False
    net_income_backup_gates = None
    oi_pos_result = None
    ni_is_insufficient = net_income_pos_result.pattern == INSUFFICIENT
    # The OI fallback is recency-gated -- it exists for a genuine one-off dip 1-2 years back, not a chronic negative/declining Net
    # Income history -- EXCEPT when NI has too few points to have any notion of "recency" at all.
    ni_dip_age = None if ni_is_insufficient else most_recent_real_dip_age(net_income)
    ni_recent_enough = ni_is_insufficient or (
        ni_dip_age is not None and ni_dip_age <= NET_INCOME_BACKUP_RECENCY_YEARS
    )
    if net_income_pos_result.score <= NET_INCOME_BACKUP_THRESHOLD and ni_recent_enough:
        oi_pos_result = _classify_positive_trend(operating_income, growth_reference)
        if latest_operating_income is _LATEST_FROM_SERIES:
            latest_operating_income = operating_income[-1] if operating_income else None
        if latest_revenue is _LATEST_FROM_SERIES:
            latest_revenue = growth_reference[-1] if growth_reference else None
        # The gates only decide whether OI may LIFT Net Income; oi_pos_result is still computed either way, so the "both NI and its
        # backup came up short" data-gap rule below is unchanged.
        if _operating_income_backup_allowed(operating_income, latest_operating_income, latest_revenue):
            backup_score = min(NET_INCOME_BACKUP_CAP, max(net_income_pos_result.score, oi_pos_result.score))
        else:
            backup_score = net_income_pos_result.score
        net_income_backup_used = backup_score != net_income_pos_result.score
        if net_income_backup_used:
            net_income_backup_gates = _operating_income_backup_gates(
                operating_income, latest_operating_income, latest_revenue
            )
        net_income_result = TrendResult(net_income_pos_result.pattern, backup_score)

    # Net Income only reads as a genuine data gap if BOTH it and its own Operating-Income backup came up short -- if OI has real
    # data, the backup mechanism above already produced a legitimate (if low) score, not a fabricated one.
    net_income_insufficient = ni_is_insufficient and (oi_pos_result is None or oi_pos_result.pattern == INSUFFICIENT)

    margin_result = None
    margin_detail: dict = {}
    if not margins_exempt:
        margin_result, margin_detail = _classify_margins(
            gross_margin, operating_margin or [], net_margin, carveout=margins_severity_carveout
        )

    if cfo_exempt or cfo is None:
        cfo_result = None
        fcf_result = None
    else:
        cfo_result = _classify_positive_trend(cfo, growth_reference)
        fcf_result = _classify_fcf(fcf) if fcf is not None else None

    standard_table, cfo_exempt_table, bank_table = step1_tables(weights)
    if margins_exempt:
        table = bank_table
    elif cfo_exempt or cfo is None:
        table = cfo_exempt_table
    else:
        table = standard_table

    # A fetch failure (cache.py::safe_fetch swallows httpx.HTTPError to {}) and a genuinely too-thin real response both collapse to
    # the "insufficient_data" pattern -- that pattern's score of 0 must never be folded into the weighted sum like a real (if bad)
    # result, fabricating a scored Fail out of a data gap. cfo/fcf are only "required" when not cfo-exempt; an exemption is not a
    # gap. fcf_result being None (not cfo-exempt, but no fcf series supplied at all) is the pre-existing "FCF isn't being scored"
    # convention for direct scoring-function callers (tests), not a reachable fetch-failure shape.
    cfo_fcf_applicable = not (cfo_exempt or cfo is None)
    cfo_insufficient = cfo_fcf_applicable and cfo_result.pattern == INSUFFICIENT
    fcf_insufficient = cfo_fcf_applicable and fcf_result is not None and fcf_result.pattern == INSUFFICIENT
    # Same "an exemption is not a gap" reasoning -- margins_exempt types have no Margins result to check.
    margins_insufficient = not margins_exempt and margin_result.pattern == INSUFFICIENT

    if (
        revenue_result.pattern == INSUFFICIENT
        or net_income_insufficient
        or margins_insufficient
        or cfo_insufficient
        or fcf_insufficient
    ):
        return {"score": None, "verdict": "insufficient_data", "components": {}, "weights": table or {}}

    # No table means every weight that applies to this company type is 0: nothing to blend, the same "cannot be scored" outcome as a
    # data gap (never a division by zero). Unreachable under the saved-weight bounds.
    if table is None:
        return {"score": None, "verdict": "insufficient_data", "components": {}, "weights": {}}

    weighted_sum = (
        revenue_result.score * table["revenue"]
        + net_income_result.score * table["net_income"]
        + (cfo_result.score if cfo_result else 0) * table["cfo"]
        + (margin_result.score if margin_result else 0) * table["margins"]
        + (fcf_result.score if fcf_result else 0) * table["fcf"]
    )
    score = max(0, min(100, round(weighted_sum)))
    if len(revenue) < THIN_HISTORY_MIN_POINTS:
        score = min(score, THIN_HISTORY_SCORE_CAP)

    net_income_component = {
        "score": net_income_result.score,
        "pattern": net_income_result.pattern,
        "used_operating_income_backup": net_income_backup_used,
    }
    if net_income_backup_used:
        # Additive display fields, present only when the backup actually lifted the score (the Net Income card's note).
        net_income_component["score_before_backup"] = net_income_pos_result.score
        net_income_component["backup_gates"] = net_income_backup_gates

    return {
        "score": score,
        "verdict": _verdict_for(score),
        "components": {
            "revenue": {"score": revenue_result.score, "pattern": revenue_result.pattern},
            "net_income": net_income_component,
            "cfo": {"score": cfo_result.score, "pattern": cfo_result.pattern} if cfo_result else None,
            # `inputs` / `binding` are additive display fields: the three margin scores and which one decides the Margins score.
            "margins": {"score": margin_result.score, "pattern": margin_result.pattern, **margin_detail}
            if margin_result
            else None,
            "fcf": {"score": fcf_result.score, "pattern": fcf_result.pattern} if fcf_result else None,
        },
        "weights": table,
    }
