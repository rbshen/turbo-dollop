"""Weinstein Stage Analysis: "pending confirmation" + ETA -- a purely
additive read on top of weinstein.py's sticky sState machine, NOT a change
to it (compute_stage_series is imported and used as-is; this module never
duplicates or edits its transition loop).

Engine-swap note (2026-09-26): weinstein.py's engine became config-driven
(EMA/SMA MA, adjustable length/band/slope lookback -- WeinsteinParams). The
state-machine transition rules this module reasons about are unchanged, so
the pending flags and ETA projection are unchanged in shape; every function
here now takes the SAME WeinsteinParams the stage itself was computed with,
so the band, the MA type and the slope lookback in the projection always
match the live engine. Where older comments below say "30-week"/"+/-5%",
read "ma_length"/"within_range_pct" (defaults 30 / 5.0).

See docs/weinstein_pending_confirmation_investigation_2026-09-22.md for the
full design proposal and the round-2 full-universe validation this module
implements. Summary of what it answers:

Weinstein's sState machine requires BOTH a slope condition (30-week MA
turning) AND a band condition (price clearing +/-5% of the MA) to hold in
the SAME week before six of its eight transitions fire (Base/Top/Decline ->
Advance, and Base/Top/Advance -> Decline -- the other two, Advance->Top and
Decline->Base, need no band condition at all and so have no "pending"
state). That's correct, deliberately sticky behavior -- but it means a
ticker's stage label can visibly disagree with where price already is: one
condition met, the other still open. This module flags that state
("pending_advance"/"pending_decline") and, only for flagged tickers,
projects how many more weeks the slope math would need under a few
explicit, clearly-labeled price assumptions -- never a price prediction.

Three scenarios (flat / trend_5 / trend_13) are projected by extending the
real weekly-close series forward under each assumption and re-running
compute_stage_series UNMODIFIED on the extended series, watching for the
first future week where slope and band both hold simultaneously -- not
slope alone (see _project_confirmation_eta's own docstring for the
simultaneity bug this design deliberately avoids).

IMPORTANT (round-2 validation finding, 2026-09-22): "does not confirm
within the horizon" is not a flat-scenario-only phenomenon. ANY scenario
with a nonzero-but-constant compounding growth rate can hit the identical
"chase never converges" shape once real history has fully rolled out of
the 30-week lookback window -- confirmed on AXON (trend_13), CDE
(trend_5), and CTSH (trend_5), not just LYB's original flat-scenario case.
UI/caveat text must describe this as "under its stated growth assumption,"
never "under a flat price," specifically because of this finding.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from .weinstein import WeinsteinParams, compute_stage_series, resample_to_weekly

PendingDirection = Literal["advance", "decline"]

# The three scenarios validated in the design doc -- flat is the literal
# ask ("if price holds"), trend_5 is a fixed 5-week pace (the most reactive read; a fixed scenario
# horizon, independent of WeinsteinParams.slope_lookback so the API keys stay stable), trend_13 is a steadier one-quarter read. Picked
# over a mean-reversion/linear-extrapolation scenario because the real risk
# this projection needs to expose (an old price move rolling out of the
# 30-week window while price just sits still) is already visible via `flat`
# + band_lapsed_before_confirmation, without pretending to model reversal
# risk explicitly.
SCENARIOS: tuple[str, ...] = ("flat", "trend_5", "trend_13")

# Matches MIN_WEEKS_REQUIRED's own "104 weeks (2y)" bootstrap-convergence
# convention (weinstein.py) -- a projection that hasn't confirmed within 2
# years is reported as horizon_exceeded rather than searched further.
PROJECTION_HORIZON_WEEKS = 104

# Trailing window for the band-cushion diagnostic's "typical weekly move"
# comparison -- one quarter, matching trend_13's own lookback.
CUSHION_STDEV_LOOKBACK_WEEKS = 13


@dataclass(frozen=True)
class WeinsteinPendingEtaScenario:
    """One scenario's projected confirmation -- see
    _project_confirmation_eta's own docstring for the full mechanism.

    horizon_exceeded=True means the two conditions never coincided within
    PROJECTION_HORIZON_WEEKS under this scenario's assumption
    (weeks_away/projected_date/projected_slope are then all None).
    band_lapsed_before_confirmation is True whenever the band condition
    dropped false at some point before (or, in the horizon-exceeded case,
    instead of) the two conditions ever coinciding again -- the signal that
    an old price move is rolling out of the 30-week window faster than
    slope can confirm under THIS scenario's growth assumption (see the
    module docstring's round-2 finding: not flat-only)."""

    weeks_away: int | None
    projected_date: date | None
    band_lapsed_before_confirmation: bool
    growth_rate_pct: float
    horizon_exceeded: bool


