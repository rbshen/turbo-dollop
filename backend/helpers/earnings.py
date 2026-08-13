from datetime import date

from sqlmodel import Session

from clients.fmp_client import fmp_client
from core.cache import get_or_fetch, safe_fetch


def most_recent_reported_earnings_date(earnings: list[dict]) -> date | None:
    """The most recent already-happened earnings date (date <= today) in a raw
    FMP /earnings response that has at least one real actual value populated
    (epsActual or revenueActual) -- the real trigger for "a new quarter's
    financial statements should now exist in FMP's system". A bare past date
    with both actuals still null is NOT treated as reported: confirmed live
    via SPY (and other pure index ETFs), whose entire /earnings history is
    null-epsActual/null-revenueActual placeholder rows going back years --
    same garbage-date shape ticker_summary.py::_next_earnings_date's own
    docstring already warns about for the future-date side, just discovered
    here on the past-date side during this feature's own dry run. Requiring
    a real actual also means a genuine report whose epsActual/revenueActual
    hasn't been back-filled yet correctly falls back to the PRIOR real
    reported date rather than firing on data that doesn't exist yet --
    EARNINGS_STALENESS_BUFFER_DAYS (core/cache.py) still covers the ordinary
    same-day-to-couple-day lag once the actuals do land.
    Mirrors data/ticker_summary.py::_next_earnings_date's structure, inverted:
    most recent PAST date instead of nearest FUTURE not-yet-reported one."""
    today = date.today()
    reported = [
        date.fromisoformat(row["date"][:10])
        for row in earnings
        if row.get("date")
        and date.fromisoformat(row["date"][:10]) <= today
        and (row.get("epsActual") is not None or row.get("revenueActual") is not None)
    ]
    return max(reported) if reported else None


async def resolve_most_recent_earnings_date(
    session: Session, ticker: str, staleness_days: int, cache_only: bool
) -> date | None:
    """Fetches (or reads from cache, flat-window -- earnings data itself isn't
    earnings-date-aware, that would be circular) a ticker's /earnings history
    and reduces it to most_recent_reported_earnings_date. Shared by every
    statement-grain data module so the earnings list is fetched/cached once per
    ticker per staleness window, not duplicated per caller -- same shared-cache-
    key convention already used for "profile"/"latest" across these modules.
    Returns None on a missing/failed fetch or an all-future earnings history
    (e.g. a newly-listed ticker) -- callers must treat this as "no signal" and
    fall back to their own flat staleness window, never as "definitely stale"
    or "definitely fresh"."""
    earnings_data = await safe_fetch(
        "earnings",
        get_or_fetch(
            session, ticker, "earnings", "latest", lambda: fmp_client.get_earnings(ticker), staleness_days, cache_only
        ),
    )
    earnings = earnings_data if isinstance(earnings_data, list) else []
    return most_recent_reported_earnings_date(earnings)
