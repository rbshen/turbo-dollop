from datetime import date as date_cls

from sqlmodel import Session

import clients.sec_edgar as sec_edgar
from core.cache import get_or_fetch_earnings_aware, safe_fetch
from core.config import settings
from core.db import engine
from helpers.earnings import resolve_most_recent_earnings_date
from helpers.first import _first
from helpers.shares import is_implausible_magnitude_shift
from clients.fmp_client import fmp_client
from core.schemas import FinancialsGroup, FinancialsLineItem, FinancialsOut, FinancialsPeriodOut, FinancialsStatementOut
from core.tickers import normalize_ticker
from helpers.ttm import TOTAL_QUARTERS_NEEDED, sum_last_four_quarters

# Same 10yr+TTM window as Step 1/Step 4 (see CLAUDE.md's Step 4 deviations)
# -- this is a raw-statement viewer, not a scored metric, but reuses the
# same window for consistency across the app.
ANNUAL_WINDOW = 10

# (label, FMP field key, unit, emphasis) -- a static table, not derived
# from any classification. Schema is identical across annual/quarterly and
# across sectors (confirmed for AAPL/JPM/NVDA), so one fixed field list
# covers every company type.
FieldSpec = tuple[str, str, str, bool]

INCOME_STATEMENT_FIELDS: list[FieldSpec] = [
    ("Revenue", "revenue", "money", False),
    ("Cost of Revenue", "costOfRevenue", "money", False),
    ("Gross Profit", "grossProfit", "money", True),
    ("Research & Development", "researchAndDevelopmentExpenses", "money", False),
    ("General & Administrative", "generalAndAdministrativeExpenses", "money", False),
    ("Selling & Marketing", "sellingAndMarketingExpenses", "money", False),
    ("SG&A", "sellingGeneralAndAdministrativeExpenses", "money", False),
    ("Other Operating Expenses", "otherExpenses", "money", False),
    ("Total Operating Expenses", "operatingExpenses", "money", False),
    ("Total Costs & Expenses", "costAndExpenses", "money", False),
    ("Operating Income", "operatingIncome", "money", True),
    ("Depreciation & Amortization", "depreciationAndAmortization", "money", False),
    ("EBIT", "ebit", "money", False),
    ("EBITDA", "ebitda", "money", False),
    ("Non-Operating Income (Excl. Interest)", "nonOperatingIncomeExcludingInterest", "money", False),
    ("Net Interest Income", "netInterestIncome", "money", False),
    ("Interest Income", "interestIncome", "money", False),
    ("Interest Expense", "interestExpense", "money", False),
    ("Total Other Income/Expenses, Net", "totalOtherIncomeExpensesNet", "money", False),
    ("Pretax Income", "incomeBeforeTax", "money", False),
    ("Income Tax Expense", "incomeTaxExpense", "money", False),
    ("Net Income from Continuing Operations", "netIncomeFromContinuingOperations", "money", False),
    ("Net Income from Discontinued Operations", "netIncomeFromDiscontinuedOperations", "money", False),
    ("Net Income", "netIncome", "money", True),
    ("Other Adjustments to Net Income", "otherAdjustmentsToNetIncome", "money", False),
    ("Net Income Deductions", "netIncomeDeductions", "money", False),
    ("Bottom Line Net Income", "bottomLineNetIncome", "money", False),
    ("EPS (Basic)", "eps", "per_share", False),
    ("EPS (Diluted)", "epsDiluted", "per_share", False),
    ("Weighted Avg Shares Outstanding (Basic, millions)", "weightedAverageShsOut", "shares", False),
    ("Weighted Avg Shares Outstanding (Diluted, millions)", "weightedAverageShsOutDil", "shares", False),
]

