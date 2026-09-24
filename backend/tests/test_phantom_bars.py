"""Non-US phantom-bar filter (P3 D7). Fixtures are real FMP /historical-price-eod/full
rows captured 2026-09-25 for the cases named in the investigation: 0005.HK Good Friday
2025-04-18 and Sunday 2025-10-26/Monday 2025-10-27, 0883.HK Sundays 2024-09-22/29, 0857.HK
Good Friday, plus an AAPL control."""

import pandas as pd

from clients.daily_bar_sources import drop_phantom_bars, fmp_rows_to_frame


def _r(date, o, h, l, c, v):
    return {"date": date, "open": o, "high": h, "low": l, "close": c, "volume": v}


# as FMP returns them (newest first)
HSBC_GOOD_FRIDAY = [
    _r("2025-04-23", 83.5, 86.3, 83.5, 85.9, 33409268),
    _r("2025-04-22", 80.1, 82.35, 80.1, 82.35, 22003396),
    _r("2025-04-18", 80.1, 80.9, 80.05, 80.8, 22248586),
    _r("2025-04-17", 80.1, 80.9, 80.05, 80.8, 22247386),
    _r("2025-04-16", 79.65, 80.3, 78.85, 79.55, 22685876),
    _r("2025-04-15", 79, 79, 78.35, 78.8, 15653353),
]

HSBC_SUNDAY = [
    _r("2025-10-28", 103.2, 106.5, 102.7, 106.5, 30318072),
    _r("2025-10-27", 103.8, 103.8, 101.2, 102, 22950060),
    _r("2025-10-26", 103.8, 103.8, 101.2, 102, 22950060),
    _r("2025-10-24", 102.6, 103.7, 102.5, 103.1, 12264938),
    _r("2025-10-23", 102.6, 103.2, 102.4, 102.7, 7515170),
]

CNOOC_SUNDAYS = [
    _r("2024-09-30", 18.86, 19.54, 18.76, 19.42, 316965800),
    _r("2024-09-29", 18.86, 18.98, 18.86, 18.88, 14248000),
    _r("2024-09-27", 18.08, 18.7, 17.54, 18.58, 379095541),
    _r("2024-09-26", 19.6, 19.76, 18.3, 18.4, 455750772),
    _r("2024-09-25", 20.6, 20.65, 19.56, 19.68, 153824831),
    _r("2024-09-24", 19.2, 19.9, 19.16, 19.76, 138176442),
    _r("2024-09-23", 19.1, 19.28, 18.9, 18.98, 76073013),
    _r("2024-09-22", 19.1, 19.28, 18.9, 18.98, 76073013),
    _r("2024-09-20", 18.98, 19.4, 18.86, 18.9, 94133374),
    _r("2024-09-19", 18.8, 18.88, 18.32, 18.8, 125938648),
]

PETRO_GOOD_FRIDAY = [
    _r("2025-04-23", 5.86, 5.9, 5.79, 5.82, 125157740),
    _r("2025-04-22", 5.66, 5.79, 5.64, 5.77, 122294507),
    _r("2025-04-18", 5.66, 5.77, 5.62, 5.67, 155533346),
    _r("2025-04-17", 5.66, 5.77, 5.62, 5.67, 155393346),
    _r("2025-04-16", 5.57, 5.62, 5.54, 5.59, 151533481),
    _r("2025-04-15", 5.55, 5.63, 5.52, 5.58, 179810010),
]

