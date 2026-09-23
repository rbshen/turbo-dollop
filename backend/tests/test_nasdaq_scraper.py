import asyncio
import datetime

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import scrapers.nasdaq_scraper as nasdaq_scraper
from core.models import IndexConstituent
from scrapers.nasdaq_scraper import (
    ConstituentRow,
    parse_nasdaq_constituents,
    refresh_nasdaq_constituents,
    sync_nasdaq_constituents,
)

# Small but structurally real sample -- same field names/shape as FMP's live
# /nasdaq-constituent response (confirmed live 2026-09-23).
SAMPLE_ROWS = [
    {
        "symbol": "ADBE",
        "name": "Adobe Inc.",
        "sector": "Technology",
        "subSector": "Software - Infrastructure",
        "headQuarter": "San Jose, CA",
        "dateFirstAdded": None,
        "cik": "0000796343",
        "founded": "1982-12-01",
    },
    {
        "symbol": "AMAT",
        "name": "Applied Materials",
        "sector": "Technology",
        "subSector": "Semiconductors",
        "headQuarter": "Santa Clara, CA",
        "dateFirstAdded": None,
        "cik": "0000006951",
        "founded": "1967-11-10",
    },
    {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "sector": "Technology",
        "subSector": "Consumer Electronics",
        "headQuarter": "Cupertino, CA",
        "dateFirstAdded": "1980-12-12",
        "cik": "0000320193",
        "founded": "1976-04-01",
    },
    {
        "symbol": "GOOGL",
        "name": "Alphabet Inc.",
        "sector": "Technology",
        "subSector": "Internet Content & Information",
        "headQuarter": "Mountain View, CA",
        "dateFirstAdded": "2004-08-19",
        "cik": "0001652044",
        "founded": "1998-09-04",
    },
    {
        "symbol": "AMZN",
        "name": "Amazon.com, Inc.",
        "sector": "Consumer Cyclical",
        "subSector": "Internet Retail",
        "headQuarter": "Seattle, WA",
        "dateFirstAdded": "1997-05-15",
        "cik": "0001018724",
        "founded": "1994-07-05",
    },
]


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_parses_fmp_response_into_constituent_rows():
    rows = parse_nasdaq_constituents(SAMPLE_ROWS)

    assert len(rows) == 5
    assert rows[0] == ConstituentRow(
        ticker="ADBE", company_name="Adobe Inc.", sector="Technology", sub_industry="Software - Infrastructure", date_added=None
    )
    assert rows[3].ticker == "GOOGL"
    assert rows[3].date_added == "2004-08-19"


def test_skips_rows_missing_symbol_or_name():
    raw = SAMPLE_ROWS + [
        {"symbol": "", "name": "No Symbol Co", "sector": "Tech"},
        {"symbol": "NONAME", "name": "", "sector": "Tech"},
    ]
    rows = parse_nasdaq_constituents(raw)
    assert len(rows) == 5
    assert all(r.ticker != "NONAME" for r in rows)


def test_raises_value_error_when_response_is_not_a_list():
    with pytest.raises(ValueError, match="was not a list"):
        parse_nasdaq_constituents({"Error Message": "not authorized"})


def test_raises_value_error_when_zero_usable_rows():
    with pytest.raises(ValueError, match="Parsed 0 constituent rows"):
        parse_nasdaq_constituents([{"symbol": "", "name": ""}])


def test_sync_replaces_existing_constituents():
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="nasdaq", ticker="OLD", company_name="Stale Co", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        rows = [ConstituentRow(ticker="NEW", company_name="Fresh Co", sector="Tech", sub_industry="Software", date_added="2020-01-01")]
        result = sync_nasdaq_constituents(session, rows)

        assert result.success is True
        assert result.constituent_count == 1

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "nasdaq")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "NEW"


def test_sync_replaces_existing_constituents_when_tickers_overlap():
    # Regression test: same class of bug covered by
    # test_sp500_scraper.py's own equivalent test -- most rows in a real
    # sync share a ticker with a row already stored, so a prior bug that
    # let SQLAlchemy flush new INSERTs before old DELETEs would trip
    # uq_index_constituent on every overlapping ticker.
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="nasdaq", ticker="ADBE", company_name="Adobe", last_synced_at=datetime.datetime.now())
        )
        session.add(
            IndexConstituent(index_name="nasdaq", ticker="AMAT", company_name="Applied Materials Inc", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        rows = [
            ConstituentRow(ticker="ADBE", company_name="Adobe Inc.", sector="Technology", sub_industry="Software - Infrastructure", date_added=None),
            ConstituentRow(ticker="AMAT", company_name="Applied Materials", sector="Technology", sub_industry="Semiconductors", date_added=None),
        ]
        result = sync_nasdaq_constituents(session, rows)

        assert result.success is True
        assert result.constituent_count == 2

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "nasdaq")).all()
        assert {s.ticker for s in stored} == {"ADBE", "AMAT"}
        assert next(s for s in stored if s.ticker == "AMAT").company_name == "Applied Materials"


def test_refresh_keeps_old_list_when_fetch_fails(monkeypatch):
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="nasdaq", ticker="KEEP", company_name="Known Good Co", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        async def failing_fetch():
            raise httpx.HTTPError("FMP unreachable")

        monkeypatch.setattr(nasdaq_scraper, "fetch_nasdaq_constituents", failing_fetch)

        result = asyncio.run(refresh_nasdaq_constituents(session))

        assert result.success is False
        assert result.error is not None and "fetch failed" in result.error

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "nasdaq")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "KEEP"


def test_refresh_keeps_old_list_when_response_shape_changed(monkeypatch):
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="nasdaq", ticker="KEEP", company_name="Known Good Co", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        async def fetch_broken_response():
            return {"Error Message": "FMP changed its response shape"}

        monkeypatch.setattr(nasdaq_scraper, "fetch_nasdaq_constituents", fetch_broken_response)

        result = asyncio.run(refresh_nasdaq_constituents(session))

        assert result.success is False
        assert "was not a list" in result.error

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "nasdaq")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "KEEP"


def test_refresh_keeps_old_list_when_row_count_suspiciously_low(monkeypatch):
    # A structurally valid response that parses fine but yields far fewer
    # rows than a real Nasdaq-100 list -- e.g. FMP serving a partial
    # response. Must be caught by the sanity floor, not stored as-is.
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="nasdaq", ticker="KEEP", company_name="Known Good Co", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        async def fetch_truncated_response():
            return SAMPLE_ROWS  # only 5 real rows, far below MIN_EXPECTED_CONSTITUENTS

        monkeypatch.setattr(nasdaq_scraper, "fetch_nasdaq_constituents", fetch_truncated_response)

        result = asyncio.run(refresh_nasdaq_constituents(session))

        assert result.success is False
        assert "expected at least" in result.error

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "nasdaq")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "KEEP"


def test_refresh_succeeds_and_stores_rows_when_everything_is_fine(monkeypatch):
    engine = _fresh_engine()
    with Session(engine) as session:

        async def fetch_ok_response():
            return SAMPLE_ROWS

        monkeypatch.setattr(nasdaq_scraper, "fetch_nasdaq_constituents", fetch_ok_response)
        monkeypatch.setattr(nasdaq_scraper, "MIN_EXPECTED_CONSTITUENTS", 3)  # sample only has 5 rows

        result = asyncio.run(refresh_nasdaq_constituents(session))

        assert result.success is True
        assert result.constituent_count == 5

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "nasdaq")).all()
        assert len(stored) == 5
        assert {s.ticker for s in stored} == {"ADBE", "AMAT", "AAPL", "GOOGL", "AMZN"}
