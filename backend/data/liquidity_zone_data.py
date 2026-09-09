"""Orchestration layer for Liquidity Zone (LP) detection -- same
get_stepN_data shape as data/entry_signal_data.py: calls the pure
calculation engine (analysis/liquidity_zones/) and persists/reads the
result (models.py::LiquidityZoneAnalysis).

Unlike trend_analysis_data.py, there is no live-fetch path here: this
feature is scoped to the union of the "Main"/"Secondary" named watchlists
and refreshed only by the nightly cron job
(pipeline/nightly_liquidity_zone_calculation.py) -- get_liquidity_zone_data
below is a plain cache-only read, returning None for a ticker that was
never on either watchlist or hasn't been processed yet.
"""

import json
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import or_, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from analysis.liquidity_zones.engine import compute_liquidity_zones
from analysis.liquidity_zones.types import Zone
from analysis.trend_structure.weinstein import resample_to_weekly
from core.db import engine
from core.models import LiquidityZoneAnalysis, LiquidityZoneConfig
from core.schemas import LiquidityZoneOut, LiquidityZonesOut, ZoneOut
from core.tickers import normalize_ticker

# Sliced from the same fetched frame the Weekly timeframe resamples in
# full -- see clients/daily_price_sources.py's own LOOKBACK_YEARS comment
# for why a single ~4yr fetch serves both timeframes.
DAILY_LOOKBACK = pd.DateOffset(years=1)

# How long a row can go un-recomputed (e.g. its ticker dropped off both
# "Main" and "Secondary") before sweep_stale_liquidity_zones clears it.
STALE_AFTER_DAYS = 7

# support_zones_json/resistance_zones_json are NOT NULL columns, so
# sweep_stale_liquidity_zones clears them to this rather than NULL --
# semantically "no zones," already handled by _zones_from_json with zero
# changes there, and avoids a SQLite table-recreate just to relax a
# constraint.
_EMPTY_ZONES_JSON = "[]"


def _zones_to_json(zones: list[Zone]) -> str:
    return json.dumps([{"price": z.price, "cluster_size": z.cluster_size, "formed_at": z.formed_at.isoformat()} for z in zones])


def _zone_out(price: float, cluster_size: int, formed_at: date, last_price: float) -> ZoneOut:
    return ZoneOut(
        price=price,
        distance_pct=(price - last_price) / last_price * 100.0,
        cluster_size=cluster_size,
        formed_at=formed_at,
    )


def _zones_from_json(raw: str, last_price: float) -> list[ZoneOut]:
    payload = json.loads(raw)
    return [_zone_out(item["price"], item["cluster_size"], date.fromisoformat(item["formed_at"]), last_price) for item in payload]


def _row_to_out(row: LiquidityZoneAnalysis) -> LiquidityZoneOut:
    return LiquidityZoneOut(
        timeframe=row.timeframe,
        last_price=row.last_price,
        as_of=row.as_of,
        computed_at=row.computed_at,
        source=row.source,
        support_zones=_zones_from_json(row.support_zones_json, row.last_price),
        resistance_zones=_zones_from_json(row.resistance_zones_json, row.last_price),
    )


def compute_and_store_liquidity_zones(ticker: str, ohlcv: pd.DataFrame, source: str, config: LiquidityZoneConfig) -> None:
    """Runs the pure calculation engine against an already-fetched daily
    OHLC frame (see clients/daily_price_sources.py) and upserts both the
    Daily and Weekly rows -- no fetch of its own, so the nightly job's one
    fetch per ticker is shared across both timeframes' compute. Raises
    ValueError if `ohlcv` is empty -- callers (the nightly job's
    per-ticker loop) treat this like any other per-ticker failure."""
    ticker = normalize_ticker(ticker)
    if ohlcv.empty:
        raise ValueError(f"No daily OHLCV data available for {ticker}")

    daily_cutoff = ohlcv.index.max() - DAILY_LOOKBACK
    daily_df = ohlcv[ohlcv.index >= daily_cutoff]
    weekly_df = resample_to_weekly(ohlcv)

    daily_result = compute_liquidity_zones(daily_df, config.daily_swing_bars, config.daily_cluster_pct, config.daily_num_zones)
    weekly_result = compute_liquidity_zones(weekly_df, config.weekly_swing_bars, config.weekly_cluster_pct, config.weekly_num_zones)

    computed_at = datetime.now()
    with Session(engine) as session:
        for timeframe, result in (("daily", daily_result), ("weekly", weekly_result)):
            fields = {
                "last_price": result.last_price,
                "as_of": result.as_of,
                "support_zones_json": _zones_to_json(result.support),
                "resistance_zones_json": _zones_to_json(result.resistance),
                "source": source,
                "computed_at": computed_at,
            }
            stmt = sqlite_insert(LiquidityZoneAnalysis).values(ticker=ticker, timeframe=timeframe, **fields)
            stmt = stmt.on_conflict_do_update(index_elements=["ticker", "timeframe"], set_=fields)
            session.execute(stmt)
        session.commit()


def get_liquidity_zone_data(ticker: str) -> LiquidityZonesOut | None:
    """Cache-only read -- never triggers a live fetch (see module
    docstring). Returns None only if NEITHER timeframe has ever been
    computed for this ticker (not a "Main"/"Secondary" member, or the
    nightly job hasn't reached it yet)."""
    ticker = normalize_ticker(ticker)
    with Session(engine) as session:
        daily_row = session.get(LiquidityZoneAnalysis, (ticker, "daily"))
        weekly_row = session.get(LiquidityZoneAnalysis, (ticker, "weekly"))

    if daily_row is None and weekly_row is None:
        return None

    return LiquidityZonesOut(
        daily=_row_to_out(daily_row) if daily_row else None,
        weekly=_row_to_out(weekly_row) if weekly_row else None,
    )


def sweep_stale_liquidity_zones(now: datetime | None = None) -> int:
    """Clears (never deletes) any row whose computed_at is more than
    STALE_AFTER_DAYS old -- the case where a ticker has fallen off both
    "Main" and "Secondary" and so is no longer reached by the nightly
    job's per-ticker loop at all. Sets support_zones_json/
    resistance_zones_json to _EMPTY_ZONES_JSON ("no zones") rather than
    NULL, since both columns are NOT NULL and relaxing that would need a
    SQLite table recreate. last_price/as_of/source/computed_at are
    deliberately left untouched, standing as a "last known" breadcrumb
    (computed_at in particular is what the ticker-page card uses to show
    "computed on X, no longer tracked") rather than deleting the row
    outright, which would lose that breadcrumb for no real storage-cost
    benefit (this table is one row per ticker/timeframe, not an
    accumulating time series).

    Only rewrites rows that still have real zones to clear, so re-running
    this against an already-swept row is a cheap no-op, not a repeated
    write. Returns the number of rows cleared."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=STALE_AFTER_DAYS)
    with Session(engine) as session:
        stmt = (
            update(LiquidityZoneAnalysis)
            .where(
                LiquidityZoneAnalysis.computed_at < cutoff,
                or_(
                    LiquidityZoneAnalysis.support_zones_json != _EMPTY_ZONES_JSON,
                    LiquidityZoneAnalysis.resistance_zones_json != _EMPTY_ZONES_JSON,
                ),
            )
            .values(support_zones_json=_EMPTY_ZONES_JSON, resistance_zones_json=_EMPTY_ZONES_JSON)
        )
        result = session.execute(stmt)
        session.commit()
        return result.rowcount
