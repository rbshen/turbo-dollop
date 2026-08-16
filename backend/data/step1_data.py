from sqlmodel import Session

from core.cache import get_or_fetch, get_or_fetch_earnings_aware, safe_fetch
from core.config import settings
from core.db import engine
from helpers.earnings import resolve_most_recent_earnings_date
from helpers.first import _first
from clients.fmp_client import fmp_client
from core.schemas import OutlierWarning, Step1Out
from core.tickers import normalize_ticker
from scoring.classification import classify_company_type
from scoring.step1 import score_step1
from helpers.ttm import TOTAL_QUARTERS_NEEDED, sum_last_four_quarters


def _detect_exemption(sector: str | None, industry: str | None, ticker: str | None = None) -> str | None:
    """Heuristic sector/industry match for the Step 1 CFO exemption (Bank /
    Insurance / Property Developer / Commodity Company) — not exhaustive
    industry-code matching, a reasonable approximation for this phase.

    Delegates Bank/Insurance/REIT detection to the shared
    scoring.classification.classify_company_type -- the same classifier
    Step 4/5/Valuation use -- so Step 1 never drifts out of sync with them
    again (this used to be a fully standalone keyword match that only knew
    about Bank/Real Estate/Basic Materials+Energy, and had no Insurance
    branch at all: Insurance tickers got no CFO de-emphasis even though the
    reasoning -- claim timing, reserve movements, investment portfolio
    fluctuations making OCF noisy -- applies to them exactly as it does to
    Banks). Commodity Company has no equivalent in the shared classifier
    (it's a Step 1-only exemption), so that check stays local."""
    sector = (sector or "").strip()
    shared_type = classify_company_type(sector, industry, ticker)
    if shared_type in ("Bank", "Insurance"):
        return shared_type
    if shared_type == "REIT/Property Developer":
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


