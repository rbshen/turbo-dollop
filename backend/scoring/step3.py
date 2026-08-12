from typing import NamedTuple

import numpy as np

from scoring.trend import RECOVERY_PATTERNS, classify_trend

# "5+ years" per valuation.md §1 -- the method-selection tree's own
# minimum window for every "consistently
# increasing" check, distinct from the 20yr projection engine's own horizon.
METHOD_SELECTION_MIN_YEARS = 5

# Step 3 of the tree: "CFO > 1.5 x Net Income?" -- both figures are the
# "current" (TTM) values per spec §2.1, not a trend check.
CFO_TO_NI_RATIO_THRESHOLD = 1.5

# The doc doesn't give a numeric bar for "aggressively" growing revenue --
# first-pass judgment call, not yet validated against a prior baseline (same
# caveat as Step 4's CCC thresholds -- see CLAUDE.md).
REVENUE_AGGRESSIVE_GROWTH_CAGR = 0.15

# A non-positive value blocks "increasing consistently" outright only if
# it's this recent (too fresh to trust as resolved); an older one falls
# through to classify_trend instead of failing immediately -- see
# _positive_and_increasing.
NEGATIVE_VALUE_RECENCY_YEARS = 3

CAPEX_NORMALIZATION_YEARS = 5

# Trailing-average window for trailing_smoothed_average (DNI_NORMALIZED's
# net_income_smoothed, and CF_NORMALIZED/FCF_NORMALIZED's cfo_smoothed/
# fcf_smoothed) -- matches CAPEX_NORMALIZATION_YEARS/METHOD_SELECTION_MIN_
# YEARS' existing "5" convention.
SMOOTHING_WINDOW_YEARS = 5


class MethodStep(NamedTuple):
    step: str
    check: str
    passed: bool | None
    detail: str


class MethodSelection(NamedTuple):
    method: str  # DCF | DFCF | DNI | DNI_NORMALIZED | PRICE_TO_BOOK | PSG | PASS
    # Which pre-computed figure step3_data.py should feed into the 20yr
    # engine as `current_value` -- None for PRICE_TO_BOOK/PSG/PASS, which
    # don't use the 20yr engine at all.
    current_value_source: str | None
    decision_trail: list[MethodStep]
    pass_reason: str | None
    # True only when method == "PASS" AND at least one step in
    # decision_trail has passed=None (a check that couldn't run at all due
    # to missing/too-thin data) -- distinguishes "we don't have enough data
    # to say" from "we checked and no method genuinely applies." Every
    # early-return branch above leaves this at its default False: a
    # None-passed step is always falsy, so it can never be the reason an
    # earlier branch's own `if x_ok:` took an early return -- a None
    # anywhere in the trail only ever coincides with falling through to the
    # final PASS below.
    insufficient_data: bool = False


def _positive_and_increasing(values: list[float] | None) -> tuple[bool | None, str]:
    """A non-positive value used to disqualify the whole series outright,
    regardless of how long ago it happened or how strong the recovery
    since -- e.g. AMZN's 2022 net loss (Rivian stake writedown) permanently
    blocked "increasing consistently" despite 3 straight years of strong
    growth since. Now only a *recent* non-positive value (within
    NEGATIVE_VALUE_RECENCY_YEARS of the most recent/TTM point) fails
    outright; an older one falls through to classify_trend, whose own
    dip-recovery patterns (small_dip_recovers / significant_dip_recovers /
    multiple_dips_resolved) can read it the same way they already read a
    dip that stayed positive -- classify_trend's percent-change math
    already treats a negative-to-positive swing as a (very) real dip on its
    own, so no separate recovery logic is needed here.

    Returns None (not False) when there's too little data to run the check
    at all -- a fetch failure or a genuinely too-thin history -- so the
    caller can tell that apart from a real computed disqualification,
    matching Step3MethodStep.passed's existing bool | None convention."""
    if not values or len(values) < METHOD_SELECTION_MIN_YEARS:
        return None, f"fewer than {METHOD_SELECTION_MIN_YEARS} years of data"

    negative_indices = [i for i, v in enumerate(values) if v <= 0]
    if negative_indices:
        years_since_negative = (len(values) - 1) - max(negative_indices)
        if years_since_negative <= NEGATIVE_VALUE_RECENCY_YEARS:
            return False, f"non-positive value within the last {NEGATIVE_VALUE_RECENCY_YEARS} years"

    trend = classify_trend(values)
    if trend.pattern in RECOVERY_PATTERNS:
        return True, f"trend pattern '{trend.pattern}'"
    return False, f"trend pattern '{trend.pattern}' does not read as consistently increasing"


