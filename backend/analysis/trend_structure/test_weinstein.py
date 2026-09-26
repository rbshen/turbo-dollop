import numpy as np
import pandas as pd

from analysis.trend_structure.weinstein import (
    WeinsteinParams,
    _stage_since,
    compute_ma,
    next_state,
    compute_stage_series,
    compute_weinstein_stage,
    resample_to_weekly,
)

# The pre-2026-09-26 engine's fixed settings (30-week SMA, 30-week volume
# average). The hand-verified traces below were built against these, so they
# pin the SMA path explicitly; the EMA default has its own tests further down.
LEGACY = WeinsteinParams(ma_type="SMA", volume_avg_length=30)
MIN_WEEKS_REQUIRED = LEGACY.min_weeks_required

EMPTY_OHLCV = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _daily_from_weekly(weekly_closes: list[float], weekly_volumes: list[float], start: str = "2020-01-06") -> pd.DataFrame:
    """Builds a business-day daily OHLCV frame where every day within a
    given week shares that week's target close, and that week's target
    volume is split evenly across its 5 days -- so resample_to_weekly's
    W-FRI-then-shift-4-days aggregation reproduces `weekly_closes`/
    `weekly_volumes` exactly. Lets tests target compute_weinstein_stage's
    WEEKLY behavior precisely without fighting resampling ambiguity."""
    n = len(weekly_closes)
    dates = pd.bdate_range(start=start, periods=n * 5)
    closes = np.repeat(np.asarray(weekly_closes, dtype=float), 5)
    volumes = np.repeat(np.asarray(weekly_volumes, dtype=float) / 5.0, 5)
    return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes, "volume": volumes}, index=dates)


