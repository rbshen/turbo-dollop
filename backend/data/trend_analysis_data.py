"""Orchestration layer for trend-structure analysis -- same get_stepN_data
shape as data/step4_data.py: fetches raw data (via clients/shared_bars_cache.py),
calls the pure calculation engine (analysis/trend_structure/), and
persists/reads the result (models.py::TrendAnalysis). Independent of FMP
entirely -- Yahoo Finance is the sole data source for this feature.
"""

import json
from dataclasses import asdict
from datetime import date, datetime

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from analysis.trend_structure.engine import compute_trend_structure
from analysis.trend_structure.types import PullbackCycle, ReversalCandidate, SwingDetail, TrendStructureResult, WeinsteinStageResult
from analysis.trend_structure.weinstein import WEINSTEIN_BENCHMARK_TICKER, compute_weinstein_stage
from analysis.trend_structure.weinstein_pending import WeinsteinPendingEtaScenario, WeinsteinPendingResult, compute_weinstein_pending
from clients.shared_bars_cache import DAILY_INTERVAL, _most_recent_completed_trading_date, get_or_fetch_bars
from core.db import engine
from core.models import TrendAnalysis
from core.schemas import PullbackCycleOut, ReversalCandidateOut, SwingDetailOut, TrendAnalysisOut, WeinsteinPendingEtaScenarioOut, WeinsteinPendingOut
from core.tickers import normalize_ticker

# 2 calendar years of daily bars -- unchanged from the period="2y" this
# feature always fetched; also what Weinstein's own bootstrap-convergence
# validation (CLAUDE.md) was measured against.
LOOKBACK_DAYS = 730


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


def _pending_eta_to_json(eta: dict[str, WeinsteinPendingEtaScenario] | None) -> str | None:
    if eta is None:
        return None
    return json.dumps(
        {
            scenario: {
                "weeks_away": s.weeks_away,
                "projected_date": s.projected_date.isoformat() if s.projected_date else None,
                "band_lapsed_before_confirmation": s.band_lapsed_before_confirmation,
                "growth_rate_pct": s.growth_rate_pct,
                "horizon_exceeded": s.horizon_exceeded,
            }
            for scenario, s in eta.items()
        }
    )


def _pending_eta_from_json(raw: str | None) -> dict[str, WeinsteinPendingEtaScenarioOut] | None:
    if raw is None:
        return None
    return {
        scenario: WeinsteinPendingEtaScenarioOut(
            weeks_away=payload["weeks_away"],
            projected_date=date.fromisoformat(payload["projected_date"]) if payload["projected_date"] else None,
            band_lapsed_before_confirmation=payload["band_lapsed_before_confirmation"],
            growth_rate_pct=payload["growth_rate_pct"],
            horizon_exceeded=payload["horizon_exceeded"],
        )
        for scenario, payload in json.loads(raw).items()
    }


def _pending_out_from_row(row: TrendAnalysis) -> WeinsteinPendingOut | None:
    """Built from the persisted columns (see models.py::TrendAnalysis's own
    weinstein_pending_* comment) -- None whenever
    weinstein_pending_direction is None, same "no fabricated neutral
    result" convention as weinstein_stage itself."""
    if row.weinstein_pending_direction is None:
        return None
    return WeinsteinPendingOut(
        direction=row.weinstein_pending_direction,
        since_date=row.weinstein_pending_since_date,
        since_is_lower_bound=row.weinstein_pending_since_is_lower_bound or False,
        band_cushion_pct=row.weinstein_pending_band_cushion_pct,
        typical_weekly_move_pct=row.weinstein_pending_typical_weekly_move_pct,
        eta=_pending_eta_from_json(row.weinstein_pending_eta_json) or {},
    )


def _pending_out_from_result(pending_result: WeinsteinPendingResult) -> WeinsteinPendingOut | None:
    """Built straight from a freshly computed WeinsteinPendingResult (the
    fresh-compute return path) -- mirrors _pending_out_from_row above,
    which builds the same shape from persisted columns instead."""
    if pending_result.direction is None:
        return None
    return WeinsteinPendingOut(
        direction=pending_result.direction,
        since_date=pending_result.since_date,
        since_is_lower_bound=pending_result.since_is_lower_bound,
        band_cushion_pct=pending_result.band_cushion_pct,
        typical_weekly_move_pct=pending_result.typical_weekly_move_pct,
        eta={
            scenario: WeinsteinPendingEtaScenarioOut(
                weeks_away=s.weeks_away,
                projected_date=s.projected_date,
                band_lapsed_before_confirmation=s.band_lapsed_before_confirmation,
                growth_rate_pct=s.growth_rate_pct,
                horizon_exceeded=s.horizon_exceeded,
            )
            for scenario, s in (pending_result.eta or {}).items()
        },
    )


def _upsert(
    ticker: str,
    result: TrendStructureResult,
    weinstein_result: WeinsteinStageResult,
    pending_result: WeinsteinPendingResult,
    computed_at: datetime,
    bars_as_of: date,
) -> bool:
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
            "bars_as_of": bars_as_of,
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
            "weinstein_pending_direction": pending_result.direction,
            "weinstein_pending_since_date": pending_result.since_date,
            "weinstein_pending_since_is_lower_bound": pending_result.since_is_lower_bound,
            "weinstein_pending_band_cushion_pct": pending_result.band_cushion_pct,
            "weinstein_pending_typical_weekly_move_pct": pending_result.typical_weekly_move_pct,
            "weinstein_pending_eta_json": _pending_eta_to_json(pending_result.eta),
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
        pending=_pending_out_from_row(row),
    )


