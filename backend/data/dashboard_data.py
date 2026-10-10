"""The Dashboard tab's one read (docs/specs/dashboard.md): the five scored steps with the series a small visual needs, the
price / fair-value block and the Weinstein stage series. Cache only: no FMP call and nothing written, built the way
`compute_ticker_score` calls the steps (`cache_only=True`) plus the cached daily bars.

Presentation only. Every score and verdict is the step function's own result (the stored TickerScore words ride alongside), every
threshold is read from the scoring modules' constants, and the Weinstein series is the production engine run on the cached bars with
the live Weinstein settings. The verdict strip (Overall, Valuation, Weinstein stage, 5Y vs SPY) and the "Why might it be stuck?" card
are NOT sourced here: the first reuses the header's hooks, the second has its own endpoint.
"""

import logging

import pandas as pd
from sqlmodel import Session

from analysis.trend_structure.weinstein import compute_stage_series, resample_to_weekly
from analysis.trend_structure.weinstein import _stage_since
from clients.shared_bars_cache import read_cached_daily_bars_batch
from core.db import engine
from core.models import MoatScoreConfig, TickerScore
from core.schemas import (
    DashboardDebtOut,
    DashboardDebtRatioOut,
    DashboardFairValueOut,
    DashboardFinancialsOut,
    DashboardGrowthOut,
    DashboardMoatOut,
    DashboardOut,
    DashboardPricePointOut,
    DashboardProfitabilityOut,
    DashboardRatioSeriesOut,
    DashboardStageWeekOut,
    DashboardTierCutoffsOut,
    DashboardWeinsteinOut,
    DashboardYearsOut,
    ScoredRatioOut,
    Step1Out,
    Step2Out,
    Step4Out,
    Step5Out,
    TickerSummaryOut,
)
from core.tickers import normalize_ticker
from data.last_close_data import get_cached_last_close
from data.moat import CONFIG_KEY as MOAT_CONFIG_KEY, get_ticker_moat, resolve_moat_multiplier
from data.score_weights import load_score_weights
from data.step1_data import get_step1_data
from data.step2_data import get_step2_data
from data.step3_data import get_active_valuation
from data.step4_data import get_step4_data
from data.step5_data import get_step5_data
from data.stuck_check_data import _cached_rows
from data.ticker_score import _safe_step
from data.ticker_summary import get_summary
from data.trend_analysis_data import WEINSTEIN_LOOKBACK_DAYS
from helpers.weinstein_config import load_weinstein_params
from scoring.classification import classify_company_type
from scoring.step2 import MAGNITUDE_HIGH, MAGNITUDE_MODEST, MAGNITUDE_SOLID
from scoring.step3 import VALUATION_OVERVALUED_THRESHOLD, VALUATION_UNDERVALUED_THRESHOLD
from scoring.step4 import ROE_EXCELLENT_AVG, ROE_GOOD_AVG, ROE_MARGINAL_AVG, ROE_MIN_YEAR_CONSISTENCY
from scoring.step5 import (
    CET1_FLOOR_PCT,
    CURRENT_RATIO_COMFORTABLE,
    CURRENT_RATIO_SEVERE,
    DEBT_EBITDA_COMFORTABLE,
    DEBT_EBITDA_SEVERE,
    DSR_COMFORTABLE,
    DSR_SEVERE,
    GEARING_LIMIT_PCT,
    NPL_LIMIT_PCT,
)

logger = logging.getLogger(__name__)

CHART_YEARS = 5  # completed fiscal years shown in the Financials and Profitability visuals
PRICE_LOOKBACK_DAYS = 5 * 365 + 10
PRICE_FULL_SPAN_YEARS = 4.5  # a series reaching back at least this far is labelled "5-year"
STAGE_WEEKS = 52  # ~12 months of weekly stage points


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _last_completed(years: list[str], *series: list) -> tuple[list[str], list[list]]:
    """The newest CHART_YEARS completed fiscal years (a trailing "TTM" slot and the "—" pad slots dropped), series aligned."""
    keep = [i for i, y in enumerate(years) if y not in ("TTM", "—")][-CHART_YEARS:]
    return [years[i] for i in keep], [[s[i] if i < len(s) else None for i in keep] for s in series]


def _head(step, stored_score: int | None, stored_verdict: str | None) -> dict:
    return {
        "score": step.score if step is not None else None,
        "verdict": step.verdict if step is not None else None,
        "stored_score": stored_score,
        "stored_verdict": stored_verdict,
    }


