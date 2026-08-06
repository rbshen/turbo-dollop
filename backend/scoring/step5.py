from typing import NamedTuple, Sequence

from scoring.classification import classify_company_type

# Score threshold for "Strong Pass" -- same convention as Step 1/Step 2's
# shared badge tiers (>90 Strong Pass, else Pass when not a hard fail).
STRONG_PASS_SCORE = 90

# Same 70 floor "Pass" starts at everywhere else in the app (CLAUDE.md).
# A tiebreaker-saved breach is a Pass variant -- it must never promote an
# otherwise-failing blend into "Pass with caution" (see _verdict_for).
PASS_SCORE_THRESHOLD = 70

# --- Severity bands ----------------------------------------------------------
# Current Ratio, Debt/EBITDA, and Debt Servicing Ratio each used a single
# hard-fail threshold with no gradation beyond it. Replaced with a 3-zone
# read: Comfortable (unchanged sub-tiering below), Borderline (a real
# breach, but one a tiebreaker -- deferred revenue for Current Ratio,
# Interest Coverage for the other two -- can still save), and Severe (a
# breach far enough beyond the old threshold that no tiebreaker applies;
# always a hard Fail). The old single hard-fail boundary becomes each
# ratio's new *Comfortable* boundary -- nothing below it changes.
CURRENT_RATIO_COMFORTABLE = 1.0
CURRENT_RATIO_SEVERE = 0.7
DEBT_EBITDA_COMFORTABLE = 3.0
DEBT_EBITDA_SEVERE = 4.0
DSR_COMFORTABLE = 30.0
DSR_SEVERE = 40.0
# A borderline breach saved by its tiebreaker still isn't a clean pass --
# scored the same as the old "approaching_limit"/DSR mid-tier, distinct
# from every genuine Comfortable-zone sub-tier (70/85/100).
BORDERLINE_SAVED_SCORE = 60

# A "Pass with caution" ticker's BLENDED score is capped here, separate
# from BORDERLINE_SAVED_SCORE above. Without this, a real breach can still
# blend to a high score if the other ratios are excellent -- worse, Current
# Ratio's deferred-revenue rescue re-scores off the adjusted ratio's own
# Comfortable-zone tier (up to 100), unlike Debt/EBITDA's and DSR's ICR
# rescue which is always capped at BORDERLINE_SAVED_SCORE regardless of how
# comfortably ICR cleared the bar -- so a rescued Current Ratio can blend to
# 95-100 (ADBE, AMP's real shape) despite a genuine breach elsewhere in the
# picture. The verdict text already can't say "Strong Pass" for this case
# (_verdict_for checks saved_by_tiebreaker first), but that only protects
# the label -- a 95-100 NUMBER next to an amber "caution" color still reads
# to a user as contradictory (a top performer flagged as risky). Capped at
# the same ceiling as ScoreBadge's lowest "Pass" shade (70-74, see
# frontend/lib/tierColor.ts) so a caution ticker reads as barely passing,
# not as an excellent result that merely got an asterisk.
PASS_WITH_CAUTION_SCORE_CAP = 74

# --- Interest Coverage Ratio (EBIT / Interest Expense, TTM) -------------------
# New tiebreaker for Debt/EBITDA and Debt Servicing Ratio's borderline zone
# only -- never applies to Current Ratio (whose tiebreaker is deferred
# revenue) and never overrides a Severe breach on either ratio. No doc-given
# numeric thresholds exist for ICR itself; >3x/1-3x/<1x are first-pass
# judgment calls, same status as Step 4's CCC thresholds.
ICR_SAFE = 3.0
ICR_DANGEROUS = 1.0