BALANCE_SHEET_GROUPS: list[tuple[str | None, list[FieldSpec]]] = [
    (
        "Assets",
        [
            ("Cash & Equivalents", "cashAndCashEquivalents", "money", False),
            ("Short-Term Investments", "shortTermInvestments", "money", False),
            ("Cash & Short-Term Investments", "cashAndShortTermInvestments", "money", False),
            ("Net Receivables", "netReceivables", "money", False),
            ("Accounts Receivable", "accountsReceivables", "money", False),
            ("Other Receivables", "otherReceivables", "money", False),
            ("Inventory", "inventory", "money", False),
            ("Prepaid Expenses", "prepaids", "money", False),
            ("Other Current Assets", "otherCurrentAssets", "money", False),
            ("Total Current Assets", "totalCurrentAssets", "money", True),
            ("Property, Plant & Equipment", "propertyPlantEquipmentNet", "money", False),
            ("Goodwill", "goodwill", "money", False),
            ("Intangible Assets", "intangibleAssets", "money", False),
            ("Goodwill & Intangible Assets", "goodwillAndIntangibleAssets", "money", False),
            ("Long-Term Investments", "longTermInvestments", "money", False),
            ("Tax Assets", "taxAssets", "money", False),
            ("Other Non-Current Assets", "otherNonCurrentAssets", "money", False),
            ("Total Non-Current Assets", "totalNonCurrentAssets", "money", True),
            ("Other Assets", "otherAssets", "money", False),
            ("Total Assets", "totalAssets", "money", True),
        ],
    ),
    (
        "Liabilities",
        [
            ("Accounts Payable", "accountPayables", "money", False),
            ("Other Payables", "otherPayables", "money", False),
            ("Total Payables", "totalPayables", "money", False),
            ("Accrued Expenses", "accruedExpenses", "money", False),
            ("Short-Term Debt", "shortTermDebt", "money", False),
            ("Capital Lease Obligations (Current)", "capitalLeaseObligationsCurrent", "money", False),
            ("Tax Payables", "taxPayables", "money", False),
            ("Deferred Revenue", "deferredRevenue", "money", False),
            ("Other Current Liabilities", "otherCurrentLiabilities", "money", False),
            ("Total Current Liabilities", "totalCurrentLiabilities", "money", True),
            ("Long-Term Debt", "longTermDebt", "money", False),
            ("Capital Lease Obligations (Non-Current)", "capitalLeaseObligationsNonCurrent", "money", False),
            ("Deferred Revenue (Non-Current)", "deferredRevenueNonCurrent", "money", False),
            ("Deferred Tax Liabilities (Non-Current)", "deferredTaxLiabilitiesNonCurrent", "money", False),
            ("Other Non-Current Liabilities", "otherNonCurrentLiabilities", "money", False),
            ("Total Non-Current Liabilities", "totalNonCurrentLiabilities", "money", True),
            ("Other Liabilities", "otherLiabilities", "money", False),
            ("Total Capital Lease Obligations", "capitalLeaseObligations", "money", False),
            ("Total Liabilities", "totalLiabilities", "money", True),
        ],
    ),
    (
        "Equity",
        [
            ("Preferred Stock", "preferredStock", "money", False),
            ("Common Stock", "commonStock", "money", False),
            ("Additional Paid-In Capital", "additionalPaidInCapital", "money", False),
            ("Retained Earnings", "retainedEarnings", "money", False),
            ("Treasury Stock", "treasuryStock", "money", False),
            ("Accumulated Other Comprehensive Income/Loss", "accumulatedOtherComprehensiveIncomeLoss", "money", False),
            ("Other Stockholders' Equity", "otherTotalStockholdersEquity", "money", False),
            ("Total Stockholders' Equity", "totalStockholdersEquity", "money", True),
            ("Minority Interest", "minorityInterest", "money", False),
            ("Total Equity", "totalEquity", "money", True),
            ("Total Liabilities & Equity", "totalLiabilitiesAndTotalEquity", "money", True),
        ],
    ),
    (
        "Supplemental",
        [
            ("Total Investments", "totalInvestments", "money", False),
            ("Total Debt", "totalDebt", "money", False),
            ("Net Debt", "netDebt", "money", False),
        ],
    ),
]

