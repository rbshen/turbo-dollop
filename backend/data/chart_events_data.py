"""Earnings-report dates and dividend ex-dates for the ticker-page Chart tab's
event markers -- see data/chart_data.py for how these become markers.

Fully ON-DEMAND, zero persistent caching, exactly like the rest of the Chart
tab (see chart_data.py's module docstring for why the cache was dropped there):
every chart request makes two live calls. Deliberately does NOT go through
core/cache.py's FundamentalsCache -- the existing "earnings"/"latest" cache
key holds a limit=8 response used for next-earnings-date logic, and reusing
it would either collide with that shape or silently cap the chart at 2 years.

Source is FMP when FMP_ENABLED, Yahoo Finance otherwise (or when the FMP calls
fail), the app's normal degrade pattern for corporate-actions data. This is
intentionally different from the Chart tab's PRICE candles, which are
Yahoo-only regardless of FMP_ENABLED (chart_data.py docstring point 3): that
decision was about keeping technical-analysis inputs independent of the FMP
subscription, and event markers are decoration on top of the candles, not an
input to any indicator. FMP is preferred because its coverage is deeper for
foreign issuers (HSBC: 40 quarters vs Yahoo's 7) and it carries declared-ahead
dividend dates.

Never raises: a failure of every source degrades to `source=None` with empty
lists, and the chart simply renders without event markers.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from clients.fmp_client import fmp_client
from clients.yahoo_client import yahoo_client
from core.data_groups import group_live

logger = logging.getLogger(__name__)

# The whole event fetch (both calls, FMP then possibly Yahoo) is capped so a
# slow/hung upstream can never hold the chart's candles hostage -- FMPClient's
# own httpx timeout is 30s, far too long for a decoration layer.
EVENTS_FETCH_TIMEOUT_SECONDS = 8.0

# 40 quarters ~ 10 years; the Chart tab's widest window is 4 years.
EARNINGS_HISTORY_LIMIT = 40


@dataclass(frozen=True)
class EarningsEvent:
    event_date: date
    eps_actual: float | None
    eps_estimated: float | None


@dataclass(frozen=True)
class DividendEvent:
    event_date: date  # ex-dividend date
    amount: float  # per share, split-adjusted (same basis as the candles)


@dataclass
class ChartEvents:
    earnings: list[EarningsEvent] = field(default_factory=list)
    dividends: list[DividendEvent] = field(default_factory=list)
    # "fmp" | "yahoo" | None. None means every source failed (or timed out) --
    # distinct from source set with empty lists, which is a ticker with no
    # reported earnings/dividends (e.g. TSLA pays no dividend).
    source: str | None = None


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if pd.isna(out) else out


def normalize_fmp_earnings(rows: object) -> list[EarningsEvent]:
    """FMP /earnings rows -> reported events only, oldest first.

    A row counts only when it carries a real actual (epsActual or
    revenueActual): FMP also returns the next scheduled date with null
    actuals, and pure index ETFs (SPY) carry a whole history of null-actual
    placeholder rows going back years -- the same garbage-date shape
    helpers/earnings.py::most_recent_reported_earnings_date documents. A
    non-list body (an error payload served with HTTP 200) raises so the caller
    falls back to Yahoo instead of reading it as "no earnings"."""
    if not isinstance(rows, list):
        raise ValueError("unexpected FMP /earnings response shape")
    out: list[EarningsEvent] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("date"):
            continue
        eps_actual = _to_float(row.get("epsActual"))
        if eps_actual is None and _to_float(row.get("revenueActual")) is None:
            continue
        try:
            when = date.fromisoformat(str(row["date"])[:10])
        except ValueError:
            continue
        out.append(EarningsEvent(when, eps_actual, _to_float(row.get("epsEstimated"))))
    return sorted(out, key=lambda e: e.event_date)


def normalize_fmp_dividends(rows: object) -> list[DividendEvent]:
    """FMP /dividends rows -> events, oldest first. `date` is the ex-dividend
    date. Amount prefers `adjDividend` (split-adjusted -- AAPL's 2019 $0.77
    reads $0.1925 there, matching the split-adjusted candles) and falls back to
    `dividend`. Zero/negative/missing amounts are dropped. Future declared
    dates are kept here -- windowing to what has actually happened is the
    marker builder's job, which already has to bound against the last bar."""
    if not isinstance(rows, list):
        raise ValueError("unexpected FMP /dividends response shape")
    out: list[DividendEvent] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("date"):
            continue
        amount = _to_float(row.get("adjDividend"))
        if amount is None:
            amount = _to_float(row.get("dividend"))
        if amount is None or amount <= 0:
            continue
        try:
            when = date.fromisoformat(str(row["date"])[:10])
        except ValueError:
            continue
        out.append(DividendEvent(when, amount))
    return sorted(out, key=lambda e: e.event_date)