def compute_and_store_from_frames(
    ticker: str, ohlcv: pd.DataFrame, benchmark_ohlcv: pd.DataFrame | None = None
) -> TrendAnalysisOut:
    """Runs the pure calculation engine against already-fetched daily OHLCV
    (lowercase columns, naive DatetimeIndex -- exactly what
    clients/shared_bars_cache.py::get_or_fetch_bars[_batch] returns) and
    upserts -- no fetch of its own. Split out from
    compute_and_store_trend_analysis so the nightly job (which fetches the
    whole universe in one batch call via
    clients.shared_bars_cache.get_or_fetch_bars_batch, per this feature's
    explicit "batch download, not one call per ticker" requirement) can
    reuse this same compute+upsert logic per ticker without each ticker
    triggering its own separate live fetch. Raises ValueError if `ohlcv`
    is empty (no Yahoo data at all for this ticker) -- callers (the nightly
    job's per-ticker loop) treat this like any other per-ticker failure,
    never aborting the whole batch. benchmark_ohlcv (^GSPC's own daily
    OHLCV) is optional -- absent/empty degrades Weinstein's Mansfield
    RS/breakout fields to None/False rather than raising (see
    compute_weinstein_stage's own na()-passes-through handling), so this
    stays backward compatible with any caller that doesn't pass it."""
    ticker = normalize_ticker(ticker)
    if ohlcv is None or ohlcv.empty:
        raise ValueError(f"No Yahoo Finance price history available for {ticker}")

    result = compute_trend_structure(ohlcv)
    weinstein_result = compute_weinstein_stage(
        ohlcv, benchmark_ohlcv if benchmark_ohlcv is not None else pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    )
    pending_result = compute_weinstein_pending(ohlcv)
    computed_at = datetime.now()
    weinstein_stage_changed = _upsert(ticker, result, weinstein_result, pending_result, computed_at, ohlcv.index.max().date())

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
        pending=_pending_out_from_result(pending_result),
    )


async def compute_and_store_trend_analysis(ticker: str, lookback_days: int = LOOKBACK_DAYS) -> TrendAnalysisOut:
    """Single-ticker fetch-then-compute-then-store -- used by the standalone
    API endpoint (a one-off, on-demand request), where fetching just this
    one ticker's history is the right cost, unlike the nightly job's
    whole-universe batch (see compute_and_store_from_frames above). Also
    fetches ^GSPC for Weinstein's Mansfield RS. Both reads go through the
    shared bars cache (clients/shared_bars_cache.py): the nightly job keeps
    both warm and close-fresh, so this is a cache hit in the overwhelming
    majority of on-demand calls, and a genuinely-stale row (last bar behind
    the most recently completed session) refetches on its own.

    auto_adjust=False -- Trend/Weinstein want raw, non-dividend-adjusted
    bars (2026-09-18 Yahoo-consolidation decision)."""
    ticker = normalize_ticker(ticker)
    ohlcv = await get_or_fetch_bars(ticker, DAILY_INTERVAL, lookback_days, auto_adjust=False)
    benchmark_ohlcv = await get_or_fetch_bars(WEINSTEIN_BENCHMARK_TICKER, DAILY_INTERVAL, lookback_days, auto_adjust=False)
    return compute_and_store_from_frames(ticker, ohlcv, benchmark_ohlcv=benchmark_ohlcv)


def _is_row_stale(row: TrendAnalysis) -> bool:
    """Close-aware, not a flat timer: a stored row is trusted only if it was
    computed from bars reaching the most recently completed session -- the
    same principle clients/shared_bars_cache.py::_is_stale applies to the
    bars themselves, one level up. A flat "computed within the last day"
    check both served a row a full session behind (computed 3:10am, market
    closes 4pm ET) and recomputed an unchanged one over weekends. `bars_as_of`
    NULL (a row from before that column existed) reads as stale.

    Inherits the bars cache's own non-holiday-awareness: on a market holiday
    the "most recently completed session" is the holiday itself, which no
    bar will ever match, so this reads stale (and recomputes) on each
    on-demand read that day -- cheap, and the bars cache refetches on the
    same days for the same reason."""
    return row.bars_as_of is None or row.bars_as_of < _most_recent_completed_trading_date()


async def get_trend_analysis_data(ticker: str, cache_only: bool = False, lookback_days: int = LOOKBACK_DAYS) -> TrendAnalysisOut | None:
    """cache_only=True (used by watchlist_data.py's bulk row compose) never
    triggers a live Yahoo fetch -- returns whatever's cached (even if
    stale), or None if this ticker has never been computed yet (the nightly
    cron hasn't reached it). cache_only=False (the standalone API endpoint)
    computes fresh on a missing/stale row."""
    ticker = normalize_ticker(ticker)
    with Session(engine) as session:
        row = session.exec(select(TrendAnalysis).where(TrendAnalysis.ticker == ticker)).first()

    is_stale = row is None or _is_row_stale(row)
    if cache_only or not is_stale:
        return _row_to_out(row) if row else None

    try:
        return await compute_and_store_trend_analysis(ticker, lookback_days=lookback_days)
    except ValueError:
        # No Yahoo Finance data at all for this ticker -- reads the same as
        # "not computed yet" to callers (falls back to a stale cached row if
        # one exists, same "stale is better than nothing" convention used
        # throughout this codebase).
        return _row_to_out(row) if row else None
