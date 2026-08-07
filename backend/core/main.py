import json
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from sqlmodel import Session, func, select

from clients.alpha_vantage_client import AlphaVantageThrottled
from data.analyst_ratings_data import get_analyst_ratings_data
from helpers.bank_capital_metrics import get_ticker_bank_capital_metrics, set_ticker_bank_capital_metrics
from core.db import engine, init_db
from helpers.discount_rate_config import get_discount_rate_config, update_discount_rate_config
from core.logging_config import apply_redaction_filters
from data.moat import get_moat_score_config, get_ticker_moat, set_ticker_moat, update_moat_score_config
from core.models import IndexConstituent, SavedScreenerFilter, TickerCustomValuation, TickerScore, Watchlist
from data.news_data import get_news_data
from data.news_sentiment_data import get_news_sentiment_data
from pipeline.recompute_ticker_scores import recompute_all
from pipeline.refresh import clear_ticker_cache
from data.financials_data import get_financials_data
from data.ratios_data import get_ratios_data
from data.saved_screener_filters import delete_saved_filter, list_saved_filters, upsert_saved_filter
from data.segmentation_data import get_segmentation_data
from core.schemas import (
    AnalystRatingsOut,
    DiscountRateConfigIn,
    DiscountRateConfigOut,
    FinancialsOut,
    MoatScoreConfigIn,
    MoatScoreConfigOut,
    NewsOut,
    NewsSentimentOut,
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
    Step3ManualParams,
    Step3ManualRequest,
    Step3Out,
    Step3PBBands,
    Step4Out,
    Step5Out,
    TickerBankCapitalMetricsIn,
    TickerBankCapitalMetricsOut,
    TickerCustomValuationIn,
    TickerCustomValuationOut,
    TickerMoatIn,
    TickerMoatOut,
    TickerScoreOut,
    TickerSummaryOut,
    Universe,
    WatchlistBulkAddIn,
    WatchlistBulkAddOut,
    WatchlistIn,
    WatchlistOut,
    WatchlistRowOut,
    WatchlistTickerIn,
    WatchlistTickerOut,
    WatchlistUpdateIn,
)
from data.custom_valuation_data import (
    activate_ticker_custom_valuation,
    deactivate_ticker_custom_valuation,
    delete_ticker_custom_valuation,
    get_ticker_custom_valuation,
    parse_custom_valuation_params,
    run_manual_calculation_from_params,
    set_ticker_custom_valuation,
)
from data.step1_data import get_step1_data
from data.step2_data import get_step2_data
from scoring.step3 import run_manual_calculation
from data.step3_data import get_active_valuation, get_step3_data
from data.step4_data import get_step4_data
from data.step5_data import get_step5_data
from data.ticker_score import compute_ticker_score
from data.ticker_summary import get_summary
from data.watchlist_data import get_watchlist_rows
from data.watchlists import (
    add_watchlist_ticker,
    bulk_add_watchlist_tickers,
    count_net_new_tickers,
    create_watchlist,
    delete_watchlist,
    get_watchlist_by_name,
    get_watchlist_ticker,
    list_watchlist_tickers,
    list_watchlists,
    remove_watchlist_ticker,
    update_watchlist,
)

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
    # Always Auto Calculation, deliberately NOT get_active_valuation -- the
    # Valuation tab's "Model Valuation" card is a fixed Auto reference point
    # to compare a custom valuation against, and must never itself switch to
    # showing custom figures. The Custom Valuation panel gets the active
    # source separately, from GET /custom-valuation's own active_verdict
    # (which does go through get_active_valuation) -- see
    # main.py::_custom_valuation_out. The ticker header pill/Screener/
    # Watchlist still follow the active source via get_summary, unchanged.
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


async def _custom_valuation_out(ticker: str, row: TickerCustomValuation | None) -> TickerCustomValuationOut:
    # cache_only=True throughout -- same philosophy as update_ticker_moat/
    # update_ticker_bank_capital_metrics: a custom-valuation change must
    # never trigger a surprise FMP fetch.
    active = await get_active_valuation(ticker, cache_only=True)
    active_verdict = Step3ManualOut(
        intrinsic_value_per_share=active.intrinsic_value_per_share,
        pb_bands=active.pb_bands,
        discount_premium_pct=active.discount_premium_pct,
        verdict=active.verdict,
    )
    if row is None:
        return TickerCustomValuationOut(ticker=ticker, saved=False, active_verdict=active_verdict)
    # A corrupt parameters_json still returns saved=True/is_active/saved_at
    # (all real) with blank parameter fields, rather than 500ing the whole
    # panel load -- same fallback-to-safe convention as
    # get_active_valuation's own corrupt-JSON handling.
    params = parse_custom_valuation_params(row.parameters_json) or Step3ManualParams()
    return TickerCustomValuationOut(
        ticker=ticker,
        saved=True,
        method=row.method,
        is_active=row.is_active,
        saved_at=row.saved_at,
        active_verdict=active_verdict,
        **params.model_dump(),
    )


