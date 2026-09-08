"""Pure gate/derivation logic for the "Speculative Growth" classification --
a new, independent, read-only lens layered on top of the existing 5-step
framework (Financials/Growth Rate/Profitability/Debt/Moat -> Overall
Assessment). Never touches Step1-5 scoring or overall.py: a ticker can be
Overall=Fail and Speculative Growth=Yes simultaneously, which is the
expected, correct outcome, not a contradiction to reconcile.

Gate model (all four must pass for `qualifies`), per the design/
investigation phase's resolved criteria set:
  - company_type == "Standard" (reuses scoring/classification.py as-is)
  - Moat is Narrow, Wide, or a *confirmed* No Moat rating (unset/never-rated
    still excludes) -- see `_MOAT_QUALIFYING` below.
  - Step2's forward growth rate clears GROWTH_GATE_MIN_PCT
  - NI was negative in a majority of tracked annual+TTM periods (see
    `is_not_durably_profitable` below) -- added 2026-08-15 after a false-
    positive investigation confirmed mature, thoroughly profitable
    wide/narrow-moat names (MSFT, ABNB, APH, MA, TSM, AVGO, ANET) were
    qualifying purely on Moat+Growth, with profitability never gating
    anything. See CLAUDE.md's Speculative Growth section for the full
    investigation and the numbers behind this gate's exact shape.

Everything else (trailing growth, gross margin, CFO sign, CFO direction,
cash runway, PSG, potential fake growth) is informational only and never
affects `qualifies` -- a ticker can be Speculative Growth and expensive
(PSG > 1) at the same time.
"""

from typing import NamedTuple

from scoring.step2 import MAGNITUDE_HIGH as GROWTH_GATE_MIN_PCT

# Informational-only secondary growth check (trailing TTM-vs-last-FY revenue
# growth) -- a supporting data point shown alongside the pill, never a gate
# on its own. See CLAUDE.md's Speculative Growth investigation: real
# speculative-growth names (RKLB 27.8%, SOUN 20.3%) frequently sit well
# below the spec's literal ">100%" framing, so this is deliberately not a
# gate -- forward-looking Step2 growth (the actual hard gate above) is what
# the market prices these names on, not trailing growth.
TRAILING_GROWTH_INFORMATIONAL_PCT = 20.0

# PSG (Price/Sales / Revenue Growth %) reference line -- informational only,
# not a gate (a name can be genuinely Speculative Growth and expensive at
# the same time, e.g. RKLB's PSG of ~2.17 in the investigation). Resolved to
# <=1 (not the spec's alternate <=0.20) via real-data validation: with
# growth expressed as a whole-number percent (this codebase's own
# convention), <=0.20 failed all 5 investigation spot-check tickers, while
# <=1 correctly separated RKLB (rich, fails) from IONQ/SOUN/ACHR/JOBY
# (reasonable, pass).
PSG_REASONABLE_MAX = 1.0

_MOAT_QUALIFYING = {"narrow_moat", "wide_moat", "no_moat"}
# "no_moat" added 2026-09-08, following the no_moat-gate investigation (see
# CLAUDE.md): the original spec described "narrow/no-moat-yet" as a defining
# trait of the category, but the shipped gate only ever passed Narrow/Wide.
# Deliberately only the *confirmed* rating -- a real TickerMoat row a human
# has actually set to "no_moat" -- not an unset/never-rated ticker, which
# still reads as `moat=None`, still fails this `in` check, and is untouched
# by this change. Universe-wide validation (572 tickers) confirmed this adds
# exactly 7 new qualifiers (AAOI, BE, CRWV, IREN, MRNA, SNOW, SYM) with the
# existing 14 qualifiers unaffected -- MRNA is the one name among the 7 that
# doesn't fit the category (see `is_potential_fake_growth` below).


class SpecGrowthGateResult(NamedTuple):
    qualifies: bool
    # None when the ticker is a plain, in-scope Standard-type candidate that
    # simply failed a gate on the merits (moat/growth/profitability) -- set
    # only when the ticker is structurally out of scope for this
    # classification (wrong company type), so the UI can distinguish
    # "evaluated and didn't qualify" from "not evaluated at all".
    not_applicable_reason: str | None


