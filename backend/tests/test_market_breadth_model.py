from datetime import date, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from core.models import MarketBreadthGateLog, MarketBreadthSnapshot


def _row(universe="sp500", as_of=date(2026, 9, 18), **overrides) -> MarketBreadthSnapshot:
    fields = dict(
        universe=universe, as_of_date=as_of, computed_at=datetime(2026, 9, 21, 3, 35), constituents=503, stale_excluded=0,
        sma20_eligible=503, sma20_above=90, pct_above_sma20=17.89, sma50_eligible=503, sma50_above=140, pct_above_sma50=27.83, sma200_eligible=501, sma200_above=247, pct_above_sma200=49.30,
        hl_eligible=499, new_highs=5, new_lows=29, net_new_highs=-24,
    )
    fields.update(overrides)
    return MarketBreadthSnapshot(**fields)


def test_create_all_makes_the_table_with_a_universe_plus_date_primary_key():
    # init_db() is create_all + additive column sweeps, so a fresh table
    # needs no migration -- and its PK must be (universe, as_of_date).
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    pk = inspect(engine).get_pk_constraint("marketbreadthsnapshot")
    assert set(pk["constrained_columns"]) == {"universe", "as_of_date"}


def test_same_date_can_exist_for_two_universes_but_not_twice_for_one():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_row("sp500"))
        session.add(_row("dow"))
        session.commit()
        assert len(session.exec(select(MarketBreadthSnapshot)).all()) == 2

    with Session(engine) as session:
        session.add(_row("sp500"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_is_backfilled_defaults_false_and_percentages_are_nullable():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_row(pct_above_sma50=None, pct_above_sma200=None))
        session.commit()
        stored = session.exec(select(MarketBreadthSnapshot)).one()
    assert stored.is_backfilled is False
    assert stored.pct_above_sma50 is None and stored.pct_above_sma200 is None


def test_sma20_columns_are_nullable_and_default_to_null():
    # A row from before the 20-day metric existed carries no sma20 values --
    # NULL ("never computed"), distinct from a real 0.
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    fields = dict(
        universe="sp500", as_of_date=date(2026, 9, 18), computed_at=datetime(2026, 9, 21), constituents=503, stale_excluded=0,
        sma50_eligible=503, sma50_above=140, sma200_eligible=501, sma200_above=247, hl_eligible=499, new_highs=5, new_lows=29,
        net_new_highs=-24,
    )
    with Session(engine) as session:
        session.add(MarketBreadthSnapshot(**fields))
        session.commit()
        stored = session.exec(select(MarketBreadthSnapshot)).one()
    assert stored.sma20_eligible is None and stored.sma20_above is None and stored.pct_above_sma20 is None


def test_init_db_style_sweep_adds_the_sma20_columns_to_a_table_that_predates_them(monkeypatch):
    # The real DB's table was created before these columns existed; this is
    # the exact path core.db.init_db takes for it (additive ADD COLUMN, no
    # rebuild), and it must keep the existing rows.
    import core.db as db

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        for column in ("sma20_eligible", "sma20_above", "pct_above_sma20"):
            conn.execute(text(f"ALTER TABLE marketbreadthsnapshot DROP COLUMN {column}"))
        conn.execute(text(
            "INSERT INTO marketbreadthsnapshot (universe, as_of_date, computed_at, constituents, stale_excluded, sma50_eligible, "
            "sma50_above, pct_above_sma50, sma200_eligible, sma200_above, pct_above_sma200, hl_eligible, new_highs, new_lows, "
            "net_new_highs, is_backfilled) VALUES ('sp500', '2026-09-18', '2026-09-21 03:35:00', 503, 0, 503, 140, 27.8, 501, 247, "
            "49.3, 499, 5, 29, -24, 1)"
        ))
    assert "sma20_eligible" not in {c["name"] for c in inspect(engine).get_columns("marketbreadthsnapshot")}

    monkeypatch.setattr(db, "engine", engine)
    db._add_missing_columns()

    assert {"sma20_eligible", "sma20_above", "pct_above_sma20"} <= {c["name"] for c in inspect(engine).get_columns("marketbreadthsnapshot")}
    with Session(engine) as session:
        row = session.exec(select(MarketBreadthSnapshot)).one()
    assert row.pct_above_sma50 == 27.8 and row.sma20_eligible is None  # existing data untouched, new columns NULL


def _log(universe="sp500", as_of=date(2026, 9, 22), **overrides) -> MarketBreadthGateLog:
    fields = dict(
        universe=universe, as_of_date=as_of, checked_at=datetime(2026, 9, 22, 3, 35), constituents=20, with_bar=19, missing_count=1,
        missing_tickers_json="[\"AAA\"]", passed=True, passed_via="floor",
    )
    fields.update(overrides)
    return MarketBreadthGateLog(**fields)


def test_gate_log_is_append_only_and_allows_repeated_universe_date_pairs():
    # No UniqueConstraint -- a run history, not a dedup'd table -- so two rows for the same
    # (universe, as_of_date) (e.g. a re-checked run) can coexist rather than colliding.
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_log())
        session.add(_log())
        session.commit()
        assert len(session.exec(select(MarketBreadthGateLog)).all()) == 2


def test_gate_log_passed_via_is_nullable_for_a_refused_check():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_log(passed=False, passed_via=None, missing_count=5, missing_tickers_json="[]"))
        session.commit()
        stored = session.exec(select(MarketBreadthGateLog)).one()
    assert stored.passed is False and stored.passed_via is None
