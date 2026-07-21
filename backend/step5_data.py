from datetime import date as date_cls

from sqlmodel import Session

import sec_edgar
from cache import get_or_fetch, safe_fetch
from config import settings
from db import engine
from debt_metrics import MetricOutlierFlags, compute_debt_metrics
from fmp_client import fmp_client
from npl import compute_npl_ratio
from schemas import OutlierWarning, SecCrossCheck, Step5Out, Step5RatioResult
from scoring.step5 import classify_company_type, score_npl, score_step5_reit, score_step5_standard
from ttm import TOTAL_QUARTERS_NEEDED, sum_last_four_quarters

# The Debt Servicing Ratio's own two inputs -- an outlier flagged on either
# of these triggers an on-demand SEC EDGAR cross-check (see sec_edgar.py).
# Never triggered in bulk/nightly -- only when a specific quarter is
# already flagged for a specific ticker being viewed.
SEC_CROSS_CHECK_METRICS = {"net_interest_expense_ttm", "cfo_ttm"}


def _first(data: dict | list) -> dict:
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def _ratio_out(raw: dict) -> Step5RatioResult:
    # interest_coverage_ratio is informational only -- it influences the
    # OTHER ratios' scoring (as the icr_is_safe signal) but has no points
    # of its own, so "points" is absent from its dict.
    return Step5RatioResult(
        value=raw["value"],
        adjusted_value=raw.get("adjusted_value"),
        label=raw["label"],
        points=raw.get("points", 0),
        saved_by_tiebreaker=raw.get("saved_by_tiebreaker", False),
    )


def _outlier_warnings(*flag_groups: MetricOutlierFlags) -> list[OutlierWarning]:
    return [
        OutlierWarning(metric=group.metric, date=fq.date, value=fq.value, trailing_median=fq.trailing_median)
        for group in flag_groups
        for fq in group.flagged
    ]


async def _attach_sec_cross_checks(
    session: Session, ticker: str, warnings: list[OutlierWarning], staleness_days: int
) -> list[OutlierWarning]:
    """On-demand only -- called with exactly the flagged quarter(s) for one
    ticker's Step 5 view, never in a bulk sweep (SEC EDGAR's rate-limit
    penalty for exceeding 10 req/sec is a 10-minute lockout, far harsher
    than FMP's)."""
    result = []
    for warning in warnings:
        if warning.metric not in SEC_CROSS_CHECK_METRICS or not warning.date:
            result.append(warning)
            continue

        target_end = date_cls.fromisoformat(warning.date)
        if warning.metric == "net_interest_expense_ttm":
            # warning.value is the raw quarterly netInterestIncome figure
            # (negative = net expense) -- flip sign to match SEC's
            # positive-expense tag convention.
            cross_check = await sec_edgar.cross_check_interest_expense(session, ticker, target_end, -warning.value, staleness_days)
        else:  # cfo_ttm
            cross_check = await sec_edgar.cross_check_cfo(session, ticker, target_end, warning.value, staleness_days)

        result.append(warning.model_copy(update={"sec_cross_check": SecCrossCheck(**cross_check._asdict())}))
    return result


