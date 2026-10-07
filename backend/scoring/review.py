"""The "Review" status: a separate, demote-only read stored beside the Overall verdict (docs/specs/overview.md, "Review").

It never changes the numeric Overall score or the stored verdict. It applies only to a ticker whose Overall verdict is
Pass, Pass with caution or Strong Pass, and only when Step 1 (Financials) or Step 5 (Debt) is a Fail scoring below
`REVIEW_GATE_SCORE`. Each gated step gets a hint (structural / by design / unclear); a data-quality guard turns a hint into
`data_uncertain` while still recording the raw hint, so a guard never hides a structural reading. Facts only, no UI wording
(the labels live in the frontend), following the DataQualityFlag convention.

Pure: no I/O, no FMP, no DB. The caller (data/ticker_score.py) passes the step outputs, the balance-sheet rows and the
data-quality flags it already has. Inputs are read by attribute, so the pydantic step payloads can be passed as they are."""

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Sequence

from scoring.step1 import operating_health_gate_passes

# The one gate constant: a Fail below this score gates Step 1 / Step 5. 70 (the Pass floor) is NOT used; see
# docs/decisions.md.
REVIEW_GATE_SCORE = 50

# Step 5 hints.
DSR_STRUCTURAL = 60.0  # debt servicing ratio (%) at or above this reads structural
DSR_COVERED_BELOW = 30.0  # a failing Debt/EBITDA is covered only while DSR is below this (%)
ICR_COVERED_MIN = 5.0  # ... and interest coverage is at least this
DEBT_EBITDA_BAND = 0.20  # last 5 fiscal years plus TTM within +/- this of their median
DEBT_EBITDA_WINDOW = 6  # 5 fiscal years + TTM
CURRENT_RATIO_FLOOR = 1.0  # "below 1.0" (strict)
CR_ANNUAL_WINDOW, CR_ANNUAL_MIN_BELOW = 5, 4
CR_QUARTERLY_WINDOW, CR_QUARTERLY_MIN_BELOW = 8, 6

PASS_FAMILY = ("Pass", "Pass with caution", "Strong Pass")
FAILING_RATIO_LABELS = ("borderline_fail", "severe", "negative_ebitda")

# Status keys (stable, stored) and their display labels (the frontend carries its own copy of the wording).
REVIEW_STRUCTURAL = "review_structural"
DATA_UNCERTAIN = "data_uncertain"
REVIEW_UNCLEAR = "review_unclear"
REVIEW_BY_DESIGN = "review_by_design"
STATUS_LABELS = {
    REVIEW_STRUCTURAL: "Review (structural)",
    DATA_UNCERTAIN: "Data uncertain",
    REVIEW_UNCLEAR: "Review (unclear)",
    REVIEW_BY_DESIGN: "Review (by design)",
}

# Hints.
STRUCTURAL = "structural"
BY_DESIGN = "by_design"
UNCLEAR = "unclear"

# Data-quality guard: which flag rules guard which step.
STEP1_GUARD_RULES = ("placeholder_cf", "scale_break", "not_landed")
STEP5_GUARD_RULES = ("partial_balance_sheet", "scale_break", "not_landed")

STEP_NAMES = {"step1": "Financials", "step5": "Debt"}


@dataclass
class ReviewResult:
    status: str | None
    reasons: list[dict] = field(default_factory=list)  # {step, score, verdict, hint, raw_hint, guarded, rule, evidence}
    conviction: str | None = None  # "high" | "medium" | "low"; Pass-family rows only


@dataclass(frozen=True)
class _Hint:
    hint: str
    rule: str
    evidence: str


# --- Step 5 coverage tests ---------------------------------------------------------------------------------------


def _current_ratio(row: dict) -> float | None:
    assets, liabilities = row.get("totalCurrentAssets"), row.get("totalCurrentLiabilities")
    if assets is None or liabilities is None or liabilities <= 0:
        return None
    return assets / liabilities


