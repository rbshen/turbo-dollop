import json
from datetime import datetime

from sqlmodel import Session, select

from core.cache import get_or_fetch, get_or_fetch_earnings_aware, safe_fetch
from core.config import settings
from core.db import engine
from core.models import FundamentalsCache
from helpers.debt_metrics import compute_debt_metrics
from helpers.discount_rate_config import get_discount_rate_config
from helpers.earnings import resolve_most_recent_earnings_date
from helpers.reit_dividend_yield_config import get_reit_dividend_yield_config
from helpers.first import _first
from clients.fmp_client import fmp_client
from core.tickers import normalize_ticker
from core.schemas import (
    OutlierWarning,
    Step2Out,
    Step3CapmComponents,
    Step3CurrentValueCandidates,
    Step3Inputs,
    Step3MethodStep,
    Step3Out,
    Step3PBBands,
)
from scoring.classification import classify_company_type
from scoring.step3 import (
    classify_valuation_verdict,
    compute_capm,
    dividend_yield_meets_reit_threshold,
    dpu_growth_note,
    historical_pb_buy_signal,
    loss_making_pb_reference_note,
    normalize_fcf,
    pb_benchmark_for,
    run_20yr_engine,
    run_price_to_book,
    run_psg,
    select_method,
    trailing_smoothed_average,
)
from helpers.shares import compute_shares_outstanding
from data.custom_valuation_data import (
    get_ticker_custom_valuation,
    parse_custom_valuation_params,
    run_manual_calculation_from_params,
)
from data.step2_data import get_step2_data
from helpers.ttm import TOTAL_QUARTERS_NEEDED, is_ttm_period_duplicate_of_last_fy, sum_last_four_quarters

# Workbook default (valuation.md §4.1) -- never automated, matches the
# source spreadsheet's own fallback.
FAIR_PSG_RATIO_DEFAULT = 0.2
# Confirmed with the user: matches the spec's own worked example and
# standard long-term/GDP-growth DCF convention. User-editable per ticker in
# the UI (Phase 3) -- this is only the pre-filled default.
TERMINAL_GROWTH_RATE_DEFAULT = 0.04
# Confirmed with the user: Yr 6-10 defaults to Yr 1-5 except when Yr 1-5
# exceeds this, in which case the default is capped here.
GROWTH_YR_6_10_CAP = 0.15
# P/B lookback per spec §3.1 -- only "5 years" or "10 years" are valid, pick
# the longer window when enough history exists (matches this app's existing
# 10yr+TTM convention elsewhere -- see CLAUDE.md's Step 1/4 deviations).
PB_LOOKBACK_LONG = 10
PB_LOOKBACK_SHORT = 5


async def _resolve_fx_rate(
    session: Session,
    reported_currency: str | None,
    staleness_days: int,
    cache_only: bool,
) -> tuple[float | None, datetime | None]:
    """Resolves a ticker's reportedCurrency -> USD spot rate, cached the
    same way fundamentals are (FundamentalsCache, via the shared
    get_or_fetch/staleness machinery) rather than fetched fresh on every
    request -- see CLAUDE.md's non-USD currency conversion investigation.
    None/"USD" short-circuits to (1.0, None) with zero FMP calls -- every
    USD-reporting ticker (the vast majority) keeps today's exact behavior.

    Returns (None, None) -- never (1.0, None) -- when a real non-USD
    conversion is needed but no rate, fresh or stale, could be resolved at
    all. Silently defaulting to 1.0 here would render a wildly-wrong
    Fair Value at the ticker's raw local-currency scale; the caller must
    treat this as insufficient_data instead.

    A stale-but-real cached row is queried up front so a live fetch failure
    below (FMP outage/rate limit) can still fall back to it: get_or_fetch's
    own "prefer stale over nothing" behavior is normally exclusive to the
    cache_only=True path (nightly cron/recompute) -- a live request whose
    refetch throws would otherwise lose an otherwise-perfectly-usable stale
    rate to safe_fetch's {} convention. This local fallback stays scoped to
    this one call site rather than changing get_or_fetch's own shared
    contract, which dozens of other call sites also depend on."""
    if not reported_currency or reported_currency == "USD":
        return 1.0, None

    fx_symbol = f"{reported_currency}USD"

    def _cached_row() -> FundamentalsCache | None:
        return session.exec(
            select(FundamentalsCache).where(
                FundamentalsCache.ticker == fx_symbol,
                FundamentalsCache.statement_type == "forex_rate",
                FundamentalsCache.period == "latest",
            )
        ).first()

    existing_row = _cached_row()

    fx_quote = await safe_fetch(
        "forex_rate",
        get_or_fetch(
            session,
            fx_symbol,
            "forex_rate",
            "latest",
            lambda: fmp_client.get_forex_quote(reported_currency),
            staleness_days,
            cache_only,
        ),
    )
    fx_rate = _first(fx_quote).get("price")
    if fx_rate is not None:
        fx_row = _cached_row()
        return fx_rate, fx_row.fetched_at if fx_row else None

    if existing_row is not None:
        stale_rate = _first(json.loads(existing_row.raw_json)).get("price")
        if stale_rate is not None:
            return stale_rate, existing_row.fetched_at

    return None, None


