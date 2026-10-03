"""Orchestration layer for the Weinstein stage analysis -- same get_stepN_data
shape as data/step4_data.py: fetches raw data (via clients/shared_bars_cache.py),
calls the pure calculation engines (analysis/trend_structure/weinstein*.py), and
persists/reads the result (models.py::TrendAnalysis). FMP daily bars (via the
shared bars cache) are the sole data source. The "trend" names here are
historical: the swing/BOS trend-structure engine was removed, Weinstein is all
this module computes now.
"""

import json
from dataclasses import asdict
from datetime import date, datetime

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from analysis.trend_structure.types import WeinsteinStageResult
from analysis.trend_structure.weinstein import WeinsteinParams, compute_weinstein_stage
from analysis.trend_structure.weinstein_pending import WeinsteinPendingEtaScenario, WeinsteinPendingResult, compute_weinstein_pending
from clients.shared_bars_cache import DAILY_INTERVAL, _most_recent_completed_trading_date, get_or_fetch_bars
from core.db import engine
from core.models import TrendAnalysis
from core.schemas import TrendAnalysisOut, WeinsteinParamsOut, WeinsteinPendingEtaScenarioOut, WeinsteinPendingOut
from core.tickers import normalize_ticker
from helpers.weinstein_config import load_weinstein_params

# The Weinstein engine replays ~5 years of daily bars. An EMA/sticky state machine
# needs a long run-in: the previous 2y window left only ~70 classified weeks
# and made "since" dates and the current stage depend on where the window
# happened to start. 1825 = 365*5, the same window the validated simulation
# script uses. The shared bars cache already holds ~5y of dailies for every
# US-listed ticker (the nightly FMP fetch), so this widens nothing in practice.
WEINSTEIN_LOOKBACK_DAYS = 365 * 5


def _params_out(params: WeinsteinParams) -> WeinsteinParamsOut:
    return WeinsteinParamsOut(**asdict(params))


def _params_out_from_row(row: TrendAnalysis) -> WeinsteinParamsOut | None:
    params = WeinsteinParams.from_json(row.weinstein_params_json)
    return _params_out(params) if params else None


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
    weinstein_result: WeinsteinStageResult,
    pending_result: WeinsteinPendingResult,
    computed_at: datetime,
    bars_as_of: date,
    params: WeinsteinParams,
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
            "weinstein_params_json": params.to_json(),
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
        weinstein_params=_params_out_from_row(row),
        pending=_pending_out_from_row(row),
    )


def _load_params() -> WeinsteinParams:
    with Session(engine) as session:
        return load_weinstein_params(session)


