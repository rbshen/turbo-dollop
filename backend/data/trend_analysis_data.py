"""Orchestration layer for trend-structure analysis -- same get_stepN_data
shape as data/step4_data.py: fetches raw data (via clients/yahoo_cache.py),
calls the pure calculation engine (analysis/trend_structure/), and
persists/reads the result (models.py::TrendAnalysis). Independent of FMP
entirely -- Yahoo Finance is the sole data source for this feature.
"""

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from analysis.trend_structure.engine import compute_trend_structure
from analysis.trend_structure.types import SwingDetail, TrendStructureResult
from clients.yahoo_cache import get_or_fetch_price_history
from core.config import settings
from core.db import engine
from core.models import TrendAnalysis, YahooPriceCache
from core.schemas import SwingDetailOut, TrendAnalysisOut
from core.tickers import normalize_ticker


def _swing_detail_to_json(detail: SwingDetail | None) -> str | None:
    if detail is None:
        return None
    payload = asdict(detail)
    payload["date"] = detail.date.isoformat()
    return json.dumps(payload)


def _swing_detail_from_json(raw: str | None) -> SwingDetailOut | None:
    if raw is None:
        return None
    payload = json.loads(raw)
    return SwingDetailOut(
        date=date.fromisoformat(payload["date"]), price=payload["price"], margin=payload["margin"], atr=payload["atr"], ratio=payload["ratio"]
    )


def _swing_detail_out(detail: SwingDetail | None) -> SwingDetailOut | None:
    if detail is None:
        return None
    return SwingDetailOut(date=detail.date, price=detail.price, margin=detail.margin, atr=detail.atr, ratio=detail.ratio)


def _ohlcv_frame(rows: list[YahooPriceCache]) -> pd.DataFrame:
    data = {
        "open": [r.open for r in rows],
        "high": [r.high for r in rows],
        "low": [r.low for r in rows],
        "close": [r.close for r in rows],
        "volume": [r.volume for r in rows],
    }
    index = pd.DatetimeIndex([r.date for r in rows])
    return pd.DataFrame(data, index=index)


def _upsert(ticker: str, result: TrendStructureResult, computed_at: datetime) -> None:
    fields = {
        "computed_at": computed_at,
        "trend_state": result.trend_state,
        "magnitude_tier": result.magnitude_tier,
        "persistence_count": result.persistence_count,
        "bars_since_confirmation": result.bars_since_confirmation,
        "last_confirmed_swing_json": _swing_detail_to_json(result.last_confirmed_swing),
        "warning_flag": result.warning_flag,
        "warning_swing_json": _swing_detail_to_json(result.warning_swing),
        "efficiency_ratio": result.efficiency_ratio,
        "regime": result.regime,
        "blended_score": result.blended_score,
        "bar_level": result.bar_level,
    }
    with Session(engine) as session:
        stmt = sqlite_insert(TrendAnalysis).values(ticker=ticker, **fields)
        stmt = stmt.on_conflict_do_update(index_elements=["ticker"], set_=fields)
        session.execute(stmt)
        session.commit()


def _row_to_out(row: TrendAnalysis) -> TrendAnalysisOut:
    return TrendAnalysisOut(
        ticker=row.ticker,
        computed_at=row.computed_at,
        trend_state=row.trend_state,
        magnitude_tier=row.magnitude_tier,
        persistence_count=row.persistence_count,
        bars_since_confirmation=row.bars_since_confirmation,
        last_confirmed_swing=_swing_detail_from_json(row.last_confirmed_swing_json),
        warning_flag=row.warning_flag,
        warning_swing=_swing_detail_from_json(row.warning_swing_json),
        efficiency_ratio=row.efficiency_ratio,
        regime=row.regime,
        blended_score=row.blended_score,
        bar_level=row.bar_level,
    )


def compute_and_store_from_rows(ticker: str, rows: list[YahooPriceCache]) -> TrendAnalysisOut:
    """Runs the pure calculation engine against already-fetched OHLCV rows
    and upserts -- no fetch of its own. Split out from
    compute_and_store_trend_analysis so the nightly job (which fetches the
    whole universe in one yfinance batch call via
    clients.yahoo_cache.get_or_fetch_price_history_batch, per this
    feature's explicit "batch download, not one call per ticker"
    requirement) can reuse this same compute+upsert logic per ticker
    without each ticker triggering its own separate live fetch. Raises
    ValueError if `rows` is empty (no Yahoo data at all for this ticker) --
    callers (the nightly job's per-ticker loop) treat this like any other
    per-ticker failure, never aborting the whole batch."""
    ticker = normalize_ticker(ticker)
    if not rows:
        raise ValueError(f"No Yahoo Finance price history available for {ticker}")

    result = compute_trend_structure(_ohlcv_frame(rows))
    computed_at = datetime.now()
    _upsert(ticker, result, computed_at)

    return TrendAnalysisOut(
        ticker=ticker,
        computed_at=computed_at,
        trend_state=result.trend_state,
        magnitude_tier=result.magnitude_tier,
        persistence_count=result.persistence_count,
        bars_since_confirmation=result.bars_since_confirmation,
        last_confirmed_swing=_swing_detail_out(result.last_confirmed_swing),
        warning_flag=result.warning_flag,
        warning_swing=_swing_detail_out(result.warning_swing),
        efficiency_ratio=result.efficiency_ratio,
        regime=result.regime,
        blended_score=result.blended_score,
        bar_level=result.bar_level,
    )


async def compute_and_store_trend_analysis(ticker: str, period: str = "2y") -> TrendAnalysisOut:
    """Single-ticker fetch-then-compute-then-store -- used by the standalone
    API endpoint (a one-off, on-demand request), where fetching just this
    one ticker's history is the right cost, unlike the nightly job's
    whole-universe batch (see compute_and_store_from_rows above)."""
    ticker = normalize_ticker(ticker)
    rows = await get_or_fetch_price_history(ticker, period=period)
    return compute_and_store_from_rows(ticker, rows)


async def get_trend_analysis_data(ticker: str, cache_only: bool = False, period: str = "2y") -> TrendAnalysisOut | None:
    """cache_only=True (used by watchlist_data.py's bulk row compose) never
    triggers a live Yahoo fetch -- returns whatever's cached (even if
    stale), or None if this ticker has never been computed yet (the nightly
    cron hasn't reached it). cache_only=False (the standalone API endpoint)
    computes fresh on a missing/stale row."""
    ticker = normalize_ticker(ticker)
    with Session(engine) as session:
        row = session.exec(select(TrendAnalysis).where(TrendAnalysis.ticker == ticker)).first()

    is_stale = row is None or (datetime.now() - row.computed_at >= timedelta(days=settings.yahoo_price_cache_staleness_days))
    if cache_only or not is_stale:
        return _row_to_out(row) if row else None

    try:
        return await compute_and_store_trend_analysis(ticker, period=period)
    except ValueError:
        # No Yahoo Finance data at all for this ticker -- reads the same as
        # "not computed yet" to callers (falls back to a stale cached row if
        # one exists, same "stale is better than nothing" convention used
        # throughout this codebase).
        return _row_to_out(row) if row else None
