import logging

from sqlmodel import Session

from scrapers.index_scraper import (
    ConstituentRow,
    IndexTableConfig,
    SyncResult,
    fetch_index_html,
    parse_index_constituents,
    refresh_index_constituents,
    sync_index_constituents,
)

logger = logging.getLogger(__name__)

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
INDEX_NAME = "sp500"
# The real S&P 500 is exactly 500 tickers (give or take a handful for
# dual-class share companies briefly overlapping during index changes) --
# a parse producing far fewer means the page structure changed or the
# fetch returned something wrong, not a real index shrinkage.
MIN_EXPECTED_CONSTITUENTS = 480

# Column order confirmed live: Symbol, Security, GICS Sector, GICS
# Sub-Industry, Headquarters Location, Date added, CIK, Founded.
_CONFIG = IndexTableConfig(
    index_name=INDEX_NAME,
    url=WIKIPEDIA_URL,
    table_id="constituents",
    min_cells=6,
    ticker_col=0,
    company_name_col=1,
    sector_col=2,
    sub_industry_col=3,
    date_added_col=5,
)


async def fetch_sp500_html() -> str:
    return await fetch_index_html(WIKIPEDIA_URL)


def parse_sp500_constituents(html: str) -> list[ConstituentRow]:
    """Pure function: parses the "constituents" wikitable (id="constituents")
    on the S&P 500 Wikipedia page -- see index_scraper.parse_index_constituents
    for the shared implementation this delegates to."""
    return parse_index_constituents(html, _CONFIG)


def sync_sp500_constituents(session: Session, rows: list[ConstituentRow]) -> SyncResult:
    """Replaces the stored sp500 constituent list with `rows` -- called only
    after a successful fetch+parse+sanity-check."""
    return sync_index_constituents(session, INDEX_NAME, rows)


async def refresh_sp500_constituents(session: Session) -> SyncResult:
    """Orchestrates fetch -> parse -> sanity-check -> store. On ANY failure,
    logs clearly and returns without touching the existing stored list.
    References fetch_sp500_html/MIN_EXPECTED_CONSTITUENTS as bare module
    globals (not values captured into _CONFIG) so tests can monkeypatch
    either directly on this module."""
    return await refresh_index_constituents(session, _CONFIG, fetch_sp500_html, MIN_EXPECTED_CONSTITUENTS, "S&P 500")
