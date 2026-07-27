import json
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from sqlmodel import Session, func, select

from analyst_ratings_data import get_analyst_ratings_data
from db import engine, init_db
from discount_rate_config import get_discount_rate_config, update_discount_rate_config
from logging_config import apply_redaction_filters
from moat import get_moat_score_config, get_ticker_moat, set_ticker_moat, update_moat_score_config
from models import IndexConstituent, SavedScreenerFilter, TickerScore
from recompute_ticker_scores import recompute_all
from refresh import clear_ticker_cache
from financials_data import get_financials_data
from ratios_data import get_ratios_data
from saved_screener_filters import delete_saved_filter, list_saved_filters, upsert_saved_filter
from segmentation_data import get_segmentation_data
from schemas import (
    AnalystRatingsOut,
    DiscountRateConfigIn,
    DiscountRateConfigOut,
    FinancialsOut,
    MoatScoreConfigIn,
    MoatScoreConfigOut,
    RatiosOut,
    RecomputeSummary,
    RefreshResult,
    SavedScreenerFilterIn,
    SavedScreenerFilterOut,
    ScreenerMeta,
    SegmentationOut,
    Step1Out,
    Step2Out,
    Step3ManualOut,
    Step3ManualRequest,
    Step3Out,
    Step3PBBands,
    Step4Out,
    Step5Out,
    TickerMoatIn,
    TickerMoatOut,
    TickerScoreOut,
    TickerSummaryOut,
    Universe,
)
from step1_data import get_step1_data
from step2_data import get_step2_data
from scoring.step3 import run_manual_calculation
from step3_data import get_step3_data
from step4_data import get_step4_data
from step5_data import get_step5_data
from ticker_score import compute_ticker_score
from ticker_summary import get_summary

apply_redaction_filters()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Fathom", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/config/discount-rate", response_model=DiscountRateConfigOut)
def discount_rate_config() -> DiscountRateConfigOut:
    with Session(engine) as session:
        row = get_discount_rate_config(session)
    return DiscountRateConfigOut(**row.model_dump())


@app.put("/api/config/discount-rate", response_model=DiscountRateConfigOut)
def update_discount_rate(body: DiscountRateConfigIn) -> DiscountRateConfigOut:
    with Session(engine) as session:
        row = update_discount_rate_config(session, body.risk_free_rate, body.market_risk_premium)
    return DiscountRateConfigOut(**row.model_dump())


@app.get("/api/config/moat", response_model=MoatScoreConfigOut)
def moat_score_config() -> MoatScoreConfigOut:
    with Session(engine) as session:
        row = get_moat_score_config(session)
    return MoatScoreConfigOut(**row.model_dump())


@app.put("/api/config/moat", response_model=MoatScoreConfigOut)
def update_moat_score(body: MoatScoreConfigIn) -> MoatScoreConfigOut:
    with Session(engine) as session:
        row = update_moat_score_config(session, body.wide_moat_score, body.narrow_moat_score, body.no_moat_score)
    return MoatScoreConfigOut(**row.model_dump())


@app.get("/api/tickers/{ticker}/summary", response_model=TickerSummaryOut)
async def ticker_summary(ticker: str) -> TickerSummaryOut:
    try:
        return await get_summary(ticker)
    except httpx.HTTPError as exc:
        # Not f"...{exc}": httpx's exception message embeds the full request
        # URL, apikey included -- every FMP fetch site already goes through
        # cache.safe_fetch (which swallows httpx.HTTPError entirely), so
        # this branch is currently dead in practice, but a raw exc here
        # would leak the key into the response body the moment that stops
        # being true for some future call site.
        raise HTTPException(status_code=502, detail="FMP request failed") from exc


@app.get("/api/tickers/{ticker}/step1", response_model=Step1Out)
async def ticker_step1(ticker: str) -> Step1Out:
    try:
        return await get_step1_data(ticker)
    except httpx.HTTPError as exc:
        # Not f"...{exc}": httpx's exception message embeds the full request
        # URL, apikey included -- every FMP fetch site already goes through
        # cache.safe_fetch (which swallows httpx.HTTPError entirely), so
        # this branch is currently dead in practice, but a raw exc here
        # would leak the key into the response body the moment that stops
        # being true for some future call site.
        raise HTTPException(status_code=502, detail="FMP request failed") from exc


@app.get("/api/tickers/{ticker}/step2", response_model=Step2Out)
async def ticker_step2(ticker: str) -> Step2Out:
    try:
        return await get_step2_data(ticker)
    except httpx.HTTPError as exc:
        # Not f"...{exc}": httpx's exception message embeds the full request
        # URL, apikey included -- every FMP fetch site already goes through
        # cache.safe_fetch (which swallows httpx.HTTPError entirely), so
        # this branch is currently dead in practice, but a raw exc here
        # would leak the key into the response body the moment that stops
        # being true for some future call site.
        raise HTTPException(status_code=502, detail="FMP request failed") from exc


