"""Hand-checkable fixtures for scoring/etf_returns.py -- window boundaries,
the YTD base, young funds, stale/partial data. Every series is flat at a
sentinel except at the exact dates under test, so a wrong base date changes
the answer instead of hiding inside a smooth trend."""

import pandas as pd
from pytest import approx

from scoring.etf_returns import WINDOWS, compute_window_returns


def _flat_series(start: str, end: str, value: float = 999.0) -> pd.Series:
    """Business-day series at a decoy value, so any window that lands on a
    day other than the one a test seeded reads as obviously wrong."""
    return pd.Series(value, index=pd.bdate_range(start=start, end=end))


def _by_window(results):
    return {r.window: r for r in results}


def test_windows_come_back_in_fixed_order():
    series = _flat_series("2024-01-01", "2026-09-18")
    assert [r.window for r in compute_window_returns(series, pd.Timestamp("2026-09-18"))] == list(WINDOWS)


def test_each_window_measures_from_its_own_calendar_offset_base():
    # Anchor Fri 2026-09-18. Calendar targets: 1d 09-17, 1w 09-11, 1m 08-18,
    # 3m 06-18, 6m 03-18, 9m 2025-12-18, 1y 2025-09-18; YTD base is 2025-12-31.
    series = _flat_series("2024-01-01", "2026-09-18")
    series[pd.Timestamp("2026-09-18")] = 110.0
    bases = {
        "2026-09-17": 105.0,  # 1d  -> ~+4.76%
        "2026-09-11": 100.0,  # 1w  -> +10%
        "2026-08-18": 50.0,  # 1m  -> +120%
        "2026-06-18": 200.0,  # 3m  -> -45%
        "2026-03-18": 110.0,  # 6m  -> 0%
        "2025-12-18": 55.0,  # 9m  -> +100%
        "2025-12-31": 88.0,  # ytd -> +25%
        "2025-09-18": 220.0,  # 1y  -> -50%
    }
    for day, price in bases.items():
        series[pd.Timestamp(day)] = price

    got = _by_window(compute_window_returns(series, pd.Timestamp("2026-09-18")))

    expected = {
        "1d": (110.0 / 105.0 - 1.0) * 100.0,
        "1w": 10.0,
        "1m": 120.0,
        "3m": -45.0,
        "6m": 0.0,
        "9m": 100.0,
        "ytd": 25.0,
        "1y": -50.0,
    }
    for window, pct in expected.items():
        assert got[window].return_pct == approx(pct, abs=1e-9), window
    assert got["1d"].base_date.isoformat() == "2026-09-17"
    assert got["1w"].base_date.isoformat() == "2026-09-11"
    assert got["1m"].base_date.isoformat() == "2026-08-18"
    assert got["3m"].base_date.isoformat() == "2026-06-18"
    assert got["6m"].base_date.isoformat() == "2026-03-18"
    assert got["9m"].base_date.isoformat() == "2025-12-18"
    assert got["ytd"].base_date.isoformat() == "2025-12-31"
    assert got["1y"].base_date.isoformat() == "2025-09-18"


def test_1d_measures_from_the_prior_trading_day_not_a_calendar_offset():
    # Anchor Mon 2026-09-21: "1 calendar day back" is Sun 09-20 (no bar), so
    # 1D must fall back to Friday 09-18's close -- the actual prior trading
    # day -- never the following Monday and never a straight 24h lookback.
    series = _flat_series("2024-01-01", "2026-09-21")
    series[pd.Timestamp("2026-09-18")] = 80.0  # Fri close (the real "prior day")
    series[pd.Timestamp("2026-09-21")] = 100.0  # Mon anchor

    one_day = _by_window(compute_window_returns(series, pd.Timestamp("2026-09-21")))["1d"]

    assert one_day.base_date.isoformat() == "2026-09-18"
    assert one_day.return_pct == approx(25.0, abs=1e-9)


