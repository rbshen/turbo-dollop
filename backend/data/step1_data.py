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


# CFO, FCF and Margins are all skipped for the four exempt types (2026-10-08, docs/decisions.md): Bank, Insurance, Property Developer
# (REIT) and Commodity Company are scored on Revenue (the real FMP revenue line, for Banks too: the old Net Interest Income
# substitution is gone) and Net Income, with Operating Income as the Net Income backup only. The score_step1 weight table for them is
# the one scoring/weights.py::step1_tables calls the "Bank" table (CFO/FCF/Margins weight spread proportionally over Revenue and Net
# Income), applied to the saved weights as well as the defaults. Standard and Utility keep all five components; Utility keeps its
# margin severity carve-out (scoring/step1.py). Before 2026-10-08 only Banks skipped Margins (an FMP gross-profit break across all 28
# Bank tickers with margin data around FY2021); Insurance, Property Developer and Commodity Company kept it.
MARGINS_EXEMPT_TYPES = {"Bank", "Insurance", "Property Developer", "Commodity Company"}

# Commodity Company (CFO and FCF skipped) is a price-taking producer or extractor: the profile sector is Basic Materials or Energy AND
# the FMP industry is one of these. The rule is deliberately narrow: a company that merely sits in one of the two sectors (specialty
# and industrial chemicals, construction materials, oilfield services, midstream pipelines, solar) sells at contract or list prices and
# is scored as Standard, CFO and FCF included. The list includes producer labels FMP uses that no scored ticker has today (aluminum,
# silver, other metals, coal) so a future ticker is handled. Matched exactly (after stripping), FMP's own spelling. A ticker in the two
# sectors with NO industry on its cached profile stays Commodity (the pre-2026-10-07 behaviour), so nothing changes silently.
# See docs/specs/company-type-variations.md and docs/decisions.md 2026-10-07 (Commodity exemption: industry allowlist).
COMMODITY_SECTORS = frozenset({"Basic Materials", "Energy"})
COMMODITY_PRODUCER_INDUSTRIES = frozenset(
    {
        "Oil & Gas Exploration & Production",
        "Oil & Gas Integrated",
        "Oil & Gas Refining & Marketing",
        "Agricultural Inputs",
        "Uranium",
        "Copper",
        "Gold",
        "Steel",
        "Paper, Lumber & Forest Products",
        "Aluminum",
        "Silver",
        "Other Industrial Metals & Mining",
        "Other Precious Metals & Mining",
        "Coal",
        "Thermal Coal",
        "Coking Coal",
    }
)

# A ticker FMP files under the wrong sector (JCI, MAS: "Basic Materials / Construction Materials", both S&P 500 Industrials) is scored
# as Standard whatever the industry rule says. Same pattern as scoring/classification.py::NON_LENDER_TICKER_OVERRIDES: a small,
# hand-verified, ticker-keyed set that does not depend on the cached profile. Since the industry allowlist above, Construction
# Materials is no longer Commodity, so these two are redundant; kept so a relabel by FMP into a producer industry cannot flip them.
COMMODITY_EXEMPTION_TICKER_OVERRIDES = {"JCI", "MAS"}


def _is_commodity_company(sector: str, industry: str | None, ticker: str | None) -> bool:
    """The Step 1 Commodity Company rule: sector Basic Materials/Energy, industry on the producer allowlist (or missing)."""
    if sector not in COMMODITY_SECTORS:
        return False
    if ticker and ticker.upper() in COMMODITY_EXEMPTION_TICKER_OVERRIDES:
        return False
    industry = (industry or "").strip()
    return not industry or industry in COMMODITY_PRODUCER_INDUSTRIES


def _detect_exemption(
    sector: str | None, industry: str | None, ticker: str | None = None, is_fund: bool = False
) -> str | None:
    """Heuristic sector/industry match for the Step 1 exemption from CFO, FCF and Margins (Bank /
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
    if _is_commodity_company(sector, industry, ticker):
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
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "net_income": net_income,
        "cfo": cfo,
        "capex": capex,
    }

    years = years + ["TTM"]
    revenue_result = sum_last_four_quarters(income_quarterly, "revenue", income_annual)
    gross_profit_result = sum_last_four_quarters(income_quarterly, "grossProfit", income_annual)
    operating_income_result = sum_last_four_quarters(income_quarterly, "operatingIncome", income_annual)
    net_income_result = sum_last_four_quarters(income_quarterly, "netIncome", income_annual)
    cfo_result = sum_last_four_quarters(cash_flow_quarterly, "netCashProvidedByOperatingActivities", cash_flow_annual)
    capex_result = sum_last_four_quarters(cash_flow_quarterly, "capitalExpenditure", cash_flow_annual)

    revenue = revenue + [revenue_result.total]
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
            ("gross_profit", gross_profit_result),
            ("operating_income", operating_income_result),
            ("net_income", net_income_result),
            ("cfo", cfo_result),
            ("capex", capex_result),
        ]
        for fq in result.flagged
    ]

    fcf = [c + x if c is not None and x is not None else None for c, x in zip(cfo, capex)]

    # Margin series are display-only for the exempt types and scored for Standard/Utility; always computed from real Revenue.
    def _margins(numerator: list[float | None], denominator: list[float | None]) -> list[float | None]:
        return [(n / d * 100) if n is not None and d else None for n, d in zip(numerator, denominator)]

    gross_margin = _margins(gross_profit, revenue)
    net_margin = _margins(net_income, revenue)

    is_fund = bool(profile.get("isEtf") or profile.get("isFund"))
    exemption = _detect_exemption(profile.get("sector"), profile.get("industry"), ticker, is_fund=is_fund)
    cfo_exempt = exemption is not None
    margins_exempt = exemption in MARGINS_EXEMPT_TYPES
    # The margin severity carve-out is Utility only now (the exempt types no longer score Margins), and _detect_exemption never
    # surfaces "Utility", so the shared classifier's own return value is read here.
    company_type = classify_company_type(profile.get("sector"), profile.get("industry"), ticker, is_fund=is_fund)
    margins_severity_carveout = company_type in MARGINS_SEVERITY_CARVEOUT_TYPES

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
    gross_margin_fy = _margins(annual["gross_profit"], revenue_fy)
    operating_margin_fy = _margins(annual["operating_income"], revenue_fy)
    net_margin_fy = _margins(annual["net_income"], revenue_fy)

    result = score_step1(
        revenue=_present(revenue_fy),
        net_income=_present(annual["net_income"]),
        operating_income=_present(annual["operating_income"]),
        cfo=_present(cfo_fy),
        gross_margin=_present(gross_margin_fy),
        operating_margin=_present(operating_margin_fy),
        net_margin=_present(net_margin_fy),
        cfo_exempt=cfo_exempt,
        fcf=_present(fcf_fy),
        margins_exempt=margins_exempt,
        margins_severity_carveout=margins_severity_carveout,
        # Real revenue and Operating Income of the last completed fiscal year (None when missing) for the Operating Income backup's
        # quality gates -- the filtered series above can't tell a missing latest year from a present one.
        latest_revenue=revenue_fy[-1] if revenue_fy else None,
        latest_operating_income=annual["operating_income"][-1] if annual["operating_income"] else None,
        weights=weights.step1,
    )

    return Step1Out(
        ticker=ticker,
        years=years,
        revenue=revenue,
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
