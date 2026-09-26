"""Earnings-report dates and dividend ex-dates for the ticker-page Chart tab's
event markers -- see data/chart_data.py for how these become markers.

**The FMP-backed CorporateEvent cache is the sole source** (data/corporate_events_data.py,
refreshed nightly by pipeline.nightly_corporate_events, full history, served however old --
including while the `corporate_events` group is off). There is no live fetch and no Yahoo
fallback (removed in Phase 6b): a ticker the nightly job has never covered, or a cache read
error, reads as no markers (`source=None`, empty lists) and the chart simply renders without
them.

The FMP normalizers below are shared with the cache: it rebuilds FMP-shaped rows from its table
and runs them through the same rules, so the marker semantics are identical to the original
live path (data/corporate_events_data.py::read_cached_chart_events).

Never raises.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)


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
    # "fmp" | None. None means the ticker isn't in the CorporateEvent cache (or the read
    # failed) -- distinct from source set with empty lists, which is a ticker with no
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
    is treated as a failed fetch instead of reading it as "no earnings"."""
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


async def fetch_chart_events(ticker: str) -> ChartEvents:
    """Earnings + dividend history for `ticker` from the CorporateEvent cache. Never raises --
    see the module docstring. (Async so chart_data can gather it beside the candles.)"""
    try:
        # Lazy import: corporate_events_data imports this module's normalizers.
        from data.corporate_events_data import read_cached_chart_events

        return read_cached_chart_events(ticker) or ChartEvents()
    except Exception as exc:  # noqa: BLE001 -- decoration layer, must never raise
        logger.warning("Corporate-events cache read failed for %s (%s)", ticker, type(exc).__name__)
        return ChartEvents()