def _annual_series(annual_rows: list[dict], field: str) -> tuple[list[str], list[float | None]]:
    # FMP returns annual rows most-recent-first; reverse to chronological
    # (oldest fiscal year first) -- same idiom as step1_data.py/step4_data.py.
    rows = list(reversed(annual_rows))
    years = [row.get("fiscalYear", row.get("date", "")[:4]) for row in rows]
    values = [row.get(field) for row in rows]
    return years, values


async def get_step3_data(
    ticker: str,
    cache_only: bool = False,
    step2_out: Step2Out | None = None,
) -> Step3Out:
    """`cache_only=True` (used by ticker_score.py's recompute path) reads
    only whatever's already cached and never calls FMP -- see
    cache.get_or_fetch's own cache_only branch.

    `step2_out`: optional pre-computed Step2Out, so a caller that's already
    run get_step2_data itself (get_summary, which needs Step 2's own
    growth_rate directly) doesn't force this function to redundantly
    recompute Step 2's cache read + full scoring a second time in the same
    request. Defaults to None, in which case this function fetches Step 2
    itself exactly as it always has -- every existing standalone caller
    (the bare /step3 endpoint, tests, recompute scripts) is unaffected."""
    ticker = normalize_ticker(ticker)
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        most_recent_earnings_date = await resolve_most_recent_earnings_date(session, ticker, staleness_days, cache_only)
        profile = _first(
            await safe_fetch(
                "profile",
                get_or_fetch(
                    session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days, cache_only
                ),
            )
        )
        quote = _first(
            await safe_fetch(
                "quote",
                get_or_fetch(
                    session, ticker, "quote", "latest", lambda: fmp_client.get_quote(ticker), staleness_days, cache_only
                ),
            )
        )
        # Same cache key + limit Step 1/Step 4 already populate
        # ("income_statement"/"annual", limit 10).
        income_annual = await safe_fetch(
            "income_statement_annual",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "income_statement",
                "annual",
                lambda: fmp_client.get_income_statement(ticker, "annual", 10),
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
                lambda: fmp_client.get_cash_flow_statement(ticker, "annual", 10),
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
        # Same cache key Step 4/Step 5 already populate
        # ("balance_sheet_statement"/"quarterly", limit TOTAL_QUARTERS_NEEDED)
        # -- this call site only reads row 0 (latest quarter), per spec
        # gotcha #2 (latest instant, not FY-end).
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
        # Same cache key Step 4/Step 5 already populate
        # ("balance_sheet_statement"/"annual", limit 10) -- a cache hit with
        # zero new FMP calls for any ticker Step 4/Step 5 has already
        # scored. Feeds the historical P/B series's tangible-book-value
        # recomputation below (2026-08-15) -- see pb_history's own comment.
        balance_sheet_annual = await safe_fetch(
            "balance_sheet_statement_annual",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "balance_sheet_statement",
                "annual",
                lambda: fmp_client.get_balance_sheet_statement(ticker, "annual", 10),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        # New cache key: 10yr annual ratios history (P/B bands + latest
        # book/sales-per-share) -- distinct from ticker_summary.py's
        # "ratios"/"latest" key (limit=1), so the two never fight over the
        # same cache row despite both hitting /ratios.
        ratios_annual = await safe_fetch(
            "ratios_annual_10y",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "ratios",
                "annual_10y",
                lambda: fmp_client.get_ratios(ticker, "annual", 10),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        # income_annual is still its raw safe_fetch result here (list, {},
        # or a genuinely malformed payload) -- _first handles all three the
        # same way _annual_series/etc. below do, so reading reportedCurrency
        # ahead of the list-coercion line below is safe. Resolved inside
        # this session block since _resolve_fx_rate needs it (get_or_fetch's
        # own cache read/write) -- and deliberately BEFORE the two
        # get-or-create config reads below: get_or_fetch's own write path
        # can commit() this session (a live forex fetch caching its
        # result), which -- with SQLAlchemy's default expire_on_commit=True
        # -- expires every ORM object already read from this session.
        reported_currency = _first(income_annual).get("reportedCurrency")
        fx_rate, fx_rate_as_of = await _resolve_fx_rate(session, reported_currency, staleness_days, cache_only)

        # Risk-Free Rate, Market Risk Premium, and the REIT dividend-yield
        # bargain-reference threshold are all manual, human-maintained
        # settings (see /settings and CLAUDE.md) -- read inside this
        # session block since their get-or-create helpers take a Session,
        # not fetched from FMP like everything else above. Each row's
        # scalar fields are read out into plain local variables
        # immediately, rather than holding onto the ORM row objects for use
        # after the `with` block exits: a get-or-create's own first-run
        # lazy-seed commit()s (see discount_rate_config.py/
        # reit_dividend_yield_config.py) expire -- via
        # expire_on_commit=True -- every ORM object already read from this
        # session, not just the one just committed, so whichever
        # get-or-create call ran earlier would otherwise raise
        # DetachedInstanceError the moment its attributes are accessed
        # after this block closes (confirmed: this broke for real once a
        # second config fetch was added here, not a theoretical concern).
        discount_rate_config = get_discount_rate_config(session)
        risk_free_rate = discount_rate_config.risk_free_rate
        market_risk_premium = discount_rate_config.market_risk_premium
        reit_dividend_yield_threshold_pct = get_reit_dividend_yield_config(session).threshold_pct

    income_annual = income_annual if isinstance(income_annual, list) else []
    income_quarterly = income_quarterly if isinstance(income_quarterly, list) else []
    cash_flow_annual = cash_flow_annual if isinstance(cash_flow_annual, list) else []
    cash_flow_quarterly = cash_flow_quarterly if isinstance(cash_flow_quarterly, list) else []
    balance_sheet_quarterly = balance_sheet_quarterly if isinstance(balance_sheet_quarterly, list) else []
    balance_sheet_annual = balance_sheet_annual if isinstance(balance_sheet_annual, list) else []
    ratios_annual = ratios_annual if isinstance(ratios_annual, list) else []
    balance_sheet_latest = _first(balance_sheet_quarterly)

    company_type = classify_company_type(
        profile.get("sector"), profile.get("industry"), ticker, is_fund=bool(profile.get("isEtf") or profile.get("isFund"))
    )

    if reported_currency and reported_currency != "USD" and fx_rate is None:
        # A genuine non-USD ticker whose FX rate couldn't be resolved at
        # all (FMP outage/rate-limit AND no cached rate, fresh or stale, to
        # fall back to) -- every monetary figure below would need this rate
        # to become a meaningful USD value, so there's no partial result
        # worth computing. Mirrors the total-fetch-failure PASS/
        # insufficient_data shape the rest of this function already uses
        # for other missing-data cases, rather than inventing a new state.
        return Step3Out(
            ticker=ticker,
            company_type=company_type,
            selected_method="PASS",
            pass_reason=(
                f"Could not resolve a {reported_currency}→USD exchange rate "
                "(FMP fetch failed and no cached rate was available) -- "
                "Valuation is unavailable until FX data can be fetched."
            ),
            insufficient_data=True,
            inputs=Step3Inputs(
                growth_yr_11_20=TERMINAL_GROWTH_RATE_DEFAULT,
                reported_currency=reported_currency,
                fx_rate=None,
                last_close=quote.get("price"),
            ),
        )

    years, revenue_annual = _annual_series(income_annual, "revenue")
    _, net_income_annual = _annual_series(income_annual, "netIncome")

    cash_flow_by_year = {row.get("fiscalYear"): row for row in cash_flow_annual}
    cfo_annual = [cash_flow_by_year.get(year, {}).get("netCashProvidedByOperatingActivities") for year in years]
    # capitalExpenditure is already negative (cash outflow) in FMP's schema
    # -- FCF = CFO + capitalExpenditure, not CFO - capitalExpenditure.
    capex_annual = [cash_flow_by_year.get(year, {}).get("capitalExpenditure") for year in years]
    fcf_annual = [c + x if c is not None and x is not None else None for c, x in zip(cfo_annual, capex_annual)]

    revenue_ttm_result = sum_last_four_quarters(income_quarterly, "revenue", income_annual)
    net_income_ttm_result = sum_last_four_quarters(income_quarterly, "netIncome", income_annual)
    cfo_ttm_result = sum_last_four_quarters(
        cash_flow_quarterly, "netCashProvidedByOperatingActivities", cash_flow_annual
    )
    capex_ttm_result = sum_last_four_quarters(cash_flow_quarterly, "capitalExpenditure", cash_flow_annual)

    revenue_ttm = revenue_ttm_result.total
    net_income_ttm = net_income_ttm_result.total
    cfo_ttm = cfo_ttm_result.total
    capex_ttm = capex_ttm_result.total
    fcf_ttm = cfo_ttm + capex_ttm if cfo_ttm is not None and capex_ttm is not None else None

    # Informational only -- never changes revenue_ttm/net_income_ttm/cfo_ttm/
    # fcf_ttm or intrinsic_value_per_share/verdict below (see
    # ttm.py::sum_last_four_quarters). Same convention as Step 1/Step 4/
    # Step 5/the ticker header; Valuation previously computed these flags
    # via sum_last_four_quarters and silently discarded them.
    outlier_warnings = [
        OutlierWarning(metric=metric, date=fq.date, value=fq.value, trailing_median=fq.trailing_median)
        for metric, result in [
            ("revenue_ttm", revenue_ttm_result),
            ("net_income_ttm", net_income_ttm_result),
            ("cfo_ttm", cfo_ttm_result),
            ("capex_ttm", capex_ttm_result),
        ]
        for fq in result.flagged
    ]

    # Convert every monetary figure to USD once, immediately after it's
    # pulled from FMP -- rather than deferring conversion to a final
    # multiply inside run_20yr_engine/run_price_to_book/run_psg -- so every
    # downstream consumer of these raw figures (the Model Valuation panel's
    # own displayed inputs, Manual Calculation's pre-fill, a saved Custom
    # Valuation's parameters) sees genuine USD, never a local-currency
    # number masquerading as one. fx_rate is guaranteed non-None here (the
    # short-circuit above already returned for the one case it wouldn't
    # be) and is exactly 1.0 for the ~546 USD-reporting tickers in the
    # tracked universe -- multiplying by 1.0 is an exact IEEE754 no-op, so
    # this is a byte-for-byte no-change for them. select_method below is
    # unaffected either way: every check it runs (CFO/NI ratio, CAGR,
    # trend shape) is scale-invariant, so converting before or after
    # method selection can never change which method gets picked.
    revenue_annual = [v * fx_rate if v is not None else None for v in revenue_annual]
    net_income_annual = [v * fx_rate if v is not None else None for v in net_income_annual]
    cfo_annual = [v * fx_rate if v is not None else None for v in cfo_annual]
    capex_annual = [v * fx_rate if v is not None else None for v in capex_annual]
    fcf_annual = [v * fx_rate if v is not None else None for v in fcf_annual]
    revenue_ttm = revenue_ttm * fx_rate if revenue_ttm is not None else None
    net_income_ttm = net_income_ttm * fx_rate if net_income_ttm is not None else None
    cfo_ttm = cfo_ttm * fx_rate if cfo_ttm is not None else None
    capex_ttm = capex_ttm * fx_rate if capex_ttm is not None else None
    fcf_ttm = fcf_ttm * fx_rate if fcf_ttm is not None else None

    # Clean (no-None), chronological series for the method-selection tree --
    # trend classification needs a gap-free run, same convention step1_data.py
    # uses for classify_trend's own inputs. cfo/capex are filtered jointly
    # (not independently) since normalize_fcf zips them positionally --
    # independent filtering could silently misalign "this year's CFO" with
    # "a different year's CapEx" if one series has a stray missing year the
    # other doesn't (see step4_data.py's _clean_aligned for the same concern).
    revenue_clean = [v for v in revenue_annual if v is not None] + ([revenue_ttm] if revenue_ttm is not None else [])
    net_income_clean = [v for v in net_income_annual if v is not None] + ([net_income_ttm] if net_income_ttm is not None else [])
    fcf_clean = [v for v in fcf_annual if v is not None] + ([fcf_ttm] if fcf_ttm is not None else [])
    # Same filter as fcf_clean above, so this stays index-aligned with both
    # fcf_clean (the [3a] series) and cfo_clean/capex_clean below (from
    # which [3b]'s normalized series is derived) -- lets select_method name
    # the actual offending period(s) in its failure detail for both checks.
    fcf_period_labels = [f"FY{year}" for year, v in zip(years, fcf_annual) if v is not None] + (
        ["TTM"] if fcf_ttm is not None else []
    )

    cfo_capex_pairs = [(c, x) for c, x in zip(cfo_annual, capex_annual) if c is not None and x is not None]
    if cfo_ttm is not None and capex_ttm is not None:
        cfo_capex_pairs.append((cfo_ttm, capex_ttm))
    cfo_clean = [c for c, _ in cfo_capex_pairs]
    capex_clean = [x for _, x in cfo_capex_pairs]

    selection = select_method(
        company_type=company_type,
        cfo_series=cfo_clean,
        cfo_ttm=cfo_ttm,
        net_income_series=net_income_clean,
        net_income_ttm=net_income_ttm,
        fcf_series=fcf_clean,
        capex_series=capex_clean,
        revenue_series=revenue_clean,
        fcf_period_labels=fcf_period_labels,
    )
    trail = [
        Step3MethodStep(step=s.step, check=s.check, passed=s.passed, detail=s.detail) for s in selection.decision_trail
    ]

    # Zero/near-zero debt should read as 0, never a fabricated/missing value
    # (spec gotcha #6) -- compute_debt_metrics already implements exactly
    # this rule, shared with Step 5 and the ticker header.
    debt_metrics = compute_debt_metrics(balance_sheet_latest, income_quarterly)
    total_debt = debt_metrics.total_debt * fx_rate if debt_metrics.total_debt is not None else None

    cash_only = balance_sheet_latest.get("cashAndCashEquivalents")
    cash_incl_st_investments = balance_sheet_latest.get("cashAndShortTermInvestments")
    # FMP's standardized schema has no equity-vs-debt split within short-term
    # investments (confirmed by inspecting JPM/AAPL/GOOGL/MSFT payloads) --
    # so the spec's "include equity-security holdings?" toggle is
    # approximated as "cash only" vs "cash + all short-term investments"
    # (which may include equity positions, undifferentiated). Defaults to
    # the combined figure; Phase 3 exposes both for the user-visible toggle
    # the spec explicitly asks for. cash_incl_st_investments itself (not the
    # converted figure) still drives the includes-short-term-investments
    # flag below, unaffected by currency.
    cash_and_st_investments = cash_incl_st_investments if cash_incl_st_investments is not None else cash_only
    cash_and_st_investments = cash_and_st_investments * fx_rate if cash_and_st_investments is not None else None

    shares_outstanding, shares_source = compute_shares_outstanding(quote, income_quarterly)

    beta = profile.get("beta")
    capm = None
    discount_rate = None
    if beta is not None:
        capm_result = compute_capm(risk_free_rate, market_risk_premium, beta)
        discount_rate = capm_result["discount_rate"]
        capm = Step3CapmComponents(
            risk_free_rate=capm_result["risk_free_rate"],
            market_risk_premium=capm_result["market_risk_premium"],
            beta=capm_result["beta"],
            beta_outside_reference_range=capm_result["beta_outside_reference_range"],
        )

    step2_out = step2_out if step2_out is not None else await get_step2_data(ticker, cache_only)
    growth_yr_1_5 = step2_out.growth_rate / 100 if step2_out.growth_rate is not None else None
    growth_yr_1_5_source = (
        f"analyst-estimate CAGR ({step2_out.basis} basis)" if step2_out.growth_rate is not None else None
    )
    # Yr 6-10 defaults to Yr 1-5, but capped at 15% when Yr 1-5 itself runs
    # hotter than that -- an unmoderated 5yr analyst-estimate growth rate
    # (e.g. 40%+ for a high-growth name) isn't a credible assumption to
    # silently carry into years 6-10 too.
    growth_yr_6_10 = min(growth_yr_1_5, GROWTH_YR_6_10_CAP) if growth_yr_1_5 is not None else None
    growth_yr_11_20 = TERMINAL_GROWTH_RATE_DEFAULT

    current_fiscal_year = years[-1] if years else None

    # Computed unconditionally (not just for whichever source the
    # method-selection tree actually picked) so Manual Calculation can
    # pre-fill a sensible Current Value default no matter which method the
    # user selects there -- see Step3CurrentValueCandidates. cfo_smoothed/
    # fcf_smoothed exist purely for this: CF_NORMALIZED/FCF_NORMALIZED are
    # Manual Calculation/Custom Valuation-only method choices (see CLAUDE.md's
    # Item 3 note) -- select_method's own tree never picks them, so nothing
    # above (selection.current_value_source) ever reads these two keys.
    normalized_fcf_series = normalize_fcf(cfo_clean, capex_clean)
    # income_statement and cash_flow_statement can independently be (or not
    # be) "TTM's 4 quarters duplicate the latest annual filing" -- checked
    # per-statement, not assumed shared, since one field can have a stray
    # missing quarter the other doesn't (see cfo_capex_pairs' own joint-filter
    # comment above for the same class of concern).
    ni_ttm_duplicates_last_fy = is_ttm_period_duplicate_of_last_fy(income_annual, income_quarterly)
    cf_ttm_duplicates_last_fy = is_ttm_period_duplicate_of_last_fy(cash_flow_annual, cash_flow_quarterly)
    current_value_by_source = {
        "cfo_ttm": cfo_ttm,
        "fcf_ttm": fcf_ttm,
        "fcf_normalized": normalized_fcf_series[-1] if normalized_fcf_series else None,
        "net_income_ttm": net_income_ttm,
        "net_income_smoothed": trailing_smoothed_average(net_income_clean, ni_ttm_duplicates_last_fy),
        "cfo_smoothed": trailing_smoothed_average(cfo_clean, cf_ttm_duplicates_last_fy),
        "fcf_smoothed": trailing_smoothed_average(fcf_clean, cf_ttm_duplicates_last_fy),
    }
    current_value = current_value_by_source.get(selection.current_value_source) if selection.current_value_source else None
    current_value_candidates = Step3CurrentValueCandidates(**current_value_by_source)
    current_value_labels = {
        "cfo_ttm": "Operating Cash Flow (Current)",
        "fcf_ttm": "Free Cash Flow (Current)",
        "fcf_normalized": "Free Cash Flow (Normalized, 5yr avg CapEx)",
        "net_income_ttm": "Net Income (Current)",
        "net_income_smoothed": "Net Income (Smoothed, 5yr avg)",
        "cfo_smoothed": "Operating Cash Flow (Smoothed, 5yr avg)",
        "fcf_smoothed": "Free Cash Flow (Smoothed, 5yr avg)",
    }
    current_value_label = current_value_labels.get(selection.current_value_source) if selection.current_value_source else None

    # P/B inputs. ratios_annual is most-recent-first (FMP's own order);
    # reversed to chronological (oldest first) since run_price_to_book's
    # "last N entries" convention means the N most recent, matching the
    # spec's own pseudocode -- also the natural left-to-right order for a
    # Phase 3 chart.
    #
    # Rebuilt onto the same tangible/quarterly-consistent book-value
    # definition as book_value_per_share below (2026-08-15), replacing the
    # prior FMP-raw-priceToBookRatio series -- averaging a series computed
    # on one book-value definition and multiplying it by a point value
    # computed on a different one produced a number that wasn't internally
    # consistent (previously documented here as a "deliberate" mismatch;
    # confirmed via real data this was worth fixing, not leaving as-is).
    # FMP's own priceToBookRatio = price / bookValuePerShare (its own
    # non-tangible per-share figure) for that period -- rescaling by
    # (totalStockholdersEquity / tangible_book_value) for the same fiscal
    # year converts it to price / tangible_book_value_per_share exactly,
    # since bookValuePerShare's own share-count denominator cancels out
    # algebraically: priceToBookRatio * (equity / tangible_equity)
    #   = (price / (equity/shares)) * (equity / tangible_equity)
    #   = price * shares / tangible_equity
    #   = price / (tangible_equity / shares)
    #   = price / tangible_book_value_per_share.
    # No new price-history fetch needed -- FMP's own priceToBookRatio
    # already embeds that period's price implicitly. Confirmed via real
    # cached data (JPM/BAC/WFC/O/AVB) that the resulting tangible-basis
    # book value per share this implies lands within ~1% of FMP's own
    # separately-reported tangibleBookValuePerShare field for the same
    # period -- i.e. this reproduces the same tangible concept, just
    # derived from data already fetched rather than trusting a second,
    # independent FMP field.
    balance_sheet_annual_by_fy = {row.get("fiscalYear"): row for row in balance_sheet_annual}
    pb_history_desc = []
    for row in ratios_annual:
        pb_raw = row.get("priceToBookRatio")
        bs_row = balance_sheet_annual_by_fy.get(row.get("fiscalYear"))
        if pb_raw is None or bs_row is None:
            continue
        equity = bs_row.get("totalStockholdersEquity")
        total_assets = bs_row.get("totalAssets")
        goodwill_and_intangibles = bs_row.get("goodwillAndIntangibleAssets")
        total_liabilities = bs_row.get("totalLiabilities")
        if None in (equity, total_assets, goodwill_and_intangibles, total_liabilities):
            continue
        tangible_equity = total_assets - goodwill_and_intangibles - total_liabilities
        if tangible_equity <= 0:
            # Same guard as book_value_per_share below -- a non-positive
            # tangible book value makes a P/B multiple for that period
            # undefined/meaningless, not just small; skip rather than
            # fabricate a negative or division-by-near-zero multiple.
            continue
        pb_history_desc.append(pb_raw * (equity / tangible_equity))
    pb_history = list(reversed(pb_history_desc))
    pb_lookback = None
    if len(pb_history) >= PB_LOOKBACK_LONG:
        pb_lookback = f"{PB_LOOKBACK_LONG} years"
    elif len(pb_history) >= PB_LOOKBACK_SHORT:
        pb_lookback = f"{PB_LOOKBACK_SHORT} years"
    # pb_history is a dimensionless multiple, never itself FX-converted --
    # both the price and the tangible book value it implicitly compares are
    # in the same (local) currency for any given period, so the ratio is
    # currency-invariant regardless of reported_currency; only the *current*
    # book_value_per_share below needs its own fx_rate multiply, since it's
    # a real dollar-per-share figure, not a ratio.
    #
    # book_value_per_share itself (valuation.md ss3.1's spec formula:
    # Total Assets - Intangible Assets - Total Liabilities, latest
    # quarter) is computed directly from balance_sheet_latest -- the same
    # latest-quarter row already used above for debt_metrics/
    # cash_and_st_investments -- rather than FMP's own bookValuePerShare
    # ratio field (raw stockholders' equity per share, sourced from the
    # latest *annual* filing, up to ~12 months stale). No new FMP fetch:
    # totalAssets/goodwillAndIntangibleAssets/totalLiabilities are already
    # on the balance_sheet_quarterly payload.
    tangible_book_value = None
    if None not in (
        balance_sheet_latest.get("totalAssets"),
        balance_sheet_latest.get("goodwillAndIntangibleAssets"),
        balance_sheet_latest.get("totalLiabilities"),
    ):
        tangible_book_value = (
            balance_sheet_latest["totalAssets"]
            - balance_sheet_latest["goodwillAndIntangibleAssets"]
            - balance_sheet_latest["totalLiabilities"]
        )
    book_value_per_share = (
        tangible_book_value / shares_outstanding if tangible_book_value is not None and shares_outstanding else None
    )
    book_value_per_share = book_value_per_share * fx_rate if book_value_per_share is not None else None

    # Computed unconditionally (not just when PRICE_TO_BOOK is the
    # auto-selected method) so Manual Calculation can pre-fill a real
    # mean/SD P/B pair regardless of which method the user selects there.
    # fx_rate=1.0 here is deliberate, not a leftover -- book_value_per_share
    # is already USD by this point (converted above), so run_price_to_book
    # must not convert it a second time. See Step3Inputs.fx_rate's own
    # docstring for why every engine call in this function passes 1.0.
    pb_result = None
    if book_value_per_share is not None and pb_lookback is not None:
        pb_result = run_price_to_book(
            book_value_per_share=book_value_per_share,
            historical_pb_ratios=pb_history,
            lookback=pb_lookback,
            fx_rate=1.0,
            last_close=quote.get("price"),
        )

    # PSG inputs.
    sales_per_share = _first(ratios_annual).get("revenuePerShare")
    sales_per_share = sales_per_share * fx_rate if sales_per_share is not None else None

    # Additive, informational-only fields (CLAUDE.md's Bank/REIT/Insurance
    # investigation) -- never change intrinsic_value_per_share/
    # discount_premium_pct/verdict above, which keep their existing
    # mean+-10% logic untouched. The -1SD value itself already exists as
    # pb_result.bands["minus_1sd"] whenever P/B was computed (unconditional,
    # same as pb_mean_ratio/pb_sd_ratio above) -- this just names the
    # framework's own buy signal explicitly.
    pb_buy_signal = (
        historical_pb_buy_signal(quote.get("price"), pb_result.bands["minus_1sd"]) if pb_result is not None else None
    )
    pb_benchmark = pb_benchmark_for(company_type)

    # REIT Dividend/DPU signal -- dividendYield/dividendPerShare are already
    # present on the same ratios_annual rows fetched above for the P/B
    # lookback, no new FMP call needed. FMP reports dividendYield as a
    # fraction (e.g. 0.04), scaled *100 here to match every other percent
    # field on this model (same convention ticker_summary.py's dividend_yield
    # already uses for the TTM equivalent from /ratios-ttm).
    dividend_yield_raw = _first(ratios_annual).get("dividendYield")
    dividend_yield_pct = dividend_yield_raw * 100 if dividend_yield_raw is not None else None
    # Known gap, deliberately deferred: dividendPerShare (a real per-share
    # monetary figure) is left un-converted here -- dpu_growth_note is
    # informational text only (never feeds verdict/score), and no
    # currently-tracked non-USD ticker is a REIT, so this is low-stakes for
    # now. Convert (dpu * fx_rate) if a non-USD REIT is ever added.
    dpu_series = list(reversed([row.get("dividendPerShare") for row in ratios_annual]))
    is_reit = company_type == "REIT/Property Developer"

    inputs = Step3Inputs(
        current_value=current_value,
        current_value_label=current_value_label,
        current_value_candidates=current_value_candidates,
        total_debt=total_debt,
        cash_and_st_investments=cash_and_st_investments,
        cash_and_st_investments_includes_short_term_investments=cash_incl_st_investments is not None,
        growth_yr_1_5=growth_yr_1_5,
        growth_yr_6_10=growth_yr_6_10,
        growth_yr_11_20=growth_yr_11_20,
        growth_yr_1_5_source=growth_yr_1_5_source,
        shares_outstanding=shares_outstanding,
        shares_outstanding_source=shares_source,
        discount_rate=discount_rate,
        capm=capm,
        current_fiscal_year=current_fiscal_year,
        reported_currency=reported_currency,
        fx_rate=fx_rate,
        fx_rate_as_of=fx_rate_as_of,
        last_close=quote.get("price"),
        book_value_per_share=book_value_per_share,
        historical_pb_ratios=pb_history or None,
        pb_lookback=pb_lookback,
        pb_mean_ratio=pb_result.mean_pb if pb_result else None,
        pb_sd_ratio=pb_result.sd_pb if pb_result else None,
        sales_per_share=sales_per_share,
        projected_growth_rate=growth_yr_1_5,
        fair_psg_ratio=FAIR_PSG_RATIO_DEFAULT,
    )

    intrinsic_value_per_share = None
    pb_bands = None
    discount_premium_pct = None

    if selection.method in ("DCF", "DFCF", "DNI", "DNI_NORMALIZED"):
        if None not in (
            inputs.current_value,
            inputs.growth_yr_1_5,
            inputs.growth_yr_6_10,
            inputs.discount_rate,
            inputs.shares_outstanding,
            inputs.total_debt,
            inputs.cash_and_st_investments,
        ):
            engine_result = run_20yr_engine(
                current_value=inputs.current_value,
                growth_yr_1_5=inputs.growth_yr_1_5,
                growth_yr_6_10=inputs.growth_yr_6_10,
                growth_yr_11_20=inputs.growth_yr_11_20,
                discount_rate=inputs.discount_rate,
                shares_outstanding=inputs.shares_outstanding,
                total_debt=inputs.total_debt,
                cash_and_st_investments=inputs.cash_and_st_investments,
                # 1.0, not inputs.fx_rate -- current_value/total_debt/
                # cash_and_st_investments above are already USD (converted
                # upfront, see the comment where revenue_ttm/etc. are
                # converted); using inputs.fx_rate here would convert twice.
                fx_rate=1.0,
                last_close=inputs.last_close,
            )
            intrinsic_value_per_share = engine_result.intrinsic_value_per_share
            discount_premium_pct = engine_result.discount_premium_pct
    elif selection.method == "PRICE_TO_BOOK":
        if pb_result is not None:
            pb_bands = Step3PBBands(**pb_result.bands)
            intrinsic_value_per_share = pb_result.bands["mean"]
            discount_premium_pct = pb_result.discount_premium_pct
    elif selection.method == "PSG":
        if inputs.sales_per_share is not None and inputs.projected_growth_rate is not None:
            psg_result = run_psg(
                sales_per_share=inputs.sales_per_share,
                projected_growth_rate=inputs.projected_growth_rate,
                fair_psg_ratio=inputs.fair_psg_ratio,
                # 1.0, not inputs.fx_rate -- sales_per_share is already USD
                # (converted upfront); see the 20yr-engine call above for
                # the same reasoning.
                fx_rate=1.0,
                last_close=inputs.last_close,
            )
            intrinsic_value_per_share = psg_result.intrinsic_value_per_share
            discount_premium_pct = psg_result.discount_premium_pct

    # Loss-making Standard company PB reference (spec's Method B,
    # "Liquidation Method") -- purely additive/informational, computed
    # independently of select_method's own decision_trail/pass_reason
    # (both stay exactly what Auto's tree actually produced). Gated on
    # selection.method == "PASS" specifically, not just "loss-making": a
    # Standard company with negative Net Income can still resolve to a
    # real method (DCF/DFCF via the CFO-based branch, which never looks at
    # Net Income), in which case this reference would be misleading rather
    # than helpful. book_value_per_share/quote are already computed above
    # for the unconditional P/B pre-fill -- no new fetches.
    loss_making_pb_note = None
    if (
        company_type == "Standard"
        and selection.method == "PASS"
        and net_income_ttm is not None
        and net_income_ttm <= 0
    ):
        current_pb_ratio = (
            quote.get("price") / book_value_per_share
            if quote.get("price") and book_value_per_share
            else None
        )
        loss_making_pb_note = loss_making_pb_reference_note(current_pb_ratio, book_value_per_share)

    return Step3Out(
        ticker=ticker,
        company_type=company_type,
        selected_method=selection.method,
        method_reasoning=trail,
        pass_reason=selection.pass_reason,
        insufficient_data=selection.insufficient_data,
        inputs=inputs,
        intrinsic_value_per_share=intrinsic_value_per_share,
        pb_bands=pb_bands,
        discount_premium_pct=discount_premium_pct,
        verdict=classify_valuation_verdict(discount_premium_pct),
        historical_pb_buy_signal=pb_buy_signal,
        benchmark_pb_low=pb_benchmark.low if pb_benchmark else None,
        benchmark_pb_high=pb_benchmark.high if pb_benchmark else None,
        benchmark_pb_note=pb_benchmark.note if pb_benchmark else None,
        dividend_yield_pct=dividend_yield_pct if is_reit else None,
        dividend_yield_meets_reit_threshold=(
            dividend_yield_meets_reit_threshold(dividend_yield_pct, reit_dividend_yield_threshold_pct)
            if is_reit
            else None
        ),
        dpu_growth_note=dpu_growth_note(dpu_series) if is_reit else None,
        loss_making_pb_note=loss_making_pb_note,
        outlier_warnings=outlier_warnings,
    )


async def get_active_valuation(
    ticker: str,
    cache_only: bool = False,
    step2_out: Step2Out | None = None,
) -> Step3Out:
    """The single choke point every consumer of Step 3's valuation
    result/verdict should call instead of get_step3_data directly --
    resolves whether this ticker's active source is Auto Calculation or a
    saved, activated TickerCustomValuation row (see
    custom_valuation_data.py), covering the Valuation tab, the ticker
    header pill (via ticker_summary.py::get_summary), and Screener/
    Watchlist (via compute_ticker_score, which calls get_summary
    internally) with one swap each.

    Auto Calculation is ALWAYS computed first and its own company_type/
    method_reasoning/pass_reason/inputs are NEVER overridden -- they
    describe what Auto's method-selection tree actually did, which stays
    meaningful context regardless of what's active (and rebuilding an
    equivalent Step3Inputs for an arbitrary user-chosen method would
    duplicate this function's own current-value-label/P-B/PSG mapping
    logic a second time, lossily). Only the result-facing fields
    (selected_method/intrinsic_value_per_share/pb_bands/
    discount_premium_pct/verdict) are overridden when a custom valuation is
    active -- see Step3Out.valuation_source's own docstring."""
    auto = await get_step3_data(ticker, cache_only, step2_out)

    with Session(engine) as session:
        custom = get_ticker_custom_valuation(session, normalize_ticker(ticker))
    if custom is None or not custom.is_active:
        return auto.model_copy(update={"valuation_source": "auto"})

    params = parse_custom_valuation_params(custom.parameters_json)
    if params is None:
        # Corrupt parameters_json must never 500 the whole ticker page --
        # fall back to Auto, same as "no custom valuation saved at all".
        return auto.model_copy(update={"valuation_source": "auto"})

    result = run_manual_calculation_from_params(custom.method, params, auto.inputs.last_close)
    return auto.model_copy(
        update={
            "valuation_source": "custom",
            "selected_method": custom.method,
            "intrinsic_value_per_share": result.intrinsic_value_per_share,
            "pb_bands": Step3PBBands(**result.pb_bands) if result.pb_bands else None,
            "discount_premium_pct": result.discount_premium_pct,
            "verdict": result.verdict,
        }
    )
