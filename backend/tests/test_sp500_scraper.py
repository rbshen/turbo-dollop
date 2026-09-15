import asyncio
import datetime

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import scrapers.sp500_scraper as sp500_scraper
from core.models import IndexConstituent
from scrapers.sp500_scraper import (
    ConstituentRow,
    parse_sp500_constituents,
    refresh_sp500_constituents,
    sync_sp500_constituents,
)

# Small but structurally real sample -- same field names/shape as FMP's live
# /sp500-constituent response (confirmed live 2026-09-15).
SAMPLE_ROWS = [
    {
        "symbol": "MMM",
        "name": "3M",
        "sector": "Industrials",
        "subSector": "Industrial Conglomerates",
        "headQuarter": "Saint Paul, MN",
        "dateFirstAdded": "1957-03-04",
        "cik": "0000066740",
        "founded": "1902",
    },
    {
        "symbol": "AOS",
        "name": "A. O. Smith",
        "sector": "Industrials",
        "subSector": "Building Products",
        "headQuarter": "Milwaukee, WI",
        "dateFirstAdded": "2017-07-26",
        "cik": "0000091142",
        "founded": "1916",
    },
    {
        "symbol": "ABT",
        "name": "Abbott Laboratories",
        "sector": "Health Care",
        "subSector": "Health Care Equipment",
        "headQuarter": "North Chicago, IL",
        "dateFirstAdded": "1957-03-04",
        "cik": "0000001800",
        "founded": "1888",
    },
    {
        "symbol": "ABBV",
        "name": "AbbVie",
        "sector": "Health Care",
        "subSector": "Biotechnology",
        "headQuarter": "North Chicago, IL",
        "dateFirstAdded": "2012-12-31",
        "cik": "0001551152",
        "founded": "2013",
    },
    {
        "symbol": "ACN",
        "name": "Accenture",
        "sector": "Information Technology",
        "subSector": "IT Consulting & Other Services",
        "headQuarter": "Dublin, Ireland",
        "dateFirstAdded": "2011-07-06",
        "cik": "0001467373",
        "founded": "1989",
    },
]


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_parses_fmp_response_into_constituent_rows():
    rows = parse_sp500_constituents(SAMPLE_ROWS)

    assert len(rows) == 5
    assert rows[0] == ConstituentRow(
        ticker="MMM", company_name="3M", sector="Industrials", sub_industry="Industrial Conglomerates", date_added="1957-03-04"
    )
    assert rows[3].ticker == "ABBV"
    assert rows[3].date_added == "2012-12-31"


def test_parses_dot_notation_ticker_as_hyphenated():
    # FMP's own live symbol field already uses hyphen notation for
    # dual-class shares ("BRK-B"), but parse_sp500_constituents must still
    # normalize a dot-notation symbol (core.tickers.normalize_ticker) at
    # parse time, defensively, rather than assume the source never sends one.
    raw = [{"symbol": "BRK.B", "name": "Berkshire Hathaway", "sector": "Financials", "subSector": "Multi-Sector Holdings", "dateFirstAdded": "2010-02-01"}]
    rows = parse_sp500_constituents(raw)
    assert len(rows) == 1
    assert rows[0].ticker == "BRK-B"


def test_skips_rows_missing_symbol_or_name():
    raw = SAMPLE_ROWS + [
        {"symbol": "", "name": "No Symbol Co", "sector": "Tech"},
        {"symbol": "NONAME", "name": "", "sector": "Tech"},
    ]
    rows = parse_sp500_constituents(raw)
    assert len(rows) == 5
    assert all(r.ticker != "NONAME" for r in rows)


def test_raises_value_error_when_response_is_not_a_list():
    with pytest.raises(ValueError, match="was not a list"):
        parse_sp500_constituents({"Error Message": "not authorized"})


def test_raises_value_error_when_zero_usable_rows():
    with pytest.raises(ValueError, match="Parsed 0 constituent rows"):
        parse_sp500_constituents([{"symbol": "", "name": ""}])