# --- Breach-context framework ---------------------------------------------------
# A Borderline breach on Debt/EBITDA or Current Ratio (never Severe -- that
# stays an unconditional Fail, no exceptions, exactly as before) gets a
# second, richer look: if the OTHER two ratios (checked as literal raw
# thresholds, not each other's own possibly-rescued classification) are both
# clean, AND a strict majority of the applicable secondary signals below are
# favorable, the breach downgrades from a hard Fail to "marginal" -- reusing
# the existing saved_by_tiebreaker=True / "Pass with caution" / capped-at-74
# machinery verbatim, not a new verdict state. See CLAUDE.md for the worked
# MA/FICO examples this was built around.
#
# All thresholds below are first-pass judgment calls (no doc-given numeric
# guidance exists for any of them), same status as ICR_SAFE above and Step
# 4's CCC thresholds.
TREND_MATERIALITY_FRACTION = 0.10  # must move >10% relatively to count as a real trend, not noise
FCF_TO_DEBT_STRONG = 0.15  # FCF could retire total debt within ~6.7 years
CASH_TO_CURRENT_LIABILITIES_STRONG = 0.5  # cash alone covers half of current liabilities
LIQUID_CURRENT_ASSET_FRACTION_STRONG = 0.5  # majority of current assets are cash+receivables, not inventory
DEFERRED_REVENUE_MATERIAL_FRACTION = 0.15  # deferred revenue is a meaningful (if not fully rescuing) share of current liabilities

# Floor of the graded "marginal" score range -- a bare-strict-majority-
# favorable outcome lands here. The ceiling reuses BORDERLINE_SAVED_SCORE
# (60) above rather than a new constant: an all-favorable outcome lands at
# the exact score the existing narrow ICR-only rescue already used, so this
# doesn't invent a new "best case" number for the same underlying state.
MARGINAL_SCORE_FLOOR = 40


class BreachContextSignal(NamedTuple):
    key: str
    status: str  # "favorable" | "unfavorable" | "not_computable"
    detail: str | None = None
    # False for informational-only signals (cause of debt, undrawn
    # revolving credit, net-vs-gross debt) -- shown to the user but never
    # counted toward the majority-vote gate.
    counts_toward_gate: bool = True


def _evaluate_breach_context(primary_gates_pass: bool, signals: Sequence[BreachContextSignal]) -> tuple[bool, int]:
    """Shared majority-vote + graded-score gate for both breach-context
    sub-frameworks. Returns (qualifies, score) -- score is meaningless
    (0) when qualifies is False, since callers keep the original Fail-
    range RatioResult in that case rather than using this score."""
    if not primary_gates_pass:
        return False, 0
    computable = [s for s in signals if s.counts_toward_gate and s.status != "not_computable"]
    if not computable:
        return False, 0
    favorable = [s for s in computable if s.status == "favorable"]
    if len(favorable) * 2 <= len(computable):  # strict majority required
        return False, 0
    fraction = len(favorable) / len(computable)
    score = round(MARGINAL_SCORE_FLOOR + (BORDERLINE_SAVED_SCORE - MARGINAL_SCORE_FLOOR) * fraction)
    return True, score


def _trend_signal(key: str, oldest_value: float | None, oldest_year: str | None, current_value: float, favorable_if_declining: bool) -> BreachContextSignal:
    """`favorable_if_declining=True` for Debt/EBITDA (declining = actively
    deleveraging); `False` for Current Ratio (declining = real
    deterioration -- stable/consistently-low is the favorable case there).
    Requires the OLDEST slot of the 5yr window specifically (not just any
    historical data point) -- a ticker with under 5 years of annual filings
    (e.g. a recent IPO) reads as not_computable rather than mislabeling a
    shorter window as "5yr"."""
    if oldest_value is None or not oldest_value:
        return BreachContextSignal(key, "not_computable", "Not enough annual history (under 5 years of filings) to compute a 5yr trend.")
    pct_change = (current_value - oldest_value) / abs(oldest_value)
    declined = pct_change <= -TREND_MATERIALITY_FRACTION
    risen = pct_change >= TREND_MATERIALITY_FRACTION
    favorable = declined if favorable_if_declining else not declined
    # "roughly stable" for any move under the materiality floor -- avoids
    # describing e.g. a -7% move (below the 10% floor, so NOT a real
    # decline) as "declined 7%", which would read as contradicting a
    # "favorable" status for Current Ratio's stable-is-fine framing.
    direction = "declined" if declined else "risen" if risen else "roughly stable"
    year_note = f" (FY{oldest_year})" if oldest_year else ""
    detail = f"{current_value:.2f} now vs {oldest_value:.2f}{year_note} 5yr ago -- {direction} ({pct_change * 100:+.0f}%)"
    return BreachContextSignal(key, "favorable" if favorable else "unfavorable", detail)