@app.get("/api/tickers/{ticker}/step3", response_model=Step3Out)
async def ticker_step3(ticker: str) -> Step3Out:
    try:
        return await get_step3_data(ticker)
    except httpx.HTTPError as exc:
        # Not f"...{exc}": httpx's exception message embeds the full request
        # URL, apikey included -- every FMP fetch site already goes through
        # cache.safe_fetch (which swallows httpx.HTTPError entirely), so
        # this branch is currently dead in practice, but a raw exc here
        # would leak the key into the response body the moment that stops
        # being true for some future call site.
        raise HTTPException(status_code=502, detail="FMP request failed") from exc


# `ticker` stays in the path for consistency with the rest of this endpoint
# family even though the calc itself is pure/ticker-agnostic -- see
# scoring.step3.run_manual_calculation's own docstring. No FMP/DB I/O here:
# `req.last_close` is supplied by the caller (already available from the
# live /step3 fetch the Manual Calculation panel seeds itself from).
@app.post("/api/tickers/{ticker}/step3/manual", response_model=Step3ManualOut)
async def ticker_step3_manual(ticker: str, req: Step3ManualRequest) -> Step3ManualOut:
    result = run_manual_calculation(
        method=req.method,
        current_value=req.current_value,
        growth_yr_1_5=req.growth_yr_1_5,
        growth_yr_6_10=req.growth_yr_6_10,
        growth_yr_11_20=req.growth_yr_11_20,
        discount_rate=req.discount_rate,
        shares_outstanding=req.shares_outstanding,
        total_debt=req.total_debt,
        cash_and_st_investments=req.cash_and_st_investments,
        book_value_per_share=req.book_value_per_share,
        pb_mean_ratio=req.pb_mean_ratio,
        pb_sd_ratio=req.pb_sd_ratio,
        sales_per_share=req.sales_per_share,
        projected_growth_rate=req.projected_growth_rate,
        fair_psg_ratio=req.fair_psg_ratio,
        last_close=req.last_close,
    )
    return Step3ManualOut(
        intrinsic_value_per_share=result.intrinsic_value_per_share,
        pb_bands=Step3PBBands(**result.pb_bands) if result.pb_bands else None,
        discount_premium_pct=result.discount_premium_pct,
        verdict=result.verdict,
        error=result.error,
    )


@app.get("/api/tickers/{ticker}/step4", response_model=Step4Out)
async def ticker_step4(ticker: str) -> Step4Out:
    try:
        return await get_step4_data(ticker)
    except httpx.HTTPError as exc:
        # Not f"...{exc}": httpx's exception message embeds the full request
        # URL, apikey included -- every FMP fetch site already goes through
        # cache.safe_fetch (which swallows httpx.HTTPError entirely), so
        # this branch is currently dead in practice, but a raw exc here
        # would leak the key into the response body the moment that stops
        # being true for some future call site.
        raise HTTPException(status_code=502, detail="FMP request failed") from exc


@app.get("/api/tickers/{ticker}/step5", response_model=Step5Out)
async def ticker_step5(ticker: str) -> Step5Out:
    try:
        return await get_step5_data(ticker)
    except httpx.HTTPError as exc:
        # Not f"...{exc}": httpx's exception message embeds the full request
        # URL, apikey included -- every FMP fetch site already goes through
        # cache.safe_fetch (which swallows httpx.HTTPError entirely), so
        # this branch is currently dead in practice, but a raw exc here
        # would leak the key into the response body the moment that stops
        # being true for some future call site.
        raise HTTPException(status_code=502, detail="FMP request failed") from exc


@app.get("/api/tickers/{ticker}/financials", response_model=FinancialsOut)
async def ticker_financials(ticker: str) -> FinancialsOut:
    try:
        return await get_financials_data(ticker)
    except httpx.HTTPError as exc:
        # Not f"...{exc}": httpx's exception message embeds the full request
        # URL, apikey included -- every FMP fetch site already goes through
        # cache.safe_fetch (which swallows httpx.HTTPError entirely), so
        # this branch is currently dead in practice, but a raw exc here
        # would leak the key into the response body the moment that stops
        # being true for some future call site.
        raise HTTPException(status_code=502, detail="FMP request failed") from exc


@app.get("/api/tickers/{ticker}/ratios", response_model=RatiosOut)
async def ticker_ratios(ticker: str) -> RatiosOut:
    try:
        return await get_ratios_data(ticker)
    except httpx.HTTPError as exc:
        # Not f"...{exc}": httpx's exception message embeds the full request
        # URL, apikey included -- every FMP fetch site already goes through
        # cache.safe_fetch (which swallows httpx.HTTPError entirely), so
        # this branch is currently dead in practice, but a raw exc here
        # would leak the key into the response body the moment that stops
        # being true for some future call site.
        raise HTTPException(status_code=502, detail="FMP request failed") from exc


@app.get("/api/tickers/{ticker}/segmentation", response_model=SegmentationOut)
async def ticker_segmentation(ticker: str) -> SegmentationOut:
    try:
        return await get_segmentation_data(ticker)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="FMP request failed") from exc


