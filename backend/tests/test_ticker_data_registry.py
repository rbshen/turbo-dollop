"""data/ticker_data_registry.py: every table with a per-ticker key is classified (WIPE / PROTECTING / KEEP), the
deletion order is pinned, and the manual-data protection list is the registry's single list."""

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel

from core.models import FundamentalsCache

import core.db as db
import data.tracked_universe as tu
from core.models import TickerView
from data import ticker_data_registry as reg
from wipe_seed import NOW, add_protection, make_engine


@pytest.fixture
def init_db_engine(tmp_path, monkeypatch):
    """A temp DB built the way the app builds it: core.db.init_db() against a file engine, plus the model-less
    legacy tables the live DB still carries."""
    from sqlmodel import create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'init.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db, "engine", engine)
    db.init_db()
    reg.create_legacy_tables(engine)
    return engine


def test_every_table_with_a_ticker_like_column_is_classified(init_db_engine):
    assert reg.unclassified_ticker_tables(init_db_engine) == []


def test_metadata_alone_is_classified_too():
    """The model-backed tables, without init_db's extras: a new model with a ticker column must be registered."""
    missing = [t for t in reg.metadata_ticker_tables() if t not in reg.REGISTRY and not any(k[0] == t for k in reg.NOT_A_TICKER_KEY)]
    assert missing == []


def test_an_unclassified_ticker_table_fails_the_guard(init_db_engine):
    with init_db_engine.begin() as conn:
        conn.execute(text("CREATE TABLE brand_new_cache (ticker VARCHAR PRIMARY KEY, raw_json VARCHAR)"))
        conn.execute(text("CREATE TABLE symbol_notes (symbol VARCHAR PRIMARY KEY)"))
    assert reg.unclassified_ticker_tables(init_db_engine) == ["brand_new_cache.ticker", "symbol_notes.symbol"]


def test_newssentimentcache_is_registered_though_it_has_no_model(init_db_engine):
    assert "newssentimentcache" not in SQLModel.metadata.tables
    entry = reg.REGISTRY["newssentimentcache"]
    assert entry.table_class is reg.TableClass.WIPE and entry.legacy_ddl
    assert "newssentimentcache" in inspect(init_db_engine).get_table_names()
    # without the legacy DDL the guard sees nothing wrong, because the table is registered by name
    assert reg.unclassified_ticker_tables(init_db_engine) == []


def test_registry_entries_match_the_real_schema(init_db_engine):
    inspector = inspect(init_db_engine)
    for name, entry in reg.REGISTRY.items():
        assert inspector.has_table(name), name
        assert entry.key_column in {c["name"] for c in inspector.get_columns(name)}, f"{name}.{entry.key_column}"
        assert (name in SQLModel.metadata.tables) == (entry.legacy_ddl is None), name


def test_deletion_order_puts_tickerview_last_and_derived_tables_before_caches():
    names = [e.name for e in reg.WIPE_TABLES]
    assert names[-1] == TickerView.__tablename__
    assert names.index("tickerscore") < names.index("fundamentalscache") < names.index("tickerview")
    assert names.index("trendanalysis") < names.index("sharedbarscache")
    assert len(names) == len(set(names))


def test_classes_are_disjoint_and_complete():
    wipe = {e.name for e in reg.WIPE_TABLES}
    protecting = {e.name for e in reg.PROTECTING_TABLES}
    assert not wipe & protecting
    keep = {n for n, e in reg.REGISTRY.items() if e.table_class is reg.TableClass.KEEP}
    assert wipe | protecting | keep == set(reg.REGISTRY)
    assert protecting == {"indexconstituent", "watchlistticker", "tickermoat", "tickercustomvaluation", "tickerbankcapitalmetrics", "growthcatalystnote"}
    assert keep == {"sectoretfreturn", "etfmomentumsnapshot"}


def test_only_fundamentalscache_has_a_keep_predicate_and_it_names_forex_rate():
    with_predicate = {e.name: e.keep_where for e in reg.REGISTRY.values() if e.keep_where}
    assert with_predicate == {"fundamentalscache": "statement_type = 'forex_rate'"}


# --- manual data: the registry's list is the loader's list -----------------------------------------------------


def test_every_user_entered_protecting_table_feeds_load_manual_data_tickers():
    user_entered = {e.name for e in reg.PROTECTING_TABLES if e.user_entered}
    assert user_entered == {m.__tablename__ for m in reg.MANUAL_DATA_MODELS}
    # a PROTECTING table that is not user-entered is one of the two membership tables the universe reads separately
    assert {e.name for e in reg.PROTECTING_TABLES if not e.user_entered} == {"indexconstituent", "watchlistticker"}


@pytest.mark.parametrize("kind", ["moat", "custom_valuation", "bank_capital", "growth_note"])
def test_load_manual_data_tickers_includes_each_user_entered_table(kind):
    engine = make_engine()
    add_protection(engine, kind, "MANUAL1")
    with Session(engine) as session:
        assert tu.load_manual_data_tickers(session) == {"MANUAL1"}


def test_a_growth_note_keeps_a_ticker_in_the_universe_as_manual():
    engine = make_engine()
    add_protection(engine, "growth_note", "NOTED")
    with Session(engine) as session:
        session.add(FundamentalsCache(ticker="NOTED", statement_type="profile", period="latest", fetched_at=NOW, raw_json="{}"))
        session.commit()
        assert tu.classify_known_tickers(session, NOW)["NOTED"] == tu.MANUAL