def evaluate_debt_to_ebitda_breach_context(
    current_ratio: float,
    debt_servicing_pct: float,
    debt_to_ebitda_current: float,
    debt_to_ebitda_oldest: float | None,
    debt_to_ebitda_oldest_year: str | None,
    fcf_ttm: float | None,
    total_debt: float | None,
    interest_coverage_ratio: float | None,
    net_debt: float | None,
    ebitda_ttm: float | None,
) -> tuple[bool, int, tuple[BreachContextSignal, ...]]:
    """Evaluated only when Debt/EBITDA is in the Borderline zone (3.0-4.0x).
    Primary gates are literal raw-threshold checks against the OTHER two
    ratios, not their own (possibly-rescued) classification -- matches the
    exact wording of the design this implements."""
    primary_gates_pass = current_ratio >= CURRENT_RATIO_COMFORTABLE and debt_servicing_pct < DSR_COMFORTABLE

    trend = _trend_signal("trend", debt_to_ebitda_oldest, debt_to_ebitda_oldest_year, debt_to_ebitda_current, favorable_if_declining=True)

    if fcf_ttm is None or total_debt is None or not total_debt:
        fcf_signal = BreachContextSignal("fcf_vs_debt", "not_computable", "Free Cash Flow or Total Debt unavailable.")
    else:
        fcf_ratio = fcf_ttm / total_debt
        favorable = fcf_ttm > 0 and fcf_ratio >= FCF_TO_DEBT_STRONG
        fcf_signal = BreachContextSignal(
            "fcf_vs_debt", "favorable" if favorable else "unfavorable", f"TTM FCF is {fcf_ratio * 100:.0f}% of total debt"
        )

    if interest_coverage_ratio is None:
        icr_signal = BreachContextSignal("interest_coverage", "not_computable", "Interest Coverage Ratio unavailable (interest expense missing or non-positive).")
    else:
        icr_signal = BreachContextSignal(
            "interest_coverage",
            "favorable" if classify_interest_coverage(interest_coverage_ratio) == "safe" else "unfavorable",
            f"{interest_coverage_ratio:.1f}x",
        )

    cause_of_debt_signal = BreachContextSignal(
        "cause_of_debt",
        "not_computable",
        "Not automatically verified -- check whether this debt originated from a recent acquisition (often temporary, as the acquired company's earnings get absorbed into EBITDA) before treating the ratio as a structural concern.",
        counts_toward_gate=False,
    )

    # Purely informational (counts_toward_gate=False) -- "status" here just
    # picks the display treatment, it never gates anything. Always
    # "favorable" when computable: net debt is additive context that either
    # meaningfully improves the picture or doesn't, never actively worse
    # than gross (net debt = gross debt - cash, and cash is never negative).
    if net_debt is None or ebitda_ttm is None or not ebitda_ttm:
        net_vs_gross_signal = BreachContextSignal("net_vs_gross_debt", "not_computable", "Net Debt unavailable.", counts_toward_gate=False)
    else:
        net_debt_to_ebitda = net_debt / ebitda_ttm
        meaningfully_better = net_debt_to_ebitda <= debt_to_ebitda_current - 0.5
        net_vs_gross_signal = BreachContextSignal(
            "net_vs_gross_debt",
            "favorable",
            f"Net Debt/EBITDA is {net_debt_to_ebitda:.2f}x vs {debt_to_ebitda_current:.2f}x gross"
            + (" -- cash holdings meaningfully improve the picture" if meaningfully_better else " -- minimal difference from cash holdings"),
            counts_toward_gate=False,
        )

    signals = (trend, fcf_signal, icr_signal, cause_of_debt_signal, net_vs_gross_signal)
    qualifies, score = _evaluate_breach_context(primary_gates_pass, signals)
    return qualifies, score, signals


