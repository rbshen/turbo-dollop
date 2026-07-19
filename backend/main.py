from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException

from db import init_db
from schemas import Step1Out, Step2Out, Step4Out, Step5Out, TickerSummaryOut
from step1_data import get_step1_data
from step2_data import get_step2_data
from step4_data import get_step4_data
from step5_data import get_step5_data
from ticker_summary import get_summary


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
        raise HTTPException(status_code=502, detail=f"FMP request failed: {exc}") from exc


@app.get("/api/tickers/{ticker}/step1", response_model=Step1Out)
async def ticker_step1(ticker: str) -> Step1Out:
    try:
        return await get_step1_data(ticker)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"FMP request failed: {exc}") from exc


@app.get("/api/tickers/{ticker}/step2", response_model=Step2Out)
async def ticker_step2(ticker: str) -> Step2Out:
    try:
        return await get_step2_data(ticker)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"FMP request failed: {exc}") from exc


@app.get("/api/tickers/{ticker}/step4", response_model=Step4Out)
async def ticker_step4(ticker: str) -> Step4Out:
    try:
        return await get_step4_data(ticker)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"FMP request failed: {exc}") from exc


@app.get("/api/tickers/{ticker}/step5", response_model=Step5Out)
async def ticker_step5(ticker: str) -> Step5Out:
    try:
        return await get_step5_data(ticker)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"FMP request failed: {exc}") from exc