def normalize_yahoo_earnings(frame: pd.DataFrame) -> list[EarningsEvent]:
    """Yahoo get_earnings_dates frame -> reported events, oldest first. The
    index is exchange-local tz-aware, so `.date()` is the local calendar date
    of the report. Rows with a NaN 'Reported EPS' are scheduled/unreported."""
    if frame is None or frame.empty or "Reported EPS" not in frame.columns:
        return []
    estimates = frame["EPS Estimate"] if "EPS Estimate" in frame.columns else pd.Series(index=frame.index, dtype=float)
    out: list[EarningsEvent] = []
    for ts, reported in frame["Reported EPS"].items():
        eps_actual = _to_float(reported)
        if eps_actual is None:
            continue
        out.append(EarningsEvent(pd.Timestamp(ts).date(), eps_actual, _to_float(estimates.get(ts))))
    return sorted(out, key=lambda e: e.event_date)


def normalize_yahoo_dividends(series: pd.Series) -> list[DividendEvent]:
    """Yahoo dividends series (ex-date index, split-adjusted amounts) ->
    events, oldest first."""
    if series is None or series.empty:
        return []
    out: list[DividendEvent] = []
    for ts, value in series.items():
        amount = _to_float(value)
        if amount is None or amount <= 0:
            continue
        out.append(DividendEvent(pd.Timestamp(ts).date(), amount))
    return sorted(out, key=lambda e: e.event_date)


async def _fetch_fmp(ticker: str) -> tuple[list[EarningsEvent], list[DividendEvent]]:
    earnings_raw, dividends_raw = await asyncio.gather(
        fmp_client.get_earnings_history(ticker, EARNINGS_HISTORY_LIMIT), fmp_client.get_dividends(ticker)
    )
    return normalize_fmp_earnings(earnings_raw), normalize_fmp_dividends(dividends_raw)


async def _fetch_yahoo(ticker: str) -> tuple[list[EarningsEvent], list[DividendEvent]] | None:
    """Each kind is tolerated independently (an earnings-calendar failure must
    not blank a perfectly good dividend history, and vice versa); None only
    when BOTH raised."""
    earnings_result, dividends_result = await asyncio.gather(
        yahoo_client.get_earnings_dates(ticker, EARNINGS_HISTORY_LIMIT),
        yahoo_client.get_dividends(ticker),
        return_exceptions=True,
    )
    if isinstance(earnings_result, BaseException) and isinstance(dividends_result, BaseException):
        return None
    earnings = [] if isinstance(earnings_result, BaseException) else normalize_yahoo_earnings(earnings_result)
    dividends = [] if isinstance(dividends_result, BaseException) else normalize_yahoo_dividends(dividends_result)
    return earnings, dividends


async def _fetch_events(ticker: str) -> ChartEvents:
    if group_live("corporate_events"):
        try:
            earnings, dividends = await _fetch_fmp(ticker)
            return ChartEvents(earnings, dividends, "fmp")
        except Exception as exc:  # noqa: BLE001 -- decoration layer, must never raise
            # Type name only: an httpx error's own message embeds the request
            # URL, apikey included.
            logger.warning("FMP earnings/dividends fetch failed for %s (%s); falling back to Yahoo", ticker, type(exc).__name__)
    yahoo = await _fetch_yahoo(ticker)
    if yahoo is None:
        return ChartEvents()
    return ChartEvents(yahoo[0], yahoo[1], "yahoo")


async def fetch_chart_events(ticker: str) -> ChartEvents:
    """Earnings + dividend history for `ticker`, best available source. Never
    raises -- see the module docstring."""
    try:
        return await asyncio.wait_for(_fetch_events(ticker), timeout=EVENTS_FETCH_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 -- includes asyncio.TimeoutError
        logger.warning("Chart event fetch gave up for %s (%s)", ticker, type(exc).__name__)
        return ChartEvents()