def evaluate_current_ratio_breach_context(
    debt_to_ebitda: float | None,
    debt_servicing_pct: float,
    current_ratio_current: float,
    current_ratio_oldest: float | None,
    current_ratio_oldest_year: str | None,
    deferred_revenue: float | None,
    current_liabilities: float | None,
    cash_and_equivalents: float | None,
    current_assets: float | None,
    liquid_current_assets: float | None,
) -> tuple[bool, int, tuple[BreachContextSignal, ...]]:
    """Evaluated only when Current Ratio is STILL Borderline after the
    existing deferred-revenue adjustment already failed to rescue it fully
    to Comfortable (that existing full-rescue path is unchanged and runs
    first -- see score_current_ratio). `debt_to_ebitda=None` (negative-
    EBITDA Fail, 2026-08-06 -- see score_step5_standard) fails the gate
    outright, same treatment as a real breach: an undefined ratio can't
    vouch for a rescue any more than a bad one can."""
    primary_gates_pass = debt_to_ebitda is not None and debt_to_ebitda <= DEBT_EBITDA_COMFORTABLE and debt_servicing_pct < DSR_COMFORTABLE

    if deferred_revenue is None or not current_liabilities:
        deferred_revenue_signal = BreachContextSignal("deferred_revenue", "not_computable", "Deferred revenue or current liabilities unavailable.")
    else:
        fraction = deferred_revenue / current_liabilities
        favorable = fraction >= DEFERRED_REVENUE_MATERIAL_FRACTION
        deferred_revenue_signal = BreachContextSignal(
            "deferred_revenue",
            "favorable" if favorable else "unfavorable",
            f"Deferred revenue is {fraction * 100:.0f}% of current liabilities" + (" -- likely business-model-driven, not a liquidity problem" if favorable else ""),
        )

    trend = _trend_signal("trend", current_ratio_oldest, current_ratio_oldest_year, current_ratio_current, favorable_if_declining=False)

    if cash_and_equivalents is None or not current_liabilities:
        cash_signal = BreachContextSignal("cash_position", "not_computable", "Cash & equivalents or current liabilities unavailable.")
    else:
        cash_fraction = cash_and_equivalents / current_liabilities
        favorable = cash_fraction >= CASH_TO_CURRENT_LIABILITIES_STRONG
        cash_signal = BreachContextSignal("cash_position", "favorable" if favorable else "unfavorable", f"Cash covers {cash_fraction * 100:.0f}% of current liabilities")

    if liquid_current_assets is None or not current_assets:
        asset_quality_signal = BreachContextSignal("asset_quality", "not_computable", "Current asset breakdown unavailable.")
    else:
        liquid_fraction = liquid_current_assets / current_assets
        favorable = liquid_fraction >= LIQUID_CURRENT_ASSET_FRACTION_STRONG
        asset_quality_signal = BreachContextSignal(
            "asset_quality", "favorable" if favorable else "unfavorable", f"{liquid_fraction * 100:.0f}% of current assets are cash/receivables (liquid)"
        )

    revolver_signal = BreachContextSignal(
        "undrawn_revolving_credit",
        "not_computable",
        "Not automatically verified -- undrawn revolving credit facilities are typically footnote/MD&A-only disclosures, check the latest 10-K/10-Q before treating this ratio as a hard liquidity constraint.",
        counts_toward_gate=False,
    )

    signals = (deferred_revenue_signal, trend, cash_signal, asset_quality_signal, revolver_signal)
    qualifies, score = _evaluate_breach_context(primary_gates_pass, signals)
    return qualifies, score, signals


# --- Weights ------------------------------------------------------------------
# Unlike Step 1/Step 4, Step 5 has no exemption/redistribution logic -- these
# are always flat splits, surfaced explicitly for the Reasoning breakdown UI
# the same way Step 1/Step 2 do (WEIGHTS_STANDARD, MAGNITUDE_WEIGHT/
# AGREEMENT_WEIGHT), rather than left implicit in the `/ 3` below.
WEIGHTS_STANDARD = {"current_ratio": 1 / 3, "debt_to_ebitda": 1 / 3, "debt_servicing_ratio": 1 / 3}
WEIGHTS_REIT = {"gearing_ratio": 1.0}
WEIGHTS_BANK = {"cet1_ratio": 0.5, "npl_ratio": 0.5}

__all__ = [
    "classify_company_type",
    "RatioResult",
    "BreachContextSignal",
    "classify_interest_coverage",
    "evaluate_debt_to_ebitda_breach_context",
    "evaluate_current_ratio_breach_context",
    "score_current_ratio",
    "score_debt_to_ebitda",
    "score_debt_servicing",
    "score_gearing",
    "score_npl",
    "score_cet1",
    "score_step5_standard",
    "score_step5_reit",
    "score_step5_bank",
]