def below_one_count(rows: Sequence[dict], window: int) -> tuple[int, int]:
    """(rows with a Current Ratio below 1.0, rows with a usable ratio) over the `window` newest rows. An unusable row
    (missing assets or liabilities, liabilities not positive) counts as not below."""
    ratios = [_current_ratio(row) for row in rows[:window]]
    usable = [r for r in ratios if r is not None]
    return sum(1 for r in usable if r < CURRENT_RATIO_FLOOR), len(usable)


def quarters_from(rows: Sequence[dict], used_period_end: str | None) -> list[dict]:
    """The cleaned quarterly balance sheets, newest first: when the completeness gate fell back, the partial newest
    quarter(s) after the balance sheet in use are dropped, so the window starts at the row Step 5 actually reads."""
    if not used_period_end:
        return list(rows)
    return [row for row in rows if (row.get("date") or "")[:10] <= used_period_end[:10]]


def current_ratio_covered(annual: Sequence[dict], quarterly: Sequence[dict]) -> tuple[bool, str, str]:
    """(covered, rule, evidence): below 1.0 in at least 4 of the last 5 fiscal years OR at least 6 of the last 8 quarters."""
    a_below, a_usable = below_one_count(annual, CR_ANNUAL_WINDOW)
    q_below, q_usable = below_one_count(quarterly, CR_QUARTERLY_WINDOW)
    evidence = (
        f"Current Ratio below 1.0 in {a_below} of the last {CR_ANNUAL_WINDOW} fiscal years "
        f"and {q_below} of the last {CR_QUARTERLY_WINDOW} quarters"
    )
    if a_below >= CR_ANNUAL_MIN_BELOW:
        return True, "cr_chronic_annual", evidence
    if q_below >= CR_QUARTERLY_MIN_BELOW:
        return True, "cr_chronic_quarterly", evidence
    return False, "not_covered", evidence


def debt_ebitda_covered(series: Sequence[float | None], icr: float | None, dsr: float | None) -> tuple[bool, str]:
    """(covered, evidence): the last 5 fiscal years plus TTM all present and within +/-20% of their median, interest
    coverage at least 5, debt servicing below 30%. A missing figure fails closed."""
    window = list(series[-DEBT_EBITDA_WINDOW:])
    icr_text = "n/a" if icr is None else f"{icr:.2f}x"
    dsr_text = "n/a" if dsr is None else f"{dsr:.1f}%"
    if len(window) < DEBT_EBITDA_WINDOW or any(v is None for v in window):
        return False, f"Debt/EBITDA history incomplete (need 5 fiscal years plus TTM); interest coverage {icr_text}, debt servicing {dsr_text}"
    mid = median(window)
    if mid <= 0:
        return False, f"Debt/EBITDA median {mid:.2f}x is not positive; interest coverage {icr_text}, debt servicing {dsr_text}"
    stable = all(abs(v - mid) <= DEBT_EBITDA_BAND * mid + 1e-9 for v in window)  # inclusive; epsilon for float edges
    evidence = (
        f"Debt/EBITDA 5 fiscal years plus TTM {min(window):.2f}x to {max(window):.2f}x around a median of {mid:.2f}x "
        f"({'within' if stable else 'outside'} +/-{DEBT_EBITDA_BAND:.0%}); interest coverage {icr_text}, debt servicing {dsr_text}"
    )
    covered = stable and icr is not None and icr >= ICR_COVERED_MIN and dsr is not None and dsr < DSR_COVERED_BELOW
    return covered, evidence


def _ratio(step5: Any, key: str) -> tuple[float | None, str | None]:
    ratio = (step5.ratios or {}).get(key)
    return (None, None) if ratio is None else (ratio.value, ratio.label)


