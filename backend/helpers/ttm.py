import math
import statistics
from typing import NamedTuple

# How many quarters back (beyond the 4 being summed) to use as the outlier-
# detection baseline, and the combined fetch depth every TTM consumer
# should request so that baseline is actually available. A quarter whose
# magnitude sits further than OUTLIER_RATIO_THRESHOLD away from the
# trailing baseline median is flagged as a possible data anomaly -- never
# altered, just surfaced (see CLAUDE.md's deferred-revenue/one-off
# precedent: surface it, don't guess at fixing it). Confirmed real case:
# FMP's PEP Q2 2026 interestExpense read $2,300M against a ~$226M trailing
# median (~10x) -- a data error, not a real event. These are first-pass
# judgment calls, validated against PEP (flags), NVDA (no false positive
# despite ~3.8x organic EBITDA growth), and AAPL (genuine all-zero history,
# no false positive) -- not a broader dataset beyond those three tickers.
OUTLIER_LOOKBACK_QUARTERS = 8
OUTLIER_RATIO_THRESHOLD = 5.0
MIN_BASELINE_QUARTERS = 4
TOTAL_QUARTERS_NEEDED = 4 + OUTLIER_LOOKBACK_QUARTERS


# Plausibility bounds on the duplicate-annual-quarter correction ("Defect B").
# The derived isolated Q4 (annual - the other 3 quarters) must not flip sign
# relative to those 3 quarters, and its magnitude must stay within
# [1/4, 4] x the magnitude of their mean -- both bounds inclusive. Outside that
# the annual row is far more likely a stub/zero/placeholder than a real
# total (FERG's stub annual row, AZO's all-zero FY2026 cash-flow row), and the
# correction is skipped for that one line item, leaving the quarter as FMP
# reported it. Judged per line item, so a harmless interest-income line can
# never block a good revenue/CFO correction.
DEFECT_B_MAX_RATIO_TO_MEAN = 4.0
DEFECT_B_MIN_RATIO_TO_MEAN = 0.25


# Placeholder cash-flow rows: FMP sometimes serves a period's cash-flow row as
# an empty skeleton -- the section totals all exactly 0 -- beside a real income
# statement (AZO FY2026: 39 of 39 numeric lines 0 on the annual row, 38 of 39 on
# the Q4 row; ITW/BX/LEN/ECL's newest quarter: only netIncome and an offsetting
# otherNonCashItems plug non-zero). That is "not reported yet", not a real
# result of zero cash generated. A row is a placeholder only when ALL of these
# lines are present and exactly 0 AND the same period's income-statement net
# income is non-zero -- i.e. no operating, investing or financing activity at
# all in a period that earned (or lost) money. Deliberately NOT a blanket
# "0 means missing" rule: a legitimately zero capex, buyback or debt line on a
# row with a real CFO never matches, and neither does any bank/insurer/REIT row
# that reports activity.
PLACEHOLDER_CASH_FLOW_ZERO_FIELDS = (
    "netCashProvidedByOperatingActivities",
    "freeCashFlow",
    "capitalExpenditure",
    "netCashProvidedByInvestingActivities",
    "netCashProvidedByFinancingActivities",
)


# Whole-row scale breaks: FMP sometimes serves one row in a different unit from
# the same ticker's other periods (AMCR's FY2026 cash-flow row is in unscaled
# millions -- CFO 2,151 -- beside neighbouring rows in dollars -- CFO
# 1,390,000,000). A row is a scale break only when it is a *whole-row* shift:
# at least SCALE_BREAK_MIN_LINES numeric lines are comparable with the nearest
# SCALE_BREAK_NEIGHBOURS other rows, at least SCALE_BREAK_LINE_FRACTION of them
# sit at least SCALE_BREAK_MIN_RATIO away in the SAME direction (10**2.5, the
# midpoint between a 100x and a 1,000x shift), and their log10 ratios cluster
# tightly (interquartile range <= SCALE_BREAK_MAX_LOG_IQR decades) -- i.e. one
# common unit factor rather than a young company simply being far smaller than
# its neighbours (VRT's pre-merger 2016 balance sheet: 89% of lines are far off,
# but spread over 1.2 decades). One tiny line (EME, MCHP, POOL, SYM) can never
# trigger it.
SCALE_BREAK_NEIGHBOURS = 4
SCALE_BREAK_MIN_LINES = 8
SCALE_BREAK_MIN_RATIO = 10**2.5
SCALE_BREAK_LINE_FRACTION = 0.8
SCALE_BREAK_MAX_LOG_IQR = 0.5
_NON_MONETARY_KEYS = {"fiscalYear", "cik"}