def test_sync_replaces_existing_constituents():
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="sp500", ticker="OLD", company_name="Stale Co", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        rows = [ConstituentRow(ticker="NEW", company_name="Fresh Co", sector="Tech", sub_industry="Software", date_added="2020-01-01")]
        result = sync_sp500_constituents(session, rows)

        assert result.success is True
        assert result.constituent_count == 1

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
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
            IndexConstituent(index_name="sp500", ticker="MMM", company_name="3M", last_synced_at=datetime.datetime.now())
        )
        session.add(
            IndexConstituent(index_name="sp500", ticker="AOS", company_name="A O Smith", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        rows = [
            ConstituentRow(ticker="MMM", company_name="3M", sector="Industrials", sub_industry="Industrial Conglomerates", date_added="1957-03-04"),
            ConstituentRow(ticker="AOS", company_name="A. O. Smith", sector="Industrials", sub_industry="Building Products", date_added="2017-07-26"),
        ]
        result = sync_sp500_constituents(session, rows)

        assert result.success is True
        assert result.constituent_count == 2

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
        assert {s.ticker for s in stored} == {"MMM", "AOS"}
        assert next(s for s in stored if s.ticker == "AOS").company_name == "A. O. Smith"


def test_refresh_keeps_old_list_when_fetch_fails(monkeypatch):
    # Simulated fetch failure: the FMP call itself raises. The existing
    # stored list must survive untouched, and the failure must be
    # reported, not silently swallowed into an empty/wrong list.
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="sp500", ticker="KEEP", company_name="Known Good Co", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        async def failing_fetch():
            raise httpx.HTTPError("FMP unreachable")

        monkeypatch.setattr(sp500_scraper, "fetch_sp500_constituents", failing_fetch)

        result = asyncio.run(refresh_sp500_constituents(session))

        assert result.success is False
        assert result.error is not None and "fetch failed" in result.error

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "KEEP"


def test_refresh_keeps_old_list_when_response_shape_changed(monkeypatch):
    # Simulated fetch failure: the call succeeds, but FMP's response shape
    # no longer matches what we parse for (not a list).
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="sp500", ticker="KEEP", company_name="Known Good Co", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        async def fetch_broken_response():
            return {"Error Message": "FMP changed its response shape"}

        monkeypatch.setattr(sp500_scraper, "fetch_sp500_constituents", fetch_broken_response)

        result = asyncio.run(refresh_sp500_constituents(session))

        assert result.success is False
        assert "was not a list" in result.error

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "KEEP"


def test_refresh_keeps_old_list_when_row_count_suspiciously_low(monkeypatch):
    # A structurally valid response that parses fine but yields far fewer
    # rows than a real S&P 500 list -- e.g. FMP serving a partial response.
    # Must be caught by the sanity floor, not stored as-is.
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(index_name="sp500", ticker="KEEP", company_name="Known Good Co", last_synced_at=datetime.datetime.now())
        )
        session.commit()

        async def fetch_truncated_response():
            return SAMPLE_ROWS  # only 5 real rows, far below MIN_EXPECTED_CONSTITUENTS

        monkeypatch.setattr(sp500_scraper, "fetch_sp500_constituents", fetch_truncated_response)

        result = asyncio.run(refresh_sp500_constituents(session))

        assert result.success is False
        assert "expected at least" in result.error

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "KEEP"


def test_refresh_succeeds_and_stores_rows_when_everything_is_fine(monkeypatch):
    engine = _fresh_engine()
    with Session(engine) as session:

        async def fetch_ok_response():
            return SAMPLE_ROWS

        monkeypatch.setattr(sp500_scraper, "fetch_sp500_constituents", fetch_ok_response)
        monkeypatch.setattr(sp500_scraper, "MIN_EXPECTED_CONSTITUENTS", 3)  # sample only has 5 rows

        result = asyncio.run(refresh_sp500_constituents(session))

        assert result.success is True
        assert result.constituent_count == 5

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
        assert len(stored) == 5
        assert {s.ticker for s in stored} == {"MMM", "AOS", "ABT", "ABBV", "ACN"}
