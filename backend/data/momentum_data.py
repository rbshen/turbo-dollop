"""Orchestration layer for the Momentum signal -- same shape as
data/trend_analysis_data.py: resolves the universe/Moat filter, fetches raw
price data through the shared bars cache (clients/shared_bars_cache.py),
calls the pure scoring engine (scoring/momentum.py), and persists/reads the
result (models.py::MomentumSnapshot). Independent of FMP and of Step 1-5/
Overall Assessment scoring entirely.

**Plain split-adjusted Close, not dividend-adjusted (2026-09-23 decision)**
-- a deliberate choice, not a bug: routed through the same shared bars cache
every other daily-bar consumer uses (plain split-adjusted `close`, FMP-sourced),
matching Sector Heatmap's own identical decision and sharing the nightly cache
with Trend/Liquidity Zones."""

import logging
from datetime import date, datetime

import pandas as pd
from sqlalchemy import delete
from sqlmodel import Session, select

from clients.daily_bar_sources import UnservedTickers
from clients.shared_bars_cache import (
    DAILY_INTERVAL,
    get_or_fetch_bars_batch,
    read_cached_daily_bars_batch,
    stale_ticker_count,
)
from core.db import engine
from core.models import EtfMomentumSnapshot, EtfScreenerRow, MomentumSnapshot, TickerScore
from core.schemas import (
    EtfMomentumOut,
    EtfMomentumRowOut,
    MomentumOut,
    MomentumPeriod,
    MomentumSnapshotRowOut,
)
from data.last_close_data import get_cached_last_closes
from data.tracked_universe import load_etf_universe, load_tracked_universe
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


# The ETF endpoint returns only the top of the stored ranking; the whole ranking stays in the table.
ETF_MOMENTUM_TOP_N = 5


def previous_snapshot_date(dates_desc: list[date]) -> date | None:
    """The "previous month" snapshot for both the stock and ETF Momentum endpoints: the latest as_of_date whose
    calendar month is earlier than the current snapshot's month (current = the newest date, first of
    `dates_desc`, sorted newest first). A second snapshot inside the current month (a mid-month manual run) is
    therefore never "previous". None when no earlier month has a snapshot."""
    if not dates_desc:
        return None
    current = dates_desc[0]
    for candidate in dates_desc[1:]:
        if (candidate.year, candidate.month) < (current.year, current.month):
            return candidate
    return None


def _target_snapshot_date(dates_desc: list[date], period: MomentumPeriod) -> date | None:
    if not dates_desc:
        return None
    return dates_desc[0] if period == "current" else previous_snapshot_date(dates_desc)


async def compute_and_store_momentum_snapshot(anchor_date: date) -> dict:
    """Computes one month's full ranked Momentum snapshot and persists it.
    Idempotent per `anchor_date`: any existing rows for this exact date are
    deleted before the fresh rows are inserted, so a manual re-run (or a
    cron retry) on the same anchor day replaces rather than duplicates --
    older snapshots (different as_of_date) are never touched, since the
    frontend's This month/Previous month toggle reads prior months'
    history directly from them."""
    with Session(engine) as session:
        tickers = load_tracked_universe(session)
        scored_rows = session.exec(select(TickerScore).where(TickerScore.ticker.in_(tickers))).all()

    # Delisted (TickerScore.delisted_at set -- see pipeline/
    # stale_data_health_check.py::sync_delisted_flags) tickers are excluded
    # from the universe here, the same way a missing Moat rating already
    # is -- no separate skip step needed, since scored_rows already carries
    # both fields off the one query above.
    # ETFs/funds are excluded as well: this is a stock momentum ranking, and an ETF can't be given a
    # Moat through the API any more (PUT /moat rejects it) -- this covers a rating set before that.
    moat_by_ticker = {
        row.ticker: row.moat
        for row in scored_rows
        if row.moat in MOAT_VALUES and row.delisted_at is None and not row.is_etf
    }
    # The tracked universe already excludes delisted-flagged tickers, so they never reach scored_rows;
    # the count is read directly so a Moat-rated delisted ticker is still reported, not silently lost.
    with Session(engine) as session:
        skipped_delisted = sorted(
            session.exec(
                select(TickerScore.ticker).where(TickerScore.moat.in_(MOAT_VALUES), TickerScore.delisted_at.is_not(None))
            ).all()
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

    # Stale-data guard
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
                    return_1w=row.return_1w,
                    return_1mo=row.return_1mo,
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
    most recent as_of_date on file; `previous` is the latest snapshot in an
    EARLIER calendar month than the current one (`previous_snapshot_date`), so
    a mid-month re-run never shadows the real month-end. Either returns an empty MomentumOut (as_of_date/computed_at both None, rows
    []) rather than raising when no matching snapshot exists yet -- the
    first-deploy-before-any-cron-run state, and "previous" when only one
    month's snapshot exists so far."""
    with Session(engine) as session:
        distinct_dates = session.exec(select(MomentumSnapshot.as_of_date).distinct().order_by(MomentumSnapshot.as_of_date.desc())).all()

        if not distinct_dates:
            return MomentumOut(as_of_date=None, computed_at=None, rows=[])

        target_date = _target_snapshot_date(distinct_dates, period)
        if target_date is None:
            return MomentumOut(as_of_date=None, computed_at=None, rows=[])

        snapshot_rows = session.exec(
            select(MomentumSnapshot).where(MomentumSnapshot.as_of_date == target_date).order_by(MomentumSnapshot.rank)
        ).all()

        tickers = [row.ticker for row in snapshot_rows]
        context_rows = session.exec(select(TickerScore).where(TickerScore.ticker.in_(tickers))).all()
        context_by_ticker = {row.ticker: row for row in context_rows}

    last_closes = get_cached_last_closes(tickers)

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
                return_1w=row.return_1w,
                return_1mo=row.return_1mo,
                last_price=last_closes.get(row.ticker),
                quote_currency=context.quote_currency if context else None,
                overall_verdict=context.overall_verdict if context else None,
            )
        )

    return MomentumOut(as_of_date=target_date, computed_at=computed_at, rows=out_rows)


