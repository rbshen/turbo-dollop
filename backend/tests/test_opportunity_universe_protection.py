"""A ticker on a list of a recent weekly opportunity run is protected from the 30-day tracked-universe expiry, so its bars keep
refreshing for later outcome tracking (data/tracked_universe.py, reason `opportunity`). Same engine convention as
test_tracked_universe.py."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.db as db
import core.main as main
import data.momentum_data as momentum_data
import data.tracked_universe as tu
from core.models import FundamentalsCache, OpportunityRun, OpportunitySnapshotRow, TickerScore, TickerView

NOW = datetime(2026, 11, 15, 12, 0)


@pytest.fixture
def engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for module in (tu, db, main, momentum_data):
        monkeypatch.setattr(module, "engine", engine)
    return engine


def _known_stock(session, ticker, idle_days=45):
    session.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=NOW, raw_json="{}"))
    session.add(TickerView(ticker=ticker, last_viewed_at=NOW - timedelta(days=idle_days)))


def _known_etf(session, ticker, idle_days=45):
    session.add(TickerScore(ticker=ticker, is_etf=True, computed_at=NOW))
    session.add(TickerView(ticker=ticker, last_viewed_at=NOW - timedelta(days=idle_days)))


def _run_with(session, tickers, as_of: date, list_name="momentum"):
    run = OpportunityRun(
        kind="weekly", as_of_date=as_of, last_bar_date=as_of, universe_size=1, rules_hash="h", rules_version="1",
        score_formula_version=6, created_at=NOW,
    )
    session.add(run)
    session.flush()
    for i, ticker in enumerate(tickers, start=1):
        session.add(OpportunitySnapshotRow(run_id=run.id, list_name=list_name, ticker=ticker, tier="momentum_only", list_order=i, rule_ids_json="[]"))
    session.commit()


def test_a_listed_ticker_is_in_the_universe_after_its_view_window_has_expired(engine):
    with Session(engine) as s:
        _known_stock(s, "LISTED")
        _known_stock(s, "UNLISTED")
        s.commit()
        _run_with(s, ["LISTED"], NOW.date() - timedelta(days=7))
        reasons = tu.classify_known_tickers(s, NOW)
        assert reasons["LISTED"] == tu.OPPORTUNITY and "LISTED" in tu.load_tracked_universe(s, NOW)
        assert reasons["UNLISTED"] == tu.EXPIRED and "UNLISTED" not in tu.load_tracked_universe(s, NOW)


def test_the_protection_ends_180_days_after_the_runs_as_of_date(engine):
    with Session(engine) as s:
        _known_stock(s, "EDGE")
        _known_stock(s, "GONE")
        s.commit()
        _run_with(s, ["EDGE"], NOW.date() - timedelta(days=tu.OPPORTUNITY_PROTECTION_DAYS), "momentum")
        _run_with(s, ["GONE"], NOW.date() - timedelta(days=tu.OPPORTUNITY_PROTECTION_DAYS + 1), "reversal")
        reasons = tu.classify_known_tickers(s, NOW)
        assert reasons["EDGE"] == tu.OPPORTUNITY and reasons["GONE"] == tu.EXPIRED


def test_either_list_protects(engine):
    with Session(engine) as s:
        _known_stock(s, "REV")
        s.commit()
        _run_with(s, ["REV"], NOW.date() - timedelta(days=1), "reversal")
        assert tu.classify_known_tickers(s, NOW)["REV"] == tu.OPPORTUNITY


def test_a_delisted_flag_still_wins(engine):
    with Session(engine) as s:
        _known_stock(s, "DEAD")
        s.add(TickerScore(ticker="DEAD", computed_at=NOW, delisted_at=NOW))
        s.commit()
        _run_with(s, ["DEAD"], NOW.date() - timedelta(days=1))
        assert tu.classify_known_tickers(s, NOW)["DEAD"] == tu.DELISTED
        assert "DEAD" not in tu.load_tracked_universe(s, NOW)


def test_an_added_ticker_keeps_its_added_reason(engine):
    with Session(engine) as s:
        _known_stock(s, "ADD")
        view = s.get(TickerView, "ADD")
        view.added_at = NOW
        s.add(view)
        s.commit()
        _run_with(s, ["ADD"], NOW.date() - timedelta(days=1))
        assert tu.classify_known_tickers(s, NOW)["ADD"] == tu.ADDED


def test_an_etf_on_a_list_stays_in_the_etf_universe(engine):
    with Session(engine) as s:
        _known_etf(s, "FUNDX")
        _known_etf(s, "FUNDY")
        s.commit()
        _run_with(s, ["FUNDX"], NOW.date() - timedelta(days=3))
        assert "FUNDX" in tu.load_etf_universe(s, NOW) and "FUNDY" not in tu.load_etf_universe(s, NOW)
        assert "FUNDX" not in tu.load_tracked_universe(s, NOW)  # the sides stay disjoint


def test_the_single_ticker_classification_agrees_with_the_bulk_one(engine):
    with Session(engine) as s:
        _known_stock(s, "LISTED")
        _known_stock(s, "UNLISTED")
        s.commit()
        _run_with(s, ["LISTED"], NOW.date() - timedelta(days=7))
        for ticker in ("LISTED", "UNLISTED"):
            assert tu.classify_one(s, ticker, NOW) == tu.classify_known_tickers(s, NOW)[ticker]


def test_the_wipe_treats_a_listed_ticker_as_protected(engine):
    with Session(engine) as s:
        _known_stock(s, "LISTED", idle_days=45)
        _known_stock(s, "PLAIN", idle_days=45)
        s.commit()
        _run_with(s, ["LISTED"], NOW.date() - timedelta(days=7))
        decisions = tu.classify_wipe_candidates(s, NOW, tickers=["LISTED", "PLAIN"])
        assert decisions["PLAIN"].decision == tu.DECISION_WIPE
        assert decisions["LISTED"].decision == tu.DECISION_PROTECTED and decisions["LISTED"].protections == (tu.PROTECTION_OPPORTUNITY,)
        assert tu.PROTECTION_OPPORTUNITY in tu.load_protection_reasons(s, "LISTED")
        assert tu.PROTECTION_OPPORTUNITY not in tu.load_protection_reasons(s, "PLAIN")
