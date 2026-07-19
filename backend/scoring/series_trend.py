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