# --- per-step blocks ---------------------------------------------------------------------------------------------------------


def financials_block(step1: Step1Out | None, head: dict) -> DashboardFinancialsOut:
    if step1 is None:
        return DashboardFinancialsOut(**head)
    years, (revenue, net_income, cfo) = _last_completed(step1.years, step1.revenue, step1.net_income, step1.cfo or [])
    # Bank / Insurance / REIT / Commodity: Revenue and Net Income only (Step 1's exemption); Standard and Utility score CFO too.
    return DashboardFinancialsOut(
        **head,
        available=bool(years),
        scored_cfo=step1.cfo_exempt_reason is None,
        cfo_exempt_reason=step1.cfo_exempt_reason,
        series=DashboardYearsOut(years=years, revenue=revenue, net_income=net_income, cfo=cfo),
    )


GROWTH_BANDS = [MAGNITUDE_MODEST, MAGNITUDE_SOLID, MAGNITUDE_HIGH]


def growth_block(step2: Step2Out | None, head: dict) -> DashboardGrowthOut:
    if step2 is None:
        return DashboardGrowthOut(**head, bands=GROWTH_BANDS)
    return DashboardGrowthOut(
        **head,
        bands=GROWTH_BANDS,
        available=step2.growth_rate is not None,
        growth_rate=step2.growth_rate,
        target_analyst_count=step2.target_analyst_count,
        basis=step2.basis,
        base_fiscal_year=step2.base_fiscal_year,
        target_fiscal_year=step2.target_fiscal_year,
    )


def weekly_price_series(close: pd.Series) -> list[DashboardPricePointOut]:
    """The last daily close of each week, with its real date (not the week-end label)."""
    close = close.dropna()
    if close.empty:
        return []
    last_of_week = close.groupby(close.index.to_period("W-FRI")).tail(1)
    return [DashboardPricePointOut(day=idx.date(), close=float(value)) for idx, value in last_of_week.items()]


def moat_block(session: Session, ticker: str, bars: pd.DataFrame | None) -> DashboardMoatOut:
    ticker_moat = get_ticker_moat(session, ticker)
    moat = ticker_moat.moat if ticker_moat is not None else None
    multiplier = resolve_moat_multiplier(session.get(MoatScoreConfig, MOAT_CONFIG_KEY), moat)
    out = DashboardMoatOut(moat=moat, rated=moat is not None, multiplier=multiplier)
    if bars is None or bars.empty:
        out.price_unavailable_reason = "No cached daily bars"
        return out
    out.price_series = weekly_price_series(bars["close"])
    if len(out.price_series) < 2:
        out.price_series = []
        out.price_unavailable_reason = "Too few cached daily bars"
        return out
    span = (out.price_series[-1].day - out.price_series[0].day).days / 365.25
    out.price_years_covered = round(span, 2)
    out.price_label = "5-year price" if span >= PRICE_FULL_SPAN_YEARS else f"{span:.1f}-year price (all the history cached)"
    return out


def _ratio_series(years: list[str], values: list[float | None], scored: ScoredRatioOut | None) -> DashboardRatioSeriesOut:
    ys, (vs,) = _last_completed(years, values)
    return DashboardRatioSeriesOut(years=ys, values=vs, scored=scored)


def profitability_block(step4: Step4Out | None, head: dict) -> DashboardProfitabilityOut:
    if step4 is None:
        return DashboardProfitabilityOut(**head)
    roe = _ratio_series(step4.years, step4.roe, step4.roe_scored)
    if step4.roic is None:
        roic = DashboardRatioSeriesOut(exempt_reason=step4.roic_exempt_reason or "ROIC does not apply to this company type")
    else:
        roic = _ratio_series(step4.years, step4.roic, step4.roic_scored)
    return DashboardProfitabilityOut(
        **head,
        available=True,
        roe=roe,
        roic=roic,
        cutoffs=DashboardTierCutoffsOut(
            excellent=ROE_EXCELLENT_AVG, good=ROE_GOOD_AVG, marginal=ROE_MARGINAL_AVG, min_year=ROE_MIN_YEAR_CONSISTENCY
        ),
    )


