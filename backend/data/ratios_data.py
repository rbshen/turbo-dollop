from sqlmodel import Session

from core.cache import get_or_fetch, safe_fetch
from core.config import settings
from core.db import engine
from helpers.first import _first
from clients.fmp_client import fmp_client
from core.schemas import FinancialsGroup, FinancialsLineItem, RatiosOut
from core.tickers import normalize_ticker
from helpers.ttm import TOTAL_QUARTERS_NEEDED

# Same 10yr+TTM window as Step 1/Step 4/Financials -- a raw-metrics viewer,
# not a scored metric, but reuses the same window for consistency.
ANNUAL_WINDOW = 10

# (label, source, FMP field key, unit) -- source is "key_metrics" (from
# /key-metrics + /key-metrics-ttm) or "ratios" (from /ratios + /ratios-ttm).
# Canonical source picked per concept where a field appears in both under
# different names (or the same name with an identical value) -- see
# CLAUDE.md-adjacent investigation notes in the Ratios tab kickoff: e.g.
# key_metrics.evToEBITDA is kept over ratios.enterpriseValueMultiple (exact
# numeric duplicate), and ratios.priceToFairValue is dropped entirely (exact
# duplicate of priceToBookRatio in this FMP tier, not a real distinct
# fair-value figure). "percent"-unit fields are fractions in both source
# payloads (e.g. 0.469 for 46.9%) and get *100 applied uniformly below.
FieldSpec = tuple[str, str, str, str]

VALUATION_FIELDS: list[FieldSpec] = [
    ("P/E", "ratios", "priceToEarningsRatio", "ratio"),
    ("P/S", "ratios", "priceToSalesRatio", "ratio"),
    ("P/B", "ratios", "priceToBookRatio", "ratio"),
    ("P/FCF", "ratios", "priceToFreeCashFlowRatio", "ratio"),
    ("P/OCF", "ratios", "priceToOperatingCashFlowRatio", "ratio"),
    ("PEG", "ratios", "priceToEarningsGrowthRatio", "ratio"),
    ("Forward PEG", "ratios", "forwardPriceToEarningsGrowthRatio", "ratio"),
    ("EV/Sales", "key_metrics", "evToSales", "ratio"),
    ("EV/EBITDA", "key_metrics", "evToEBITDA", "ratio"),
    ("EV/OCF", "key_metrics", "evToOperatingCashFlow", "ratio"),
    ("EV/FCF", "key_metrics", "evToFreeCashFlow", "ratio"),
    ("Earnings Yield", "key_metrics", "earningsYield", "percent"),
    ("FCF Yield", "key_metrics", "freeCashFlowYield", "percent"),
    ("Dividend Yield", "ratios", "dividendYield", "percent"),
    ("Graham Number", "key_metrics", "grahamNumber", "per_share"),
    ("Graham Net-Net", "key_metrics", "grahamNetNet", "per_share"),
]

MARGIN_FIELDS: list[FieldSpec] = [
    ("Gross Margin", "ratios", "grossProfitMargin", "percent"),
    ("EBIT Margin", "ratios", "ebitMargin", "percent"),
    ("EBITDA Margin", "ratios", "ebitdaMargin", "percent"),
    ("Operating Margin", "ratios", "operatingProfitMargin", "percent"),
    ("Pretax Margin", "ratios", "pretaxProfitMargin", "percent"),
    ("Net Margin", "ratios", "netProfitMargin", "percent"),
    ("Effective Tax Rate", "ratios", "effectiveTaxRate", "percent"),
]

RETURNS_FIELDS: list[FieldSpec] = [
    ("ROE", "key_metrics", "returnOnEquity", "percent"),
    ("ROIC", "key_metrics", "returnOnInvestedCapital", "percent"),
    ("Return on Tangible Assets", "key_metrics", "returnOnTangibleAssets", "percent"),
    ("Asset Turnover", "ratios", "assetTurnover", "ratio"),
    ("Fixed Asset Turnover", "ratios", "fixedAssetTurnover", "ratio"),
    ("Receivables Turnover", "ratios", "receivablesTurnover", "ratio"),
    ("Payables Turnover", "ratios", "payablesTurnover", "ratio"),
    ("Inventory Turnover", "ratios", "inventoryTurnover", "ratio"),
    ("Days Sales Outstanding", "key_metrics", "daysOfSalesOutstanding", "days"),
    ("Days Payables Outstanding", "key_metrics", "daysOfPayablesOutstanding", "days"),
    ("Days Inventory Outstanding", "key_metrics", "daysOfInventoryOutstanding", "days"),
    ("Working Capital Turnover", "ratios", "workingCapitalTurnoverRatio", "ratio"),
]

