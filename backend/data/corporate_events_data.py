"""FMP-backed cache of earnings dates, dividends and splits (Phase 6a).

`refresh_ticker_events` pulls the three FMP endpoints (`/earnings`, `/dividends`,
`/splits`, all data group `corporate_events`) and REPLACES that ticker's stored rows
per event type with FMP's current full history -- a mirror, not a layered history. A
successful refresh also stamps CorporateEventFetch, which is what lets the reader tell
"fetched, FMP has none" (TSLA pays no dividend) from "never fetched". Refreshed nightly
by pipeline/nightly_corporate_events.py (the first run is the full-history backfill).

`read_cached_chart_events` feeds the Chart tab's E/D markers
(data/chart_events_data.py): it rebuilds FMP-shaped rows from the table and reuses that
module's own normalizers, so the cached path applies exactly the rules the live path
does (real-actuals-only earnings, split-adjusted dividend amounts, no zero amounts).
Splits are stored for completeness/future use; no chart marker reads them yet.
"""

import logging
from datetime import date, datetime

from sqlalchemy import delete
from sqlmodel import Session, select

from clients.fmp_client import fmp_client
from core.db import engine
from core.models import CorporateEvent, CorporateEventFetch
from data.chart_events_data import ChartEvents, normalize_fmp_dividends, normalize_fmp_earnings

logger = logging.getLogger(__name__)

EARNINGS, DIVIDEND, SPLIT = "earnings", "dividend", "split"
EVENT_TYPES = (EARNINGS, DIVIDEND, SPLIT)

# FMP returns the whole history (AAPL: 165 earnings rows back to 1985, 92 dividends) as
# long as `limit` is large enough; these are far above any real ticker's count.
EARNINGS_LIMIT = 1000
DIVIDENDS_LIMIT = 2000


def _num(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if out != out else out  # NaN -> None


def _date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def build_rows(ticker: str, event_type: str, payload: object) -> list[CorporateEvent]:
    """FMP rows -> CorporateEvent rows (no id). A non-list payload (an error body
    served with HTTP 200) raises ValueError so the caller keeps the old rows rather
    than reading it as "FMP has none". A duplicate date within one payload keeps the
    first row (FMP lists newest first)."""
    if not isinstance(payload, list):
        raise ValueError(f"unexpected FMP {event_type} response shape")
    out: dict[date, CorporateEvent] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        when = _date(row.get("date"))
        if when is None or when in out:
            continue
        event = CorporateEvent(ticker=ticker, event_type=event_type, event_date=when)
        if event_type == EARNINGS:
            event.eps_actual, event.eps_estimated = _num(row.get("epsActual")), _num(row.get("epsEstimated"))
            event.revenue_actual, event.revenue_estimated = _num(row.get("revenueActual")), _num(row.get("revenueEstimated"))
        elif event_type == DIVIDEND:
            event.dividend, event.adj_dividend = _num(row.get("dividend")), _num(row.get("adjDividend"))
            event.record_date, event.payment_date = _date(row.get("recordDate")), _date(row.get("paymentDate"))
            event.declaration_date = _date(row.get("declarationDate"))
            event.frequency = row.get("frequency") or None
        else:
            event.split_numerator, event.split_denominator = _num(row.get("numerator")), _num(row.get("denominator"))
        out[when] = event
    return list(out.values())


async def _fetch(ticker: str, event_type: str) -> object:
    if event_type == EARNINGS:
        return await fmp_client.get_earnings_history(ticker, EARNINGS_LIMIT)
    if event_type == DIVIDEND:
        return await fmp_client.get_dividends(ticker, DIVIDENDS_LIMIT)
    return await fmp_client.get_splits(ticker)


def replace_events(ticker: str, event_type: str, rows: list[CorporateEvent], now: datetime | None = None) -> None:
    """Swap `ticker`'s stored rows of this type for `rows` and stamp the fetch, in one
    transaction (a failure leaves the old rows untouched)."""
    now = now or datetime.now()
    with Session(engine) as session:
        session.exec(delete(CorporateEvent).where(CorporateEvent.ticker == ticker, CorporateEvent.event_type == event_type))
        session.add_all(rows)
        stamp = session.get(CorporateEventFetch, (ticker, event_type))
        if stamp is None:
            session.add(CorporateEventFetch(ticker=ticker, event_type=event_type, fetched_at=now, row_count=len(rows)))
        else:
            stamp.fetched_at, stamp.row_count = now, len(rows)
        session.commit()


async def refresh_ticker_events(ticker: str) -> dict[str, int | str]:
    """Refresh every event type for `ticker`. Returns {event_type: rows written} with a
    failed type reading "error: <ExceptionType>" (its old rows, if any, are kept). Type
    name only -- an httpx error's message embeds the request URL, apikey included."""
    result: dict[str, int | str] = {}
    for event_type in EVENT_TYPES:
        try:
            rows = build_rows(ticker, event_type, await _fetch(ticker, event_type))
            replace_events(ticker, event_type, rows)
            result[event_type] = len(rows)
        except Exception as exc:  # noqa: BLE001 -- one bad endpoint must not abort the ticker
            logger.warning("Corporate events (%s) refresh failed for %s (%s)", event_type, ticker, type(exc).__name__)
            result[event_type] = f"error: {type(exc).__name__}"
    return result


def read_cached_chart_events(ticker: str) -> ChartEvents | None:
    """Earnings + dividend events for the Chart tab from the cache, or None when the
    ticker's earnings OR dividends were never successfully fetched (the caller then
    falls through to its live path). Serves whatever is cached however old -- freshness
    is the nightly job's concern, and the cache is the designed answer while the
    `corporate_events` group is off."""
    with Session(engine) as session:
        fetched = {
            f.event_type
            for f in session.exec(select(CorporateEventFetch).where(CorporateEventFetch.ticker == ticker)).all()
        }
        if not {EARNINGS, DIVIDEND} <= fetched:
            return None
        rows = session.exec(
            select(CorporateEvent).where(CorporateEvent.ticker == ticker, CorporateEvent.event_type.in_([EARNINGS, DIVIDEND]))
        ).all()
    earnings_raw = [
        {"date": r.event_date.isoformat(), "epsActual": r.eps_actual, "epsEstimated": r.eps_estimated, "revenueActual": r.revenue_actual}
        for r in rows
        if r.event_type == EARNINGS
    ]
    dividends_raw = [
        {"date": r.event_date.isoformat(), "adjDividend": r.adj_dividend, "dividend": r.dividend}
        for r in rows
        if r.event_type == DIVIDEND
    ]
    return ChartEvents(normalize_fmp_earnings(earnings_raw), normalize_fmp_dividends(dividends_raw), "fmp")
