from sqlmodel import Session

from cache import get_or_fetch, safe_fetch
from config import settings
from db import engine
from debt_metrics import compute_debt_metrics
from discount_rate_config import get_discount_rate_config
from fmp_client import fmp_client
from schemas import Step3CapmComponents, Step3Inputs, Step3MethodStep, Step3Out, Step3PBBands
from scoring.classification import classify_company_type
from scoring.step3 import (
    classify_valuation_verdict,
    compute_capm,
    normalize_fcf,
    run_20yr_engine,
    run_price_to_book,
    run_psg,
    select_method,
)
from step2_data import get_step2_data
from ttm import TOTAL_QUARTERS_NEEDED, sum_last_four_quarters

# Workbook default (step6_intrinsic_value_calculation_prompt.md §4.1) --
# never automated, matches the source spreadsheet's own fallback.
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


def _first(data: dict | list) -> dict:
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def _annual_series(annual_rows: list[dict], field: str) -> tuple[list[str], list[float | None]]:
    # FMP returns annual rows most-recent-first; reverse to chronological
    # (oldest fiscal year first) -- same idiom as step1_data.py/step4_data.py.
    rows = list(reversed(annual_rows))
    years = [row.get("fiscalYear", row.get("date", "")[:4]) for row in rows]
    values = [row.get(field) for row in rows]
    return years, values


def _shares_outstanding(quote: dict, income_quarterly: list[dict]) -> tuple[float | None, str | None]:
    """Prefers marketCap/price (both instant quote-level figures, per spec
    gotcha #2's "most recent instant" rule) over the income statement's
    weightedAverageShsOutDil, which is a period-average flow figure, not an
    instant share count -- used only as a fallback when quote data is
    incomplete."""
    market_cap, price = quote.get("marketCap"), quote.get("price")
    if market_cap and price:
        return market_cap / price, "marketCap / price (latest quote)"
    latest_quarter = _first(income_quarterly)
    shares = latest_quarter.get("weightedAverageShsOutDil")
    if shares:
        return shares, "weightedAverageShsOutDil (latest quarter, diluted)"
    return None, None


async def get_step3_data(
    ticker: str,
    cache_only: bool = False,
    growth_yr_1_5_override: float | None = None,
    growth_yr_6_10_override: float | None = None,
    growth_yr_11_20_override: float | None = None,
) -> Step3Out:
    """`cache_only=True` (used by ticker_score.py's recompute path) reads
    only whatever's already cached and never calls FMP -- see
    cache.get_or_fetch's own cache_only branch.

    `growth_yr_*_override` (decimal fractions, e.g. 0.15 for 15%) let the
    Phase 3 UI recompute with user-edited growth rates -- when given, they
    replace the computed defaults in `inputs` itself (so what's displayed
    always matches what fed the engine) without any new FMP fetch, keeping
    the math in exactly one place instead of duplicating it in TypeScript."""
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

    company_type = classify_company_type(profile.get("sector"), profile.get("industry"))

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

    shares_outstanding, shares_source = _shares_outstanding(quote, income_quarterly)

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

    step2_out = await get_step2_data(ticker, cache_only)
    growth_yr_1_5 = step2_out.growth_rate / 100 if step2_out.growth_rate is not None else None
    growth_yr_1_5_source = (
        f"Step 2 analyst-estimate CAGR ({step2_out.basis} basis)" if step2_out.growth_rate is not None else None
    )
    # Yr 6-10 defaults to Yr 1-5, but capped at 15% when Yr 1-5 itself runs
    # hotter than that -- an unmoderated 5yr analyst-estimate growth rate
    # (e.g. 40%+ for a high-growth name) isn't a credible assumption to
    # silently carry into years 6-10 too. Default only: a user's own
    # override below is never clamped, matching this feature's "editable,
    # not silently fixed" growth-rate convention.
    growth_yr_6_10 = min(growth_yr_1_5, GROWTH_YR_6_10_CAP) if growth_yr_1_5 is not None else None
    growth_yr_11_20 = TERMINAL_GROWTH_RATE_DEFAULT
    if growth_yr_1_5_override is not None:
        growth_yr_1_5 = growth_yr_1_5_override
    if growth_yr_6_10_override is not None:
        growth_yr_6_10 = growth_yr_6_10_override
    if growth_yr_11_20_override is not None:
        growth_yr_11_20 = growth_yr_11_20_override

    current_fiscal_year = years[-1] if years else None

    normalized_fcf_series = normalize_fcf(cfo_clean, capex_clean) if selection.current_value_source == "fcf_normalized" else None
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

    # PSG inputs.
    sales_per_share = _first(ratios_annual).get("revenuePerShare")

    inputs = Step3Inputs(
        current_value=current_value,
        current_value_label=current_value_label,
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
        if inputs.book_value_per_share is not None and inputs.pb_lookback is not None:
            pb_result = run_price_to_book(
                book_value_per_share=inputs.book_value_per_share,
                historical_pb_ratios=inputs.historical_pb_ratios,
                lookback=inputs.pb_lookback,
                fx_rate=inputs.fx_rate,
                last_close=inputs.last_close,
            )
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
        inputs=inputs,
        intrinsic_value_per_share=intrinsic_value_per_share,
        pb_bands=pb_bands,
        discount_premium_pct=discount_premium_pct,
        verdict=classify_valuation_verdict(discount_premium_pct),
    )