def is_not_durably_profitable(net_income_series: list[float | None] | None) -> bool:
    """True when Net Income was negative in a majority (>50%) of tracked
    annual+TTM periods -- the profitability gate's operational definition of
    "not yet profitable," broad enough to also catch "inconsistent" per the
    spec's original characteristics.

    Deliberately majority-of-periods, not a flat `NI TTM <= 0` check: a flat
    TTM-only check would still let a durably-profitable company through
    after a single bad year -- confirmed real case, TRMB (10 of 11 tracked
    periods profitable, only the latest TTM negative off a one-off charge)
    -- which is a "mature company, rough year" story, not "not yet
    profitable." Majority-of-periods correctly excludes TRMB while still
    including every genuine case found in the same investigation (CRWD
    10/11, LITE 6/11, NET 11/11 negative) and leaving RKLB (8/8) and the
    original spot-check names unaffected.

    None/empty series (no real NI history at all) reads as durably
    profitable -- i.e. this gate is not cleared -- since a "not yet
    profitable" story can't be confirmed without real NI history; failing
    closed here matches every other gate in this module.
    """
    real_values = [v for v in (net_income_series or []) if v is not None]
    if not real_values:
        return False
    negative_count = sum(1 for v in real_values if v < 0)
    return negative_count > len(real_values) / 2


def evaluate_speculative_growth(
    company_type: str,
    moat: str | None,
    growth_rate_pct: float | None,
    net_income_series: list[float | None] | None = None,
) -> SpecGrowthGateResult:
    if company_type != "Standard":
        return SpecGrowthGateResult(
            qualifies=False,
            not_applicable_reason=(
                f"Speculative Growth is scoped to Standard-type companies only -- {company_type}'s financial "
                "fingerprint (e.g. NII-driven revenue, rental income, reserve accounting) doesn't map onto "
                "'early-stage, high-growth, not-yet-profitable' the same way."
            ),
        )

    moat_pass = moat in _MOAT_QUALIFYING
    growth_pass = growth_rate_pct is not None and growth_rate_pct > GROWTH_GATE_MIN_PCT
    profitability_pass = is_not_durably_profitable(net_income_series)
    return SpecGrowthGateResult(
        qualifies=moat_pass and growth_pass and profitability_pass, not_applicable_reason=None
    )


def cfo_recent_direction(latest_quarter_cfo: float | None, prior_quarter_cfo: float | None) -> str | None:
    """Direction of the two most recent reported quarters' CFO -- informational
    context for the "OCF negative, ideally turning positive in the last 1-2
    quarters" fingerprint. None when either quarter's CFO is unavailable.

    'turning_positive': the latest quarter is positive (regardless of
    whether the prior one was too, or negative) -- the shape the spec's
    "turning positive" language actually describes.
    'improving'/'worsening': both quarters still negative, less/more so.
    'mixed': latest negative but prior was positive (a reversal the other
    way) -- distinct from 'worsening', which is two negative quarters
    trending the wrong direction.
    """
    if latest_quarter_cfo is None or prior_quarter_cfo is None:
        return None
    if latest_quarter_cfo > 0:
        return "turning_positive"
    if prior_quarter_cfo <= 0:
        return "improving" if latest_quarter_cfo > prior_quarter_cfo else "worsening"
    return "mixed"


def cash_runway_years(cash_and_st_investments: float | None, cfo_ttm: float | None) -> float | None:
    """Years of cash at the current TTM CFO burn rate -- display-only, no
    hard cutoff (per the approved design: this metric is new to Fathom and
    hasn't been validated at scale against a risk threshold yet). None
    whenever the company isn't actually burning cash (cfo_ttm >= 0) --
    "runway" isn't a meaningful concept for a cash-flow-positive company."""
    if cash_and_st_investments is None or cfo_ttm is None or cfo_ttm >= 0:
        return None
    return cash_and_st_investments / abs(cfo_ttm)


def psg_ratio(price_to_sales_ttm: float | None, trailing_growth_pct: float | None) -> float | None:
    """Price/Sales ÷ trailing revenue growth % (growth as a whole number,
    e.g. 45.2 not 0.452 -- matches this codebase's own growth_rate_pct
    convention and the PEG-ratio-style formula PSG mirrors). None if either
    input is missing or growth isn't positive -- dividing by a zero/negative
    growth rate isn't a meaningful "cheap relative to growth" reading."""
    if price_to_sales_ttm is None or trailing_growth_pct is None or trailing_growth_pct <= 0:
        return None
    return price_to_sales_ttm / trailing_growth_pct


