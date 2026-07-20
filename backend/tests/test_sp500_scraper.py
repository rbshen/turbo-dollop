import asyncio
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import sp500_scraper
from models import IndexConstituent
from sp500_scraper import (
    ConstituentRow,
    parse_sp500_constituents,
    refresh_sp500_constituents,
    sync_sp500_constituents,
)

FIXTURE_HTML = (Path(__file__).parent / "fixtures" / "sp500_wikipedia_sample.html").read_text()


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_parses_real_wikipedia_table_structure_from_fixture():
    # Fixture is a trimmed but structurally real sample: same table id,
    # header row, and column order as the live page (confirmed live before
    # writing this fixture) -- 5 valid rows plus one deliberately malformed
    # row (fewer than 6 cells) that must be skipped, not crash the parser.
    rows = parse_sp500_constituents(FIXTURE_HTML)

    assert len(rows) == 5
    assert rows[0] == ConstituentRow(
        ticker="MMM", company_name="3M", sector="Industrials", sub_industry="Industrial Conglomerates", date_added="1957-03-04"
    )
    assert rows[3].ticker == "ABBV"
    assert rows[3].date_added == "2012-12-31"
    assert all(r.ticker != "BADROW" for r in rows)


def test_ignores_unrelated_tables_on_the_page():
    rows = parse_sp500_constituents(FIXTURE_HTML)
    assert all(r.ticker != "ignore me" for r in rows)


def test_raises_value_error_when_constituents_table_missing():
    html = "<html><body><table id='something-else'><tbody><tr><td>x</td></tr></tbody></table></body></html>"
    with pytest.raises(ValueError, match="Could not find the constituents table"):
        parse_sp500_constituents(html)


def test_raises_value_error_when_table_has_no_rows():
    html = '<html><body><table id="constituents"><tbody><tr><th>Symbol</th></tr></tbody></table></body></html>'
    with pytest.raises(ValueError, match="Parsed 0 constituent rows"):
        parse_sp500_constituents(html)


def test_sync_replaces_existing_constituents():
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(
                index_name="sp500", ticker="OLD", company_name="Stale Co", last_synced_at=__import__("datetime").datetime.now()
            )
        )
        session.commit()

        rows = [ConstituentRow(ticker="NEW", company_name="Fresh Co", sector="Tech", sub_industry="Software", date_added="2020-01-01")]
        result = sync_sp500_constituents(session, rows)

        assert result.success is True
        assert result.constituent_count == 1

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "NEW"


def test_refresh_keeps_old_list_when_fetch_fails(monkeypatch):
    # Simulated scrape failure: the network fetch itself raises. The
    # existing stored list must survive untouched, and the failure must be
    # reported, not silently swallowed into an empty/wrong list.
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(
                index_name="sp500",
                ticker="KEEP",
                company_name="Known Good Co",
                last_synced_at=__import__("datetime").datetime.now(),
            )
        )
        session.commit()

        async def failing_fetch():
            raise httpx.HTTPError("Wikipedia unreachable")

        monkeypatch.setattr(sp500_scraper, "fetch_sp500_html", failing_fetch)

        result = asyncio.run(refresh_sp500_constituents(session))

        assert result.success is False
        assert result.error is not None and "fetch failed" in result.error

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "KEEP"


def test_refresh_keeps_old_list_when_page_structure_changed(monkeypatch):
    # Simulated scrape failure: the page fetched fine, but its structure no
    # longer matches what we parse for (id="constituents" table missing).
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(
                index_name="sp500",
                ticker="KEEP",
                company_name="Known Good Co",
                last_synced_at=__import__("datetime").datetime.now(),
            )
        )
        session.commit()

        async def fetch_broken_page():
            return "<html><body><p>Wikipedia redesigned this page entirely</p></body></html>"

        monkeypatch.setattr(sp500_scraper, "fetch_sp500_html", fetch_broken_page)

        result = asyncio.run(refresh_sp500_constituents(session))

        assert result.success is False
        assert "Could not find the constituents table" in result.error

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "KEEP"


def test_refresh_keeps_old_list_when_row_count_suspiciously_low(monkeypatch):
    # A structurally valid table that parses fine but yields far fewer rows
    # than a real S&P 500 list -- e.g. Wikipedia serving a partial/cached
    # page. Must be caught by the sanity floor, not stored as-is.
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(
                index_name="sp500",
                ticker="KEEP",
                company_name="Known Good Co",
                last_synced_at=__import__("datetime").datetime.now(),
            )
        )
        session.commit()

        async def fetch_truncated_page():
            return FIXTURE_HTML  # only 5 real rows, far below MIN_EXPECTED_CONSTITUENTS

        monkeypatch.setattr(sp500_scraper, "fetch_sp500_html", fetch_truncated_page)

        result = asyncio.run(refresh_sp500_constituents(session))

        assert result.success is False
        assert "expected at least" in result.error

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "KEEP"


def test_refresh_succeeds_and_stores_rows_when_everything_is_fine(monkeypatch):
    engine = _fresh_engine()
    with Session(engine) as session:

        async def fetch_ok_page():
            return FIXTURE_HTML

        monkeypatch.setattr(sp500_scraper, "fetch_sp500_html", fetch_ok_page)
        monkeypatch.setattr(sp500_scraper, "MIN_EXPECTED_CONSTITUENTS", 3)  # fixture only has 5 rows

        result = asyncio.run(refresh_sp500_constituents(session))

        assert result.success is True
        assert result.constituent_count == 5

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
        assert len(stored) == 5
        assert {s.ticker for s in stored} == {"MMM", "AOS", "ABT", "ABBV", "ACN"}