@dataclass(frozen=True)
class WeinsteinPendingResult:
    """direction is None (every other field None too) whenever the ticker
    isn't currently pending a Stage 2/Stage 4 transition -- either it has
    too little weekly history (mirrors WeinsteinStageResult's own
    MIN_WEEKS_REQUIRED gate) or it genuinely isn't in a "one condition met,
    one still open" state right now. eta is only ever computed (a dict
    keyed by SCENARIOS) when direction is not None -- the whole point of
    gating this on the pending flag first is that the 3-scenario projection
    is comparatively expensive and only ever meaningful for a pending
    ticker (confirmed cheap in aggregate: ~12s for the full tracked
    universe in the validation round, since the ETA projection only ever
    runs for the small pending subset)."""

    direction: PendingDirection | None
    since_date: date | None
    since_is_lower_bound: bool
    band_cushion_pct: float | None
    typical_weekly_move_pct: float | None
    eta: dict[str, WeinsteinPendingEtaScenario] | None


def _stage_flags(weekly_close: pd.Series, params: WeinsteinParams) -> pd.DataFrame:
    """compute_stage_series' output plus the band/slope-direction booleans
    the pending logic needs -- read-only derived from weinstein.py's own
    unmodified ma/slope columns, no new numerics on the stage itself.

    Confirmed against all 8 of compute_stage_series' transition rules
    (weinstein.py lines ~114-131): pending_advance is meaningful from any
    stage OTHER than advance (base, top, OR decline -- not just
    decline->advance), and pending_decline mirrors it for any stage other
    than decline. The two are mutually exclusive (the +/-5% bands can't
    both hold at once), so at most one is ever True for a given week.
    """
    band = params.band
    stage_df = compute_stage_series(weekly_close, params)
    out = weekly_close.to_frame("close").join(stage_df)
    out["above_band"] = out["valid"] & (out["close"] > out["ma"] * (1.0 + band))
    out["below_band"] = out["valid"] & (out["close"] < out["ma"] * (1.0 - band))
    out["rising"] = out["valid"] & (out["slope"] > 0.0)
    out["falling"] = out["valid"] & (out["slope"] < 0.0)
    out["pending_advance"] = out["valid"] & (out["stage"] != "advance") & out["above_band"] & (~out["rising"])
    out["pending_decline"] = out["valid"] & (out["stage"] != "decline") & out["below_band"] & (~out["falling"])
    return out


def _current_pending_direction(flags: pd.DataFrame) -> PendingDirection | None:
    latest = flags.iloc[-1]
    if bool(latest["pending_advance"]):
        return "advance"
    if bool(latest["pending_decline"]):
        return "decline"
    return None


def _pending_since(flags: pd.DataFrame, direction: PendingDirection) -> tuple[date | None, bool]:
    """Same walk-backward shape as weinstein.py's own _stage_since (not
    reused directly -- that one keys off the `stage` label, this keys off a
    boolean pending column -- but deliberately mirrors its "lower bound if
    constant across all available history" case)."""
    col = "pending_advance" if direction == "advance" else "pending_decline"
    series = flags[col]
    if not bool(series.iloc[-1]):
        return None, False
    i = len(series) - 1
    while i > 0 and bool(series.iloc[i - 1]):
        i -= 1
    is_lower_bound = i == 0
    idx = series.index[i]
    return (idx.date() if hasattr(idx, "date") else idx), is_lower_bound


def _scenario_growth_rate(weekly_close: pd.Series, scenario: str) -> float:
    """flat -> 0% weekly growth. trend_N -> the trailing N-week average
    weekly % return, compounded forward."""
    if scenario == "flat":
        return 0.0
    n = int(scenario.split("_")[1])
    trailing = weekly_close.iloc[-(n + 1) :]
    if len(trailing) < 2:
        return 0.0
    return float(trailing.pct_change().dropna().mean())


def _project_confirmation_eta(
    weekly_close: pd.Series,
    direction: PendingDirection,
    scenario: str,
    params: WeinsteinParams,
    horizon_weeks: int = PROJECTION_HORIZON_WEEKS,
) -> WeinsteinPendingEtaScenario:
    """Walks forward week by week under the stated price-growth assumption,
    re-running compute_stage_series UNMODIFIED on the extended series, and
    reports the first future week where BOTH the slope condition and the
    band condition needed for a real transition hold SIMULTANEOUSLY -- not
    slope alone.

    That "simultaneously" requirement matters: flagging "confirmed" the
    moment slope alone crosses zero, for a ticker whose band-clearance is
    fading as an old price spike rolls out of the 30-week window, would
    report a confirmation date at which the real compute_stage_series
    would actually land in Top/Base instead, because the band condition
    had already lapsed by then. band_lapsed_before_confirmation surfaces
    exactly this (see the module docstring for why this isn't
    flat-scenario-specific)."""
    assert direction in ("advance", "decline")
    last_close = float(weekly_close.iloc[-1])
    last_date = weekly_close.index[-1]
    growth = _scenario_growth_rate(weekly_close, scenario)

    future_index = pd.DatetimeIndex([last_date + pd.Timedelta(weeks=i) for i in range(1, horizon_weeks + 1)])
    future_closes = last_close * (1.0 + growth) ** np.arange(1, horizon_weeks + 1)
    extended = pd.concat([weekly_close, pd.Series(future_closes, index=future_index)])

    band = params.band
    stage_df = compute_stage_series(extended, params)
    cutoff_pos = len(weekly_close) - 1

    band_lapsed_first: int | None = None
    for i in range(cutoff_pos + 1, len(extended)):
        slope = stage_df["slope"].iloc[i]
        ma = stage_df["ma"].iloc[i]
        close = extended.iloc[i]
        if pd.isna(slope) or pd.isna(ma):
            continue
        if direction == "advance":
            slope_ok = slope > 0.0
            band_ok = close > ma * (1.0 + band)
        else:
            slope_ok = slope < 0.0
            band_ok = close < ma * (1.0 - band)

        if not band_ok and band_lapsed_first is None:
            band_lapsed_first = i - cutoff_pos

        if slope_ok and band_ok:
            projected_idx = extended.index[i]
            return WeinsteinPendingEtaScenario(
                weeks_away=i - cutoff_pos,
                projected_date=projected_idx.date() if hasattr(projected_idx, "date") else projected_idx,
                band_lapsed_before_confirmation=band_lapsed_first is not None and band_lapsed_first < (i - cutoff_pos),
                growth_rate_pct=growth * 100.0,
                horizon_exceeded=False,
            )
    return WeinsteinPendingEtaScenario(
        weeks_away=None,
        projected_date=None,
        band_lapsed_before_confirmation=band_lapsed_first is not None,
        growth_rate_pct=growth * 100.0,
        horizon_exceeded=True,
    )