CASH_FLOW_GROUPS: list[tuple[str | None, list[FieldSpec]]] = [
    (
        "Operating",
        [
            ("Net Income", "netIncome", "money", False),
            ("Depreciation & Amortization", "depreciationAndAmortization", "money", False),
            ("Deferred Income Tax", "deferredIncomeTax", "money", False),
            ("Stock-Based Compensation", "stockBasedCompensation", "money", False),
            ("Change in Working Capital", "changeInWorkingCapital", "money", False),
            ("Change in Accounts Receivable", "accountsReceivables", "money", False),
            ("Change in Inventory", "inventory", "money", False),
            ("Change in Accounts Payable", "accountsPayables", "money", False),
            ("Other Working Capital", "otherWorkingCapital", "money", False),
            ("Other Non-Cash Items", "otherNonCashItems", "money", False),
            ("Net Cash from Operating Activities", "netCashProvidedByOperatingActivities", "money", True),
        ],
    ),
    (
        "Investing",
        [
            ("Capital Expenditures", "capitalExpenditure", "money", False),
            ("Acquisitions, Net", "acquisitionsNet", "money", False),
            ("Purchases of Investments", "purchasesOfInvestments", "money", False),
            ("Sales/Maturities of Investments", "salesMaturitiesOfInvestments", "money", False),
            ("Other Investing Activities", "otherInvestingActivities", "money", False),
            ("Net Cash from Investing Activities", "netCashProvidedByInvestingActivities", "money", True),
        ],
    ),
    (
        "Financing",
        [
            ("Debt Issuance/(Repayment), Net", "netDebtIssuance", "money", False),
            ("Long-Term Debt Issuance, Net", "longTermNetDebtIssuance", "money", False),
            ("Short-Term Debt Issuance, Net", "shortTermNetDebtIssuance", "money", False),
            ("Common Stock Issuance", "commonStockIssuance", "money", False),
            ("Common Stock Repurchased", "commonStockRepurchased", "money", False),
            ("Net Common Stock Issuance", "netCommonStockIssuance", "money", False),
            ("Preferred Stock Issuance, Net", "netPreferredStockIssuance", "money", False),
            ("Net Stock Issuance", "netStockIssuance", "money", False),
            ("Common Dividends Paid", "commonDividendsPaid", "money", False),
            ("Preferred Dividends Paid", "preferredDividendsPaid", "money", False),
            ("Total Dividends Paid", "netDividendsPaid", "money", False),
            ("Other Financing Activities", "otherFinancingActivities", "money", False),
            ("Net Cash from Financing Activities", "netCashProvidedByFinancingActivities", "money", True),
        ],
    ),
    (
        "Net Change",
        [
            ("Effect of Forex on Cash", "effectOfForexChangesOnCash", "money", False),
            ("Net Change in Cash", "netChangeInCash", "money", True),
            ("Cash at Beginning of Period", "cashAtBeginningOfPeriod", "money", False),
            ("Cash at End of Period", "cashAtEndOfPeriod", "money", False),
            ("Free Cash Flow", "freeCashFlow", "money", False),
            ("Income Taxes Paid", "incomeTaxesPaid", "money", False),
            ("Interest Paid", "interestPaid", "money", False),
        ],
    ),
]


# Phase 3a (2026-08-16): on-demand SEC EDGAR cross-check, scoped to exactly
# these two fields -- confirmed by investigation to be the only ones with a
# real FMP data gap (see FinancialsStatementTable.tsx's
# INCOMPLETE_COVERAGE_LABELS, same two labels). Deliberately not a generic
# "any cell" lookup -- the candidate-XBRL-tag-and-fallback logic doesn't
# generalize to arbitrary fields without the same kind of live-filing
# research that produced these two (see sec_edgar.py).
#
# Field names, not bound function references: get_cash_flow_cell_sec_check
# below looks up sec_edgar.cross_check_* by attribute name at call time, not
# through a dict of pre-bound functions -- the latter would capture
# sec_edgar's cross-check functions at import time, permanently pinned past
# a test's monkeypatch of the live sec_edgar module attribute.
SEC_CELL_CHECK_FIELDS = {
    "incomeTaxesPaid": "cross_check_income_taxes_paid",
    "interestPaid": "cross_check_interest_paid",
}