def trailing_revenue_growth_pct(ttm_revenue: float | None, last_fy_revenue: float | None) -> float | None:
    """TTM-vs-last-full-FY revenue growth, as a % -- the informational
    secondary growth signal (TRAILING_GROWTH_INFORMATIONAL_PCT) and PSG's
    growth denominator. None if the base (last FY) revenue is missing or
    non-positive (a near-zero prior-year base makes this % meaningless --
    confirmed real case in the investigation: ACHR's $300K FY2025 base
    produced a 2200% reading off a single new commercial delivery)."""
    if ttm_revenue is None or last_fy_revenue is None or last_fy_revenue <= 0:
        return None
    return (ttm_revenue / last_fy_revenue - 1) * 100


# "Potential fake growth" -- informational only, never a gate (added
# 2026-09-08, following the no_moat-gate investigation's MRNA finding).
# A ticker can clear the growth gate on Step2's forward CAGR while its
# growth is actually a recovery off a depressed prior-year base rather than
# real momentum -- MRNA is the confirmed real case: forward CAGR 34.4% vs.
# trailing YoY revenue growth of only 14.6%, with TTM revenue still 88.2%
# below its 2022 (COVID-era) peak.
#
# Requires BOTH conditions, not either alone -- validated against all 21
# post-no_moat-gate-change qualifiers: condition (b) alone (trailing growth
# under half of forward CAGR) fires on 13/21 names, most of them genuine
# decelerating-but-healthy growth stories (e.g. SNOW: forward 32.5% vs.
# trailing 7.4%, a large/maturing company's growth naturally cooling, not a
# depressed-base artifact -- its revenue has never declined at all). Adding
# condition (a) (a real >30% revenue decline from a recent peak) narrows
# this to MRNA alone among all 21 -- the AND is load-bearing, not a nicety.
FAKE_GROWTH_REVENUE_DECLINE_THRESHOLD = 0.30
FAKE_GROWTH_TRAILING_RATIO = 0.5
# Trailing *annual* periods (excluding TTM itself) to search for the peak
# over -- degrades gracefully for a thin-history ticker via plain slicing
# (e.g. CRWV's 4 annual years all get used rather than erroring).
FAKE_GROWTH_LOOKBACK_PERIODS = 5


def is_potential_fake_growth(
    revenue_series: list[float | None] | None,
    growth_rate_pct: float | None,
    trailing_growth_pct: float | None,
) -> bool:
    """True when a ticker's current revenue sits more than
    FAKE_GROWTH_REVENUE_DECLINE_THRESHOLD below its own trailing-5yr peak
    (a real, material decline -- not just decelerating growth) AND the
    ticker clears the growth gate mainly via forward CAGR while trailing
    YoY revenue growth sits under half of that forward figure -- i.e. the
    forward number is doing the work a recovering-off-a-trough company's
    number would do, not a genuinely fast-growing one's.

    Fails closed (False) on any missing input, matching every other
    gate/informational check in this module -- a missing revenue history,
    forward growth, or trailing growth figure isn't itself evidence of
    fake growth, just an unresolvable comparison.
    """
    revenue = revenue_series or []
    if not revenue:
        return False
    current_revenue = revenue[-1] if revenue[-1] is not None else (revenue[-2] if len(revenue) >= 2 else None)
    trailing_window = [v for v in revenue[-(FAKE_GROWTH_LOOKBACK_PERIODS + 1) : -1] if v is not None]
    peak_revenue = max(trailing_window) if trailing_window else None

    revenue_depressed = (
        current_revenue is not None
        and peak_revenue is not None
        and peak_revenue > 0
        and current_revenue < peak_revenue * (1 - FAKE_GROWTH_REVENUE_DECLINE_THRESHOLD)
    )
    forward_growth_outpaces_trailing = (
        growth_rate_pct is not None
        and growth_rate_pct > GROWTH_GATE_MIN_PCT
        and trailing_growth_pct is not None
        and trailing_growth_pct < growth_rate_pct * FAKE_GROWTH_TRAILING_RATIO
    )
    return revenue_depressed and forward_growth_outpaces_trailing
