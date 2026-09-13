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
from analysis.trend_structure.types import PullbackCycle, ReversalCandidate, SwingDetail, TrendStructureResult, WeinsteinStageResult
from analysis.trend_structure.weinstein import WEINSTEIN_BENCHMARK_TICKER, compute_weinstein_stage
from clients.yahoo_cache import get_or_fetch_price_history
from core.config import settings
from core.db import engine
from core.models import TrendAnalysis, YahooPriceCache
from core.schemas import PullbackCycleOut, ReversalCandidateOut, SwingDetailOut, TrendAnalysisOut
from core.tickers import normalize_ticker


def _swing_detail_to_json(detail: SwingDetail | None) -> str | None:
    if detail is None:
        return None
    payload = asdict(detail)
    payload["date"] = detail.date.isoformat()
    return json.dumps(payload)


def _swing_detail_dict_to_out(payload: dict) -> SwingDetailOut:
    return SwingDetailOut(
        date=date.fromisoformat(payload["date"]),
        price=payload["price"],
        margin=payload["margin"],
        atr=payload["atr"],
        ratio=payload["ratio"],
        # .get(), not [...]: a row computed before this field existed has no
        # "classification" key in its stored JSON at all -- reads as None
        # until the next nightly run rewrites it (see SwingDetailOut's own
        # comment).
        classification=payload.get("classification"),
    )


def _swing_detail_from_json(raw: str | None) -> SwingDetailOut | None:
    if raw is None:
        return None
    return _swing_detail_dict_to_out(json.loads(raw))


def _swing_detail_out(detail: SwingDetail | None) -> SwingDetailOut | None:
    if detail is None:
        return None
    return SwingDetailOut(
        date=detail.date, price=detail.price, margin=detail.margin, atr=detail.atr, ratio=detail.ratio, classification=detail.classification
    )


def _pullback_history_to_json(history: list[PullbackCycle]) -> str:
    payload = [
        {
            "warning_swing": {**asdict(cycle.warning_swing), "date": cycle.warning_swing.date.isoformat()},
            "resolving_swing": {**asdict(cycle.resolving_swing), "date": cycle.resolving_swing.date.isoformat()},
        }
        for cycle in history
    ]
    return json.dumps(payload)


def _pullback_history_from_json(raw: str | None) -> list[PullbackCycleOut]:
    # [] (not None) for a pre-existing row computed before this field
    # existed -- see models.py::TrendAnalysis.pullback_history_json's own
    # comment on why an empty list, not a nullable field, is the right
    # migration-safety shape here.
    if raw is None:
        return []
    return [
        PullbackCycleOut(
            warning_swing=_swing_detail_dict_to_out(entry["warning_swing"]),
            resolving_swing=_swing_detail_dict_to_out(entry["resolving_swing"]),
        )
        for entry in json.loads(raw)
    ]


def _pullback_history_out(history: list[PullbackCycle]) -> list[PullbackCycleOut]:
    return [
        PullbackCycleOut(
            warning_swing=_swing_detail_out(cycle.warning_swing),
            resolving_swing=_swing_detail_out(cycle.resolving_swing),
        )
        for cycle in history
    ]


def _reversal_history_to_json(history: list[ReversalCandidate]) -> str:
    payload = [
        {
            "swing": {**asdict(candidate.swing), "date": candidate.swing.date.isoformat()},
            "ad_bullish_divergence": candidate.ad_bullish_divergence,
            "ad_divergence_swing_date": candidate.ad_divergence_swing_date.isoformat() if candidate.ad_divergence_swing_date else None,
        }
        for candidate in history
    ]
    return json.dumps(payload)


def _reversal_history_from_json(raw: str | None) -> list[ReversalCandidateOut]:
    # [] (not None) for a pre-existing row computed before this field
    # existed -- see models.py::TrendAnalysis.reversal_history_json's own
    # comment on why an empty list, not a nullable field, is the right
    # migration-safety shape here.
    if raw is None:
        return []
    return [
        ReversalCandidateOut(
            swing=_swing_detail_dict_to_out(entry["swing"]),
            ad_bullish_divergence=entry["ad_bullish_divergence"],
            ad_divergence_swing_date=date.fromisoformat(entry["ad_divergence_swing_date"]) if entry["ad_divergence_swing_date"] else None,
        )
        for entry in json.loads(raw)
    ]