LIQUIDITY_FIELDS: list[FieldSpec] = [
    ("Current Ratio", "ratios", "currentRatio", "ratio"),
    ("Quick Ratio", "ratios", "quickRatio", "ratio"),
    ("Cash Ratio", "ratios", "cashRatio", "ratio"),
    ("Solvency Ratio", "ratios", "solvencyRatio", "ratio"),
    ("Working Capital", "key_metrics", "workingCapital", "money"),
]

LEVERAGE_FIELDS: list[FieldSpec] = [
    ("Debt/Equity", "ratios", "debtToEquityRatio", "ratio"),
    ("Debt/Assets", "ratios", "debtToAssetsRatio", "ratio"),
    ("Debt/Capital", "ratios", "debtToCapitalRatio", "ratio"),
    ("LT Debt/Capital", "ratios", "longTermDebtToCapitalRatio", "ratio"),
    ("Financial Leverage", "ratios", "financialLeverageRatio", "ratio"),
    ("Net Debt/EBITDA", "key_metrics", "netDebtToEBITDA", "ratio"),
    ("Debt/Market Cap", "ratios", "debtToMarketCap", "ratio"),
]

COVERAGE_FIELDS: list[FieldSpec] = [
    ("Interest Coverage", "ratios", "interestCoverageRatio", "ratio"),
    ("Debt Service Coverage", "ratios", "debtServiceCoverageRatio", "ratio"),
    ("Short-Term OCF Coverage", "ratios", "shortTermOperatingCashFlowCoverageRatio", "ratio"),
    ("Capex Coverage", "ratios", "capitalExpenditureCoverageRatio", "ratio"),
    ("Dividend + Capex Coverage", "ratios", "dividendPaidAndCapexCoverageRatio", "ratio"),
]

CASH_FLOW_FIELDS: list[FieldSpec] = [
    ("OCF Ratio", "ratios", "operatingCashFlowRatio", "ratio"),
    ("OCF/Sales", "ratios", "operatingCashFlowSalesRatio", "percent"),
    ("FCF/OCF Ratio", "ratios", "freeCashFlowOperatingCashFlowRatio", "percent"),
]

PER_SHARE_FIELDS: list[FieldSpec] = [
    ("Revenue/Share", "ratios", "revenuePerShare", "per_share"),
    ("Net Income/Share", "ratios", "netIncomePerShare", "per_share"),
    ("OCF/Share", "ratios", "operatingCashFlowPerShare", "per_share"),
    ("FCF/Share", "ratios", "freeCashFlowPerShare", "per_share"),
    ("Capex/Share", "ratios", "capexPerShare", "per_share"),
    ("Cash/Share", "ratios", "cashPerShare", "per_share"),
    ("Book Value/Share", "ratios", "bookValuePerShare", "per_share"),
    ("Tangible Book Value/Share", "ratios", "tangibleBookValuePerShare", "per_share"),
    ("Interest Debt/Share", "ratios", "interestDebtPerShare", "per_share"),
    ("Dividend/Share", "ratios", "dividendPerShare", "per_share"),
]

PAYOUT_FIELDS: list[FieldSpec] = [
    ("Dividend Payout Ratio", "ratios", "dividendPayoutRatio", "percent"),
]

CATEGORIES: list[tuple[str, list[FieldSpec]]] = [
    ("Valuation Multiples", VALUATION_FIELDS),
    ("Profitability Margins", MARGIN_FIELDS),
    ("Returns & Efficiency", RETURNS_FIELDS),
    ("Liquidity", LIQUIDITY_FIELDS),
    ("Leverage & Solvency", LEVERAGE_FIELDS),
    ("Coverage", COVERAGE_FIELDS),
    ("Cash Flow Ratios", CASH_FLOW_FIELDS),
    ("Per-Share", PER_SHARE_FIELDS),
    ("Payout", PAYOUT_FIELDS),
]


def _annual_years(*row_sources: list[dict], count: int = ANNUAL_WINDOW) -> list[str]:
    # Same convention as step4_data.py::_annual_years -- picks fiscal-year
    # labels from the first non-empty source rather than a per-field
    # fiscal-year join; every annual field below is independently padded to
    # the same `count` slots (see _annual_series), matching the positional-
    # alignment convention every other multi-source data module in this repo
    # already relies on (step4_data.py merges income/balance-sheet/key-
    # metrics annual rows the same way).
    for rows in row_sources:
        if rows:
            trimmed = list(reversed(rows[:count]))
            pad = count - len(trimmed)
            return ["—"] * pad + [row.get("fiscalYear", row.get("date", "")[:4]) for row in trimmed]
    return ["—"] * count


def _annual_series(annual_rows: list[dict], field: str, unit: str, count: int = ANNUAL_WINDOW) -> list[float | None]:
    rows = list(reversed(annual_rows[:count]))
    pad = count - len(rows)
    values = [None] * pad + [row.get(field) for row in rows]
    if unit == "percent":
        values = [v * 100 if v is not None else None for v in values]
    return values