def _ratio(step5: Step5Out, key: str, label: str, unit: str, direction: str, pass_line: float, hard_limit: float, value=None) -> DashboardDebtRatioOut:
    result = step5.ratios.get(key)
    return DashboardDebtRatioOut(
        key=key,
        label=label,
        unit=unit,
        direction=direction,
        value=result.value if result is not None else value,
        adjusted_value=result.adjusted_value if result is not None and result.adjusted_value != result.value else None,
        tier=result.label if result is not None else None,
        points=result.points if result is not None else None,
        excluded=result is not None and result.label == "excluded_negative_cfo",
        note=result.note if result is not None else None,
        pass_line=pass_line,
        hard_limit=hard_limit,
    )


def debt_block(step5: Step5Out | None, head: dict) -> DashboardDebtOut:
    if step5 is None:
        return DashboardDebtOut(**head)
    company_type = step5.company_type
    base = dict(
        **head,
        available=True,
        unrescued_breaches=step5.unrescued_breaches,
        pass_with_caution=step5.pass_with_caution,
    )
    if company_type == "Insurance":
        return DashboardDebtOut(**base, status="not_applicable", status_reason="Debt is not applied to insurers")
    if company_type == "ETF":
        return DashboardDebtOut(**base, status="not_applicable", status_reason="Stocks only")
    if company_type == "Bank":
        if not step5.bank_capital_metrics_editable:
            return DashboardDebtOut(**base, status="not_applicable", status_reason=step5.classification_note)
        ratios = [
            _ratio(step5, "cet1_ratio", "CET1 ratio", "pct", "floor", CET1_FLOOR_PCT, CET1_FLOOR_PCT, value=step5.cet1_ratio_pct),
            _ratio(step5, "npl_ratio", "NPL ratio", "pct", "ceiling", NPL_LIMIT_PCT, NPL_LIMIT_PCT),
        ]
        complete = step5.score is not None
        return DashboardDebtOut(
            **base,
            status="scored" if complete else "partial",
            status_reason=None if complete else "CET1 and NPL are both needed for a score",
            ratios=ratios,
        )
    if company_type == "REIT/Property Developer":
        if step5.verdict == "insufficient_data":
            return DashboardDebtOut(**base, status="insufficient_data")
        return DashboardDebtOut(
            **base,
            status="scored",
            ratios=[_ratio(step5, "gearing_ratio", "Gearing", "pct", "ceiling", GEARING_LIMIT_PCT, GEARING_LIMIT_PCT)],
        )
    if not step5.ratios:
        return DashboardDebtOut(**base, status="insufficient_data")
    return DashboardDebtOut(
        **base,
        status="scored",
        ratios=[
            _ratio(step5, "current_ratio", "Current ratio", "x", "floor", CURRENT_RATIO_COMFORTABLE, CURRENT_RATIO_SEVERE),
            _ratio(step5, "debt_to_ebitda", "Debt / EBITDA", "x", "ceiling", DEBT_EBITDA_COMFORTABLE, DEBT_EBITDA_SEVERE),
            _ratio(step5, "debt_servicing_ratio", "Debt servicing", "pct", "ceiling", DSR_COMFORTABLE, DSR_SEVERE),
        ],
    )


# --- price and valuation -----------------------------------------------------------------------------------------------------

BAND_LOW = round(1 + VALUATION_UNDERVALUED_THRESHOLD, 6)  # price at or under 0.9x fair value reads undervalued
BAND_HIGH = round(1 + VALUATION_OVERVALUED_THRESHOLD, 6)  # price at or over 1.1x reads overvalued


async def fair_value_block(ticker: str, summary: TickerSummaryOut | None) -> DashboardFairValueOut:
    out = DashboardFairValueOut(band_low=BAND_LOW, band_high=BAND_HIGH)
    if summary is None:
        out.unavailable_reason = "not_scored"
        return out
    out.currency = summary.quote_currency or "USD"
    price = summary.price
    if not price:
        cached_close = get_cached_last_close(ticker)
        price = cached_close[0] if cached_close is not None else None
    out.price = price
    out.fair_value_price = summary.fair_value_price
    out.verdict = summary.fair_value_verdict
    out.method = summary.fair_value_method
    out.source = summary.valuation_source
    if summary.fair_value_price:
        out.available = True
        if price:
            out.discount_premium_pct = (price / summary.fair_value_price - 1) * 100
        else:
            out.unavailable_reason = "no_price"
        return out
    # No fair value: say why, from the valuation result the header pill is built on (cache only).
    step3, _error = await _safe_step(ticker, "step3", get_active_valuation(ticker, cache_only=True))
    if step3 is not None and step3.selected_method == "PASS":
        out.unavailable_reason = "insufficient_data" if step3.insufficient_data else "pass_method"
        out.unavailable_detail = step3.pass_reason
    elif not price:
        out.unavailable_reason = "no_price"
    else:
        out.unavailable_reason = "not_scored"
    return out


