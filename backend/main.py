from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException

from db import init_db
from schemas import TickerSummaryOut
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