_MAX_NAMED_PERIODS_IN_DETAIL = 3


def _fcf_positive_and_consistent(
    fcf_values: list[float] | None, period_labels: list[str] | None = None
) -> tuple[bool | None, str]:
    """Brought in line with _positive_and_increasing's trend-aware
    tolerance -- previously the one remaining check in select_method
    reading "consistent" as a pure floor (all-positive across the whole
    window), which permanently blocked a durably recovered old dip (e.g.
    AMD's FY2017/2018, since fully recovered to $8.57B TTM FCF) the same
    way _positive_and_increasing used to for CFO/Net Income before
    e0af903. A non-positive value still fails outright if it's recent
    (within NEGATIVE_VALUE_RECENCY_YEARS of the most recent/TTM point);
    an older one falls through to classify_trend, same as
    _positive_and_increasing. `period_labels`, when supplied and aligned
    1:1 with fcf_values, names the actual recent offending period(s) in
    the failure detail instead of a generic message.

    Returns None (not False) when there's too little data to run the check
    at all, same convention and rationale as _positive_and_increasing."""
    if not fcf_values or len(fcf_values) < METHOD_SELECTION_MIN_YEARS:
        return None, f"fewer than {METHOD_SELECTION_MIN_YEARS} years of data"
    if all(v > 0 for v in fcf_values):
        return True, "positive in every year of the window"

    negative_indices = [i for i, v in enumerate(fcf_values) if v <= 0]
    years_since_negative = (len(fcf_values) - 1) - max(negative_indices)
    if years_since_negative <= NEGATIVE_VALUE_RECENCY_YEARS:
        recent_indices = [
            i for i in negative_indices if (len(fcf_values) - 1) - i <= NEGATIVE_VALUE_RECENCY_YEARS
        ]
        if period_labels is not None and len(period_labels) == len(fcf_values):
            offending = [period_labels[i] for i in recent_indices]
            named = ", ".join(offending[:_MAX_NAMED_PERIODS_IN_DETAIL])
            remaining = len(offending) - _MAX_NAMED_PERIODS_IN_DETAIL
            if remaining > 0:
                named += f" and {remaining} more"
            return False, f"{named} non-positive within the last {NEGATIVE_VALUE_RECENCY_YEARS} years"
        return False, f"non-positive value within the last {NEGATIVE_VALUE_RECENCY_YEARS} years"

    trend = classify_trend(fcf_values)
    if trend.pattern in RECOVERY_PATTERNS:
        return True, f"trend pattern '{trend.pattern}'"
    return False, f"trend pattern '{trend.pattern}' does not read as consistently increasing"


def normalize_fcf(cfo_series: list[float], capex_series: list[float]) -> list[float] | None:
    """Spec step 3's fallback: replace each year's actual CapEx with the
    trailing N-year average CapEx (FMP reports capitalExpenditure as already
    negative, so FCF = CFO + capex without double-subtracting), then re-test
    positive-and-consistent on the resulting series."""
    if len(capex_series) < 1 or len(cfo_series) != len(capex_series):
        return None
    window = capex_series[-CAPEX_NORMALIZATION_YEARS:]
    avg_capex = sum(window) / len(window)
    return [cfo + avg_capex for cfo in cfo_series]


