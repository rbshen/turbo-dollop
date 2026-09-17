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
        compute_liquidity_zones(pd.DataFrame(), swing_bars=2, cluster_pct=2.0, num_zones=3, breach_recency_bars=6)


def test_zero_valid_zones_when_no_swings_have_formed_yet():
    # Monotonic, thin series -- no confirmed swing lows/highs at all.
    df = _ohlc(low=[float(i) for i in range(6)])

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=2.0, num_zones=3, breach_recency_bars=6)

    assert result.support == []
    assert result.resistance == []


def test_finds_nearest_unbreached_support_and_resistance():
    # A clean swing low at 90 and swing high at 130, both still unbreached,
    # with price now sitting between them.
    low = [100, 100, 90, 100, 100, 100, 100, 100, 100]
    high = [105, 105, 92, 105, 105, 105, 130, 105, 105]
    df = _ohlc(low=low, high=high)

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=2.0, num_zones=3, breach_recency_bars=6)

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

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=2.0, num_zones=3, breach_recency_bars=6)

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

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=0, num_zones=2, breach_recency_bars=6)

    assert len(result.support) == 2
    assert [z.price for z in result.support] == [95.0, 90.0]  # nearest (highest) first


def test_broken_zone_none_when_no_breach_at_all():
    low = [100, 100, 90, 100, 100, 100, 100, 100, 100]
    high = [105, 105, 92, 105, 105, 105, 130, 105, 105]
    df = _ohlc(low=low, high=high)

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=2.0, num_zones=3, breach_recency_bars=6)

    assert result.broken_support is None
    assert result.broken_resistance is None


def test_broken_support_surfaces_within_recency_window_with_no_competing_valid_zone():
    # Swing low at 90 (pos 2), later breached by a lower swing low at 80
    # (pos 8) -- 90 drops out of `support` entirely under the locked
    # breach rule. No other valid support zone exists on this side, so
    # rule 2 (positional) auto-passes. Recency is measured from the
    # zone's OWN formation (pos 2), not the breach bar (pos 8): last_pos -
    # pos = 20 - 2 = 18, exactly at an 18-bar window's boundary (inclusive).
    low = [100] * 21
    low[2] = 90
    low[8] = 80
    high = [v + 5 for v in low]
    df = _ohlc(low=low, high=high)

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=2.0, num_zones=3, breach_recency_bars=18)

    assert result.broken_support is not None
    assert result.broken_support.price == 90.0
    assert result.broken_support.breached_at == df.index[8].date()
    assert 90.0 not in [z.price for z in result.support]


def test_broken_zone_excluded_when_formation_is_outside_the_recency_window_even_if_breach_is_recent():
    # The exact regression this rule was fixed for (MSFT, 2026-09-17): a
    # zone whose OWN formation is old (pos 2) but whose breach bar (pos 8)
    # is recent must NOT qualify -- recency is measured from the zone's
    # own swing point, not from the breach bar. last_pos - pos = 20 - 2 =
    # 18, outside a 6-bar window, even though last_pos - breach_pos =
    # 20 - 8 = 12 would have passed under the old (wrong) rule.
    low = [100] * 21
    low[2] = 90
    low[8] = 80
    high = [v + 5 for v in low]
    df = _ohlc(low=low, high=high)

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=2.0, num_zones=3, breach_recency_bars=6)

    assert result.broken_support is None


def test_broken_zone_excluded_when_breach_is_outside_the_recency_window():
    low = [100] * 21
    low[2] = 90
    low[8] = 80
    high = [v + 5 for v in low]
    df = _ohlc(low=low, high=high)

    # last_pos=20, the zone's own pos=2 -> gap of 18, outside a 5-bar window.
    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=2.0, num_zones=3, breach_recency_bars=5)

    assert result.broken_support is None


def test_broken_support_excluded_when_a_higher_valid_support_already_exists():
    # A resolved/breached low at 90 (pos 2 -> breached at pos 8 by 80), but
    # a genuinely higher, still-valid swing low at 95 forms later (pos 14)
    # and never gets breached -- rule 2 says the broken 90 no longer
    # qualifies, since a real support already sits above it. A generous
    # 20-bar recency window ensures the 90 candidate clears rule 1 (its
    # own formation at pos 2 is 18 bars back), isolating this test to
    # rule 2 (positional) alone.
    low = [100] * 21
    low[2] = 90
    low[8] = 80
    low[14] = 95
    high = [v + 5 for v in low]
    df = _ohlc(low=low, high=high)

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=0, num_zones=3, breach_recency_bars=20)

    assert result.broken_support is None


def test_broken_support_keeps_only_the_most_recent_of_several_in_window_breaches():
    # A strictly-decreasing chain of swing lows: each new, lower swing
    # breaches every prior one still holding a higher price, so 3 of the 4
    # swings end up broken (only the last, lowest one stays valid). All 3
    # broken candidates clear both hard filters -- only the one with the
    # LATEST breach_pos (90, broken by 75 forming at pos 14) should survive.
    low = [100] * 22
    low[2] = 90  # first breached at pos 6 (by 85)
    low[6] = 85  # first breached at pos 10 (by 80)
    low[10] = 80  # first breached at pos 14 (by 75) -- the most recent breach
    low[14] = 75  # never breached, stays valid
    high = [v + 5 for v in low]
    df = _ohlc(low=low, high=high)

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=0, num_zones=3, breach_recency_bars=20)

    assert result.broken_support is not None
    assert result.broken_support.price == 80.0
    assert result.broken_support.breached_at == df.index[14].date()


def test_broken_support_tie_break_prefers_the_later_formed_of_two_simultaneous_breaches():
    # Two independent, non-breaching-each-other swing lows (90 at pos 10,
    # then a HIGHER 95 at pos 15 -- doesn't breach 90 since it's not
    # lower), spaced far enough apart that neither falls in the other's
    # swing-detection window, both get breached by the SAME later, lower
    # swing low (80 at pos 20) -- an exact breach_pos tie. Both clear
    # rule 1 on their OWN formation (last_pos=24: 24-10=14, 24-15=9, both
    # <= a 14-bar window). The later-formed of the two (95, pos 15)
    # should win over the earlier one (90, pos 10).
    low = [100] * 25
    low[10] = 90
    low[15] = 95
    low[20] = 80  # never breached, stays valid; breaches both 90 and 95 at once
    high = [v + 5 for v in low]
    df = _ohlc(low=low, high=high)

    result = compute_liquidity_zones(df, swing_bars=2, cluster_pct=0, num_zones=3, breach_recency_bars=14)

    assert result.broken_support is not None
    assert result.broken_support.price == 95.0
    assert result.broken_support.formed_at == df.index[15].date()
    assert result.broken_support.breached_at == df.index[20].date()
