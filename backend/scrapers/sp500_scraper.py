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

INDEX_NAME = "sp500"
# The real S&P 500 is exactly 500 tickers (give or take a handful for
# dual-class share companies briefly overlapping during index changes) --
# a parse producing far fewer means FMP's response shape changed or the
# fetch returned something wrong, not a real index shrinkage.
MIN_EXPECTED_CONSTITUENTS = 480


async def fetch_sp500_constituents() -> list[dict]:
    return await fmp_client.get_sp500_constituents()


def parse_sp500_constituents(raw: list[dict]) -> list[ConstituentRow]:
    """Pure function: maps FMP's /sp500-constituent response into
    ConstituentRow -- see index_scraper.parse_constituent_rows for the
    shared implementation this delegates to."""
    return parse_constituent_rows(raw, INDEX_NAME)


def sync_sp500_constituents(session: Session, rows: list[ConstituentRow]) -> SyncResult:
    """Replaces the stored sp500 constituent list with `rows` -- called only
    after a successful fetch+parse+sanity-check."""
    return sync_index_constituents(session, INDEX_NAME, rows)


async def refresh_sp500_constituents(session: Session) -> SyncResult:
    """Orchestrates fetch -> parse -> sanity-check -> store. On ANY failure,
    logs clearly and returns without touching the existing stored list.
    References fetch_sp500_constituents/MIN_EXPECTED_CONSTITUENTS as bare
    module globals (not values captured into a shared config) so tests can
    monkeypatch either directly on this module."""
    return await refresh_index_constituents(
        session, INDEX_NAME, fetch_sp500_constituents, MIN_EXPECTED_CONSTITUENTS, "S&P 500"
    )