def _strip_ttm_suffix(row: dict) -> dict:
    """/key-metrics-ttm and /ratios-ttm suffix every field with "TTM" (e.g.
    priceToEarningsRatio -> priceToEarningsRatioTTM) -- stripping it once
    lets the same FieldSpec.fmp_field_key drive both the annual and TTM
    lookups instead of a parallel TTM-specific field table."""
    return {k[:-3]: v for k, v in row.items() if k.endswith("TTM")}


def _ttm_value(stripped_row: dict, field: str, unit: str) -> float | None:
    value = stripped_row.get(field)
    if value is not None and unit == "percent":
        value = value * 100
    return value


def _build_groups(
    key_metrics_annual: list[dict],
    ratios_annual: list[dict],
    key_metrics_ttm: dict,
    ratios_ttm: dict,
) -> list[FinancialsGroup]:
    groups = []
    for category_label, fields in CATEGORIES:
        items = []
        for label, source, key, unit in fields:
            annual_rows = key_metrics_annual if source == "key_metrics" else ratios_annual
            ttm_row = key_metrics_ttm if source == "key_metrics" else ratios_ttm
            values = _annual_series(annual_rows, key, unit) + [_ttm_value(ttm_row, key, unit)]
            items.append(FinancialsLineItem(label=label, values=values, unit=unit))
        groups.append(FinancialsGroup(label=category_label, items=items))
    return groups


async def get_ratios_data(ticker: str, cache_only: bool = False) -> RatiosOut:
    """`cache_only=True` reads only whatever's already cached and never
    calls FMP -- same convention as get_step1_data/get_step4_data."""
    ticker = normalize_ticker(ticker)
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        key_metrics_annual = await safe_fetch(
            "key_metrics_annual",
            get_or_fetch(
                session,
                ticker,
                "key_metrics",
                "annual",
                lambda: fmp_client.get_key_metrics(ticker, "annual", ANNUAL_WINDOW),
                staleness_days,
                cache_only,
            ),
        )
        key_metrics_ttm = _first(
            await safe_fetch(
                "key_metrics_ttm",
                get_or_fetch(
                    session,
                    ticker,
                    "key_metrics",
                    "ttm",
                    lambda: fmp_client.get_key_metrics_ttm(ticker),
                    staleness_days,
                    cache_only,
                ),
            )
        )
        ratios_annual = await safe_fetch(
            "ratios_annual_10y",
            get_or_fetch(
                session,
                ticker,
                "ratios",
                "annual_10y",
                lambda: fmp_client.get_ratios(ticker, "annual", ANNUAL_WINDOW),
                staleness_days,
                cache_only,
            ),
        )
        ratios_ttm = _first(
            await safe_fetch(
                "ratios_ttm",
                get_or_fetch(
                    session, ticker, "ratios", "ttm", lambda: fmp_client.get_ratios_ttm(ticker), staleness_days, cache_only
                ),
            )
        )
        # Only fetched for its latest-quarter date, to build a dated TTM
        # column label ("TTM (YYYY-MM-DD)") matching Financials' own
        # convention (financials_data.py::_annual_period) -- Ratios can't
        # derive this from its own TTM payloads, which carry no date field,
        # and can't fetch quarterly key-metrics/ratios directly (402 on our
        # FMP plan). Same cache key Step 4/5/Financials already populate.
        balance_sheet_quarterly = await safe_fetch(
            "balance_sheet_statement_quarterly",
            get_or_fetch(
                session,
                ticker,
                "balance_sheet_statement",
                "quarterly",
                lambda: fmp_client.get_balance_sheet_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
                cache_only,
            ),
        )

    key_metrics_annual = key_metrics_annual if isinstance(key_metrics_annual, list) else []
    ratios_annual = ratios_annual if isinstance(ratios_annual, list) else []
    key_metrics_ttm = _strip_ttm_suffix(key_metrics_ttm)
    ratios_ttm = _strip_ttm_suffix(ratios_ttm)
    balance_sheet_quarterly = balance_sheet_quarterly if isinstance(balance_sheet_quarterly, list) else []

    years = _annual_years(key_metrics_annual, ratios_annual)
    ttm_date = balance_sheet_quarterly[0].get("date") if balance_sheet_quarterly else None
    periods = years + [f"TTM ({ttm_date})" if ttm_date else "TTM"]

    groups = _build_groups(key_metrics_annual, ratios_annual, key_metrics_ttm, ratios_ttm)
    # Cosmetic-only label (CLAUDE.md's non-USD currency investigation,
    # decided scope #1) -- per-share/money rows above stay raw/un-converted;
    # this just tells the frontend which currency those rows actually are.
    # ratios_annual over key_metrics_annual since money/per_share fields in
    # this schema all come from the "ratios" source (see PER_SHARE_FIELDS).
    reported_currency = _first(ratios_annual).get("reportedCurrency")

    return RatiosOut(ticker=ticker, periods=periods, groups=groups, reported_currency=reported_currency)