def test_1d_falls_back_across_a_holiday_to_the_prior_session():
    # 1d from Tue 2026-09-08 (day after Labor Day, Mon 2026-09-07) targets
    # Mon 2026-09-07 itself -- a real calendar day, but a holiday with no bar
    # -- so it must fall back one more step to Fri 2026-09-04.
    series = _flat_series("2025-01-01", "2026-09-08").drop(pd.Timestamp("2026-09-07"))
    series[pd.Timestamp("2026-09-04")] = 90.0
    series[pd.Timestamp("2026-09-08")] = 99.0

    one_day = _by_window(compute_window_returns(series, pd.Timestamp("2026-09-08")))["1d"]

    assert one_day.base_date.isoformat() == "2026-09-04"
    assert one_day.return_pct == approx(10.0, abs=1e-9)


def test_weekend_target_falls_back_to_the_prior_trading_bar():
    # Anchor Tue 2026-11-03: the 1m target is Sat 2026-10-03 and the 6m
    # target is Sun 2026-05-03 -- both must use the Friday before, never
    # the following Monday.
    series = _flat_series("2025-01-01", "2026-11-03")
    series[pd.Timestamp("2026-11-03")] = 100.0
    series[pd.Timestamp("2026-10-02")] = 80.0  # Fri before the 1m target
    series[pd.Timestamp("2026-10-05")] = 1.0  # Mon after -- must not be picked
    series[pd.Timestamp("2026-05-01")] = 125.0  # Fri before the 6m target
    series[pd.Timestamp("2026-05-04")] = 1.0

    got = _by_window(compute_window_returns(series, pd.Timestamp("2026-11-03")))

    assert got["1m"].base_date.isoformat() == "2026-10-02"
    assert got["1m"].return_pct == approx(25.0, abs=1e-9)
    assert got["6m"].base_date.isoformat() == "2026-05-01"
    assert got["6m"].return_pct == approx(-20.0, abs=1e-9)


def test_holiday_target_falls_back_to_the_prior_session():
    # 9m from Fri 2026-09-25 targets 2025-12-25 (Christmas, no bar).
    series = _flat_series("2025-01-01", "2026-09-25").drop(pd.Timestamp("2025-12-25"))
    series[pd.Timestamp("2026-09-25")] = 150.0
    series[pd.Timestamp("2025-12-24")] = 100.0
    series[pd.Timestamp("2025-12-26")] = 1.0

    got = _by_window(compute_window_returns(series, pd.Timestamp("2026-09-25")))

    assert got["9m"].base_date.isoformat() == "2025-12-24"
    assert got["9m"].return_pct == approx(50.0, abs=1e-9)


def test_ytd_base_is_the_prior_years_last_close_not_the_first_of_the_year():
    # 2022-12-31 was a Saturday, so the base is Fri 2022-12-30 -- and the
    # first 2023 close (Tue 01-03) must not be used.
    series = _flat_series("2022-01-03", "2023-03-15")
    series[pd.Timestamp("2022-12-30")] = 100.0
    series[pd.Timestamp("2023-01-03")] = 400.0
    series[pd.Timestamp("2023-03-15")] = 120.0

    ytd = _by_window(compute_window_returns(series, pd.Timestamp("2023-03-15")))["ytd"]

    assert ytd.base_date.isoformat() == "2022-12-30"
    assert ytd.return_pct == approx(20.0, abs=1e-9)


def test_ytd_on_the_first_session_of_the_year_is_a_one_day_return():
    series = _flat_series("2025-06-02", "2026-01-02")
    series[pd.Timestamp("2025-12-31")] = 200.0
    series[pd.Timestamp("2026-01-02")] = 210.0

    ytd = _by_window(compute_window_returns(series, pd.Timestamp("2026-01-02")))["ytd"]

    assert ytd.base_date.isoformat() == "2025-12-31"
    assert ytd.return_pct == approx(5.0, abs=1e-9)


