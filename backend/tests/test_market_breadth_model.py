from datetime import date, datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from core.models import MarketBreadthSnapshot


def _row(universe="sp500", as_of=date(2026, 9, 18), **overrides) -> MarketBreadthSnapshot:
    fields = dict(
        universe=universe, as_of_date=as_of, computed_at=datetime(2026, 9, 21, 3, 35), constituents=503, stale_excluded=0,
        sma50_eligible=503, sma50_above=140, pct_above_sma50=27.83, sma200_eligible=501, sma200_above=247, pct_above_sma200=49.30,
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