def test_resample_to_weekly_matches_native_yfinance_monday_anchoring():
    # Two full Mon-Fri weeks -- distinct per-day values so aggregation is
    # unambiguous, and the resulting index must land on each week's Monday.
    dates = pd.bdate_range("2024-01-01", periods=10)  # Mon 1/1 .. Fri 1/12
    ohlcv = pd.DataFrame(
        {
            "open": [10, 11, 12, 13, 14, 20, 21, 22, 23, 24],
            "high": [15, 16, 17, 18, 19, 25, 26, 27, 28, 29],
            "low": [5, 6, 7, 8, 9, 15, 16, 17, 18, 19],
            "close": [11, 12, 13, 14, 20, 21, 22, 23, 24, 30],
            "volume": [100, 100, 100, 100, 100, 200, 200, 200, 200, 200],
        },
        index=dates,
    )

    weekly = resample_to_weekly(ohlcv)

    assert len(weekly) == 2
    assert list(weekly.index.date) == [pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-01-08").date()]
    assert weekly["open"].iloc[0] == 10  # first day of week 1
    assert weekly["high"].iloc[0] == 19  # max across week 1
    assert weekly["low"].iloc[0] == 5  # min across week 1
    assert weekly["close"].iloc[0] == 20  # last day (Friday) of week 1
    assert weekly["volume"].iloc[0] == 500  # sum across week 1
    assert weekly["close"].iloc[1] == 30
    assert weekly["volume"].iloc[1] == 1000


def test_resample_to_weekly_of_an_empty_frame_returns_empty():
    assert resample_to_weekly(EMPTY_OHLCV).empty


def test_compute_stage_series_reaches_all_four_states():
    # Bootstrap+flat (base), then a sustained uptrend (advance), a gentle
    # roll-over (top), then a sharp decline (decline) -- empirically
    # verified transitions land at indices 34 (bootstrap ends -> base),
    # 47 (base -> advance), 113 (advance -> top), 115 (top -> decline).
    seg1 = [100.0] * 45
    seg2 = [100.0 * (1.02**i) for i in range(1, 41)]
    seg3 = [seg2[-1] * (0.997**i) for i in range(1, 31)]
    seg4 = [seg3[-1] * (0.98**i) for i in range(1, 41)]
    closes = seg1 + seg2 + seg3 + seg4
    idx = pd.date_range("2020-01-06", periods=len(closes), freq="W-MON")
    weekly_close = pd.Series(closes, index=idx)

    stage = compute_stage_series(weekly_close, LEGACY)["stage"]

    assert stage.iloc[:34].isna().all()  # pre-bootstrap
    assert stage.iloc[40] == "base"
    assert stage.iloc[80] == "advance"
    assert stage.iloc[113] == "top"
    assert stage.iloc[-1] == "decline"
    assert set(stage.dropna().unique()) == {"base", "advance", "top", "decline"}


def test_stage_since_returns_none_when_no_valid_week_exists():
    idx = pd.date_range("2020-01-06", periods=2, freq="W-MON")
    stage = pd.Series([None, None], index=idx)

    since_date, is_lower_bound = _stage_since(stage)

    assert since_date is None
    assert is_lower_bound is False


def test_stage_since_is_lower_bound_when_stage_never_differs():
    idx = pd.date_range("2020-01-06", periods=5, freq="W-MON")
    stage = pd.Series([None, "advance", "advance", "advance", "advance"], index=idx)

    since_date, is_lower_bound = _stage_since(stage)

    assert since_date == idx[1].date()
    assert is_lower_bound is True


def test_stage_since_ignores_pre_bootstrap_none_weeks():
    # Regression test: the walk-back must treat the leading None (pre-
    # bootstrap) weeks as absent, not as "a week with a differing stage" --
    # otherwise a transition landing right at the end of bootstrap would be
    # misread.
    idx = pd.date_range("2020-01-06", periods=6, freq="W-MON")
    stage = pd.Series([None, None, "base", "base", "advance", "advance"], index=idx)

    since_date, is_lower_bound = _stage_since(stage)

    assert since_date == idx[4].date()
    assert is_lower_bound is False


def test_stage_since_finds_a_real_transition_when_one_exists():
    idx = pd.date_range("2020-01-06", periods=4, freq="W-MON")
    stage = pd.Series(["base", "base", "advance", "advance"], index=idx)

    since_date, is_lower_bound = _stage_since(stage)

    assert since_date == idx[2].date()
    assert is_lower_bound is False


def test_compute_weinstein_stage_degrades_gracefully_below_min_weeks():
    thin = _daily_from_weekly([100.0] * (MIN_WEEKS_REQUIRED - 1), [1_000_000] * (MIN_WEEKS_REQUIRED - 1))

    result = compute_weinstein_stage(thin, EMPTY_OHLCV, LEGACY)

    assert result.stage is None
    assert result.stage_since_date is None
    assert result.stage_since_is_lower_bound is False
    # weeks_available is a real count even in the degraded path -- this is
    # exactly what distinguishes "a real compute ran and genuinely found
    # too little history" (this case) from "never computed at all" (a
    # persisted row where this column itself reads NULL -- see
    # models.py::TrendAnalysis's own comment).
    assert result.weeks_available == MIN_WEEKS_REQUIRED - 1
    assert result.ma_slope_pct is None
    assert result.vs_ma_pct is None
    assert result.volume_ratio is None
    assert result.mansfield_rs is None
    assert result.breakout_confirmed is False


def test_compute_weinstein_stage_empty_benchmark_gives_none_mansfield_rs_without_crashing():
    weekly_closes = [100.0] * 46 + [130.0]
    ohlcv = _daily_from_weekly(weekly_closes, [1_000_000] * 47)

    result = compute_weinstein_stage(ohlcv, EMPTY_OHLCV, LEGACY)

    assert result.stage == "advance"
    assert result.mansfield_rs is None


def test_breakout_confirmed_true_with_high_volume_and_no_rs_data():
    # A fresh base -> advance transition on the final week (verified via
    # compute_stage_series: week 46 is "base", week 47 is "advance"), with
    # 2.8x average volume clearing the 2.0x confirmation multiplier. No
    # benchmark data at all -- Mansfield RS's na()-passes-through rule
    # means missing RS data does not block a breakout.
    weekly_closes = [100.0] * 46 + [130.0]
    weekly_volumes = [1_000_000] * 46 + [3_000_000]
    ohlcv = _daily_from_weekly(weekly_closes, weekly_volumes)

    result = compute_weinstein_stage(ohlcv, EMPTY_OHLCV, LEGACY)

    assert result.stage == "advance"
    assert result.weeks_available == 47
    assert result.volume_ratio == 2.8125
    assert result.breakout_confirmed is True


def test_breakout_confirmed_false_when_volume_does_not_confirm():
    weekly_closes = [100.0] * 46 + [130.0]
    weekly_volumes = [1_000_000] * 46 + [1_100_000]  # only 1.1x average

    ohlcv = _daily_from_weekly(weekly_closes, weekly_volumes)

    result = compute_weinstein_stage(ohlcv, EMPTY_OHLCV, LEGACY)

    assert result.stage == "advance"
    assert result.volume_ratio < 2.0
    assert result.breakout_confirmed is False


def test_breakout_confirmed_true_when_ticker_outperforms_benchmark():
    weekly_closes = [100.0] * 60 + [130.0]
    ohlcv = _daily_from_weekly(weekly_closes, [1_000_000] * 60 + [3_000_000])
    benchmark_flat = _daily_from_weekly([100.0] * 61, [1_000_000] * 61)

    result = compute_weinstein_stage(ohlcv, benchmark_flat, LEGACY)

    assert result.mansfield_rs > 0
    assert result.breakout_confirmed is True


def test_breakout_confirmed_false_when_benchmark_outperforms():
    # The benchmark jumps even harder than the ticker in the breakout week,
    # so the ticker's relative strength vs. its own 52-week trailing
    # average actually falls -- Mansfield RS goes negative and blocks the
    # breakout despite ample volume.
    weekly_closes = [100.0] * 60 + [130.0]
    ohlcv = _daily_from_weekly(weekly_closes, [1_000_000] * 60 + [3_000_000])
    benchmark_bigger_jump = _daily_from_weekly([100.0] * 60 + [300.0], [1_000_000] * 61)

    result = compute_weinstein_stage(ohlcv, benchmark_bigger_jump, LEGACY)

    assert result.mansfield_rs < 0
    assert result.breakout_confirmed is False


# --- configurable engine (EMA default, Settings-driven) ---------------------


def test_default_params_are_the_validated_pine_reference_values():
    p = WeinsteinParams()
    assert (p.ma_length, p.ma_type, p.within_range_pct, p.slope_lookback) == (30, "EMA", 5.0, 5)
    assert (p.breakout_volume_mult, p.volume_avg_length, p.rs_benchmark, p.rs_smoothing_length) == (2.0, 50, "SPY", 52)
    assert WeinsteinParams.from_json(p.to_json()) == p
    assert WeinsteinParams.from_json(None) is None
    assert WeinsteinParams.from_json("not json") is None


def test_compute_ma_ema_and_sma_differ_and_mask_the_first_length_weeks():
    close = pd.Series(np.arange(1.0, 41.0))
    ema = compute_ma(close, 10, "EMA")
    sma = compute_ma(close, 10, "SMA")
    assert ema.iloc[:9].isna().all() and sma.iloc[:9].isna().all()
    assert sma.iloc[9] == 5.5
    assert ema.iloc[-1] != sma.iloc[-1]
    assert compute_ma(close, 10, "ema").equals(ema)  # case-insensitive
    try:
        compute_ma(close, 10, "WMA")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown ma_type must raise")


def test_next_state_transition_table():
    # (prev, rising, falling, above, below) -> next; 0 = first valid week.
    cases = [
        ((0, True, False, True, False), 2),
        ((0, False, True, False, True), 4),
        ((0, True, False, False, False), 3),
        ((0, False, False, False, False), 1),
        ((2, False, True, False, True), 4),
        ((2, False, False, True, False), 3),  # slope no longer rising -> Top
        ((2, True, False, False, False), 2),
        ((3, True, False, True, False), 2),
        ((3, False, True, False, True), 4),
        ((3, False, False, False, False), 3),
        ((4, True, False, True, False), 2),
        ((4, False, False, False, False), 1),  # decline stops falling -> Base
        ((4, False, True, False, False), 4),
        ((1, False, True, False, True), 4),
        ((1, True, False, True, False), 2),
        ((1, True, False, False, False), 1),
    ]
    for args, expected in cases:
        assert next_state(*args) == expected, args


def _uptrend_then_dip_weekly() -> pd.Series:
    closes = [100.0] * 45 + [100.0 * (1.02**i) for i in range(1, 41)] + [130.0 * (0.985**i) for i in range(1, 30)]
    return pd.Series(closes, index=pd.date_range("2020-01-06", periods=len(closes), freq="W-MON"))


def test_ema_reacts_sooner_than_sma_to_a_rollover():
    weekly = _uptrend_then_dip_weekly()
    ema = compute_stage_series(weekly, WeinsteinParams(ma_type="EMA"))["stage"]
    sma = compute_stage_series(weekly, WeinsteinParams(ma_type="SMA"))["stage"]
    first_non_advance = lambda s: next(i for i in range(60, len(s)) if s.iloc[i] != "advance")  # noqa: E731
    assert first_non_advance(ema) <= first_non_advance(sma)


def test_within_range_pct_and_slope_lookback_are_honoured():
    weekly = _uptrend_then_dip_weekly()
    wide = compute_stage_series(weekly, WeinsteinParams(ma_type="SMA", within_range_pct=40.0))["stage"]
    tight = compute_stage_series(weekly, WeinsteinParams(ma_type="SMA", within_range_pct=0.0))["stage"]
    assert "advance" not in set(wide.dropna())  # a 40% band is never cleared
    assert "advance" in set(tight.dropna())
    fast = compute_stage_series(weekly, WeinsteinParams(ma_type="SMA", slope_lookback=1))
    slow = compute_stage_series(weekly, WeinsteinParams(ma_type="SMA", slope_lookback=20))
    assert fast["valid"].sum() > slow["valid"].sum()


def test_min_weeks_scales_with_the_configured_lengths():
    p = WeinsteinParams(ma_length=10, slope_lookback=3)
    assert p.min_weeks_required == 18
    thin = _daily_from_weekly([100.0] * 17, [1e6] * 17)
    ok = _daily_from_weekly([100.0] * 18, [1e6] * 18)
    assert compute_weinstein_stage(thin, EMPTY_OHLCV, p).stage is None
    assert compute_weinstein_stage(ok, EMPTY_OHLCV, p).stage is not None


def test_breakout_volume_multiplier_and_average_length_are_honoured():
    weekly_closes = [100.0] * 46 + [130.0]
    volumes = [1_000_000] * 46 + [3_000_000]
    ohlcv = _daily_from_weekly(weekly_closes, volumes)
    base = dict(ma_type="SMA", volume_avg_length=30)
    assert compute_weinstein_stage(ohlcv, EMPTY_OHLCV, WeinsteinParams(breakout_volume_mult=2.0, **base)).breakout_confirmed is True
    assert compute_weinstein_stage(ohlcv, EMPTY_OHLCV, WeinsteinParams(breakout_volume_mult=3.0, **base)).breakout_confirmed is False


def test_stage_since_is_the_date_of_the_most_recent_real_transition():
    weekly = _uptrend_then_dip_weekly()
    df = compute_stage_series(weekly, WeinsteinParams())
    daily = _daily_from_weekly(list(weekly.values), [1e6] * len(weekly))
    result = compute_weinstein_stage(daily, EMPTY_OHLCV, WeinsteinParams())
    stages = df["stage"].dropna()
    changed = stages[stages != stages.shift()].index[-1]
    assert result.stage == stages.iloc[-1]
    assert str(result.stage_since_date) == str(changed.date())
