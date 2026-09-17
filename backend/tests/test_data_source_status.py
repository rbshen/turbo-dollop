from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from core.data_source_status import _status_for, get_data_source_health
from core.main import app
from core.models import DataSourceHealth


def _seed(engine, source: str, age: timedelta) -> None:
    with Session(engine) as session:
        session.add(DataSourceHealth(source=source, last_success_at=datetime.now() - age))
        session.commit()


def test_status_for_disabled_is_disabled_or_failing():
    assert _status_for(False, datetime.now(), datetime.now()) == "disabled_or_failing"


def test_status_for_no_last_success_is_disabled_or_failing():
    assert _status_for(True, None, datetime.now()) == "disabled_or_failing"


def test_status_for_recent_success_is_healthy():
    now = datetime.now()
    assert _status_for(True, now - timedelta(hours=1), now) == "healthy"


def test_status_for_moderately_stale_success_is_stale():
    now = datetime.now()
    assert _status_for(True, now - timedelta(hours=48), now) == "stale"


def test_status_for_very_stale_success_is_disabled_or_failing():
    now = datetime.now()
    assert _status_for(True, now - timedelta(days=10), now) == "disabled_or_failing"


def test_get_data_source_health_reflects_fmp_enabled_flag(monkeypatch, _isolate_data_source_health_engine):
    import core.data_source_status as data_source_status

    monkeypatch.setattr(data_source_status.settings, "fmp_enabled", False)
    result = get_data_source_health()
    fmp = next(s for s in result.sources if s.source == "fmp")
    assert fmp.enabled is False
    assert fmp.status == "disabled_or_failing"


def test_get_data_source_health_yahoo_has_no_kill_switch(monkeypatch, _isolate_data_source_health_engine):
    engine = _isolate_data_source_health_engine
    _seed(engine, "yahoo", timedelta(minutes=5))
    result = get_data_source_health()
    yahoo = next(s for s in result.sources if s.source == "yahoo")
    assert yahoo.enabled is True
    assert yahoo.status == "healthy"


def test_data_source_health_endpoint_returns_both_sources(monkeypatch, _isolate_data_source_health_engine):
    engine = _isolate_data_source_health_engine
    _seed(engine, "fmp", timedelta(minutes=5))
    _seed(engine, "yahoo", timedelta(minutes=5))
    with TestClient(app) as client:
        response = client.get("/api/config/data-source-health")
    assert response.status_code == 200
    body = response.json()
    assert {s["source"] for s in body["sources"]} == {"fmp", "yahoo"}
