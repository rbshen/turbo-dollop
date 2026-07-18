from typing import NamedTuple

import numpy as np

# A period-over-period change smaller than this counts as flat/noise, not a
# real move. 5% rather than something tighter because routine single-digit
# swings in large, otherwise-consistent companies (e.g. a ~2-3% single-year
# revenue dip) shouldn't read as a "dip" the way a human eyeballing a 10-year
# chart wouldn't call it one either.
NOISE_FLOOR = 0.05
# Boundary between a "small" and a "significant" single dip.
SIGNIFICANT_DIP = 0.10
# How large the final jump must be, and how flat everything before it must
# be, to read as "flat for years then a sudden spike" rather than gradual
# multi-dip growth.
SPIKE_THRESHOLD = 0.25
FLAT_WINDOW_THRESHOLD = 0.10


class TrendResult(NamedTuple):
    pattern: str
    score: int


def _pct_changes(values: np.ndarray) -> np.ndarray:
    prev = values[:-1]
    curr = values[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(prev != 0, (curr - prev) / np.abs(prev), np.sign(curr))


def classify_trend(values: list[float]) -> TrendResult:
    """Classify a chronological (oldest fiscal year -> TTM) metric series into
    one of the Step 1 methodology's 6 trend patterns.

    Contract: `values` must already be filtered of None/missing periods and
    given in chronological order ending with TTM. Requires at least 2 points.
    """
    if len(values) < 2:
        return TrendResult("insufficient_data", 0)

    arr = np.asarray(values, dtype=float)
    pct_changes = _pct_changes(arr)
    real_dips = np.flatnonzero(pct_changes < -NOISE_FLOOR)

    # TTM (the final transition) declining is disqualifying regardless of
    # earlier history -- the methodology explicitly requires TTM to confirm
    # the trend, not undermine it, even after a long clean run.
    if pct_changes[-1] < -NOISE_FLOOR:
        return TrendResult("declining", 0)

    if real_dips.size == 0:
        return TrendResult("grows_every_year", 100)

    if real_dips.size == 1:
        dip_index = int(real_dips[0])
        pre_dip_value = arr[dip_index]
        recovered = arr[-1] >= pre_dip_value
        if not recovered:
            # Dipped and never got back to the pre-dip level by TTM -- closer
            # to an inconsistent read than a clean "dip then recovery" story.
            return TrendResult("multiple_dips", 40)
        dip_pct = pct_changes[dip_index]
        if abs(dip_pct) <= SIGNIFICANT_DIP:
            return TrendResult("small_dip_recovers", 90)
        return TrendResult("significant_dip_recovers", 70)

    growth_before_last = _pct_changes(arr[[0, -2]])[0]
    last_jump = pct_changes[-1]
    if abs(growth_before_last) < FLAT_WINDOW_THRESHOLD and last_jump > SPIKE_THRESHOLD:
        return TrendResult("flat_then_spike", 20)

    # Deliberately refined beyond step1_revenue_income_cfo_assessment_prompt.md's
    # original flat 40-for-any-2+-dips read -- see CLAUDE.md's "Scoring rubric
    # deviations" section. A resolved dip from several years ago is a
    # different risk profile than one still resolving now, so recovery and
    # recency each get their own tier instead of collapsing into one bucket.
    all_recovered = all(arr[-1] >= arr[i] for i in real_dips)
    if not all_recovered:
        # At least one dip never got back to its pre-dip level by TTM --
        # genuinely uneven, unchanged from the original flat tier.
        return TrendResult("multiple_dips", 40)

    n = len(arr)
    recent_fy_indices = {n - 2, n - 3}  # the 2 FYs immediately before TTM
    dip_is_recent = any((i + 1) in recent_fy_indices for i in real_dips)
    if dip_is_recent:
        return TrendResult("multiple_dips_recent", 60)
    return TrendResult("multiple_dips_resolved", 75)
