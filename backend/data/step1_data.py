from sqlmodel import Session

from core.cache import get_or_fetch, safe_fetch
from core.config import settings
from core.db import engine
from helpers.earnings import resolve_most_recent_earnings_date
from helpers.first import _first
from clients.fmp_client import fmp_client
from core.schemas import OutlierWarning, Step1Out
from core.tickers import normalize_ticker
from data.score_weights import load_score_weights
from scoring.classification import classify_company_type
from scoring.weights import ScoreWeights
from scoring.step1 import MARGINS_SEVERITY_CARVEOUT_TYPES, score_step1
from helpers.statement_view import load_statement_view
from helpers.ttm import sum_last_four_quarters


# Banks (2026-09-10): Margins is excluded from scoring entirely, on top of
# the existing CFO/FCF exemption -- mirrors the AR_EXEMPT_TYPES/
# ROIC_EXEMPT_TYPES company-type-set pattern (data/step4_data.py), just
# scoped to Step 1's own Margins component. Confirmed via a full-universe
# scan that grossProfit/revenue -- the raw GAAP line Margins is computed
# from, unchanged by the Bank Net-Interest-Income substitution below --
# shows the identical structural break for all 28 Bank-classified tickers
# with margin data: at or above 100% (a mathematically impossible "gross
# margin") around FY2021, then a permanent drop to a 42-77% plateau from
# FY2022 on. An FMP data-methodology break specific to financial-services
# reporting, not a real margin trend -- the same "this GAAP line doesn't
# map onto this business model" reasoning that already justifies the CFO
# exemption for Banks, just discovered later. Insurance/Property Developer/
# Commodity Company are deliberately NOT included here -- the same
# investigation found their margins are mostly a working signal (Insurance,
# Commodity Company) or a real-but-differently-shaped, separately-scoped
# data issue (REIT's own terminal-period collapse, not yet investigated)
# rather than sharing Banks' universal root cause. See CLAUDE.md's Step 1
# deviations for the full investigation.
MARGINS_EXEMPT_TYPES = {"Bank"}

# Commodity Company is detected by profile sector text alone (Basic Materials/Energy), so a ticker FMP files under the wrong sector
# gets the CFO/FCF exemption it should not have. Same pattern as scoring/classification.py::NON_LENDER_TICKER_OVERRIDES: a small,
# hand-verified, ticker-keyed set (it does not depend on the cached profile, so a profile refresh cannot undo it, and it does not
# change the displayed sector). JCI (Johnson Controls) and MAS (Masco) are industrials (S&P 500 sector Industrials) but FMP labels
# both "Basic Materials / Construction Materials" (2026-10-07). Listed ones are scored as Standard in Step 1: CFO and FCF scored,
# standard weights. See docs/specs/company-type-variations.md and docs/decisions.md 2026-10-07.
COMMODITY_EXEMPTION_TICKER_OVERRIDES = {"JCI", "MAS"}


def _detect_exemption(
    sector: str | None, industry: str | None, ticker: str | None = None, is_fund: bool = False
) -> str | None:
    """Heuristic sector/industry match for the Step 1 CFO exemption (Bank /
    Insurance / Property Developer / Commodity Company) — not exhaustive
    industry-code matching, a reasonable approximation for this phase.

    Delegates Bank/Insurance/REIT/ETF detection to the shared
    scoring.classification.classify_company_type -- the same classifier
    Step 4/5/Valuation use -- so Step 1 never drifts out of sync with them
    again (this used to be a fully standalone keyword match that only knew
    about Bank/Real Estate/Basic Materials+Energy, and had no Insurance
    branch at all: Insurance tickers got no CFO de-emphasis even though the
    reasoning -- claim timing, reserve movements, investment portfolio
    fluctuations making OCF noisy -- applies to them exactly as it does to
    Banks). Commodity Company has no equivalent in the shared classifier
    (it's a Step 1-only exemption), so that check stays local. ETF isn't a
    Step 1 exemption either (falling through to `None` here is correct --
    an ETF has no CFO to de-emphasize/swap, it just naturally scores
    insufficient_data on real, non-Bank-shaped Revenue/CFO series)."""
    sector = (sector or "").strip()
    shared_type = classify_company_type(sector, industry, ticker, is_fund=is_fund)
    if shared_type in ("Bank", "Insurance"):
        return shared_type
    if shared_type == "REIT/Property Developer":
        return "Property Developer"
    if sector in {"Basic Materials", "Energy"} and not (ticker and ticker.upper() in COMMODITY_EXEMPTION_TICKER_OVERRIDES):
        return "Commodity Company"
    return None


def _annual_series(annual_rows: list[dict], field: str) -> tuple[list[str], list[float | None]]:
    # FMP returns annual rows most-recent-first; reverse to chronological
    # (oldest fiscal year first) since that's the order classify_trend expects.
    rows = list(reversed(annual_rows))
    years = [row.get("fiscalYear", row.get("date", "")[:4]) for row in rows]
    values = [row.get(field) for row in rows]
    return years, values