def trailing_smoothed_average(
    clean_series: list[float], ttm_period_duplicates_last_fy: bool, window: int = SMOOTHING_WINDOW_YEARS
) -> float | None:
    """Multi-year trailing average behind DNI_NORMALIZED's net_income_smoothed
    and CF_NORMALIZED/FCF_NORMALIZED's cfo_smoothed/fcf_smoothed. `clean_series`
    is chronological, no gaps, TTM appended last -- the same net_income_clean/
    cfo_clean/fcf_clean shape step3_data.py already builds for the
    method-selection tree.

    When `ttm_period_duplicates_last_fy` is True (see
    helpers.ttm.is_ttm_period_duplicate_of_last_fy), TTM and the last annual
    point describe the identical underlying period -- averaging both,
    unadjusted, counts that one period twice in a `window`-point average
    while every other period counts once. Dropping TTM in this case and
    averaging the prior `window` distinct fiscal years instead keeps the
    window at a true `window` points, not `window - 1`. Confirmed real case
    (2026-08-08 investigation): SNDK's FY2026 memory-supercycle Net Income
    ($11.4B, more than the prior 4 years combined) was being counted at 2/5
    weight instead of the intended 1/5 -- see CLAUDE.md.

    Falls back to including TTM (the un-deduplicated `window`-point average)
    if dropping it would leave fewer than 2 points to average -- same "never
    make a metric less scoreable" guard step4.py's own
    recovery_excluded_prefix_length uses for its dip-recovery exclusion; not
    currently reachable (every ticker hitting the duplicate condition today
    has 5+ years of history) but cheap insurance for a thin-history ticker."""
    if not clean_series:
        return None
    series = clean_series[:-1] if ttm_period_duplicates_last_fy and len(clean_series) - 1 >= 2 else clean_series
    window_slice = series[-window:]
    return sum(window_slice) / len(window_slice)


def _revenue_growing_aggressively(revenue_series: list[float] | None) -> tuple[bool | None, str]:
    """CAGR from the earliest *positive*-revenue year to TTM -- not simply
    index 0, since a recently-IPO'd or pre-production company (e.g. RIVN:
    $0 revenue in its earliest two reported years, then $55M -> $5.4B) would
    otherwise poison the base and read as "not positive" despite genuinely
    aggressive growth.

    Returns None (not False) for the insufficient-history case only -- "not
    positive across the window" below is a genuine business fact given
    enough real history, not a data gap, so it stays a real False."""
    if not revenue_series or len(revenue_series) < 2:
        return None, "insufficient revenue history"
    positive_from = next((i for i, v in enumerate(revenue_series) if v > 0), None)
    if positive_from is None or positive_from == len(revenue_series) - 1:
        return False, "revenue not positive across the window"
    base, current = revenue_series[positive_from], revenue_series[-1]
    years = len(revenue_series) - 1 - positive_from
    if current <= 0:
        return False, "revenue not positive across the window"
    cagr = (current / base) ** (1 / years) - 1
    if cagr >= REVENUE_AGGRESSIVE_GROWTH_CAGR:
        return True, f"revenue CAGR {cagr:.1%} over {years}y meets the {REVENUE_AGGRESSIVE_GROWTH_CAGR:.0%} bar"
    return False, f"revenue CAGR {cagr:.1%} over {years}y is below the {REVENUE_AGGRESSIVE_GROWTH_CAGR:.0%} bar"