async def get_cash_flow_cell_sec_check(ticker: str, field: str, period_end: str) -> sec_edgar.CrossCheckResult:
    """On-demand only: single ticker, single field, single annual period,
    triggered by an explicit user click on a zero/blank Income Taxes Paid or
    Interest Paid cell in the Financials tab's *annual* Cash Flow table --
    never called from any batch/bulk context (Screener, Watchlist, nightly
    jobs all reach get_financials_data, never this function; grep confirms
    the only caller is core/main.py's dedicated endpoint). This is the same
    on-demand-only discipline Step 5's own SEC cross-check enforces (see
    step5_data.py / CLAUDE.md's 2026-08-16 nightly-sweep fix) -- SEC's
    rate-limit penalty for exceeding ~10 req/sec is a 10-minute IP lockout.

    Quarterly/TTM cells are out of scope: TTM's cash-flow figure here is a
    derived sum of 4 quarters (_ttm_row_summed), not a single filed value,
    so there's no single SEC fact to cross-check it against; the quarterly
    table's own period labels ("Q2 2026") don't carry a raw end date at all
    today. Only the annual table's periods double as real ISO dates, so
    period_end must match one of cash_flow_annual's own `date` values
    exactly -- no match returns an explicit "unavailable" result rather
    than guessing the nearest period.

    Raises ValueError for an unsupported field or a malformed period_end --
    both are caller/input errors the API layer turns into a 400, not a
    condition worth a CrossCheckResult's own "unavailable" shape."""
    ticker = normalize_ticker(ticker)
    cross_check_fn_name = SEC_CELL_CHECK_FIELDS.get(field)
    if cross_check_fn_name is None:
        raise ValueError(f"Unsupported field {field!r} -- only {sorted(SEC_CELL_CHECK_FIELDS)} are supported.")
    cross_check_fn = getattr(sec_edgar, cross_check_fn_name)
    try:
        target_end = date_cls.fromisoformat(period_end)
    except ValueError as exc:
        raise ValueError("period_end must be an ISO date (YYYY-MM-DD).") from exc

    staleness_days = settings.cache_staleness_days
    with Session(engine) as session:
        most_recent_earnings_date = await resolve_most_recent_earnings_date(session, ticker, staleness_days, False)
        cash_flow_annual = await safe_fetch(
            "cash_flow_statement_annual",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "cash_flow_statement",
                "annual",
                lambda: fmp_client.get_cash_flow_statement(ticker, "annual", ANNUAL_WINDOW),
                staleness_days,
                most_recent_earnings_date,
                False,
            ),
        )
        cash_flow_annual = cash_flow_annual if isinstance(cash_flow_annual, list) else []
        row = next((r for r in cash_flow_annual if r.get("date") == period_end), None)
        if row is None:
            return sec_edgar.CrossCheckResult(
                False, None, None, None, f"No cached annual filing found for {ticker} as of {period_end}."
            )

        fmp_value = row.get(field) or 0.0
        return await cross_check_fn(session, ticker, target_end, fmp_value, staleness_days)


def _trim_and_pad(rows: list[dict], count: int) -> list[dict]:
    """Most-recent-`count` rows (FMP returns most-recent-first), reversed to
    chronological (oldest first) and None-padded at the old end if fewer
    than `count` are available (e.g. a recent IPO) -- same convention as
    step4_data.py's _annual_series."""
    trimmed = list(reversed(rows[:count]))
    pad = count - len(trimmed)
    return [{}] * pad + trimmed


def _annual_labels(rows: list[dict], count: int) -> list[str]:
    trimmed = list(reversed(rows[:count]))
    pad = count - len(trimmed)
    # Full fiscal year-end date -- falls back to the bare fiscalYear for
    # rows/fixtures without a "date" field.
    return ["—"] * pad + [r.get("date") or r.get("fiscalYear", "—") for r in trimmed]


def _quarter_label(row: dict) -> str:
    period, fiscal_year = row.get("period"), row.get("fiscalYear")
    return f"{period} {fiscal_year}" if period and fiscal_year else "—"


def _quarterly_labels(rows: list[dict], count: int) -> list[str]:
    trimmed = list(reversed(rows[:count]))
    pad = count - len(trimmed)
    return ["—"] * pad + [_quarter_label(r) for r in trimmed]


def _build_groups(rows: list[dict], grouped_fields: list[tuple[str | None, list[FieldSpec]]]) -> list[FinancialsGroup]:
    groups = []
    for group_label, fields in grouped_fields:
        items = [
            FinancialsLineItem(label=label, values=[r.get(key) for r in rows], unit=unit, emphasis=emphasis)
            for label, key, unit, emphasis in fields
        ]
        groups.append(FinancialsGroup(label=group_label, items=items))
    return groups


