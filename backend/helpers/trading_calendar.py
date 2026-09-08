"""NYSE trading-calendar helper for the Momentum signal (see
pipeline/monthly_momentum_snapshot.py) -- pure, no DB/HTTP, matching this
package's existing shape (ttm.py, shares.py, etc.). Uses
pandas_market_calendars, the same library the original momentum-backtest
scratch work already relied on for month-end/next-trading-day logic (see
CLAUDE.md's Momentum section) -- reused here rather than picked fresh.
"""

from datetime import date, timedelta

import pandas_market_calendars as mcal

_XNYS = mcal.get_calendar("XNYS")


def resolve_month_end_anchor(today: date) -> date | None:
    """Returns the last NYSE trading day strictly before `today`, but only
    when `today` is itself the first NYSE trading day of its calendar
    month -- otherwise returns None.

    Doubles as both the monthly cron's no-op gate and its anchor-date
    resolver: the cron tries daily across the first several days of the
    month (crontab.txt), and this is the one function that decides "is
    today actually the day to run, and if so, which month-end close are we
    anchoring the lookback windows to." A single tested function for both
    concerns, rather than two that could drift apart.

    Deliberately does NOT assume day-of-month 1 is a trading day -- a
    holiday (e.g. Labor Day) can push the real first trading day of a
    month to the 2nd or later, which would otherwise both mis-fire the
    gate and mis-anchor the lookback."""
    month_start = today.replace(day=1)
    schedule_days = _XNYS.valid_days(start_date=month_start, end_date=today)
    trading_days_this_month = [d.date() for d in schedule_days]

    if not trading_days_this_month or trading_days_this_month[0] != today:
        return None

    # A plain 14-calendar-day lookback window comfortably covers "the last
    # trading day before today" in every real case -- NYSE has no holiday
    # stretch anywhere near that long -- so this avoids an unbounded scan
    # back from `today`.
    lookback_start = today - timedelta(days=14)
    recent_days = _XNYS.valid_days(start_date=lookback_start, end_date=today)
    recent_trading_days = [d.date() for d in recent_days if d.date() < today]
    return recent_trading_days[-1] if recent_trading_days else None
