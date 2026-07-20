import logging
from datetime import datetime
from typing import NamedTuple

import httpx
from bs4 import BeautifulSoup
from sqlmodel import Session, select

from models import IndexConstituent

logger = logging.getLogger(__name__)

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
INDEX_NAME = "sp500"
# The real S&P 500 is exactly 500 tickers (give or take a handful for
# dual-class share companies briefly overlapping during index changes) --
# a parse producing far fewer means the page structure changed or the
# fetch returned something wrong, not a real index shrinkage.
MIN_EXPECTED_CONSTITUENTS = 480


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


async def fetch_sp500_html() -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            WIKIPEDIA_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FathomBot/1.0; +https://github.com/)"},
        )
        response.raise_for_status()
        return response.text


def parse_sp500_constituents(html: str) -> list[ConstituentRow]:
    """Pure function: parses the "constituents" wikitable (id="constituents")
    on the S&P 500 Wikipedia page. Column order confirmed live: Symbol,
    Security, GICS Sector, GICS Sub-Industry, Headquarters Location, Date
    added, CIK, Founded.

    Raises ValueError on any structural surprise (missing table, missing
    tbody, too few usable rows) -- a Wikipedia layout change must be a loud,
    caught failure here, never a silently empty or wrong list. Does NOT
    enforce the ~500-row sanity floor itself -- that's the caller's job
    (sync_sp500_constituents), so this function stays independently
    testable against small fixture snippets.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", {"id": "constituents"})
    if table is None:
        raise ValueError('Could not find the constituents table (id="constituents") -- Wikipedia page structure may have changed.')

    tbody = table.find("tbody")
    if tbody is None:
        raise ValueError("constituents table has no <tbody> -- Wikipedia page structure may have changed.")

    body_rows = tbody.find_all("tr")[1:]  # first row is the header
    rows: list[ConstituentRow] = []
    for tr in body_rows:
        cells = tr.find_all("td")
        if len(cells) < 6:
            continue
        ticker = cells[0].get_text(strip=True)
        company_name = cells[1].get_text(strip=True)
        sector = cells[2].get_text(strip=True) or None
        sub_industry = cells[3].get_text(strip=True) or None
        date_added = cells[5].get_text(strip=True) or None
        if not ticker or not company_name:
            continue
        rows.append(
            ConstituentRow(
                ticker=ticker, company_name=company_name, sector=sector, sub_industry=sub_industry, date_added=date_added
            )
        )

    if not rows:
        raise ValueError("Parsed 0 constituent rows from the constituents table -- Wikipedia page structure may have changed.")

    return rows


def sync_sp500_constituents(session: Session, rows: list[ConstituentRow]) -> SyncResult:
    """Replaces the stored sp500 constituent list with `rows` -- called only
    after a successful fetch+parse+sanity-check. Never called with a partial
    or empty list; the caller (refresh_sp500_list.py) is responsible for
    keeping the old rows in place if anything upstream failed."""
    now = datetime.now()
    existing = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == INDEX_NAME)).all()
    for row in existing:
        session.delete(row)

    for row in rows:
        session.add(
            IndexConstituent(
                index_name=INDEX_NAME,
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


async def refresh_sp500_constituents(session: Session) -> SyncResult:
    """Orchestrates fetch -> parse -> sanity-check -> store. On ANY failure
    (network error, parse error, too-few-rows sanity check), logs clearly
    and returns without touching the existing stored list -- a failed
    refresh attempt must never wipe or partially-overwrite last known-good
    data."""
    try:
        html = await fetch_sp500_html()
    except httpx.HTTPError as exc:
        logger.error("S&P 500 constituent refresh failed: could not fetch Wikipedia page: %s", exc)
        return SyncResult(success=False, constituent_count=0, error=f"fetch failed: {exc}")

    try:
        rows = parse_sp500_constituents(html)
    except ValueError as exc:
        logger.error("S&P 500 constituent refresh failed: %s", exc)
        return SyncResult(success=False, constituent_count=0, error=str(exc))

    if len(rows) < MIN_EXPECTED_CONSTITUENTS:
        error = f"parsed only {len(rows)} rows, expected at least {MIN_EXPECTED_CONSTITUENTS} -- refusing to overwrite the stored list"
        logger.error("S&P 500 constituent refresh failed: %s", error)
        return SyncResult(success=False, constituent_count=len(rows), error=error)

    result = sync_sp500_constituents(session, rows)
    logger.info("S&P 500 constituent refresh succeeded: %d tickers stored", result.constituent_count)
    return result
