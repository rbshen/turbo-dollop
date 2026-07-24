"""Generic Wikipedia-table-scrape pipeline shared by every stock-index
constituent scraper (sp500_scraper.py, dow_scraper.py, ...). FMP's own
constituent endpoints are unavailable on this plan (confirmed for
sp500-constituent, dowjones-constituent and nasdaq-constituent -- all 402),
so each concrete index module supplies its own Wikipedia URL, table id, and
column layout via IndexTableConfig, and gets the same
fetch -> parse -> sanity-check -> replace pipeline sp500_scraper.py
originally had to itself.
"""

import logging
from datetime import datetime
from typing import Awaitable, Callable, NamedTuple

import httpx
from bs4 import BeautifulSoup
from sqlmodel import Session, select

from models import IndexConstituent

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


class IndexTableConfig(NamedTuple):
    """Column indices are 0-based positions into a wikitable row's <td>
    cells (header row excluded). sector_col/sub_industry_col/date_added_col
    are optional -- not every index's Wikipedia table has all three (Dow's
    table has no GICS sub-industry column, unlike S&P 500's)."""

    index_name: str
    url: str
    table_id: str
    min_cells: int
    ticker_col: int
    company_name_col: int
    sector_col: int | None = None
    sub_industry_col: int | None = None
    date_added_col: int | None = None


async def fetch_index_html(url: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FathomBot/1.0; +https://github.com/)"},
        )
        response.raise_for_status()
        return response.text


def _cell_text(cells, idx: int | None) -> str | None:
    if idx is None:
        return None
    return cells[idx].get_text(strip=True) or None


def parse_index_constituents(html: str, config: IndexTableConfig) -> list[ConstituentRow]:
    """Pure function: parses the constituents wikitable identified by
    `config.table_id`. Raises ValueError on any structural surprise (missing
    table, missing tbody, too few usable rows) -- a Wikipedia layout change
    must be a loud, caught failure here, never a silently empty or wrong
    list. Does NOT enforce the sanity floor itself -- that's the caller's
    job (refresh_index_constituents), so this stays independently testable
    against small fixture snippets."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", {"id": config.table_id})
    if table is None:
        raise ValueError(
            f'Could not find the constituents table (id="{config.table_id}") -- Wikipedia page structure may have changed.'
        )

    tbody = table.find("tbody")
    if tbody is None:
        raise ValueError("constituents table has no <tbody> -- Wikipedia page structure may have changed.")

    body_rows = tbody.find_all("tr")[1:]  # first row is the header
    rows: list[ConstituentRow] = []
    for tr in body_rows:
        # th, not just td: some tables (e.g. Dow's) mark their row-header
        # column (Company) as <th scope="row">, not <td> -- confirmed S&P
        # 500's own table uses plain <td> throughout its body rows, so this
        # is a no-op there.
        cells = tr.find_all(["th", "td"])
        if len(cells) < config.min_cells:
            continue
        ticker = cells[config.ticker_col].get_text(strip=True)
        company_name = cells[config.company_name_col].get_text(strip=True)
        if not ticker or not company_name:
            continue
        rows.append(
            ConstituentRow(
                ticker=ticker,
                company_name=company_name,
                sector=_cell_text(cells, config.sector_col),
                sub_industry=_cell_text(cells, config.sub_industry_col),
                date_added=_cell_text(cells, config.date_added_col),
            )
        )

    if not rows:
        raise ValueError("Parsed 0 constituent rows from the constituents table -- Wikipedia page structure may have changed.")

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
    config: IndexTableConfig,
    fetch_html: Callable[[], Awaitable[str]],
    min_expected_constituents: int,
    label: str,
) -> SyncResult:
    """Orchestrates fetch -> parse -> sanity-check -> store. On ANY failure
    (network error, parse error, too-few-rows sanity check), logs clearly
    and returns without touching the existing stored list -- a failed
    refresh attempt must never wipe or partially-overwrite last known-good
    data. `fetch_html`/`min_expected_constituents` are passed in rather than
    read off `config` so a caller's own module-level fetch function/
    threshold (e.g. sp500_scraper.py's fetch_sp500_html/
    MIN_EXPECTED_CONSTITUENTS, which existing tests monkeypatch directly) is
    honored without this module needing to know about that caller's
    globals."""
    try:
        html = await fetch_html()
    except httpx.HTTPError as exc:
        logger.error("%s constituent refresh failed: could not fetch Wikipedia page: %s", label, exc)
        return SyncResult(success=False, constituent_count=0, error=f"fetch failed: {exc}")

    try:
        rows = parse_index_constituents(html, config)
    except ValueError as exc:
        logger.error("%s constituent refresh failed: %s", label, exc)
        return SyncResult(success=False, constituent_count=0, error=str(exc))

    if len(rows) < min_expected_constituents:
        error = f"parsed only {len(rows)} rows, expected at least {min_expected_constituents} -- refusing to overwrite the stored list"
        logger.error("%s constituent refresh failed: %s", label, error)
        return SyncResult(success=False, constituent_count=len(rows), error=error)

    result = sync_index_constituents(session, config.index_name, rows)
    logger.info("%s constituent refresh succeeded: %d tickers stored", label, result.constituent_count)
    return result