async def compute_and_store_etf_momentum_snapshot(anchor_date: date, cached_only: bool = False) -> dict:
    """The ETF twin of compute_and_store_momentum_snapshot: the same ranking engine, 3/6/12-month composite, split-adjusted
    close basis and drop rules (scoring/momentum.py), over `load_etf_universe` frozen at this call. Persists the
    FULL ranking to EtfMomentumSnapshot. Idempotent per `anchor_date`: it deletes and re-inserts only that date's
    EtfMomentumSnapshot rows in one transaction (no other table, no other date).

    `cached_only=True` reads the shared bars cache without any FMP call or cache write (historical backfills:
    the bars are whatever is already held, and the stale/unserved counts are 0 because nothing was fetched).
    A backfill uses TODAY's ETF universe, so an ETF that has since left it is absent from a past anchor's
    ranking (docs/specs/momentum.md, "Caveats")."""
    with Session(engine) as session:
        universe = load_etf_universe(session)
    logger.info("ETF momentum snapshot: %d ETFs in universe for anchor %s (cached_only=%s).", len(universe), anchor_date, cached_only)

    unserved_tickers = UnservedTickers()
    if cached_only:
        price_histories = read_cached_daily_bars_batch(universe, FETCH_LOOKBACK_DAYS)
        stale_count = 0
    else:
        price_histories = await get_or_fetch_bars_batch(
            universe, DAILY_INTERVAL, FETCH_LOOKBACK_DAYS, auto_adjust=False, unserved_tickers=unserved_tickers
        )
        stale_count, _ = stale_ticker_count(universe, DAILY_INTERVAL)

    ranked = compute_momentum_ranking(price_histories, pd.Timestamp(anchor_date))
    computed_at = datetime.now()

    with Session(engine) as session:
        session.execute(delete(EtfMomentumSnapshot).where(EtfMomentumSnapshot.as_of_date == anchor_date))
        for row in ranked:
            session.add(
                EtfMomentumSnapshot(
                    ticker=row.ticker,
                    as_of_date=anchor_date,
                    computed_at=computed_at,
                    return_3mo=row.return_3mo,
                    return_6mo=row.return_6mo,
                    return_12mo=row.return_12mo,
                    composite_score=row.composite_score,
                    rank=row.rank,
                    return_1w=row.return_1w,
                    return_1mo=row.return_1mo,
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
        "cached_only": cached_only,
        "top5": [r.ticker for r in ranked[:ETF_MOMENTUM_TOP_N]],
    }
    logger.info(
        "ETF momentum snapshot complete for %s: %d/%d ETFs scored, %d dropped for insufficient price history.",
        anchor_date, summary["processed"], summary["universe_size"], summary["dropped"],
    )
    return summary


def get_etf_momentum_snapshot(period: MomentumPeriod = "current") -> EtfMomentumOut:
    """Reads a persisted ETF snapshot -- never computes live. `current` is the newest as_of_date, `previous` the
    latest one in an earlier calendar month (`previous_snapshot_date`). Returns only the top
    ETF_MOMENTUM_TOP_N rows by rank; `total_ranked` is the stored ranking's size. Empty (never an error) when no
    matching snapshot exists."""
    empty = EtfMomentumOut(as_of_date=None, computed_at=None, total_ranked=0, rows=[])
    with Session(engine) as session:
        distinct_dates = session.exec(
            select(EtfMomentumSnapshot.as_of_date).distinct().order_by(EtfMomentumSnapshot.as_of_date.desc())
        ).all()
        target_date = _target_snapshot_date(list(distinct_dates), period)
        if target_date is None:
            return empty

        total_ranked = len(
            session.exec(select(EtfMomentumSnapshot.id).where(EtfMomentumSnapshot.as_of_date == target_date)).all()
        )
        top_rows = session.exec(
            select(EtfMomentumSnapshot)
            .where(EtfMomentumSnapshot.as_of_date == target_date)
            .order_by(EtfMomentumSnapshot.rank)
            .limit(ETF_MOMENTUM_TOP_N)
        ).all()
        tickers = [row.ticker for row in top_rows]
        names = {
            row.ticker: row.name for row in session.exec(select(EtfScreenerRow).where(EtfScreenerRow.ticker.in_(tickers))).all()
        }

    last_closes = get_cached_last_closes(tickers)
    return EtfMomentumOut(
        as_of_date=target_date,
        computed_at=top_rows[0].computed_at if top_rows else None,
        total_ranked=total_ranked,
        rows=[
            EtfMomentumRowOut(
                ticker=row.ticker,
                company_name=names.get(row.ticker),
                return_3mo=row.return_3mo,
                return_6mo=row.return_6mo,
                return_12mo=row.return_12mo,
                composite_score=row.composite_score,
                rank=row.rank,
                return_1w=row.return_1w,
                return_1mo=row.return_1mo,
                last_price=last_closes.get(row.ticker),
            )
            for row in top_rows
        ],
    )