@app.get("/api/tickers/{ticker}/custom-valuation", response_model=TickerCustomValuationOut)
async def ticker_custom_valuation(ticker: str) -> TickerCustomValuationOut:
    ticker = ticker.upper()
    with Session(engine) as session:
        row = get_ticker_custom_valuation(session, ticker)
    return await _custom_valuation_out(ticker, row)


@app.put("/api/tickers/{ticker}/custom-valuation", response_model=TickerCustomValuationOut)
async def update_ticker_custom_valuation(ticker: str, body: TickerCustomValuationIn) -> TickerCustomValuationOut:
    ticker = ticker.upper()
    # Validate before persisting -- a user must never be able to save a
    # custom valuation that can't actually produce a verdict for the chosen
    # method (missing required inputs). cache_only=True: only last_close is
    # needed here, not a live refetch of every Auto input.
    auto = await get_step3_data(ticker, cache_only=True)
    params = Step3ManualParams(**body.model_dump(exclude={"method"}))
    validation = run_manual_calculation_from_params(body.method, params, auto.inputs.last_close)
    if validation.error:
        raise HTTPException(status_code=400, detail=validation.error)

    with Session(engine) as session:
        row = set_ticker_custom_valuation(session, ticker, body.method, params.model_dump_json())
        was_active = row.is_active
    # Never touches is_active (see set_ticker_custom_valuation's own
    # docstring) -- but if the row was already active, its live values just
    # changed, so the Screener/Watchlist's cached TickerScore row needs the
    # same on-demand recompute update_ticker_moat/update_ticker_bank_
    # capital_metrics already use. An inactive save has no live effect, so
    # no recompute is needed.
    if was_active:
        await compute_ticker_score(ticker, cache_only=True)
    return await _custom_valuation_out(ticker, row)


@app.post("/api/tickers/{ticker}/custom-valuation/activate", response_model=TickerCustomValuationOut)
async def activate_ticker_custom_valuation_endpoint(ticker: str) -> TickerCustomValuationOut:
    ticker = ticker.upper()
    with Session(engine) as session:
        row = activate_ticker_custom_valuation(session, ticker)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No custom valuation saved for {ticker} -- save one first")
    await compute_ticker_score(ticker, cache_only=True)
    return await _custom_valuation_out(ticker, row)


@app.post("/api/tickers/{ticker}/custom-valuation/deactivate", response_model=TickerCustomValuationOut)
async def deactivate_ticker_custom_valuation_endpoint(ticker: str) -> TickerCustomValuationOut:
    ticker = ticker.upper()
    with Session(engine) as session:
        row = deactivate_ticker_custom_valuation(session, ticker)
    # None means there was nothing to deactivate -- a no-op, nothing for
    # the Screener/Watchlist to recompute.
    if row is not None:
        await compute_ticker_score(ticker, cache_only=True)
    return await _custom_valuation_out(ticker, row)


@app.delete("/api/tickers/{ticker}/custom-valuation", status_code=204)
async def delete_ticker_custom_valuation_endpoint(ticker: str) -> None:
    ticker = ticker.upper()
    with Session(engine) as session:
        deleted = delete_ticker_custom_valuation(session, ticker)
    if deleted:
        # Reverts the ticker to Auto (get_active_valuation finds no row) as
        # a side effect of this same request -- Screener/Watchlist need the
        # same on-demand recompute as every other mutating endpoint here.
        await compute_ticker_score(ticker, cache_only=True)


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


@app.get("/api/tickers/{ticker}/news", response_model=NewsOut)
async def ticker_news(ticker: str) -> NewsOut:
    try:
        return await get_news_data(ticker)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="FMP request failed") from exc


@app.get("/api/tickers/{ticker}/news-sentiment", response_model=NewsSentimentOut)
async def ticker_news_sentiment(ticker: str) -> NewsSentimentOut:
    try:
        return await get_news_sentiment_data(ticker)
    except AlphaVantageThrottled as exc:
        # Not str(exc): AV's throttle message doesn't embed the API key,
        # but a static detail string keeps this consistent with the app's
        # existing policy (see the Step1 endpoint's own comment) of never
        # echoing a raw exception straight into a response body.
        raise HTTPException(status_code=503, detail="Alpha Vantage rate limit reached -- try again later") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Alpha Vantage request failed") from exc


