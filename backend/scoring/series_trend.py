from typing import NamedTuple

import numpy as np


class SeriesDirectionAnalysis(NamedTuple):
    direction: float  # late-window average minus early-window average
    num_real_dips: int
    sustained_decline: bool


def analyze_series_direction(
    values: np.ndarray,
    window: int,
    dip_threshold: float,
    sustained_decline_steps: int,
    sustained_decline_threshold: float,
) -> SeriesDirectionAnalysis:
    """Generic early-window-vs-late-window direction + dip-count +
    sustained-decline analysis, shared by Step 1's margin classifier and
    Step 4's Cash Conversion Cycle classifier (the latter runs this on a
    negated series, since a declining CCC is the desirable direction while
    a declining margin is not -- see CLAUDE.md's "Scoring rubric
    deviations")."""
    w = min(window, len(values))
    direction = float(values[-w:].mean() - values[:w].mean())

    diffs = np.diff(values)
    num_real_dips = int(np.count_nonzero(diffs < -dip_threshold))

    sustained_decline = False
    for i in range(len(diffs) - sustained_decline_steps + 1):
        run = diffs[i : i + sustained_decline_steps]
        if np.all(run < 0) and run.sum() <= -sustained_decline_threshold:
            sustained_decline = True
            break

    return SeriesDirectionAnalysis(direction, num_real_dips, sustained_decline)


def robust_late_direction(values: np.ndarray, window: int, protect_terminal: bool = False) -> float:
    """`direction`, but with the single most extreme point WITHIN the late
    window (vs. that window's own median) excluded from its average -- the
    mirror-image guard to sustained_decline/_series_recovered: a lone
    anomalous good-side data point in the late window (e.g. one wildly
    negative CCC quarter, or a spike-year margin) can otherwise single-
    handedly flip `direction` positive even when the rest of the window
    shows a flat or worsening trend. Deliberately touches ONLY the late
    window, not the early one for every general caller here -- an early-
    window anomaly is a different correction, with a different (asymmetric)
    risk profile, and is handled separately by `robust_early_direction`
    below for the one narrow case that needs it (see that function's own
    docstring for why it isn't just this function mirrored blindly).

    `protect_terminal`: never let the excluded outlier be the series' own
    most recent point. Every other caller (margins/CCC/AR-DSO, and
    flat_then_spike's own narrowing) is deliberately fine excluding a
    one-off good TERMINAL value too -- that's exactly the "one lucky year"
    the guard exists to catch. `_dip_durably_resolved` is different: its
    whole question is "has this series' own most current value shown
    genuine improvement," so discarding that value as noise defeats the
    check rather than protecting it. Confirmed real case: VZ's CFO
    recovery segment (2022-TTM) is flat-to-improving, but TTM is both the
    highest point AND the furthest from the window's median, so the
    unguarded version threw out the one point that was actual evidence of
    recovery, netting a coin-flip-thin negative (-$151.5M on a ~$37B base,
    ~0.4%) instead of the genuinely-positive naive average (+$440M)."""
    arr = np.asarray(values, dtype=float)
    w = min(window, len(arr))
    early_avg = float(arr[:w].mean())
    late = arr[-w:]
    if len(late) < 3:
        return float(late.mean()) - early_avg
    median = np.median(late)
    idx = int(np.argmax(np.abs(late - median)))
    if protect_terminal and idx == len(late) - 1:
        return float(late.mean()) - early_avg
    robust_late_avg = float(np.delete(late, idx).mean())
    return robust_late_avg - early_avg


def robust_early_direction(values: np.ndarray, window: int) -> float:
    """`direction`, but with the single most extreme point WITHIN the early
    window (vs. that window's own median) excluded from its average --
    exists for exactly one caller (Step 1's Margins `sharply_declining`
    check) and is NOT a general-purpose mirror of `robust_late_direction`
    the way it might look. The two functions solve different-shaped
    problems: excluding the late window's outlier is safe to use
    unconditionally, because a single good late point can only ever make
    `direction` look BETTER than it should -- excluding it is conservative.
    Excluding the early window's outlier is NOT safety-symmetric: the
    excluded point can be either a high anomaly (raises `direction`, e.g. a
    one-off gain inflating the early baseline -- GLW's 2016 39.35% net
    margin) or a low anomaly (LOWERS `direction` by raising what's left of
    the early average, e.g. a real oil-crash trough sitting in DVN's first
    3 years) -- and only the first case is the false positive this exists
    to catch. Confirmed via a full-universe check (2026-08-13): using this
    function's raw output unconditionally regressed 16 tickers (DVN's
    Margins score cratered from stable_or_expanding/100 to
    sharply_declining/20 -- excluding its 2016 trough raised the early
    average, which made `direction` MORE negative, the opposite of the
    intended fix). Callers MUST take `max(direction, robust_early_direction(...))`,
    never this function's return value alone -- that makes the correction
    one-directional (only ever raises a reading that direction's own
    unguarded average put too low), so a genuine low early anomaly can
    never make a company look worse than the unadjusted average already
    did. See CLAUDE.md's Step 1 deviations for the full investigation."""
    arr = np.asarray(values, dtype=float)
    w = min(window, len(arr))
    late_avg = float(arr[-w:].mean())
    early = arr[:w]
    if len(early) < 3:
        return late_avg - float(early.mean())
    median = np.median(early)
    idx = int(np.argmax(np.abs(early - median)))
    robust_early_avg = float(np.delete(early, idx).mean())
    return late_avg - robust_early_avg
