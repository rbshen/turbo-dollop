"""Orchestration layer for the Sector Heatmap -- the 11 SPDR sector ETFs x 8
trailing total-return windows. Same shape as data/momentum_data.py: fetch
through the shared bars cache (clients/shared_bars_cache.py), run the pure
math (scoring/etf_returns.py), persist (models.py::SectorEtfReturn), and a
read path that never computes live. Independent of FMP and of Step 1-5/
Overall Assessment scoring entirely -- zero FMP calls, no FMP_ENABLED guard
needed.

**Plain split-adjusted Close, not total return (2026-09-23 Massive
migration decision)** -- a deliberate accepted one-time step change in
every window's value, not a bug. Previously fetched with auto_adjust=False
so the frame carried both raw `Close` and dividend-adjusted `Adj Close`,
computing returns off `Adj Close` (bond/income funds differ from their
price return by up to ~6pp over 1y, see
docs/etf_heatmap_momentum_investigation_2026-09-20.md, section 2.5).
Massive/Polygon's `/v2/aggs` has no `Adj Close`-equivalent field (see
docs/massive_feasibility_investigation_2026-09-23.md §2c) -- reconstructing
one via its dividends endpoint was scoped out by this decision rather than
built, matching Market Breadth's own long-standing plain-Close convention.
This also means this module can now go through the SAME shared bars cache
(clients/shared_bars_cache.py) every other daily-bar consumer uses, instead
of its own standalone Yahoo fetch -- the only reason it avoided that cache
before (needing a dividend-adjusted column the cache never carried) no
longer applies.
"""

import logging
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from clients.shared_bars_cache import DAILY_INTERVAL, _most_recent_completed_trading_date, get_or_fetch_bars_batch
from core.db import engine
from core.models import SectorEtfReturn
from core.schemas import SectorHeatmapCellOut, SectorHeatmapOut, SectorHeatmapRowOut
from scoring.etf_returns import WINDOWS, compute_window_returns

logger = logging.getLogger(__name__)

# Fixed for this round, in display order (roughly by index weight). Names
# are the funds' own SPDR sector labels, hand-written -- ETFs are not in
# TickerScore, so there is nothing to join them from.
SECTOR_ETFS: list[tuple[str, str]] = [
    ("XLK", "Technology"),
    ("XLF", "Financials"),
    ("XLV", "Health Care"),
    ("XLE", "Energy"),
    ("XLI", "Industrials"),
    ("XLY", "Consumer Discretionary"),
    ("XLP", "Consumer Staples"),
    ("XLU", "Utilities"),
    ("XLB", "Materials"),
    ("XLRE", "Real Estate"),
    ("XLC", "Communication Services"),
]

# 1y is the longest window; 730 days (2y) leaves a full year of slack for
# the base bar's on-or-before lookup.
FETCH_LOOKBACK_DAYS = 730

# Rolling window of daily snapshots kept in SectorEtfReturn: rows whose as_of_date
# is MORE than this many days before the newest snapshot are pruned (see
# prune_sector_etf_returns). 370 (not 365) so "the same calendar date one
# year back" is still on file: a leap year adds a day, and when that date
# falls on a weekend/holiday the lookup resolves to the prior trading day,
# which can be up to 369-370 days back. Deliberately not a fetch limit -- each
# snapshot row already carries its own 1w..1y/YTD returns, computed from the
# 2y bar fetch, so retention only decides how far back a past snapshot can
# still be read.
RETENTION_DAYS = 370


def _close(frame: pd.DataFrame) -> pd.Series:
    if "close" not in frame.columns:
        raise ValueError("Bar frame has no 'close' column")
    return frame["close"]


def _resolve_anchor(closes: dict[str, pd.Series], completed_date: date) -> pd.Timestamp | None:
    """The latest bar date, across every fetched fund, that is not after the
    last COMPLETED session. Taking it from the data (rather than using the
    weekday-aware `completed_date` directly, which is not holiday-aware)
    means a market holiday anchors to the real last trading day, and the
    `<= completed_date` cap drops an in-progress/live bar."""
    cap = pd.Timestamp(completed_date)
    latest: pd.Timestamp | None = None
    for series in closes.values():
        index = series.dropna().index
        if index.tz is not None:
            index = index.tz_localize(None)
        eligible = index.normalize()[index.normalize() <= cap]
        if len(eligible) and (latest is None or eligible.max() > latest):
            latest = eligible.max()
    return latest


