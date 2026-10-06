import json
import logging
from datetime import datetime
from typing import Awaitable, TypeVar

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from core.cache import current_fetch_failure_tracker
from core.db import engine
from core.models import TechnicalEntrySignal, TickerScore, TrendAnalysis
from core.tickers import normalize_ticker
from data.entry_signal_data import DEFAULT_SIGNAL_TYPE, DEFAULT_TIMEFRAME, is_entry_signal_active
from data.moat import get_moat_score_config, get_ticker_moat, resolve_moat_score
from scoring.overall import MoatSnapshot, StepSnapshot, compute_overall_assessment
from data.step1_data import get_step1_data
from data.step2_data import get_step2_data
from data.speculative_growth_data import get_speculative_growth_data
from data.step4_data import get_step4_data
from data.step5_data import get_step5_data
from data.ticker_summary import get_summary
from helpers.statement_view import build_statement_view, data_quality_flags, read_cached_inputs
from scoring.review import REVIEW_GATE_SCORE, compute_review, quarters_from
from scoring.weights import DEFAULT_WEIGHTS
from data.warren_signal_data import (
    DEFAULT_SIGNAL_TYPE as WARREN_SIGNAL_TYPE,
    DEFAULT_TIMEFRAME as WARREN_TIMEFRAME,
    last_buy_signal_fired_at,
    warren_active_up_kind,
)

logger = logging.getLogger(__name__)

STEP_LABELS = {"step1": "Step 1", "step2": "Step 2", "step4": "Step 4", "step5": "Step 5"}

T = TypeVar("T")


async def _safe_step(ticker: str, label: str, coro: Awaitable[T]) -> tuple[T | None, bool]:
    """One step's data function failing (a genuine bug, not a missing-data
    verdict -- those are handled gracefully by the functions themselves)
    must not blow up this ticker's whole score row, in a ~500-ticker sweep
    where any one ticker can have a data shape edge case."""
    try:
        return await coro, False
    except Exception as exc:  # noqa: BLE001
        logger.warning("compute_ticker_score: %s failed for %s: %s", label, ticker, exc)
        return None, True


def _snapshot(key: str, result, has_error: bool) -> StepSnapshot:
    return StepSnapshot(
        key=key,
        label=STEP_LABELS[key],
        has_error=has_error,
        score=result.score if result is not None else None,
        verdict=result.verdict if result is not None else None,
    )


