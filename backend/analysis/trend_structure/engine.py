"""Top-level composition: swings -> classification -> state machine ->
regime -> conviction -> TrendStructureResult. The single function
data/trend_analysis_data.py calls; everything below it stays pure (no DB,
no HTTP), matching analysis/ma_magnet's calculation style.
"""

import pandas as pd

from .atr import compute_atr
from .classification import classify_swings
from .conviction import compute_bar_level, compute_blended_score
from .regime import latest_regime
from .state_machine import run_state_machine
from .swings import extract_swing_points
from .types import TrendStructureResult


def compute_trend_structure(ohlcv: pd.DataFrame) -> TrendStructureResult:
    """ohlcv must be indexed by date (ascending) with columns
    open/high/low/close/volume (lowercase, matching YahooPriceCache's own
    column names)."""
    close = ohlcv["close"]
    high = ohlcv["high"]
    low = ohlcv["low"]

    atr_series = compute_atr(high, low, close)
    atr_by_date = {
        (idx.date() if hasattr(idx, "date") else idx): float(value) for idx, value in atr_series.items() if value == value
    }  # value == value excludes NaN without importing math/numpy just for this

    swings = extract_swing_points(close)
    classified = classify_swings(swings, atr_by_date)
    state = run_state_machine(classified)

    dates = [idx.date() if hasattr(idx, "date") else idx for idx in close.index]
    bars_since_confirmation = None
    if state.last_confirmed_swing is not None and state.last_confirmed_swing.date in dates:
        bars_since_confirmation = len(dates) - 1 - dates.index(state.last_confirmed_swing.date)

    efficiency_ratio, regime = latest_regime(close)

    blended_score = compute_blended_score(
        trend_state=state.trend_state,
        magnitude_tier=state.magnitude_tier,
        persistence_count=state.persistence_count,
        bars_since_confirmation=bars_since_confirmation,
        regime=regime,
        warning_flag=state.warning_flag,
    )
    bar_level = compute_bar_level(blended_score)

    return TrendStructureResult(
        trend_state=state.trend_state,
        magnitude_tier=state.magnitude_tier,
        persistence_count=state.persistence_count,
        bars_since_confirmation=bars_since_confirmation,
        last_confirmed_swing=state.last_confirmed_swing,
        warning_flag=state.warning_flag,
        warning_swing=state.warning_swing,
        efficiency_ratio=efficiency_ratio,
        regime=regime,
        blended_score=blended_score,
        bar_level=bar_level,
    )
