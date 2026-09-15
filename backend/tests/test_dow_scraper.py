import asyncio
import datetime

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import scrapers.dow_scraper as dow_scraper
from core.models import IndexConstituent
from scrapers.dow_scraper import (
    ConstituentRow,
    parse_dow_constituents,
    refresh_dow_constituents,
    sync_dow_constituents,
)

# Small but structurally real sample -- same field names/shape as FMP's live
# /dowjones-constituent response (confirmed live 2026-09-15). Unlike
# Wikipedia's old Dow table, FMP's response carries a real subSector value
# for every row.
SAMPLE_ROWS = [
    {
        "symbol": "MMM",
        "name": "3M",
        "sector": "Industrials",
        "subSector": "Industrial Conglomerates",
        "headQuarter": "Saint Paul, MN",
        "dateFirstAdded": "1976-08-09",
        "cik": "0000066740",
        "founded": "1902",
    },
    {
        "symbol": "GOOGL",
        "name": "Alphabet Inc.",
        "sector": "Communication Services",
        "subSector": "Internet Content & Information",
        "headQuarter": "Mountain View, CA",
        "dateFirstAdded": "2026-06-29",
        "cik": "0001652044",
        "founded": "1998",
    },
    {
        "symbol": "AXP",
        "name": "American Express",
        "sector": "Financials",
        "subSector": "Consumer Finance",
        "headQuarter": "New York, NY",
        "dateFirstAdded": "1982-08-30",
        "cik": "0000004962",
        "founded": "1850",
    },
    {
        "symbol": "AMGN",
        "name": "Amgen",
        "sector": "Health Care",
        "subSector": "Biotechnology",
        "headQuarter": "Thousand Oaks, CA",
        "dateFirstAdded": "2020-08-31",
        "cik": "0000318154",
        "founded": "1980",
    },
    {
        "symbol": "AMZN",
        "name": "Amazon",
        "sector": "Consumer Discretionary",
        "subSector": "Broadline Retail",
        "headQuarter": "Seattle, WA",
        "dateFirstAdded": "2024-02-26",
        "cik": "0001018724",
        "founded": "1994",
    },
]


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_parses_fmp_response_into_constituent_rows():
    rows = parse_dow_constituents(SAMPLE_ROWS)

    assert len(rows) == 5
    assert rows[0] == ConstituentRow(
        ticker="MMM", company_name="3M", sector="Industrials", sub_industry="Industrial Conglomerates", date_added="1976-08-09"
    )
    assert rows[1].ticker == "GOOGL"
    assert rows[1].company_name == "Alphabet Inc."
    # Unlike the old Wikipedia-based parse (no GICS sub-industry column on
    # that table), every row here carries a real subSector value.
    assert all(r.sub_industry is not None for r in rows)


def test_skips_rows_missing_symbol_or_name():
    raw = SAMPLE_ROWS + [{"symbol": "", "name": "No Symbol Co"}]
    rows = parse_dow_constituents(raw)
    assert len(rows) == 5


def test_raises_value_error_when_response_is_not_a_list():
    with pytest.raises(ValueError, match="was not a list"):
        parse_dow_constituents({"Error Message": "not authorized"})


def test_raises_value_error_when_zero_usable_rows():
    with pytest.raises(ValueError, match="Parsed 0 constituent rows"):
        parse_dow_constituents([{"symbol": "", "name": ""}])


def test_sync_replaces_existing_constituents():
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="dow", ticker="OLD", company_name="Stale Co", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        rows = [ConstituentRow(ticker="NEW", company_name="Fresh Co", sector="Tech", sub_industry="Software", date_added="2020-01-01")]
        result = sync_dow_constituents(session, rows)

        assert result.success is True
        assert result.constituent_count == 1

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "dow")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "NEW"


def test_sync_replaces_existing_constituents_when_tickers_overlap():
    # Regression test: unlike test_sync_replaces_existing_constituents
    # above (an OLD ticker fully swapped for a different NEW one), index
    # membership normally changes by only a handful of tickers -- most
    # rows in `rows` share a ticker with a row already stored. A prior bug
    # here let SQLAlchemy flush the new rows' INSERTs before the old rows'
    # DELETEs, tripping uq_index_constituent(index_name, ticker) on every
    # overlapping ticker and rolling back the whole sync.
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="dow", ticker="MMM", company_name="3M", last_synced_at=datetime.datetime.now())
        )
        session.add(
            IndexConstituent(index_name="dow", ticker="GOOGL", company_name="Alphabet", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        rows = [
            ConstituentRow(ticker="MMM", company_name="3M", sector="Industrials", sub_industry="Industrial Conglomerates", date_added="1976-08-09"),
            ConstituentRow(ticker="GOOGL", company_name="Alphabet Inc.", sector="Communication Services", sub_industry="Internet Content & Information", date_added="2026-06-29"),
        ]
        result = sync_dow_constituents(session, rows)

        assert result.success is True
        assert result.constituent_count == 2

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "dow")).all()
        assert {s.ticker for s in stored} == {"MMM", "GOOGL"}
        assert next(s for s in stored if s.ticker == "GOOGL").company_name == "Alphabet Inc."


def test_refresh_keeps_old_list_when_fetch_fails(monkeypatch):
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="dow", ticker="KEEP", company_name="Known Good Co", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        async def failing_fetch():
            raise httpx.HTTPError("FMP unreachable")

        monkeypatch.setattr(dow_scraper, "fetch_dow_constituents", failing_fetch)

        result = asyncio.run(refresh_dow_constituents(session))

        assert result.success is False
        assert result.error is not None and "fetch failed" in result.error

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "dow")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "KEEP"


def test_refresh_keeps_old_list_when_row_count_suspiciously_low(monkeypatch):
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="dow", ticker="KEEP", company_name="Known Good Co", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        async def fetch_truncated_response():
            return SAMPLE_ROWS  # only 5 real rows, far below MIN_EXPECTED_CONSTITUENTS

        monkeypatch.setattr(dow_scraper, "fetch_dow_constituents", fetch_truncated_response)

        result = asyncio.run(refresh_dow_constituents(session))

        assert result.success is False
        assert "expected at least" in result.error

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "dow")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "KEEP"


def test_refresh_succeeds_and_stores_rows_when_everything_is_fine(monkeypatch):
    engine = _fresh_engine()
    with Session(engine) as session:

        async def fetch_ok_response():
            return SAMPLE_ROWS

        monkeypatch.setattr(dow_scraper, "fetch_dow_constituents", fetch_ok_response)
        monkeypatch.setattr(dow_scraper, "MIN_EXPECTED_CONSTITUENTS", 3)  # sample only has 5 rows

        result = asyncio.run(refresh_dow_constituents(session))

        assert result.success is True
        assert result.constituent_count == 5

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "dow")).all()
        assert len(stored) == 5
        assert {s.ticker for s in stored} == {"MMM", "GOOGL", "AXP", "AMGN", "AMZN"}
