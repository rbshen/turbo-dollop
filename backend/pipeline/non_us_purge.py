"""Shared non-US ticker detection and removal. Fathom supports US-listed tickers only (an
NYSE/NASDAQ-listed ADR counts as US; listing venue decides, not domicile -- see
core/tickers.py::is_us_listed). Two callers:

  * pipeline/stale_data_health_check.py -- the weekly safety net that removes any non-US ticker
    that got in later by mistake (search is filtered too, but a manual add or an old row can slip
    through);
  * pipeline/backfills/non_us_cleanup.py -- the one-time cleanup.

Detection reads only local data: a tracked ticker is non-US when its cached FMP /profile
`exchange` is not a US venue, or -- with no cached profile -- when its symbol is dotted (0700.HK,
MC.PA). Removal deletes the ticker's rows from EVERY table that has a `ticker` column, plus
nothing else: the ticker's shared-cache rows, scores, watchlist entries, everything.

Because a wrong exchange string would otherwise wipe real US tickers every week, the weekly caller
passes `max_fraction`: if more than that share of the tracked universe would be removed, nothing is
deleted and the run reports `refused` (the exchanges involved are logged so `US_EXCHANGES` can be
fixed).
"""

import json
import logging
from collections import Counter

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from core.models import FundamentalsCache
from core.tickers import is_us_listed
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe

logger = logging.getLogger(__name__)

# Above this share of the tracked universe, the weekly check refuses to delete anything.
DEFAULT_MAX_FRACTION = 0.02


def _cached_exchanges(session: Session, tickers: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(tickers), 400):
        stmt = select(FundamentalsCache.ticker, FundamentalsCache.raw_json).where(
            FundamentalsCache.statement_type == "profile",
            FundamentalsCache.period == "latest",
            FundamentalsCache.ticker.in_(tickers[i : i + 400]),
        )
        for ticker, raw in session.exec(stmt).all():
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue
            row = payload[0] if isinstance(payload, list) and payload else payload
            exchange = row.get("exchange") if isinstance(row, dict) else None
            if isinstance(exchange, str) and exchange.strip():
                out[ticker] = exchange
    return out


def find_non_us_tickers(session: Session) -> dict[str, str | None]:
    """{ticker: cached exchange or None} for every tracked ticker that is not US-listed."""
    tickers = sorted(load_full_tracked_universe(session))
    exchanges = _cached_exchanges(session, tickers)
    return {t: exchanges.get(t) for t in tickers if not is_us_listed(t, exchanges.get(t))}


def _ticker_tables(engine: Engine) -> list[str]:
    inspector = inspect(engine)
    return [
        name
        for name in inspector.get_table_names()
        if "ticker" in {col["name"] for col in inspector.get_columns(name)}
    ]


def purge_tickers(engine: Engine, tickers: list[str], dry_run: bool = False) -> dict[str, int]:
    """Deletes (or, under dry_run, counts) every row for `tickers` in every table with a `ticker`
    column. Returns {table: rows} for the tables that had any. Idempotent."""
    out: dict[str, int] = {}
    if not tickers:
        return out
    with engine.begin() as conn:
        for table in _ticker_tables(engine):
            total = 0
            for i in range(0, len(tickers), 200):
                chunk = tickers[i : i + 200]
                params = {f"t{j}": t for j, t in enumerate(chunk)}
                placeholders = ", ".join(f":t{j}" for j in range(len(chunk)))
                where = f'"ticker" in ({placeholders})'
                if dry_run:
                    total += conn.execute(text(f'select count(*) from "{table}" where {where}'), params).scalar_one()
                else:
                    total += conn.execute(text(f'delete from "{table}" where {where}'), params).rowcount
            if total:
                out[table] = total
    return out


def purge_non_us_tickers(
    engine: Engine, dry_run: bool = False, max_fraction: float | None = None
) -> dict:
    """Detect and remove every non-US ticker. With `max_fraction`, refuses (deletes nothing) when the
    hit list exceeds that share of the tracked universe."""
    with Session(engine) as session:
        universe_size = len(load_full_tracked_universe(session))
        found = find_non_us_tickers(session)
    result: dict = {"tickers": sorted(found), "rows": {}, "refused": False}
    if not found:
        return result
    if max_fraction is not None and universe_size and len(found) / universe_size > max_fraction:
        result["refused"] = True
        logger.error(
            "Refusing to purge %d of %d tracked tickers as non-US (> %.0f%%) -- likely an exchange-name "
            "mismatch, not real non-US tickers. Exchanges seen: %s",
            len(found),
            universe_size,
            max_fraction * 100,
            dict(Counter(found.values())),
        )
        return result
    logger.warning("%s non-US tickers: %s", "Would remove" if dry_run else "Removing", sorted(found))
    result["rows"] = purge_tickers(engine, sorted(found), dry_run=dry_run)
    return result