class RatioResult(NamedTuple):
    label: str
    points: int
    hard_fail: bool
    # True when a Borderline breach was excused by its tiebreaker (deferred
    # revenue for Current Ratio, Interest Coverage for the other two, or the
    # breach-context framework for both) -- drives the "Pass with caution"
    # verdict, distinct from a clean Pass.
    saved_by_tiebreaker: bool = False
    # Populated only when the breach-context framework evaluated this ratio
    # (Current Ratio/Debt-to-EBITDA, Borderline zone only) -- regardless of
    # whether it qualified for a downgrade, so the UI can explain either
    # outcome. See score_step5_standard.
    breach_context: tuple[BreachContextSignal, ...] = ()
    # Full sentence explaining an unusual result -- populated only for
    # Debt/EBITDA's negative-EBITDA Fail so far (see score_step5_standard).
    # None for every ordinary tier.
    note: str | None = None


def classify_interest_coverage(icr: float | None) -> str:
    if icr is None:
        return "not_applicable"
    if icr > ICR_SAFE:
        return "safe"
    if icr >= ICR_DANGEROUS:
        return "tight"
    return "dangerous"


def _comfortable_current_ratio_tier(value: float) -> tuple[str, int]:
    if value < 1.5:
        return "acceptable", 70
    if value <= 2.0:
        return "good", 85
    return "excellent", 100


def score_current_ratio(raw_ratio: float, adjusted_ratio: float) -> RatioResult:
    """`adjusted_ratio` = current assets / (current liabilities - deferred
    revenue) -- computed by the caller (step5_data.py has the raw balance
    sheet figures; this stays a pure ratio-in, ratio-out function like
    every other scorer here). Equals raw_ratio when there's no deferred
    revenue, so behavior is unchanged for anyone without it."""
    if raw_ratio >= CURRENT_RATIO_COMFORTABLE:
        # Already comfortable on the RAW ratio -- score off raw, byte-
        # identical to before this redesign. Deferred revenue has nothing
        # to rescue here, so it must not perturb an already-fine score.
        label, points = _comfortable_current_ratio_tier(raw_ratio)
        return RatioResult(label, points, False)
    if adjusted_ratio >= CURRENT_RATIO_COMFORTABLE:
        # Raw was NOT comfortable, but deferred revenue rescues it -- score
        # off the adjusted ratio, since that's the basis for the rescue.
        label, points = _comfortable_current_ratio_tier(adjusted_ratio)
        return RatioResult(label, points, False, saved_by_tiebreaker=True)
    if adjusted_ratio >= CURRENT_RATIO_SEVERE:
        return RatioResult("borderline_fail", 0, True)
    return RatioResult("severe", 0, True)


def score_debt_to_ebitda(value: float) -> RatioResult:
    """Pure tier classification only -- the Borderline zone's rescue logic
    used to live here (a narrow icr_is_safe-only check), but is now the
    richer evaluate_debt_to_ebitda_breach_context, applied by the caller
    (score_step5_standard) since it needs context this function doesn't
    have. Borderline always returns unrescued (hard_fail=True) here; the
    caller may override that result."""
    if value <= DEBT_EBITDA_COMFORTABLE:
        if value > 2.0:
            return RatioResult("acceptable", 70, False)
        if value > 1.0:
            return RatioResult("good", 85, False)
        return RatioResult("excellent", 100, False)
    if value <= DEBT_EBITDA_SEVERE:
        return RatioResult("borderline_fail", 0, True)
    return RatioResult("severe", 0, True)


def score_debt_servicing(value_pct: float, icr_is_safe: bool) -> RatioResult:
    if value_pct < DSR_COMFORTABLE:
        if value_pct >= 20.0:
            return RatioResult("approaching_limit", 60, False)
        if value_pct >= 10.0:
            return RatioResult("good", 85, False)
        return RatioResult("excellent", 100, False)
    if value_pct < DSR_SEVERE:
        if icr_is_safe:
            return RatioResult("borderline_saved_by_icr", BORDERLINE_SAVED_SCORE, False, saved_by_tiebreaker=True)
        return RatioResult("borderline_fail", 0, True)
    return RatioResult("severe", 0, True)


def score_gearing(value_pct: float) -> RatioResult:
    if value_pct < 30.0:
        return RatioResult("excellent", 100, False)
    if value_pct <= 40.0:
        return RatioResult("good", 85, False)
    if value_pct <= 45.0:
        return RatioResult("approaching_limit", 60, False)
    return RatioResult("fail", 0, True)


