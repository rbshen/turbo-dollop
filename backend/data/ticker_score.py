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
from data.last_close_data import get_cached_last_close
from core.models import MoatScoreConfig
from data.moat import CONFIG_KEY as MOAT_CONFIG_KEY, get_ticker_moat, resolve_moat_multiplier
from scoring.step3 import classify_valuation_verdict
from scoring.overall import SCORE_FORMULA_VERSION, StepSnapshot, compute_overall_assessment
from data.step1_data import get_step1_data
from data.step2_data import get_step2_data
from data.speculative_growth_data import get_speculative_growth_data
from data.step4_data import get_step4_data
from data.step5_data import get_step5_data
from data.ticker_summary import get_summary
from scoring.weights import ScoreWeights
from data.score_weights import load_score_weights
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


def _screener_price_and_market_cap(
    last_close: float | None, quote_price: float | None, quote_market_cap: float | None
) -> tuple[float | None, float | None]:
    """The Screener's Quote and Mkt cap follow the nightly last close (docs/decisions.md 2026-10-10), like the Watchlist and the
    P/E: the price is the cached last close, and the quote's market cap is scaled by last_close / quote_price (the quote's
    market cap is for the quote's price). No cached close -> the quote values as they are. A missing or zero quote price
    cannot give a ratio, so the market cap stays unscaled (the price is still the close)."""
    if last_close is None:
        return quote_price, quote_market_cap
    if quote_market_cap is not None and quote_price:
        quote_market_cap = quote_market_cap * last_close / quote_price
    return last_close, quote_market_cap


def _screener_valuation_verdict(last_close: float | None, fair_value_price: float | None, summary_verdict: str | None) -> str | None:
    """The stored valuation verdict compares fair value with the nightly last close, the price the Screener and Watchlist show
    (docs/decisions.md 2026-10-10, follow-up). Same band as Step 3 (scoring.step3.classify_valuation_verdict); fair value and
    every score are untouched. No cached close, or no positive fair value (a PASS, a suppressed result), keeps the summary's
    verdict, which was computed against the cached quote. A custom valuation is covered: fair_value_price is already its value."""
    if last_close is None or not fair_value_price or fair_value_price <= 0:
        return summary_verdict
    return classify_valuation_verdict(last_close / fair_value_price - 1)


# TickerScore columns written by other jobs, never overwritten by a score upsert.
PRESERVED_ON_UPSERT = ("delisted_at",)

async def compute_ticker_score(
    ticker: str, cache_only: bool = False, persist_etf: bool = True, persist: bool = True, weights: ScoreWeights | None = None
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
    # `weights` (an explicit set) is for dry runs and experiments; a real compute reads the saved set and stamps its version.
    if weights is None:
        snapshot = load_score_weights(engine)
        weights, weights_version = snapshot.weights, snapshot.version
    else:
        weights_version = None

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
    # guarding. Unset = scored as No moat (multiplier 0.70). The Narrow multiplier is read without get-or-create, so a read-only
    # engine never writes (an absent config row reads as the default).
    with Session(engine) as session:
        ticker_moat = get_ticker_moat(session, ticker)
        moat = ticker_moat.moat if ticker_moat is not None else None
        narrow_multiplier = None
        moat_config = session.get(MoatScoreConfig, MOAT_CONFIG_KEY)
        if moat_config is not None:
            narrow_multiplier = moat_config.narrow_moat_multiplier
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
        moat=moat,
        weights=weights.overall,
        narrow_multiplier=narrow_multiplier or resolve_moat_multiplier(None, "narrow_moat"),
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

    cached_close = get_cached_last_close(ticker)
    last_close = cached_close[0] if cached_close is not None else None
    last_price, market_cap = _screener_price_and_market_cap(last_close, summary.price, summary.market_cap)
    valuation_verdict = _screener_valuation_verdict(last_close, summary.fair_value_price, summary.fair_value_verdict)

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
        moat=moat,
        steps_score=overall.steps_score,
        moat_multiplier=overall.moat_multiplier,
        overall_score=overall.score,
        overall_verdict=overall.verdict,
        market_cap=market_cap,
        last_price=last_price,
        pe_ratio=summary.pe_ratio,
        beta=summary.beta,
        quote_currency=summary.quote_currency,
        reported_currency=summary.reported_currency,
        valuation_verdict=valuation_verdict,
        valuation_source=summary.valuation_source,
        growth_rate=step2.growth_rate if step2 else None,
        computed_at=datetime.now(),
        weights_version=weights_version,
        formula_version=SCORE_FORMULA_VERSION,
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
