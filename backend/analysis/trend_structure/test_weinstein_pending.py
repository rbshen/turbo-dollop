import numpy as np
import pandas as pd

from analysis.trend_structure.weinstein_pending import (
    SCENARIOS,
    _band_cushion_pct,
    _pending_since,
    _scenario_growth_rate,
    compute_weinstein_pending,
)

EMPTY_OHLCV = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _daily_from_weekly(weekly_closes: list[float], start: str = "2020-01-06") -> pd.DataFrame:
    """Same construction as analysis/trend_structure/test_weinstein.py's own
    _daily_from_weekly -- a business-day daily frame where every day within
    a given week shares that week's target close, so resample_to_weekly's
    W-FRI-then-shift-4-days aggregation reproduces `weekly_closes` exactly."""
    n = len(weekly_closes)
    dates = pd.bdate_range(start=start, periods=n * 5)
    closes = np.repeat(np.asarray(weekly_closes, dtype=float), 5)
    return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000.0}, index=dates)


# A long decline (bear stage) followed by a sharp rally -- confirmed
# (empirically, against this exact series) to pass through a window where
# price has already cleared the +5% band while the 30-week MA slope is
# still negative (falling) from the preceding decline, i.e. genuinely
# "pending_advance": one condition (band) met, the other (slope) not yet.
_DECLINE = [200.0 * (0.985**i) for i in range(60)]
_RALLY = [_DECLINE[-1] * (1.03**i) for i in range(1, 15)]
_PENDING_ADVANCE_CLOSES = _DECLINE + _RALLY  # truncate below at various cutoffs


def test_compute_weinstein_pending_on_empty_frame_is_not_pending():
    result = compute_weinstein_pending(EMPTY_OHLCV)
    assert result.direction is None
    assert result.since_date is None
    assert result.since_is_lower_bound is False
    assert result.band_cushion_pct is None
    assert result.typical_weekly_move_pct is None
    assert result.eta is None


def test_compute_weinstein_pending_below_min_weeks_required_is_not_pending():
    # 20 weeks, well under weinstein.py's MIN_WEEKS_REQUIRED (40) --
    # mirrors compute_weinstein_stage's own thin-history degrade.
    ohlcv = _daily_from_weekly([100.0 + i for i in range(20)])
    result = compute_weinstein_pending(ohlcv)
    assert result.direction is None
    assert result.eta is None


def test_compute_weinstein_pending_detects_pending_advance():
    # cutoff=70 (of the module-level rally fixture): stage="decline",
    # above the +5% band, slope still (mildly) negative -- confirmed via a
    # direct trace of _stage_flags on this exact series.
    ohlcv = _daily_from_weekly(_PENDING_ADVANCE_CLOSES[:70])

    result = compute_weinstein_pending(ohlcv)

    assert result.direction == "advance"
    assert result.since_date is not None
    assert result.since_is_lower_bound is False
    assert result.band_cushion_pct is not None and result.band_cushion_pct > 0
    assert result.typical_weekly_move_pct is not None and result.typical_weekly_move_pct > 0
    assert result.eta is not None
    assert set(result.eta) == set(SCENARIOS)
    for scenario in SCENARIOS:
        s = result.eta[scenario]
        assert s.horizon_exceeded is False
        assert s.weeks_away is not None and s.weeks_away > 0
        assert s.projected_date is not None
        assert s.band_lapsed_before_confirmation is False


def test_compute_weinstein_pending_detects_pending_decline():
    # A flat baseline, a brief upward spike still inside the 30-week
    # window, then a drop that settles below the spike-inflated MA -- at
    # this exact truncation, slope is still (mildly) rising from the
    # spike's own entry into the window while price already sits below the
    # -5% band, i.e. genuinely "pending_decline": band met, slope not yet.
    closes = [100.0] * 40 + [200.0] * 3 + [90.0] * 4
    ohlcv = _daily_from_weekly(closes)

    result = compute_weinstein_pending(ohlcv)

    assert result.direction == "decline"
    assert result.since_date is not None
    assert result.eta is not None
    for scenario in SCENARIOS:
        assert result.eta[scenario].weeks_away is not None