def score_npl(value_pct: float) -> RatioResult:
    """NPL ratio tiers, mirroring Debt/EBITDA's excellent/good/acceptable/
    fail structure (both are higher-is-worse ratios). The source doc's own
    threshold is <5% = pass, so >=5% is the hard-fail boundary; the
    sub-tiers above that are first-pass judgment calls, same status as
    Step 4's CCC thresholds (no doc-given numeric gradation exists).
    Also used, unchanged, as the NPL half of score_step5_bank's blend once
    a CET1 value is available (see score_step5_bank) -- still a standalone
    partial signal on its own otherwise (a Bank ticker with no CET1 entered
    yet still shows this alone, see step5_data.py)."""
    if value_pct >= 5.0:
        return RatioResult("fail", 0, True)
    if value_pct >= 3.0:
        return RatioResult("acceptable", 70, False)
    if value_pct >= 1.0:
        return RatioResult("good", 85, False)
    return RatioResult("excellent", 100, False)


# --- CET1 (Common Equity Tier 1) Ratio -- Bank, manual entry only -----------
# No FMP source exists (confirmed -- see CLAUDE.md's Step 5 CET1 deviation
# note), so this is always a user-entered value, never fetched. Bands below
# are the current agreed thresholds (2026-08-05), replacing both the
# original source doc's numbers and an earlier code-only 8/10/12 version --
# not a reversion to either prior set.
def score_cet1(value_pct: float) -> RatioResult:
    """Mirrors score_npl's excellent/good/acceptable/fail 4-tier shape."""
    if value_pct < 10.0:
        return RatioResult("fail", 0, True)
    if value_pct < 12.0:
        return RatioResult("acceptable", 70, False)
    if value_pct < 14.0:
        return RatioResult("good", 85, False)
    return RatioResult("excellent", 100, False)


def _verdict_for(score: int, hard_fail: bool, saved_by_tiebreaker: bool) -> str:
    # Hard-fail overrides the blended score entirely -- mirrors the Step 2
    # fix (CLAUDE.md's "Scoring rubric deviations"): a breached hard limit
    # must never be diluted by averaging with healthy ratios.
    if hard_fail:
        return "Fail"
    # Neither a hard fail nor a tiebreaker-saved breach, yet the blend still
    # lands below the shared 70 Pass floor -- must not display "Pass"/"Pass
    # with caution" text next to a Fail-range number. Checked once here,
    # covering BOTH: a rescued breach whose blend is still too low (e.g. a
    # saved Debt/EBITDA breach at 60pts alongside a separately weak,
    # non-breaching DSR at 60pts, "approaching_limit", blending under 70
    # with no hard_fail anywhere -- the rescue is redundant in that case,
    # the ticker genuinely fails regardless), AND a plain no-breach-at-all
    # fallback that's just mediocre (e.g. REIT gearing's own
    # "approaching_limit" tier, 60pts, no breach involved -- previously
    # this masked-Pass gap survived even after the first fix above, since
    # this branch only guarded the saved_by_tiebreaker case).
    if score < PASS_SCORE_THRESHOLD:
        return "Fail"
    # A Borderline breach excused by its tiebreaker is a distinct third
    # state -- not a clean Pass (a real breach did occur), not a Fail (a
    # tiebreaker resolved it) -- checked before the Strong Pass threshold
    # since a saved breach should never read as a Strong Pass regardless
    # of score.
    if saved_by_tiebreaker:
        return "Pass with caution"
    if score > STRONG_PASS_SCORE:
        return "Strong Pass"
    return "Pass"


