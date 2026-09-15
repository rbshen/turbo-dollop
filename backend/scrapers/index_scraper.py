"""Generic FMP-backed constituent-list pipeline shared by every stock-index
constituent module (sp500_scraper.py, dow_scraper.py, ...). FMP Ultimate now
serves its own /sp500-constituent and /dowjones-constituent endpoints
(confirmed live 2026-09-15 -- previously 402 on this plan, which is why this
pipeline originally scraped Wikipedia's own constituent tables via httpx +
BeautifulSoup; see git history for that implementation). Each concrete index
module supplies its own FMP-fetch callable and index_name, and gets the same
fetch -> parse -> sanity-check -> replace pipeline sp500_scraper.py
originally had to itself.
"""

import logging
from datetime import datetime
from typing import Awaitable, Callable, NamedTuple

import httpx
from sqlmodel import Session, select

from core.models import IndexConstituent
from core.tickers import normalize_ticker

logger = logging.getLogger(__name__)


class ConstituentRow(NamedTuple):
    ticker: str
    company_name: str
    sector: str | None
    sub_industry: str | None
    date_added: str | None


class SyncResult(NamedTuple):
    success: bool
    constituent_count: int
    error: str | None


def parse_constituent_rows(raw: list[dict] | dict, index_name: str) -> list[ConstituentRow]:
    """Pure function: maps FMP's /sp500-constituent or /dowjones-constituent
    response (a flat list of dicts -- symbol/name/sector/subSector/
    dateFirstAdded/cik/founded, confirmed live 2026-09-15) into
    ConstituentRow. Raises ValueError on any structural surprise (not a
    list, or zero usable rows) -- an FMP response-shape change must be a
    loud, caught failure here, never a silently empty or wrong list. Does
    NOT enforce the sanity floor itself -- that's the caller's job
    (refresh_index_constituents), so this stays independently testable
    against small fixture payloads."""
    if not isinstance(raw, list):
        raise ValueError(f"{index_name} constituent response was not a list -- FMP response shape may have changed.")

    rows: list[ConstituentRow] = []
    for entry in raw:
        symbol = (entry.get("symbol") or "").strip()
        name = (entry.get("name") or "").strip()
        if not symbol or not name:
            continue
        rows.append(
            ConstituentRow(
                ticker=normalize_ticker(symbol),
                company_name=name,
                sector=entry.get("sector") or None,
                sub_industry=entry.get("subSector") or None,
                date_added=entry.get("dateFirstAdded") or None,
            )
        )

    if not rows:
        raise ValueError(
            f"Parsed 0 constituent rows from the {index_name} FMP response -- FMP response shape may have changed."
        )

    return rows


def sync_index_constituents(session: Session, index_name: str, rows: list[ConstituentRow]) -> SyncResult:
    """Replaces the stored constituent list for `index_name` with `rows` --
    called only after a successful fetch+parse+sanity-check. Never called
    with a partial or empty list; the caller is responsible for keeping the
    old rows in place if anything upstream failed."""
    now = datetime.now()
    existing = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == index_name)).all()
    for row in existing:
        session.delete(row)
    # Without this, SQLAlchemy's flush ordering issues INSERTs for the new
    # rows before the DELETEs above are actually sent, tripping
    # uq_index_constituent whenever a ticker (the common case -- index
    # membership rarely changes) appears in both the old and new lists.
    session.flush()

    for row in rows:
        session.add(
            IndexConstituent(
                index_name=index_name,
                ticker=row.ticker,
                company_name=row.company_name,
                sector=row.sector,
                sub_industry=row.sub_industry,
                date_added=row.date_added,
                last_synced_at=now,
            )
        )
    session.commit()
    return SyncResult(success=True, constituent_count=len(rows), error=None)


async def refresh_index_constituents(
    session: Session,
    index_name: str,
    fetch_constituents: Callable[[], Awaitable[list[dict] | dict]],
    min_expected_constituents: int,
    label: str,
) -> SyncResult:
    """Orchestrates fetch -> parse -> sanity-check -> store. On ANY failure
    (network/FMP error, parse error, too-few-rows sanity check), logs
    clearly and returns without touching the existing stored list -- a
    failed refresh attempt must never wipe or partially-overwrite last
    known-good data. `fetch_constituents`/`min_expected_constituents` are
    passed in rather than read off a shared config so a caller's own
    module-level fetch function/threshold (e.g. sp500_scraper.py's
    fetch_sp500_constituents/MIN_EXPECTED_CONSTITUENTS, which existing
    tests monkeypatch directly) is honored without this module needing to
    know about that caller's globals.

    Catching httpx.HTTPError here also catches FMPDisabledError (a
    subclass -- see clients/fmp_client.py) as a defense-in-depth safety
    net, but the primary FMP-disabled handling lives one layer up, in each
    refresh_*_list.py script's own early-return guard -- see that guard's
    own comment for why a disabled run must never reach this failure path
    at all (it needs to read as a clean skip, not a failed sync)."""
    try:
        raw = await fetch_constituents()
    except httpx.HTTPError as exc:
        logger.error("%s constituent refresh failed: could not fetch from FMP: %s", label, exc)
        return SyncResult(success=False, constituent_count=0, error=f"fetch failed: {exc}")

    try:
        rows = parse_constituent_rows(raw, index_name)
    except ValueError as exc:
        logger.error("%s constituent refresh failed: %s", label, exc)
        return SyncResult(success=False, constituent_count=0, error=str(exc))

    if len(rows) < min_expected_constituents:
        error = f"parsed only {len(rows)} rows, expected at least {min_expected_constituents} -- refusing to overwrite the stored list"
        logger.error("%s constituent refresh failed: %s", label, error)
        return SyncResult(success=False, constituent_count=len(rows), error=error)

    result = sync_index_constituents(session, index_name, rows)
    logger.info("%s constituent refresh succeeded: %d tickers stored", label, result.constituent_count)
    return result