def select_method(
    company_type: str,
    cfo_series: list[float] | None,
    cfo_ttm: float | None,
    net_income_series: list[float] | None,
    net_income_ttm: float | None,
    fcf_series: list[float] | None,
    capex_series: list[float] | None,
    revenue_series: list[float] | None,
    fcf_period_labels: list[str] | None = None,
) -> MethodSelection:
    """Pure implementation of valuation.md §1's method-selection tree. All
    series are chronological (oldest first,
    ending TTM); *_ttm are the single "current" figures per spec §2.1.
    No I/O -- step3_data.py sources every input from FMP/Step 1/Step 2.
    `fcf_period_labels`, when supplied, must align 1:1 with both fcf_series
    and cfo_series/capex_series -- step3_data.py builds fcf_clean and
    cfo_clean/capex_clean from the same non-None filter, so one label list
    correctly names periods for both the [3a] raw-FCF check and the [3b]
    normalized-FCF check."""
    trail: list[MethodStep] = []

    # 1. Company type check.
    if company_type in ("Bank", "REIT/Property Developer"):
        trail.append(MethodStep("1", "Bank / REIT / Property Developer?", True, f"company_type={company_type}"))
        return MethodSelection("PRICE_TO_BOOK", None, trail, None)
    trail.append(MethodStep("1", "Bank / REIT / Property Developer?", False, f"company_type={company_type}"))

    # 1a. Insurance skips the CFO-based method family entirely (steps
    # 2/3/3a/3b below) -- claim timing, reserve movements, and investment
    # portfolio fluctuations make OCF unreliable for insurers (same
    # reasoning already applied to Step 1's CFO de-emphasis), so a DCF/DFCF
    # selection here would be building on a noisy signal the framework
    # explicitly distrusts for this company type. Insurance still falls
    # through to the existing Net Income check (step 4) and its own
    # DNI -> DNI_NORMALIZED -> PSG -> PASS fallback chain unchanged --
    # deliberately NOT forced to DNI unconditionally, since that would
    # fabricate a value for a distressed insurer with genuinely
    # insufficient NI history (inconsistent with this app's established
    # insufficient-data conventions elsewhere).
    if company_type == "Insurance":
        trail.append(
            MethodStep(
                "1a",
                "Insurance — cash-flow-based methods skipped?",
                True,
                "OCF unreliable for insurers (claim timing, reserve movements, investment portfolio fluctuations)",
            )
        )
    else:
        # 2. Cash flow quality check.
        cfo_ok, cfo_detail = _positive_and_increasing(cfo_series)
        trail.append(MethodStep("2", "CFO positive and increasing consistently (5+ yrs)?", cfo_ok, cfo_detail))

        if cfo_ok:
            # 3. CFO vs Net Income check.
            if cfo_ttm is None or net_income_ttm is None:
                trail.append(MethodStep("3", "CFO > 1.5x Net Income?", None, "missing current CFO or Net Income"))
            else:
                ratio_ok = cfo_ttm > CFO_TO_NI_RATIO_THRESHOLD * net_income_ttm
                trail.append(
                    MethodStep(
                        "3",
                        "CFO > 1.5x Net Income?",
                        ratio_ok,
                        f"CFO={cfo_ttm:,.0f} vs 1.5x NI={CFO_TO_NI_RATIO_THRESHOLD * net_income_ttm:,.0f}",
                    )
                )
                if not ratio_ok:
                    return MethodSelection("DCF", "cfo_ttm", trail, None)

                fcf_ok, fcf_detail = _fcf_positive_and_consistent(fcf_series, fcf_period_labels)
                trail.append(MethodStep("3a", "FCF (CFO - CapEx) positive and consistent?", fcf_ok, fcf_detail))
                if fcf_ok:
                    return MethodSelection("DFCF", "fcf_ttm", trail, None)

                normalized = (
                    normalize_fcf(cfo_series, capex_series) if cfo_series is not None and capex_series is not None else None
                )
                norm_ok, norm_detail = _fcf_positive_and_consistent(normalized, fcf_period_labels)
                trail.append(
                    MethodStep(
                        "3b",
                        f"FCF normalized with {CAPEX_NORMALIZATION_YEARS}yr avg CapEx now positive and consistent?",
                        norm_ok,
                        norm_detail,
                    )
                )
                if norm_ok:
                    return MethodSelection("DFCF", "fcf_normalized", trail, None)
                # Falls through to step 4, same as the "NO" branch when CFO
                # itself fails the quality check.

    # 4. Net income check.
    ni_ok, ni_detail = _positive_and_increasing(net_income_series)
    trail.append(MethodStep("4", "Net Income increasing consistently (5+ yrs)?", ni_ok, ni_detail))
    if ni_ok:
        return MethodSelection("DNI", "net_income_ttm", trail, None)

    profitable_now = None if net_income_ttm is None else net_income_ttm > 0
    trail.append(MethodStep("4a", "Profitable but inconsistent?", profitable_now, f"TTM Net Income={net_income_ttm}"))
    if profitable_now and net_income_series:
        window = net_income_series[-METHOD_SELECTION_MIN_YEARS:]
        smoothed = sum(window) / len(window)
        if smoothed > 0:
            trail.append(MethodStep("4a-1", "Smoothed Net Income positive?", True, f"avg of last {len(window)}y = {smoothed:,.0f}"))
            return MethodSelection("DNI_NORMALIZED", "net_income_smoothed", trail, None)
        trail.append(MethodStep("4a-1", "Smoothed Net Income positive?", False, f"avg of last {len(window)}y = {smoothed:,.0f}"))

    # 5. Unprofitable company.
    growing, growth_detail = _revenue_growing_aggressively(revenue_series)
    trail.append(MethodStep("5", "Revenue growing aggressively?", growing, growth_detail))
    if growing:
        return MethodSelection("PSG", None, trail, None)

    return MethodSelection(
        "PASS",
        None,
        trail,
        "No valuation method in the tree applies to this company's data.",
        insufficient_data=any(step.passed is None for step in trail),
    )