def score_step5_standard(
    current_ratio: float,
    adjusted_current_ratio: float,
    debt_to_ebitda: float | None,
    debt_servicing_pct: float,
    interest_coverage_ratio: float | None,
    *,
    # Breach-context inputs -- all optional (default None), consulted only
    # when the corresponding ratio actually lands in the Borderline zone.
    # A missing individual value just reads as "not_computable" for that
    # one secondary signal rather than failing the whole evaluation (see
    # evaluate_debt_to_ebitda_breach_context / evaluate_current_ratio_
    # breach_context).
    debt_to_ebitda_oldest: float | None = None,
    debt_to_ebitda_oldest_year: str | None = None,
    current_ratio_oldest: float | None = None,
    current_ratio_oldest_year: str | None = None,
    fcf_ttm: float | None = None,
    total_debt: float | None = None,
    net_debt: float | None = None,
    # `debt_to_ebitda=None` and `ebitda_ttm` together disambiguate WHY
    # Debt/EBITDA is unavailable: the caller (step5_data.py) guarantees
    # `debt_to_ebitda` is None here ONLY because `ebitda_ttm` itself is
    # <=0 (2026-08-06 fix) -- a genuinely-missing total_debt/ebitda_ttm
    # never reaches this function at all (that's still `insufficient_data`,
    # filtered out by step5_data.py's own gate before calling this). So
    # `ebitda_ttm` is required (not just decorative) whenever
    # `debt_to_ebitda` is None.
    ebitda_ttm: float | None = None,
    deferred_revenue: float | None = None,
    current_liabilities: float | None = None,
    cash_and_equivalents: float | None = None,
    current_assets: float | None = None,
    liquid_current_assets: float | None = None,
) -> dict:
    """Pure scoring function for Step 5's Standard-company path. No I/O, no
    FMP/DB dependency -- mirrors score_step1/score_step2's shape.
    `adjusted_current_ratio` and `interest_coverage_ratio` are precomputed
    by the caller (step5_data.py has the raw balance sheet/income figures).

    Debt/EBITDA's "ratio undefined" case (2026-08-06 fix) is deliberately
    NOT treated as a neutral exemption the way e.g. IBKR/HOOD's Bank
    exclusion is: negative EBITDA means the company isn't generating
    positive operating earnings at all -- a real weakness -- so it fails
    outright (0 points, hard_fail) and stays IN the blend like any other
    Fail, rather than being excluded/reweighted."""
    icr_is_safe = interest_coverage_ratio is not None and interest_coverage_ratio > ICR_SAFE
    cr = score_current_ratio(current_ratio, adjusted_current_ratio)
    if debt_to_ebitda is not None:
        de = score_debt_to_ebitda(debt_to_ebitda)
    else:
        de = RatioResult(
            "negative_ebitda",
            0,
            True,
            note=(
                f"Debt/EBITDA cannot be meaningfully calculated because EBITDA is negative "
                f"(TTM EBITDA is ${ebitda_ttm:,.0f}) -- the company is not generating positive "
                f"operating earnings. This is treated as a failing result, not a data gap."
            ),
        )
    # DSR keeps its own existing, unchanged ICR-only Borderline rescue --
    # it's a primary-gate INPUT to the other two frameworks below, never a
    # breach-context subject itself.
    ds = score_debt_servicing(debt_servicing_pct, icr_is_safe)

    if de.label == "borderline_fail":
        qualifies, marginal_score, signals = evaluate_debt_to_ebitda_breach_context(
            current_ratio=current_ratio,
            debt_servicing_pct=debt_servicing_pct,
            debt_to_ebitda_current=debt_to_ebitda,
            debt_to_ebitda_oldest=debt_to_ebitda_oldest,
            debt_to_ebitda_oldest_year=debt_to_ebitda_oldest_year,
            fcf_ttm=fcf_ttm,
            total_debt=total_debt,
            interest_coverage_ratio=interest_coverage_ratio,
            net_debt=net_debt,
            ebitda_ttm=ebitda_ttm,
        )
        de = (
            RatioResult("marginal_via_breach_context", marginal_score, False, saved_by_tiebreaker=True, breach_context=signals)
            if qualifies
            else de._replace(breach_context=signals)
        )

    # Only reached when the EXISTING deferred-revenue full-rescue-to-
    # Comfortable path (score_current_ratio, unchanged) already tried and
    # failed -- this is a second, later chance for the same Borderline
    # breach, not a replacement for that first one.
    if cr.label == "borderline_fail":
        qualifies, marginal_score, signals = evaluate_current_ratio_breach_context(
            debt_to_ebitda=debt_to_ebitda,
            debt_servicing_pct=debt_servicing_pct,
            current_ratio_current=adjusted_current_ratio,
            current_ratio_oldest=current_ratio_oldest,
            current_ratio_oldest_year=current_ratio_oldest_year,
            deferred_revenue=deferred_revenue,
            current_liabilities=current_liabilities,
            cash_and_equivalents=cash_and_equivalents,
            current_assets=current_assets,
            liquid_current_assets=liquid_current_assets,
        )
        cr = (
            RatioResult("marginal_via_breach_context", marginal_score, False, saved_by_tiebreaker=True, breach_context=signals)
            if qualifies
            else cr._replace(breach_context=signals)
        )

    hard_fail = cr.hard_fail or de.hard_fail or ds.hard_fail
    # cr/de's saved_by_tiebreaker can now come from the breach-context
    # framework above, independently of each other and of DSR's own
    # icr_is_safe-driven tiebreaker.
    saved_by_tiebreaker = cr.saved_by_tiebreaker or de.saved_by_tiebreaker or ds.saved_by_tiebreaker
    score = round((cr.points + de.points + ds.points) / 3)
    # See PASS_WITH_CAUTION_SCORE_CAP's comment -- a hard fail already
    # forces "Fail" regardless of score, so this only ever lowers a
    # genuine Pass-with-caution number, never a Fail's.
    if not hard_fail and saved_by_tiebreaker:
        score = min(score, PASS_WITH_CAUTION_SCORE_CAP)
    verdict = _verdict_for(score, hard_fail, saved_by_tiebreaker)
    return {
        "score": score,
        "verdict": verdict,
        "hard_fail": hard_fail,
        # Derived from the actual verdict, not re-tested independently --
        # saved_by_tiebreaker alone would say True even for the sub-70
        # fall-through-to-Fail case above (see _verdict_for).
        "pass_with_caution": verdict == "Pass with caution",
        "weights": WEIGHTS_STANDARD,
        "ratios": {
            "current_ratio": {
                "value": current_ratio,
                "adjusted_value": adjusted_current_ratio,
                "label": cr.label,
                "points": cr.points,
                "saved_by_tiebreaker": cr.saved_by_tiebreaker,
                "breach_context": cr.breach_context or None,
            },
            "debt_to_ebitda": {
                "value": debt_to_ebitda,
                "label": de.label,
                "points": de.points,
                "saved_by_tiebreaker": de.saved_by_tiebreaker,
                "breach_context": de.breach_context or None,
                "note": de.note,
            },
            "debt_servicing_ratio": {
                "value": debt_servicing_pct,
                "label": ds.label,
                "points": ds.points,
                "saved_by_tiebreaker": ds.saved_by_tiebreaker,
            },
            "interest_coverage_ratio": {
                "value": interest_coverage_ratio,
                "label": classify_interest_coverage(interest_coverage_ratio),
            },
        },
    }


