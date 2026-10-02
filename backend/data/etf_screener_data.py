"""ETF screener read-model access (docs/specs/etf-screener.md): the write helper the ETF nightly job (not built
yet) will use, and the two reads behind GET /api/etf-screener and /api/etf-screener/meta.

Rows live in models.py::EtfScreenerRow and are read only for tickers in
data/tracked_universe.py::load_etf_universe: an expired ETF keeps its row but is not returned. The
equity-only Beta rule is applied here, at read time (the row stores FMP's raw beta).

`engine` is not used here: every function takes the caller's Session (the callers own the per-module engine
reference)."""

from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from core.models import EtfScreenerRow
from core.schemas import EtfRangeOut, EtfScreenerMeta, EtfScreenerRowOut
from core.tickers import normalize_ticker
from data.etf_data import is_equity_asset_class
from data.tracked_universe import count_hidden_inactive_etfs, load_etf_universe

# The columns an upsert may set: every EtfScreenerRow column except the key and updated_at (always stamped).
WRITABLE_FIELDS: frozenset[str] = frozenset(EtfScreenerRow.model_fields) - {"ticker", "updated_at"}

# The numeric filters GET /api/etf-screener/meta reports a min/max for.
RANGE_FIELDS: tuple[str, ...] = (
    "expense_ratio",
    "aum",
    "last_price",
    "pct_change_1d",
    "beta",
    "return_1y",
    "vs_spy_1y",
)


def upsert_etf_screener_row(session: Session, ticker: str, now: datetime | None = None, **fields) -> EtfScreenerRow:
    """Creates the ticker's row or updates the columns named in `fields`; every column not named keeps its
    stored value (the job fills a row from several sources, and one must not blank another's). A column
    passed as None is set to None on purpose. `updated_at` is always stamped. An unknown column raises
    ValueError before anything is written."""
    unknown = set(fields) - WRITABLE_FIELDS
    if unknown:
        raise ValueError(f"Unknown EtfScreenerRow column(s): {', '.join(sorted(unknown))}")
    ticker = normalize_ticker(ticker)
    values = {**fields, "updated_at": now or datetime.now()}
    stmt = sqlite_insert(EtfScreenerRow).values(ticker=ticker, **values)
    stmt = stmt.on_conflict_do_update(index_elements=["ticker"], set_=values)
    session.execute(stmt)
    session.commit()
    return session.exec(select(EtfScreenerRow).where(EtfScreenerRow.ticker == ticker)).one()


def _row_out(row: EtfScreenerRow) -> EtfScreenerRowOut:
    out = EtfScreenerRowOut(**row.model_dump())
    if not is_equity_asset_class(out.asset_class):
        out.beta = None  # a bond/commodity/alternatives fund's beta against equities means nothing (TLT: 2.4)
    return out


def list_etf_screener_rows(session: Session, now: datetime | None = None) -> list[EtfScreenerRowOut]:
    """Rows for the ETF universe only, sorted by ticker."""
    tickers = load_etf_universe(session, now)
    if not tickers:
        return []
    rows = session.exec(select(EtfScreenerRow).where(EtfScreenerRow.ticker.in_(tickers)).order_by(EtfScreenerRow.ticker)).all()
    return [_row_out(row) for row in rows]


def etf_screener_meta(session: Session, now: datetime | None = None) -> EtfScreenerMeta:
    rows = list_etf_screener_rows(session, now)
    ranges: dict[str, EtfRangeOut] = {}
    for field in RANGE_FIELDS:
        values = [v for v in (getattr(row, field) for row in rows) if v is not None]
        ranges[field] = EtfRangeOut(min=min(values) if values else None, max=max(values) if values else None)
    return EtfScreenerMeta(
        total_etfs=len(load_etf_universe(session, now)),
        row_count=len(rows),
        hidden_inactive=count_hidden_inactive_etfs(session, now),
        asset_classes=sorted({row.asset_class for row in rows if row.asset_class}),
        ranges=ranges,
    )