@app.post("/api/tickers/{ticker}/refresh", response_model=RefreshResult)
async def ticker_refresh(ticker: str) -> RefreshResult:
    result = clear_ticker_cache(ticker)
    # cache_only=False (not the moat/CET1 endpoints' pattern below): the
    # cache was just cleared, so a cache_only read would see nothing and
    # silently skip writing a row (compute_ticker_score's own summary-is-
    # None early return). This forces the same live re-fetch the frontend's
    # subsequent GETs would trigger anyway, just synchronously here, so
    # TickerScore is never left stale after an explicit refresh the way it
    # used to be -- same motivation as update_ticker_moat/
    # update_ticker_bank_capital_metrics below, cache_only flipped because
    # there's no pre-existing warm cache to read yet.
    await compute_ticker_score(ticker, cache_only=False)
    return result


# The ticker header's Assessment chip's data source -- a cheap read of the
# same precomputed row Screener/Watchlist use, instead of the chip fetching
# /step1,2,4,5 individually and blending them client-side (the Analysis
# tab's OverallAssessmentCard still does that in full, for its live
# per-step breakdown; this endpoint is header-chip-only). No existing
# single-ticker TickerScore read path existed to reuse: Screener only has a
# universe-filtered list endpoint, and Watchlist doesn't read the stored
# row at all (compute_ticker_score(cache_only=True) live per row instead).
# Falls back to that same cache-only compute when no row exists yet
# (nightly job only covers S&P 500 + Dow -- see load_universe_tickers) so
# the chip still works on a ticker's very first view, mirroring Watchlist's
# own fallback rather than leaving the chip blank until a refresh/nightly
# run. Either path makes zero FMP calls.
@app.get("/api/tickers/{ticker}/score", response_model=TickerScoreOut | None)
async def ticker_score_out(ticker: str) -> TickerScoreOut | None:
    ticker = ticker.upper()
    with Session(engine) as session:
        row = session.get(TickerScore, ticker)
    if row is None:
        row = await compute_ticker_score(ticker, cache_only=True)
    return TickerScoreOut(**row.model_dump()) if row is not None else None


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


@app.get("/api/tickers/{ticker}/bank-capital-metrics", response_model=TickerBankCapitalMetricsOut)
def ticker_bank_capital_metrics(ticker: str) -> TickerBankCapitalMetricsOut:
    ticker = ticker.upper()
    with Session(engine) as session:
        row = get_ticker_bank_capital_metrics(session, ticker)
    if row is None:
        return TickerBankCapitalMetricsOut(
            ticker=ticker, cet1_ratio_pct=None, cet1_as_of=None, npl_ratio_pct=None, npl_as_of=None, updated_at=None
        )
    return TickerBankCapitalMetricsOut(**row.model_dump())


@app.put("/api/tickers/{ticker}/bank-capital-metrics", response_model=TickerBankCapitalMetricsOut)
async def update_ticker_bank_capital_metrics(ticker: str, body: TickerBankCapitalMetricsIn) -> TickerBankCapitalMetricsOut:
    ticker = ticker.upper()
    with Session(engine) as session:
        row = set_ticker_bank_capital_metrics(
            session, ticker, body.cet1_ratio_pct, body.cet1_as_of, body.npl_ratio_pct, body.npl_as_of
        )
    # cache_only=True -- same reasoning as update_ticker_moat: a CET1/NPL
    # change alone shouldn't trigger a surprise FMP fetch, just keep the
    # Screener's TickerScore row from going stale after an explicit user
    # action.
    await compute_ticker_score(ticker, cache_only=True)
    return TickerBankCapitalMetricsOut(**row.model_dump())


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


def _watchlist_out(row: Watchlist, tickers: list) -> WatchlistOut:
    return WatchlistOut(
        id=row.id,
        name=row.name,
        sort_field=row.sort_field,
        sort_direction=row.sort_direction,
        created_at=row.created_at,
        updated_at=row.updated_at,
        tickers=[WatchlistTickerOut(ticker=t.ticker, added_at=t.added_at) for t in tickers],
    )


@app.get("/api/watchlists", response_model=list[WatchlistOut])
def watchlists_list() -> list[WatchlistOut]:
    with Session(engine) as session:
        watchlists = list_watchlists(session)
        return [_watchlist_out(w, list_watchlist_tickers(session, w.id)) for w in watchlists]


@app.post("/api/watchlists", response_model=WatchlistOut, status_code=201)
def watchlists_create(body: WatchlistIn) -> WatchlistOut:
    with Session(engine) as session:
        if get_watchlist_by_name(session, body.name) is not None:
            raise HTTPException(status_code=409, detail=f"A watchlist named '{body.name}' already exists")
        row = create_watchlist(session, body.name)
        return _watchlist_out(row, [])