def score_step5_reit(gearing_pct: float) -> dict:
    """Pure scoring function for Step 5's REIT/Property Developer path."""
    g = score_gearing(gearing_pct)
    return {
        "score": g.points,
        "verdict": _verdict_for(g.points, g.hard_fail, False),
        "hard_fail": g.hard_fail,
        "weights": WEIGHTS_REIT,
        "ratios": {
            "gearing_ratio": {"value": gearing_pct, "label": g.label, "points": g.points},
        },
    }


def score_step5_bank(cet1_pct: float, npl_pct: float) -> dict:
    """Pure scoring function for Step 5's Bank path, once both a manually-
    entered CET1 ratio and a resolved NPL ratio (manual override or the
    live compute_npl_ratio() result -- see step5_data.py) are available.
    Blends 50/50 -- CET1 (capital adequacy) and NPL (asset quality) are
    independent signals, neither doc-weighted over the other. Hard-fail
    override reuses _verdict_for unchanged; saved_by_tiebreaker is always
    False here -- no rescue mechanism exists for either ratio in v1."""
    cet1 = score_cet1(cet1_pct)
    npl = score_npl(npl_pct)
    hard_fail = cet1.hard_fail or npl.hard_fail
    score = round(cet1.points * WEIGHTS_BANK["cet1_ratio"] + npl.points * WEIGHTS_BANK["npl_ratio"])
    verdict = _verdict_for(score, hard_fail, False)
    return {
        "score": score,
        "verdict": verdict,
        "hard_fail": hard_fail,
        "weights": WEIGHTS_BANK,
        "ratios": {
            "cet1_ratio": {"value": cet1_pct, "label": cet1.label, "points": cet1.points},
            "npl_ratio": {"value": npl_pct, "label": npl.label, "points": npl.points},
        },
    }