@app.get("/api/tickers/{ticker}/analyst-ratings", response_model=AnalystRatingsOut)
async def ticker_analyst_ratings(ticker: str) -> AnalystRatingsOut:
    try:
        return await get_analyst_ratings_data(ticker)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="FMP request failed") from exc


@app.post("/api/tickers/{ticker}/refresh", response_model=RefreshResult)
async def ticker_refresh(ticker: str) -> RefreshResult:
    return clear_ticker_cache(ticker)


@app.get("/api/tickers/{ticker}/moat", response_model=TickerMoatOut)
def ticker_moat(ticker: str) -> TickerMoatOut:
    ticker = ticker.upper()
    with Session(engine) as session:
        row = get_ticker_moat(session, ticker)
    if row is None:
        return TickerMoatOut(ticker=ticker, moat=None, updated_at=None)
    return TickerMoatOut(**row.model_dump())


@app.put("/api/tickers/{ticker}/moat", response_model=TickerMoatOut)
async def update_ticker_moat(ticker: str, body: TickerMoatIn) -> TickerMoatOut:
    ticker = ticker.upper()
    with Session(engine) as session:
        row = set_ticker_moat(session, ticker, body.moat)
    # cache_only=True -- a moat change alone shouldn't trigger a surprise FMP
    # fetch (same philosophy as recompute_ticker_scores.py); this just makes
    # sure the Screener's TickerScore row isn't left stale after an explicit
    # user action. No-op (returns None, skipped) if this ticker has never
    # been viewed and has no cached profile yet.
    await compute_ticker_score(ticker, cache_only=True)
    return TickerMoatOut(**row.model_dump())


@app.get("/api/screener", response_model=list[TickerScoreOut])
def screener_list(universe: Universe = "sp500") -> list[TickerScoreOut]:
    # Filtered to the selected universe's constituents -- TickerScore also
    # picks up rows for any ticker ever viewed individually (see
    # compute_ticker_score's other call sites), which must not leak into
    # a named-index list. universe="all" is the deliberate escape hatch for
    # that: every cached ticker, index member or not.
    with Session(engine) as session:
        if universe == "all":
            rows = session.exec(select(TickerScore)).all()
        else:
            universe_tickers = select(IndexConstituent.ticker).where(IndexConstituent.index_name == universe)
            rows = session.exec(select(TickerScore).where(TickerScore.ticker.in_(universe_tickers))).all()
    return [TickerScoreOut(**row.model_dump()) for row in rows]


@app.get("/api/screener/meta", response_model=ScreenerMeta)
def screener_meta(universe: Universe = "sp500") -> ScreenerMeta:
    # A ticker with no cached profile at all (e.g. BRK.B/BF.B's FMP 402) gets
    # no TickerScore row -- this lets the UI show an honest "X of Y" count
    # rather than silently presenting a partial list as complete. universe=
    # "all" has no such gap by definition (it IS the cached-ticker count),
    # so total_constituents there always equals screener_list's own length.
    with Session(engine) as session:
        if universe == "all":
            total_constituents = session.exec(select(func.count()).select_from(TickerScore)).one()
        else:
            total_constituents = session.exec(
                select(func.count()).select_from(IndexConstituent).where(IndexConstituent.index_name == universe)
            ).one()
    return ScreenerMeta(universe=universe, total_constituents=total_constituents)


@app.post("/api/screener/recompute", response_model=RecomputeSummary)
async def screener_recompute() -> RecomputeSummary:
    # recompute_all(), not recompute_ticker_scores.main() -- main() also
    # calls configure_logging()/init_db(), which would hijack this already-
    # running app's logging setup on every request (see that module's
    # docstring).
    summary = await recompute_all()
    return RecomputeSummary(**summary)


def _saved_filter_out(row: SavedScreenerFilter) -> SavedScreenerFilterOut:
    return SavedScreenerFilterOut(
        id=row.id,
        name=row.name,
        universe=row.universe,
        sort_field=row.sort_field,
        sort_direction=row.sort_direction,
        filters=json.loads(row.filters_json),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@app.get("/api/screener/filters", response_model=list[SavedScreenerFilterOut])
def screener_filters_list() -> list[SavedScreenerFilterOut]:
    with Session(engine) as session:
        rows = list_saved_filters(session)
    return [_saved_filter_out(row) for row in rows]


@app.put("/api/screener/filters/{name}", response_model=SavedScreenerFilterOut)
def screener_filters_upsert(name: str, body: SavedScreenerFilterIn) -> SavedScreenerFilterOut:
    with Session(engine) as session:
        row = upsert_saved_filter(
            session,
            name=name,
            universe=body.universe,
            sort_field=body.sort_field,
            sort_direction=body.sort_direction,
            filters_json=json.dumps(body.filters),
        )
    return _saved_filter_out(row)


@app.delete("/api/screener/filters/{name}", status_code=204)
def screener_filters_delete(name: str) -> None:
    with Session(engine) as session:
        deleted = delete_saved_filter(session, name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No saved filter named '{name}'")