def _review_columns(ticker: str, company_type: str | None, overall_verdict: str | None, step1, step2, step4, step5) -> dict:
    """The four Review columns (scoring/review.py) from the same cached statements the steps just read: no FMP call.
    Always returns all four keys, None included, so the upsert rewrites them and a stale status can never linger. A failure
    here never costs the row its scores: it is logged and the four columns are written as None."""
    empty = {"review_status": None, "review_reasons": None, "conviction": None, "data_quality_flags": None}
    try:
        with Session(engine) as session:
            raw, earnings, classified = read_cached_inputs(session, ticker)
        kind = company_type or classified
        flags = data_quality_flags(raw, earnings, kind)
        view = build_statement_view(raw, kind)
        result = compute_review(
            overall_verdict,
            step1,
            step2,
            step4,
            step5,
            raw.balance_sheet_annual,
            quarters_from(raw.balance_sheet_quarterly, view.used.balance_sheet),
            flags,
            gate=REVIEW_GATE_SCORE,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("compute_ticker_score: review failed for %s: %s", ticker, exc)
        return empty
    return {
        "review_status": result.status,
        "review_reasons": json.dumps(result.reasons) if result.status else None,
        "conviction": result.conviction,
        "data_quality_flags": json.dumps([f.model_dump() for f in flags]) if flags else None,
    }


def stored_review_fields(row: TickerScore | None) -> dict:
    """The Review status fields of one TickerScore row for a payload that shows them beside that same row's verdict (the
    Watchlist and Momentum rows): status, parsed reasons and conviction, all None for no row or an ETF/fund (it never
    carries a status). The JSON text is parsed here once; `data_quality_flags` is not part of any row payload."""
    if row is None or row.is_etf or not row.review_status:
        return {"review_status": None, "review_reasons": None, "conviction": None}
    return {
        "review_status": row.review_status,
        "review_reasons": json.loads(row.review_reasons) if row.review_reasons else None,
        "conviction": row.conviction,
    }


# TickerScore columns written by other jobs, never overwritten by a score upsert.
PRESERVED_ON_UPSERT = ("delisted_at",)

async def compute_ticker_score(
    ticker: str, cache_only: bool = False, persist_etf: bool = True, persist: bool = True, weights=None
) -> TickerScore | None:
    """Builds and upserts one ticker's TickerScore row for the Screener page
    -- the same 5 functions Step 1/2/4/5 and the ticker header already call,
    passed through `cache_only` (see cache.get_or_fetch), plus the ported
    Overall Assessment weighting (scoring/overall.py). Returns None if
    there's no cached profile at all for this ticker (nothing to build a
    card from) -- callers should skip storing a row in that case.

    `persist_etf=False` computes and returns the row exactly the same but does not write it when the ticker is an ETF/fund
    (the app's one rule, summary.is_etf); a stock is upserted as always. GET /score passes it: an ETF's score row is
    frozen since the 2026-10-03 cutover (the ETF job's EtfScreenerRow is the ETF read model), so its page load must not
    rewrite one. The default keeps every other caller unchanged.

    `persist=False` computes and returns the row but writes nothing at all (the read-only dry run that diffs new scoring
    code against the stored rows before a recompute)."""
    ticker = normalize_ticker(ticker)
    # One weight set for the whole compute: the four steps and the Overall blend must agree on it.
    weights = weights if weights is not None else DEFAULT_WEIGHTS

    step1, step1_error = await _safe_step(ticker, "step1", get_step1_data(ticker, cache_only=cache_only, weights=weights))
    step2, step2_error = await _safe_step(ticker, "step2", get_step2_data(ticker, cache_only=cache_only, weights=weights))
    step4, step4_error = await _safe_step(ticker, "step4", get_step4_data(ticker, cache_only=cache_only, weights=weights))
    step5, step5_error = await _safe_step(ticker, "step5", get_step5_data(ticker, cache_only=cache_only, weights=weights))
    summary, summary_error = await _safe_step(ticker, "summary", get_summary(ticker, cache_only=cache_only))
    # New, independent, read-only classification -- never feeds
    # compute_overall_assessment below (only STEP_LABELS-style steps do), so
    # this isn't wrapped in a _snapshot the way step1/2/4/5 are. Its own
    # error flag is unused past _safe_step's warning-log side effect --
    # unlike summary_error, a speculative-growth failure shouldn't block
    # this ticker's whole row.
    speculative_growth, _speculative_growth_error = await _safe_step(
        ticker, "speculative_growth", get_speculative_growth_data(ticker, cache_only=cache_only)
    )

    if summary_error or summary is None or summary.company_name is None:
        return None

    # Moat is user-set, not fetched -- reading it is a plain DB lookup, not
    # part of the cache_only/FMP-call story the 5 _safe_step calls above are
    # guarding.
    with Session(engine) as session:
        ticker_moat = get_ticker_moat(session, ticker)
        moat_snapshot = (
            MoatSnapshot(ticker_moat.moat, resolve_moat_score(get_moat_score_config(session), ticker_moat.moat))
            if ticker_moat is not None
            else None
        )
        # Plain same-session sibling read, same shape as ticker_moat above --
        # not one of the FMP-backed _safe_step calls, so a missing row (a
        # ticker Weinstein hasn't processed yet) is just None, never a raise.
        trend_analysis = session.get(TrendAnalysis, ticker)
        entry_signal = session.get(TechnicalEntrySignal, (ticker, DEFAULT_SIGNAL_TYPE, DEFAULT_TIMEFRAME))
        warren_signal = session.get(TechnicalEntrySignal, (ticker, WARREN_SIGNAL_TYPE, WARREN_TIMEFRAME))
        warren_last_buy_fired_at = last_buy_signal_fired_at(session, ticker)

    overall = compute_overall_assessment(
        [
            _snapshot("step1", step1, step1_error),
            _snapshot("step2", step2, step2_error),
            _snapshot("step4", step4, step4_error),
            _snapshot("step5", step5, step5_error),
        ],
        moat=moat_snapshot,
        weights=weights.overall,
    )

    # Demote-only status beside the verdict, never feeding it (an ETF/fund has none: the 5-step framework is not applied).
    review = (
        _review_columns(ticker, None, overall.verdict, step1, step2, step4, step5)
        if not summary.is_etf
        else {"review_status": None, "review_reasons": None, "conviction": None, "data_quality_flags": None}
    )

    # Step 4 and Step 5 independently run the same shared classifier
    # (scoring/classification.py::classify_company_type) on the same
    # profile data, so they always agree when both are available -- either
    # one is an equally valid source.
    company_type = (step4.company_type if step4 else None) or (step5.company_type if step5 else None)

    # An ETF/fund product (e.g. SPY) has no single meaningful GICS sector --
    # FMP's own profile sector for these is really "the fund sponsor's
    # business," not the fund's -- so this is deliberately nulled rather
    # than passed through, even though summary.sector (profile.get("sector"))
    # itself is untouched (raw cache stays a faithful copy of what FMP
    # returned; only this persisted/displayed field is suppressed).
    sector = summary.sector if company_type != "ETF" else None

    row = TickerScore(
        ticker=ticker,
        company_name=summary.company_name,
        sector=sector,
        industry=summary.industry,
        company_type=company_type,
        is_etf=summary.is_etf,
        step1_score=step1.score if step1 else None,
        step1_verdict=step1.verdict if step1 else None,
        step2_score=step2.score if step2 else None,
        step2_verdict=step2.verdict if step2 else None,
        step4_score=step4.score if step4 else None,
        step4_verdict=step4.verdict if step4 else None,
        step5_score=step5.score if step5 else None,
        step5_verdict=step5.verdict if step5 else None,
        moat=moat_snapshot.moat if moat_snapshot else None,
        moat_score=moat_snapshot.score if moat_snapshot else None,
        overall_score=overall.score,
        overall_verdict=overall.verdict,
        market_cap=summary.market_cap,
        last_price=summary.price,
        pe_ratio=summary.pe_ratio,
        beta=summary.beta,
        quote_currency=summary.quote_currency,
        reported_currency=summary.reported_currency,
        valuation_verdict=summary.fair_value_verdict,
        valuation_source=summary.valuation_source,
        growth_rate=step2.growth_rate if step2 else None,
        computed_at=datetime.now(),
        perf_5y_vs_spy_pct=summary.perf_5y_vs_spy_pct,
        perf_5y_vs_spy_status=summary.perf_5y_vs_spy_status,
        speculative_growth_qualifies=speculative_growth.qualifies if speculative_growth else None,
        weinstein_stage=trend_analysis.weinstein_stage if trend_analysis else None,
        weinstein_stage_since_date=trend_analysis.weinstein_stage_since_date if trend_analysis else None,
        weinstein_stage_since_is_lower_bound=trend_analysis.weinstein_stage_since_is_lower_bound if trend_analysis else None,
        weinstein_ma_slope_pct=trend_analysis.weinstein_ma_slope_pct if trend_analysis else None,
        weinstein_vs_ma_pct=trend_analysis.weinstein_vs_ma_pct if trend_analysis else None,
        weinstein_pending_direction=trend_analysis.weinstein_pending_direction if trend_analysis else None,
        bb_rsi_entry_signal=is_entry_signal_active(entry_signal.fired_at) if entry_signal else None,
        warren_active_signal_kind=warren_active_up_kind(warren_signal.signal_kind) if warren_signal else None,
        warren_last_buy_fired_at=warren_last_buy_fired_at,
        **review,
    )

    if not persist or (summary.is_etf and not persist_etf):
        return row

    # Inside the ticker-page Refresh (core/cache.py::track_fetch_failures): a live fetch that failed with nothing cached
    # to fall back on left some input empty, so this row would overwrite the last good one with a degraded score.
    # Keep the previous row; the nightly jobs and the next successful refresh re-score it.
    tracker = current_fetch_failure_tracker()
    if tracker is not None and tracker.unrecovered:
        logger.warning(
            "compute_ticker_score: %s not persisted -- live fetch(es) failed during the refresh with no cached row to use: %s",
            ticker,
            ", ".join(sorted(set(tracker.unrecovered))),
        )
        return row

    values = row.model_dump()
    with Session(engine) as session:
        stmt = sqlite_insert(TickerScore).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            # delisted_at is owned by pipeline.stale_data_health_check, not by a
            # score recompute: `values` carries it as None, so including it here
            # wiped the flag on every recompute (2026-09-24: EA/EQR/TWTR/WBA
            # flagged at 21:49, cleared by the next recompute).
            set_={k: v for k, v in values.items() if k not in ("ticker", *PRESERVED_ON_UPSERT)},
        )
        session.execute(stmt)
        session.commit()

    return row
