import asyncio
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import scrapers.dow_scraper as dow_scraper
from models import IndexConstituent
from scrapers.dow_scraper import (
    ConstituentRow,
    parse_dow_constituents,
    refresh_dow_constituents,
    sync_dow_constituents,
)

FIXTURE_HTML = (Path(__file__).parent / "fixtures" / "dow_wikipedia_sample.html").read_text()


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_parses_real_wikipedia_table_structure_from_fixture():
    # Fixture is a trimmed but structurally real sample: same table id,
    # header row, and column order as the live page (confirmed live before
    # writing this fixture) -- including the Company column's <th
    # scope="row"> (unlike S&P 500's table, which uses plain <td>
    # throughout). 5 valid rows plus one deliberately malformed row (fewer
    # than 5 cells) that must be skipped, not crash the parser.
    rows = parse_dow_constituents(FIXTURE_HTML)

    assert len(rows) == 5
    assert rows[0] == ConstituentRow(
        ticker="MMM", company_name="3M", sector="Industrials", sub_industry=None, date_added="1976-08-09"
    )
    assert rows[1].ticker == "GOOGL"
    assert rows[1].company_name == "Alphabet"
    assert all(r.ticker != "BADEX" for r in rows)
    # No GICS sub-industry column on this table, unlike S&P 500's.
    assert all(r.sub_industry is None for r in rows)


def test_ignores_unrelated_tables_on_the_page():
    rows = parse_dow_constituents(FIXTURE_HTML)
    assert all(r.ticker != "ignore me" for r in rows)


def test_raises_value_error_when_constituents_table_missing():
    html = "<html><body><table id='something-else'><tbody><tr><td>x</td></tr></tbody></table></body></html>"
    with pytest.raises(ValueError, match="Could not find the constituents table"):
        parse_dow_constituents(html)


def test_raises_value_error_when_table_has_no_rows():
    html = '<html><body><table id="constituents"><tbody><tr><th>Company</th></tr></tbody></table></body></html>'
    with pytest.raises(ValueError, match="Parsed 0 constituent rows"):
        parse_dow_constituents(html)


def test_sync_replaces_existing_constituents():
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(
                index_name="dow", ticker="OLD", company_name="Stale Co", last_synced_at=__import__("datetime").datetime.now()
            )
        )
        session.commit()

        rows = [ConstituentRow(ticker="NEW", company_name="Fresh Co", sector="Tech", sub_industry=None, date_added="2020-01-01")]
        result = sync_dow_constituents(session, rows)

        assert result.success is True
        assert result.constituent_count == 1

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "dow")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "NEW"


def test_refresh_keeps_old_list_when_fetch_fails(monkeypatch):
    engine = _fresh_engine()
    with Session(engine) as session:
        session.add(
            IndexConstituent(
                index_name="dow",
                ticker="KEEP",
                company_name="Known Good Co",
                last_synced_at=__import__("datetime").datetime.now(),
            )
        )
        session.commit()

        async def failing_fetch():
            raise httpx.HTTPError("Wikipedia unreachable")

        monkeypatch.setattr(dow_scraper, "fetch_dow_html", failing_fetch)

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
            IndexConstituent(
                index_name="dow",
                ticker="KEEP",
                company_name="Known Good Co",
                last_synced_at=__import__("datetime").datetime.now(),
            )
        )
        session.commit()

        async def fetch_truncated_page():
            return FIXTURE_HTML  # only 5 real rows, far below MIN_EXPECTED_CONSTITUENTS

        monkeypatch.setattr(dow_scraper, "fetch_dow_html", fetch_truncated_page)

        result = asyncio.run(refresh_dow_constituents(session))

        assert result.success is False
        assert "expected at least" in result.error

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "dow")).all()
        assert len(stored) == 1
        assert stored[0].ticker == "KEEP"


def test_refresh_succeeds_and_stores_rows_when_everything_is_fine(monkeypatch):
    engine = _fresh_engine()
    with Session(engine) as session:

        async def fetch_ok_page():
            return FIXTURE_HTML

        monkeypatch.setattr(dow_scraper, "fetch_dow_html", fetch_ok_page)
        monkeypatch.setattr(dow_scraper, "MIN_EXPECTED_CONSTITUENTS", 3)  # fixture only has 5 rows

        result = asyncio.run(refresh_dow_constituents(session))

        assert result.success is True
        assert result.constituent_count == 5

        stored = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "dow")).all()
        assert len(stored) == 5
        assert {s.ticker for s in stored} == {"MMM", "GOOGL", "AXP", "AMGN", "AMZN"}
