import logging
from datetime import datetime
from typing import Awaitable, TypeVar

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from db import engine
from models import TickerScore
from scoring.overall import StepSnapshot, compute_overall_assessment
from step1_data import get_step1_data
from step2_data import get_step2_data
from step4_data import get_step4_data
from step5_data import get_step5_data
from ticker_summary import get_summary

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


async def compute_ticker_score(ticker: str, cache_only: bool = False) -> TickerScore | None:
    """Builds and upserts one ticker's TickerScore row for the Screener page
    -- the same 5 functions Step 1/2/4/5 and the ticker header already call,
    passed through `cache_only` (see cache.get_or_fetch), plus the ported
    Overall Assessment weighting (scoring/overall.py). Returns None if
    there's no cached profile at all for this ticker (nothing to build a
    card from) -- callers should skip storing a row in that case."""
    ticker = ticker.upper()

    step1, step1_error = await _safe_step(ticker, "step1", get_step1_data(ticker, cache_only=cache_only))
    step2, step2_error = await _safe_step(ticker, "step2", get_step2_data(ticker, cache_only=cache_only))
    step4, step4_error = await _safe_step(ticker, "step4", get_step4_data(ticker, cache_only=cache_only))
    step5, step5_error = await _safe_step(ticker, "step5", get_step5_data(ticker, cache_only=cache_only))
    summary, summary_error = await _safe_step(ticker, "summary", get_summary(ticker, cache_only=cache_only))

    if summary_error or summary is None or summary.company_name is None:
        return None

    overall = compute_overall_assessment(
        [
            _snapshot("step1", step1, step1_error),
            _snapshot("step2", step2, step2_error),
            _snapshot("step4", step4, step4_error),
            _snapshot("step5", step5, step5_error),
        ]
    )

    # Step 4 and Step 5 independently run the same shared classifier
    # (scoring/classification.py::classify_company_type) on the same
    # profile data, so they always agree when both are available -- either
    # one is an equally valid source.
    company_type = (step4.company_type if step4 else None) or (step5.company_type if step5 else None)

    row = TickerScore(
        ticker=ticker,
        company_name=summary.company_name,
        sector=summary.sector,
        industry=summary.industry,
        company_type=company_type,
        step1_score=step1.score if step1 else None,
        step1_verdict=step1.verdict if step1 else None,
        step2_score=step2.score if step2 else None,
        step2_verdict=step2.verdict if step2 else None,
        step4_score=step4.score if step4 else None,
        step4_verdict=step4.verdict if step4 else None,
        step5_score=step5.score if step5 else None,
        step5_verdict=step5.verdict if step5 else None,
        overall_score=overall.score,
        overall_verdict=overall.verdict,
        market_cap=summary.market_cap,
        pe_ratio=summary.pe_ratio,
        beta=summary.beta,
        computed_at=datetime.now(),
    )

    values = row.model_dump()
    with Session(engine) as session:
        stmt = sqlite_insert(TickerScore).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_={k: v for k, v in values.items() if k != "ticker"},
        )
        session.execute(stmt)
        session.commit()

    return row
