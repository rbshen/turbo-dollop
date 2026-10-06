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


# --- SavedScreenerFilter.kind: the one-time table rebuild (2026-10-02) ---------------------------------

_OLD_SAVED_FILTER_DDL = """
CREATE TABLE savedscreenerfilter (
    id INTEGER NOT NULL,
    name VARCHAR NOT NULL,
    universe VARCHAR NOT NULL,
    sort_field VARCHAR NOT NULL,
    sort_direction VARCHAR NOT NULL,
    filters_json VARCHAR NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL, "watchlist_id" INTEGER,
    PRIMARY KEY (id),
    CONSTRAINT uq_saved_screener_filter_name UNIQUE (name)
)
"""


def _old_saved_filter_db(monkeypatch):
    """The live table's real pre-`kind` shape (UNIQUE(name) as a table constraint), with 3 rows."""
    engine = _fresh_engine(monkeypatch)
    with engine.begin() as conn:
        conn.execute(text(_OLD_SAVED_FILTER_DDL))
        conn.execute(text("CREATE INDEX ix_savedscreenerfilter_name ON savedscreenerfilter (name)"))
        for id_, name, watchlist_id in ((5, "No Moat >SPY", None), (8, "Wide All", 7), (9, "Narrow All", None)):
            conn.execute(
                text(
                    "INSERT INTO savedscreenerfilter (id, name, universe, sort_field, sort_direction, filters_json,"
                    " created_at, updated_at, watchlist_id) VALUES (:id, :n, 'all', 'overall_score', 'desc', '{\"x\": 1}',"
                    " '2026-09-01 10:00:00', '2026-09-02 11:00:00', :w)"
                ),
                {"id": id_, "n": name, "w": watchlist_id},
            )
    return engine


def _saved_rows(engine):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id, name, kind, watchlist_id, filters_json, created_at, updated_at FROM savedscreenerfilter ORDER BY id")
        ).fetchall()


def test_the_rebuild_keeps_every_existing_view_as_a_stock_view(monkeypatch):
    engine = _old_saved_filter_db(monkeypatch)

    assert db_module._migrate_saved_filter_kind() is True

    assert _saved_rows(engine) == [
        (5, "No Moat >SPY", "stock", None, '{"x": 1}', "2026-09-01 10:00:00", "2026-09-02 11:00:00"),
        (8, "Wide All", "stock", 7, '{"x": 1}', "2026-09-01 10:00:00", "2026-09-02 11:00:00"),
        (9, "Narrow All", "stock", None, '{"x": 1}', "2026-09-01 10:00:00", "2026-09-02 11:00:00"),
    ]
    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        index_names = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
    assert "savedscreenerfilter_old" not in tables
    assert "ix_savedscreenerfilter_name" in index_names


def test_after_the_rebuild_a_name_is_unique_per_kind_not_globally(monkeypatch):
    engine = _old_saved_filter_db(monkeypatch)
    db_module._migrate_saved_filter_kind()

    from data.saved_screener_filters import get_saved_filter, upsert_saved_filter

    with Session(engine) as session:
        kwargs = dict(universe="all", sort_field="aum", sort_direction="asc", filters_json="{}")
        upsert_saved_filter(session, name="Wide All", kind="etf", **kwargs)  # same name as a stock view
        upsert_saved_filter(session, name="Wide All", **kwargs)  # updates the stock one in place (no new row)
        assert get_saved_filter(session, "Wide All", "etf").sort_field == "aum"
        assert get_saved_filter(session, "Wide All").id == 8  # the original row, updated
        assert get_saved_filter(session, "Wide All").sort_field == "aum"


def test_the_rebuild_is_idempotent_and_leaves_a_fresh_database_alone(monkeypatch):
    engine = _old_saved_filter_db(monkeypatch)
    assert db_module._migrate_saved_filter_kind() is True
    before = _saved_rows(engine)
    assert db_module._migrate_saved_filter_kind() is False
    assert _saved_rows(engine) == before

    fresh = _fresh_engine(monkeypatch)
    SQLModel.metadata.create_all(fresh)  # a new install gets the per-kind constraint straight from the model
    assert db_module._migrate_saved_filter_kind() is False