def test_ytd_at_year_end_covers_the_whole_year():
    # Anchor on Dec 31 itself: the base is the PRIOR year's Dec 31, not the anchor.
    series = _flat_series("2024-06-03", "2025-12-31")
    series[pd.Timestamp("2024-12-31")] = 100.0
    series[pd.Timestamp("2025-12-31")] = 130.0

    ytd = _by_window(compute_window_returns(series, pd.Timestamp("2025-12-31")))["ytd"]

    assert ytd.base_date.isoformat() == "2024-12-31"
    assert ytd.return_pct == approx(30.0, abs=1e-9)


def test_young_fund_is_null_for_windows_it_has_no_history_for_never_imputed():
    # History starts 2026-06-01: 1w/1m/3m exist; 6m/9m/1y have no bar on/before
    # their target, and so does YTD (nothing on/before 2025-12-31).
    series = _flat_series("2026-06-01", "2026-09-18", value=100.0)
    series[pd.Timestamp("2026-09-18")] = 110.0

    got = _by_window(compute_window_returns(series, pd.Timestamp("2026-09-18")))

    for window in ("1w", "1m", "3m"):
        assert got[window].return_pct == approx(10.0, abs=1e-9), window
    for window in ("6m", "9m", "ytd", "1y"):
        assert got[window].return_pct is None, window
        assert got[window].base_date is None, window


def test_stale_latest_bar_nulls_every_window():
    series = _flat_series("2024-01-01", "2026-09-10")  # last bar 8 days before the anchor
    got = compute_window_returns(series, pd.Timestamp("2026-09-18"))
    assert all(r.return_pct is None and r.base_date is None for r in got)


def test_a_fund_missing_only_the_anchor_day_still_computes_within_the_stale_tolerance():
    series = _flat_series("2024-01-01", "2026-09-17", value=100.0)  # no Fri 09-18 bar
    series[pd.Timestamp("2026-09-17")] = 130.0
    series[pd.Timestamp("2026-09-11")] = 100.0

    one_week = _by_window(compute_window_returns(series, pd.Timestamp("2026-09-18")))["1w"]

    assert one_week.return_pct == approx(30.0, abs=1e-9)


def test_bars_after_the_anchor_are_ignored():
    # e.g. an in-progress same-day bar: the anchor is the completed session.
    series = _flat_series("2024-01-01", "2026-09-21", value=100.0)
    series[pd.Timestamp("2026-09-18")] = 110.0
    series[pd.Timestamp("2026-09-21")] = 5000.0

    got = _by_window(compute_window_returns(series, pd.Timestamp("2026-09-18")))

    assert got["1w"].return_pct == approx(10.0, abs=1e-9)


def test_non_positive_base_close_is_null_not_a_division_artifact():
    series = _flat_series("2024-01-01", "2026-09-18", value=100.0)
    series[pd.Timestamp("2026-09-11")] = 0.0

    got = _by_window(compute_window_returns(series, pd.Timestamp("2026-09-18")))

    assert got["1w"].return_pct is None
    assert got["1m"].return_pct == approx(0.0, abs=1e-9)


def test_unsorted_tz_aware_series_with_nans_is_normalized():
    series = _flat_series("2024-01-01", "2026-09-18", value=100.0)
    series[pd.Timestamp("2026-09-18")] = 110.0
    series[pd.Timestamp("2026-09-17")] = float("nan")
    scrambled = series.sample(frac=1.0, random_state=1)
    scrambled.index = scrambled.index.tz_localize("America/New_York")

    got = _by_window(compute_window_returns(scrambled, pd.Timestamp("2026-09-18")))

    assert got["1w"].return_pct == approx(10.0, abs=1e-9)


def test_empty_series_is_all_null():
    got = compute_window_returns(pd.Series(dtype=float, index=pd.DatetimeIndex([])), pd.Timestamp("2026-09-18"))
    assert [r.return_pct for r in got] == [None] * len(WINDOWS)
