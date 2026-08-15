from fastapi.testclient import TestClient

import core.main as main
from core.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_fmp_status_reports_enabled_true_by_default():
    with TestClient(app) as client:
        response = client.get("/api/config/fmp-status")
    assert response.status_code == 200
    assert response.json() == {"enabled": True}


def test_fmp_status_reflects_the_flag_when_disabled(monkeypatch):
    monkeypatch.setattr(main.settings, "fmp_enabled", False)
    with TestClient(app) as client:
        response = client.get("/api/config/fmp-status")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}