class FlaggedQuarter(NamedTuple):
    date: str | None
    value: float
    trailing_median: float


class TTMResult(NamedTuple):
    total: float | None
    flagged: list[FlaggedQuarter]


def is_quarter_content_duplicate_of_annual(annual_rows: list[dict], quarterly_rows: list[dict], field: str) -> bool:
    """True when the most recent quarter is a Q4 whose own `field` value is
    an exact match to the matching fiscal year's annual row -- i.e. FMP
    served the just-closed fiscal year's cumulative annual total as the
    "Q4" quarterly row instead of the true isolated quarter. Confirmed real
    case (2026-08-16): TEAM's Q4 FY2026 income_statement/cash_flow_statement
    quarterly rows are byte-identical to the FY2026 annual row for revenue/
    CFO/FCF/netIncome -- not a units/scaling defect (see
    is_implausible_magnitude_shift), a wrong-period-boundary one, likely
    FMP's pipeline momentarily falling back to the annual total immediately
    after a fiscal-year-end filing before it finishes computing the true
    isolated Q4.

    Different failure mode from is_ttm_period_duplicate_of_last_fy above
    (that one detects a MISSING new quarter -- TTM's own 4 quarters ARE the
    annual's Q1-Q4; this one detects a quarter whose CONTENT was
    overwritten with the annual total) -- checked per-field, since not
    every field in a corrupted row is necessarily duplicated (confirmed:
    TEAM's Q4 "ebitda" does NOT match its annual ebitda, only revenue/CFO/
    FCF/netIncome do).

    Requires the quarter to actually be labeled "Q4" matching the annual
    row's own fiscalYear -- a mid-year quarter happening to equal its
    (still-open) annual-to-date total isn't this failure mode, and
    "correcting" it the same way (annual - other 3 quarters) would be
    mathematically wrong outside a closed fiscal year."""
    if not annual_rows or not quarterly_rows:
        return False
    latest_quarter = quarterly_rows[0]
    if latest_quarter.get("period") != "Q4":
        return False
    matching_annual = next(
        (row for row in annual_rows if row.get("fiscalYear") == latest_quarter.get("fiscalYear")), None
    )
    if matching_annual is None:
        return False
    quarter_value = latest_quarter.get(field)
    annual_value = matching_annual.get(field)
    if quarter_value is None or annual_value is None:
        return False
    return quarter_value == annual_value


def is_plausible_isolated_quarter(corrected_q4: float, other_three: list[float]) -> bool:
    """True when a derived isolated Q4 value is believable next to the other
    three quarters of the same fiscal year: same sign as their mean, and
    between DEFECT_B_MIN_RATIO_TO_MEAN and DEFECT_B_MAX_RATIO_TO_MEAN times its
    magnitude (both ends inclusive). A zero mean has no scale to judge
    against, so it is never plausible -- harmless in practice, since with the
    other three quarters summing to 0 the "corrected" value equals the
    uncorrected one anyway."""
    mean = sum(other_three) / len(other_three)
    if mean == 0 or corrected_q4 * mean < 0:
        return False
    return DEFECT_B_MIN_RATIO_TO_MEAN * abs(mean) <= abs(corrected_q4) <= DEFECT_B_MAX_RATIO_TO_MEAN * abs(mean)


