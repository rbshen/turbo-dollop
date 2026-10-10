"""Data-quality flags from the cache (docs/specs/data-quality.md): run the pure checks of scoring/data_quality.py over each tracked
ticker's cached statements, keep the `DataQualityFlag` table in step with them, and read it back for the Settings table and the
ticker-page note. Cache only: no FMP call, no SEC call, and nothing here feeds a score, verdict, label or TickerScore column."""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from core.models import DataQualityFlag
from core.tickers import normalize_ticker
from data.tracked_universe import load_tracked_universe, load_watchlist_tickers
from helpers.statement_view import read_cached_inputs
from helpers.ttm import clean_cash_flow_statements
from scoring.data_quality import (
    KIND_DEFINITION,
    KIND_LARGE_GAP,
    KIND_SIGN_DIFFERS,
    KIND_ZERO_BETWEEN,
    KIND_ZERO_LINE,
    KIND_ZERO_NEWEST,
    QualityFlag,
    run_checks,
)

logger = logging.getLogger(__name__)

# Ticker-page note order: the findings that change a number first, the definition effect last.
KIND_PRIORITY = {
    KIND_ZERO_LINE: 0,
    KIND_SIGN_DIFFERS: 1,
    KIND_LARGE_GAP: 2,
    KIND_ZERO_BETWEEN: 3,
    KIND_ZERO_NEWEST: 4,
    KIND_DEFINITION: 5,
}
NOTE_MAX_LINES = 3


@dataclass(frozen=True)
class SyncResult:
    universe: int  # tracked tickers
    scanned: int  # tickers whose cached statements were read
    no_data: int  # tracked but no cached annual income statement: left as they were
    errors: int  # a ticker whose check raised: left as it was
    added: int  # new open flags
    kept: int  # flags that still hold (last_seen_at moved)
    cleared: int  # flags deleted because the condition no longer holds, or the ticker left the universe

    @property
    def open_flags(self) -> int:
        return self.added + self.kept


def flags_for_ticker(session: Session, ticker: str) -> list[QualityFlag] | None:
    """The current flags for one ticker from its cached rows, or None when there is nothing cached to judge (no annual income rows)."""
    ticker = normalize_ticker(ticker)
    raw, _earnings, company_type = read_cached_inputs(session, ticker)
    if not raw.income_annual:
        return None
    cash_flow_annual, cash_flow_quarterly = clean_cash_flow_statements(
        raw.cash_flow_annual, raw.cash_flow_quarterly, raw.income_annual, raw.income_quarterly
    )
    return run_checks(ticker, company_type, raw.income_annual, cash_flow_annual, cash_flow_quarterly)


def _key(flag) -> tuple[str, str, str, str]:
    return (flag.ticker, flag.check, flag.field, flag.fiscal_year)


def sync_flags(session: Session, now: datetime | None = None) -> SyncResult:
    """Make the table equal to what holds right now, over the whole tracked universe. Idempotent: a second run changes nothing but
    `last_seen_at`. A flag that still holds keeps `found_at` and `reviewed_at` (a changed `kind` is a different finding, so it is
    un-reviewed); a flag whose condition is gone is deleted, as is any flag of a ticker that left the universe. A ticker with nothing
    cached, or whose check raised, is left exactly as it was. Commits once at the end."""
    now = now or datetime.now()
    universe = load_tracked_universe(session)
    in_universe = set(universe)
    existing: dict[tuple[str, str, str, str], DataQualityFlag] = {_key(f): f for f in session.exec(select(DataQualityFlag)).all()}
    by_ticker: dict[str, list[DataQualityFlag]] = {}
    for row in existing.values():
        by_ticker.setdefault(row.ticker, []).append(row)

    scanned = no_data = errors = added = kept = cleared = 0
    for ticker in universe:
        try:
            current = flags_for_ticker(session, ticker)
        except Exception:  # one bad cached row must not stop the sweep
            logger.exception("data quality check failed for %s", ticker)
            errors += 1
            continue
        if current is None:
            no_data += 1
            continue
        scanned += 1
        seen = set()
        for flag in current:
            key = _key(flag)
            seen.add(key)
            row = existing.get(key)
            if row is None:
                session.add(
                    DataQualityFlag(
                        ticker=flag.ticker, check=flag.check, field=flag.field, fiscal_year=flag.fiscal_year,
                        fmp_value=flag.fmp_value, comparison_value=flag.comparison_value, kind=flag.kind, detail=flag.detail,
                        found_at=now, last_seen_at=now,
                    )
                )
                added += 1
                continue
            if row.kind != flag.kind:
                row.reviewed_at = None
                row.found_at = now
            row.fmp_value, row.comparison_value, row.kind, row.detail = flag.fmp_value, flag.comparison_value, flag.kind, flag.detail
            row.last_seen_at = now
            session.add(row)
            kept += 1
        for row in by_ticker.get(ticker, []):
            if _key(row) not in seen:
                session.delete(row)
                cleared += 1
    for ticker, rows in by_ticker.items():
        if ticker not in in_universe:
            for row in rows:
                session.delete(row)
                cleared += 1
    session.commit()
    return SyncResult(len(universe), scanned, no_data, errors, added, kept, cleared)


def list_flags(session: Session, scope: str = "watchlisted", include_reviewed: bool = False) -> list[DataQualityFlag]:
    """Open flags, newest finding first. `scope` is "watchlisted" (tickers on any watchlist) or "all"."""
    query = select(DataQualityFlag)
    if not include_reviewed:
        query = query.where(DataQualityFlag.reviewed_at == None)  # noqa: E711 -- SQL IS NULL
    rows = list(session.exec(query).all())
    if scope == "watchlisted":
        watched = load_watchlist_tickers(session)
        rows = [r for r in rows if r.ticker in watched]
    return sorted(rows, key=lambda r: (-r.found_at.timestamp(), r.ticker, r.check, r.fiscal_year))


def count_open(session: Session) -> tuple[int, int]:
    """(open flags on watchlisted tickers, open flags on all tickers)."""
    rows = session.exec(select(DataQualityFlag.ticker).where(DataQualityFlag.reviewed_at == None)).all()  # noqa: E711
    watched = load_watchlist_tickers(session)
    return sum(1 for t in rows if t in watched), len(rows)


def mark_reviewed(session: Session, flag_id: int, now: datetime | None = None) -> DataQualityFlag | None:
    """Idempotent: an already-reviewed flag keeps its first `reviewed_at`. None when the id does not exist (e.g. cleared meanwhile)."""
    row = session.get(DataQualityFlag, flag_id)
    if row is None:
        return None
    if row.reviewed_at is None:
        row.reviewed_at = now or datetime.now()
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def ticker_note_flags(session: Session, ticker: str) -> list[DataQualityFlag]:
    """The ticker's open, un-reviewed flags in note order (at most one per finding), for the Financials-tab note."""
    ticker = normalize_ticker(ticker)
    rows = session.exec(
        select(DataQualityFlag).where(DataQualityFlag.ticker == ticker, DataQualityFlag.reviewed_at == None)  # noqa: E711
    ).all()
    return sorted(rows, key=lambda r: (KIND_PRIORITY.get(r.kind, 9), r.check, r.fiscal_year))