def compute_capm(risk_free_rate: float, market_risk_premium: float, beta: float) -> dict:
    """Direct linear CAPM -- deliberately NOT bucketed to the workbook's own
    0.1-increment beta reference table, which spec §5 states is a manual
    reference only, not formula-linked. Beta < 0.8 flows through unchanged
    (not floored), flagged via beta_outside_reference_range for the UI."""
    return {
        "discount_rate": risk_free_rate + beta * market_risk_premium,
        "risk_free_rate": risk_free_rate,
        "market_risk_premium": market_risk_premium,
        "beta": beta,
        "beta_outside_reference_range": beta < 0.8,
    }


# First-pass ±10% band, not yet validated against a prior baseline (same
# caveat as REVENUE_AGGRESSIVE_GROWTH_CAGR above) -- easy to retune later.
VALUATION_UNDERVALUED_THRESHOLD = -0.10
VALUATION_OVERVALUED_THRESHOLD = 0.10


def classify_valuation_verdict(discount_premium_pct: float | None) -> str | None:
    if discount_premium_pct is None:
        return None
    if discount_premium_pct <= VALUATION_UNDERVALUED_THRESHOLD:
        return "undervalued"
    if discount_premium_pct >= VALUATION_OVERVALUED_THRESHOLD:
        return "overvalued"
    return "fair"


def _discount_premium_pct(last_close: float | None, intrinsic_value_per_share: float | None) -> float | None:
    if not last_close or not intrinsic_value_per_share:
        return None
    return last_close / intrinsic_value_per_share - 1


# --- Additive, informational-only fields (never change verdict/score) ------
# The framework's own buy signal for Bank/REIT P/B (never wired into
# classify_valuation_verdict above, which keeps its existing mean+-10% read
# unchanged) -- "price at/below -1 SD of historical average P/B". The -1SD
# value itself already exists as pb_bands.minus_1sd (bands_from_mean_sd
# computes all 5 unconditionally); this just names the comparison.
def historical_pb_buy_signal(last_close: float | None, minus_1sd_iv_per_share: float | None) -> bool | None:
    if last_close is None or minus_1sd_iv_per_share is None:
        return None
    return last_close <= minus_1sd_iv_per_share


# Fixed sanity-range benchmarks from the framework, surfaced as context next
# to the ticker-specific historical mean/SD bands -- never used to gate or
# adjust the actual P/B calculation. REIT's upper bound is conditionally
# 1.5 "given high double-digit DPU growth" per the framework -- that
# condition is judged qualitatively by whoever reads the DPU growth note
# alongside this, not automated into a second numeric threshold here.
BANK_PB_BENCHMARK_LOW = 1.2
BANK_PB_BENCHMARK_HIGH = 1.4
REIT_PB_BENCHMARK_FAIR_MAX = 1.2
REIT_PB_BENCHMARK_STRETCH_MAX = 1.5


class PbBenchmark(NamedTuple):
    low: float | None
    high: float | None
    note: str | None


def pb_benchmark_for(company_type: str) -> PbBenchmark | None:
    if company_type == "Bank":
        return PbBenchmark(BANK_PB_BENCHMARK_LOW, BANK_PB_BENCHMARK_HIGH, None)
    if company_type == "REIT/Property Developer":
        return PbBenchmark(
            None,
            REIT_PB_BENCHMARK_FAIR_MAX,
            f"Up to {REIT_PB_BENCHMARK_STRETCH_MAX} is acceptable given high double-digit DPU growth.",
        )
    return None


# REIT Dividend/DPU Yield check. Sourced from ratios_annual's dividendYield
# field, already fetched by step3_data.py for the P/B lookback -- no new FMP
# call needed. `threshold_pct` is now Settings-configurable (2026-08-13) --
# see helpers/reit_dividend_yield_config.py for the default (5.0) and the
# get-or-create DB row step3_data.py fetches and passes in here.


def dividend_yield_meets_reit_threshold(dividend_yield_pct: float | None, threshold_pct: float) -> bool | None:
    if dividend_yield_pct is None:
        return None
    return dividend_yield_pct >= threshold_pct