def _eta_report(weekly_close: pd.Series, direction: PendingDirection, params: WeinsteinParams) -> dict[str, WeinsteinPendingEtaScenario]:
    return {scenario: _project_confirmation_eta(weekly_close, direction, scenario, params) for scenario in SCENARIOS}


def _band_cushion_pct(weekly_close: pd.Series, direction: PendingDirection, params: WeinsteinParams) -> tuple[float, float]:
    """Not a scenario -- a snapshot risk read: how far past the band
    threshold price closed today, versus the standard deviation of the
    last CUSHION_STDEV_LOOKBACK_WEEKS weekly returns. A thin cushion means
    one ordinary-sized move the other way could un-clear the band before
    slope ever gets a chance to confirm -- a heuristic, single-ticker-
    validated diagnostic (see the design doc's META false-alarm cases), not
    a rigorously back-tested predictor, and never a gate on the pending
    flag itself."""
    band = params.band
    stage_df = compute_stage_series(weekly_close, params)
    close = float(weekly_close.iloc[-1])
    ma = float(stage_df["ma"].iloc[-1])
    threshold = ma * (1.0 + band) if direction == "advance" else ma * (1.0 - band)
    cushion_pct = (close / threshold - 1.0) * 100.0 if direction == "advance" else (1.0 - close / threshold) * 100.0
    recent_returns = weekly_close.pct_change().dropna().iloc[-CUSHION_STDEV_LOOKBACK_WEEKS:]
    stdev_pct = float(recent_returns.std()) * 100.0
    return cushion_pct, stdev_pct


def compute_weinstein_pending(ohlcv: pd.DataFrame, params: WeinsteinParams | None = None) -> WeinsteinPendingResult:
    """ohlcv is a daily-indexed frame matching weinstein.py::
    compute_weinstein_stage's own contract (lowercase open/high/low/close/
    volume) -- resampled to weekly here via resample_to_weekly (imported,
    not duplicated), the same real data the nightly job already has, no
    new fetch. Mirrors compute_weinstein_stage's own thin-history
    early-return: below MIN_WEEKS_REQUIRED weekly bars, every field reads
    None/not-pending rather than raising."""
    p = params or WeinsteinParams()
    if ohlcv is None or ohlcv.empty:
        return WeinsteinPendingResult(
            direction=None, since_date=None, since_is_lower_bound=False, band_cushion_pct=None, typical_weekly_move_pct=None, eta=None
        )

    weekly = resample_to_weekly(ohlcv)
    weekly_close = weekly["close"] if not weekly.empty else pd.Series(dtype=float)
    if len(weekly_close) < p.min_weeks_required:
        return WeinsteinPendingResult(
            direction=None, since_date=None, since_is_lower_bound=False, band_cushion_pct=None, typical_weekly_move_pct=None, eta=None
        )

    flags = _stage_flags(weekly_close, p)
    direction = _current_pending_direction(flags)
    if direction is None:
        return WeinsteinPendingResult(
            direction=None, since_date=None, since_is_lower_bound=False, band_cushion_pct=None, typical_weekly_move_pct=None, eta=None
        )

    since_date, since_is_lower_bound = _pending_since(flags, direction)
    band_cushion_pct, typical_weekly_move_pct = _band_cushion_pct(weekly_close, direction, p)
    eta = _eta_report(weekly_close, direction, p)

    return WeinsteinPendingResult(
        direction=direction,
        since_date=since_date,
        since_is_lower_bound=since_is_lower_bound,
        band_cushion_pct=band_cushion_pct,
        typical_weekly_move_pct=typical_weekly_move_pct,
        eta=eta,
    )
