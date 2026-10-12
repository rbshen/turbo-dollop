"""OpportunityPick: the Opportunities page's manual Add to watchlist also records which names were chosen, for the run shown (the
latest unless a past snapshot is selected), stored under that run's as_of_date -- insert-only, unique on (as_of_date, ticker), never
deleted by anything (--force, removing a ticker, deleting the watchlist, the ticker leaving the universe), and the add itself is unchanged."""

import json
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.db as db_module
import core.main as main
import data.opportunity_data as od
from core.models import (
    OpportunityPick,
    OpportunityRun,
    OpportunitySnapshotRow,
    TickerScore,
    Watchlist,
    WatchlistTicker,
)

NOW = datetime(2026, 10, 12, 9, 0)
OLD, NEW = date(2026, 10, 2), date(2026, 10, 9)


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
        for run_id, as_of, tickers in ((1, OLD, ("AAA", "BBB", "OLDONLY")), (2, NEW, ("AAA", "BBB", "CCC"))):
            s.add(OpportunityRun(id=run_id, kind="weekly", as_of_date=as_of, last_bar_date=as_of, universe_size=1, rules_hash="h", rules_version="2",
                                 score_formula_version=6, created_at=NOW, summary_json=json.dumps({})))
            for i, t in enumerate(tickers, 1):
                s.add(OpportunitySnapshotRow(run_id=run_id, list_name="momentum", ticker=t, tier="quality", list_order=i, rule_ids_json="[]"))
        s.commit()
    return engine


def picks(engine) -> list[tuple[date, str, str]]:
    with Session(engine) as s:
        return sorted((p.as_of_date, p.ticker, p.source) for p in s.exec(select(OpportunityPick)).all())


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


# --- recording ---------------------------------------------------------------------------------------------------------------


def test_a_single_add_from_the_page_records_the_pick_under_the_runs_as_of_date(engine):
    with TestClient(main.app) as client:
        assert post_one(client, "AAA", run_id=2).status_code == 201
    assert members(engine) == ["AAA"] and picks(engine) == [(NEW, "AAA", "opportunities_page")]


def test_a_multi_add_records_only_the_submitted_tickers_that_are_rows_of_the_shown_run(engine):
    with TestClient(main.app) as client:
        response = post_bulk(client, ["AAA", "OLDONLY", "ZZZZ", "CCC"], run_id=2)  # OLDONLY is a row of the OTHER run, ZZZZ of none
    assert response.status_code == 200 and response.json() == {"added": 4, "already_present": 0}  # the add itself takes all four
    assert picks(engine) == [(NEW, "AAA", "opportunities_page"), (NEW, "CCC", "opportunities_page")]


def test_selecting_a_past_snapshot_records_that_snapshots_as_of_date(engine):
    with TestClient(main.app) as client:
        post_bulk(client, ["AAA", "OLDONLY"], run_id=1)
        post_one(client, "BBB", run_id=2)
    assert picks(engine) == [(OLD, "AAA", "opportunities_page"), (OLD, "OLDONLY", "opportunities_page"), (NEW, "BBB", "opportunities_page")]


def test_the_same_ticker_picked_twice_for_the_same_as_of_date_is_a_no_op(engine):
    with TestClient(main.app) as client:
        post_bulk(client, ["AAA", "BBB"], run_id=2)
        first = picks(engine)
        again = post_bulk(client, ["AAA", "BBB"], run_id=2)  # both already on the list
        assert again.json() == {"added": 0, "already_present": 2}
        post_bulk(client, ["AAA", "CCC"], run_id=2)  # one old pick, one new
    assert picks(engine)[:2] == first and len(picks(engine)) == 3
    with Session(engine) as s:
        assert len(s.exec(select(OpportunityPick).where(OpportunityPick.ticker == "AAA")).all()) == 1
    with Session(engine) as s:  # a later attempt neither duplicates the pick nor moves its first picked_at
        assert od.record_picks(s, 2, ["AAA"], now=datetime(2027, 1, 1)) == 0
        assert s.exec(select(OpportunityPick).where(OpportunityPick.ticker == "AAA")).one().picked_at != datetime(2027, 1, 1)