@app.put("/api/watchlists/{watchlist_id}", response_model=WatchlistOut)
def watchlists_update(watchlist_id: int, body: WatchlistUpdateIn) -> WatchlistOut:
    with Session(engine) as session:
        if body.name is not None:
            existing = get_watchlist_by_name(session, body.name)
            if existing is not None and existing.id != watchlist_id:
                raise HTTPException(status_code=409, detail=f"A watchlist named '{body.name}' already exists")
        row = update_watchlist(
            session, watchlist_id, name=body.name, sort_field=body.sort_field, sort_direction=body.sort_direction
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"No watchlist with id {watchlist_id}")
        return _watchlist_out(row, list_watchlist_tickers(session, watchlist_id))


@app.delete("/api/watchlists/{watchlist_id}", status_code=204)
def watchlists_delete(watchlist_id: int) -> None:
    with Session(engine) as session:
        deleted = delete_watchlist(session, watchlist_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No watchlist with id {watchlist_id}")


WATCHLIST_CAPACITY = 100


def _capacity_error(existing_count: int, net_new_count: int) -> HTTPException:
    total = existing_count + net_new_count
    return HTTPException(
        status_code=400,
        detail=(
            f"This watchlist has {existing_count}/{WATCHLIST_CAPACITY} tickers. Adding {net_new_count} new "
            f"ticker{'s' if net_new_count != 1 else ''} would bring it to {total}, over the {WATCHLIST_CAPACITY} cap."
        ),
    )


@app.post("/api/watchlists/{watchlist_id}/tickers", response_model=WatchlistTickerOut, status_code=201)
def watchlist_add_ticker(watchlist_id: int, body: WatchlistTickerIn) -> WatchlistTickerOut:
    ticker = body.ticker.upper()
    with Session(engine) as session:
        watchlist = session.get(Watchlist, watchlist_id)
        if watchlist is None:
            raise HTTPException(status_code=404, detail=f"No watchlist with id {watchlist_id}")
        if get_watchlist_ticker(session, watchlist_id, ticker) is not None:
            raise HTTPException(status_code=409, detail=f"{ticker} is already in this watchlist")
        # A watchlist can never hold more than WATCHLIST_CAPACITY tickers,
        # existing + incoming combined -- checked here too (not just the
        # bulk endpoint) so a watchlist sitting at exactly the cap correctly
        # refuses a single add as well.
        existing_count, net_new_count = count_net_new_tickers(session, watchlist_id, [ticker])
        if existing_count + net_new_count > WATCHLIST_CAPACITY:
            raise _capacity_error(existing_count, net_new_count)
        row = add_watchlist_ticker(session, watchlist_id, ticker)
        return WatchlistTickerOut(ticker=row.ticker, added_at=row.added_at)


@app.post("/api/watchlists/{watchlist_id}/tickers/bulk", response_model=WatchlistBulkAddOut)
def watchlist_bulk_add_tickers(watchlist_id: int, body: WatchlistBulkAddIn) -> WatchlistBulkAddOut:
    tickers = [t.upper() for t in body.tickers]
    with Session(engine) as session:
        watchlist = session.get(Watchlist, watchlist_id)
        if watchlist is None:
            raise HTTPException(status_code=404, detail=f"No watchlist with id {watchlist_id}")
        # Whole-operation rejection, not a partial fill: the capacity check
        # runs before any insert happens. Computed against net-new tickers
        # only (see count_net_new_tickers) -- re-adding tickers already in
        # the watchlist never counts against the cap.
        existing_count, net_new_count = count_net_new_tickers(session, watchlist_id, tickers)
        if existing_count + net_new_count > WATCHLIST_CAPACITY:
            raise _capacity_error(existing_count, net_new_count)
        added, already_present = bulk_add_watchlist_tickers(session, watchlist_id, tickers)
    return WatchlistBulkAddOut(added=added, already_present=already_present)


@app.delete("/api/watchlists/{watchlist_id}/tickers/{ticker}", status_code=204)
def watchlist_remove_ticker(watchlist_id: int, ticker: str) -> None:
    with Session(engine) as session:
        deleted = remove_watchlist_ticker(session, watchlist_id, ticker.upper())
    if not deleted:
        raise HTTPException(status_code=404, detail=f"{ticker.upper()} not found in watchlist {watchlist_id}")


@app.get("/api/watchlists/{watchlist_id}/rows", response_model=list[WatchlistRowOut])
async def watchlist_rows(watchlist_id: int) -> list[WatchlistRowOut]:
    with Session(engine) as session:
        watchlist = session.get(Watchlist, watchlist_id)
        if watchlist is None:
            raise HTTPException(status_code=404, detail=f"No watchlist with id {watchlist_id}")
        tickers = list_watchlist_tickers(session, watchlist_id)
    return await get_watchlist_rows(tickers)
