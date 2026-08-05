from datetime import date as date_cls

from sqlmodel import Session

import clients.sec_edgar as sec_edgar
from helpers.bank_capital_metrics import get_ticker_bank_capital_metrics
from core.cache import get_or_fetch, safe_fetch
from core.config import settings
from core.db import engine
from helpers.debt_metrics import MetricOutlierFlags, compute_debt_metrics
from helpers.first import _first
from clients.fmp_client import fmp_client
from helpers.npl import compute_npl_ratio
from core.schemas import BreachContextSignal, OutlierWarning, SecCrossCheck, Step5Out, Step5RatioResult
from scoring.step5 import classify_company_type, score_npl, score_step5_bank, score_step5_reit, score_step5_standard
from helpers.ttm import TOTAL_QUARTERS_NEEDED, sum_last_four_quarters

# Same 10yr fetch window/cache key Step 4 already populates
# ("balance_sheet_statement"/"annual", "income_statement"/"annual") -- for
# any ticker Step 4 has already scored, this is a pure cache hit with zero
# new FMP calls. Only the most recent TREND_WINDOW_YEARS get used for the
# breach-context trend signal; fetching at the full 10 avoids ever caching
# a truncated dataset under a cache key Step 4 also depends on (see
# CLAUDE.md's caching policy).
ANNUAL_WINDOW = 10
TREND_WINDOW_YEARS = 5

# The Debt Servicing Ratio's own two inputs -- an outlier flagged on either
# of these triggers an on-demand SEC EDGAR cross-check (see sec_edgar.py).
# Never triggered in bulk/nightly -- only when a specific quarter is
# already flagged for a specific ticker being viewed.
SEC_CROSS_CHECK_METRICS = {"net_interest_expense_ttm", "cfo_ttm"}

# Of the tickers classify_company_type buckets as "Bank", these two are
# confirmed (via cached FMP XBRL data -- the `deposits` tag is entirely
# absent) to have no customer deposit-taking business, unlike SCHW/GS/MS
# (confirmed present, 23-49% of total assets). CET1 is a regulatory
# capital-adequacy ratio that only makes sense for a deposit-taking
# institution, so these two never get the CET1/NPL manual-entry treatment
# even though they stay classify_company_type == "Bank" everywhere else in
# the app (Step 1's NII swap, Step 4's ROIC exemption). Deliberately a
# separate constant from classify_company_type/NON_LENDER_TICKER_OVERRIDES
# (scoring/classification.py) -- that mechanism answers a different
# question (is this ticker a lender at all) and must not be touched by this
# feature; this one only controls whether the CET1/NPL input UI/scoring
# path applies to an already-Bank-classified ticker.
BANK_CET1_NPL_EXCLUDED_TICKERS = {"IBKR", "HOOD"}


def _ratio_out(raw: dict) -> Step5RatioResult:
    # interest_coverage_ratio is informational only -- it influences the
    # OTHER ratios' scoring (as the icr_is_safe signal) but has no points
    # of its own, so "points" is absent from its dict.
    breach_context = raw.get("breach_context")
    return Step5RatioResult(
        value=raw["value"],
        adjusted_value=raw.get("adjusted_value"),
        label=raw["label"],
        points=raw.get("points", 0),
        saved_by_tiebreaker=raw.get("saved_by_tiebreaker", False),
        breach_context=[BreachContextSignal(**s._asdict()) for s in breach_context] if breach_context else None,
    )


def _annual_series(annual_rows: list[dict], field: str, count: int = ANNUAL_WINDOW) -> list[float | None]:
    # FMP returns annual rows most-recent-first; take the most recent
    # `count` and reverse to chronological (oldest fiscal year first),
    # None-padded at the oldest end if fewer than `count` are available --
    # same convention as step4_data.py's own private helper of this shape
    # (not shared/exported; each step file keeps its own copy).
    rows = list(reversed(annual_rows[:count]))
    pad = count - len(rows)
    return [None] * pad + [row.get(field) for row in rows]


def _annual_years(annual_rows: list[dict], count: int = ANNUAL_WINDOW) -> list[str | None]:
    rows = list(reversed(annual_rows[:count]))
    pad = count - len(rows)
    return [None] * pad + [row.get("fiscalYear", (row.get("date") or "")[:4]) or None for row in rows]