async def compute_and_store_sector_returns(completed_date: date | None = None) -> dict:
    """Fetches the 11 sector ETFs in one Yahoo batch, computes all 7 windows
    for each, and upserts them. Idempotent per (ticker, window, as_of_date):
    a weekend/holiday re-run re-computes the same anchor and overwrites in
    place. `completed_date` (the last completed session, default: derived
    from the clock) is a testing/manual-run seam.

    A fund Yahoo returned nothing usable for is reported in `failures` and
    keeps whatever rows it had -- the read path then shows it as blank under
    the new as_of_date instead of serving a stale number. Raises only when
    NOTHING could be computed (Yahoo down, or every frame unusable), so the
    cron heartbeat records that as a failed run rather than a "success" that
    silently left the table a night behind."""
    completed = completed_date or _most_recent_completed_trading_date()
    tickers = [t for t, _ in SECTOR_ETFS]

    histories = await get_or_fetch_bars_batch(tickers, DAILY_INTERVAL, FETCH_LOOKBACK_DAYS, auto_adjust=False)

    failures: list[tuple[str, str]] = []
    closes: dict[str, pd.Series] = {}
    for ticker in tickers:
        frame = histories.get(ticker)
        if frame is None or frame.empty:
            failures.append((ticker, "no bars returned"))
            continue
        try:
            closes[ticker] = _close(frame)
        except ValueError as exc:
            failures.append((ticker, str(exc)))

    anchor = _resolve_anchor(closes, completed)
    if anchor is None:
        raise RuntimeError(
            f"Sector heatmap: no usable bars for any of {len(tickers)} tickers on/before {completed} "
            f"(failures: {failures})"
        )

    computed_at = datetime.now()
    values = []
    for ticker, series in closes.items():
        for result in compute_window_returns(series, anchor):
            values.append(
                {
                    "ticker": ticker,
                    "return_window": result.window,
                    "as_of_date": anchor.date(),
                    "base_date": result.base_date,
                    "return_pct": result.return_pct,
                    "computed_at": computed_at,
                }
            )

    with Session(engine) as session:
        stmt = sqlite_insert(SectorEtfReturn)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "return_window", "as_of_date"],
            set_={c: getattr(stmt.excluded, c) for c in ("base_date", "return_pct", "computed_at")},
        )
        session.execute(stmt, values)
        session.commit()

    for ticker, reason in failures:
        logger.error("Sector heatmap: %s FAILED - %s", ticker, reason)

    summary = {
        "as_of_date": anchor.date().isoformat(),
        "processed": len(closes),
        "failed": len(failures),
        "failures": failures,
    }
    logger.info("Sector heatmap complete for %s: %d/%d tickers computed.", anchor.date(), summary["processed"], len(tickers))
    return summary


def get_sector_heatmap() -> SectorHeatmapOut:
    """Reads the latest persisted heatmap -- never computes live. Empty
    (as_of_date/computed_at None, rows []) before the nightly job has ever
    run, never an error."""
    windows = list(WINDOWS)
    with Session(engine) as session:
        latest = session.exec(select(SectorEtfReturn.as_of_date).order_by(SectorEtfReturn.as_of_date.desc()).limit(1)).first()
        if latest is None:
            return SectorHeatmapOut(as_of_date=None, computed_at=None, windows=windows, rows=[])
        stored = session.exec(select(SectorEtfReturn).where(SectorEtfReturn.as_of_date == latest)).all()

    by_key = {(row.ticker, row.return_window): row for row in stored}
    rows = []
    for ticker, name in SECTOR_ETFS:
        cells = {}
        for window in windows:
            row = by_key.get((ticker, window))
            cells[window] = (
                SectorHeatmapCellOut(return_pct=row.return_pct, base_date=row.base_date) if row else SectorHeatmapCellOut()
            )
        rows.append(SectorHeatmapRowOut(ticker=ticker, name=name, cells=cells))

    return SectorHeatmapOut(as_of_date=latest, computed_at=max(row.computed_at for row in stored), windows=windows, rows=rows)


def prune_sector_etf_returns(as_of: date, retention_days: int = RETENTION_DAYS) -> int:
    """Deletes SectorEtfReturn rows whose as_of_date is more than
    `retention_days` before `as_of` (a row exactly `retention_days` old is
    kept). Genuinely deleted, not cleared -- an old snapshot is a plain time
    series point with no "last known" marker worth preserving. Returns the
    number of rows deleted.

    `as_of` is the newest snapshot just written by the same run (not the
    wall clock), so a run can never prune relative to a date newer than the
    data the table holds -- and this is only ever reached after a successful
    compute_and_store_sector_returns, so a stalled/failed job never eats
    history without also writing something new."""
    cutoff = as_of - timedelta(days=retention_days)
    with Session(engine) as session:
        result = session.execute(delete(SectorEtfReturn).where(SectorEtfReturn.as_of_date < cutoff))
        session.commit()
        return result.rowcount
