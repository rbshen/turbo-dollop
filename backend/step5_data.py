from sqlmodel import Session

from cache import get_or_fetch, safe_fetch
from config import settings
from db import engine
from fmp_client import fmp_client
from schemas import Step5Out, Step5RatioResult
from scoring.step5 import classify_company_type, score_step5_reit, score_step5_standard
from ttm import sum_last_four_quarters


def _first(data: dict | list) -> dict:
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def _ratio_out(raw: dict) -> Step5RatioResult:
    return Step5RatioResult(value=raw["value"], label=raw["label"], points=raw["points"])


async def get_step5_data(ticker: str) -> Step5Out:
    ticker = ticker.upper()
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        profile = _first(
            await safe_fetch(
                "profile",
                get_or_fetch(session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days),
            )
        )
        company_type = classify_company_type(profile.get("sector"), profile.get("industry"))

        if company_type == "Bank":
            # Investigation already confirmed FMP has no CET1 field and no
            # raw components to compute one -- deferred, not approximated.
            return Step5Out(ticker=ticker, company_type=company_type, score=None, verdict="not_supported")

        # Balance sheet items are point-in-time snapshots -- the latest
        # available quarter is simply more current than the latest annual
        # filing (which can be many months stale by the time this is viewed).
        balance_sheet = await safe_fetch(
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
        # EBITDA, net interest expense, and CFO are flow measures (activity
        # over a period), not snapshots -- a single quarter's figure would
        # understate them ~4x relative to the debt figures they're compared
        # against, so these are summed trailing-twelve-months instead, same
        # convention and cache key + limit Step 1 already populates
        # ("income_statement"/"quarterly" and "cash_flow_statement"/
        # "quarterly", both limit 4).
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

    balance_sheet_row = _first(balance_sheet)
    income_quarterly = income_quarterly if isinstance(income_quarterly, list) else []
    cash_flow_quarterly = cash_flow_quarterly if isinstance(cash_flow_quarterly, list) else []

    ebitda_ttm = sum_last_four_quarters(income_quarterly, "ebitda")
    net_interest_income_ttm = sum_last_four_quarters(income_quarterly, "netInterestIncome")
    cfo_ttm = sum_last_four_quarters(cash_flow_quarterly, "netCashProvidedByOperatingActivities")

    total_debt = balance_sheet_row.get("totalDebt")
    total_assets = balance_sheet_row.get("totalAssets")
    deferred_revenue = balance_sheet_row.get("deferredRevenue")

    if company_type == "REIT/Property Developer":
        if total_debt is None or not total_assets:
            return Step5Out(ticker=ticker, company_type=company_type, score=None, verdict="insufficient_data")

        gearing_pct = total_debt / total_assets * 100
        result = score_step5_reit(gearing_pct)
        return Step5Out(
            ticker=ticker,
            company_type=company_type,
            ratios={"gearing_ratio": _ratio_out(result["ratios"]["gearing_ratio"])},
            deferred_revenue_current=deferred_revenue,
            score=result["score"],
            verdict=result["verdict"],
            hard_fail=result["hard_fail"],
        )

    # Standard path.
    current_assets = balance_sheet_row.get("totalCurrentAssets")
    current_liabilities = balance_sheet_row.get("totalCurrentLiabilities")
    short_term_debt = balance_sheet_row.get("shortTermDebt")
    long_term_debt = balance_sheet_row.get("longTermDebt")

    current_ratio = current_assets / current_liabilities if current_assets is not None and current_liabilities else None
    debt_to_ebitda = (
        ((short_term_debt or 0) + (long_term_debt or 0)) / ebitda_ttm
        if ebitda_ttm is not None and ebitda_ttm > 0
        else None
    )
    # A company earning net interest income has no interest burden for this
    # ratio's purpose (clamped at 0, not left negative).
    net_interest_expense_ttm = max(0.0, -net_interest_income_ttm) if net_interest_income_ttm is not None else None
    # CFO <= 0 makes the ratio meaningless (or sign-flipped) rather than
    # just large -- treated as unavailable, not computed.
    debt_servicing_pct = (
        net_interest_expense_ttm / cfo_ttm * 100
        if net_interest_expense_ttm is not None and cfo_ttm is not None and cfo_ttm > 0
        else None
    )

    if current_ratio is None or debt_to_ebitda is None or debt_servicing_pct is None:
        return Step5Out(ticker=ticker, company_type=company_type, score=None, verdict="insufficient_data")

    result = score_step5_standard(current_ratio, debt_to_ebitda, debt_servicing_pct)
    return Step5Out(
        ticker=ticker,
        company_type=company_type,
        ratios={
            "current_ratio": _ratio_out(result["ratios"]["current_ratio"]),
            "debt_to_ebitda": _ratio_out(result["ratios"]["debt_to_ebitda"]),
            "debt_servicing_ratio": _ratio_out(result["ratios"]["debt_servicing_ratio"]),
        },
        deferred_revenue_current=deferred_revenue,
        score=result["score"],
        verdict=result["verdict"],
        hard_fail=result["hard_fail"],
    )