def dpu_growth_note(dpu_per_share: list[float]) -> str | None:
    """Simple last-vs-first read over the dividendPerShare annual series --
    the same "last >= first" bar Step 4 uses for its own negative-equity Net
    Income substitute (see scoring/step4.py::_net_income_consistent_and_
    positive), not a full trend classifier, since the framework's own
    language ("consistently growing or stable") is qualitative. None when
    there's too little data to say anything."""
    valid = [v for v in dpu_per_share if v is not None]
    if len(valid) < 2:
        return None
    first, last = valid[0], valid[-1]
    if last >= first:
        return f"DPU/share grew from {first:.2f} to {last:.2f} over the reporting window."
    return f"DPU/share declined from {first:.2f} to {last:.2f} over the reporting window."


# Loss-making Standard company PB reference (spec's Method B, "Liquidation
# Method") -- last resort, informational only, never a scored method
# select_method's own tree can return. step3_data.py gates this to
# company_type == "Standard" and selection.method == "PASS" and a genuinely
# negative TTM Net Income -- see its own call site for why selection.method
# == "PASS" specifically (not just "loss-making"): a Standard company can
# have negative Net Income yet still resolve to a real method (DCF/DFCF via
# the CFO-based branch, which never looks at Net Income at all), in which
# case this reference would be actively misleading.
LOSS_MAKING_PB_BARGAIN_THRESHOLD = 0.50


def loss_making_pb_reference_note(current_pb_ratio: float | None, book_value_per_share: float | None) -> str | None:
    if current_pb_ratio is None or book_value_per_share is None:
        return None
    if book_value_per_share <= 0:
        # Negative tangible book value (post-Piece-1: totalAssets -
        # goodwillAndIntangibleAssets - totalLiabilities can go negative for
        # a heavily-leveraged or goodwill-heavy company, e.g. GPN) means
        # liquidation wouldn't even cover liabilities -- the opposite of
        # what this note is meant to convey ("cheap relative to a positive
        # liquidation value"). No note is more honest than a nonsensical
        # negative-PB "bargain" reference.
        return None
    return (
        "This company has negative TTM earnings, so standard valuation methods (DCF/DNI) "
        "don't apply. As a rough reference: if this stock's Price-to-Book ratio is at or "
        f"below {LOSS_MAKING_PB_BARGAIN_THRESHOLD:.2f}x, it may represent a potential bargain "
        "even at liquidation value — but this is not a fair-value estimate, just a reference "
        f"point. Current PB: {current_pb_ratio:.2f}x (Book Value/Share: ${book_value_per_share:.2f}). "
        "To value this ticker using the Price-to-Book method directly, use Manual Calculation."
    )


class TwentyYearEngineResult(NamedTuple):
    intrinsic_value_per_share: float
    discount_premium_pct: float | None
    pv_sum: float


def run_20yr_engine(
    current_value: float,
    growth_yr_1_5: float,
    growth_yr_6_10: float,
    growth_yr_11_20: float,
    discount_rate: float,
    shares_outstanding: float,
    total_debt: float,
    cash_and_st_investments: float,
    fx_rate: float,
    last_close: float | None,
) -> TwentyYearEngineResult:
    """Spec §2.2-2.4's shared 20yr projection/discount/roll-up engine --
    identical math for DCF/DFCF/DNI, differing only in what `current_value`
    represents (see §2.5's method-specific labels, handled by the caller).
    Cross-checked cell-for-cell against the spec's own MSFT DFCF worked
    example in the source workbook (PV sum, IV/share, discount %)."""
    growth_rates = np.concatenate(
        [np.full(5, growth_yr_1_5), np.full(5, growth_yr_6_10), np.full(10, growth_yr_11_20)]
    )
    cumulative_growth = np.cumprod(1 + growth_rates)
    projected_values = current_value * cumulative_growth

    years = np.arange(1, 21)
    discount_factors = 1 / (1 + discount_rate) ** years
    discounted_values = projected_values * discount_factors

    pv_sum = float(discounted_values.sum())
    intrinsic_value_pre_adj = pv_sum / shares_outstanding
    less_debt_per_share = total_debt / shares_outstanding
    plus_cash_per_share = cash_and_st_investments / shares_outstanding
    intrinsic_value_per_share = intrinsic_value_pre_adj - less_debt_per_share + plus_cash_per_share
    final_iv_per_share = intrinsic_value_per_share * fx_rate

    return TwentyYearEngineResult(
        intrinsic_value_per_share=final_iv_per_share,
        discount_premium_pct=_discount_premium_pct(last_close, final_iv_per_share),
        pv_sum=pv_sum,
    )


