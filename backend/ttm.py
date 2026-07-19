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


def sum_last_four_quarters(quarters: list[dict], field: str) -> TTMResult:
    """Sum a flow-measure field across the 4 most recent quarters --
    trailing-twelve-months convention shared by Step 1 (income statement/
    cash flow TTM columns), Step 4 (revenue/net income/COGS TTM), Step 5
    (EBITDA, net interest expense, CFO), and the ticker header's raw metric
    tiles. `quarters` must be most-recent-first (FMP's own ordering) --
    `total` is None if fewer than 4 quarters have a non-null value for this
    field, rather than summing a partial year.

    Also flags (never alters) any of those 4 summed quarters whose
    magnitude is more than OUTLIER_RATIO_THRESHOLD away from the trailing
    median of up to OUTLIER_LOOKBACK_QUARTERS prior quarters. Requires at
    least MIN_BASELINE_QUARTERS of baseline history to run at all (skipped,
    not flagged, when less is available -- e.g. a recent IPO), and skips
    when the baseline median is exactly 0 (a ratio against zero is
    undefined, not "infinite" -- avoids false-flagging tickers with a
    genuine all-zero history like AAPL's interest fields)."""
    recent = quarters[:4]
    recent_values = [q.get(field) for q in recent]
    if len(recent) < 4 or any(v is None for v in recent_values):
        return TTMResult(total=None, flagged=[])
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
