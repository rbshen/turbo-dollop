import numpy as np
import pandas as pd

from analysis.fvg import FVG_ATR_MULTIPLIER, detect_fvgs
from analysis.warren_signal.indicators import compute_atr_wilder


def _frame(rows: list[tuple[float, float, float]]) -> pd.DataFrame:
    """(high, low, close) rows on consecutive business days."""
    idx = pd.bdate_range("2026-01-05", periods=len(rows))
    return pd.DataFrame(rows, columns=["high", "low", "close"], index=idx)


def _atr(frame: pd.DataFrame, value: float) -> pd.Series:
    return pd.Series(value, index=frame.index, dtype=float)


# c1 high 10 / c2 / c3 low 12 -> bullish gap 10..12 (height 2).
BULL = [(10.0, 9.0, 9.5), (13.0, 9.5, 12.5), (14.0, 12.0, 13.5)]
# c1 low 20 / c3 high 18 -> bearish gap 18..20 (height 2).
BEAR = [(21.0, 20.0, 20.5), (20.5, 17.0, 17.5), (18.0, 16.0, 16.5)]


def test_bullish_and_bearish_geometry():
    bull = detect_fvgs(_frame(BULL), _atr(_frame(BULL), 1.0))
    assert [(g.side, g.bottom, g.top, g.c3_index, g.start_index, g.end_index) for g in bull] == [("bullish", 10.0, 12.0, 2, 3, None)]
    bear = detect_fvgs(_frame(BEAR), _atr(_frame(BEAR), 1.0))
    assert [(g.side, g.bottom, g.top) for g in bear] == [("bearish", 18.0, 20.0)]


def test_size_filter_above_below_and_exactly_equal_threshold():
    frame = _frame(BULL)  # height 2
    assert FVG_ATR_MULTIPLIER == 0.5
    assert len(detect_fvgs(frame, _atr(frame, 3.9))) == 1  # threshold 1.95 < 2
    assert detect_fvgs(frame, _atr(frame, 4.0)) == []  # threshold 2.0 == height: excluded
    assert detect_fvgs(frame, _atr(frame, 4.1)) == []
    assert len(detect_fvgs(frame, _atr(frame, 2.0), mult=0.5)) == 1


def test_zero_height_gap_is_not_a_gap():
    frame = _frame([(10.0, 9.0, 9.5), (13.0, 9.5, 12.5), (14.0, 10.0, 13.5)])  # low(c3) == high(c1)
    assert detect_fvgs(frame, _atr(frame, 0.001)) == []


def test_nan_and_zero_atr_keep_nothing():
    frame = _frame(BULL)
    assert detect_fvgs(frame, _atr(frame, np.nan)) == []
    assert detect_fvgs(frame, _atr(frame, 0.0)) == []


def test_fewer_than_three_bars_and_atr_warmup():
    assert detect_fvgs(_frame(BULL[:2]), _atr(_frame(BULL[:2]), 1.0)) == []
    frame = _frame(BULL)  # 3 bars: the real ATR(14) is still all NaN
    assert detect_fvgs(frame, compute_atr_wilder(frame["high"], frame["low"], frame["close"])) == []


def test_clean_close_through_with_no_earlier_touch_ends_on_c4():
    frame = _frame(BULL + [(11.0, 8.0, 9.0)])  # c4 gaps down through the zone and closes below bottom 10
    (g,) = detect_fvgs(frame, _atr(frame, 1.0))
    assert (g.start_index, g.end_index) == (3, 3)  # one-bar sliver


def test_wick_through_with_close_inside_does_not_end():
    frame = _frame(BULL + [(12.5, 8.0, 10.5)])  # wick below 10, close 10.5 inside
    (g,) = detect_fvgs(frame, _atr(frame, 1.0))
    assert g.end_index is None


def test_close_exactly_on_boundary_does_not_end_bullish_or_bearish():
    bull = _frame(BULL + [(12.0, 9.0, 10.0)])  # close == bottom
    assert detect_fvgs(bull, _atr(bull, 1.0))[0].end_index is None
    bear = _frame(BEAR + [(21.0, 17.0, 20.0)])  # close == top
    assert detect_fvgs(bear, _atr(bear, 1.0))[0].end_index is None


def test_ends_on_first_close_beyond_far_side_later_bar():
    bull = _frame(BULL + [(13.0, 11.0, 12.0), (12.0, 8.0, 9.5), (9.0, 7.0, 8.0)])
    assert detect_fvgs(bull, _atr(bull, 1.0))[0].end_index == 4
    bear = _frame(BEAR + [(19.0, 16.0, 17.0), (21.5, 18.0, 20.5)])
    assert detect_fvgs(bear, _atr(bear, 1.0))[0].end_index == 4


def test_c3_as_last_bar_has_projected_start():
    frame = _frame(BULL)
    (g,) = detect_fvgs(frame, _atr(frame, 1.0))
    assert g.c3_index == len(frame) - 1 and g.start_index == len(frame) and g.end_index is None


def test_atr_filter_does_not_affect_ending():
    frame = _frame(BULL + [(11.0, 8.0, 9.0)])
    (g,) = detect_fvgs(frame, _atr(frame, 1.0))
    assert g.end_index == 3


def test_overlapping_gaps_are_all_reported():
    frame = _frame([(10.0, 9.0, 9.5), (13.0, 9.5, 12.5), (14.0, 12.0, 13.5), (16.0, 13.5, 15.5), (18.0, 15.0, 17.5)])
    gaps = detect_fvgs(frame, _atr(frame, 1.0))
    assert [(g.c3_index, g.bottom, g.top) for g in gaps] == [(2, 10.0, 12.0), (4, 14.0, 15.0)]


def test_compute_atr_wilder_matches_wilder_rma_of_true_range():
    rng = np.random.default_rng(0)
    close = pd.Series(100 + rng.normal(0, 1, 40).cumsum())
    high, low = close + 1.0, close - 1.0
    atr = compute_atr_wilder(high, low, close)
    assert atr.iloc[:13].isna().all() and atr.iloc[13:].notna().all()
    assert atr.iloc[-1] > 0