def _step5_hint(step5: Any, annual: Sequence[dict], quarterly: Sequence[dict]) -> _Hint:
    cr_value, cr_label = _ratio(step5, "current_ratio")
    de_value, de_label = _ratio(step5, "debt_to_ebitda")
    dsr_value, dsr_label = _ratio(step5, "debt_servicing_ratio")
    icr_value, _ = _ratio(step5, "interest_coverage_ratio")

    if dsr_value is not None and dsr_value >= DSR_STRUCTURAL:
        return _Hint(STRUCTURAL, "dsr_ge_60", f"Debt servicing ratio {dsr_value:.1f}% (at or above {DSR_STRUCTURAL:.0f}%)")

    failing = [
        key
        for key, label in (("current_ratio", cr_label), ("debt_to_ebitda", de_label), ("debt_servicing_ratio", dsr_label))
        if label in FAILING_RATIO_LABELS
    ]
    if not failing:
        # REIT gearing and any blend-only failure: there is no failing ratio a coverage test could excuse.
        labels = ", ".join(f"{key} {ratio.label}" for key, ratio in (step5.ratios or {}).items()) or "no ratios"
        return _Hint(UNCLEAR, "not_covered", f"No single failing ratio ({labels})")
    if "debt_servicing_ratio" in failing:
        return _Hint(UNCLEAR, "not_covered", f"Debt servicing ratio {dsr_value:.1f}% fails and is never covered")

    rules: list[str] = []
    parts: list[str] = []
    all_covered = True
    if "current_ratio" in failing:
        covered, rule, evidence = current_ratio_covered(annual, quarterly)
        parts.append(f"Current Ratio {cr_value:.2f} ({cr_label}): {evidence}")
        rules.append(rule)
        all_covered &= covered
    if "debt_to_ebitda" in failing:
        covered, evidence = debt_ebitda_covered(step5.debt_to_ebitda_series or [], icr_value, dsr_value)
        shown = "negative EBITDA" if de_value is None else f"{de_value:.2f}x"
        parts.append(f"Debt/EBITDA {shown} ({de_label}): {evidence}")
        rules.append("debt_ebitda_stable" if covered else "not_covered")
        all_covered &= covered
    if all_covered:
        return _Hint(BY_DESIGN, "+".join(rules), "; ".join(parts))
    return _Hint(UNCLEAR, "not_covered", "; ".join(parts))


# --- Step 1 evidence ----------------------------------------------------------------------------------------------


def _loss_periods(series: Sequence[float | None]) -> str:
    real = [v for v in series if v is not None]
    return f"{sum(1 for v in real if v < 0)}/{len(real)}"


def _completed_years(step1: Any, values: Sequence[float | None] | None) -> list[float | None]:
    """The series without the display-only TTM slot at its end: Step 1 scores completed fiscal years only."""
    series = list(values or [])
    years = getattr(step1, "years", None) or []
    return series[:-1] if years and years[-1] == "TTM" and len(series) == len(years) else series


def _step1_evidence(step1: Any, gate: int) -> str:
    weak = []
    for name, component in (step1.components or {}).items():
        if component and component.get("score") is not None and component["score"] < gate:
            weak.append(f"{name} {component.get('pattern')} {component['score']}")
    operating_income = _completed_years(step1, step1.operating_income)
    revenue = _completed_years(step1, step1.revenue)
    latest_oi = operating_income[-1] if operating_income else None
    latest_revenue = revenue[-1] if revenue else None
    margin = f"{latest_oi / latest_revenue * 100:.1f}%" if latest_oi is not None and latest_revenue else "n/a"
    gate_passes = operating_health_gate_passes([v for v in operating_income if v is not None], latest_oi, latest_revenue)
    return (
        f"weak components: {', '.join(weak) if weak else 'none below ' + str(gate)}; "
        f"latest fiscal year operating margin {margin}; "
        f"operating-health gate {'passes' if gate_passes else 'fails'}; "
        f"loss years: net income {_loss_periods(_completed_years(step1, step1.net_income))}, operating income {_loss_periods(operating_income)}"
    )


# --- guard --------------------------------------------------------------------------------------------------------


