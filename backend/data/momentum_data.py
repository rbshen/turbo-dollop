"""Orchestration layer for the Momentum signal -- same shape as
data/trend_analysis_data.py: resolves the universe/Moat filter, fetches raw
price data through the shared bars cache (clients/shared_bars_cache.py),
calls the pure scoring engine (scoring/momentum.py), and persists/reads the
result (models.py::MomentumSnapshot). Independent of FMP and of Step 1-5/
Overall Assessment scoring entirely.

**Plain split-adjusted Close, not dividend-adjusted (2026-09-23 Massive
migration decision)** -- a deliberate accepted one-time step change, not a
bug. Previously fetched via a standalone Yahoo call whose `Close` column
was dividend+split adjusted; now routed through the same shared bars cache
every other daily-bar consumer uses (plain split-adjusted `close`, FMP-sourced
since Phase 2), matching Sector Heatmap's own identical decision and sharing
the nightly cache with Trend/Liquidity Zones."""

import logging
from datetime import date, datetime

import pandas as pd
from sqlalchemy import delete
from sqlmodel import Session, select

from clients.daily_bar_sources import UnservedTickers
from clients.shared_bars_cache import DAILY_INTERVAL, get_or_fetch_bars_batch, stale_ticker_count
from core.db import engine
from core.models import MomentumSnapshot, TickerScore
from core.schemas import MomentumOut, MomentumPeriod, MomentumSnapshotRowOut
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe
from scoring.momentum import compute_momentum_ranking

logger = logging.getLogger(__name__)

# Same set MoatPill/lib/overallScore.ts's MOAT_LABELS recognizes -- a
# ticker with no moat set at all (TickerScore.moat is None) is excluded
# from the universe entirely, never included with a fabricated default.
MOAT_VALUES = {"wide_moat", "narrow_moat", "no_moat"}

# 1y is the longest lookback (LOOKBACK_MONTHS=[3, 6, 12] in scoring/momentum.py);
# 730 days (2y) leaves a full year of slack for the anchor's on-or-before
# lookup, matching the same reasoning data/sector_heatmap_data.py's own
# FETCH_LOOKBACK_DAYS uses.
FETCH_LOOKBACK_DAYS = 730


async def compute_and_store_momentum_snapshot(anchor_date: date) -> dict:
    """Computes one month's full ranked Momentum snapshot and persists it.
    Idempotent per `anchor_date`: any existing rows for this exact date are
    deleted before the fresh rows are inserted, so a manual re-run (or a
    cron retry) on the same anchor day replaces rather than duplicates --
    older snapshots (different as_of_date) are never touched, since the
    frontend's This month/Previous month toggle reads prior months'
    history directly from them."""
    with Session(engine) as session:
        tickers = load_full_tracked_universe(session)
        scored_rows = session.exec(select(TickerScore).where(TickerScore.ticker.in_(tickers))).all()

    # Delisted (TickerScore.delisted_at set -- see pipeline/
    # stale_data_health_check.py::sync_delisted_flags) tickers are excluded
    # from the universe here, the same way a missing Moat rating already
    # is -- no separate skip step needed, since scored_rows already carries
    # both fields off the one query above.
    moat_by_ticker = {row.ticker: row.moat for row in scored_rows if row.moat in MOAT_VALUES and row.delisted_at is None}
    skipped_delisted = sorted(
        row.ticker for row in scored_rows if row.moat in MOAT_VALUES and row.delisted_at is not None
    )
    universe = sorted(moat_by_ticker)
    logger.info(
        "Momentum snapshot: %d Moat-rated tickers in universe for anchor %s (%d skipped as delisted).",
        len(universe), anchor_date, len(skipped_delisted),
    )

    unserved_tickers = UnservedTickers()
    price_histories = await get_or_fetch_bars_batch(
        universe, DAILY_INTERVAL, FETCH_LOOKBACK_DAYS, auto_adjust=False, unserved_tickers=unserved_tickers
    )

    # Stale-data guard (docs/yahoo_close_data_gap_investigation_2026-09-23.md, historical)
    # -- see pipeline/nightly_trend_calculation.py's own equivalent comment
    # for the full reasoning.
    stale_count, _ = stale_ticker_count(universe, DAILY_INTERVAL)

    ranked = compute_momentum_ranking(price_histories, pd.Timestamp(anchor_date))
    computed_at = datetime.now()

    with Session(engine) as session:
        session.execute(delete(MomentumSnapshot).where(MomentumSnapshot.as_of_date == anchor_date))
        for row in ranked:
            session.add(
                MomentumSnapshot(
                    ticker=row.ticker,
                    as_of_date=anchor_date,
                    computed_at=computed_at,
                    moat=moat_by_ticker[row.ticker],
                    return_3mo=row.return_3mo,
                    return_6mo=row.return_6mo,
                    return_12mo=row.return_12mo,
                    composite_score=row.composite_score,
                    rank=row.rank,
                )
            )
        session.commit()

    summary = {
        "as_of_date": anchor_date.isoformat(),
        "universe_size": len(universe),
        "processed": len(ranked),
        "dropped": len(universe) - len(ranked),
        "stale_count": stale_count,
        "unserved_count": len(unserved_tickers),
        "skipped_delisted_count": len(skipped_delisted),
    }
    logger.info(
        "Momentum snapshot complete for %s: %d/%d tickers scored, %d dropped for insufficient price history.",
        anchor_date,
        summary["processed"],
        summary["universe_size"],
        summary["dropped"],
    )
    return summary


def get_momentum_snapshot(period: MomentumPeriod = "current") -> MomentumOut:
    """Reads a persisted snapshot -- never computes live. `current` is the
    most recent as_of_date on file; `previous` is the next one down. Either
    returns an empty MomentumOut (as_of_date/computed_at both None, rows
    []) rather than raising when no matching snapshot exists yet -- the
    first-deploy-before-any-cron-run state, and "previous" when only one
    month's snapshot exists so far."""
    with Session(engine) as session:
        distinct_dates = session.exec(select(MomentumSnapshot.as_of_date).distinct().order_by(MomentumSnapshot.as_of_date.desc())).all()

        if not distinct_dates:
            return MomentumOut(as_of_date=None, computed_at=None, rows=[])

        if period == "current":
            target_date = distinct_dates[0]
        else:
            if len(distinct_dates) < 2:
                return MomentumOut(as_of_date=None, computed_at=None, rows=[])
            target_date = distinct_dates[1]

        snapshot_rows = session.exec(
            select(MomentumSnapshot).where(MomentumSnapshot.as_of_date == target_date).order_by(MomentumSnapshot.rank)
        ).all()

        tickers = [row.ticker for row in snapshot_rows]
        context_rows = session.exec(select(TickerScore).where(TickerScore.ticker.in_(tickers))).all()
        context_by_ticker = {row.ticker: row for row in context_rows}

    computed_at = snapshot_rows[0].computed_at if snapshot_rows else None

    out_rows = []
    for row in snapshot_rows:
        context = context_by_ticker.get(row.ticker)
        out_rows.append(
            MomentumSnapshotRowOut(
                ticker=row.ticker,
                company_name=context.company_name if context else None,
                moat=row.moat,
                return_3mo=row.return_3mo,
                return_6mo=row.return_6mo,
                return_12mo=row.return_12mo,
                composite_score=row.composite_score,
                rank=row.rank,
                overall_score=context.overall_score if context else None,
            )
        )

    return MomentumOut(as_of_date=target_date, computed_at=computed_at, rows=out_rows)