def test_compute_weinstein_pending_flags_horizon_exceeded_and_band_lapsed_for_a_non_converging_scenario():
    """The "chase never converges" edge case (see
    docs/weinstein_pending_confirmation_investigation_2026-09-22.md's LYB/
    AXON/CDE/CTSH findings): a scenario whose assumed growth rate has the
    WRONG sign for the pending direction can never satisfy the slope
    condition once the projection window is fully synthetic, so it's
    reported as horizon_exceeded rather than silently confirming at the
    wrong (Top/Base) stage. Constructed here as a rally that's already
    fading (a small recent pullback) right as it clears the +5% band --
    trend_5's own trailing-average growth reads negative even though the
    ticker is pending_advance, so projecting it forward can never turn
    slope positive."""
    decline = [200.0 * (0.985**i) for i in range(60)]
    rally = [decline[-1] * (1.03**i) for i in range(1, 11)]
    pullback = [rally[-1] * (0.985**i) for i in range(1, 9)]
    ohlcv = _daily_from_weekly((decline + rally + pullback)[:75])

    result = compute_weinstein_pending(ohlcv)

    assert result.direction == "advance"
    assert result.eta is not None
    trend_5 = result.eta["trend_5"]
    assert trend_5.horizon_exceeded is True
    assert trend_5.band_lapsed_before_confirmation is True
    assert trend_5.weeks_away is None
    assert trend_5.projected_date is None
    assert trend_5.growth_rate_pct < 0  # the "wrong sign" for an advance confirmation

    # The other two scenarios aren't fighting a wrong-signed growth
    # assumption and confirm normally within the horizon.
    assert result.eta["flat"].horizon_exceeded is False
    assert result.eta["trend_13"].horizon_exceeded is False


def test_scenario_growth_rate_flat_is_always_zero():
    weekly = pd.Series([100.0, 105.0, 95.0], index=pd.date_range("2020-01-06", periods=3, freq="W-MON"))
    assert _scenario_growth_rate(weekly, "flat") == 0.0


def test_scenario_growth_rate_trend_n_is_the_trailing_average_weekly_return():
    # 5 weeks of a flat +2%/wk compounding return -- trend_5's own trailing
    # average must reproduce it exactly (no rounding surprises from a
    # constant series).
    closes = [100.0 * (1.02**i) for i in range(6)]
    weekly = pd.Series(closes, index=pd.date_range("2020-01-06", periods=6, freq="W-MON"))
    rate = _scenario_growth_rate(weekly, "trend_5")
    assert abs(rate - 0.02) < 1e-9


def test_scenario_growth_rate_with_too_few_points_is_zero():
    weekly = pd.Series([100.0], index=pd.date_range("2020-01-06", periods=1, freq="W-MON"))
    assert _scenario_growth_rate(weekly, "trend_5") == 0.0


def test_band_cushion_pct_reflects_distance_past_threshold():
    # 29 weeks at 100 then a final bar at 120 -- the trailing 30-week MA
    # (MA_LEN) is (29*100 + 120)/30, so the "advance" threshold (MA*1.05)
    # and expected cushion are computed the same way here as inside
    # _band_cushion_pct itself, rather than assuming ma==100.
    closes = [100.0] * 39 + [120.0]
    weekly = pd.Series(closes, index=pd.date_range("2020-01-06", periods=40, freq="W-MON"))
    ma = (29 * 100.0 + 120.0) / 30.0
    threshold = ma * 1.05
    expected_cushion = (120.0 / threshold - 1.0) * 100.0

    cushion, typical_move = _band_cushion_pct(weekly, "advance")

    assert abs(cushion - expected_cushion) < 1e-6
    assert typical_move >= 0


def test_pending_since_returns_none_when_not_currently_pending():
    idx = pd.date_range("2020-01-06", periods=3, freq="W-MON")
    flags = pd.DataFrame({"pending_advance": [True, True, False]}, index=idx)

    since_date, is_lower_bound = _pending_since(flags, "advance")

    assert since_date is None
    assert is_lower_bound is False


def test_pending_since_is_lower_bound_when_pending_since_the_first_row():
    idx = pd.date_range("2020-01-06", periods=4, freq="W-MON")
    flags = pd.DataFrame({"pending_decline": [True, True, True, True]}, index=idx)

    since_date, is_lower_bound = _pending_since(flags, "decline")

    assert since_date == idx[0].date()
    assert is_lower_bound is True


def test_pending_since_walks_back_to_the_start_of_the_current_pending_run():
    idx = pd.date_range("2020-01-06", periods=5, freq="W-MON")
    # False, True, False, True, True -- the CURRENT run only starts at
    # index 3 (the False at index 2 breaks the run started at index 1).
    flags = pd.DataFrame({"pending_advance": [False, True, False, True, True]}, index=idx)

    since_date, is_lower_bound = _pending_since(flags, "advance")

    assert since_date == idx[3].date()
    assert is_lower_bound is False
