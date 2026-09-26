from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from core.models import DataSourceHealth, TechnicalEntrySignal
from datetime import datetime
from pipeline.backfills.phase6b_yahoo_cleanup import run


def _engine():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:  # the table this build removed from the models still exists in the real DB
        conn.execute(text("create table yahoopricecache (id integer primary key, ticker text)"))
        conn.execute(text("insert into yahoopricecache (ticker) values ('AAPL'), ('MSFT')"))
    with Session(engine) as session:
        now = datetime(2026, 9, 26)
        for ticker, signal_type, source in [("AAPL", "bb_rsi", "yahoo"), ("AAPL", "warren", "yahoo"), ("MSFT", "bb_rsi", "fmp")]:
            session.add(TechnicalEntrySignal(ticker=ticker, signal_type=signal_type, timeframe="2h", source=source, as_of=now, computed_at=now))
        for source in ("fmp", "massive", "yahoo"):
            session.add(DataSourceHealth(source=source, last_success_at=now))
        session.commit()
    return engine


def _state(engine):
    with engine.connect() as conn:
        sources = sorted(r[0] for r in conn.execute(text("select source from technicalentrysignal")))
        health = sorted(r[0] for r in conn.execute(text("select source from datasourcehealth")))
        has_table = conn.execute(text("select 1 from sqlite_master where name='yahoopricecache'")).first() is not None
    return sources, health, has_table


def test_dry_run_reports_and_writes_nothing():
    engine = _engine()
    assert run(engine, dry_run=True) == {
        "entry_signal_rows_rewritten": 2, "data_source_health_rows_deleted": 2, "yahoo_price_cache_rows_dropped": 2,
    }
    assert _state(engine) == (["fmp", "yahoo", "yahoo"], ["fmp", "massive", "yahoo"], True)


def test_run_rewrites_yahoo_sources_deletes_removed_health_rows_and_drops_the_table_idempotently():
    engine = _engine()
    assert run(engine)["entry_signal_rows_rewritten"] == 2
    assert _state(engine) == (["fmp", "fmp", "fmp"], ["fmp"], False)
    assert run(engine) == {"entry_signal_rows_rewritten": 0, "data_source_health_rows_deleted": 0, "yahoo_price_cache_rows_dropped": 0}
