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

INDEX_NAME = "dow"
# The Dow is fixed at exactly 30 tickers -- unlike the S&P 500's "give or
# take a handful" tolerance, a parse producing meaningfully fewer than 30
# always means FMP's response shape changed or the fetch returned something
# wrong, never a real index change (any single addition/removal is a
# same-day swap, not a shrinkage).
MIN_EXPECTED_CONSTITUENTS = 28


async def fetch_dow_constituents() -> list[dict]:
    return await fmp_client.get_dowjones_constituents()


def parse_dow_constituents(raw: list[dict]) -> list[ConstituentRow]:
    """Pure function: maps FMP's /dowjones-constituent response into
    ConstituentRow -- see index_scraper.parse_constituent_rows for the
    shared implementation this delegates to. Unlike the old Wikipedia table
    (which had no GICS sub-industry column for the Dow), FMP's response
    does carry a real subSector value for every row."""
    return parse_constituent_rows(raw, INDEX_NAME)


def sync_dow_constituents(session: Session, rows: list[ConstituentRow]) -> SyncResult:
    """Replaces the stored dow constituent list with `rows` -- called only
    after a successful fetch+parse+sanity-check."""
    return sync_index_constituents(session, INDEX_NAME, rows)


async def refresh_dow_constituents(session: Session) -> SyncResult:
    """Orchestrates fetch -> parse -> sanity-check -> store. On ANY failure,
    logs clearly and returns without touching the existing stored list.
    References fetch_dow_constituents/MIN_EXPECTED_CONSTITUENTS as bare
    module globals, mirroring sp500_scraper.py, so tests can monkeypatch
    either directly on this module."""
    return await refresh_index_constituents(
        session, INDEX_NAME, fetch_dow_constituents, MIN_EXPECTED_CONSTITUENTS, "Dow Jones"
    )
