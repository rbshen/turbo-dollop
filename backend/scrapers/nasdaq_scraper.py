import logging

from sqlmodel import Session

from clients.fmp_client import fmp_client
from scrapers.index_scraper import (
    ConstituentRow,
    SyncResult,
    parse_constituent_rows,
    refresh_index_constituents,
    sync_index_constituents,
)

logger = logging.getLogger(__name__)

INDEX_NAME = "nasdaq"
# The Nasdaq-100 is nominally 100 tickers but commonly runs 101-102 due to
# dual-class share companies (e.g. GOOGL/GOOG) counting as separate
# constituents -- confirmed live 2026-09-23 at 102. A parse producing far
# fewer means FMP's response shape changed or the fetch returned something
# wrong, not a real index shrinkage (same reasoning as sp500_scraper.py's
# own tolerance).
MIN_EXPECTED_CONSTITUENTS = 95


async def fetch_nasdaq_constituents() -> list[dict]:
    return await fmp_client.get_nasdaq_constituents()


def parse_nasdaq_constituents(raw: list[dict]) -> list[ConstituentRow]:
    """Pure function: maps FMP's /nasdaq-constituent response into
    ConstituentRow -- see index_scraper.parse_constituent_rows for the
    shared implementation this delegates to. Confirmed live 2026-09-23:
    same field shape (symbol/name/sector/subSector/headQuarter/
    dateFirstAdded/cik/founded) as /sp500-constituent and
    /dowjones-constituent."""
    return parse_constituent_rows(raw, INDEX_NAME)


def sync_nasdaq_constituents(session: Session, rows: list[ConstituentRow]) -> SyncResult:
    """Replaces the stored nasdaq constituent list with `rows` -- called only
    after a successful fetch+parse+sanity-check."""
    return sync_index_constituents(session, INDEX_NAME, rows)


async def refresh_nasdaq_constituents(session: Session) -> SyncResult:
    """Orchestrates fetch -> parse -> sanity-check -> store. On ANY failure,
    logs clearly and returns without touching the existing stored list.
    References fetch_nasdaq_constituents/MIN_EXPECTED_CONSTITUENTS as bare
    module globals, mirroring sp500_scraper.py/dow_scraper.py, so tests can
    monkeypatch either directly on this module."""
    return await refresh_index_constituents(
        session, INDEX_NAME, fetch_nasdaq_constituents, MIN_EXPECTED_CONSTITUENTS, "Nasdaq-100"
    )