def compute_and_store_from_frames(
    ticker: str,
    ohlcv: pd.DataFrame,
    benchmark_ohlcv: pd.DataFrame | None = None,
    params: WeinsteinParams | None = None,
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
    is empty (no bars at all for this ticker) -- callers (the nightly
    job's per-ticker loop) treat this like any other per-ticker failure,
    never aborting the whole batch. benchmark_ohlcv (WEINSTEIN_BENCHMARK_TICKER's
    own daily OHLCV, SPY) is optional -- absent/empty degrades Weinstein's Mansfield
    RS/breakout fields to None/False rather than raising (see
    compute_weinstein_stage's own na()-passes-through handling), so this
    stays backward compatible with any caller that doesn't pass it.

    `params` (the live Weinstein Settings) is read from the DB when the
    caller doesn't pass it -- the nightly job reads it once per run and
    passes it in. `ohlcv` may hold up to WEINSTEIN_LOOKBACK_DAYS of history:
    the Weinstein engine replays all of it."""
    ticker = normalize_ticker(ticker)
    if ohlcv is None or ohlcv.empty:
        raise ValueError(f"No price history available for {ticker}")

    if params is None:
        params = _load_params()

    weinstein_result, pending_result = compute_weinstein_results(ohlcv, benchmark_ohlcv, params)
    return store_weinstein_results(ticker, weinstein_result, pending_result, ohlcv.index.max().date(), params)


def compute_weinstein_results(
    ohlcv: pd.DataFrame, benchmark_ohlcv: pd.DataFrame | None, params: WeinsteinParams
) -> tuple[WeinsteinStageResult, WeinsteinPendingResult]:
    """The pure engines (stage, then pending) on already-fetched daily bars, no DB. Split out so a caller that needs
    the result for more than the TrendAnalysis row (the ETF screener job, which also copies fields onto its own
    row) computes Weinstein ONCE and hands the same result to `store_weinstein_results`."""
    weinstein_result = compute_weinstein_stage(
        ohlcv, benchmark_ohlcv if benchmark_ohlcv is not None else pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), params
    )
    return weinstein_result, compute_weinstein_pending(ohlcv, params)


def store_weinstein_results(
    ticker: str,
    weinstein_result: WeinsteinStageResult,
    pending_result: WeinsteinPendingResult,
    bars_as_of: date,
    params: WeinsteinParams,
) -> TrendAnalysisOut:
    """Upserts one ticker's TrendAnalysis row from results already computed by `compute_weinstein_results`."""
    computed_at = datetime.now()
    weinstein_stage_changed = _upsert(ticker, weinstein_result, pending_result, computed_at, bars_as_of, params)

    return TrendAnalysisOut(
        ticker=ticker,
        computed_at=computed_at,
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
        weinstein_params=_params_out(params),
        pending=_pending_out_from_result(pending_result),
    )


async def compute_and_store_trend_analysis(ticker: str, lookback_days: int = WEINSTEIN_LOOKBACK_DAYS) -> TrendAnalysisOut:
    """Single-ticker fetch-then-compute-then-store -- used by the standalone
    API endpoint (a one-off, on-demand request), where fetching just this
    one ticker's history is the right cost, unlike the nightly job's
    whole-universe batch (see compute_and_store_from_frames above). Also
    fetches WEINSTEIN_BENCHMARK_TICKER (SPY) for Weinstein's Mansfield RS. Both reads go through the
    shared bars cache (clients/shared_bars_cache.py): the nightly job keeps
    both warm and close-fresh, so this is a cache hit in the overwhelming
    majority of on-demand calls, and a genuinely-stale row (last bar behind
    the most recently completed session) refetches on its own.

    auto_adjust=False -- Trend/Weinstein want raw, non-dividend-adjusted
    bars (2026-09-18 decision)."""
    ticker = normalize_ticker(ticker)
    params = _load_params()
    ohlcv = await get_or_fetch_bars(ticker, DAILY_INTERVAL, lookback_days, auto_adjust=False)
    benchmark_ohlcv = await get_or_fetch_bars(params.rs_benchmark, DAILY_INTERVAL, lookback_days, auto_adjust=False)
    return compute_and_store_from_frames(ticker, ohlcv, benchmark_ohlcv=benchmark_ohlcv, params=params)


def _is_row_stale(row: TrendAnalysis) -> bool:
    """Close-aware, not a flat timer: a stored row is trusted only if it was
    computed from bars reaching the most recently completed session -- the
    same principle clients/shared_bars_cache.py::_is_stale applies to the
    bars themselves, one level up. A flat "computed within the last day"
    check both served a row a full session behind (computed ~2am UTC, market
    closes 4pm ET) and recomputed an unchanged one over weekends. `bars_as_of`
    NULL (a row from before that column existed) reads as stale.

    Inherits the bars cache's own non-holiday-awareness: on a market holiday
    the "most recently completed session" is the holiday itself, which no
    bar will ever match, so this reads stale (and recomputes) on each
    on-demand read that day -- cheap, and the bars cache refetches on the
    same days for the same reason."""
    return row.bars_as_of is None or row.bars_as_of < _most_recent_completed_trading_date()


async def get_trend_analysis_data(ticker: str, cache_only: bool = False, lookback_days: int = WEINSTEIN_LOOKBACK_DAYS) -> TrendAnalysisOut | None:
    """cache_only=True (used by watchlist_data.py's bulk row compose) never
    triggers a live bar fetch -- returns whatever's cached (even if
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
        # No bars at all for this ticker -- reads the same as
        # "not computed yet" to callers (falls back to a stale cached row if
        # one exists, same "stale is better than nothing" convention used
        # throughout this codebase).
        return _row_to_out(row) if row else None
