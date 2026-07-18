import logging
from datetime import date
from typing import Awaitable

import httpx
from sqlmodel import Session

from cache import get_or_fetch
from config import settings
from db import engine
from fmp_client import fmp_client
from schemas import TickerSummaryOut

logger = logging.getLogger(__name__)


async def _safe(label: str, coro: Awaitable[dict | list]) -> dict | list:
    """Isolate one FMP sub-fetch: a failure here (e.g. this FMP plan lacking
    access to a given endpoint) shouldn't take down the whole summary — the
    caller falls back to nulls for whatever fields depended on it."""
    try:
        return await coro
    except httpx.HTTPError as exc:
        logger.warning("FMP fetch failed for %s: %s", label, exc)
        return {}


def _first(data: dict | list) -> dict:
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def _next_earnings_date(earnings: list[dict]) -> date | None:
    """The nearest not-yet-reported (epsActual is null) earnings date."""
    upcoming = [row["date"] for row in earnings if row.get("date") and row.get("epsActual") is None]
    if not upcoming:
        return None
    return date.fromisoformat(min(upcoming)[:10])


def _compute_eps_cagr(estimates: list[dict]) -> float | None:
    """Projected EPS growth rate: CAGR from the nearest annual EPS estimate to
    whichever available estimate sits closest to 4 years out (the middle of
    the spec's "3-5yr" horizon), falling back to the furthest estimate if
    none falls in that window."""
    rows = [
        (row["date"], row["epsAvg"])
        for row in estimates
        if row.get("date") and row.get("epsAvg") is not None and row["epsAvg"] > 0
    ]
    if len(rows) < 2:
        return None
    rows.sort(key=lambda r: r[0])
    base_date_str, base_eps = rows[0]
    base_year = date.fromisoformat(base_date_str[:10]).year

    def year_offset(date_str: str) -> int:
        return date.fromisoformat(date_str[:10]).year - base_year

    later_rows = rows[1:]
    in_window = [r for r in later_rows if 3 <= year_offset(r[0]) <= 5]
    target_date_str, target_eps = (
        min(in_window, key=lambda r: abs(year_offset(r[0]) - 4)) if in_window else later_rows[-1]
    )

    years = year_offset(target_date_str)
    if years <= 0:
        return None
    return (target_eps / base_eps) ** (1 / years) - 1


async def get_summary(ticker: str) -> TickerSummaryOut:
    ticker = ticker.upper()
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        profile = _first(
            await _safe(
                "profile",
                get_or_fetch(session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days),
            )
        )
        quote = _first(
            await _safe(
                "quote",
                get_or_fetch(session, ticker, "quote", "latest", lambda: fmp_client.get_quote(ticker), staleness_days),
            )
        )
        price_change = _first(
            await _safe(
                "price_change",
                get_or_fetch(
                    session, ticker, "price_change", "latest", lambda: fmp_client.get_price_change(ticker), staleness_days
                ),
            )
        )
        ratios = _first(
            await _safe(
                "ratios",
                get_or_fetch(session, ticker, "ratios", "latest", lambda: fmp_client.get_ratios(ticker), staleness_days),
            )
        )
        estimates_data = await _safe(
            "analyst_estimates",
            get_or_fetch(
                session, ticker, "analyst_estimates", "latest", lambda: fmp_client.get_analyst_estimates(ticker), staleness_days
            ),
        )
        earnings_data = await _safe(
            "earnings",
            get_or_fetch(session, ticker, "earnings", "latest", lambda: fmp_client.get_earnings(ticker), staleness_days),
        )

    estimates = estimates_data if isinstance(estimates_data, list) else []
    earnings = earnings_data if isinstance(earnings_data, list) else []
    price = quote.get("price")
    eps_cagr = _compute_eps_cagr(estimates)

    return TickerSummaryOut(
        company_name=profile.get("companyName"),
        ticker=ticker,
        exchange=profile.get("exchangeShortName") or profile.get("exchange"),
        sector=profile.get("sector"),
        industry=profile.get("industry"),
        price=price,
        change=quote.get("change"),
        change_percent=quote.get("changePercentage", quote.get("changesPercentage")),
        market_cap=quote.get("marketCap") or profile.get("mktCap"),
        beta=profile.get("beta"),
        perf_1m=price_change.get("1M"),
        perf_6m=price_change.get("6M"),
        # price-change/quote percentages from FMP already come as percentage
        # points (e.g. 11.98 for 11.98%); normalize the CAGR fraction to match.
        eps_growth_3_5y=eps_cagr * 100 if eps_cagr is not None else None,
        pe_ratio=ratios.get("priceToEarningsRatio"),
        next_earnings_date=_next_earnings_date(earnings),
        # Fair value calculation is out of scope for this phase (per spec) —
        # placeholder only, so the UI has a real field to render.
        fair_value_price=round(price * 1.1, 2) if price else None,
        fair_value_verdict="undervalued" if price else None,
    )
