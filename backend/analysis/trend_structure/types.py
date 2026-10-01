"""Shared types for the Weinstein stage engine (see weinstein.py). The
package name `trend_structure` is historical: the daily-bar swing/BOS
trend-structure engine that once lived alongside it was removed, Weinstein
(plus the chart's Stochastic helper) is all that remains here.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

WeinsteinStage = Literal["base", "advance", "top", "decline"]


@dataclass(frozen=True)
class WeinsteinStageResult:
    """Stan Weinstein's classic 4-stage (Base/Advance/Top/Decline) reading,
    computed on WEEKLY bars (see weinstein.py), which needs an extra
    benchmark series and operates on a weekly, resampled timeframe. See weinstein.py's own module docstring for the
    full mechanism.

    stage is None (and every other field None/False) only when there's too
    little daily history to produce even MIN_WEEKS_REQUIRED weekly bars yet
    (e.g. a recent IPO) -- a graceful degradation, never an exception.
    """

    stage: WeinsteinStage | None
    # UNLIKE every other field on this dataclass, always a real int, even
    # when stage is None -- "how many weekly bars WERE available" is exactly
    # the point of this field, populated in both the thin-history
    # early-return and the full-compute path. Lets a caller distinguish
    # "never computed at all" (a persisted row where this column itself is
    # NULL -- see models.py::TrendAnalysis's own comment) from "a real
    # compute ran and genuinely found fewer than MIN_WEEKS_REQUIRED weeks"
    # (this field holds that real, sub-threshold count) -- found necessary
    # after a real incident where a stale, never-reprocessed row's NULL
    # stage was indistinguishable in the UI from a genuine data gap.
    weeks_available: int
    # The first week of the CURRENT stage, walked back from the latest
    # available week. stage_since_is_lower_bound=True means the stage never
    # differed anywhere in the available (post-bootstrap) history -- the
    # true start predates the fetch window, so this date is a lower bound,
    # not a precise transition date. Always False when stage is None too.
    stage_since_date: date | None
    stage_since_is_lower_bound: bool
    ma_slope_pct: float | None
    vs_ma_pct: float | None
    volume_ratio: float | None
    mansfield_rs: float | None
    # A single-run, week-over-week read straight off the just-computed
    # weekly stage series (mirrors the Pine source's own `breakout` plot):
    # true only when the latest week just transitioned INTO "advance" with
    # both volume and relative-strength confirmation. Deliberately NOT the
    # same concept as TrendAnalysis.weinstein_stage_changed (an
    # across-nightly-runs comparison computed in the DB-aware orchestration
    # layer, see data/trend_analysis_data.py) -- always a real bool, never
    # None, even when stage is None (reads False).
    breakout_confirmed: bool
