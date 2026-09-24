"""Non-US phantom-bar filter (P3 D7). Fixtures are real FMP /historical-price-eod/full
rows captured 2026-09-25: 0005.HK Good Friday 2025-04-18 and Sunday 2025-10-26/Monday
2025-10-27, 0883.HK Sundays and holiday copies in 2024-09, 0857.HK Good Friday, 3988.HK Good
Friday (the known survivor), real OHLC-repeating days on 0728.HK, plus an AAPL control.
Which of a copied pair is real was checked against live Yahoo bars for the same dates."""

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

CNOOC_HOLIDAY_COPIES = [
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
    _r("2024-09-18", 18.8, 18.88, 18.32, 18.8, 125938648),
    _r("2024-09-17", 18.58, 18.92, 18.54, 18.78, 35350031),
    _r("2024-09-16", 18.18, 18.5, 18.14, 18.42, 20440956),
    _r("2024-09-15", 18.18, 18.5, 18.14, 18.42, 20440956),
    _r("2024-09-13", 18.3, 18.72, 18.3, 18.48, 78299262),
    _r("2024-09-12", 18.22, 18.3, 17.8, 18.16, 97405548),
]

CHINA_TELECOM_REAL_FLATS = [
    _r("2021-11-17", 2.63, 2.64, 2.61, 2.63, 35578000),
    _r("2021-11-16", 2.64, 2.64, 2.62, 2.63, 28556269),
    _r("2021-11-15", 2.64, 2.66, 2.61, 2.63, 37759323),
    _r("2021-11-12", 2.64, 2.66, 2.61, 2.63, 29160000),
    _r("2021-11-11", 2.6, 2.64, 2.6, 2.63, 23517246),
    _r("2021-11-10", 2.65, 2.65, 2.6, 2.61, 37172660),
    _r("2024-05-27", 4.45, 4.5, 4.45, 4.47, 61997541),
    _r("2024-05-24", 4.43, 4.46, 4.41, 4.44, 29060784),
    _r("2024-05-23", 4.43, 4.46, 4.41, 4.44, 40784635),
    _r("2024-05-22", 4.32, 4.46, 4.32, 4.44, 63458000),
]

BOC_GOOD_FRIDAY = [
    _r("2025-04-23", 4.36, 4.37, 4.3, 4.33, 183292410),
    _r("2025-04-22", 4.35, 4.36, 4.23, 4.3, 445089971),
    _r("2025-04-18", 4.39, 4.45, 4.38, 4.44, 160265230),
    _r("2025-04-17", 4.39, 4.45, 4.38, 4.44, 174440230),
    _r("2025-04-16", 4.44, 4.49, 4.36, 4.39, 215058329),
    _r("2025-04-15", 4.43, 4.47, 4.41, 4.46, 182036403),
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
    # the Sunday phantom goes; the Monday bar carries the same values but is the REAL day
    assert _dates(fmp_rows_to_frame(HSBC_SUNDAY, non_us=True)) == ["2025-10-23", "2025-10-24", "2025-10-27", "2025-10-28"]


def test_weekend_bars_and_holiday_copies_on_0883_keep_the_real_day_not_the_phantom():
    """Yahoo has 09-16, 09-17, 09-19, 09-20, 09-23 and NOT 09-15 (Sunday), 09-18 (a HK holiday),
    09-22 (Sunday), 09-29 (Sunday). FMP's 09-18 is a copy of the NEXT real day (09-19): the
    earlier one is the phantom, so the real 09-19 must survive."""
    kept = _dates(fmp_rows_to_frame(CNOOC_HOLIDAY_COPIES, non_us=True))
    assert kept == ["2024-09-12", "2024-09-13", "2024-09-16", "2024-09-17", "2024-09-19", "2024-09-20",
                    "2024-09-23", "2024-09-24", "2024-09-25", "2024-09-26", "2024-09-27", "2024-09-30"]


def test_real_consecutive_days_with_repeated_ohlc_but_different_volume_are_kept():
    """0728.HK: Yahoo has BOTH days of each pair, with distinct volumes."""
    frame = fmp_rows_to_frame(CHINA_TELECOM_REAL_FLATS, non_us=True)
    assert len(frame) == len(CHINA_TELECOM_REAL_FLATS)


def test_boc_good_friday_copy_with_an_eight_percent_volume_gap_is_a_known_survivor():
    """Documented limitation: 3988's phantom 2025-04-18 has -8.1% volume, inside the range of
    genuine OHLC repeats (14%+ on 0728), so it cannot be told apart and is kept."""
    assert "2025-04-18" in _dates(fmp_rows_to_frame(BOC_GOOD_FRIDAY, non_us=True))


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


def test_exact_copy_pair_keeps_the_later_bar_and_a_run_of_copies_keeps_only_the_last():
    rows = [
        _r("2025-05-08", 6.0, 6.2, 5.9, 6.1, 400_000),
        _r("2025-05-07", 5.0, 5.1, 4.9, 5.0, 900_000),
        _r("2025-05-06", 5.0, 5.1, 4.9, 5.0, 900_000),
        _r("2025-05-05", 5.0, 5.1, 4.9, 5.0, 900_000),
        _r("2025-05-02", 4.8, 5.2, 4.7, 5.0, 700_000),
    ]
    assert _dates(fmp_rows_to_frame(rows, non_us=True)) == ["2025-05-02", "2025-05-07", "2025-05-08"]


def test_partial_ohlc_repeat_is_kept():
    rows = [_r("2025-05-06", 5.0, 5.1, 4.9, 5.05, 900_000), _r("2025-05-05", 5.0, 5.1, 4.9, 5.0, 900_000)]
    assert len(fmp_rows_to_frame(rows, non_us=True)) == 2


def test_empty_and_single_row_inputs():
    assert drop_phantom_bars(pd.DataFrame(columns=["open", "high", "low", "close", "volume"])).empty
    assert len(fmp_rows_to_frame([_r("2025-05-05", 5.0, 5.1, 4.9, 5.0, 1)], non_us=True)) == 1
