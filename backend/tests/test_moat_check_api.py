"""GET /api/tickers/{t}/moat-check (docs/specs/moat-check.md, "API"): the newest advisory check, JSON null when never checked,
read-only. Throwaway in-memory engine patched onto core.main."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
import data.moat_check as mc
from core.models import FundamentalsCache, MoatCheck, TickerMoat, TickerScore
from tests.test_moat_check import make_record

T0 = datetime(2026, 10, 12, 10, 0)


@pytest.fixture
def engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def save(engine, ticker="PM", p1=None, p2=None, now=T0):
    with Session(engine) as session:
        return mc.append_moat_check(session, ticker, p1 or make_record(ticker=ticker), p2 or make_record(ticker=ticker), now=now).row


def get(ticker="PM"):
    with TestClient(main.app) as client:
        return client.get(f"/api/tickers/{ticker}/moat-check")


def test_a_ticker_never_checked_answers_json_null(engine):
    response = get()
    assert response.status_code == 200 and response.json() is None


def test_a_stable_row_carries_pass_1_detail_and_no_passes(engine):
    save(engine, p1=make_record(rating="wide_moat", confidence="High"), p2=make_record(rating="wide_moat", confidence="Medium"))
    body = get().json()
    assert body["ticker"] == "PM" and body["status"] == "stable" and body["rating"] == "wide_moat"
    assert body["pass1_rating"] == body["pass2_rating"] == "wide_moat"
    assert body["evidence_confidence"] == "Medium" and body["proof_basis"] == "independent" and body["threat_level"] == "Moderate"
    assert body["checked_at"] == "2026-10-12T10:00:00" and body["criteria_version"] == mc.MOAT_CRITERIA_VERSION
    assert set(body["sources_rating"]) == set(mc.SOURCE_NAMES) and body["source_facts"]["economies_of_scale"] is None
    assert body["observed_damage"][0]["counted"] == "no" and body["forward_threats"]["threats"][0]["tripwire"]["metric"] == "share"
    assert body["would_lower"] and body["would_raise"] and body["evidence_note"] is None
    assert body["pass1"] is None and body["pass2"] is None


def test_an_inconclusive_row_has_no_rating_no_detail_and_both_passes(engine):
    save(engine, p1=make_record(rating="wide_moat"), p2=make_record(rating="narrow_moat"))
    body = get().json()
    assert body["status"] == "inconclusive" and body["rating"] is None and body["evidence_confidence"] == "Low"
    assert (body["pass1_rating"], body["pass2_rating"]) == ("wide_moat", "narrow_moat")
    for key in ("threat_level", "sources_rating", "source_facts", "observed_damage", "forward_threats", "would_lower", "would_raise"):
        assert body[key] is None
    assert body["pass1"]["suggested_rating"] == "wide_moat" and body["pass2"]["suggested_rating"] == "narrow_moat"


def test_company_only_proof_comes_through_with_low_confidence(engine):
    record = make_record(confidence="High", proof="company_reported_only")
    save(engine, p1=record, p2=record)
    body = get().json()
    assert body["proof_basis"] == "company_reported_only" and body["evidence_confidence"] == "Low"


def test_the_newest_of_several_checks_is_returned(engine):
    save(engine, p1=make_record(rating="no_moat"), p2=make_record(rating="no_moat"), now=datetime(2026, 10, 1))
    save(engine, p1=make_record(rating="wide_moat"), p2=make_record(rating="wide_moat"), now=datetime(2026, 10, 9))
    save(engine, p1=make_record(rating="narrow_moat"), p2=make_record(rating="narrow_moat"), now=datetime(2026, 10, 5))
    assert get().json()["rating"] == "wide_moat"


def test_another_ticker_is_not_returned(engine):
    save(engine, "MO")
    assert get("PM").json() is None and get("MO").json()["ticker"] == "MO"


@pytest.mark.parametrize("spelling", ["pm", "Pm", " PM "])
def test_the_ticker_is_normalized(engine, spelling):
    save(engine)
    assert get(spelling.strip()).json()["ticker"] == "PM"


def test_a_dot_form_ticker_reads_the_hyphen_form(engine):
    save(engine, "BRK-B")
    assert get("BRK.B").json()["ticker"] == "BRK-B"


def test_criteria_is_current_is_false_for_another_version(engine):
    row = save(engine)
    assert get().json()["criteria_is_current"] is True
    with Session(engine) as session:
        stored = session.get(MoatCheck, row.id)
        stored.criteria_version = "moat-criteria-v5.1"
        session.add(stored)
        session.commit()
    body = get().json()
    assert body["criteria_is_current"] is False and body["criteria_version"] == "moat-criteria-v5.1"


def test_a_later_criteria_shape_does_not_break_the_read(engine):
    """The nested parts are loose on purpose: a row whose records carry keys this version never heard of still serves."""
    row = save(engine)
    with Session(engine) as session:
        stored = session.get(MoatCheck, row.id)
        stored.source_facts_json = '{"future_source": {"anything": [1, 2]}}'
        session.add(stored)
        session.commit()
    assert get().json()["source_facts"] == {"future_source": {"anything": [1, 2]}}


def test_an_etf_has_no_check_and_answers_null(engine):
    with Session(engine) as session:
        session.add(FundamentalsCache(ticker="SPY", statement_type="profile", period="latest", fetched_at=T0, raw_json='[{"isEtf": true}]'))
        session.commit()
    assert get("SPY").json() is None


def test_the_read_writes_nothing_and_touches_no_rating_or_score(engine):
    save(engine)
    with Session(engine) as session:
        session.add(TickerMoat(ticker="PM", moat="wide_moat", updated_at=T0))
        session.commit()
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split(None, 1)[0].upper())

    get()
    get("NEVERSEEN")
    assert statements and set(statements) == {"SELECT"}
    with Session(engine) as session:
        assert len(session.exec(select(MoatCheck)).all()) == 1
        assert session.get(TickerMoat, "PM").moat == "wide_moat"
        assert session.exec(select(TickerScore)).all() == []


def test_the_endpoint_calls_no_score_recompute_or_fmp():
    import inspect

    source = inspect.getsource(main.ticker_moat_check)
    assert not any(name in source for name in ("compute_ticker_score", "fmp_client", "set_ticker_moat", "await "))