def weinstein_block(session: Session, bars: pd.DataFrame | None) -> DashboardWeinsteinOut:
    """Per-week stage for the last ~12 months from the production engine on the cached daily bars and the live Weinstein settings."""
    params = load_weinstein_params(session)
    out = DashboardWeinsteinOut(weeks_required=params.min_weeks_required, ma_label=f"{params.ma_type.upper()}{params.ma_length}")
    if bars is None or bars.empty:
        out.unavailable_reason = "No cached daily bars"
        return out
    weekly = resample_to_weekly(bars)
    out.weeks_available = len(weekly)
    if out.weeks_available < out.weeks_required:
        out.unavailable_reason = f"Fewer than {out.weeks_required} weeks of cached history"
        return out
    stage_df = compute_stage_series(weekly["close"], params)
    since, lower_bound = _stage_since(stage_df["stage"])
    out.available = True
    out.stage = stage_df["stage"].iloc[-1]
    out.since_date, out.since_is_lower_bound = since, lower_bound
    out.weeks = [
        DashboardStageWeekOut(week=idx.date(), stage=stage if isinstance(stage, str) else None)
        for idx, stage in stage_df["stage"].iloc[-STAGE_WEEKS:].items()
    ]
    return out


# --- the endpoint's read -----------------------------------------------------------------------------------------------------


async def get_dashboard_data(ticker: str) -> DashboardOut:
    """Cache only: reads `FundamentalsCache`, `TickerScore`, `SharedBarsCache` and the manual Moat rating; never fetches or writes."""
    ticker = normalize_ticker(ticker)
    with Session(engine) as session:
        profile_rows = _cached_rows(session, ticker, "profile", "latest")
        profile = profile_rows[0] if profile_rows else {}
        score = session.get(TickerScore, ticker)
    if profile.get("isEtf") or profile.get("isFund") or (score is not None and score.is_etf):
        return DashboardOut(ticker=ticker, applicable=False, not_applicable_reason="Stocks only", has_data=False)
    if not profile and score is None:
        return DashboardOut(ticker=ticker, has_data=False)

    weights = load_score_weights(engine).weights
    step1, _ = await _safe_step(ticker, "step1", get_step1_data(ticker, cache_only=True, weights=weights))
    step2, _ = await _safe_step(ticker, "step2", get_step2_data(ticker, cache_only=True, weights=weights))
    step4, _ = await _safe_step(ticker, "step4", get_step4_data(ticker, cache_only=True, weights=weights))
    step5, _ = await _safe_step(ticker, "step5", get_step5_data(ticker, cache_only=True, weights=weights))
    summary, _ = await _safe_step(ticker, "summary", get_summary(ticker, cache_only=True))

    def stored(prefix: str) -> tuple[int | None, str | None]:
        return (getattr(score, f"{prefix}_score"), getattr(score, f"{prefix}_verdict")) if score is not None else (None, None)

    company_type = (
        (step4.company_type if step4 else None)
        or (step5.company_type if step5 else None)
        or classify_company_type(profile.get("sector"), profile.get("industry"), ticker)
    )

    frames = read_cached_daily_bars_batch([ticker], WEINSTEIN_LOOKBACK_DAYS)
    bars = frames.get(ticker)
    with Session(engine) as session:
        moat = moat_block(session, ticker, bars)
        weinstein = weinstein_block(session, bars)

    return DashboardOut(
        ticker=ticker,
        company_type=company_type,
        currency=(summary.reported_currency if summary else None) or "USD",
        financials=financials_block(step1, _head(step1, *stored("step1"))),
        growth=growth_block(step2, _head(step2, *stored("step2"))),
        moat=moat,
        profitability=profitability_block(step4, _head(step4, *stored("step4"))),
        debt=debt_block(step5, _head(step5, *stored("step5"))),
        fair_value=await fair_value_block(ticker, summary),
        weinstein=weinstein,
    )