def _reversal_history_out(history: list[ReversalCandidate]) -> list[ReversalCandidateOut]:
    return [
        ReversalCandidateOut(
            swing=_swing_detail_out(candidate.swing),
            ad_bullish_divergence=candidate.ad_bullish_divergence,
            ad_divergence_swing_date=candidate.ad_divergence_swing_date,
        )
        for candidate in history
    ]


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


def _upsert(ticker: str, result: TrendStructureResult, weinstein_result: WeinsteinStageResult, computed_at: datetime) -> bool:
    """Returns weinstein_stage_changed -- computed HERE, not in the pure
    engine, since it's an ACROSS-NIGHTLY-RUNS comparison (today's freshly
    computed stage vs. whatever was stored before this write), requiring a
    read of the previous row. Deliberately distinct from
    weinstein_result.breakout_confirmed (a pure, single-run, week-over-week
    comparison the engine already computed -- see WeinsteinStageResult's
    own docstring). False, not an error, when there's no previous row yet
    (a brand-new ticker's first-ever compute)."""
    with Session(engine) as session:
        previous = session.get(TrendAnalysis, ticker)
        weinstein_stage_changed = False if previous is None else previous.weinstein_stage != weinstein_result.stage

        fields = {
            "computed_at": computed_at,
            "trend_state": result.trend_state,
            "magnitude_tier": result.magnitude_tier,
            "persistence_count": result.persistence_count,
            "bars_since_confirmation": result.bars_since_confirmation,
            "last_confirmed_swing_json": _swing_detail_to_json(result.last_confirmed_swing),
            "warning_flag": result.warning_flag,
            "warning_swing_json": _swing_detail_to_json(result.warning_swing),
            "pullback_occurred_since_flip": result.pullback_occurred_since_flip,
            "trend_started_json": _swing_detail_to_json(result.trend_started),
            "trend_started_is_lower_bound": result.trend_started_is_lower_bound,
            "pullback_history_json": _pullback_history_to_json(result.pullback_history),
            "reversal_history_json": _reversal_history_to_json(result.reversal_history),
            "efficiency_ratio": result.efficiency_ratio,
            "regime": result.regime,
            "blended_score": result.blended_score,
            "bar_level": result.bar_level,
            "ad_bullish_divergence": result.ad_bullish_divergence,
            "ad_divergence_swing_date": result.ad_divergence_swing_date,
            "sma20_position_pct": result.sma20_position_pct,
            "sma20_cross": result.sma20_cross,
            "sma50_position_pct": result.sma50_position_pct,
            "sma50_cross": result.sma50_cross,
            "sma200_position_pct": result.sma200_position_pct,
            "sma200_cross": result.sma200_cross,
            "weinstein_stage": weinstein_result.stage,
            "weinstein_stage_since_date": weinstein_result.stage_since_date,
            "weinstein_stage_since_is_lower_bound": weinstein_result.stage_since_is_lower_bound,
            "weinstein_weeks_available": weinstein_result.weeks_available,
            "weinstein_stage_changed": weinstein_stage_changed,
            "weinstein_ma_slope_pct": weinstein_result.ma_slope_pct,
            "weinstein_vs_ma_pct": weinstein_result.vs_ma_pct,
            "weinstein_volume_ratio": weinstein_result.volume_ratio,
            "weinstein_mansfield_rs": weinstein_result.mansfield_rs,
            "weinstein_breakout_confirmed": weinstein_result.breakout_confirmed,
        }
        stmt = sqlite_insert(TrendAnalysis).values(ticker=ticker, **fields)
        stmt = stmt.on_conflict_do_update(index_elements=["ticker"], set_=fields)
        session.execute(stmt)
        session.commit()

    return weinstein_stage_changed


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
        pullback_occurred_since_flip=row.pullback_occurred_since_flip,
        trend_started=_swing_detail_from_json(row.trend_started_json),
        trend_started_is_lower_bound=row.trend_started_is_lower_bound,
        pullback_history=_pullback_history_from_json(row.pullback_history_json),
        reversal_history=_reversal_history_from_json(row.reversal_history_json),
        efficiency_ratio=row.efficiency_ratio,
        regime=row.regime,
        blended_score=row.blended_score,
        bar_level=row.bar_level,
        ad_bullish_divergence=row.ad_bullish_divergence,
        ad_divergence_swing_date=row.ad_divergence_swing_date,
        sma20_position_pct=row.sma20_position_pct,
        sma20_cross=row.sma20_cross,
        sma50_position_pct=row.sma50_position_pct,
        sma50_cross=row.sma50_cross,
        sma200_position_pct=row.sma200_position_pct,
        sma200_cross=row.sma200_cross,
        weinstein_stage=row.weinstein_stage,
        weinstein_stage_since_date=row.weinstein_stage_since_date,
        weinstein_stage_since_is_lower_bound=row.weinstein_stage_since_is_lower_bound,
        weinstein_weeks_available=row.weinstein_weeks_available,
        weinstein_stage_changed=row.weinstein_stage_changed,
        weinstein_ma_slope_pct=row.weinstein_ma_slope_pct,
        weinstein_vs_ma_pct=row.weinstein_vs_ma_pct,
        weinstein_volume_ratio=row.weinstein_volume_ratio,
        weinstein_mansfield_rs=row.weinstein_mansfield_rs,
        weinstein_breakout_confirmed=row.weinstein_breakout_confirmed,
    )


