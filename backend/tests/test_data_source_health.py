from datetime import datetime, timedelta

from sqlmodel import Session

import core.data_source_health as data_source_health
from core.data_source_health import record_success
from core.models import DataSourceHealth


def test_record_success_creates_a_row_when_none_exists(_isolate_data_source_health_engine):
    engine = _isolate_data_source_health_engine
    record_success("fmp")
    with Session(engine) as session:
        row = session.get(DataSourceHealth, "fmp")
    assert row is not None
    assert (datetime.now() - row.last_success_at) < timedelta(seconds=5)


def test_record_success_updates_an_existing_row(_isolate_data_source_health_engine):
    engine = _isolate_data_source_health_engine
    old = datetime.now() - timedelta(days=3)
    with Session(engine) as session:
        session.add(DataSourceHealth(source="other", last_success_at=old))
        session.commit()

    record_success("other")

    with Session(engine) as session:
        row = session.get(DataSourceHealth, "other")
    assert row.last_success_at > old


def test_record_success_never_raises_when_the_write_itself_fails(monkeypatch):
    # Simulates the exact "disk full"-shaped failure cron_heartbeat's own
    # swallowed writes exist to tolerate -- a broken health tracker must
    # never break the real fetch it's piggybacking on.
    class _BrokenEngine:
        pass

    monkeypatch.setattr(data_source_health, "engine", _BrokenEngine())
    record_success("fmp")  # must not raise


def test_record_success_keeps_sources_independent(_isolate_data_source_health_engine):
    engine = _isolate_data_source_health_engine
    record_success("fmp")
    with Session(engine) as session:
        assert session.get(DataSourceHealth, "other") is None