def _corrected_recent_values(
    quarters: list[dict], recent_values: list[float], field: str, annual_rows: list[dict] | None
) -> list[float]:
    """Substitutes the true isolated Q4 value (annual - sum of the other 3
    known-good quarters) for `recent_values[0]` when
    is_quarter_content_duplicate_of_annual detects the duplicate-annual
    defect -- the correct value IS mathematically derivable here, unlike
    is_implausible_magnitude_shift's shares/EV defect, where no clean
    correction exists and suppression is the only safe option.

    The correction is skipped (the uncorrected quarters are used) when the
    derived Q4 fails is_plausible_isolated_quarter -- see
    DEFECT_B_MAX_RATIO_TO_MEAN."""
    if not annual_rows or not is_quarter_content_duplicate_of_annual(annual_rows, quarters, field):
        return recent_values
    matching_annual = next(
        row for row in annual_rows if row.get("fiscalYear") == quarters[0].get("fiscalYear")
    )
    corrected_q4 = matching_annual[field] - sum(recent_values[1:4])
    if not is_plausible_isolated_quarter(corrected_q4, recent_values[1:4]):
        return recent_values
    return [corrected_q4, *recent_values[1:]]


def sum_last_four_quarters(quarters: list[dict], field: str, annual_rows: list[dict] | None = None) -> TTMResult:
    """Sum a flow-measure field across the 4 most recent quarters --
    trailing-twelve-months convention shared by Step 1 (income statement/
    cash flow TTM columns), Step 4 (revenue/net income/COGS TTM), Step 5
    (EBITDA, net interest expense, CFO), and the ticker header's raw metric
    tiles. `quarters` must be most-recent-first (FMP's own ordering) --
    `total` is None if fewer than 4 quarters have a non-null value for this
    field, rather than summing a partial year.

    `annual_rows`, when passed, is used to detect and correct TEAM Defect B
    (see is_quarter_content_duplicate_of_annual) before summing -- optional
    and backward-compatible, since not every call site has annual data
    readily in scope (e.g. ticker_summary.py's header tiles); omitting it
    just means that one call site doesn't get this specific correction,
    unchanged from before this parameter existed.

    Also flags (never alters) any of those 4 summed quarters whose
    magnitude is more than OUTLIER_RATIO_THRESHOLD away from the trailing
    median of up to OUTLIER_LOOKBACK_QUARTERS prior quarters -- this
    detector runs on the (possibly already-corrected) recent_values, so a
    quarter fixed by the annual-duplicate correction above no longer shows
    up here; it's not the same value anymore. Requires at least
    MIN_BASELINE_QUARTERS of baseline history to run at all (skipped, not
    flagged, when less is available -- e.g. a recent IPO), and skips when
    the baseline median is exactly 0 (a ratio against zero is undefined,
    not "infinite" -- avoids false-flagging tickers with a genuine
    all-zero history like AAPL's interest fields)."""
    recent = quarters[:4]
    recent_values = [q.get(field) for q in recent]
    if len(recent) < 4 or any(v is None for v in recent_values):
        return TTMResult(total=None, flagged=[])
    recent_values = _corrected_recent_values(quarters, recent_values, field, annual_rows)
    total = sum(recent_values)

    baseline_rows = quarters[4 : 4 + OUTLIER_LOOKBACK_QUARTERS]
    baseline_values = [abs(q[field]) for q in baseline_rows if q.get(field) is not None]

    flagged: list[FlaggedQuarter] = []
    if len(baseline_values) >= MIN_BASELINE_QUARTERS:
        median = statistics.median(baseline_values)
        if median > 0:
            for row, value in zip(recent, recent_values):
                abs_value = abs(value)
                if abs_value > OUTLIER_RATIO_THRESHOLD * median or abs_value < median / OUTLIER_RATIO_THRESHOLD:
                    flagged.append(FlaggedQuarter(date=row.get("date"), value=value, trailing_median=median))

    return TTMResult(total=total, flagged=flagged)


