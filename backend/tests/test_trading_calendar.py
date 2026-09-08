from datetime import date

from helpers.trading_calendar import resolve_month_end_anchor


def test_not_first_trading_day_returns_none():
    # 2025-09-03 is a real NYSE trading day but not the first one of
    # September (2025-09-02 is, since Labor Day pushed it off the 1st).
    assert resolve_month_end_anchor(date(2025, 9, 3)) is None


def test_normal_month_anchors_to_prior_trading_day():
    # 2025-10-01 (Wednesday) is an ordinary first-trading-day-of-month with
    # no holiday involved -- anchor should be 2025-09-30 (Tuesday).
    assert resolve_month_end_anchor(date(2025, 10, 1)) == date(2025, 9, 30)


def test_labor_day_2025_shifts_first_trading_day_to_the_2nd():
    # Labor Day 2025 falls on Monday 2025-09-01, a NYSE holiday -- the real
    # first trading day of September 2025 is Tuesday 2025-09-02, and it
    # should anchor to Friday 2025-08-29 (the last trading day of August).
    assert resolve_month_end_anchor(date(2025, 9, 2)) == date(2025, 8, 29)


def test_the_holiday_itself_is_not_mistaken_for_the_first_trading_day():
    # 2025-09-01 is Labor Day itself -- not a trading day at all, so it must
    # never be treated as "the first trading day of the month."
    assert resolve_month_end_anchor(date(2025, 9, 1)) is None


def test_a_weekend_date_returns_none():
    # 2025-09-06 is a Saturday -- never a valid anchor-check day.
    assert resolve_month_end_anchor(date(2025, 9, 6)) is None
