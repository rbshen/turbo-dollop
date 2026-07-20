from sqlmodel import Session

from cache import get_or_fetch, safe_fetch
from config import settings
from db import engine
from fmp_client import fmp_client
from schemas import Step4Out
from scoring.classification import classify_company_type
from scoring.step4 import classify_ccc_trend, score_revenue_vs_ar, score_roe, score_roic, score_step4
from ttm import TOTAL_QUARTERS_NEEDED, sum_last_four_quarters

ROIC_EXEMPT_TYPES = {"Bank", "Insurance", "Utility", "REIT/Property Developer"}
# Both display AND scoring now use the same 10yr+TTM window, matching Step
# 1 -- a deliberate deviation beyond step4_profitability_efficiency_
# assessment_prompt.md's explicit "5 years" language (see CLAUDE.md's Step
# 4 deviations). There used to be a separate, narrower SCORING_ANNUAL_WINDOW
# (5) feeding only the score while display used the full 10 -- that
# decoupling has been removed; a single window now drives both.
ANNUAL_WINDOW = 10


def _first(data: dict | list) -> dict:
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def _annual_series(annual_rows: list[dict], field: str, count: int = ANNUAL_WINDOW) -> list[float | None]:
    # FMP returns annual rows most-recent-first; take the most recent
    # `count` and reverse to chronological (oldest fiscal year first).
    # Always padded to exactly `count` slots (None-padded at the oldest end)
    # so every metric series lines up index-for-index even if one FMP
    # endpoint returns fewer annual periods than another for the same
    # ticker.
    rows = list(reversed(annual_rows[:count]))
    pad = count - len(rows)
    return [None] * pad + [row.get(field) for row in rows]


def _annual_years(*row_sources: list[dict], count: int = ANNUAL_WINDOW) -> list[str]:
    for rows in row_sources:
        if rows:
            trimmed = list(reversed(rows[:count]))
            pad = count - len(trimmed)
            return ["—"] * pad + [row.get("fiscalYear", row.get("date", "")[:4]) for row in trimmed]
    return ["—"] * count


def _clean_aligned(*series: list) -> list[list]:
    """Keep only the index positions where every given series has a
    non-None value, preserving cross-series alignment (e.g. an ROE reading
    and the equity figure it depends on must come from the same period)."""
    n = len(series[0])
    keep = [i for i in range(n) if all(s[i] is not None for s in series)]
    return [[s[i] for i in keep] for s in series]


def _compute_ccc_series(
    revenue: list[float | None],
    cost_of_revenue: list[float | None],
    inventory: list[float | None],
    accounts_receivable: list[float | None],
    accounts_payable: list[float | None],
) -> list[float]:
    ccc = []
    for rev, cogs, inv, ar, ap in zip(revenue, cost_of_revenue, inventory, accounts_receivable, accounts_payable):
        if not rev or not cogs or inv is None or ar is None or ap is None:
            continue
        dio = inv / cogs * 365
        dso = ar / rev * 365
        dpo = ap / cogs * 365
        ccc.append(dio + dso - dpo)
    return ccc


