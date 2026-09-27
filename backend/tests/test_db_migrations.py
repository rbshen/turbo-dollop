"""Tests for core/db.py's small migration helpers. _add_missing_columns
has no dedicated test (implicitly exercised by every test that calls
init_db()) -- _drop_obsolete_columns gets one directly here because it
fixes a real, confirmed bug (see its own docstring): TechnicalEntrySignal's
original `fired` column was NOT NULL with no default, so simply removing
it from the model (leaving the physical column behind) broke every future
INSERT with a NOT NULL constraint violation.
"""

from datetime import datetime

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

import core.db as db_module
from core.db import _add_missing_columns, _drop_obsolete_columns
from core.models import TechnicalEntrySignal


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_module, "engine", engine)
    return engine


def test_drops_a_column_that_still_has_a_not_null_constraint(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    # The table's REAL original shape (before fired_at/stop_price existed
    # and `fired` was still NOT NULL) -- built by hand (not
    # SQLModel.metadata.create_all, which only knows the CURRENT model) to
    # reproduce the exact state a pre-existing DB would be in.
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE technicalentrysignal (
                    ticker VARCHAR NOT NULL,
                    signal_type VARCHAR NOT NULL,
                    timeframe VARCHAR NOT NULL,
                    fired BOOLEAN NOT NULL,
                    pct_b FLOAT,
                    rsi FLOAT,
                    close FLOAT,
                    source VARCHAR NOT NULL,
                    as_of DATETIME NOT NULL,
                    computed_at DATETIME NOT NULL,
                    PRIMARY KEY (ticker, signal_type, timeframe)
                )
                """
            )
        )

    # Same order init_db() itself calls these in: add the new nullable
    # columns (fired_at, stop_price) first, then drop the obsolete one.
    _add_missing_columns()
    _drop_obsolete_columns()

    # An insert that omits `fired` entirely -- exactly what the current
    # SQLModel-generated INSERT does -- must now succeed.
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(
                ticker="AAPL",
                signal_type="bb_rsi",
                timeframe="2h",
                source="fmp",
                as_of=datetime(2026, 9, 9),
                computed_at=datetime(2026, 9, 9),
            )
        )
        session.commit()


def test_is_a_no_op_when_the_column_is_already_gone(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    SQLModel.metadata.create_all(engine)  # current schema, no `fired` column at all

    _drop_obsolete_columns()  # must not raise


def test_is_a_no_op_when_the_table_does_not_exist_yet(monkeypatch):
    _fresh_engine(monkeypatch)  # no tables created at all

    _drop_obsolete_columns()  # must not raise


def test_drops_the_removed_screener_country_columns(monkeypatch):
    # Screener Country filter removal (2026-09-26): both columns must be
    # dropped from an already-populated DB, twice-run safe.
    engine = create_engine("sqlite://")
    monkeypatch.setattr(db_module, "engine", engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tickerscore (ticker TEXT PRIMARY KEY, country TEXT)"))
        conn.execute(text("CREATE TABLE savedscreenerfilter (id INTEGER PRIMARY KEY, name TEXT, country TEXT)"))
        conn.execute(text("INSERT INTO tickerscore VALUES ('AAPL', 'US')"))

    _drop_obsolete_columns()
    _drop_obsolete_columns()

    with engine.connect() as conn:
        for table in ("tickerscore", "savedscreenerfilter"):
            cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))]
            assert "country" not in cols
        assert conn.execute(text("SELECT ticker FROM tickerscore")).scalar_one() == "AAPL"


def test_drops_the_removed_tier_verified_column(monkeypatch):
    # Verified tick removal (2026-09-27): confirmed zero downstream effect
    # (never read by effective_state/effective_state_from, only ever
    # displayed) -- dropped from an already-populated DB, twice-run safe.
    engine = create_engine("sqlite://")
    monkeypatch.setattr(db_module, "engine", engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE datagroupsetting (group_key TEXT PRIMARY KEY, enabled BOOLEAN, tier_verified BOOLEAN)"
            )
        )
        conn.execute(text("INSERT INTO datagroupsetting VALUES ('fundamentals', 1, 1)"))

    _drop_obsolete_columns()
    _drop_obsolete_columns()

    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(datagroupsetting)"))]
        assert "tier_verified" not in cols
        assert conn.execute(text("SELECT group_key FROM datagroupsetting")).scalar_one() == "fundamentals"
