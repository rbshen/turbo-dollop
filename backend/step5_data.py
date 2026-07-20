from sqlmodel import Session

from cache import get_or_fetch, safe_fetch
from config import settings
from db import engine
from debt_metrics import MetricOutlierFlags, compute_debt_metrics
from fmp_client import fmp_client
from npl import compute_npl_ratio
from schemas import OutlierWarning, Step5Out, Step5RatioResult
from scoring.step5 import classify_company_type, score_npl, score_step5_reit, score_step5_standard
from ttm import TOTAL_QUARTERS_NEEDED, sum_last_four_quarters


def _first(data: dict | list) -> dict:
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def _ratio_out(raw: dict) -> Step5RatioResult:
    return Step5RatioResult(value=raw["value"], label=raw["label"], points=raw["points"])


def _outlier_warnings(*flag_groups: MetricOutlierFlags) -> list[OutlierWarning]:
    return [
        OutlierWarning(metric=group.metric, date=fq.date, value=fq.value, trailing_median=fq.trailing_median)
        for group in flag_groups
        for fq in group.flagged
    ]


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
        balance_sheet_row = _first(balance_sheet)

        if company_type == "Bank":
            # CET1 is still unavailable (confirmed: FMP has no field and no
            # raw components to compute one) -- deferred, not approximated,
            # so the overall verdict stays "not_supported" regardless of NPL.
            # NPL is a partial signal, computed from FMP's raw XBRL-tag dump
            # (not the standardized schema) -- see npl.py for why this is
            # NOT trusted blindly across every bank ticker.
            full_as_reported = await safe_fetch(
                "financial_statement_full_as_reported_quarterly",
                get_or_fetch(
                    session,
                    ticker,
                    "financial_statement_full_as_reported",
                    "quarterly",
                    lambda: fmp_client.get_financial_statement_full_as_reported(ticker, "quarter", 1),
                    staleness_days,
                ),
            )
            full_as_reported_row = _first(full_as_reported)
            raw_tags = full_as_reported_row.get("data") or {} if isinstance(full_as_reported_row, dict) else {}

            npl_result = compute_npl_ratio(raw_tags, balance_sheet_row.get("totalAssets"))
            ratios = {}
            if npl_result.ratio_pct is not None:
                npl_score = score_npl(npl_result.ratio_pct)
                ratios["npl_ratio"] = _ratio_out(
                    {"value": npl_result.ratio_pct, "label": npl_score.label, "points": npl_score.points}
                )

            return Step5Out(ticker=ticker, company_type=company_type, ratios=ratios, score=None, verdict="not_supported")

        # EBITDA, net interest expense, and CFO are flow measures (activity
        # over a period), not snapshots -- a single quarter's figure would
        # understate them ~4x relative to the debt figures they're compared
        # against, so these are summed trailing-twelve-months instead, same
        # convention and cache key + limit Step 1 already populates
        # ("income_statement"/"quarterly" and "cash_flow_statement"/
        # "quarterly", both limit TOTAL_QUARTERS_NEEDED -- the extra
        # quarters beyond the 4 being summed feed the outlier-detection
        # baseline in ttm.py::sum_last_four_quarters).
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
        cash_flow_quarterly = await safe_fetch(
            "cash_flow_statement_quarterly",
            get_or_fetch(
                session,
                ticker,
                "cash_flow_statement",
                "quarterly",
                lambda: fmp_client.get_cash_flow_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
            ),
        )

    income_quarterly = income_quarterly if isinstance(income_quarterly, list) else []
    cash_flow_quarterly = cash_flow_quarterly if isinstance(cash_flow_quarterly, list) else []

    # Shared with the ticker header's raw metric tiles -- single source of
    # truth so the two views can never diverge for the same ticker.
    debt_metrics = compute_debt_metrics(balance_sheet_row, income_quarterly)
    ebitda_ttm = debt_metrics.ebitda_ttm
    cfo_result = sum_last_four_quarters(cash_flow_quarterly, "netCashProvidedByOperatingActivities")
    cfo_ttm = cfo_result.total

    outlier_warnings = _outlier_warnings(
        *debt_metrics.outlier_flags, MetricOutlierFlags(metric="cfo_ttm", flagged=cfo_result.flagged)
    )

    # REIT gearing uses FMP's own totalDebt field (a broader aggregate than
    # short+long term debt alone), a different definition than the Standard
    # path's debt_to_ebitda below -- unchanged from before this refactor.
    total_debt = balance_sheet_row.get("totalDebt")
    total_assets = balance_sheet_row.get("totalAssets")
    deferred_revenue = balance_sheet_row.get("deferredRevenue")

    if company_type == "REIT/Property Developer":
        if total_debt is None or not total_assets:
            return Step5Out(
                ticker=ticker,
                company_type=company_type,
                score=None,
                verdict="insufficient_data",
                outlier_warnings=outlier_warnings,
            )

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
            outlier_warnings=outlier_warnings,
        )

    # Standard path.
    current_assets = balance_sheet_row.get("totalCurrentAssets")
    current_liabilities = balance_sheet_row.get("totalCurrentLiabilities")

    current_ratio = current_assets / current_liabilities if current_assets is not None and current_liabilities else None
    debt_to_ebitda = (
        debt_metrics.total_debt / ebitda_ttm
        if debt_metrics.total_debt is not None and ebitda_ttm is not None and ebitda_ttm > 0
        else None
    )
    # CFO <= 0 makes the ratio meaningless (or sign-flipped) rather than
    # just large -- treated as unavailable, not computed.
    debt_servicing_pct = (
        debt_metrics.net_interest_expense_ttm / cfo_ttm * 100
        if debt_metrics.net_interest_expense_ttm is not None and cfo_ttm is not None and cfo_ttm > 0
        else None
    )

    if current_ratio is None or debt_to_ebitda is None or debt_servicing_pct is None:
        return Step5Out(
            ticker=ticker,
            company_type=company_type,
            score=None,
            verdict="insufficient_data",
            outlier_warnings=outlier_warnings,
        )

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
        outlier_warnings=outlier_warnings,
    )