def test_the_rebuild_does_nothing_when_the_table_does_not_exist(monkeypatch):
    _fresh_engine(monkeypatch)
    assert db_module._migrate_saved_filter_kind() is False


def test_a_failure_mid_rebuild_rolls_back_to_the_untouched_old_table(monkeypatch):
    engine = _old_saved_filter_db(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(db_module.SavedScreenerFilter.__table__, "create", boom)
    try:
        db_module._migrate_saved_filter_kind()
    except RuntimeError:
        pass
    else:
        raise AssertionError("the failure should propagate")

    with engine.connect() as conn:
        ddl = conn.execute(text("SELECT sql FROM sqlite_master WHERE name = 'savedscreenerfilter'")).scalar()
        names = [r[0] for r in conn.execute(text("SELECT name FROM savedscreenerfilter ORDER BY id"))]
        leftover = conn.execute(text("SELECT name FROM sqlite_master WHERE name = 'savedscreenerfilter_old'")).first()
    assert "uq_saved_screener_filter_name UNIQUE (name)" in ddl  # the original table, unchanged
    assert names == ["No Moat >SPY", "Wide All", "Narrow All"]
    assert leftover is None


def test_init_db_rebuilds_then_adds_the_etf_table(monkeypatch):
    engine = _old_saved_filter_db(monkeypatch)
    db_module.init_db()
    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert "etfscreenerrow" in tables
    assert [r[2] for r in _saved_rows(engine)] == ["stock", "stock", "stock"]


def test_an_old_tickerview_table_gains_the_added_columns_and_keeps_its_rows(monkeypatch):
    """Opt-in universe step 2: TickerView gained nullable added_at / added_source. The live table was created with
    only (ticker, last_viewed_at): the add-missing-columns sweep must add both, leave every existing row untouched
    (NULL in the new columns) and be a no-op the second time."""
    engine = _fresh_engine(monkeypatch)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tickerview (ticker VARCHAR NOT NULL, last_viewed_at DATETIME NOT NULL, PRIMARY KEY (ticker))"))
        conn.execute(text("INSERT INTO tickerview VALUES ('AAPL', '2026-10-02 07:00:52.930737'), ('QQQ', '2026-10-03 02:16:16.264082')"))

    _add_missing_columns()
    _add_missing_columns()  # idempotent

    with engine.connect() as conn:
        columns = {row[1]: row[2] for row in conn.execute(text("PRAGMA table_info(tickerview)"))}
        rows = conn.execute(text("SELECT ticker, last_viewed_at, added_at, added_source FROM tickerview ORDER BY ticker")).all()
    assert columns == {"ticker": "VARCHAR", "last_viewed_at": "DATETIME", "added_at": "DATETIME", "added_source": "VARCHAR"}
    assert rows == [("AAPL", "2026-10-02 07:00:52.930737", None, None), ("QQQ", "2026-10-03 02:16:16.264082", None, None)]


def test_an_old_tickerscore_table_gains_the_four_review_columns_and_keeps_its_rows(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tickerscore (ticker VARCHAR NOT NULL, overall_score INTEGER, overall_verdict VARCHAR, computed_at DATETIME NOT NULL, PRIMARY KEY (ticker))"))
        conn.execute(text("INSERT INTO tickerscore VALUES ('AAPL', 76, 'Pass', '2026-10-05 02:00:00')"))

    _add_missing_columns()
    _add_missing_columns()  # idempotent

    with engine.connect() as conn:
        columns = {row[1]: row[2] for row in conn.execute(text("PRAGMA table_info(tickerscore)"))}
        row = conn.execute(text("SELECT ticker, overall_verdict, review_status, review_reasons, conviction, data_quality_flags FROM tickerscore")).one()
    assert {"review_status", "review_reasons", "conviction", "data_quality_flags"} <= set(columns)
    assert tuple(row) == ("AAPL", "Pass", None, None, None, None)