def _sanitize_shares_magnitude(
    quarterly_rows: list[dict], grouped_fields: list[tuple[str | None, list[FieldSpec]]]
) -> list[dict]:
    """Null out any "shares"-unit field on the latest quarter whose value is
    an implausible magnitude shift vs. the prior quarter (see
    is_implausible_magnitude_shift) -- the signature of an FMP freshly-
    filed-quarter units defect (confirmed: TEAM, FLY), not a real corporate
    action. Never auto-corrects/rescales, only suppresses the untrustworthy
    cell, since guessing the right scale risks misfiring on a genuine (if
    rare) reverse split. Applied once, upstream of both the quarterly table
    and the TTM column (_ttm_row_summed's "shares" branch reads
    quarterly_rows[0] directly), so neither view can show the raw defect."""
    if len(quarterly_rows) < 2:
        return quarterly_rows
    share_keys = {key for _, fields in grouped_fields for _, key, unit, _ in fields if unit == "shares"}
    if not share_keys:
        return quarterly_rows
    latest, prior = quarterly_rows[0], quarterly_rows[1]
    sanitized_latest = dict(latest)
    for key in share_keys:
        if is_implausible_magnitude_shift(latest.get(key), prior.get(key)):
            sanitized_latest[key] = None
    return [sanitized_latest, *quarterly_rows[1:]]


def _ttm_row_summed(
    quarterly_rows: list[dict],
    grouped_fields: list[tuple[str | None, list[FieldSpec]]],
    annual_rows: list[dict] | None = None,
) -> dict:
    """Flow-measure fields (income statement, cash flow): TTM = trailing 4
    quarters summed, same convention as Step 1's revenue/net income/CFO TTM
    column. `quarterly_rows` must be most-recent-first (FMP's own
    ordering), matching sum_last_four_quarters' own requirement.

    `annual_rows`, when passed, lets sum_last_four_quarters correct TEAM
    Defect B (a just-closed fiscal year's Q4 quarterly row served as a
    duplicate of the annual total) before summing -- this only ever
    affects the TTM column here, never the raw per-quarter columns
    _quarterly_period builds separately, since those are meant to show
    exactly what FMP reported (same "raw, un-converted" convention this
    tab's currency handling already follows), not a derived correction.

    Share-count fields ("shares" unit -- Weighted Avg Shares Outstanding)
    are the one exception within an otherwise-summed statement: a share
    count is a snapshot-like measure, not a flow, so summing 4 quarters
    would produce a meaningless ~4x-inflated figure. These fall back to
    the latest quarter's value instead, same treatment the whole Balance
    Sheet statement gets via _ttm_row_latest."""
    result: dict = {}
    for _, fields in grouped_fields:
        for _, key, unit, _ in fields:
            if unit == "shares":
                result[key] = quarterly_rows[0].get(key) if quarterly_rows else None
            else:
                result[key] = sum_last_four_quarters(quarterly_rows, key, annual_rows).total
    return result


def _ttm_row_latest(quarterly_rows: list[dict]) -> dict:
    """Balance sheet items are point-in-time snapshots, not summable -- the
    latest quarter stands in for the "TTM" column, same convention Step 4/
    Step 5 already use for their own balance-sheet TTM figures."""
    return quarterly_rows[0] if quarterly_rows else {}


def _annual_period(
    annual_rows: list[dict],
    quarterly_rows: list[dict],
    grouped_fields: list[tuple[str | None, list[FieldSpec]]],
    ttm_mode: str,
) -> FinancialsPeriodOut:
    rows = _trim_and_pad(annual_rows, ANNUAL_WINDOW)
    labels = _annual_labels(annual_rows, ANNUAL_WINDOW)
    ttm_row = (
        _ttm_row_summed(quarterly_rows, grouped_fields, annual_rows)
        if ttm_mode == "sum"
        else _ttm_row_latest(quarterly_rows)
    )
    rows = rows + [ttm_row]
    # TTM is the one annual column that keeps a full date -- "TTM" alone
    # doesn't say which date it's as-of, unlike a bare fiscal year.
    ttm_date = quarterly_rows[0].get("date") if quarterly_rows else None
    labels = labels + [f"TTM ({ttm_date})" if ttm_date else "TTM"]
    return FinancialsPeriodOut(periods=labels, groups=_build_groups(rows, grouped_fields))


