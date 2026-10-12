"""OpportunityPick: the Opportunities page's manual Add to watchlist also records which names were chosen, for the run shown (the
latest unless a past snapshot is selected) -- insert-only, unique on (run_id, ticker), and the add itself is unchanged."""

import json
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
import data.opportunity_data as od
from core.models import OpportunityPick, OpportunityRun, OpportunitySnapshotRow, Watchlist, WatchlistTicker

NOW = datetime(2026, 10, 12, 9, 0)


@pytest.fixture
def engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(od, "engine", engine)
    async def no_etf_rows(tickers):  # the ETF-card best effort would reach FMP
        return None
    monkeypatch.setattr(main, "ensure_etf_screener_rows", no_etf_rows)
    with Session(engine) as s:
        s.add(Watchlist(id=1, name="Picks", created_at=NOW, updated_at=NOW))
        for run_id, as_of, tickers in ((1, date(2026, 10, 2), ("AAA", "BBB", "OLDONLY")), (2, date(2026, 10, 9), ("AAA", "BBB", "CCC"))):
            s.add(OpportunityRun(id=run_id, kind="weekly", as_of_date=as_of, last_bar_date=as_of, universe_size=1, rules_hash="h", rules_version="2",
                                 score_formula_version=6, created_at=NOW, summary_json=json.dumps({})))
            for i, t in enumerate(tickers, 1):
                s.add(OpportunitySnapshotRow(run_id=run_id, list_name="momentum", ticker=t, tier="quality", list_order=i, rule_ids_json="[]"))
        s.commit()
    return engine


def picks(engine) -> list[tuple[int, str, str]]:
    with Session(engine) as s:
        return sorted((p.run_id, p.ticker, p.source) for p in s.exec(select(OpportunityPick)).all())


def members(engine) -> list[str]:
    with Session(engine) as s:
        return sorted(r.ticker for r in s.exec(select(WatchlistTicker)).all())


def post_one(client, ticker, run_id=None):
    body = {"ticker": ticker}
    if run_id is not None:
        body["opportunity_run_id"] = run_id
    return client.post("/api/watchlists/1/tickers", json=body)


def post_bulk(client, tickers, run_id=None):
    body = {"tickers": tickers}
    if run_id is not None:
        body["opportunity_run_id"] = run_id
    return client.post("/api/watchlists/1/tickers/bulk", json=body)


def test_a_single_add_from_the_page_records_the_pick_for_the_run_shown(engine):
    with TestClient(main.app) as client:
        assert post_one(client, "AAA", run_id=2).status_code == 201
    assert members(engine) == ["AAA"] and picks(engine) == [(2, "AAA", "opportunities_page")]


def test_a_multi_add_records_every_submitted_ticker(engine):
    with TestClient(main.app) as client:
        response = post_bulk(client, ["AAA", "BBB", "CCC"], run_id=2)
    assert response.status_code == 200 and response.json() == {"added": 3, "already_present": 0}
    assert picks(engine) == [(2, t, "opportunities_page") for t in ("AAA", "BBB", "CCC")]


def test_adding_the_same_ticker_again_is_a_no_op_for_the_pick(engine):
    with TestClient(main.app) as client:
        post_bulk(client, ["AAA", "BBB"], run_id=2)
        first = picks(engine)
        again = post_bulk(client, ["AAA", "BBB"], run_id=2)  # both already on the list
        assert again.json() == {"added": 0, "already_present": 2}
        post_bulk(client, ["AAA", "CCC"], run_id=2)  # one old pick, one new
    assert picks(engine)[:2] == first and len(picks(engine)) == 3
    with Session(engine) as s:
        assert len(s.exec(select(OpportunityPick).where(OpportunityPick.ticker == "AAA")).all()) == 1


def test_a_single_re_add_is_refused_as_before_and_records_nothing_new(engine):
    with TestClient(main.app) as client:
        assert post_one(client, "AAA", run_id=2).status_code == 201
        assert post_one(client, "AAA", run_id=2).status_code == 409  # unchanged behaviour
    assert picks(engine) == [(2, "AAA", "opportunities_page")]


def test_a_past_snapshot_records_the_pick_against_that_run(engine):
    with TestClient(main.app) as client:
        post_bulk(client, ["AAA", "OLDONLY"], run_id=1)
        post_one(client, "BBB", run_id=2)
    assert picks(engine) == [(1, "AAA", "opportunities_page"), (1, "OLDONLY", "opportunities_page"), (2, "BBB", "opportunities_page")]


def test_the_same_ticker_can_be_picked_from_two_different_runs(engine):
    with TestClient(main.app) as client:
        post_one(client, "AAA", run_id=1)
        post_bulk(client, ["AAA"], run_id=2)
    assert picks(engine) == [(1, "AAA", "opportunities_page"), (2, "AAA", "opportunities_page")]


def test_an_add_without_a_run_id_records_nothing(engine):
    with TestClient(main.app) as client:
        post_one(client, "AAA")
        post_bulk(client, ["BBB", "CCC"])
    assert members(engine) == ["AAA", "BBB", "CCC"] and picks(engine) == []


def test_a_ticker_the_run_never_listed_or_an_unknown_run_is_ignored_and_the_add_still_works(engine):
    with TestClient(main.app) as client:
        assert post_bulk(client, ["AAA", "ZZZZ"], run_id=2).json()["added"] == 2  # ZZZZ is not a row of run 2
        assert post_one(client, "BBB", run_id=999).status_code == 201  # no such run
    assert members(engine) == ["AAA", "BBB", "ZZZZ"] and picks(engine) == [(2, "AAA", "opportunities_page")]


def test_a_failing_pick_write_never_fails_the_add(engine, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db is unhappy")

    monkeypatch.setattr(OpportunityPick, "__init__", boom)
    with TestClient(main.app) as client:
        assert post_one(client, "AAA", run_id=2).status_code == 201
    assert members(engine) == ["AAA"]


def test_a_refused_add_records_no_pick(engine):
    with Session(engine) as s:
        s.add(Watchlist(id=2, name="ETF", created_at=NOW, updated_at=NOW))
        s.commit()
    with TestClient(main.app) as client:  # the ETF-only list refuses a stock (400)
        response = client.post("/api/watchlists/2/tickers/bulk", json={"tickers": ["AAA"], "opportunity_run_id": 2})
    assert response.status_code == 400 and picks(engine) == []


def test_the_database_enforces_one_pick_per_run_and_ticker(engine):
    with Session(engine) as s:
        s.add(OpportunityPick(run_id=2, ticker="AAA", picked_at=NOW, source="opportunities_page"))
        s.commit()
        s.add(OpportunityPick(run_id=2, ticker="AAA", picked_at=NOW, source="opportunities_page"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_record_picks_is_idempotent_and_returns_the_new_count(engine):
    with Session(engine) as s:
        assert od.record_picks(s, 2, ["AAA", "BBB"], now=NOW) == 2
        assert od.record_picks(s, 2, ["AAA", "BBB", "CCC"], now=NOW) == 1
        assert od.record_picks(s, 2, ["AAA"], now=NOW) == 0
        assert od.record_picks(s, None, ["AAA"], now=NOW) == 0 and od.record_picks(s, 2, [], now=NOW) == 0
