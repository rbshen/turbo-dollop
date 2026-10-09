"""The daily signal log: write one append-only row per tracked ticker (`TickerSignalSnapshot`) from the STORED `TickerScore` values, and
read a ticker's smoothed "good and undervalued since" date back. Stored values only: no recomputation, no FMP call, feeds no score.
docs/specs/stuck-check.md, "Daily snapshot log"."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from core.models import TickerScore, TickerSignalSnapshot
from core.tickers import normalize_ticker
from data.tracked_universe import load_tracked_universe
from helpers.trading_calendar import xnys_sessions
from scoring.good_undervalued import good_and_undervalued_since, is_good_and_undervalued

_CHUNK = 400  # SQLite's host-parameter limit is 999 on older builds


@dataclass(frozen=True)
class SnapshotResult:
    snapshot_date: date
    universe: int  # tracked tickers
    written: int  # new rows
    already_present: int  # the (ticker, date) row was there: left untouched
    no_score: int  # tracked but no TickerScore row yet: nothing to copy


def _chunks(items: list[str]):
    for start in range(0, len(items), _CHUNK):
        yield items[start : start + _CHUNK]


def write_daily_snapshot(session: Session, snapshot_date: date) -> SnapshotResult:
    """Idempotent: a (ticker, snapshot_date) row that exists is never updated (append-only, first write of the day wins)."""
    universe = load_tracked_universe(session)
    scores: dict[str, TickerScore] = {}
    present: set[str] = set()
    for chunk in _chunks(universe):
        for row in session.exec(select(TickerScore).where(TickerScore.ticker.in_(chunk))).all():
            scores[row.ticker] = row
        present.update(
            session.exec(
                select(TickerSignalSnapshot.ticker).where(
                    TickerSignalSnapshot.snapshot_date == snapshot_date, TickerSignalSnapshot.ticker.in_(chunk)
                )
            ).all()
        )
    new_rows = [
        {
            "ticker": t,
            "snapshot_date": snapshot_date,
            "overall_verdict": scores[t].overall_verdict,
            "valuation_verdict": scores[t].valuation_verdict,
            "weinstein_stage": scores[t].weinstein_stage,
            "good_and_undervalued": is_good_and_undervalued(scores[t].overall_verdict, scores[t].valuation_verdict),
            "score_computed_at": scores[t].computed_at,
        }
        for t in universe
        if t in scores and t not in present
    ]
    for start in range(0, len(new_rows), 200):
        # on_conflict_do_nothing: a concurrent writer for the same day cannot make this raise or overwrite.
        session.execute(
            sqlite_insert(TickerSignalSnapshot).on_conflict_do_nothing(index_elements=["ticker", "snapshot_date"]),
            new_rows[start : start + 200],
        )
    session.commit()
    return SnapshotResult(
        snapshot_date=snapshot_date,
        universe=len(universe),
        written=len(new_rows),
        already_present=len(present),
        no_score=sum(1 for t in universe if t not in scores),
    )


def good_undervalued_since_for(session: Session, ticker: str, smoothing_days: int) -> date | None:
    """The smoothed "good and undervalued since" date for `ticker` from its logged history (None when it is not in the state or has no
    history). `smoothing_days` is Settings > Why might it be stuck? > Time-stop smoothing; trading days are the NYSE sessions."""
    ticker = normalize_ticker(ticker)
    rows = session.exec(
        select(TickerSignalSnapshot.snapshot_date, TickerSignalSnapshot.good_and_undervalued).where(
            TickerSignalSnapshot.ticker == ticker
        )
    ).all()
    if not rows:
        return None
    first, last = min(d for d, _ in rows), max(d for d, _ in rows)
    sessions = {day for day, _open, _close in xnys_sessions(first, last)}
    return good_and_undervalued_since(rows, smoothing_days, sessions)