def _quarterly_period(
    quarterly_rows: list[dict], grouped_fields: list[tuple[str | None, list[FieldSpec]]]
) -> FinancialsPeriodOut:
    rows = _trim_and_pad(quarterly_rows, TOTAL_QUARTERS_NEEDED)
    labels = _quarterly_labels(quarterly_rows, TOTAL_QUARTERS_NEEDED)
    return FinancialsPeriodOut(periods=labels, groups=_build_groups(rows, grouped_fields))


async def get_financials_data(ticker: str, cache_only: bool = False) -> FinancialsOut:
    """`cache_only=True` reads only whatever's already cached and never
    calls FMP -- same convention as get_step1_data/get_step4_data."""
    ticker = normalize_ticker(ticker)
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        most_recent_earnings_date = await resolve_most_recent_earnings_date(session, ticker, staleness_days, cache_only)
        income_annual = await safe_fetch(
            "income_statement_annual",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "income_statement",
                "annual",
                lambda: fmp_client.get_income_statement(ticker, "annual", ANNUAL_WINDOW),
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
                lambda: fmp_client.get_cash_flow_statement(ticker, "annual", ANNUAL_WINDOW),
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
        balance_sheet_annual = await safe_fetch(
            "balance_sheet_statement_annual",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "balance_sheet_statement",
                "annual",
                lambda: fmp_client.get_balance_sheet_statement(ticker, "annual", ANNUAL_WINDOW),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        # Same cache key as Step 4/Step 5's own balance_sheet_statement/
        # quarterly fetch -- limit bumped to TOTAL_QUARTERS_NEEDED there too
        # (see step4_data.py/step5_data.py) so this tab has real quarterly
        # history instead of just the latest snapshot; Step 4/5 are
        # unaffected since they only ever read row 0.
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

    income_annual = income_annual if isinstance(income_annual, list) else []
    income_quarterly = income_quarterly if isinstance(income_quarterly, list) else []
    cash_flow_annual = cash_flow_annual if isinstance(cash_flow_annual, list) else []
    cash_flow_quarterly = cash_flow_quarterly if isinstance(cash_flow_quarterly, list) else []
    balance_sheet_annual = balance_sheet_annual if isinstance(balance_sheet_annual, list) else []
    balance_sheet_quarterly = balance_sheet_quarterly if isinstance(balance_sheet_quarterly, list) else []

    income_fields = [(None, INCOME_STATEMENT_FIELDS)]
    income_quarterly = _sanitize_shares_magnitude(income_quarterly, income_fields)
    # Cosmetic-only label (CLAUDE.md's non-USD currency investigation,
    # decided scope #1) -- every figure above stays the company's raw
    # reported number, un-converted; this just tells the frontend which
    # currency that raw number actually is. income_annual's own row is as
    # good a source as balance_sheet/cash_flow's -- reportedCurrency is the
    # same value across all three for a given ticker/period (confirmed
    # during the investigation).
    reported_currency = _first(income_annual).get("reportedCurrency")

    return FinancialsOut(
        ticker=ticker,
        reported_currency=reported_currency,
        income_statement=FinancialsStatementOut(
            annual=_annual_period(income_annual, income_quarterly, income_fields, ttm_mode="sum"),
            quarterly=_quarterly_period(income_quarterly, income_fields),
        ),
        balance_sheet=FinancialsStatementOut(
            annual=_annual_period(balance_sheet_annual, balance_sheet_quarterly, BALANCE_SHEET_GROUPS, ttm_mode="latest"),
            quarterly=_quarterly_period(balance_sheet_quarterly, BALANCE_SHEET_GROUPS),
        ),
        cash_flow=FinancialsStatementOut(
            annual=_annual_period(cash_flow_annual, cash_flow_quarterly, CASH_FLOW_GROUPS, ttm_mode="sum"),
            quarterly=_quarterly_period(cash_flow_quarterly, CASH_FLOW_GROUPS),
        ),
    )