def test_the_same_ticker_picked_from_two_different_as_of_dates_gives_two_picks(engine):
    with TestClient(main.app) as client:
        post_one(client, "AAA", run_id=1)
        post_bulk(client, ["AAA"], run_id=2)
    assert picks(engine) == [(OLD, "AAA", "opportunities_page"), (NEW, "AAA", "opportunities_page")]


def test_a_single_add_that_is_refused_with_409_records_nothing(engine):
    with TestClient(main.app) as client:
        assert post_one(client, "AAA").status_code == 201  # already on the list, added outside the page
        assert post_one(client, "AAA", run_id=2).status_code == 409  # unchanged behaviour
    assert picks(engine) == []


def test_an_add_without_a_run_id_records_nothing(engine):
    with TestClient(main.app) as client:
        post_one(client, "AAA")
        post_bulk(client, ["BBB", "CCC"])
    assert members(engine) == ["AAA", "BBB", "CCC"] and picks(engine) == []


def test_an_unknown_run_is_ignored_and_the_add_still_works(engine):
    with TestClient(main.app) as client:
        assert post_one(client, "BBB", run_id=999).status_code == 201
    assert members(engine) == ["BBB"] and picks(engine) == []


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


def test_the_database_enforces_one_pick_per_as_of_date_and_ticker(engine):
    with Session(engine) as s:
        s.add(OpportunityPick(as_of_date=NEW, ticker="AAA", picked_at=NOW, source="opportunities_page"))
        s.commit()
        s.add(OpportunityPick(as_of_date=NEW, ticker="AAA", picked_at=NOW, source="opportunities_page"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_record_picks_is_idempotent_and_returns_the_new_count(engine):
    with Session(engine) as s:
        assert od.record_picks(s, 2, ["AAA", "BBB"], now=NOW) == 2
        assert od.record_picks(s, 2, ["AAA", "BBB", "CCC"], now=NOW) == 1
        assert od.record_picks(s, 2, ["AAA"], now=NOW) == 0
        assert od.record_picks(s, None, ["AAA"], now=NOW) == 0 and od.record_picks(s, 2, [], now=NOW) == 0


# --- nothing deletes a pick ------------------------------------------------------------------------------------------------------


def _picked(engine, client):
    assert post_bulk(client, ["AAA", "BBB"], run_id=2).status_code == 200
    return picks(engine)


def test_a_pick_survives_removing_the_ticker_from_the_watchlist(engine):
    with TestClient(main.app) as client:
        before = _picked(engine, client)
        assert client.delete("/api/watchlists/1/tickers/AAA").status_code == 204
    assert members(engine) == ["BBB"] and picks(engine) == before


def test_a_pick_survives_deleting_the_entire_watchlist(engine):
    with TestClient(main.app) as client:
        before = _picked(engine, client)
        assert client.delete("/api/watchlists/1").status_code in (200, 204)
    with Session(engine) as s:
        assert s.get(Watchlist, 1) is None
    assert picks(engine) == before


def test_a_pick_survives_the_ticker_leaving_the_universe(engine):
    from data.ticker_data_registry import WIPE_TABLES
    from pipeline import wipe_untouched_tickers as wipe

    with TestClient(main.app) as client:
        before = _picked(engine, client)
    with Session(engine) as s:  # the delisted flag removes a ticker from every nightly job...
        s.add(TickerScore(ticker="AAA", company_name="AAA", delisted_at=NOW, computed_at=NOW))
        s.commit()
    present = set(inspect(engine).get_table_names())  # the real job also skips tables the file does not have
    with engine.begin() as conn:  # ...and the wipe deletes the ticker's rows from every WIPE table, in registry order
        for entry in WIPE_TABLES:
            if entry.name in present:
                wipe._delete_rows(conn, entry, "AAA")
    with Session(engine) as s:
        assert s.get(TickerScore, "AAA") is None  # the wipe really ran for AAA
    assert picks(engine) == before


def test_a_pick_survives_a_rebuilt_run_and_a_deleted_run(engine):
    with TestClient(main.app) as client:
        before = _picked(engine, client)
    with Session(engine) as s:  # the run (and its rows) is gone entirely; the pick is kept as is
        for row in s.exec(select(OpportunitySnapshotRow)).all():
            s.delete(row)
        for run in s.exec(select(OpportunityRun)).all():
            s.delete(run)
        s.commit()
    assert picks(engine) == before


# --- the migration from the run_id key ----------------------------------------------------------------------------------------------


def _legacy_engine(monkeypatch, picks_rows, runs):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE opportunitypick"))
        conn.execute(text(
            "CREATE TABLE opportunitypick (id INTEGER NOT NULL, run_id INTEGER NOT NULL, ticker VARCHAR NOT NULL, picked_at DATETIME NOT NULL, "
            "source VARCHAR NOT NULL, PRIMARY KEY (id), CONSTRAINT uq_opportunity_pick UNIQUE (run_id, ticker))"
        ))
        conn.execute(text("CREATE INDEX ix_opportunitypick_run_id ON opportunitypick (run_id)"))
        conn.execute(text("CREATE INDEX ix_opportunitypick_ticker ON opportunitypick (ticker)"))
    with Session(engine) as s:
        for run_id, as_of in runs:
            s.add(OpportunityRun(id=run_id, kind="weekly", as_of_date=as_of, last_bar_date=as_of, universe_size=1, rules_hash="h", rules_version="2",
                                 score_formula_version=6, created_at=NOW))
        s.commit()
    with engine.begin() as conn:
        for i, (run_id, ticker) in enumerate(picks_rows, 1):
            conn.execute(text("INSERT INTO opportunitypick VALUES (:i, :r, :t, '2026-10-11 10:00:00', 'opportunities_page')"), {"i": i, "r": run_id, "t": ticker})
    return engine


def test_the_run_id_keyed_table_is_rebuilt_with_every_pick_kept(monkeypatch):
    engine = _legacy_engine(monkeypatch, [(1, "AAA"), (1, "BBB"), (2, "AAA")], [(1, OLD), (2, NEW)])
    assert db_module._migrate_opportunity_pick_key() is True
    with Session(engine) as s:
        rows = sorted((p.id, p.as_of_date, p.ticker, p.source) for p in s.exec(select(OpportunityPick)).all())
        assert rows == [(1, OLD, "AAA", "opportunities_page"), (2, OLD, "BBB", "opportunities_page"), (3, NEW, "AAA", "opportunities_page")]
        s.add(OpportunityPick(as_of_date=OLD, ticker="AAA", picked_at=NOW, source="opportunities_page"))
        with pytest.raises(IntegrityError):  # the new key is in force
            s.commit()
    with engine.begin() as conn:
        assert "run_id" not in {r[1] for r in conn.execute(text("PRAGMA table_info(opportunitypick)"))}
        assert not conn.execute(text("SELECT 1 FROM sqlite_master WHERE name LIKE 'opportunitypick_%'")).first()  # no leftover table
    assert db_module._migrate_opportunity_pick_key() is False  # idempotent


def test_a_pick_whose_run_is_gone_is_never_dropped_by_the_migration(monkeypatch):
    engine = _legacy_engine(monkeypatch, [(1, "AAA"), (7, "GONE")], [(1, OLD)])
    db_module._migrate_opportunity_pick_key()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT ticker FROM opportunitypick_unmapped ORDER BY id")).scalars().all() == ["AAA", "GONE"]
        assert conn.execute(text("SELECT ticker FROM opportunitypick")).scalars().all() == ["AAA"]


def test_an_empty_legacy_table_is_simply_recreated(monkeypatch):
    engine = _legacy_engine(monkeypatch, [], [])
    assert db_module._migrate_opportunity_pick_key() is True
    with Session(engine) as s:
        assert s.exec(select(OpportunityPick)).all() == []