def _period_net_income(cash_flow_row: dict, income_rows: list[dict]) -> float | None:
    """The same period's income-statement net income -- matched on the
    period-end date first, then on (fiscalYear, period). None when the
    income statement has no such row or no value."""
    date = cash_flow_row.get("date")
    for row in income_rows:
        if date and row.get("date") == date:
            return row.get("netIncome")
    key = (cash_flow_row.get("fiscalYear"), cash_flow_row.get("period"))
    if None not in key:
        for row in income_rows:
            if (row.get("fiscalYear"), row.get("period")) == key:
                return row.get("netIncome")
    return None


def is_placeholder_cash_flow_row(cash_flow_row: dict, income_rows: list[dict]) -> bool:
    """True when `cash_flow_row` is an empty-skeleton row (see
    PLACEHOLDER_CASH_FLOW_ZERO_FIELDS): CFO, FCF, capex and the investing and
    financing totals are all present and exactly 0, while the same period's
    income-statement net income is non-zero. Not provable without that net
    income, so a row whose period has no income row is never a placeholder."""
    # `!= 0` is also True for a missing (None) field, so an absent line is never read as a zero.
    if any(cash_flow_row.get(field) != 0 for field in PLACEHOLDER_CASH_FLOW_ZERO_FIELDS):
        return False
    net_income = _period_net_income(cash_flow_row, income_rows)
    return net_income is not None and net_income != 0


