import logging

from sqlmodel import Session

from core.cache import get_or_fetch, safe_fetch
from core.config import settings
from core.db import engine
from helpers.debt_metrics import compute_debt_metrics
from helpers.discount_rate_config import get_discount_rate_config
from helpers.first import _first
from clients.fmp_client import fmp_client
from core.schemas import (
    Step2Out,
    Step3CapmComponents,
    Step3CurrentValueCandidates,
    Step3Inputs,
    Step3ManualParams,
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
    normalize_fcf,
    pb_benchmark_for,
    run_20yr_engine,
    run_manual_calculation,
    run_price_to_book,
    run_psg,
    select_method,
)
from helpers.shares import compute_shares_outstanding
from data.custom_valuation_data import get_ticker_custom_valuation
from data.step2_data import get_step2_data
from helpers.ttm import TOTAL_QUARTERS_NEEDED, sum_last_four_quarters

logger = logging.getLogger(__name__)

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
            get_or_fetch(
                session,
                ticker,
                "income_statement",
                "annual",
                lambda: fmp_client.get_income_statement(ticker, "annual", 10),
                staleness_days,
                cache_only,
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
                cache_only,
            ),
        )
        cash_flow_annual = await safe_fetch(
            "cash_flow_statement_annual",
            get_or_fetch(
                session,
                ticker,
                "cash_flow_statement",
                "annual",
                lambda: fmp_client.get_cash_flow_statement(ticker, "annual", 10),
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
        # Same cache key Step 4/Step 5 already populate
        # ("balance_sheet_statement"/"quarterly", limit TOTAL_QUARTERS_NEEDED)
        # -- this call site only reads row 0 (latest quarter), per spec
        # gotcha #2 (latest instant, not FY-end).
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
        # New cache key: 10yr annual ratios history (P/B bands + latest
        # book/sales-per-share) -- distinct from ticker_summary.py's
        # "ratios"/"latest" key (limit=1), so the two never fight over the
        # same cache row despite both hitting /ratios.
        ratios_annual = await safe_fetch(
            "ratios_annual_10y",
            get_or_fetch(
                session,
                ticker,
                "ratios",
                "annual_10y",
                lambda: fmp_client.get_ratios(ticker, "annual", 10),
                staleness_days,
                cache_only,
            ),
        )
        # Risk-Free Rate and Market Risk Premium are both manual, human-
        # maintained settings (see /settings and CLAUDE.md) -- read inside
        # this session block since discount_rate_config.py's helper takes a
        # Session, not fetched from FMP like everything else above.
        discount_rate_row = get_discount_rate_config(session)

    income_annual = income_annual if isinstance(income_annual, list) else []
    income_quarterly = income_quarterly if isinstance(income_quarterly, list) else []
    cash_flow_annual = cash_flow_annual if isinstance(cash_flow_annual, list) else []
    cash_flow_quarterly = cash_flow_quarterly if isinstance(cash_flow_quarterly, list) else []
    balance_sheet_quarterly = balance_sheet_quarterly if isinstance(balance_sheet_quarterly, list) else []
    ratios_annual = ratios_annual if isinstance(ratios_annual, list) else []
    balance_sheet_latest = _first(balance_sheet_quarterly)

    company_type = classify_company_type(profile.get("sector"), profile.get("industry"), ticker)

    years, revenue_annual = _annual_series(income_annual, "revenue")
    _, net_income_annual = _annual_series(income_annual, "netIncome")

    cash_flow_by_year = {row.get("fiscalYear"): row for row in cash_flow_annual}
    cfo_annual = [cash_flow_by_year.get(year, {}).get("netCashProvidedByOperatingActivities") for year in years]
    # capitalExpenditure is already negative (cash outflow) in FMP's schema
    # -- FCF = CFO + capitalExpenditure, not CFO - capitalExpenditure.
    capex_annual = [cash_flow_by_year.get(year, {}).get("capitalExpenditure") for year in years]
    fcf_annual = [c + x if c is not None and x is not None else None for c, x in zip(cfo_annual, capex_annual)]

    revenue_ttm = sum_last_four_quarters(income_quarterly, "revenue").total
    net_income_ttm = sum_last_four_quarters(income_quarterly, "netIncome").total
    cfo_ttm = sum_last_four_quarters(cash_flow_quarterly, "netCashProvidedByOperatingActivities").total
    capex_ttm = sum_last_four_quarters(cash_flow_quarterly, "capitalExpenditure").total
    fcf_ttm = cfo_ttm + capex_ttm if cfo_ttm is not None and capex_ttm is not None else None

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

    cash_only = balance_sheet_latest.get("cashAndCashEquivalents")
    cash_incl_st_investments = balance_sheet_latest.get("cashAndShortTermInvestments")
    # FMP's standardized schema has no equity-vs-debt split within short-term
    # investments (confirmed by inspecting JPM/AAPL/GOOGL/MSFT payloads) --
    # so the spec's "include equity-security holdings?" toggle is
    # approximated as "cash only" vs "cash + all short-term investments"
    # (which may include equity positions, undifferentiated). Defaults to
    # the combined figure; Phase 3 exposes both for the user-visible toggle
    # the spec explicitly asks for.
    cash_and_st_investments = cash_incl_st_investments if cash_incl_st_investments is not None else cash_only

    shares_outstanding, shares_source = compute_shares_outstanding(quote, income_quarterly)

    beta = profile.get("beta")
    capm = None
    discount_rate = None
    if beta is not None:
        capm_result = compute_capm(discount_rate_row.risk_free_rate, discount_rate_row.market_risk_premium, beta)
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
        f"Step 2 analyst-estimate CAGR ({step2_out.basis} basis)" if step2_out.growth_rate is not None else None
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
    # user selects there -- see Step3CurrentValueCandidates.
    normalized_fcf_series = normalize_fcf(cfo_clean, capex_clean)
    current_value_by_source = {
        "cfo_ttm": cfo_ttm,
        "fcf_ttm": fcf_ttm,
        "fcf_normalized": normalized_fcf_series[-1] if normalized_fcf_series else None,
        "net_income_ttm": net_income_ttm,
        "net_income_smoothed": (
            sum(net_income_clean[-5:]) / len(net_income_clean[-5:]) if net_income_clean else None
        ),
    }
    current_value = current_value_by_source.get(selection.current_value_source) if selection.current_value_source else None
    current_value_candidates = Step3CurrentValueCandidates(**current_value_by_source)
    current_value_labels = {
        "cfo_ttm": "Operating Cash Flow (Current)",
        "fcf_ttm": "Free Cash Flow (Current)",
        "fcf_normalized": "Free Cash Flow (Normalized, 5yr avg CapEx)",
        "net_income_ttm": "Net Income (Current)",
        "net_income_smoothed": "Net Income (Smoothed, 5yr avg)",
    }
    current_value_label = current_value_labels.get(selection.current_value_source) if selection.current_value_source else None

    # P/B inputs. ratios_annual is most-recent-first (FMP's own order);
    # reversed to chronological (oldest first) since run_price_to_book's
    # "last N entries" convention means the N most recent, matching the
    # spec's own pseudocode -- also the natural left-to-right order for a
    # Phase 3 chart.
    pb_history = list(
        reversed([row.get("priceToBookRatio") for row in ratios_annual if row.get("priceToBookRatio") is not None])
    )
    pb_lookback = None
    if len(pb_history) >= PB_LOOKBACK_LONG:
        pb_lookback = f"{PB_LOOKBACK_LONG} years"
    elif len(pb_history) >= PB_LOOKBACK_SHORT:
        pb_lookback = f"{PB_LOOKBACK_SHORT} years"
    book_value_per_share = _first(ratios_annual).get("bookValuePerShare")

    # Computed unconditionally (not just when PRICE_TO_BOOK is the
    # auto-selected method) so Manual Calculation can pre-fill a real
    # mean/SD P/B pair regardless of which method the user selects there.
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
    dpu_series = list(reversed([row.get("dividendPerShare") for row in ratios_annual]))
    is_reit = company_type == "REIT/Property Developer"

    inputs = Step3Inputs(
        current_value=current_value,
        current_value_label=current_value_label,
        current_value_candidates=current_value_candidates,
        total_debt=debt_metrics.total_debt,
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
        fx_rate=1.0,
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
                fx_rate=inputs.fx_rate,
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
                fx_rate=inputs.fx_rate,
                last_close=inputs.last_close,
            )
            intrinsic_value_per_share = psg_result.intrinsic_value_per_share
            discount_premium_pct = psg_result.discount_premium_pct

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
        dividend_yield_meets_reit_threshold=dividend_yield_meets_reit_threshold(dividend_yield_pct) if is_reit else None,
        dpu_growth_note=dpu_growth_note(dpu_series) if is_reit else None,
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
        custom = get_ticker_custom_valuation(session, ticker.upper())
    if custom is None or not custom.is_active:
        return auto.model_copy(update={"valuation_source": "auto"})

    try:
        params = Step3ManualParams.model_validate_json(custom.parameters_json)
    except ValueError:
        # A future field rename hitting an old saved row without a data
        # migration must never 500 the whole ticker page -- fall back to
        # Auto, same as "no custom valuation saved at all".
        logger.warning("Failed to parse saved custom valuation parameters for %s -- falling back to Auto", ticker)
        return auto.model_copy(update={"valuation_source": "auto"})

    result = run_manual_calculation(
        method=custom.method,
        current_value=params.current_value,
        growth_yr_1_5=params.growth_yr_1_5,
        growth_yr_6_10=params.growth_yr_6_10,
        growth_yr_11_20=params.growth_yr_11_20,
        discount_rate=params.discount_rate,
        shares_outstanding=params.shares_outstanding,
        total_debt=params.total_debt,
        cash_and_st_investments=params.cash_and_st_investments,
        book_value_per_share=params.book_value_per_share,
        pb_mean_ratio=params.pb_mean_ratio,
        pb_sd_ratio=params.pb_sd_ratio,
        sales_per_share=params.sales_per_share,
        projected_growth_rate=params.projected_growth_rate,
        fair_psg_ratio=params.fair_psg_ratio,
        last_close=auto.inputs.last_close,
    )
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