class PriceToBookResult(NamedTuple):
    mean_pb: float
    sd_pb: float
    bands: dict  # "minus_2sd"/"minus_1sd"/"mean"/"plus_1sd"/"plus_2sd" -> IV per share
    discount_premium_pct: float | None


def bands_from_mean_sd(
    book_value_per_share: float,
    mean_pb: float,
    sd_pb: float,
    fx_rate: float,
    last_close: float | None,
) -> PriceToBookResult:
    """Spec §3.2's 5-band roll-up, factored out of `run_price_to_book` so a
    caller that already has (or wants to directly supply) a mean/SD P/B
    pair -- e.g. Manual Calculation's what-if panel -- doesn't need to hand
    in a full historical-ratio array just to get the same bands.

    Note: the source workbook's own "VMI IV Calculator (Mean PB)" sheet has
    a labeling bug on its minus-side band columns -- its "Mean - 1 SD"
    column actually holds the 2SD-away value and vice versa (confirmed
    against JPM's worked example: mean=1.752, SD=0.213002, and the column
    labeled "-1 SD" holds 1.325995 = mean - 2*SD, not mean - SD). The plus
    side is correctly ordered. This implementation follows the spec's
    literal formula (mathematically correct), not the workbook's own
    mislabeled minus-side columns."""
    pb_bands = {
        "minus_2sd": mean_pb - 2 * sd_pb,
        "minus_1sd": mean_pb - 1 * sd_pb,
        "mean": mean_pb,
        "plus_1sd": mean_pb + 1 * sd_pb,
        "plus_2sd": mean_pb + 2 * sd_pb,
    }
    iv_bands = {label: pb * book_value_per_share * fx_rate for label, pb in pb_bands.items()}

    return PriceToBookResult(
        mean_pb=mean_pb,
        sd_pb=sd_pb,
        bands=iv_bands,
        discount_premium_pct=_discount_premium_pct(last_close, iv_bands["mean"]),
    )


def run_price_to_book(
    book_value_per_share: float,
    historical_pb_ratios: list[float],
    lookback: str,
    fx_rate: float,
    last_close: float | None,
) -> PriceToBookResult:
    """Spec §3.2's 5-band mean/SD engine. `historical_pb_ratios` must be
    chronological (oldest first) -- "last N entries" means the N most
    recent. Uses sample stdev (ddof=1, matching Excel's STDEV.S)."""
    window = historical_pb_ratios[-5:] if lookback == "5 years" else historical_pb_ratios[-10:]
    arr = np.asarray(window, dtype=float)
    mean_pb = float(arr.mean())
    sd_pb = float(arr.std(ddof=1))
    return bands_from_mean_sd(book_value_per_share, mean_pb, sd_pb, fx_rate, last_close)


class PSGResult(NamedTuple):
    intrinsic_value_per_share: float
    current_psg_ratio: float | None
    discount_premium_pct: float | None


def run_psg(
    sales_per_share: float,
    projected_growth_rate: float,
    fair_psg_ratio: float,
    fx_rate: float,
    last_close: float | None,
) -> PSGResult:
    """Spec §4.2 -- note the literal `* 100`: growth is expressed as a
    percentage number inside this specific formula, not a decimal fraction."""
    intrinsic_value_per_share = fair_psg_ratio * sales_per_share * projected_growth_rate * 100
    final_iv_per_share = intrinsic_value_per_share * fx_rate

    current_psg_ratio = (
        last_close / sales_per_share / (projected_growth_rate * 100)
        if last_close is not None and sales_per_share and projected_growth_rate
        else None
    )

    return PSGResult(
        intrinsic_value_per_share=final_iv_per_share,
        current_psg_ratio=current_psg_ratio,
        discount_premium_pct=_discount_premium_pct(last_close, final_iv_per_share),
    )


# CF_NORMALIZED/FCF_NORMALIZED share the exact same 20yr-engine math as
# DCF/DFCF -- only current_value's source differs (cfo_smoothed/
# fcf_smoothed instead of cfo_ttm/fcf_ttm, computed by step3_data.py).
# select_method never returns either -- they're Manual Calculation/Custom
# Valuation-only method choices (see CLAUDE.md's Item 3 note), included
# here so run_manual_calculation/run_manual_calculation_from_params accept
# them.
_TWENTY_YEAR_METHODS = {"DCF", "DFCF", "DNI", "DNI_NORMALIZED", "CF_NORMALIZED", "FCF_NORMALIZED"}


