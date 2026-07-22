from typing import NamedTuple

import numpy as np

from scoring.trend import classify_trend

# "5+ years" per step6_intrinsic_value_calculation_prompt.md §1 -- the
# method-selection tree's own minimum window for every "consistently
# increasing" check, distinct from the 20yr projection engine's own horizon.
METHOD_SELECTION_MIN_YEARS = 5

# Step 3 of the tree: "CFO > 1.5 x Net Income?" -- both figures are the
# "current" (TTM) values per spec §2.1, not a trend check.
CFO_TO_NI_RATIO_THRESHOLD = 1.5

# classify_trend patterns that read as "increasing consistently" for method-
# selection purposes -- lenient by design (a resolved dip still counts),
# reusing Step 1's already-computed trend classification per the feature
# brief's explicit instruction, rather than reimplementing trend detection.
_CONSISTENTLY_INCREASING_PATTERNS = {
    "grows_every_year",
    "small_dip_recovers",
    "significant_dip_recovers",
    "multiple_dips_resolved",
}

# The doc doesn't give a numeric bar for "aggressively" growing revenue --
# first-pass judgment call, not yet validated against a prior baseline (same
# caveat as Step 4's CCC thresholds -- see CLAUDE.md).
REVENUE_AGGRESSIVE_GROWTH_CAGR = 0.15

CAPEX_NORMALIZATION_YEARS = 5


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


def _positive_and_increasing(values: list[float] | None) -> tuple[bool, str]:
    if not values or len(values) < METHOD_SELECTION_MIN_YEARS:
        return False, f"fewer than {METHOD_SELECTION_MIN_YEARS} years of data"
    if any(v <= 0 for v in values):
        return False, "not positive throughout the window"
    trend = classify_trend(values)
    if trend.pattern in _CONSISTENTLY_INCREASING_PATTERNS:
        return True, f"positive throughout, trend pattern '{trend.pattern}'"
    return False, f"trend pattern '{trend.pattern}' does not read as consistently increasing"


def _fcf_positive_and_consistent(fcf_values: list[float] | None) -> tuple[bool, str]:
    """Stricter than Step 1's own FCF scoring tiers (which award partial
    credit for an isolated dip) -- this is a binary eligibility gate for
    method selection, not a point-scoring rubric, so "consistent" is read
    literally as all-positive across the window."""
    if not fcf_values or len(fcf_values) < METHOD_SELECTION_MIN_YEARS:
        return False, f"fewer than {METHOD_SELECTION_MIN_YEARS} years of data"
    if all(v > 0 for v in fcf_values):
        return True, "positive in every year of the window"
    return False, "at least one non-positive year in the window"


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


def _revenue_growing_aggressively(revenue_series: list[float] | None) -> tuple[bool, str]:
    """CAGR from the earliest *positive*-revenue year to TTM -- not simply
    index 0, since a recently-IPO'd or pre-production company (e.g. RIVN:
    $0 revenue in its earliest two reported years, then $55M -> $5.4B) would
    otherwise poison the base and read as "not positive" despite genuinely
    aggressive growth."""
    if not revenue_series or len(revenue_series) < 2:
        return False, "insufficient revenue history"
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
) -> MethodSelection:
    """Pure implementation of step6_intrinsic_value_calculation_prompt.md
    §1's method-selection tree. All series are chronological (oldest first,
    ending TTM); *_ttm are the single "current" figures per spec §2.1.
    No I/O -- step3_data.py sources every input from FMP/Step 1/Step 2."""
    trail: list[MethodStep] = []

    # 1. Company type check.
    if company_type in ("Bank", "REIT/Property Developer"):
        trail.append(MethodStep("1", "Bank / REIT / Property Developer?", True, f"company_type={company_type}"))
        return MethodSelection("PRICE_TO_BOOK", None, trail, None)
    trail.append(MethodStep("1", "Bank / REIT / Property Developer?", False, f"company_type={company_type}"))

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

            fcf_ok, fcf_detail = _fcf_positive_and_consistent(fcf_series)
            trail.append(MethodStep("3a", "FCF (CFO - CapEx) positive and consistent?", fcf_ok, fcf_detail))
            if fcf_ok:
                return MethodSelection("DFCF", "fcf_ttm", trail, None)

            normalized = (
                normalize_fcf(cfo_series, capex_series) if cfo_series is not None and capex_series is not None else None
            )
            norm_ok, norm_detail = _fcf_positive_and_consistent(normalized)
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

    profitable_now = net_income_ttm is not None and net_income_ttm > 0
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

    return MethodSelection("PASS", None, trail, "No valuation method in the tree applies to this company's data.")


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


def run_price_to_book(
    book_value_per_share: float,
    historical_pb_ratios: list[float],
    lookback: str,
    fx_rate: float,
    last_close: float | None,
) -> PriceToBookResult:
    """Spec §3.2's 5-band mean/SD engine. `historical_pb_ratios` must be
    chronological (oldest first) -- "last N entries" means the N most
    recent. Uses sample stdev (ddof=1, matching Excel's STDEV.S).

    Note: the source workbook's own "VMI IV Calculator (Mean PB)" sheet has
    a labeling bug on its minus-side band columns -- its "Mean - 1 SD"
    column actually holds the 2SD-away value and vice versa (confirmed
    against JPM's worked example: mean=1.752, SD=0.213002, and the column
    labeled "-1 SD" holds 1.325995 = mean - 2*SD, not mean - SD). The plus
    side is correctly ordered. This implementation follows the spec's
    literal formula (mathematically correct), not the workbook's own
    mislabeled minus-side columns."""
    window = historical_pb_ratios[-5:] if lookback == "5 years" else historical_pb_ratios[-10:]
    arr = np.asarray(window, dtype=float)
    mean_pb = float(arr.mean())
    sd_pb = float(arr.std(ddof=1))

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
