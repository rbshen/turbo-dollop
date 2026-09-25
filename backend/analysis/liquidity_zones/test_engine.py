import pandas as pd
import pytest

from analysis.liquidity_zones.engine import compute_liquidity_zones
from analysis.liquidity_zones.types import LiquidityZoneSettings


def _ohlc(low: list[float], high: list[float] | None = None) -> pd.DataFrame:
    """Minimal OHLC frame -- Close tracks the midpoint of Low/High."""
    high = high or [v + 5 for v in low]
    dates = pd.date_range("2024-01-01", periods=len(low), freq="D")
    close = [(lo + hi) / 2 for lo, hi in zip(low, high)]
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": [1000] * len(low)}, index=dates
    )


def _s(**kw) -> LiquidityZoneSettings:
    base = dict(swing_bars_each_side=2, cluster_pct=0.0, max_lps_per_side=10, breach_recency_bars=5)
    base.update(kw)
    return LiquidityZoneSettings(**base)


def test_raises_on_empty_frame():
    with pytest.raises(ValueError):
        compute_liquidity_zones(pd.DataFrame(), _s())


def test_zero_valid_zones_when_no_swings_have_formed_yet():
    result = compute_liquidity_zones(_ohlc(low=[float(i) for i in range(6)]), _s())

    assert result.support == [] and result.resistance == []


def test_finds_unbreached_support_and_resistance():
    low = [100, 100, 90, 100, 100, 100, 100, 100, 100]
    high = [105, 105, 92, 105, 105, 105, 130, 105, 105]

    result = compute_liquidity_zones(_ohlc(low, high), _s(cluster_pct=2.0))

    assert [z.price for z in result.support] == [90.0]
    assert [z.price for z in result.resistance] == [130.0]
    assert result.broken_support is None and result.broken_resistance is None


def test_ordinary_bar_dipping_below_a_level_breaches_it():
    # Swing low 90 at pos 2; a non-swing (tied) dip to 80 at pos 5-6 breaches it.
    low = [100, 100, 90, 100, 100, 80, 80, 100, 100, 100, 100, 100]

    result = compute_liquidity_zones(_ohlc(low), _s(breach_recency_bars=20))

    assert 90.0 not in [z.price for z in result.support]
    assert result.broken_support is not None
    assert result.broken_support.price == 90.0
    assert result.broken_support.breached_at == result.as_of.replace(day=6)  # pos 5 -> Jan 6


def test_cap_keeps_nearest_to_price_or_most_recent():
    # Four rising swing lows (none breach each other).
    low = [100] * 30
    for pos, price in [(2, 80), (8, 85), (14, 90), (20, 95)]:
        low[pos] = price
    df = _ohlc(low)

    nearest = compute_liquidity_zones(df, _s(max_lps_per_side=2, over_cap_priority="nearest_price"))
    recent = compute_liquidity_zones(df, _s(max_lps_per_side=2, over_cap_priority="most_recent"))

    assert [z.price for z in nearest.support] == [95.0, 90.0]
    assert [z.price for z in recent.support] == [95.0, 90.0]  # latest formed are also the highest here

    # The newest zone (70) is the farthest from price -- most_recent keeps it
    # even when nearest_price would not. It also breaches 95 and 96.
    low3 = [100] * 30
    for pos, price in [(2, 95), (8, 96), (14, 70)]:
        low3[pos] = price
    d3 = _ohlc(low3)
    r = compute_liquidity_zones(d3, _s(max_lps_per_side=1, over_cap_priority="most_recent"))
    assert [z.price for z in r.support] == [70.0]


def test_kept_breached_support_must_sit_above_best_valid_support():
    # Broken 90 (breached by 80 at pos 8), but a valid, unbreached support at 95 forms later.
    low = [100] * 21
    low[2], low[8], low[14] = 90, 80, 95
    # 80 at pos 8 breaches 90 only when the ordinary-bar rule sees it; 95 (pos 14) is never breached.
    result = compute_liquidity_zones(_ohlc(low), _s(breach_recency_bars=20))

    assert result.broken_support is None  # 90 < threshold 95 -> wrong side


def test_kept_breached_support_picks_lowest_candidate_above_threshold():
    # No valid support at the end: 90, 85 and 80 all end up breached by the later 70.
    low = [100] * 30
    low[2], low[8], low[14], low[20] = 90, 85, 80, 70
    # 70 at pos 20 is a swing low itself and stays valid -> threshold 70; candidates 90/85/80 are above it.
    result = compute_liquidity_zones(_ohlc(low), _s(breach_recency_bars=50))

    assert result.broken_support is not None
    assert result.broken_support.price == 80.0  # closest to the threshold


def test_recency_filter_can_be_toggled():
    low = [100] * 21
    low[2], low[8] = 90, 80
    df = _ohlc(low)

    recent = compute_liquidity_zones(df, _s(breach_recency_bars=5))  # breached at pos 8, last_pos 20 -> 12 bars
    anytime = compute_liquidity_zones(df, _s(breach_recency_bars=5, only_keep_if_breached_recently=False))
    edge = compute_liquidity_zones(df, _s(breach_recency_bars=12))

    assert recent.broken_support is None
    assert anytime.broken_support is not None and anytime.broken_support.price == 90.0
    assert edge.broken_support is not None  # inclusive boundary


def test_recency_is_measured_from_the_breach_bar_not_the_formation():
    low = [100] * 21
    low[2] = 90
    low[17] = 80  # breaches 90 only at pos 17 -> 3 bars before last
    result = compute_liquidity_zones(_ohlc(low), _s(breach_recency_bars=3))

    assert result.broken_support is not None and result.broken_support.price == 90.0


def test_keep_flags_disable_each_side_independently():
    low = [100] * 21
    high = [105] * 21
    low[2], low[8] = 90, 80
    high[2], high[8] = 110, 120
    df = _ohlc(low, high)
    s = _s(breach_recency_bars=50)

    both = compute_liquidity_zones(df, s)
    no_support = compute_liquidity_zones(df, _s(breach_recency_bars=50, keep_last_breached_support=False))
    no_resistance = compute_liquidity_zones(df, _s(breach_recency_bars=50, keep_last_breached_resistance=False))

    assert both.broken_support is not None and both.broken_resistance is not None
    assert no_support.broken_support is None and no_support.broken_resistance is not None
    assert no_resistance.broken_resistance is None and no_resistance.broken_support is not None


def test_kept_breached_threshold_uses_raw_valid_swings_not_cluster_representatives():
    # Valid supports 94 (pos 14) and 95 (pos 20) cluster at 2% into a zone
    # represented by 94, but the raw highest valid support is 95. The breached
    # 94.5 (pos 2, broken by the 90 at pos 8) sits above the cluster rep (94)
    # yet BELOW the raw threshold (95) -> must not be kept.
    low = [100.0] * 30
    low[2], low[8], low[14], low[20] = 94.5, 90.0, 94.0, 95.0
    result = compute_liquidity_zones(_ohlc(low), _s(cluster_pct=2.0, breach_recency_bars=50))

    assert 94.0 in [z.price for z in result.support]  # 94/95 clustered to 94
    assert result.broken_support is None