AAPL_CONTROL = [
    _r("2025-04-30", 209.3, 213.58, 206.67, 212.5, 52286500),
    _r("2025-04-29", 208.69, 212.24, 208.37, 211.21, 36827633),
    _r("2025-04-28", 210, 211.5, 207.46, 210.14, 38743100),
    _r("2025-04-25", 206.37, 209.75, 206.2, 209.28, 38222300),
    _r("2025-04-24", 204.89, 208.83, 202.94, 208.37, 47311000),
    _r("2025-04-23", 206, 208, 202.8, 204.6, 52929200),
    _r("2025-04-22", 196.12, 201.59, 195.97, 199.74, 52976400),
    _r("2025-04-21", 193.27, 193.8, 189.81, 193.16, 46742537),
    _r("2025-04-17", 197.2, 198.83, 194.42, 196.98, 52164700),
    _r("2025-04-16", 198.36, 200.7, 192.37, 194.27, 59732423),
    _r("2025-04-15", 201.86, 203.51, 199.8, 202.14, 51343900),
]


def _dates(frame):
    return [d.strftime("%Y-%m-%d") for d in frame.index]


def test_good_friday_copy_is_dropped_even_though_its_volume_was_revised_slightly():
    """The literal 'identical volume' rule keeps this bar: FMP's copy carries volume +0.005%."""
    kept = _dates(fmp_rows_to_frame(HSBC_GOOD_FRIDAY, non_us=True))
    assert kept == ["2025-04-15", "2025-04-16", "2025-04-17", "2025-04-22", "2025-04-23"]


def test_sunday_bar_and_its_monday_copy_are_both_dropped():
    assert _dates(fmp_rows_to_frame(HSBC_SUNDAY, non_us=True)) == ["2025-10-23", "2025-10-24", "2025-10-28"]


def test_weekend_bars_and_flat_copies_on_0883():
    kept = _dates(fmp_rows_to_frame(CNOOC_SUNDAYS, non_us=True))
    assert "2024-09-22" not in kept and "2024-09-23" not in kept and "2024-09-29" not in kept
    assert kept == ["2024-09-19", "2024-09-20", "2024-09-24", "2024-09-25", "2024-09-26", "2024-09-27", "2024-09-30"]


def test_good_friday_copy_on_0857():
    kept = _dates(fmp_rows_to_frame(PETRO_GOOD_FRIDAY, non_us=True))
    assert "2025-04-18" not in kept and "2025-04-17" in kept


def test_us_control_is_untouched_and_the_filter_is_off_by_default():
    assert len(fmp_rows_to_frame(AAPL_CONTROL, non_us=True)) == len(AAPL_CONTROL)
    # the default (US path) never filters, even for a series that would be dropped
    assert len(fmp_rows_to_frame(HSBC_GOOD_FRIDAY)) == len(HSBC_GOOD_FRIDAY)


def test_a_real_bar_that_only_repeats_ohlc_but_trades_different_volume_is_kept():
    rows = [
        _r("2025-05-06", 5.0, 5.1, 4.9, 5.0, 2_000_000),
        _r("2025-05-05", 5.0, 5.1, 4.9, 5.0, 1_000_000),  # same OHLC, volume doubled: a real day
        _r("2025-05-02", 4.8, 5.2, 4.7, 5.0, 900_000),
    ]
    assert len(fmp_rows_to_frame(rows, non_us=True)) == 3


def test_flat_bar_with_zero_volume_is_dropped():
    rows = [_r("2025-05-06", 5.0, 5.1, 4.9, 5.0, 0), _r("2025-05-05", 5.0, 5.1, 4.9, 5.0, 900_000)]
    assert _dates(fmp_rows_to_frame(rows, non_us=True)) == ["2025-05-05"]


def test_partial_ohlc_repeat_is_kept():
    rows = [_r("2025-05-06", 5.0, 5.1, 4.9, 5.05, 900_000), _r("2025-05-05", 5.0, 5.1, 4.9, 5.0, 900_000)]
    assert len(fmp_rows_to_frame(rows, non_us=True)) == 2


def test_empty_and_single_row_inputs():
    assert drop_phantom_bars(pd.DataFrame(columns=["open", "high", "low", "close", "volume"])).empty
    assert len(fmp_rows_to_frame([_r("2025-05-05", 5.0, 5.1, 4.9, 5.0, 1)], non_us=True)) == 1