def _monetary_lines(row: dict) -> dict[str, float]:
    return {
        k: v
        for k, v in row.items()
        if k not in _NON_MONETARY_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def is_scale_broken_row(rows: list[dict], index: int) -> bool:
    """True when rows[index] looks like a whole-row unit/scale break against
    its nearest SCALE_BREAK_NEIGHBOURS other rows in the same list (see
    SCALE_BREAK_MIN_RATIO and friends). `rows` is the ticker's own series of
    one statement and period; a list too short to supply two non-zero
    neighbours for a line contributes nothing for that line."""
    nearest = sorted((j for j in range(len(rows)) if j != index), key=lambda j: abs(j - index))
    neighbours = [_monetary_lines(rows[j]) for j in nearest[:SCALE_BREAK_NEIGHBOURS]]
    log_ratios: list[float] = []
    for key, value in _monetary_lines(rows[index]).items():
        if value == 0:
            continue
        magnitudes = [abs(n[key]) for n in neighbours if n.get(key)]
        if len(magnitudes) < 2:
            continue
        log_ratios.append(math.log10(abs(value) / statistics.median(magnitudes)))
    if len(log_ratios) < SCALE_BREAK_MIN_LINES:
        return False
    direction = 1 if statistics.median(log_ratios) > 0 else -1
    threshold = math.log10(SCALE_BREAK_MIN_RATIO)
    far = sum(1 for lr in log_ratios if direction * lr >= threshold)
    if far / len(log_ratios) < SCALE_BREAK_LINE_FRACTION:
        return False
    ordered = sorted(log_ratios)
    q1, q3 = ordered[len(ordered) // 4], ordered[(3 * len(ordered)) // 4]
    return q3 - q1 <= SCALE_BREAK_MAX_LOG_IQR


def _blank(row: dict) -> dict:
    return {k: (None if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in row.items()}


def _treat_as_missing(rows: list[dict], is_missing: list[bool], drop_leading: bool) -> list[dict]:
    """Quarterly (`drop_leading=True`): the contiguous run of missing rows at
    the NEWEST end is removed, so the TTM window slides back to the last four
    valid quarters; a missing row anywhere else is kept but blanked (numeric
    fields None, identity fields kept), so a TTM window containing it reads
    None -- skipping an interior quarter would stretch the window past 12
    months. Annual (`drop_leading=False`): missing rows are blanked in place,
    never removed, because annual series are read positionally and by fiscal
    year beside the income and balance-sheet series. With fewer than four valid
    quarters left the TTM is missing, never partial."""
    cleaned: list[dict] = []
    leading = drop_leading
    for row, missing in zip(rows, is_missing):
        if not missing:
            leading = False
            cleaned.append(row)
        elif not leading:
            cleaned.append(_blank(row))
    return cleaned


def drop_placeholder_cash_flow_rows(
    cash_flow_rows: list[dict], income_rows: list[dict], drop_leading: bool = True
) -> list[dict]:
    """Treats only placeholder cash-flow rows (is_placeholder_cash_flow_row) as
    missing -- see _treat_as_missing for the quarterly (`drop_leading=True`) vs
    annual (`drop_leading=False`) handling. `cash_flow_rows` most-recent-first."""
    return _treat_as_missing(
        cash_flow_rows, [is_placeholder_cash_flow_row(row, income_rows) for row in cash_flow_rows], drop_leading
    )


def clean_cash_flow_statements(
    cash_flow_annual: list[dict],
    cash_flow_quarterly: list[dict],
    income_annual: list[dict],
    income_quarterly: list[dict],
) -> tuple[list[dict], list[dict]]:
    """The one entry point Steps 1, 3, 4 and 5 call right after loading the
    cash-flow statements. Treats as MISSING (see _treat_as_missing for how
    quarterly vs annual lists handle that):

    1. placeholder rows (is_placeholder_cash_flow_row: empty skeletons beside a
       real income statement), annual and quarterly;
    2. whole-row scale breaks (is_scale_broken_row), annual and quarterly; and
       the "Q4" quarterly row of any fiscal year whose ANNUAL row is a scale
       break, because FMP derives every Q4 as annual minus the other three
       quarters, so a mis-scaled annual poisons its Q4 (AMCR: Q4 net income
       -716,998,894 = 1,106 - 717,000,000, against +389M on the income
       statement, which is how TTM CFO came out as 22.7M instead of ~2.15B).

    Returns (annual, quarterly), both most-recent-first. Only cash-flow rows are
    touched; income and balance-sheet rows never go through this."""
    annual_scale = [is_scale_broken_row(cash_flow_annual, i) for i in range(len(cash_flow_annual))]
    broken_years = {row.get("fiscalYear") for row, broken in zip(cash_flow_annual, annual_scale) if broken}
    annual_missing = [
        broken or is_placeholder_cash_flow_row(row, income_annual)
        for row, broken in zip(cash_flow_annual, annual_scale)
    ]
    quarterly_missing = [
        is_scale_broken_row(cash_flow_quarterly, i)
        or is_placeholder_cash_flow_row(row, income_quarterly)
        or (row.get("period") == "Q4" and row.get("fiscalYear") in broken_years)
        for i, row in enumerate(cash_flow_quarterly)
    ]
    return (
        _treat_as_missing(cash_flow_annual, annual_missing, drop_leading=False),
        _treat_as_missing(cash_flow_quarterly, quarterly_missing, drop_leading=True),
    )


def is_ttm_period_duplicate_of_last_fy(annual_rows: list[dict], quarterly_rows: list[dict]) -> bool:
    """True when the 4 quarters `sum_last_four_quarters` would sum for TTM
    are exactly the latest annual filing's own Q1-Q4 -- i.e. no quarter has
    been reported since that fiscal year closed, so TTM and the last annual
    figure describe the identical underlying period. A multi-year-average
    smoother (see scoring.step3.trailing_smoothed_average) that blindly
    appends TTM after the annual series double-counts this period.

    Checked by `fiscalYear`/`period` identity (FMP's own labels on each
    row), not value equality -- a coincidental value match isn't the same
    condition (would false-clear on real, distinct periods that happen to
    net to the same total), and a genuine period match can differ slightly
    in value after a restatement (would false-miss under a value check).

    `quarterly_rows` must be most-recent-first (FMP's own ordering, same
    convention `sum_last_four_quarters` requires). `annual_rows` order-
    agnostic -- the latest fiscal year is resolved by comparing `fiscalYear`
    labels directly, not by position."""
    if not annual_rows or len(quarterly_rows) < 4:
        return False
    last_fy = max(annual_rows, key=lambda row: row.get("fiscalYear", "")).get("fiscalYear")
    recent4 = quarterly_rows[:4]
    quarter_fys = {q.get("fiscalYear") for q in recent4}
    quarter_periods = {q.get("period") for q in recent4}
    return quarter_fys == {last_fy} and quarter_periods == {"Q1", "Q2", "Q3", "Q4"}