async def get_step1_data(ticker: str, cache_only: bool = False, weights: ScoreWeights | None = None) -> Step1Out:
    """`cache_only=True` (used by ticker_score.py's recompute path) reads
    only whatever's already cached and never calls FMP -- see
    cache.get_or_fetch's own cache_only branch."""
    ticker = normalize_ticker(ticker)
    weights = weights if weights is not None else load_score_weights(engine).weights
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
        # Placeholder cash-flow rows and mis-scaled rows are treated as missing
        # -- see helpers/statement_view.py (via ttm.py::clean_cash_flow_statements:
        # quarterly, the newest run is dropped so TTM covers the last four valid
        # quarters; annual, blanked in place). Step 1 reads no balance sheet, so
        # no gate or alignment applies.
        view = await load_statement_view(
            session,
            ticker,
            None,
            most_recent_earnings_date=most_recent_earnings_date,
            staleness_days=staleness_days,
            cache_only=cache_only,
            balance_sheet=False,
        )

    income_annual = view.income_annual
    income_quarterly = view.income_quarterly
    cash_flow_annual = view.cash_flow_annual
    cash_flow_quarterly = view.cash_flow_quarterly

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

    # Scoring reads the completed fiscal years only (docs/specs/financials.md); the TTM point appended below is display-only.
    annual = {
        "revenue": revenue,
        "net_interest_income": net_interest_income,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "net_income": net_income,
        "cfo": cfo,
        "capex": capex,
    }

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
    def _margins(numerator: list[float | None], denominator: list[float | None]) -> list[float | None]:
        return [(n / d * 100) if n is not None and d else None for n, d in zip(numerator, denominator)]

    gross_margin = _margins(gross_profit, revenue)
    net_margin = _margins(net_income, revenue)

    is_fund = bool(profile.get("isEtf") or profile.get("isFund"))
    exemption = _detect_exemption(profile.get("sector"), profile.get("industry"), ticker, is_fund=is_fund)
    cfo_exempt = exemption is not None
    is_bank = exemption == "Bank"
    margins_exempt = exemption in MARGINS_EXEMPT_TYPES
    # Uses classify_company_type's own raw return value, not _detect_
    # exemption's remapped one -- _detect_exemption never surfaces "Utility"
    # at all (Step 1 doesn't CFO-exempt utilities), and renames "REIT/
    # Property Developer" to "Property Developer" for Step 1's own display
    # purposes, neither of which matches MARGINS_SEVERITY_CARVEOUT_TYPES's
    # naming (which mirrors AR_EXEMPT_TYPES/ROIC_EXEMPT_TYPES exactly).
    company_type = classify_company_type(profile.get("sector"), profile.get("industry"), ticker, is_fund=is_fund)
    margins_severity_carveout = company_type in MARGINS_SEVERITY_CARVEOUT_TYPES

    # Banks: the Revenue check (score + Financials Trend chart) uses Net
    # Interest Income instead of Revenue -- FMP's netInterestIncome is a
    # clean standard-schema field, unlike Revenue which mixes interest and
    # non-interest income in a way that obscures the core lending-spread
    # trend.
    display_revenue = net_interest_income if is_bank else revenue
    revenue_label = "Net Interest Income" if is_bank else "Revenue"

    # The engine needs a clean, gap-free chronological series of COMPLETED fiscal years -- the raw (with-gaps, TTM-ended) arrays above
    # are what the UI renders, the annual-only filtered copies below are only for scoring. FCF mirrors CFO's exemption exactly (it is
    # derived from CFO, so the same "not a reliable signal for these business models" reasoning applies). Computed unconditionally,
    # regardless of cfo_exempt: score_step1 short-circuits on the `cfo_exempt` flag itself, so the cfo/fcf values passed for an
    # exempt ticker are never consulted.
    def _present(values: list[float | None]) -> list[float]:
        return [v for v in values if v is not None]

    revenue_fy = annual["revenue"]
    cfo_fy = annual["cfo"]
    fcf_fy = [c + x if c is not None and x is not None else None for c, x in zip(cfo_fy, annual["capex"])]
    display_revenue_fy = annual["net_interest_income"] if is_bank else revenue_fy
    gross_margin_fy = _margins(annual["gross_profit"], revenue_fy)
    operating_margin_fy = _margins(annual["operating_income"], revenue_fy)
    net_margin_fy = _margins(annual["net_income"], revenue_fy)

    result = score_step1(
        revenue=_present(display_revenue_fy),
        net_income=_present(annual["net_income"]),
        operating_income=_present(annual["operating_income"]),
        cfo=_present(cfo_fy),
        gross_margin=_present(gross_margin_fy),
        operating_margin=_present(operating_margin_fy),
        net_margin=_present(net_margin_fy),
        cfo_exempt=cfo_exempt,
        fcf=_present(fcf_fy),
        margin_context_revenue=_present(revenue_fy),
        margins_exempt=margins_exempt,
        margins_severity_carveout=margins_severity_carveout,
        # Real revenue (not the Bank Net-Interest-Income substitution) and Operating Income of the last completed fiscal year (None
        # when missing) for the Operating Income backup's quality gates -- the filtered series above can't tell a missing latest year
        # from a present one.
        latest_revenue=revenue_fy[-1] if revenue_fy else None,
        latest_operating_income=annual["operating_income"][-1] if annual["operating_income"] else None,
        weights=weights.step1,
    )

    return Step1Out(
        ticker=ticker,
        years=years,
        revenue=display_revenue,
        revenue_label=revenue_label,
        net_income=net_income,
        operating_income=operating_income,
        # Real values now pass through unconditionally -- display is
        # decoupled from scoring. The score itself still excludes cfo/fcf
        # entirely for an exempt ticker via score_step1's own `cfo_exempt`
        # param above, independent of what's returned here for the UI.
        cfo=cfo,
        fcf=fcf,
        gross_margin=gross_margin,
        net_margin=net_margin,
        cfo_exempt_reason=exemption,
        score=result["score"],
        verdict=result["verdict"],
        components=result["components"],
        weights=result["weights"],
        outlier_warnings=outlier_warnings,
    )
