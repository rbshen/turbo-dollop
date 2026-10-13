"""FastAPI's interactive docs and schema routes are off by default (ENABLE_API_DOCS re-enables them for dev)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import main
from core.config import Settings

DOC_PATHS = ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"]


@pytest.mark.parametrize("path", DOC_PATHS)
def test_live_app_serves_no_docs_routes(path):
    with TestClient(main.app) as client:
        assert client.get(path).status_code == 404


def test_live_app_has_no_docs_urls_configured():
    assert (main.app.docs_url, main.app.redoc_url, main.app.openapi_url) == (None, None, None)


def test_docs_are_off_by_default_in_settings():
    assert Settings(_env_file=None).enable_api_docs is False


def test_env_flag_turns_docs_on(monkeypatch):
    monkeypatch.setenv("ENABLE_API_DOCS", "true")
    assert Settings(_env_file=None).enable_api_docs is True


def test_api_docs_urls_enabled_serves_all_three():
    app = FastAPI(**main.api_docs_urls(True))
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_api_docs_urls_disabled_serves_none():
    app = FastAPI(**main.api_docs_urls(False))
    with TestClient(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404
