import pandas as pd
import pytest

from analysis.liquidity_zones.engine import compute_liquidity_zones


def _ohlc(low: list[float], high: list[float] | None = None) -> pd.DataFrame:
    """Builds a minimal OHLC frame -- Close tracks the midpoint of Low/High
    (or Low itself if High isn't given) so it never itself matters to this
    engine's own swing math, only Low/High do."""
    high = high or [v + 1 for v in low]
    dates = pd.date_range("2024-01-01", periods=len(low), freq="D")
    close = [(lo + hi) / 2 for lo, hi in zip(low, high)]
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": [1000] * len(low)}, index=dates
    )


def test_raises_on_empty_frame():
    with pytest.raises(ValueError):
        compute_liquidity_zones(pd.DataFrame(), swing_bars=2, cluster_pct=2.0, num_zones=3)


def test_zero_valid_zones_when_no_swings_have_formed_yet():
    # Monotonic, thin series -- no confirmed swing lows/highs at all.
    df = _ohlc(low=[float(i) for i in range(6)])

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=2.0, num_zones=3)

    assert result.support == []
    assert result.resistance == []


def test_finds_nearest_unbreached_support_and_resistance():
    # A clean swing low at 90 and swing high at 130, both still unbreached,
    # with price now sitting between them.
    low = [100, 100, 90, 100, 100, 100, 100, 100, 100]
    high = [105, 105, 92, 105, 105, 105, 130, 105, 105]
    df = _ohlc(low=low, high=high)

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=2.0, num_zones=3)

    assert len(result.support) == 1
    assert result.support[0].price == 90.0
    assert len(result.resistance) == 1
    assert result.resistance[0].price == 130.0


def test_stale_zones_on_the_wrong_side_of_last_price_are_filtered_out():
    # An old swing low at 90 that price has since fallen well below (to 50)
    # without a later swing low ever confirming a breach -- still
    # technically "unbreached" per the locked rule, but not a meaningful
    # "support below current price" for the card, so it must be filtered.
    low = [100, 100, 90, 100, 100, 100, 100, 60, 50, 55, 100, 100]
    high = [v + 5 for v in low]
    df = _ohlc(low=low, high=high)

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=2.0, num_zones=3)

    assert all(z.price <= result.last_price for z in result.support)
    assert 90.0 not in [z.price for z in result.support]


def test_num_zones_caps_the_nearest_n_per_side():
    # Four well-separated swing lows, each LATER one HIGHER than the last
    # (a classic rising-higher-lows shape) so none of them breach each
    # other -- all four stay simultaneously valid.
    low = [100] * 30
    for pos, price in [(2, 80), (8, 85), (14, 90), (20, 95)]:
        low[pos] = price
    high = [v + 5 for v in low]
    df = _ohlc(low=low, high=high)

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=0, num_zones=2)

    assert len(result.support) == 2
    assert [z.price for z in result.support] == [95.0, 90.0]  # nearest (highest) first