async def get_step1_data(ticker: str, cache_only: bool = False) -> Step1Out:
    """`cache_only=True` (used by ticker_score.py's recompute path) reads
    only whatever's already cached and never calls FMP -- see
    cache.get_or_fetch's own cache_only branch."""
    ticker = normalize_ticker(ticker)
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        most_recent_earnings_date = await resolve_most_recent_earnings_date(session, ticker, staleness_days, cache_only)
        profile = _first(
            await safe_fetch(
                "profile",
                get_or_fetch(
                    session,
                    ticker,
                    "profile",
                    "latest",
                    lambda: fmp_client.get_profile(ticker),
                    settings.profile_staleness_days,
                    cache_only,
                ),
            )
        )
        income_annual = await safe_fetch(
            "income_statement_annual",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "income_statement",
                "annual",
                lambda: fmp_client.get_income_statement(ticker, "annual", 10),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        income_quarterly = await safe_fetch(
            "income_statement_quarterly",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "income_statement",
                "quarterly",
                lambda: fmp_client.get_income_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        cash_flow_annual = await safe_fetch(
            "cash_flow_statement_annual",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "cash_flow_statement",
                "annual",
                lambda: fmp_client.get_cash_flow_statement(ticker, "annual", 10),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        cash_flow_quarterly = await safe_fetch(
            "cash_flow_statement_quarterly",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "cash_flow_statement",
                "quarterly",
                lambda: fmp_client.get_cash_flow_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )

    income_annual = income_annual if isinstance(income_annual, list) else []
    income_quarterly = income_quarterly if isinstance(income_quarterly, list) else []
    cash_flow_annual = cash_flow_annual if isinstance(cash_flow_annual, list) else []
    cash_flow_quarterly = cash_flow_quarterly if isinstance(cash_flow_quarterly, list) else []

    years, revenue = _annual_series(income_annual, "revenue")
    _, net_interest_income = _annual_series(income_annual, "netInterestIncome")
    _, gross_profit = _annual_series(income_annual, "grossProfit")
    _, operating_income = _annual_series(income_annual, "operatingIncome")
    _, net_income = _annual_series(income_annual, "netIncome")

    cash_flow_by_year = {row.get("fiscalYear"): row for row in cash_flow_annual}
    cfo = [cash_flow_by_year.get(year, {}).get("netCashProvidedByOperatingActivities") for year in years]
    # capitalExpenditure is already reported as a negative number (cash
    # outflow) by FMP -- FCF = CFO + capitalExpenditure, not CFO -
    # capitalExpenditure, which would double-subtract it.
    capex = [cash_flow_by_year.get(year, {}).get("capitalExpenditure") for year in years]

    years = years + ["TTM"]
    revenue_result = sum_last_four_quarters(income_quarterly, "revenue", income_annual)
    net_interest_income_result = sum_last_four_quarters(income_quarterly, "netInterestIncome", income_annual)
    gross_profit_result = sum_last_four_quarters(income_quarterly, "grossProfit", income_annual)
    operating_income_result = sum_last_four_quarters(income_quarterly, "operatingIncome", income_annual)
    net_income_result = sum_last_four_quarters(income_quarterly, "netIncome", income_annual)
    cfo_result = sum_last_four_quarters(cash_flow_quarterly, "netCashProvidedByOperatingActivities", cash_flow_annual)
    capex_result = sum_last_four_quarters(cash_flow_quarterly, "capitalExpenditure", cash_flow_annual)

    revenue = revenue + [revenue_result.total]
    net_interest_income = net_interest_income + [net_interest_income_result.total]
    gross_profit = gross_profit + [gross_profit_result.total]
    operating_income = operating_income + [operating_income_result.total]
    net_income = net_income + [net_income_result.total]
    cfo = cfo + [cfo_result.total]
    capex = capex + [capex_result.total]

    # Informational only -- never changes revenue/net_income/cfo/fcf or the
    # score/verdict below (see ttm.py::sum_last_four_quarters). Same
    # convention as Step 5/the ticker header; Step 1 previously computed
    # these flags via sum_last_four_quarters and silently discarded them.
    outlier_warnings = [
        OutlierWarning(metric=metric, date=fq.date, value=fq.value, trailing_median=fq.trailing_median)
        for metric, result in [
            ("revenue", revenue_result),
            ("net_interest_income", net_interest_income_result),
            ("gross_profit", gross_profit_result),
            ("operating_income", operating_income_result),
            ("net_income", net_income_result),
            ("cfo", cfo_result),
            ("capex", capex_result),
        ]
        for fq in result.flagged
    ]

    fcf = [c + x if c is not None and x is not None else None for c, x in zip(cfo, capex)]

    # Margins are always computed from real Revenue, regardless of company
    # type -- deliberately untouched by the Bank substitution below.
    gross_margin = [(gp / rev * 100) if gp is not None and rev else None for gp, rev in zip(gross_profit, revenue)]
    net_margin = [(ni / rev * 100) if ni is not None and rev else None for ni, rev in zip(net_income, revenue)]

    exemption = _detect_exemption(profile.get("sector"), profile.get("industry"), ticker)
    cfo_exempt = exemption is not None
    is_bank = exemption == "Bank"

    # Banks: the Revenue check (score + Financials Trend chart) uses Net
    # Interest Income instead of Revenue -- FMP's netInterestIncome is a
    # clean standard-schema field, unlike Revenue which mixes interest and
    # non-interest income in a way that obscures the core lending-spread
    # trend.
    display_revenue = net_interest_income if is_bank else revenue
    revenue_label = "Net Interest Income" if is_bank else "Revenue"

    # classify_trend needs a clean, gap-free chronological series -- the raw
    # (with-gaps) arrays above are what the UI renders, these filtered copies
    # are only for scoring. FCF mirrors CFO's exemption exactly (it's
    # derived from CFO, so the same "not a reliable signal for these
    # business models" reasoning applies).
    clean_cfo = [v for v in cfo if v is not None] if not cfo_exempt else None
    clean_fcf = [v for v in fcf if v is not None] if not cfo_exempt else None
    # NOT the same filter as clean_cfo above: fcf[i] is None whenever EITHER
    # cfo[i] or capex[i] is missing, so clean_cfo's own independent
    # None-filter can drop a different set of periods than clean_fcf did --
    # passing clean_cfo alongside clean_fcf would silently desync indices.
    # This filter instead walks fcf's own None-ness, guaranteeing fcf_cfo is
    # None-free and positionally aligned with clean_fcf (fcf[i] is only
    # non-None when cfo[i] is too).
    fcf_cfo = [c for c, f in zip(cfo, fcf) if f is not None] if not cfo_exempt else None

    result = score_step1(
        revenue=[v for v in display_revenue if v is not None],
        net_income=[v for v in net_income if v is not None],
        operating_income=[v for v in operating_income if v is not None],
        cfo=clean_cfo,
        gross_margin=[v for v in gross_margin if v is not None],
        net_margin=[v for v in net_margin if v is not None],
        cfo_exempt=cfo_exempt,
        fcf=clean_fcf,
        margin_context_revenue=[v for v in revenue if v is not None],
        fcf_cfo=fcf_cfo,
    )

    return Step1Out(
        ticker=ticker,
        years=years,
        revenue=display_revenue,
        revenue_label=revenue_label,
        net_income=net_income,
        operating_income=operating_income,
        cfo=None if cfo_exempt else cfo,
        fcf=None if cfo_exempt else fcf,
        gross_margin=gross_margin,
        net_margin=net_margin,
        cfo_exempt_reason=exemption,
        score=result["score"],
        verdict=result["verdict"],
        components=result["components"],
        weights=result["weights"],
        outlier_warnings=outlier_warnings,
    )
