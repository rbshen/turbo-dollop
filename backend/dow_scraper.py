import logging

from sqlmodel import Session

from index_scraper import (
    ConstituentRow,
    IndexTableConfig,
    SyncResult,
    fetch_index_html,
    parse_index_constituents,
    refresh_index_constituents,
    sync_index_constituents,
)

logger = logging.getLogger(__name__)

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"
INDEX_NAME = "dow"
# The Dow is fixed at exactly 30 tickers -- unlike the S&P 500's "give or
# take a handful" tolerance, a parse producing meaningfully fewer than 30
# always means the page structure changed or the fetch returned something
# wrong, never a real index change (any single addition/removal is a
# same-day swap, not a shrinkage).
MIN_EXPECTED_CONSTITUENTS = 28

# Column order confirmed live: Company, Exchange, Symbol, Sector, Date
# added, Notes, Index weighting. Unlike S&P 500's table, the Company column
# is a <th scope="row">, not a <td> -- index_scraper.parse_index_constituents
# already selects both. No GICS sub-industry column on this table.
_CONFIG = IndexTableConfig(
    index_name=INDEX_NAME,
    url=WIKIPEDIA_URL,
    table_id="constituents",
    min_cells=5,
    ticker_col=2,
    company_name_col=0,
    sector_col=3,
    sub_industry_col=None,
    date_added_col=4,
)


async def fetch_dow_html() -> str:
    return await fetch_index_html(WIKIPEDIA_URL)


def parse_dow_constituents(html: str) -> list[ConstituentRow]:
    """Pure function: parses the "constituents" wikitable (id="constituents")
    on the Dow Jones Industrial Average Wikipedia page -- see
    index_scraper.parse_index_constituents for the shared implementation
    this delegates to."""
    return parse_index_constituents(html, _CONFIG)


def sync_dow_constituents(session: Session, rows: list[ConstituentRow]) -> SyncResult:
    """Replaces the stored dow constituent list with `rows` -- called only
    after a successful fetch+parse+sanity-check."""
    return sync_index_constituents(session, INDEX_NAME, rows)


async def refresh_dow_constituents(session: Session) -> SyncResult:
    """Orchestrates fetch -> parse -> sanity-check -> store. On ANY failure,
    logs clearly and returns without touching the existing stored list.
    References fetch_dow_html/MIN_EXPECTED_CONSTITUENTS as bare module
    globals (not values captured into _CONFIG), mirroring sp500_scraper.py,
    so tests can monkeypatch either directly on this module."""
    return await refresh_index_constituents(session, _CONFIG, fetch_dow_html, MIN_EXPECTED_CONSTITUENTS, "Dow Jones")
