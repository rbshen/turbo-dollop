"""Top-level composition: swings -> classification -> state machine ->
regime -> conviction -> TrendStructureResult. The single function
data/trend_analysis_data.py calls; everything below it stays pure (no DB,
no HTTP), matching analysis/ma_magnet's calculation style.
"""

import pandas as pd

from .ad_line import compute_ad_line, compute_chaikin_oscillator
from .atr import compute_atr
from .classification import classify_swings
from .conviction import compute_bar_level, compute_blended_score
from .regime import latest_regime
from .sma_position import compute_sma_position
from .state_machine import run_state_machine
from .swings import extract_swing_points
from .types import CONFIRMED_RATIO, TrendStructureResult


def compute_trend_structure(ohlcv: pd.DataFrame) -> TrendStructureResult:
    """ohlcv must be indexed by date (ascending) with columns
    open/high/low/close/volume (lowercase, matching YahooPriceCache's own
    column names)."""
    close = ohlcv["close"]
    high = ohlcv["high"]
    low = ohlcv["low"]
    volume = ohlcv["volume"]

    # SMA position tracking -- computed straight off `close`, no dependency
    # on swings/ATR/regime, so it's placed right here rather than after them.
    sma20 = compute_sma_position(close, 20)
    sma50 = compute_sma_position(close, 50)
    sma200 = compute_sma_position(close, 200)

    atr_series = compute_atr(high, low, close)
    atr_by_date = {
        (idx.date() if hasattr(idx, "date") else idx): float(value) for idx, value in atr_series.items() if value == value
    }  # value == value excludes NaN without importing math/numpy just for this

    # A/D Bullish Divergence's Chaikin Oscillator, computed inline from the
    # same in-memory OHLCV frame already fetched for ATR/swings above -- no
    # second fetch, no second pass over the ticker's price history, per this
    # feature's own "fold into the existing loop" requirement.
    ad_line = compute_ad_line(high, low, close, volume)
    chaikin_osc = compute_chaikin_oscillator(ad_line)

    swings = extract_swing_points(close)
    classified = classify_swings(swings, atr_by_date, chaikin_osc)
    state = run_state_machine(classified)

    dates = [idx.date() if hasattr(idx, "date") else idx for idx in close.index]
    bars_since_confirmation = None
    if state.last_confirmed_swing is not None and state.last_confirmed_swing.date in dates:
        bars_since_confirmation = len(dates) - 1 - dates.index(state.last_confirmed_swing.date)

    efficiency_ratio, regime = latest_regime(close)

    # The ticker's MOST RECENT confirmed LL swing's own divergence fields --
    # classify_swings already computed these per-swing inline; this just
    # selects which one (if any) surfaces at the top level. False/None when
    # no confirmed LL exists at all (never a flip has happened, or too thin
    # a history).
    confirmed_lls = [cs for cs in classified if cs.classification == "LL" and cs.ratio >= CONFIRMED_RATIO]
    if confirmed_lls:
        latest_ll = confirmed_lls[-1]
        ad_bullish_divergence = latest_ll.ad_bullish_divergence
        ad_divergence_swing_date = latest_ll.ad_divergence_swing_date
    else:
        ad_bullish_divergence = False
        ad_divergence_swing_date = None

    blended_score = compute_blended_score(
        trend_state=state.trend_state,
        magnitude_tier=state.magnitude_tier,
        persistence_count=state.persistence_count,
        bars_since_confirmation=bars_since_confirmation,
        regime=regime,
        warning_flag=state.warning_flag,
        ad_bullish_divergence=ad_bullish_divergence,
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
        ad_bullish_divergence=ad_bullish_divergence,
        ad_divergence_swing_date=ad_divergence_swing_date,
        sma20_position_pct=sma20.position_pct,
        sma20_cross=sma20.cross,
        sma50_position_pct=sma50.position_pct,
        sma50_cross=sma50.cross,
        sma200_position_pct=sma200.position_pct,
        sma200_cross=sma200.cross,
    )