def flag_counts(flag: Any) -> bool:
    """An annual flag always counts; a quarterly one only when it sits in the TTM window or is the newest row. not_landed
    is about the newest reported quarter missing from the statements, so it always counts (its own detail marks neither
    in_ttm_window nor newest_period)."""
    if flag.rule == "not_landed" or flag.period == "annual":
        return True
    detail = flag.detail or {}
    return bool(detail.get("in_ttm_window") or detail.get("newest_period"))


def _guards(step: str, step5: Any, flags: Sequence[Any]) -> list[str]:
    rules = STEP1_GUARD_RULES if step == "step1" else STEP5_GUARD_RULES
    found = [
        f"{f.rule} {f.statement} {f.period} {f.period_end or 'n/a'}" for f in flags if f.rule in rules and flag_counts(f)
    ]
    if step == "step5" and step5 is not None and getattr(step5, "balance_sheet_fallback", None) is not None:
        found.append("balance_sheet_fallback")
    return found


# --- conviction ---------------------------------------------------------------------------------------------------


def conviction_for(step2_verdict: str | None, step4_verdict: str | None) -> str:
    """high: Steps 2 and 4 both Pass or better; low: both Fail; otherwise medium. A step that is not scored counts as
    below Pass (never as Fail)."""
    verdicts = (step2_verdict, step4_verdict)
    if all(v in ("Pass", "Strong Pass") for v in verdicts):
        return "high"
    if all(v == "Fail" for v in verdicts):
        return "low"
    return "medium"


# --- the status ---------------------------------------------------------------------------------------------------


def _gated(step: Any, gate: int) -> bool:
    return step is not None and step.verdict == "Fail" and step.score is not None and step.score < gate


def compute_review(
    overall_verdict: str | None,
    step1: Any,
    step2: Any,
    step4: Any,
    step5: Any,
    balance_sheet_annual: Sequence[dict],
    balance_sheet_quarterly: Sequence[dict],
    flags: Sequence[Any],
    *,
    gate: int = REVIEW_GATE_SCORE,
) -> ReviewResult:
    """`overall_verdict` is the stored Overall verdict; only a Pass-family one can get a status (and a conviction). `step1`,
    `step5` need score, verdict (and, for the hints, components/series/ratios); `step2`, `step4` only a verdict. Any step may
    be None (errored). `balance_sheet_quarterly` is the cleaned quarterly list (see `quarters_from`), newest first."""
    if overall_verdict not in PASS_FAMILY:
        return ReviewResult(None)

    conviction = conviction_for(getattr(step2, "verdict", None), getattr(step4, "verdict", None))
    reasons: list[dict] = []
    for key, step in (("step1", step1), ("step5", step5)):
        if not _gated(step, gate):
            continue
        hint = (
            _Hint(UNCLEAR, "step1_gated", _step1_evidence(step, gate))
            if key == "step1"
            else _step5_hint(step, balance_sheet_annual, balance_sheet_quarterly)
        )
        guards = _guards(key, step5, flags)
        evidence = hint.evidence + (f"; data-quality guard: {', '.join(guards)}" if guards else "")
        reasons.append(
            {
                "step": key,
                "score": step.score,
                "verdict": step.verdict,
                "hint": DATA_UNCERTAIN if guards else hint.hint,
                "raw_hint": hint.hint,
                "guarded": bool(guards),
                "rule": hint.rule,
                "evidence": evidence,
            }
        )

    if not reasons:
        return ReviewResult(None, [], conviction)
    if any(r["hint"] == STRUCTURAL for r in reasons):
        status = REVIEW_STRUCTURAL
    elif any(r["guarded"] for r in reasons):
        status = DATA_UNCERTAIN
    elif any(r["hint"] == UNCLEAR for r in reasons):
        status = REVIEW_UNCLEAR
    else:
        status = REVIEW_BY_DESIGN
    return ReviewResult(status, reasons, conviction)
