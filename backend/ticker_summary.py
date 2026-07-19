from datetime import date

from sqlmodel import Session

from cache import get_or_fetch, safe_fetch
from config import settings
from db import engine
from debt_metrics import compute_debt_metrics
from fmp_client import fmp_client
from schemas import TickerSummaryOut


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
            await safe_fetch(
                "profile",
                get_or_fetch(session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days),
            )
        )
        quote = _first(
            await safe_fetch(
                "quote",
                get_or_fetch(session, ticker, "quote", "latest", lambda: fmp_client.get_quote(ticker), staleness_days),
            )
        )
        price_change = _first(
            await safe_fetch(
                "price_change",
                get_or_fetch(
                    session, ticker, "price_change", "latest", lambda: fmp_client.get_price_change(ticker), staleness_days
                ),
            )
        )
        ratios = _first(
            await safe_fetch(
                "ratios",
                get_or_fetch(session, ticker, "ratios", "latest", lambda: fmp_client.get_ratios(ticker), staleness_days),
            )
        )
        estimates_data = await safe_fetch(
            "analyst_estimates",
            get_or_fetch(
                session, ticker, "analyst_estimates", "latest", lambda: fmp_client.get_analyst_estimates(ticker), staleness_days
            ),
        )
        earnings_data = await safe_fetch(
            "earnings",
            get_or_fetch(session, ticker, "earnings", "latest", lambda: fmp_client.get_earnings(ticker), staleness_days),
        )
        # Same cache keys + limits Step 1/Step 5 already populate
        # ("balance_sheet_statement"/"quarterly" limit 1, "income_statement"/
        # "quarterly" limit 4) -- compute_debt_metrics is the same shared
        # calculation Step 5's debt ratios use, so the header and Step 5's
        # card can never show inconsistent numbers for the same ticker.
        balance_sheet_data = await safe_fetch(
            "balance_sheet_statement_quarterly",
            get_or_fetch(
                session,
                ticker,
                "balance_sheet_statement",
                "quarterly",
                lambda: fmp_client.get_balance_sheet_statement(ticker, "quarter", 1),
                staleness_days,
            ),
        )
        income_quarterly_data = await safe_fetch(
            "income_statement_quarterly",
            get_or_fetch(
                session,
                ticker,
                "income_statement",
                "quarterly",
                lambda: fmp_client.get_income_statement(ticker, "quarter", 4),
                staleness_days,
            ),
        )

    estimates = estimates_data if isinstance(estimates_data, list) else []
    earnings = earnings_data if isinstance(earnings_data, list) else []
    price = quote.get("price")
    eps_cagr = _compute_eps_cagr(estimates)
    debt_metrics = compute_debt_metrics(
        _first(balance_sheet_data), income_quarterly_data if isinstance(income_quarterly_data, list) else []
    )

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
        total_debt=debt_metrics.total_debt,
        ebitda_ttm=debt_metrics.ebitda_ttm,
        interest_expense_ttm=debt_metrics.interest_expense_ttm,
        interest_income_ttm=debt_metrics.interest_income_ttm,
        # Fair value calculation is out of scope for this phase (per spec) —
        # placeholder only, so the UI has a real field to render.
        fair_value_price=round(price * 1.1, 2) if price else None,
        fair_value_verdict="undervalued" if price else None,
    )