async def get_step5_data(ticker: str, cache_only: bool = False) -> Step5Out:
    """`cache_only=True` (used by ticker_score.py's recompute path) reads
    only whatever's already cached and never calls FMP -- see
    cache.get_or_fetch's own cache_only branch. It also skips the SEC EDGAR
    cross-check entirely regardless of whether an outlier is flagged: that
    cross-check is on-demand-only by design (SEC's rate-limit penalty is a
    10-minute lockout), and must never fire during a ~500-ticker sweep."""
    ticker = ticker.upper()
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        profile = _first(
            await safe_fetch(
                "profile",
                get_or_fetch(
                    session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days, cache_only
                ),
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
                cache_only,
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
            full_as_reported_quarterly = await safe_fetch(
                "financial_statement_full_as_reported_quarterly",
                get_or_fetch(
                    session,
                    ticker,
                    "financial_statement_full_as_reported",
                    "quarterly",
                    lambda: fmp_client.get_financial_statement_full_as_reported(ticker, "quarter", 1),
                    staleness_days,
                    cache_only,
                ),
            )
            # Fallback source when the latest quarter's nonaccrual-loan tag
            # is absent -- confirmed a real 10-K-only disclosure gap for
            # some filers (USB, TFC), not a data error.
            full_as_reported_annual = await safe_fetch(
                "financial_statement_full_as_reported_annual",
                get_or_fetch(
                    session,
                    ticker,
                    "financial_statement_full_as_reported",
                    "annual",
                    lambda: fmp_client.get_financial_statement_full_as_reported(ticker, "annual", 1),
                    staleness_days,
                    cache_only,
                ),
            )
            quarterly_row = _first(full_as_reported_quarterly)
            annual_row = _first(full_as_reported_annual)

            npl_result = compute_npl_ratio(quarterly_row, annual_row, balance_sheet_row.get("totalAssets"))
            ratios = {}
            if npl_result.ratio_pct is not None:
                npl_score = score_npl(npl_result.ratio_pct)
                ratios["npl_ratio"] = _ratio_out(
                    {"value": npl_result.ratio_pct, "label": npl_score.label, "points": npl_score.points}
                )

            return Step5Out(
                ticker=ticker,
                company_type=company_type,
                ratios=ratios,
                npl_as_of=npl_result.as_of,
                score=None,
                verdict="not_supported",
            )

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
                cache_only,
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
                cache_only,
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

    if outlier_warnings and not cache_only:
        # Fresh, short-lived session scoped to just this on-demand
        # cross-check -- only opened when there's actually something
        # flagged, not on every Step 5 view, and never at all in
        # cache_only mode (see this function's docstring).
        with Session(engine) as sec_session:
            outlier_warnings = await _attach_sec_cross_checks(sec_session, ticker, outlier_warnings, staleness_days)

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
    # Deferred revenue -- a current LIABILITY representing cash already
    # collected, not a real short-term obligation -- is now wired into the
    # Current Ratio verdict itself (see scoring/step5.py::score_current_ratio),
    # not just an informational note. Falls back to the raw ratio if
    # subtracting it would leave a non-positive denominator.
    adjusted_liabilities = current_liabilities - (deferred_revenue or 0) if current_liabilities else None
    adjusted_current_ratio = (
        current_assets / adjusted_liabilities
        if current_assets is not None and adjusted_liabilities is not None and adjusted_liabilities > 0
        else current_ratio
    )
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
    # Interest Coverage Ratio: the Debt/EBITDA and Debt Servicing Ratio
    # tiebreaker (never Current Ratio's -- that's deferred revenue above).
    # Interest expense <= 0 makes the ratio meaningless -- None, not
    # fabricated as "infinitely safe".
    interest_coverage_ratio = (
        debt_metrics.ebit_ttm / debt_metrics.interest_expense_ttm
        if debt_metrics.ebit_ttm is not None
        and debt_metrics.interest_expense_ttm is not None
        and debt_metrics.interest_expense_ttm > 0
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

    result = score_step5_standard(current_ratio, adjusted_current_ratio, debt_to_ebitda, debt_servicing_pct, interest_coverage_ratio)
    return Step5Out(
        ticker=ticker,
        company_type=company_type,
        ratios={
            "current_ratio": _ratio_out(result["ratios"]["current_ratio"]),
            "debt_to_ebitda": _ratio_out(result["ratios"]["debt_to_ebitda"]),
            "debt_servicing_ratio": _ratio_out(result["ratios"]["debt_servicing_ratio"]),
            "interest_coverage_ratio": _ratio_out(result["ratios"]["interest_coverage_ratio"]),
        },
        deferred_revenue_current=deferred_revenue,
        score=result["score"],
        verdict=result["verdict"],
        hard_fail=result["hard_fail"],
        pass_with_caution=result["pass_with_caution"],
        outlier_warnings=outlier_warnings,
    )