class ManualCalculationResult(NamedTuple):
    intrinsic_value_per_share: float | None
    pb_bands: dict | None
    discount_premium_pct: float | None
    verdict: str | None
    error: str | None


def run_manual_calculation(
    method: str,
    current_value: float | None,
    growth_yr_1_5: float | None,
    growth_yr_6_10: float | None,
    growth_yr_11_20: float | None,
    discount_rate: float | None,
    shares_outstanding: float | None,
    total_debt: float | None,
    cash_and_st_investments: float | None,
    book_value_per_share: float | None,
    pb_mean_ratio: float | None,
    pb_sd_ratio: float | None,
    sales_per_share: float | None,
    projected_growth_rate: float | None,
    fair_psg_ratio: float | None,
    last_close: float | None,
) -> ManualCalculationResult:
    """Manual Calculation's what-if engine -- a pure function over
    caller-supplied inputs (the Manual Calculation UI panel, pre-filled
    from live Auto Calculation data and then user-edited), reusing the same
    engines `get_step3_data` uses for the automatic answer rather than
    duplicating any of this math a third time. `fx_rate` fixed at 1.0 --
    not because this app is USD-only (it isn't -- see CLAUDE.md's non-USD
    currency conversion investigation), but because every monetary figure
    reaching this function is already USD by construction: `get_step3_data`
    converts each raw figure to USD once, upfront, right after pulling it
    from FMP, before it ever lands in `Step3Inputs` (Manual Calculation's
    pre-fill source) or a saved `TickerCustomValuation`'s parameters. A
    user editing a pre-filled value in the UI is always editing a USD
    number, never a local-currency one, so there's nothing left for this
    function itself to convert. No I/O: `last_close` is supplied by the
    caller (already available from the live Auto Calculation fetch) rather
    than re-fetched here."""
    fx_rate = 1.0

    if method in _TWENTY_YEAR_METHODS:
        if None in (current_value, growth_yr_1_5, growth_yr_6_10, growth_yr_11_20, discount_rate, shares_outstanding, total_debt, cash_and_st_investments):
            return ManualCalculationResult(None, None, None, None, f"Missing required inputs for {method}")
        engine_result = run_20yr_engine(
            current_value=current_value,
            growth_yr_1_5=growth_yr_1_5,
            growth_yr_6_10=growth_yr_6_10,
            growth_yr_11_20=growth_yr_11_20,
            discount_rate=discount_rate,
            shares_outstanding=shares_outstanding,
            total_debt=total_debt,
            cash_and_st_investments=cash_and_st_investments,
            fx_rate=fx_rate,
            last_close=last_close,
        )
        return ManualCalculationResult(
            engine_result.intrinsic_value_per_share,
            None,
            engine_result.discount_premium_pct,
            classify_valuation_verdict(engine_result.discount_premium_pct),
            None,
        )

    if method == "PRICE_TO_BOOK":
        if None in (book_value_per_share, pb_mean_ratio, pb_sd_ratio):
            return ManualCalculationResult(None, None, None, None, "Missing required inputs for PRICE_TO_BOOK")
        pb_result = bands_from_mean_sd(book_value_per_share, pb_mean_ratio, pb_sd_ratio, fx_rate, last_close)
        return ManualCalculationResult(
            pb_result.bands["mean"],
            pb_result.bands,
            pb_result.discount_premium_pct,
            classify_valuation_verdict(pb_result.discount_premium_pct),
            None,
        )

    if method == "PSG":
        if None in (sales_per_share, projected_growth_rate, fair_psg_ratio):
            return ManualCalculationResult(None, None, None, None, "Missing required inputs for PSG")
        psg_result = run_psg(
            sales_per_share=sales_per_share,
            projected_growth_rate=projected_growth_rate,
            fair_psg_ratio=fair_psg_ratio,
            fx_rate=fx_rate,
            last_close=last_close,
        )
        return ManualCalculationResult(
            psg_result.intrinsic_value_per_share,
            None,
            psg_result.discount_premium_pct,
            classify_valuation_verdict(psg_result.discount_premium_pct),
            None,
        )

    return ManualCalculationResult(None, None, None, None, f"Unknown method: {method}")
