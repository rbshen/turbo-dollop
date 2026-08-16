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


def _corrected_recent_values(
    quarters: list[dict], recent_values: list[float], field: str, annual_rows: list[dict] | None
) -> list[float]:
    """Substitutes the true isolated Q4 value (annual - sum of the other 3
    known-good quarters) for `recent_values[0]` when
    is_quarter_content_duplicate_of_annual detects the duplicate-annual
    defect -- the correct value IS mathematically derivable here, unlike
    is_implausible_magnitude_shift's shares/EV defect, where no clean
    correction exists and suppression is the only safe option."""
    if not annual_rows or not is_quarter_content_duplicate_of_annual(annual_rows, quarters, field):
        return recent_values
    matching_annual = next(
        row for row in annual_rows if row.get("fiscalYear") == quarters[0].get("fiscalYear")
    )
    corrected_q4 = matching_annual[field] - sum(recent_values[1:4])
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