def compute_and_store_from_rows(
    ticker: str, rows: list[YahooPriceCache], benchmark_rows: list[YahooPriceCache] | None = None
) -> TrendAnalysisOut:
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
    per-ticker failure, never aborting the whole batch. benchmark_rows
    (^GSPC's own daily OHLCV rows) is optional -- absent/empty degrades
    Weinstein's Mansfield RS/breakout fields to None/False rather than
    raising (see compute_weinstein_stage's own na()-passes-through
    handling), so this stays backward compatible with any caller that
    doesn't pass it."""
    ticker = normalize_ticker(ticker)
    if not rows:
        raise ValueError(f"No Yahoo Finance price history available for {ticker}")

    ohlcv = _ohlcv_frame(rows)
    result = compute_trend_structure(ohlcv)
    weinstein_result = compute_weinstein_stage(ohlcv, _ohlcv_frame(benchmark_rows or []))
    computed_at = datetime.now()
    weinstein_stage_changed = _upsert(ticker, result, weinstein_result, computed_at)

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
        pullback_occurred_since_flip=result.pullback_occurred_since_flip,
        trend_started=_swing_detail_out(result.trend_started),
        trend_started_is_lower_bound=result.trend_started_is_lower_bound,
        pullback_history=_pullback_history_out(result.pullback_history),
        reversal_history=_reversal_history_out(result.reversal_history),
        efficiency_ratio=result.efficiency_ratio,
        regime=result.regime,
        blended_score=result.blended_score,
        bar_level=result.bar_level,
        ad_bullish_divergence=result.ad_bullish_divergence,
        ad_divergence_swing_date=result.ad_divergence_swing_date,
        sma20_position_pct=result.sma20_position_pct,
        sma20_cross=result.sma20_cross,
        sma50_position_pct=result.sma50_position_pct,
        sma50_cross=result.sma50_cross,
        sma200_position_pct=result.sma200_position_pct,
        sma200_cross=result.sma200_cross,
        weinstein_stage=weinstein_result.stage,
        weinstein_stage_since_date=weinstein_result.stage_since_date,
        weinstein_stage_since_is_lower_bound=weinstein_result.stage_since_is_lower_bound,
        weinstein_weeks_available=weinstein_result.weeks_available,
        weinstein_stage_changed=weinstein_stage_changed,
        weinstein_ma_slope_pct=weinstein_result.ma_slope_pct,
        weinstein_vs_ma_pct=weinstein_result.vs_ma_pct,
        weinstein_volume_ratio=weinstein_result.volume_ratio,
        weinstein_mansfield_rs=weinstein_result.mansfield_rs,
        weinstein_breakout_confirmed=weinstein_result.breakout_confirmed,
    )


async def compute_and_store_trend_analysis(ticker: str, period: str = "2y") -> TrendAnalysisOut:
    """Single-ticker fetch-then-compute-then-store -- used by the standalone
    API endpoint (a one-off, on-demand request), where fetching just this
    one ticker's history is the right cost, unlike the nightly job's
    whole-universe batch (see compute_and_store_from_rows above). Also
    fetches ^GSPC for Weinstein's Mansfield RS -- cache-first, and the
    nightly job keeps ^GSPC's cache warm, so this is a cache hit in the
    overwhelming majority of on-demand calls, not a new live fetch."""
    ticker = normalize_ticker(ticker)
    rows = await get_or_fetch_price_history(ticker, period=period)
    benchmark_rows = await get_or_fetch_price_history(WEINSTEIN_BENCHMARK_TICKER, period=period)
    return compute_and_store_from_rows(ticker, rows, benchmark_rows=benchmark_rows)


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
