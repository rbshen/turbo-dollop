from sqlmodel import Session

from core.cache import get_or_fetch, get_or_fetch_earnings_aware, safe_fetch
from core.config import settings
from core.db import engine
from clients.fmp_client import fmp_client
from data.moat import get_ticker_moat
from data.step1_data import get_step1_data
from data.step2_data import get_step2_data
from helpers.earnings import resolve_most_recent_earnings_date
from helpers.first import _first
from core.schemas import SpeculativeGrowthOut
from core.tickers import normalize_ticker
from scoring.classification import classify_company_type
from scoring.speculative_growth import (
    cash_runway_years,
    cfo_recent_direction,
    evaluate_speculative_growth,
    psg_ratio,
    trailing_revenue_growth_pct,
)
from helpers.ttm import TOTAL_QUARTERS_NEEDED


async def get_speculative_growth_data(ticker: str, cache_only: bool = False) -> SpeculativeGrowthOut:
    """New, independent, read-only classification layered on top of the
    existing 5-step framework -- see CLAUDE.md's Speculative Growth
    investigation/design notes and scoring/speculative_growth.py. Never
    writes to or reads back from Step1-5/Overall Assessment's own scoring;
    only reuses their already-computed outputs (get_step1_data/
    get_step2_data/get_ticker_moat) as read-only inputs.

    `cache_only=True` (mirrors every other get_stepN_data function) reads
    only whatever's already cached and never calls FMP.
    """
    ticker = normalize_ticker(ticker)
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        # Same cache key ("profile"/"latest") Step 1/2/4/5 already populate
        # -- a cache hit, not a new fetch, for any ticker already viewed
        # elsewhere in the app.
        profile = _first(
            await safe_fetch(
                "profile",
                get_or_fetch(
                    session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days, cache_only
                ),
            )
        )
        company_type = classify_company_type(profile.get("sector"), profile.get("industry"), ticker)

        if company_type != "Standard":
            gate = evaluate_speculative_growth(company_type, moat=None, growth_rate_pct=None)
            return SpeculativeGrowthOut(
                ticker=ticker,
                qualifies=gate.qualifies,
                company_type=company_type,
                not_applicable_reason=gate.not_applicable_reason,
            )

        moat_row = get_ticker_moat(session, ticker)
        moat = moat_row.moat if moat_row else None

        # Only resolved here, past the Standard-type check above -- computing
        # it unconditionally at function top would cost every non-Standard
        # ticker an unused /earnings fetch/cache-read for a value nothing
        # else in the early-return branch needs (same motivation as
        # step2_data.py's own REIT-only resolve_most_recent_earnings_date call).
        most_recent_earnings_date = await resolve_most_recent_earnings_date(session, ticker, staleness_days, cache_only)

        # Same cache key Step 1/Step 5 already populate ("cash_flow_statement"/
        # "quarterly") -- fetched here in raw quarterly form (rather than
        # reusing Step1Out.cfo, which is annual+TTM only) purely for
        # cfo_recent_direction's last-2-quarters read.
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
        # Same cache key Step 5/ticker_summary already populate
        # ("balance_sheet_statement"/"quarterly").
        balance_sheet_quarterly = await safe_fetch(
            "balance_sheet_statement_quarterly",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "balance_sheet_statement",
                "quarterly",
                lambda: fmp_client.get_balance_sheet_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        # Same cache key ticker_summary.py already populates ("ratios"/"latest").
        ratios = _first(
            await safe_fetch(
                "ratios",
                get_or_fetch(
                    session, ticker, "ratios", "latest", lambda: fmp_client.get_ratios(ticker), staleness_days, cache_only
                ),
            )
        )

    cash_flow_quarterly = cash_flow_quarterly if isinstance(cash_flow_quarterly, list) else []
    balance_sheet_quarterly = balance_sheet_quarterly if isinstance(balance_sheet_quarterly, list) else []

    step1_out = await get_step1_data(ticker, cache_only)
    step2_out = await get_step2_data(ticker, cache_only)

    if step1_out.cfo_exempt_reason is not None:
        # A CFO-exempt Step1 ticker (Bank/Insurance/Property Developer/
        # Commodity Company) indicates a non-Standard-shaped business even
        # when classify_company_type alone read "Standard" -- Step 1's own
        # exemption detection (_detect_exemption) is a superset of the
        # shared classifier (it also catches Commodity Company, which
        # classify_company_type has no equivalent branch for).
        gate = evaluate_speculative_growth(step1_out.cfo_exempt_reason, moat=None, growth_rate_pct=None)
        return SpeculativeGrowthOut(
            ticker=ticker,
            qualifies=False,
            company_type=step1_out.cfo_exempt_reason,
            not_applicable_reason=gate.not_applicable_reason,
        )

    ttm_revenue = step1_out.revenue[-1] if step1_out.revenue else None
    last_fy_revenue = step1_out.revenue[-2] if len(step1_out.revenue) >= 2 else None
    trailing_growth = trailing_revenue_growth_pct(ttm_revenue, last_fy_revenue)

    gross_margin_ttm = step1_out.gross_margin[-1] if step1_out.gross_margin else None
    net_income_ttm = step1_out.net_income[-1] if step1_out.net_income else None
    cfo_ttm = step1_out.cfo[-1] if step1_out.cfo else None

    latest_bs = _first(balance_sheet_quarterly)
    cash_and_st_investments = latest_bs.get("cashAndShortTermInvestments")
    if cash_and_st_investments is None:
        cash_and_st_investments = latest_bs.get("cashAndCashEquivalents")

    q0 = cash_flow_quarterly[0].get("netCashProvidedByOperatingActivities") if cash_flow_quarterly else None
    q1 = cash_flow_quarterly[1].get("netCashProvidedByOperatingActivities") if len(cash_flow_quarterly) >= 2 else None
    cfo_direction = cfo_recent_direction(q0, q1)

    price_to_sales_ttm = ratios.get("priceToSalesRatio")
    psg = psg_ratio(price_to_sales_ttm, trailing_growth)

    gate = evaluate_speculative_growth(company_type, moat, step2_out.growth_rate, step1_out.net_income)

    return SpeculativeGrowthOut(
        ticker=ticker,
        qualifies=gate.qualifies,
        company_type=company_type,
        not_applicable_reason=gate.not_applicable_reason,
        moat=moat,
        growth_rate_pct=step2_out.growth_rate,
        growth_basis=step2_out.basis,
        trailing_revenue_growth_pct=trailing_growth,
        gross_margin_ttm_pct=gross_margin_ttm,
        net_income_ttm=net_income_ttm,
        cfo_ttm=cfo_ttm,
        cfo_recent_direction=cfo_direction,
        cash_and_st_investments=cash_and_st_investments,
        cash_runway_years=cash_runway_years(cash_and_st_investments, cfo_ttm),
        price_to_sales_ttm=price_to_sales_ttm,
        psg_ratio=psg,
    )