def _oldest_in_trend_window(series: list[float | None], years: list[str | None]) -> tuple[float | None, str | None]:
    """The oldest slot of the most-recent TREND_WINDOW_YEARS -- None
    (rather than falling back to an older or more-recent real value) when
    that specific slot is empty, so a ticker with under 5 years of annual
    filings reads as not_computable instead of silently comparing against
    a shorter, mislabeled window (see scoring/step5.py::_trend_signal)."""
    window = series[-TREND_WINDOW_YEARS:]
    window_years = years[-TREND_WINDOW_YEARS:]
    if not window:
        return None, None
    return window[0], window_years[0]


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
        company_type = classify_company_type(profile.get("sector"), profile.get("industry"), ticker)

        # Balance sheet items are point-in-time snapshots -- the latest
        # available quarter is simply more current than the latest annual
        # filing (which can be many months stale by the time this is viewed).
        # Limit is TOTAL_QUARTERS_NEEDED (shared cache key with Step 4 and
        # the Financials tab's financials_data.py, which needs the deeper
        # history) -- this call site still only reads row 0 below, so the
        # deeper fetch doesn't change anything here.
        balance_sheet = await safe_fetch(
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
        balance_sheet_row = _first(balance_sheet)

        if company_type == "Bank":
            # CET1 is manual-entry only (no FMP source -- see CLAUDE.md);
            # NPL is a partial signal computed from FMP's raw XBRL-tag dump
            # (not the standardized schema) -- see npl.py for why this
            # isn't trusted blindly across every bank ticker. Auto-NPL
            # still runs unconditionally (even for excluded tickers, and
            # even when a manual override exists) since it's needed as the
            # pre-fill/fallback value regardless.
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

            if ticker in BANK_CET1_NPL_EXCLUDED_TICKERS:
                # Byte-for-byte today's behavior -- no deposit-taking
                # business, so CET1 doesn't apply and no manual-entry UI is
                # offered; IBKR/HOOD must be completely unaffected by this
                # feature.
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
                    bank_capital_metrics_editable=False,
                )

            metrics_row = get_ticker_bank_capital_metrics(session, ticker)
            cet1_pct = metrics_row.cet1_ratio_pct if metrics_row else None
            cet1_as_of = metrics_row.cet1_as_of if metrics_row else None
            manual_npl_pct = metrics_row.npl_ratio_pct if metrics_row else None
            manual_npl_as_of = metrics_row.npl_as_of if metrics_row else None

            if manual_npl_pct is not None:
                resolved_npl_pct, resolved_npl_as_of, npl_source = manual_npl_pct, manual_npl_as_of, "manual"
            elif npl_result.ratio_pct is not None:
                resolved_npl_pct, resolved_npl_as_of, npl_source = npl_result.ratio_pct, npl_result.as_of, "auto"
            else:
                resolved_npl_pct, resolved_npl_as_of, npl_source = None, None, None

            ratios = {}
            if resolved_npl_pct is not None:
                npl_score = score_npl(resolved_npl_pct)
                ratios["npl_ratio"] = _ratio_out(
                    {"value": resolved_npl_pct, "label": npl_score.label, "points": npl_score.points}
                )

            if cet1_pct is None or resolved_npl_pct is None:
                # Still "not_supported" -- but populate whatever's
                # available (resolved NPL + its source/as-of, and the raw
                # cet1_ratio_pct=None "not yet entered" signal) so the
                # frontend can render the input form pre-filled correctly.
                return Step5Out(
                    ticker=ticker,
                    company_type=company_type,
                    ratios=ratios,
                    npl_as_of=resolved_npl_as_of,
                    npl_source=npl_source,
                    cet1_ratio_pct=cet1_pct,
                    cet1_as_of=cet1_as_of,
                    score=None,
                    verdict="not_supported",
                    bank_capital_metrics_editable=True,
                )

            result = score_step5_bank(cet1_pct, resolved_npl_pct)
            return Step5Out(
                ticker=ticker,
                company_type=company_type,
                ratios={
                    "cet1_ratio": _ratio_out(result["ratios"]["cet1_ratio"]),
                    "npl_ratio": _ratio_out(result["ratios"]["npl_ratio"]),
                },
                npl_as_of=resolved_npl_as_of,
                npl_source=npl_source,
                cet1_ratio_pct=cet1_pct,
                cet1_as_of=cet1_as_of,
                score=result["score"],
                verdict=result["verdict"],
                hard_fail=result["hard_fail"],
                weights=result["weights"],
                bank_capital_metrics_editable=True,
            )

        if company_type == "Insurance":
            # The Standard path's 3 hard-numeric ratios (Current Ratio /
            # Debt-EBITDA / Debt Servicing Ratio) aren't meaningful for
            # insurers -- their balance sheets are dominated by loss
            # reserves and unearned premiums (not comparable to a real
            # short-term liquidity picture), and their debt levels need
            # general qualitative judgement, not a hard numeric threshold
            # (confirmed via repro: PGR's real Current Ratio of 0.67 alone
            # forced a hard-fail "severe" breach and a 67/Fail verdict
            # despite Debt/EBITDA, DSR, and Interest Coverage Ratio all
            # reading excellent -- Current Ratio's deferred-revenue rescue
            # can't save this either, since insurers carry unearned premium
            # reserves under a different balance-sheet line FMP's schema
            # doesn't map to "deferredRevenue"). Unlike Bank, there's no
            # NPL-equivalent partial signal available for Insurance (no
            # capital-adequacy ratio computable from FMP's data, the same
            # class of gap as Bank's own CET1), so this returns immediately
            # with no ratios at all rather than attempting one.
            return Step5Out(
                ticker=ticker,
                company_type=company_type,
                ratios={},
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
            weights=result["weights"],
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

    # Breach-context inputs -- only fetched/computed once we know we're
    # actually proceeding to score (the insufficient_data bailout above
    # already ran). Annual fetches reuse Step 4's exact cache key/limit
    # (see ANNUAL_WINDOW's own comment) -- a cache hit with zero new FMP
    # calls for any ticker Step 4 has already scored.
    with Session(engine) as session:
        balance_sheet_annual = await safe_fetch(
            "balance_sheet_statement_annual",
            get_or_fetch(
                session,
                ticker,
                "balance_sheet_statement",
                "annual",
                lambda: fmp_client.get_balance_sheet_statement(ticker, "annual", ANNUAL_WINDOW),
                staleness_days,
                cache_only,
            ),
        )
        income_annual = await safe_fetch(
            "income_statement_annual",
            get_or_fetch(
                session,
                ticker,
                "income_statement",
                "annual",
                lambda: fmp_client.get_income_statement(ticker, "annual", ANNUAL_WINDOW),
                staleness_days,
                cache_only,
            ),
        )
    balance_sheet_annual = balance_sheet_annual if isinstance(balance_sheet_annual, list) else []
    income_annual = income_annual if isinstance(income_annual, list) else []

    years = _annual_years(balance_sheet_annual)
    short_term_debt_series = _annual_series(balance_sheet_annual, "shortTermDebt")
    long_term_debt_series = _annual_series(balance_sheet_annual, "longTermDebt")
    ebitda_series = _annual_series(income_annual, "ebitda")
    debt_to_ebitda_series = [
        ((st or 0) + (lt or 0)) / e if (st is not None or lt is not None) and e else None
        for st, lt, e in zip(short_term_debt_series, long_term_debt_series, ebitda_series)
    ]
    current_assets_series = _annual_series(balance_sheet_annual, "totalCurrentAssets")
    current_liabilities_series = _annual_series(balance_sheet_annual, "totalCurrentLiabilities")
    current_ratio_series = [
        ca / cl if ca is not None and cl else None for ca, cl in zip(current_assets_series, current_liabilities_series)
    ]
    debt_to_ebitda_oldest, debt_to_ebitda_oldest_year = _oldest_in_trend_window(debt_to_ebitda_series, years)
    current_ratio_oldest, current_ratio_oldest_year = _oldest_in_trend_window(current_ratio_series, years)

    fcf_ttm = sum_last_four_quarters(cash_flow_quarterly, "freeCashFlow").total
    cash_and_equivalents = balance_sheet_row.get("cashAndCashEquivalents")
    net_debt = balance_sheet_row.get("netDebt")
    receivables = balance_sheet_row.get("netReceivables")
    if receivables is None:
        receivables = balance_sheet_row.get("accountsReceivables")
    liquid_current_assets = (
        cash_and_equivalents + receivables if cash_and_equivalents is not None and receivables is not None else None
    )

    result = score_step5_standard(
        current_ratio,
        adjusted_current_ratio,
        debt_to_ebitda,
        debt_servicing_pct,
        interest_coverage_ratio,
        debt_to_ebitda_oldest=debt_to_ebitda_oldest,
        debt_to_ebitda_oldest_year=debt_to_ebitda_oldest_year,
        current_ratio_oldest=current_ratio_oldest,
        current_ratio_oldest_year=current_ratio_oldest_year,
        fcf_ttm=fcf_ttm,
        total_debt=debt_metrics.total_debt,
        net_debt=net_debt,
        ebitda_ttm=ebitda_ttm,
        deferred_revenue=deferred_revenue,
        current_liabilities=current_liabilities,
        cash_and_equivalents=cash_and_equivalents,
        current_assets=current_assets,
        liquid_current_assets=liquid_current_assets,
    )
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
        weights=result["weights"],
        outlier_warnings=outlier_warnings,
    )
