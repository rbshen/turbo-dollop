from sqlmodel import Session

from cache import get_or_fetch, safe_fetch
from config import settings
from db import engine
from fmp_client import fmp_client
from schemas import Step1Out
from scoring.step1 import score_step1
from ttm import sum_last_four_quarters


def _first(data: dict | list) -> dict:
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def _detect_exemption(sector: str | None, industry: str | None) -> str | None:
    """Heuristic sector/industry match for the Step 1 CFO exemption (Bank /
    Property Developer / Commodity Company) — not exhaustive industry-code
    matching, a reasonable approximation for this phase."""
    sector = (sector or "").strip()
    industry_lower = (industry or "").strip().lower()
    if sector == "Financial Services" and "bank" in industry_lower:
        return "Bank"
    if sector == "Real Estate":
        return "Property Developer"
    if sector in {"Basic Materials", "Energy"}:
        return "Commodity Company"
    return None


def _annual_series(annual_rows: list[dict], field: str) -> tuple[list[str], list[float | None]]:
    # FMP returns annual rows most-recent-first; reverse to chronological
    # (oldest fiscal year first) since that's the order classify_trend expects.
    rows = list(reversed(annual_rows))
    years = [row.get("fiscalYear", row.get("date", "")[:4]) for row in rows]
    values = [row.get(field) for row in rows]
    return years, values


async def get_step1_data(ticker: str) -> Step1Out:
    ticker = ticker.upper()
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        profile = _first(
            await safe_fetch(
                "profile",
                get_or_fetch(session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days),
            )
        )
        income_annual = await safe_fetch(
            "income_statement_annual",
            get_or_fetch(
                session,
                ticker,
                "income_statement",
                "annual",
                lambda: fmp_client.get_income_statement(ticker, "annual", 10),
                staleness_days,
            ),
        )
        income_quarterly = await safe_fetch(
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
        cash_flow_annual = await safe_fetch(
            "cash_flow_statement_annual",
            get_or_fetch(
                session,
                ticker,
                "cash_flow_statement",
                "annual",
                lambda: fmp_client.get_cash_flow_statement(ticker, "annual", 10),
                staleness_days,
            ),
        )
        cash_flow_quarterly = await safe_fetch(
            "cash_flow_statement_quarterly",
            get_or_fetch(
                session,
                ticker,
                "cash_flow_statement",
                "quarterly",
                lambda: fmp_client.get_cash_flow_statement(ticker, "quarter", 4),
                staleness_days,
            ),
        )

    income_annual = income_annual if isinstance(income_annual, list) else []
    income_quarterly = income_quarterly if isinstance(income_quarterly, list) else []
    cash_flow_annual = cash_flow_annual if isinstance(cash_flow_annual, list) else []
    cash_flow_quarterly = cash_flow_quarterly if isinstance(cash_flow_quarterly, list) else []

    years, revenue = _annual_series(income_annual, "revenue")
    _, gross_profit = _annual_series(income_annual, "grossProfit")
    _, operating_income = _annual_series(income_annual, "operatingIncome")
    _, net_income = _annual_series(income_annual, "netIncome")

    cash_flow_by_year = {row.get("fiscalYear"): row for row in cash_flow_annual}
    cfo = [cash_flow_by_year.get(year, {}).get("netCashProvidedByOperatingActivities") for year in years]

    years = years + ["TTM"]
    revenue = revenue + [sum_last_four_quarters(income_quarterly, "revenue")]
    gross_profit = gross_profit + [sum_last_four_quarters(income_quarterly, "grossProfit")]
    operating_income = operating_income + [sum_last_four_quarters(income_quarterly, "operatingIncome")]
    net_income = net_income + [sum_last_four_quarters(income_quarterly, "netIncome")]
    cfo = cfo + [sum_last_four_quarters(cash_flow_quarterly, "netCashProvidedByOperatingActivities")]

    gross_margin = [(gp / rev * 100) if gp is not None and rev else None for gp, rev in zip(gross_profit, revenue)]
    net_margin = [(ni / rev * 100) if ni is not None and rev else None for ni, rev in zip(net_income, revenue)]

    exemption = _detect_exemption(profile.get("sector"), profile.get("industry"))
    cfo_exempt = exemption is not None

    # classify_trend needs a clean, gap-free chronological series -- the raw
    # (with-gaps) arrays above are what the UI renders, these filtered copies
    # are only for scoring.
    clean_cfo = [v for v in cfo if v is not None] if not cfo_exempt else None

    result = score_step1(
        revenue=[v for v in revenue if v is not None],
        net_income=[v for v in net_income if v is not None],
        operating_income=[v for v in operating_income if v is not None],
        cfo=clean_cfo,
        gross_margin=[v for v in gross_margin if v is not None],
        net_margin=[v for v in net_margin if v is not None],
        cfo_exempt=cfo_exempt,
    )

    return Step1Out(
        ticker=ticker,
        years=years,
        revenue=revenue,
        net_income=net_income,
        operating_income=operating_income,
        cfo=None if cfo_exempt else cfo,
        gross_margin=gross_margin,
        net_margin=net_margin,
        cfo_exempt_reason=exemption,
        score=result["score"],
        verdict=result["verdict"],
        components=result["components"],
    )
