from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from sqlmodel import Session, select

from db import engine, init_db
from logging_config import apply_redaction_filters
from models import TickerScore
from recompute_ticker_scores import recompute_all
from refresh import clear_ticker_cache
from schemas import RecomputeSummary, RefreshResult, Step1Out, Step2Out, Step4Out, Step5Out, TickerScoreOut, TickerSummaryOut
from step1_data import get_step1_data
from step2_data import get_step2_data
from step4_data import get_step4_data
from step5_data import get_step5_data
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


@app.post("/api/tickers/{ticker}/refresh", response_model=RefreshResult)
async def ticker_refresh(ticker: str) -> RefreshResult:
    return clear_ticker_cache(ticker)


@app.get("/api/screener", response_model=list[TickerScoreOut])
def screener_list() -> list[TickerScoreOut]:
    with Session(engine) as session:
        rows = session.exec(select(TickerScore)).all()
    return [TickerScoreOut(**row.model_dump()) for row in rows]


@app.post("/api/screener/recompute", response_model=RecomputeSummary)
async def screener_recompute() -> RecomputeSummary:
    # recompute_all(), not recompute_ticker_scores.main() -- main() also
    # calls configure_logging()/init_db(), which would hijack this already-
    # running app's logging setup on every request (see that module's
    # docstring).
    summary = await recompute_all()
    return RecomputeSummary(**summary)