async def get_step4_data(ticker: str) -> Step4Out:
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

        # Same cache key + limit Step 1 already populates ("income_statement"
        # / "annual", limit 10) -- requesting a different limit here would
        # fight over the same cache row (see CLAUDE.md's caching policy).
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
                lambda: fmp_client.get_income_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
            ),
        )
        balance_sheet_annual = await safe_fetch(
            "balance_sheet_statement_annual",
            get_or_fetch(
                session,
                ticker,
                "balance_sheet_statement",
                "annual",
                lambda: fmp_client.get_balance_sheet_statement(ticker, "annual", ANNUAL_WINDOW),
                staleness_days,
            ),
        )
        # Same cache key + limit Step 5 already populates ("balance_sheet_
        # statement"/"quarterly", limit 1) -- balance sheet items are
        # snapshots, so the latest quarter stands in for the "TTM" column.
        balance_sheet_quarterly = await safe_fetch(
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
        key_metrics_annual = await safe_fetch(
            "key_metrics_annual",
            get_or_fetch(
                session,
                ticker,
                "key_metrics",
                "annual",
                lambda: fmp_client.get_key_metrics(ticker, "annual", ANNUAL_WINDOW),
                staleness_days,
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
                ),
            )
        )

    income_annual = income_annual if isinstance(income_annual, list) else []
    income_quarterly = income_quarterly if isinstance(income_quarterly, list) else []
    balance_sheet_annual = balance_sheet_annual if isinstance(balance_sheet_annual, list) else []
    key_metrics_annual = key_metrics_annual if isinstance(key_metrics_annual, list) else []
    balance_sheet_latest = _first(balance_sheet_quarterly)

    years = _annual_years(income_annual, balance_sheet_annual, key_metrics_annual)
    revenue = _annual_series(income_annual, "revenue")
    net_income = _annual_series(income_annual, "netIncome")
    cost_of_revenue = _annual_series(income_annual, "costOfRevenue")
    equity = _annual_series(balance_sheet_annual, "totalStockholdersEquity")
    accounts_receivable = _annual_series(balance_sheet_annual, "accountsReceivables")
    inventory = _annual_series(balance_sheet_annual, "inventory")
    accounts_payable = _annual_series(balance_sheet_annual, "accountPayables")
    roe = _annual_series(key_metrics_annual, "returnOnEquity")
    roic = _annual_series(key_metrics_annual, "returnOnInvestedCapital")
    # FMP's returnOnEquity/returnOnInvestedCapital are fractions (e.g. 0.31
    # for 31%) -- convert to percent to match the doc's 8/12/15% thresholds.
    roe = [v * 100 if v is not None else None for v in roe]
    roic = [v * 100 if v is not None else None for v in roic]

    years = years + ["TTM"]
    revenue = revenue + [sum_last_four_quarters(income_quarterly, "revenue").total]
    net_income = net_income + [sum_last_four_quarters(income_quarterly, "netIncome").total]
    cost_of_revenue = cost_of_revenue + [sum_last_four_quarters(income_quarterly, "costOfRevenue").total]
    equity = equity + [balance_sheet_latest.get("totalStockholdersEquity")]
    accounts_receivable = accounts_receivable + [balance_sheet_latest.get("accountsReceivables")]
    inventory = inventory + [balance_sheet_latest.get("inventory")]
    accounts_payable = accounts_payable + [balance_sheet_latest.get("accountPayables")]
    roe_ttm = key_metrics_ttm.get("returnOnEquityTTM")
    roic_ttm = key_metrics_ttm.get("returnOnInvestedCapitalTTM")
    roe = roe + [roe_ttm * 100 if roe_ttm is not None else None]
    roic = roic + [roic_ttm * 100 if roic_ttm is not None else None]

    roic_exempt = company_type in ROIC_EXEMPT_TYPES
    roic_exempt_reason = (
        f"ROIC not applicable for {company_type} — structurally high leverage is core to the business "
        "model, not mismanagement (assessed on ROE only)."
        if roic_exempt
        else None
    )

    # Data-driven detection: no physical inventory across all 10 annual
    # filings reads as inventory being 0 or null in every year (confirmed
    # reliable for CRM, ADBE; MSFT is a notable false-negative risk since it
    # carries real hardware inventory despite being thought of as "pure
    # software"). Checked against the full annual history now that scoring
    # itself uses the full 10yr window -- deliberately still checked on the
    # annual history only, not the latest-quarter snapshot appended below:
    # FMP's quarterly inventory figure has proven unreliable for
    # inventory-free companies (e.g. MA shows +$2.06B, NOW shows -$28M in
    # their latest quarter despite straight clean-zero annual years) -- a
    # likely data-provider classification artifact, not a real change in the
    # business.
    ccc_exempt = all(v is None or v == 0 for v in inventory[:-1])
    ccc_exempt_reason = "No physical inventory detected across the reporting window — CCC not applicable." if ccc_exempt else None

    roe_clean, equity_clean, net_income_clean = _clean_aligned(roe, equity, net_income)
    revenue_clean, ar_clean = _clean_aligned(revenue, accounts_receivable)

    if len(roe_clean) < 2 or len(revenue_clean) < 2:
        return Step4Out(
            ticker=ticker,
            years=years,
            company_type=company_type,
            roe=roe,
            roic=None if roic_exempt else roic,
            roic_exempt_reason=roic_exempt_reason,
            revenue=revenue,
            accounts_receivable=accounts_receivable,
            ccc=None,
            ccc_exempt_reason=ccc_exempt_reason,
            score=None,
            verdict="insufficient_data",
        )

    roe_result = score_roe(roe_clean, equity_clean, net_income_clean)
    ar_result = score_revenue_vs_ar(revenue_clean, ar_clean)

    roic_result = None
    if not roic_exempt:
        roic_clean = [v for v in roic if v is not None]
        roic_result = score_roic(roic_clean) if len(roic_clean) >= 2 else None

    # ccc_series now feeds both display (Step4Out.ccc) and scoring directly
    # -- no separate scoring-window recomputation needed now that the two
    # windows are the same.
    ccc_series: list[float] | None = None
    ccc_result = None
    if not ccc_exempt:
        ccc_series = _compute_ccc_series(revenue, cost_of_revenue, inventory, accounts_receivable, accounts_payable)
        if len(ccc_series) >= 2:
            ccc_result = classify_ccc_trend(ccc_series)

    result = score_step4(roe_result, ar_result, roic_result, ccc_result)

    return Step4Out(
        ticker=ticker,
        years=years,
        company_type=company_type,
        roe=roe,
        roic=None if roic_exempt else roic,
        roic_exempt_reason=roic_exempt_reason,
        revenue=revenue,
        accounts_receivable=accounts_receivable,
        ccc=None if ccc_exempt else ccc_series,
        ccc_exempt_reason=ccc_exempt_reason,
        score=result["score"],
        verdict=result["verdict"],
        hard_fail=result["hard_fail"],
        components=result["components"],
    )
